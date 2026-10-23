#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""版权闸门（扫描制）· 交付物是否混入了原材料原文。

为什么需要：此前版权是「登记制」——只在文档头部写一句「只用概括」，
但从不真的检查交付物里有没有原文。承诺写了，门没有。
这是对外最重要的一条承诺，必须可验证。

做法：
  1. 把原材料压成纯中文长串（去标点、数字、英文、空白）
  2. 把交付物同样压成中文串片段
  3. 长度 ≥ --min 的片段若在原材料中精确命中 → 判定为原文摘录

为什么用「连续中文串」而不是「句子」：摘录常跨标点、改标点，
按标点切句会被绕过。压成纯中文串后，「他总是迟到。」和「他总是迟到」等价。

用法:
    python check_copyright.py --source <原材料.md> <交付物1.md> <交付物2.md> ...
    python check_copyright.py --source A.md --source B.md *.md
    python check_copyright.py --source-dir <目录> --min 20 *.md

退出码: 0 = 干净 / 1 = 发现疑似原文摘录 / 2 = 无法判定
"""

import argparse
import io
import os
import re
import sys
import glob
from functools import lru_cache
from bisect import bisect_right
from pathlib import Path

# 只保留中文字符（含 CJK 统一汉字）
NON_HAN = re.compile(r"[^\u4e00-\u9fff]")
ALLOW_MARK = "copyright:allow"


def to_han(text):
    """压成纯中文长串：去掉标点、数字、英文、空白。"""
    return NON_HAN.sub("", text)


def load_source(paths):
    buf = []
    for p in paths:
        if os.path.splitext(p)[1].lower() not in {'.md', '.txt', '.markdown'}:
            raise ValueError('版权比对需使用可读派生文本，不可直接传入 PDF/二进制文件')
        with io.open(p, encoding="utf-8-sig") as f:
            buf.append(f.read())
    return to_han("\n".join(buf))


def split_fragments(han_line, min_len):
    """把一行压过的中文串按「非中文已经剔除」后切成不短于 min_len 的片段。

    这里直接对整段的中文串做滑动窗口会太慢；改为按原始行的中文串整体检查，
    再对命中的二分定位——先整体，再细分到 min_len 报告。
    """
    return han_line if len(han_line) >= min_len else ""


@lru_cache(maxsize=4)
def windows(source, length):
    return frozenset(source[i:i + length] for i in range(len(source) - length + 1))


def scan(path, source, min_len, warn_len):
    """扫描单个交付物，返回 (fatal, warn) 两个列表。"""
    fatal, warn = [], []
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        return [(0, "FATAL", "文件不存在", "")], []
    # Preserve line attribution while matching across wrapping/newlines. Explicit
    # exemptions split the stream, so they cannot be joined to adjacent content.
    chunks, chars, starts, line_numbers = [], '', [], []
    for lineno, raw in enumerate(lines, 1):
        if ALLOW_MARK in raw:
            if chars:
                chunks.append((chars, starts, line_numbers))
            chars, starts, line_numbers = '', [], []
            continue
        han = to_han(raw)
        if han:
            starts.append(len(chars))
            line_numbers.append(lineno)
            chars += han
    if chars:
        chunks.append((chars, starts, line_numbers))
    seen_fatal, seen_warn = set(), set()
    for han, starts, line_numbers in chunks:
        for length, target, seen, label in (
            (min_len, fatal, seen_fatal, '原文摘录'),
            (warn_len, warn, seen_warn, '短片段重合（仅提示）'),
        ):
            index = windows(source, length)
            for pos in range(len(han) - length + 1):
                if han[pos:pos + length] not in index:
                    continue
                lineno = line_numbers[bisect_right(starts, pos) - 1]
                if lineno not in seen and (target is fatal or lineno not in seen_fatal):
                    seen.add(lineno)
                    target.append((lineno, label, length, lines[lineno - 1].strip()[:60]))
    return fatal, warn


def main():
    ap = argparse.ArgumentParser(description="版权闸门：交付物是否混入原材料原文")
    ap.add_argument("files", nargs="*", help="待检交付物")
    # 注意：这里必须用 action="append"。写成 nargs="*" 会把后面所有位置参数
    # （也就是待检交付物）一并当成原材料吃掉，导致「没有待检文件」——实测踩过。
    ap.add_argument("--source", action="append", default=[], help="原材料文件（可重复指定）")
    ap.add_argument("--source-dir", help="原材料目录（递归取 .md/.txt）")
    ap.add_argument("--min", type=int, default=20, help="判定为摘录的最小连续中文字数（默认 20）")
    ap.add_argument("--warn", type=int, default=12, help="提示阈值（默认 12，仅提示不拦截）")
    a = ap.parse_args()
    if not 1 <= a.warn < a.min:
        ap.error('阈值须满足 1 <= warn < min')

    src_paths = list(a.source or [])
    if a.source_dir:
        for ext in ("*.md", "*.txt"):
            src_paths.extend(glob.glob(os.path.join(a.source_dir, "**", ext), recursive=True))
    if not src_paths:
        print("FATAL：必须用 --source 或 --source-dir 指定原材料，否则无从比对")
        return 2
    if not a.files:
        print("FATAL：没有待检文件")
        return 2

    try:
        source = load_source(src_paths)
    except (OSError, UnicodeError, ValueError) as exc:
        print('FATAL：原材料不可用于比对：%s' % exc)
        return 2
    if len(source) < a.min:
        print('FATAL：可比较中文不足阈值，无法判定（当前仅支持中文重合扫描）')
        return 2
    print("=" * 74)
    print("版权闸门（扫描制）· 交付物原文摘录检查")
    print("=" * 74)
    print("原材料：%d 个文件，压成中文串 %d 字" % (len(src_paths), len(source)))
    print("判定阈值：连续 %d 字精确命中即判为摘录（提示阈值 %d 字）" % (a.min, a.warn))
    print()

    total_fatal = 0
    for f in a.files:
        fatal, warn = scan(f, source, a.min, a.warn)
        status = "❌" if fatal else "✅"
        print("%s %-46s 命中 %d 处" % (status, os.path.basename(f)[:46], len(fatal)))
        for lineno, kind, ln, ctx in fatal[:6]:
            print("     第%-5d %s（%s字） …%s…" % (lineno, kind, ln, ctx))
        for lineno, kind, ln, ctx in warn[:6]:
            print("     警告 第%d行 %s（%s字） …%s…" % (lineno, kind, ln, ctx))
        if len(fatal) > 6:
            print("     …… 另有 %d 处" % (len(fatal) - 6))
        total_fatal += len(fatal)

    print()
    print("=" * 74)
    if total_fatal:
        print("判定：❌ 未通过 —— 共 %d 处疑似原文摘录" % total_fatal)
        print()
        print("处理办法（三选一，不许直接删阈值）：")
        print("  1. 改写成自己的概括")
        print("  2. 取得授权后，在该行加 %s 标记并注明授权范围" % ALLOW_MARK)
        print("  3. 确实必须原文、且无授权 → 该内容不得进入交付物")
        return 1
    print("判定：✅ 通过 —— 未发现达到阈值的原文摘录")
    return 0


if __name__ == "__main__":
    sys.exit(main())
