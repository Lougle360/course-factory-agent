#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 5 闸门 · 跨文件交付口径一致性校验。

为什么需要（这次是给自己补的短板）：
    课程计划按方案 A 排到了 960 分钟（2 天 × 480），并在正文里明写
    「需回写大纲第四节」——这句回写没做。结果是同一门课在六份交付物里
    出现三种时长口径：需求说明书 720、大纲 720、计划 960、手册 960、
    PPT 页稿按 720 算页数。而 check_schedule 只比对「计划实排 vs 大纲模块
    合计」，这两个恰好都是 720，于是 240 分钟的口径撕裂被整份放行。

    讲师拿到这样的六件套，第一天会排到 17:00，而学员通知单上写的是
    每天 360 分钟。这不是排版错误，是交付事故。

本脚本校验四条机械可判的口径：
    GROSS  总包时长（含茶歇午休）—— 六份文件必须同一个数
    NET    教学净时长（模块合计）—— 六份文件必须同一个数，且等于大纲模块声明之和
    PERDAY 每天分钟数            —— 必须同一个数
    PLAN   计划实排合计          —— 必须等于 GROSS

退出码: 0 = 通过 / 1 = 未通过 / 2 = 无法判定（找不到可判定文件）
"""

import argparse
import io
import os
import re
import sys

# ── 提取规则 ────────────────────────────────────────────────
# GROSS： | 时长 | 720 分钟 |  /  | 建议时长 | 720 分钟 |  /  把总时长扩到 **960 分钟**
GROSS_PATS = [
    re.compile(r"\|\s*(?:建议)?时长\s*\|\s*\*{0,2}(\d{3,4})\s*分钟"),
    re.compile(r"总时长[^0-9]{0,16}\*{0,2}(\d{3,4})\s*分钟"),
]
# NET：教学时长 720 分钟 / 各模块时长合计 **720 分钟** / 模块 720 分钟
NET_PATS = [
    re.compile(r"教学时长\s*\*{0,2}(\d{3,4})\s*分钟"),
    re.compile(r"模块[^0-9]{0,10}合计\s*\*{0,2}(\d{3,4})\s*分钟"),
    re.compile(r"模块\s*\*{0,2}(\d{3,4})\s*分钟"),
]
# PERDAY：每天 360 分钟 / 2 天 × 480 分钟 / ## 一、Day 1（480 分钟）
PERDAY_PATS = [
    re.compile(r"每天\s*\*{0,2}(\d{3,4})\s*分钟"),
    re.compile(r"(\d)\s*天\s*[×x*]\s*\*{0,2}(\d{3,4})\s*分钟"),
    re.compile(r"Day\s*\d+[^0-9（(]{0,4}（\s*\*{0,2}(\d{3,4})\s*分钟"),
]
DAY_GROUP = 2  # 上面第二条正则里代表「每天分钟数」的分组

# 引号区间：凡落在「」""''（）内的数值是「引用原话」，不是本文件的声明。
# 这次踩到的坑：计划第 12 行在「」里复述大纲的「2 天 × 360 分钟」，被当成自己的
# 声明，于是 PERDAY 全票通过于 360 —— 而计划实际每天排 480。不排除引用就是假 OK。
QUOTE_RE = re.compile(r"[「“”\"'‘’]")

# 大纲模块声明：1. M0 开场：这不是让管理者变软（Know，40 分钟）
MOD_ITEM_RE = re.compile(r"^\d+\.\s+(M\d+)\s+(.+?)（[^，]*，\s*(\d+)\s*分钟")
MOD_HEAD_RE = re.compile(r"^###\s+(M\d+)\s+·\s+(.+?)（[^，]*，\s*(\d+)\s*分钟")

# 计划排期行首列
TIME_RE = re.compile(r"^\s*\*{0,2}(\d{1,2}):(\d{2})\s*[–\-~]\s*\*{0,2}(\d{1,2}):(\d{2})\s*\*{0,2}\s*$")

DEFAULT_FILES = [
    "培训需求说明书", "课程大纲", "详细课程计划", "学员课程讲义",
    "教员课程指导手册", "教员课程PPT-Storyboard",
]


def to_min(hh, mm):
    return int(hh) * 60 + int(mm)


def quote_spans(ln):
    """返回本行所有成对引号的内部区间 [(start, end)]，用于排除引用中的数值。"""
    s, spans, stack = [], [], None
    for i, ch in enumerate(ln):
        if ch in "「“\"'‘":
            if stack is None:
                stack = i
        elif ch in "」”\"'’":
            if stack is not None:
                spans.append((stack, i))
                stack = None
    return spans


def in_quotes(pos, spans):
    return any(a < pos < b for a, b in spans)


def scan_duration(path):
    """扫一个文件里的 GROSS / NET / PERDAY 声明，返回 [(行号, 值, 原文)]。

    落在引号内的数值一律跳过——那是引用别处的原话，不是本文件自己的口径。
    """
    out = {"gross": [], "net": [], "perday": []}
    with io.open(path, encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            spans = quote_spans(ln)
            for key, pats in (("gross", GROSS_PATS), ("net", NET_PATS), ("perday", PERDAY_PATS)):
                for p in pats:
                    for m in p.finditer(ln):
                        if in_quotes(m.start(), spans):
                            continue
                        g = DAY_GROUP if (key == "perday" and p is PERDAY_PATS[1]) else 1
                        out[key].append((i, int(m.group(g)), ln.strip()[:60]))
    return out


def plan_actual(path):
    """从课程计划的时间轴实算：总包分钟数 + 按天分段每天的分钟数。

    这是唯一权威的实际排期——文件里写什么都得以它不是为准。
    跨天判定：后一行开始时间早于前一行结束，即视为换天（同一天内不会倒流）。
    """
    with io.open(path, encoding="utf-8") as f:
        rows = []
        for ln in f:
            if not ln.startswith("|"):
                continue
            cell = ln.strip().strip("|").split("|")[0].strip().replace("*", "").strip()
            m = TIME_RE.match(cell)
            if m:
                rows.append((to_min(m.group(1), m.group(2)), to_min(m.group(3), m.group(4))))
    if not rows:
        return None, []
    days, cur = [], None
    prev_end = None
    for s, e in rows:
        if prev_end is not None and s < prev_end:      # 换天
            days.append(cur)
            cur = None
        cur = (cur or 0) + (e - s)
        prev_end = e
    if cur is not None:
        days.append(cur)
    return sum(days), days


def outline_module_sum(path):
    """大纲模块声明时长之和。两种写法都认：有序列表和 ### 小节标题。"""
    mods = []
    with io.open(path, encoding="utf-8") as f:
        for ln in f:
            m = MOD_HEAD_RE.match(ln)
            if m:
                mods.append((m.group(1), int(m.group(3))))
    if mods:
        return sum(v for _, v in mods), mods
    with io.open(path, encoding="utf-8") as f:
        for ln in f:
            m = MOD_ITEM_RE.match(ln)
            if m:
                mods.append((m.group(1), int(m.group(3))))
    return (sum(v for _, v in mods) if mods else None), mods


def main():
    ap = argparse.ArgumentParser(description="交付物跨文件口径一致性校验")
    ap.add_argument("--project", default=".", help="项目目录，自动识别六件套")
    ap.add_argument("files", nargs="*", help="显式指定要校验的 md 文件（优先于自动识别）")
    ap.add_argument("--outline", help="显式指定课程大纲（用于取模块声明之和）")
    ap.add_argument("--plan", help="显式指定详细课程计划（用于取实排总时长）")
    a = ap.parse_args()

    root = a.project
    found = {}
    for fn in sorted(os.listdir(root)):
        if not fn.endswith(".md"):
            continue
        for tag in DEFAULT_FILES:
            if tag in fn:
                found.setdefault(tag, []).append(fn)
    files = a.files if a.files else [v[0] for k in DEFAULT_FILES for v in [found.get(k, [])]]
    files = [f if os.path.isabs(f) else os.path.join(root, f) for f in files]

    if not files:
        print("FATAL：目录下没找到任何六件套文件")
        return 2

    print("=" * 72)
    print("Stage 5 闸门 · 跨文件交付口径一致性")
    print("=" * 72)

    # ── 收集 ──────────────────────────────────────
    acc = {"gross": [], "net": [], "perday": []}
    for f in files:
        d = scan_duration(f)
        for k in acc:
            for ln, v, raw in d[k]:
                acc[k].append((os.path.basename(f), ln, v, raw))

    # ── 权威源 ────────────────────────────────────
    # 只有两个地方能定真值：大纲定 NET（模块时长之和），计划定 GROSS/PERDAY（时间轴实排）。
    # 第一版按「各文件互相投票、少数服从多数」判定，结果计划正文引用大纲原话的
    # 「2 天 × 360」混进票箱，让实际每天 480 的排期全票通过——引用稀释了真值。
    # 投票制在这里是错的：这门课的时长只能有一个出处，其余全部向它对账。
    outline = a.outline
    if outline is None:
        cands = found.get("课程大纲", [])
        outline = os.path.join(root, cands[0]) if cands else None
    plan = a.plan
    if plan is None:
        cands = found.get("详细课程计划", [])
        plan = os.path.join(root, cands[0]) if cands else None

    net_true, mods = (None, [])
    if outline and os.path.exists(outline):
        net_true, mods = outline_module_sum(outline)

    gross_true, days = (None, [])
    if plan and os.path.exists(plan):
        gross_true, days = plan_actual(plan)

    if net_true is None and gross_true is None:
        print("\nFATAL：既没有解析到大纲模块声明，也没有解析到计划排期轴，无法判定")
        print("判定：无法判定 —— 请先用 --outline / --plan 指定，或检查文件格式")
        return 2

    problems, notes = [], []

    print("\n【权威源】NET 教学净时长 ← 大纲模块声明之和")
    print("-" * 72)
    if net_true is None:
        print("  未解析到（需形如 ### M0 · 名称（Know，40 分钟））")
    else:
        print("  %d 个模块，合计 %d 分钟" % (len(mods), net_true))
        print("  %s" % "  ".join("%s:%d" % (m, v) for m, v in mods))

    print("\n【权威源】GROSS 总包时长 ← 课程计划时间轴实排")
    print("-" * 72)
    if gross_true is None:
        print("  未解析到排期时间轴（表格首列需形如 09:00–09:10）")
    else:
        print("  实排合计 %d 分钟，分 %d 天：%s"
              % (gross_true, len(days), " / ".join("%d" % d for d in days)))

    days_uniform = None
    if len(days) >= 1 and len(set(days)) == 1:
        days_uniform = days[0]

    def check_bucket(key, label, true_v, soft=False):
        """各文件声明必须与权威源一致。soft=True 时只提示不拦（用于非均匀天数）。"""
        items = acc[key]
        print("\n%s（各文件声明 vs 权威值 %s）" % (label, true_v if true_v else "—"))
        print("-" * 72)
        if not items:
            print("  无文件显式声明")
            return
        bad = []
        for fn, ln, v, raw in items:
            ok = (true_v is None) or (v == true_v)
            print("  %-40s 第%-4d行 声明 %4d 分  %s　%s"
                  % (fn[:40], ln, v, "✅" if ok else "❌", raw[:46]))
            if not ok:
                bad.append((fn, ln, v))
        if bad:
            msg = ("%s 有 %d 处与权威值 %d 不符：%s"
                   % (label, len(bad), true_v,
                      "、".join("%s第%d行=%d" % (f[:24], l, v) for f, l, v in bad)[:180]))
            notes.append(msg) if soft else problems.append(msg)
        elif true_v is not None:
            notes.append("%s 全部 %d 处声明与权威值一致（%d 分钟）" % (label, len(items), true_v))

    check_bucket("net", "NET 教学净时长", net_true)
    check_bucket("gross", "GROSS 总包时长", gross_true)

    print("\n【权威源】PERDAY 每天分钟数 ← 计划按天实算")
    print("-" * 72)
    if days_uniform is not None:
        print("  各天均为 %d 分钟（%d 天）" % (days_uniform, len(days)))
        check_bucket("perday", "PERDAY 每天分钟数", days_uniform)
    elif days:
        print("  ⚠ 各天时长不同（%s），不存在统一的「每天 X 分钟」表述"
              % " / ".join("%d" % d for d in days))
        check_bucket("perday", "PERDAY 每天分钟数（仅供参考，不拦）", days[0], soft=True)
    else:
        print("  未解析到按天分段")

    # ── 派生约束 ──────────────────────────────────
    if gross_true is not None and net_true is not None:
        print("\n总包构成")
        print("-" * 72)
        diff = gross_true - net_true
        print("  GROSS %d − NET %d = %d 分钟（茶歇/午休/开场/收尾/过渡）"
              % (gross_true, net_true, diff))
        if diff < 0:
            problems.append("总包 %d < 模块净时长 %d：休息时间为负，排期不成立"
                            % (gross_true, net_true))
        elif diff == 0:
            notes.append("总包 = 模块净时长（%d 分钟）：意味着全天无茶歇无午休，"
                         "请确认这是有意安排" % gross_true)
        else:
            notes.append("休息时间预算 %d 分钟（占总包 %.1f%%）"
                         % (diff, 100.0 * diff / gross_true))

    if gross_true is not None and days_uniform is not None and days_uniform > 0:
        d = gross_true / float(days_uniform)
        print("\n天数换算")
        print("-" * 72)
        print("  GROSS %d ÷ 每天 %d = %.2f 天" % (gross_true, days_uniform, d))
        if abs(d - round(d)) > 0.01:
            problems.append("总包 %d 无法被每天 %d 分钟整除（%.2f 天）"
                            % (gross_true, days_uniform, d))
        else:
            notes.append("天数换算自洽（%d 天 × %d 分钟 = %d）"
                         % (int(round(d)), days_uniform, int(round(d)) * days_uniform))

    print()
    print("=" * 72)
    for n in notes:
        print("  ✅ %s" % n)
    for p in problems:
        print("  ❌ %s" % p)
    print("=" * 72)
    if problems:
        print("判定：❌ 未通过 —— 交付物之间存在口径冲突，讲师会拿到互相矛盾的排期")
        return 1
    print("判定：✅ 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
