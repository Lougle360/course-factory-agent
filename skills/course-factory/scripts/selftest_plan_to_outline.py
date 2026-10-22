#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plan_to_outline 的闸门自检：用负例证明「闸门真的会咬人」。

为什么单独写这个
----------------
复盘 FIRE 流水线时抓到的最大问题就是：五道闸门全写进了文档，实跑 0/5 拦住东西。
所以新增任何检查，第一件事不是跑正例，而是**先证明它能拦住负例**。

每个用例做一处变异，断言校验必须报出对应问题：

| 用例 | 变异 | 预期报错 |
|---|---|---|
| 丢模块 | 删掉 M5 整段 | 大纲丢失模块 |
| 改模块名 | M1 改名 | 模块名被改动 |
| 改时长 | 某个模块时长改大 | 时长合计不符 |
| 丢组件 | 从总览表摘掉 C026 | 选用组件未出现 |
| 编造编号 | 插入 C999 | 清单里没有的编号 |
| 删去向表 | 删掉未选用组件附表 | 未交代去向 |
| 删小节 | 删掉「七、能力差距」 | 缺少小节 |
| 正例 | 不改 | 通过 |

用法：
    python selftest_plan_to_outline.py --plan <方案.md> --components <清单.md>
退出码：0 全部用例符合预期 / 1 有闸门没咬住
"""

import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plan_to_outline import load_components, load_plan, verify  # noqa: E402


def mutate(text, kind, plan):
    """对大纲做一处指定的破坏，返回变异后的文本。"""
    if kind == "丢模块":
        return re.sub(r"### M5 ·.*?(?=\n### M6|\n#### )", "", text, flags=re.S)
    if kind == "改模块名":
        return re.sub(r"(### M1 · )[^（]+（", r"\1被改成了别的名字（", text, count=1)
    if kind == "改时长":
        return re.sub(r"建议时长\*\*：(\d+) 分钟",
                      lambda m: "建议时长**：%d 分钟" % (int(m.group(1)) + 300),
                      text, count=1)
    if kind == "丢组件":
        # 从模块详细大纲里摘掉 C026 所在行
        out = [ln for ln in text.split("\n")
               if not ln.startswith("| C026 ")]
        return "\n".join(out)
    if kind == "编造编号":
        return text + "\n\n（附注：另参考 C999 与 C998。)\n"
    if kind == "删去向表":
        return re.sub(r"#### 附：未选用组件的去向.*?(?=\n---)", "", text, flags=re.S)
    if kind == "删小节":
        return re.sub(r"## 七、能力差距\n", "", text, count=1)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--components", required=True)
    ap.add_argument("--outline", required=True, help="由 gen 生成的大纲")
    a = ap.parse_args()

    comps, err = load_components(a.components)
    if err:
        print("[输入不可用] " + err)
        sys.exit(2)
    plan, err = load_plan(a.plan)
    if err:
        print("[输入不可用] " + err)
        sys.exit(2)
    if not os.path.isfile(a.outline):
        print("[输入不可用] 大纲不存在：%s" % a.outline)
        sys.exit(2)

    base = io.open(a.outline, encoding="utf-8").read()

    cases = [
        ("丢模块", "丢失模块"),
        ("改模块名", "模块名被改动"),
        ("改时长", "时长合计"),
        ("丢组件", "未落进模块核心内容表"),
        ("编造编号", "没有的编号"),
        ("删去向表", "去向"),
        ("删小节", "缺少小节"),
        ("正例", None),
    ]

    print("闸门自检 · 负例必须被拦下")
    print("=" * 68)
    failed = 0
    for kind, expect in cases:
        text = mutate(base, kind, plan)
        problems, notes, todos = verify(text, plan, comps)
        if expect is None:
            ok = not problems
            detail = "无问题（%d 处待补）" % len(todos) if ok else "；".join(problems)
        else:
            hit = any(expect in p for p in problems)
            ok = hit
            detail = ("已报出「%s」" % expect) if hit else \
                     "未拦住，实际报：%s" % ("；".join(problems) or "无")
        print("  %s %-6s %s" % ("✅" if ok else "❌", kind, detail))
        if not ok:
            failed += 1
    print("=" * 68)
    if failed:
        print("❌ %d/%d 个用例不符合预期——有闸门形同虚设" % (failed, len(cases)))
        sys.exit(1)
    print("✅ %d/%d 个用例全部符合预期——闸门真的会拦" % (len(cases), len(cases)))
    sys.exit(0)


if __name__ == "__main__":
    main()
