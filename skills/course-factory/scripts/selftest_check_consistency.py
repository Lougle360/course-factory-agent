#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_consistency.py 负例自测。

闸门的价值不在于它能通过正例，而在于它能拦住什么。
每个用例先把全套产物复制进临时目录，再做一处指定改动，
断言脚本给出期望的退码。

用法：python selftest_check_consistency.py
退出码：0 = 全部用例符合预期 / 1 = 有用例未按预期判定
"""

import io
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check_consistency.py")
SRC = os.environ.get("V1TRIAL", r"G:/WorkBuddy/Workshop/FDE-course/v1-trial")
WORK = os.path.join(SRC, "_negtest_consistency")

FILES = [
    "培训需求说明书-非暴力沟通企业中层-V0.1.md",
    "课程大纲-企业中层-V0.1.md",
    "详细课程计划-非暴力沟通企业中层-V0.1.md",
    "学员课程讲义-非暴力沟通企业中层-V0.1.md",
    "教员课程指导手册-非暴力沟通企业中层-V0.1.md",
    "教员课程PPT-Storyboard-非暴力沟通企业中层-V0.1.md",
]

OUTLINE = FILES[1]
SPEC = FILES[0]
PLAN = FILES[2]
PPT = FILES[5]


# ── 工具 ────────────────────────────────────────────
def fresh():
    """重建干净副本，并「幂等地」把整套口径压成 960 / 480 一致态。

    幂等是关键：外部文档本身可能已经在 960（真实发生过），也可能还在 720，
    自测必须在两种情形下都能构造出同一个已知起点。用正则而非字面串。
    """
    if os.path.isdir(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    for f in FILES:
        shutil.copy(os.path.join(SRC, f), os.path.join(WORK, f))
    # 需求说明书：时长行 → 960（2 天 × 480）
    sub_re(SPEC, r"\|\s*时长\s*\|\s*\*{0,2}\d{3,4}\s*分钟[^|]*\|",
           "| 时长 | 960 分钟（2 天 × 480 分钟，09:00–17:00） |")
    # 需求说明书：每天分钟数 → 480
    sub_re(SPEC, r"\|\s*时间安排\s*\|[^|]*\|",
           "| 时间安排 | 每天 480 分钟，含茶歇与午休 |")
    # 大纲：建议时长 → 960
    sub_re(OUTLINE, r"\|\s*建议时长\s*\|[^|]*\|",
           "| 建议时长 | 960 分钟（2 天 × 480 分钟）|")
    return 0


def read(f):
    with io.open(os.path.join(WORK, f), encoding="utf-8") as fh:
        return fh.read()


def write(f, t):
    with io.open(os.path.join(WORK, f), "w", encoding="utf-8") as fh:
        fh.write(t)


def sub(f, old, new, count=0):
    """字面替换；返回实际替换次数。count=0 表示替换全部。"""
    t = read(f)
    n = t.count(old)
    if n == 0:
        return 0
    write(f, t.replace(old, new) if count == 0 else t.replace(old, new, count))
    return n


def sub_re(f, pattern, new, count=0):
    """正则替换，返回替换次数。

    为什么必须有它：自测不能依赖外部文档的当前状态。第一版用字面串
    「720 → 960」构造基线，而真实文档后来真的改成 960 了，于是两个用例
    的锚点直接失效、被静默跳过（assert 拦下的才报错，没 assert 的就假通过）。
    用正则做幂等归一化：不管当前是 720 还是 960，都压到一致态。
    """
    t = read(f)
    new_t, n = re.subn(pattern, new, t, count=0 if count == 0 else count)
    if n:
        write(f, new_t)
    return n


def run():
    p = subprocess.run([sys.executable, SCRIPT, "--project", WORK],
                       capture_output=True, text=True, encoding="utf-8")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


CASES = []


def case(name, expect, fn, must_hit=None):
    CASES.append((name, expect, fn, must_hit))


# ── 用例定义 ────────────────────────────────────────
def c_baseline():
    fresh()
    return 0


def c_spec_wrong_gross():
    fresh()
    assert sub_re(SPEC, r"\|\s*时长\s*\|\s*\*{0,2}\d{3,4}\s*分钟[^|]*\|",
                  "| 时长 | 720 分钟（2 天 × 360 分钟） |") >= 1
    return 1


def c_outline_wrong_gross():
    fresh()
    assert sub_re(OUTLINE, r"\|\s*建议时长\s*\|[^|]*\|",
                  "| 建议时长 | 480 分钟（1 天）|") >= 1
    return 1


def c_plan_missing_rows():
    """删掉计划 Day2 最后的排期行 → 实算总包变化，与声明的 960 对不上。"""
    fresh()
    lines = read(PLAN).splitlines()
    tail = [i for i, l in enumerate(lines) if re.match(r"^\|\s*\d{2}:\d{2}", l)][-4:]
    for i in reversed(tail):
        del lines[i]
    write(PLAN, "\n".join(lines) + "\n")
    return 1


def c_ppt_net_fake():
    """PPT 页稿里的教学净时长被改成与大纲模块之和不符。"""
    fresh()
    assert sub(PPT, "教学时长 720 分钟", "教学时长 700 分钟") == 1
    return 1


def c_perday_not_divide():
    """总包 960 但写成 3 天 × 320：PERDAY 与计划实算的 480 冲突。"""
    fresh()
    assert sub_re(SPEC, r"\|\s*时长\s*\|[^|]*\|",
                  "| 时长 | 960 分钟（3 天 × 320 分钟） |") >= 1
    return 1


def c_gross_lt_net():
    """大纲模块之和被改到超过总包 → 休息时间为负。"""
    fresh()
    # 大纲里同一模块在「模块列表」和「### 小节标题」各出现一次，故替换数 ≥1
    assert sub(OUTLINE, "（Do，105 分钟）", "（Do，905 分钟）") >= 1
    return 1


def c_quote_excluded():
    """把时长声明放进引号内：那是引用，不是本文件的口径，不应计入。

    这个用例验证「引用稀释真值」那个 bug 确实被修掉了——
    第一版就是在这里翻的车。"""
    fresh()
    assert sub(SPEC, "| 时长 | 960 分钟", "| 时长 | 「960 分钟」") == 1
    return 0


def c_no_teaching_time():
    """总包恰好等于模块之和：全天无茶歇午休，须明确提示（但不拦）。"""
    fresh()
    # 把计划里两天的所有休息行时间压缩到 0 不现实，改为直接让 NET 声明 = GROSS
    assert sub(PPT, "教学时长 720 分钟", "教学时长 960 分钟") == 1
    return 1


case("C0 基线：口径统一后应放行", 0, c_baseline, "通过")
case("C1 需求说明书总包回退为 720", 1, c_spec_wrong_gross, "GROSS")
case("C2 大纲建议时长写成 480", 1, c_outline_wrong_gross, "GROSS")
case("C3 计划删掉 4 个排期行", 1, c_plan_missing_rows, "GROSS")
case("C4 PPT 教学净时长造假 700", 1, c_ppt_net_fake, "NET")
case("C5 总包写成 3 天 × 320", 1, c_perday_not_divide, "PERDAY")
case("C6 模块之和 > 总包（休息为负）", 1, c_gross_lt_net, "休息时间为负")
case("C7 引号内的时长应被忽略", 0, c_quote_excluded, "通过")
case("C8 NET 被改成等于总包（无休息）", 1, c_no_teaching_time, "NET")


def main():
    if not os.path.isfile(SCRIPT):
        print("FATAL：找不到 %s" % SCRIPT)
        return 1
    if not all(os.path.isfile(os.path.join(SRC, f)) for f in FILES):
        print("FATAL：源文件不全，请设置环境变量 V1TRIAL 指向试跑目录")
        return 1

    print("=" * 72)
    print("负例自测 · check_consistency.py")
    print("=" * 72)
    fails = 0
    for name, expect, fn, must_hit in CASES:
        try:
            fn()
        except AssertionError:
            print("  ⚠️  %-32s 构造失败（锚点未命中）" % name)
            fails += 1
            continue
        code, out = run()
        ok = (code == expect)
        hit = (must_hit in out) if must_hit else True
        if ok and hit:
            print("  ✅ %-32s 退码 %d（期望 %d）" % (name, code, expect))
        else:
            fails += 1
            print("  ❌ %-32s 退码 %d（期望 %d）%s"
                  % (name, code, expect,
                     "" if hit else "　且输出缺关键词：%s" % must_hit))
            tail = [l for l in out.splitlines() if l.strip().startswith(("❌", "✅", "判定"))]
            for l in tail[-6:]:
                print("        %s" % l.strip()[:110])

    if os.path.isdir(WORK):
        shutil.rmtree(WORK)

    print()
    print("=" * 72)
    print("%d/%d 用例符合预期" % (len(CASES) - fails, len(CASES)))
    print("=" * 72)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
