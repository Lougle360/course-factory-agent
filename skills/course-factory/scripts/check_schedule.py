#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage 5 闸门 · 课程计划时间自洽校验。

为什么需要：02 阶段要求「所有时间加总必须与总课时一致」，
但人眼核对分钟级排期几乎必错——本次实测就漏排了 M2 的 10 分钟。
时间排错不是排版问题：讲师按表上课，错 10 分钟就是一整个单元讲不完。

本脚本做三件机械可判的事：
  1. 时间轴连续：相邻行首尾相接，无重叠、无空隙
  2. 模块时长：按出现顺序把非休息单元归堆，逐模块比对大纲声明的时长
  3. 总量：所有区间之和 = 计划头部声明的总时长

用法:
    python check_schedule.py <课程计划.md> --outline <课程大纲.md>
    python check_schedule.py <课程计划.md> --total 960

退出码: 0 = 通过 / 1 = 未通过 / 2 = 无法判定（缺输入或解析不到）
"""

import argparse
import io
import re
import sys

# 时间区间：兼容 –(en dash) -(hyphen) ~ 三种写法
TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*[–\-~]\s*(\d{1,2}):(\d{2})\s*$")
# 大纲里的模块声明：### M0 · 名称（Know，40 分钟）
MOD_RE = re.compile(r"^###\s+(M\d+)\s+·\s+(.+?)（[^，]*，\s*(\d+)\s*分钟")
# 计划头部声明的总时长：960 分钟 / 720 分钟
TOTAL_RE = re.compile(r"(\d{3,4})\s*分钟")
# 组件号：出现即认定为教学单元（比关键词可靠得多）
COMP_RE = re.compile(r"\bC\d{3}\b")
# 仅用于给人工提示「这行看着像休息」，不参与判定
BREAK_WORDS = ("茶歇", "午休", "复盘", "回顾", "唤醒", "收束", "收尾", "签到")


def to_min(hh, mm):
    return int(hh) * 60 + int(mm)


def parse_row(line):
    """返回 (start, end, 单元名, 是否教学单元)；不是表格数据行则返回 None。

    两处都是实测踩出来的：
    1. 休息行常写成 `| **11:10–11:20** | **茶歇** |`，加粗标记必须剥掉，
       否则茶歇和午休整行解析不到，会被误报成「时间空隙」。
    2. 「是不是教学单元」不能用单元名里的关键词判断——
       「复盘 + 听到「不」的解读」含「复盘」却被判成休息，导致该模块少 15 分，
       随后吃掉下一模块的第一个单元补数，级联偏移，误差全堆到最后一个模块。
       改用更强的判据：教学单元必须挂组件号（C0xx），否则算休息或过渡。
    """
    if not line.startswith("|"):
        return None
    cells = [c.strip().replace("*", "").strip() for c in line.strip().strip("|").split("|")]
    if len(cells) < 2:
        return None
    m = TIME_RE.match(cells[0])
    if not m:
        return None
    start = to_min(m.group(1), m.group(2))
    end = to_min(m.group(3), m.group(4))
    teaching = bool(COMP_RE.search(line))
    return start, end, cells[1], teaching


def load_outline_minutes(path):
    """从大纲解析每个模块的声明时长（按出现顺序）。"""
    out = []
    with io.open(path, encoding="utf-8") as f:
        for ln in f:
            m = MOD_RE.match(ln)
            if m:
                out.append((m.group(1), int(m.group(3)), m.group(2).strip()))
    return out


def main():
    ap = argparse.ArgumentParser(description="课程计划时间自洽校验")
    ap.add_argument("plan", help="课程计划 md")
    ap.add_argument("--outline", help="课程大纲 md（用于取模块声明时长）")
    ap.add_argument("--total", type=int, help="计划声明的总时长（分钟）；不给则从文中猜")
    a = ap.parse_args()

    try:
        with io.open(a.plan, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        print("FATAL：找不到课程计划文件 %s" % a.plan)
        return 2

    rows = []
    for i, ln in enumerate(lines, 1):
        r = parse_row(ln)
        if r:
            rows.append((i, r[0], r[1], r[2], r[3]))

    if not rows:
        print("FATAL：课程计划里没解析到任何时间区间行（表格首列需形如 09:00–09:10）")
        return 2

    problems, notes = [], []

    # ── 1. 时间轴连续 ──────────────────────────────
    # 跨天处理：第二天从头开始（09:00 < 昨日 17:00），这不是重叠，是换天。
    # 第一版没处理，把 Day2 的开场判成「与 Day1 收尾重叠 480 分钟」。
    gaps, overlaps, backwards = [], [], []
    day_breaks = [0]
    for k in range(1, len(rows)):
        prev_end = rows[k - 1][2]
        cur_start = rows[k][1]
        if cur_start < prev_end:
            day_breaks.append(k)          # 视为新的一天，不判重叠
            continue
        if cur_start > prev_end:
            gaps.append((rows[k - 1][0], rows[k][0], cur_start - prev_end))
    if len(day_breaks) > 1:
        notes.append("检测到 %d 天分段，跨天处已按换天处理（不判重叠）" % len(day_breaks))
    for i, s, e, name, _ in rows:
        if e <= s:
            backwards.append((i, name))

    print("=" * 72)
    print("Stage 5 闸门 · 课程计划时间自洽")
    print("=" * 72)
    print("解析到 %d 个排期行，跨度 %s–%s"
          % (len(rows), hhmm(rows[0][1]), hhmm(rows[-1][2])))

    if backwards:
        problems.append("存在结束≤开始的区间：%s"
                        % "、".join("第%d行 %s" % (i, n) for i, n in backwards))
    if overlaps:
        problems.append("时间重叠 %d 处：%s"
                        % (len(overlaps),
                           "、".join("第%d/%d行 重叠%d分" % (a1, b1, d) for a1, b1, d in overlaps[:5])))
    if gaps:
        problems.append("时间空隙 %d 处：%s"
                        % (len(gaps),
                           "、".join("第%d→%d行 空%d分" % (a1, b1, d) for a1, b1, d in gaps[:5])))
    if not (backwards or overlaps or gaps):
        notes.append("时间轴连续，无重叠、无空隙、无倒挂")

    # ── 2. 模块时长比对 ────────────────────────────
    if a.outline:
        try:
            mods = load_outline_minutes(a.outline)
        except FileNotFoundError:
            print("FATAL：找不到大纲文件 %s" % a.outline)
            return 2
        if not mods:
            print("FATAL：大纲里没解析到模块声明（需形如 ### M0 · 名称（Know，40 分钟））")
            return 2

        # 按出现顺序把教学单元归堆（教学单元 = 挂了组件号的行）
        units = [(s, e, n) for _, s, e, n, t in rows if t]
        # 未挂组件号的过渡行（回顾、收束、日复盘等）单独列出供人工确认
        ambiguous = [(i, e - s, n) for i, s, e, n, t in rows
                     if not t and not any(w in n for w in BREAK_WORDS)]
        if ambiguous:
            print("  ⚠ 未挂组件号、且不像休息的过渡行 %d 处（已按非教学计）：%s"
                  % (len(ambiguous),
                     "、".join("第%d行 %s(%d分)" % (i, n[:16], d) for i, d, n in ambiguous[:4])))
        print()
        print("模块时长比对（大纲声明 vs 计划实排）")
        print("-" * 72)
        idx, mismatch = 0, []
        for mid, want, mname in mods:
            got = 0
            while idx < len(units):
                got += units[idx][1] - units[idx][0]
                idx += 1
                if got >= want:
                    break
            flag = "OK " if got == want else "差异"
            print("  %-4s %-28s 声明 %3d 分 / 实排 %3d 分  %s"
                  % (mid, mname[:28], want, got, flag))
            if got != want:
                mismatch.append((mid, mname, want, got))
        if idx < len(units):
            problems.append("还有 %d 个教学单元未被任何模块认领（模块总时长偏小）" % (len(units) - idx))
        if mismatch:
            problems.append("模块时长不符 %d 处：%s"
                            % (len(mismatch),
                               "、".join("%s 声明%d实排%d" % (m, w, g) for m, _, w, g in mismatch)))
        else:
            notes.append("全部 %d 个模块时长与大纲一致" % len(mods))

    # ── 3. 总量 ────────────────────────────────────
    total_actual = sum(e - s for _, s, e, _, _ in rows)
    declared = a.total
    if declared is None:
        # 必须认准「总时长」后面的数字。第一版用「含『分钟』且含『总』」的宽松匹配，
        # 结果先撞上「模块 720 分钟」这句，把模块时长当成了总时长，凭空报错。
        for ln in lines[:80]:
            m = re.search(r"总时长[^0-9]{0,12}(\d{3,4})", ln)
            if m:
                declared = int(m.group(1))
                break
        if declared is None:
            for ln in lines[:80]:
                m = re.search(r"总课时[^0-9]{0,12}(\d{3,4})", ln)
                if m:
                    declared = int(m.group(1))
                    break
    print()
    print("总量校验")
    print("-" * 72)
    print("  实排合计 %d 分钟（%s–%s）" % (total_actual, hhmm(rows[0][1]), hhmm(rows[-1][2])))
    if declared is None:
        notes.append("未声明总时长，跳过总量比对（可用 --total 指定）")
        print("  声明总时长：未找到")
    else:
        print("  声明总时长 %d 分钟" % declared)
        if total_actual != declared:
            problems.append("总量不符：声明 %d，实排 %d，差 %d 分钟"
                            % (declared, total_actual, total_actual - declared))
        else:
            notes.append("总量一致（%d 分钟）" % declared)

    # 模块净时长（排掉休息）
    net = sum(e - s for _, s, e, n, t in rows if t)
    brk = total_actual - net
    print("  其中：教学单元净时长 %d 分钟，休息/收束 %d 分钟" % (net, brk))

    print()
    print("=" * 72)
    for n in notes:
        print("  ✅ %s" % n)
    for p in problems:
        print("  ❌ %s" % p)
    print("=" * 72)
    if problems:
        print("判定：❌ 未通过 —— 修完再进 03 讲义")
        return 1
    print("判定：✅ 通过")
    return 0


def hhmm(m):
    return "%02d:%02d" % (m // 60, m % 60)


if __name__ == "__main__":
    sys.exit(main())
