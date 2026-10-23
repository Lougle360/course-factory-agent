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

# 只保留中文字符（含 CJK 统一汉字）
NON_HAN = re.compile(r"[^\u4e00-\u9fff]")
ALLOW_MARK = "copyright:allow"


def to_han(text):
    """压成纯中文长串：去掉标点、数字、英文、空白。"""
    return NON_HAN.sub("", text)


def load_source(paths):
    buf = []
    for p in paths:
        with io.open(p, encoding="utf-8", errors="ignore") as f:
            buf.append(f.read())
    return to_han("\n".join(buf))


def split_fragments(han_line, min_len):
    """把一行压过的中文串按「非中文已经剔除」后切成不短于 min_len 的片段。

    这里直接对整段的中文串做滑动窗口会太慢；改为按原始行的中文串整体检查，
    再对命中的二分定位——先整体，再细分到 min_len 报告。
    """
    return han_line if len(han_line) >= min_len else ""


def scan(path, source, min_len, warn_len):
    """扫描单个交付物，返回 (fatal, warn) 两个列表。"""
    fatal, warn = [], []
    try:
        lines = io.open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return [(0, "FATAL", "文件不存在", "")], []

    for lineno, raw in enumerate(lines, 1):
        if ALLOW_MARK in raw:
            continue
        # 跳过表格分隔行与纯符号行
        han = to_han(raw)
        if len(han) < warn_len:
            continue
        if han in source:
            fatal.append((lineno, "原文摘录", len(han), raw.strip()[:60]))
            continue
        # 整段未命中，再按滑动窗口查更短的摘录（只查 warn 区间与 min 区间的边界）
        n = len(han)
        if n >= min_len:
            hit = None
            step = max(1, min_len // 4)
            for i in range(0, n - min_len + 1, step):
                frag = han[i:i + min_len]
                if frag in source:
                    hit = frag
                    break
            if hit:
                fatal.append((lineno, "原文摘录(片段)", min_len, raw.strip()[:60]))

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

    source = load_source(src_paths)
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
            print("     第%-5d %s（%d字） …%s…" % (lineno, kind, ln, ctx))
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
