# -*- coding: utf-8 -*-
"""组件候选定位器（L2 编排层 · Stage 1）

职责边界（重要）：
  本脚本**只做定位**，不做摘录。
  输出 = 位置信息 + 信号强度 + 信号类型，不含任何原文片段。
  真正的语义判定（这一段到底是不是 misconception）由 AI 读原文后完成，
  且判定结果以「概括」写入交付物，不复制原文。

  这个边界来自版权约束——受版权保护的材料，交付物里只能有
  「某章某段可支撑某组件」的定位信息 + 概括性表述。

用法：
  python locate_component_candidates.py <chapters.json> <out.json> [--top N]
"""
import io
import json
import re
import sys


# ---------------------------------------------------------------- 信号词典
# 每个信号对应 taxonomy-v2 的一类或多类受控类型（course 已被 profile 排除）
# 格式：(信号名, 正则, 指向的候选类型, 权重)
# 权重说明：`？` 在中文书里几乎每段都有，判定力弱 → 低权重；
#        「不是…而是」式对照、引号对话、编号列举判定力强 → 高权重。
SIGNALS = [
    ('dialogue',     re.compile(r'[\u201c\u201d\u201c\u201d][^\u201c\u201d\u201c\u201d]{6,80}[\u201c\u201d\u201c\u201d]'), 'case', 3),
    ('contrast',     re.compile(r'(不是.{0,12}而是|并非.{0,12}而是|而不是|我们常常.{0,10}却|常常误以为|容易混淆)'), 'misconception', 4),
    ('should',       re.compile(r'(应该|应当|我们需要|我们可以|建议|避免|不要|试着|不妨|重要的是)'), 'guideline', 2),
    ('enumerate',    re.compile(r'(第[一二三四五六七八九十][、，]|首先.{0,8}其次|一方面.{0,10}另一方面|[①②③④⑤⑥])'), 'framework,workflow', 4),
    ('explain',      re.compile(r'(也就是|换句话说|这意味着|之所以|原因在于|是因为|在于)'), 'principle', 2),
    ('define',       re.compile(r'(是指|指的是|所谓|定义为|包含.{0,6}(要素|部分|步骤)|被称为)'), 'concept', 4),
    ('question',     re.compile(r'？'), 'misconception,scene', 1),   # 弱信号，仅作辅助
    ('exercise',     re.compile(r'(练习|试试看|请写下|邀请你|留意一下|回想一下|请你|花点时间|问问自己)'), 'exercise', 5),
    ('boundary_neg', re.compile(r'(不等同|并不意味着|不能代替|不应被|拒绝|警惕|小心|危险|误区|切记)'), 'boundary,misconception', 3),
]

# 体裁噪声：这些形式为诗/歌/索引，不应被当作知识组件原料
NOISE = [
    ('poem',   re.compile(r'^\s*.{2,18}$')),      # 极短行（可能是诗）
    ('index',  re.compile(r'^[\d\s\.\-]+$')),     # 纯页码/数字行
]


def split_paragraphs(text, max_chars=420):
    """把章节正文切成语义段：连续非空行聚合，过长再切。"""
    lines = text.split('\n')
    paras, buf, start = [], [], None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s:
            if start is None:
                start = i
            buf.append(s)
        elif buf:
            paras.append((start, i, '\n'.join(buf)))
            buf, start = [], None
    if buf:
        paras.append((start, len(lines), '\n'.join(buf)))

    out = []
    for st, ed, body in paras:
        body_only = re.sub(r'\s', '', body)
        if len(body_only) < 12:          # 过短，多半是标题或断句
            continue
        if len(body_only) > max_chars:   # 过长，按句号二次切分
            pieces = re.split(r'(?<=[。！？])', body_only)
            sub, acc = [], ''
            for p in pieces:
                acc += p
                if len(acc) >= max_chars:
                    sub.append(acc)
                    acc = ''
            if acc:
                sub.append(acc)
            for k, p in enumerate(sub):
                out.append({'line_start': st, 'line_end': ed, 'chars': len(p), 'body': p})
        else:
            out.append({'line_start': st, 'line_end': ed, 'chars': len(body_only), 'body': body_only})
    return out


def noise_flags(body):
    lines = [l for l in body.split('\n') if l.strip()]
    if not lines:
        return []
    short = sum(1 for l in lines if len(l.strip()) <= 18)
    flags = []
    if len(lines) >= 4 and short / len(lines) > 0.7:
        flags.append('poem_like')     # 疑似诗歌/排比短句，需人工剔除
    return flags


def score_para(body):
    """返回 {类型 -> (加权得分, {信号: 次数})}。按候选类型聚合，便于分类型取 Top。"""
    by_type = {}
    hit_detail = {}
    for name, pat, types, w in SIGNALS:
        n = len(pat.findall(body))
        if not n:
            continue
        hit_detail[name] = n
        for t in types.split(','):
            cur = by_type.get(t, [0, {}])
            cur[0] += n * w
            cur[1][name] = n
            by_type[t] = cur
    return {t: {'score': v[0], 'signals': v[1]} for t, v in by_type.items()}, hit_detail


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, out_path = sys.argv[1], sys.argv[2]
    top_per_type = 2
    if '--per-type' in sys.argv:
        top_per_type = int(sys.argv[sys.argv.index('--per-type') + 1])

    chapters = json.loads(io.open(src, encoding='utf-8').read())
    result = []
    for ch in chapters:
        paras = split_paragraphs(ch['text'])
        # 先算出每段的「每类型得分」，再按类型分别取 Top
        # 这样能避免高频弱类型（如 question→misconception）挤掉低频强类型（如 exercise）
        entries = []
        for idx, p in enumerate(paras):
            by_type, detail = score_para(p['body'])
            if not by_type:
                continue
            entries.append({
                'para_index': idx,
                'line_start': p['line_start'],
                'line_end': p['line_end'],
                'chars': p['chars'],
                'by_type': by_type,
                'signals': detail,
                'noise': noise_flags(p['body']),
            })

        per_type = {}
        for t in ('case', 'misconception', 'guideline', 'concept', 'principle',
                  'framework', 'workflow', 'boundary', 'scene', 'exercise'):
            rows = [e for e in entries if t in e['by_type'] and 'poem_like' not in e['noise']]
            rows.sort(key=lambda x: -x['by_type'][t]['score'])
            if rows:
                per_type[t] = [{
                    'para_index': r['para_index'],
                    'line_start': r['line_start'],
                    'line_end': r['line_end'],
                    'chars': r['chars'],
                    'score': r['by_type'][t]['score'],
                    'signals': r['signals'],
                    'noise': r['noise'],
                } for r in rows[:top_per_type]]

        # 该章各类候选的可用数量概览（不产出正文）
        avail = {}
        for e in entries:
            for t in e['by_type']:
                avail[t] = avail.get(t, 0) + 1

        result.append({
            'chapter': ch['chapter'],
            'title': ch['title'],
            'total_chars': ch['chars'],
            'para_total': len(paras),
            'candidate_total': len(entries),
            'type_availability': dict(sorted(avail.items(), key=lambda kv: -kv[1])),
            'top_by_type': per_type,
        })

    io.open(out_path, 'w', encoding='utf-8').write(
        json.dumps(result, ensure_ascii=False, indent=2))

    tot = sum(r['candidate_total'] for r in result)
    picked = sum(len(v) for r in result for v in r['top_by_type'].values())
    print(f'章节 {len(result)} | 候选段 {tot} | 按类型抽取 {picked} 个待裁定位置')
    print()
    print('章节'.ljust(10), '字数'.rjust(6), '候选'.rjust(5), '  各类型可用数（前4）')
    print('-' * 76)
    for r in result:
        top4 = ', '.join(f'{k}:{v}' for k, v in list(r['type_availability'].items())[:4])
        print(r['chapter'].ljust(11), str(r['total_chars']).rjust(6),
              str(r['candidate_total']).rjust(5), '  ', top4)
    print()
    print(f'→ {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
