# -*- coding: utf-8 -*-
"""导出待裁定原文（仅供AI裁定阅读，属流程中间产物，不进交付物）

用法：
  python export_passages.py <chapters.json> <candidates.json> <out.md> [--per-chapter N] [--max-chars N]

版权约束提示：
  本文件是**流程中间产物**，保留原文是为了让 AI 能判定该段是否支撑某组件。
  它会留在 v1-trial 目录内，**不作为交付物**。
  交付物（组件卡 / 课程内容）中只能出现「概括」+「定位」，不得摘录原文。
"""
import io
import json
import sys


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    ch_src, cand_src, out = sys.argv[1], sys.argv[2], sys.argv[3]

    def arg(name, d):
        return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else d

    per_chapter = arg('--per-chapter', 5)
    max_chars = arg('--max-chars', 300)

    chapters = {c['chapter']: c for c in
                json.loads(io.open(ch_src, encoding='utf-8').read())}
    cands = json.loads(io.open(cand_src, encoding='utf-8').read())

    buf = []
    total = 0
    for c in cands:
        ch = c['chapter']
        text_lines = chapters[ch]['text'].split('\n')
        seen, rows = set(), []
        # 汇总该章所有类型的候选，按分数排序，取前 per_chapter 个不重复位置
        for t, items in c['top_by_type'].items():
            for it in items:
                rows.append((it['score'], it['line_start'], it['line_end'], t, it['signals']))
        rows.sort(key=lambda x: -x[0])
        picked = []
        for score, ls, le, t, sigs in rows:
            key = (ls, le)
            if key in seen:
                continue
            seen.add(key)
            body = '\n'.join(text_lines[ls:le]).strip()
            body = ' '.join(body.split())
            if len(body) > max_chars:
                body = body[:max_chars] + '…【截断】'
            if len(body) < 30:
                continue
            picked.append((t, score, sigs, body))
            if len(picked) >= per_chapter:
                break

        buf.append(f'\n## {ch}《{c["title"]}》\n')
        for t, score, sigs, body in picked:
            buf.append(f'- 候选类型 {t} | 信号 {sigs} | 强度 {score}')
            buf.append(f'  {body}\n')
            total += len(body)

    io.open(out, 'w', encoding='utf-8').write('\n'.join(buf))
    print(f'章节 {len(cands)} | 每章 {per_chapter} 段 | 导出字符 {total}')
    print(f'→ {out}（中间产物，不进交付物）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
