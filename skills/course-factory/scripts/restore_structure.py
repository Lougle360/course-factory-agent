# -*- coding: utf-8 -*-
"""L1.5 结构还原：把无结构的派生全书文本，按章节标题切成语义块。

背景：MarkItDown 转换本书后 H1/H2/H3 全为 0、无 Markdown 层级，
导致 L1 切出的 1939 个碎片 heading_path 全空、粒度退化到句子级（中位 32 字）。
本脚本用「章节标题串 + 出现位置规则」从纯文本里还原结构。

用法：
    python restore_structure.py <派生md> <输出json> [--pattern 正则] [--gap N]
    python restore_structure.py <派生md> <输出json> --report   # 只体检不写文件

退出码：0 = 健康（仅有警告也算健康）；1 = 结构还原失败（章节数不足 / 顺序异常）
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

# 默认判据：中文书「第X章 标题」
DEFAULT_PATTERN = r'^(第[一二三四五六七八九十百]+章)\s*[　 ]*([^\n]{0,40})$'

# 相邻章节标题相距不超过多少行，即视为同一「密集簇」（目录页／书末索引）
DEFAULT_GAP = 6

CN = '一二三四五六七八九十'


def load_chapters(lines, pattern):
    """找出全书章节标题及其所有出现位置。"""
    rx = re.compile(pattern)
    hits = []
    for i, line in enumerate(lines):
        m = rx.match(line.strip())
        if m:
            grp = m.groups()
            chapter = grp[0]
            name = grp[1].strip() if len(grp) > 1 and grp[1] else ''
            hits.append((i, chapter, name))
    return hits


def pick_body_starts(hits, lines, gap):
    """每个章节出现多次（目录区／正文起始／书末索引区），取真正的正文起始。

    判据：目录区与索引区的标题是「密集连排」（相邻标题间隔几行），
    而正文区里相邻章节相隔数百行。因此先把所有标题位置按距离聚簇，
    落在密集簇里的都是目录/索引，剩下的孤立位置即正文起始。

    这比「看下一行是不是标题」可靠：目录最后一项后面接的是"后记"而非
    章节标题，朴素判据会漏；聚簇判据不受这种边界影响。
    """
    all_positions = sorted({lineno for lineno, _, _ in hits})

    # 1. 聚簇：相邻标题间隔 <= gap 行视为同一密集簇（目录/索引）
    clusters = []
    for pos in all_positions:
        if clusters and pos - clusters[-1][-1] <= gap:
            clusters[-1].append(pos)
        else:
            clusters.append([pos])
    dense = {p for cl in clusters if len(cl) >= 2 for p in cl}

    # 2. 每个章节选正文起始：优先孤立位置；若全在密集簇内则回退取最长内容
    by_title = {}
    for lineno, ch, name in hits:
        by_title.setdefault(ch, []).append((lineno, name))

    starts = []
    for ch, occ in by_title.items():
        isolated = [(l, n) for l, n in occ if l not in dense]
        pool = isolated if isolated else occ
        scored = []
        for lineno, name in pool:
            after = '\n'.join(lines[lineno + 1: lineno + 41])
            scored.append((len(re.sub(r'\s', '', after)), lineno, name))
        scored.sort(key=lambda x: (-x[0], x[1]))
        _, lineno, name = scored[0]
        starts.append((ch, name, lineno))

    # 3. 按中文序数还原章节顺序（不受标题被误定位的影响）
    def order(item):
        inner = item[0].strip('第章')
        idx = CN.find(inner[0]) if inner else -1
        return (idx if idx >= 0 else 99, item[2])
    starts.sort(key=order)
    return starts


def slice_blocks(lines, starts, total_lines):
    blocks = []
    for idx, (ch, name, lineno) in enumerate(starts):
        end = starts[idx + 1][2] if idx + 1 < len(starts) else total_lines
        body = '\n'.join(lines[lineno: end]).strip()
        clean = re.sub(r'\n{3,}', '\n\n', body)
        blocks.append({
            'chapter': ch,
            'title': f'{ch} {name}'.strip(),
            'start_line': lineno,
            'end_line': end,
            'chars': len(re.sub(r'\s', '', clean)),
            'text': clean,
        })
    return blocks


def health_check(blocks):
    """结构健康度后置校验。

    为什么不改上游：kb-builder 的 MarkItDown 遇到损坏 PDF 会静默降级为纯文本
    而不报错（其单测因此失败）。与其改上游源码，不如在这一层盯住结果。
    """
    issues = []
    if len(blocks) < 2:
        issues.append(('FATAL', f'只还原出 {len(blocks)} 个章节块，判据可能不适用于该素材'))

    # 起始行必须单调递增
    for a, b in zip(blocks, blocks[1:]):
        if b['start_line'] <= a['start_line']:
            issues.append(('FATAL', f"{b['chapter']} 起始行 {b['start_line']} 未晚于 {a['chapter']}（{a['start_line']}），章节顺序异常"))

    # 空章节 / 过短章节
    for b in blocks:
        if b['chars'] < 200:
            issues.append(('FATAL', f"{b['chapter']} 只有 {b['chars']} 字，疑似定位到了目录行而非正文"))
        elif b['chars'] < 1000:
            issues.append(('WARN', f"{b['chapter']} 仅 {b['chars']} 字，远低于其他章节，建议抽查"))

    # 字数离散度：极差过大说明有章节把别人吃进去了
    if len(blocks) >= 3:
        sizes = [b['chars'] for b in blocks]
        avg = sum(sizes) / len(sizes)
        for b in blocks:
            if avg and b['chars'] > avg * 5:
                issues.append(('WARN', f"{b['chapter']} {b['chars']} 字，是均值的 {b['chars']/avg:.1f} 倍，疑把后续章节吞并"))
    return issues


def main():
    ap = argparse.ArgumentParser(description='L1.5 结构还原：无结构文本 → 章节块')
    ap.add_argument('src', help='派生 md（MarkItDown 等转换产物）')
    ap.add_argument('out_json', help='输出 chapters.json 路径')
    ap.add_argument('--pattern', default=DEFAULT_PATTERN,
                    help='章节标题正则，须含两个分组：(章节号)(标题)')
    ap.add_argument('--gap', type=int, default=DEFAULT_GAP,
                    help=f'相邻标题间隔≤{DEFAULT_GAP}行视为同一密集簇（目录/索引）')
    ap.add_argument('--report', action='store_true', help='只体检，不写文件')
    args = ap.parse_args()

    if not Path(args.src).exists():
        print(f'[FATAL] 源文件不存在：{args.src}')
        sys.exit(1)

    text = io.open(args.src, encoding='utf-8').read()
    lines = text.split('\n')
    hits = load_chapters(lines, args.pattern)
    if not hits:
        print('[FATAL] 未匹配到任何章节标题 —— 请换 --pattern，或素材本身非分章结构')
        sys.exit(1)

    starts = pick_body_starts(hits, lines, args.gap)
    blocks = slice_blocks(lines, starts, len(lines))

    print(f'派生文本：{len(lines)} 行 / {len(text)} 字符')
    print(f'章节标题出现：{len(hits)} 次 → 还原出 {len(blocks)} 个章节块')
    print()
    print(f"{'章节':<8} {'起始行':>7} {'字数':>8}   {'标题'}")
    print('-' * 62)
    for b in blocks:
        print(f"{b['chapter']:<9}{b['start_line']:>7} {b['chars']:>8}   {b['title'][:34]}")
    total = sum(b['chars'] for b in blocks)
    print('-' * 62)
    print(f"{'合计':<9}{'':>7} {total:>8}   平均每章 {total // max(len(blocks),1)} 字")

    issues = health_check(blocks)
    print('\n结构健康度校验：')
    if not issues:
        print('  ✅ 无异常')
    for level, msg in issues:
        print(f"  {'❌' if level == 'FATAL' else '⚠️ '} [{level}] {msg}")

    fatal = [x for x in issues if x[0] == 'FATAL']
    if fatal:
        print(f'\n[FATAL] 结构还原失败：{len(fatal)} 项致命问题，不得进入 Stage 2')
        sys.exit(1)

    if args.report:
        print('\n--report 模式：未写出文件')
        sys.exit(0)

    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    io.open(args.out_json, 'w', encoding='utf-8').write(
        json.dumps(blocks, ensure_ascii=False, indent=1))
    print(f'\n已写出：{args.out_json}')


if __name__ == '__main__':
    main()
