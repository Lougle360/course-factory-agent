#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编排方案 → 课程大纲：Stage 4 到 Stage 5 的交接转换器。

为什么需要这个脚本
------------------
Stage 4 产出「编排方案」（模块序列 + 组件取舍 + 课时），Stage 5 的 fire-course-dev
要的是「课程大纲」。此前这两头各说各话：fire-course-dev 的 01 阶段只认《培训需求
说明书》，全文检索「组件清单 / 编排方案」命中 0 处，交接棒掉在地上。

本脚本把交接固化成一次确定性的转换：

  编排方案 + 组件清单 + 学员画像卡  ──▶  课程大纲（13 节，对齐 fire-course-dev 01）

设计原则（重要）
----------------
脚本只做**能算出来的部分**，不做语义创作：

  自动完成：模块序列表、组件归属表、课时与配比、原材料地图、
            适用对象与**不适合对象**（从画像卡的 drop 判据反推）、
            模块「为什么学」（从编排决策按模块号/组件号反查）、核心成果

  留给 AI  ：课程名称、定位一句话、能力差距、学习目标的行文、
            每模块的核心问题与学习结果、核心成果的扩展

留给 AI 的部分统一标记为【AI 补：……】，生成后脚本会统计并列出待补清单，
填完再跑 `verify` 复核。这样「AI 补」是可以被复算、被追责的，不是随手生成。

用法
----
    python plan_to_outline.py gen    --plan 方案.md --components 组件清单.md \
                                     --profile 画像卡.yaml --out 课程大纲.md
    python plan_to_outline.py verify --outline 课程大纲.md --plan 方案.md \
                                     --components 组件清单.md [--strict]

退出码：0 通过 / 1 校验未过 / 2 输入不可用
"""

import argparse
import io
import os
import re
import sys
from collections import Counter, OrderedDict

# ── 组件类型 → 大纲「原材料地图」的分类映射 ──────────────────
TYPE_TO_MATERIAL = [
    ("核心知识", ("concept", "principle", "paradigm", "viewpoint")),
    ("方法/工具", ("tool", "framework", "technique")),
    ("SOP/流程", ("workflow", "process")),
    ("专家判断", ("guideline", "rule", "boundary", "criterion")),
    ("案例", ("case", "scene", "story", "analogy")),
    ("常见错误", ("misconception", "pitfall")),
    ("可训练技能", ("exercise", "drill")),
    ("数据/出处", ("data", "source", "quote")),
]

LEVEL_LABEL = {
    "Know": "Know（知道什么）",
    "Do": "Do（会做什么）",
    "Act": "Act（回到工作中做什么）",
}

TODO_PREFIX = "【AI 补："


# ────────────────────────────────────────────────────────────
# 一、解析
# ────────────────────────────────────────────────────────────

def _clean_cell(s):
    """清掉表格单元格里的加粗标记与可能造成错列的竖线。"""
    s = s.strip()
    s = s.replace("**", "")
    s = s.replace("|", "／")
    s = re.sub(r"\s+", " ", s)
    return s


def _is_table_sep(line):
    return bool(re.match(r"^\s*\|[\s:\-|]+\|\s*$", line))


def _split_row(line):
    if not line.strip().startswith("|"):
        return None
    cells = line.strip().strip("|").split("|")
    return [_clean_cell(c) for c in cells]


def load_trunk(path):
    """解析「二、四要素主干」表，返回 {ID: 概括}。

    为什么要单独解析这一段：逐章明细里对主干组件只写「见上文」「见主干表」，
    不回填的话，生成的大纲里这些组件的核心内容就是一句空话。
    """
    lines = io.open(path, encoding="utf-8").read().split("\n")
    start = end = None
    for i, ln in enumerate(lines):
        if re.match(r"^#{2,3}\s*二[、\.]", ln.strip()):
            start = i
        elif start is not None and re.match(r"^#{2,3}\s*三[、\.]", ln.strip()):
            end = i
            break
    if start is None:
        return {}
    end = end if end is not None else len(lines)

    out = {}
    for ln in lines[start:end]:
        row = _split_row(ln)
        if not row or len(row) < 4 or _is_table_sep(ln):
            continue
        if not re.fullmatch(r"C\d{3}", row[0]):
            continue
        out[row[0]] = row[3]
    return out


def load_components(path):
    """解析组件清单的「三、逐章组件明细」段落，返回 {ID: {...}}。

    只取该段落，是因为文件前部还有一张「四要素主干」表，列结构不同，
    混进来会把概括列和定位列错位。
    """
    if not os.path.isfile(path):
        return None, "组件清单不存在：%s" % path
    lines = io.open(path, encoding="utf-8").read().split("\n")

    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^#{2,3}\s*三[、\.]", ln.strip()):
            start = i
            break
    if start is None:
        return None, "组件清单里没找到「三、逐章组件明细」章节"

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^#{2,3}\s*四[、\.]", lines[j].strip()):
            end = j
            break

    comps = OrderedDict()
    chapter = ""
    for ln in lines[start:end]:
        s = ln.strip()
        m = re.match(r"^#{3,4}\s*(第.+?)\s*[（(]", s)
        if m:
            chapter = m.group(1).strip()
            continue
        row = _split_row(ln)
        if not row or _is_table_sep(ln):
            continue
        if len(row) < 4:
            continue
        cid = row[0]
        if not re.fullmatch(r"C\d{3}", cid):
            continue
        # 表头行跳过
        if cid == "ID" or row[1] in ("名称", "组件名"):
            continue
        comps[cid] = {
            "id": cid,
            "name": row[1],
            "type": row[2],
            "summary": row[3] if len(row) > 3 else "",
            "value": row[4] if len(row) > 4 else "",
            "chapter": chapter,
        }
    if not comps:
        return None, "逐章组件明细里没解析到任何组件"

    # 回填主干表里才有概括的组件，避免大纲里出现「见上文」这种空话。
    # 用前缀匹配而非等值匹配：有的写「见主干表。补充说明」，后半句要留住。
    trunk = load_trunk(path)
    for cid, c in comps.items():
        s = c["summary"].strip()
        for ph in ("见主干表", "见上文", "同上", "见上"):
            if s == ph or s.startswith(ph):
                rest = s[len(ph):].lstrip("。.，、；： ")
                base = trunk.get(cid, "")
                c["summary"] = (base + ("。" + rest if base and rest else rest)).strip()
                break
    return comps, None


def load_plan(path):
    """解析编排方案：立意、模块序列、关键决策、未选用清单、课时配比。"""
    if not os.path.isfile(path):
        return None, "编排方案不存在：%s" % path
    txt = io.open(path, encoding="utf-8").read()
    lines = txt.split("\n")

    plan = {
        "title": "", "thesis": "", "modules": [], "decisions": [],
        "unused": OrderedDict(), "level_pct": OrderedDict(),
        "intent_pct": OrderedDict(), "total_min": 0, "intent_legend": "",
    }

    m = re.search(r"^#\s+(.+)$", txt, re.M)
    if m:
        plan["title"] = m.group(1).strip()

    # 立意：模块序列之前那节里的引用块
    m = re.search(r"##\s*一、编排立意.*?\n+>\s*\*\*(.+?)\*\*", txt, re.S)
    if m:
        plan["thesis"] = m.group(1).strip()
    if not plan["thesis"]:
        m = re.search(r"##\s*一、编排立意.*?\n+>\s*(.+)", txt)
        if m:
            plan["thesis"] = m.group(1).strip().replace("**", "")

    # 模块序列
    mods = []
    for ln in lines:
        row = _split_row(ln)
        if not row or len(row) < 6 or _is_table_sep(ln):
            continue
        if not re.fullmatch(r"M\d+", row[0]):
            continue
        if row[1] in ("模块名", "模块名称"):
            continue
        comps = [c.strip() for c in re.findall(r"C\d{3}", row[5])]
        mods.append({
            "id": row[0],
            "name": row[1],
            "level": row[2],
            "minutes": int(re.sub(r"\D", "", row[3]) or 0),
            "intent": row[4],
            "comps": comps,
            "method": row[6] if len(row) > 6 else "",
        })
    if not mods:
        return None, "编排方案里没解析到模块序列表（需形如 | M0 | 模块名 | Know | 40 | — | C001 | 讲授 |）"
    plan["modules"] = mods
    plan["total_min"] = sum(x["minutes"] for x in mods)

    # 关键编排决策
    m = re.search(r"##\s*三、关键编排决策.*?\n(.*?)(?=\n##\s|$)", txt, re.S)
    if m:
        for ln in m.group(1).split("\n"):
            row = _split_row(ln)
            if not row or len(row) < 2 or _is_table_sep(ln):
                continue
            if row[0] in ("决策",):
                continue
            plan["decisions"].append((row[0], row[1]))

    # 未选用组件
    m = re.search(r"##\s*四、未选用组件清单.*?\n(.*?)(?=\n##\s|$)", txt, re.S)
    if m:
        for ln in m.group(1).split("\n"):
            row = _split_row(ln)
            if not row or len(row) < 4 or _is_table_sep(ln):
                continue
            if not re.fullmatch(r"C\d{3}", row[0]):
                continue
            plan["unused"][row[0]] = {
                "name": row[1], "type": row[2],
                "dest": row[3], "reason": row[4] if len(row) > 4 else "",
            }

    # 层级配比
    m = re.search(r"##\s*五、课时与层级配比.*?\n(.*?)(?=\n##\s|\n\*|$)", txt, re.S)
    if m:
        block = m.group(1)
        for ln in block.split("\n"):
            row = _split_row(ln)
            if not row or len(row) < 2 or _is_table_sep(ln):
                continue
            if re.fullmatch(r"(Know|Do|Act)", row[0]):
                plan["level_pct"][row[0]] = row[1]
            if re.fullmatch(r"[PETR]", row[0]):
                plan["intent_pct"][row[0]] = row[1]

    m = re.search(r"\*\*Do 意图标签\*\*：(.+)", txt)
    if m:
        plan["intent_legend"] = m.group(1).strip()

    return plan, None


def load_profile(path):
    """极简 YAML 解析：只支持本流水线画像卡用到的语法。

    不引第三方包，是为了让这个仓库 clone 下来就能跑。
    支持：顶层键、二层映射、- 列表项、- id: x 开头的映射列表、`>` 折叠块标量。
    """
    if not os.path.isfile(path):
        return None, "画像卡不存在：%s" % path
    raw = io.open(path, encoding="utf-8").read().split("\n")

    lines = []
    for ln in raw:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(ln.replace("\t", "    "))

    def indent_of(ln):
        return len(ln) - len(ln.lstrip(" "))

    data = {}
    # 栈项：{"ind": 该容器键所在缩进, "key": 父级键名（None 表示列表项，已入列）,
    #        "d": 映射, "l": 列表}
    # 子内容缩进必然大于容器键缩进，因此「新行缩进 <= 栈顶缩进」即该出栈。
    stack = [{"ind": -1, "key": None, "d": data, "l": []}]
    pending = None        # (容器, 键, 收集列表)
    pending_ind = -1

    def flush_pending():
        nonlocal pending
        if pending is not None:
            cont, key, parts = pending
            cont[key] = " ".join(parts).strip()
            pending = None

    def pop_to(ind):
        """弹出所有容器键缩进 >= 当前缩进的层级，并把值写回父级。"""
        while len(stack) > 1 and ind <= stack[-1]["ind"]:
            node = stack.pop()
            parent = stack[-1]
            if node["key"] is None:
                continue          # 列表项：值已在入列时放入，无需回写
            parent["d"][node["key"]] = node["l"] if node["l"] else node["d"]

    for ln in lines:
        ind = indent_of(ln)
        s = ln.strip()

        if pending is not None:
            if ind > pending_ind:
                pending[2].append(s)
                continue
            flush_pending()

        pop_to(ind)
        cur = stack[-1]

        if s.startswith("- "):
            body = s[2:].strip()
            if ":" in body and not body.startswith('"'):
                k, _, v = body.partition(":")
                k, v = k.strip(), v.strip()
                item = {}
                if v in (">", "|"):
                    pending, pending_ind = (item, k, []), ind
                    item[k] = ""
                else:
                    item[k] = v
                cur["l"].append(item)
                # 该项后续的同级键要归到这个 item，故压栈
                stack.append({"ind": ind, "key": None, "d": item, "l": []})
            else:
                cur["l"].append(body)
            continue

        if ":" in s:
            k, _, v = s.partition(":")
            k, v = k.strip(), v.strip()
            if v in (">", "|"):
                pending, pending_ind = (cur["d"], k, []), ind
                cur["d"][k] = ""
            elif v == "":
                stack.append({"ind": ind, "key": k, "d": {}, "l": []})
            else:
                cur["d"][k] = v
            continue

    flush_pending()
    pop_to(-1)

    if "label" not in data:
        return None, "画像卡缺 label 字段"
    return data, None


# ────────────────────────────────────────────────────────────
# 二、生成
# ────────────────────────────────────────────────────────────

def _match_decisions(plan, comps):
    """把「关键编排决策」挂到具体模块上，作为该模块「为什么学」的依据。

    两条匹配路径：
      1) 决策文本里出现模块号（M1）→ 直接对应
      2) 决策文本里出现组件号（C038）→ 落到该组件所属模块
    两条都走，是因为方案里的决策有的写模块、有的只写组件。
    """
    comp_to_mod = {}
    for mod in plan["modules"]:
        for cid in mod["comps"]:
            comp_to_mod[cid] = mod["id"]

    bucket = {m["id"]: [] for m in plan["modules"]}
    for head, reason in plan["decisions"]:
        text = head + " " + reason
        hit = set(re.findall(r"\bM\d+\b", text))
        for cid in re.findall(r"C\d{3}", text):
            if cid in comp_to_mod:
                hit.add(comp_to_mod[cid])
        for mid in hit:
            if mid in bucket:
                bucket[mid].append((head, reason))
    return bucket


def _material_map(plan, comps):
    """按选用的组件统计原材料地图。"""
    used = []
    for mod in plan["modules"]:
        used.extend(mod["comps"])
    used = list(dict.fromkeys(used))

    by_type = Counter()
    for cid in used:
        c = comps.get(cid)
        if c:
            by_type[c["type"]] += 1

    rows = []
    for label, types in TYPE_TO_MATERIAL:
        ids = [cid for cid in used
               if comps.get(cid) and comps[cid]["type"] in types]
        if not ids:
            continue
        shown = "、".join(
            "%s %s" % (cid, comps[cid]["name"]) for cid in ids[:8]
        )
        if len(ids) > 8:
            shown += " 等 %d 项" % len(ids)
        rows.append((label, shown, len(ids)))
    return rows, used, by_type


def _not_for(profile):
    """从画像卡的 drop 判据反推「不适合对象」。

    这是脚本能算、AI 容易漏的一类：画像里写了哪些东西不进课，
    就等于声明了这门课不为谁设计。
    """
    rules = profile.get("selection_rules") or []
    if isinstance(rules, dict):
        rules = [rules]
    drops = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        if str(r.get("action", "")).strip() == "drop":
            drops.append((r.get("condition", "").strip(),
                          r.get("reason", "").strip()))
    return drops


def _scenes(profile):
    v = profile.get("scenes") or []
    return [x for x in v if isinstance(x, str)]


def _pains(profile):
    v = profile.get("pains") or []
    return [x for x in v if isinstance(x, str)]


def _accept(profile):
    v = profile.get("acceptance") or []
    return [x for x in v if isinstance(x, str)]


def render_outline(plan, comps, profile, src_paths):
    """生成大纲正文。AI 需补之处统一用【AI 补：……】标记。"""
    label = profile.get("label", "（未命名学员群）")
    cons = profile.get("constraints") or {}
    if not isinstance(cons, dict):
        cons = {}
    budget = profile.get("time_budget") or {}
    if not isinstance(budget, dict):
        budget = {}

    dec_bucket = _match_decisions(plan, comps)
    materials, used_ids, by_type = _material_map(plan, comps)
    drops = _not_for(profile)
    scenes = _scenes(profile)
    pains = _pains(profile)
    accepts = _accept(profile)

    total = plan["total_min"]
    layout = budget.get("layout") or "待定"
    n_mod = len(plan["modules"])

    L = []
    A = L.append

    A("# 《课程大纲》")
    A("")
    A("> **生成方式**：由 `plan_to_outline.py` 从编排方案自动转换为大纲骨架。")
    A("> **上游**：`%s` + `%s` + `%s`" % (
        os.path.basename(src_paths["plan"]),
        os.path.basename(src_paths["components"]),
        os.path.basename(src_paths["profile"])))
    A("> **状态**：骨架已由脚本算定，凡方括号标记处需由 AI 补写，补齐后需重跑 `verify`。")
    A("")
    A("> ⛔ **版权约束继承**：本大纲全部内容为整理者概括，不含原文摘录；"
      "教学如需使用原文须另行取得授权。")
    A("")
    A("---")
    A("")

    # 一、课程名称
    A("## 一、课程名称")
    A("")
    A("1. %s：面向「%s」，题眼取自首模块「%s」"
      % (TODO_PREFIX + "备选一】", label, plan["modules"][0]["name"]))
    A("2. %s：以编排立意为题眼 —— %s"
      % (TODO_PREFIX + "备选二】", plan["thesis"] or "（方案未写明立意）"))
    A("3. %s" % (TODO_PREFIX + "备选三】"))
    A("")
    A("> 推荐：%s（依据：画像卡 primary_risk 与编排立意）"
      % (TODO_PREFIX + "写明推荐理由】"))
    A("")
    A("---")
    A("")

    # 二、课程定位
    A("## 二、课程定位")
    A("")
    A("**为谁设计**：%s。" % label)
    A("")
    if cons.get("power"):
        A("- **权力位置**：%s" % cons["power"])
    if cons.get("time_per_interaction"):
        A("- **单次沟通时长**：%s" % cons["time_per_interaction"])
    if cons.get("autonomy"):
        A("- **自主度**：%s" % cons["autonomy"])
    A("")
    A("**解决什么问题**（来自画像卡 pains 与编排立意）：")
    A("")
    if pains:
        for p in pains:
            A("- %s" % p)
    A("- 编排立意指向的根本问题：%s" % (plan["thesis"] or "（方案未写明立意）"))
    A("")
    A("**形成什么能力**：%s" % (TODO_PREFIX + "一句话，参照第十二节核心成果】"))
    A("")
    A("---")
    A("")

    # 三、适用对象
    A("## 三、适用对象")
    A("")
    A("**适合对象**：%s" % label)
    A("")
    if scenes:
        A("**典型工作场景**：")
        A("")
        for s in scenes:
            A("- %s" % s)
        A("")
    A("**基础要求**：%s" % (TODO_PREFIX + "如：带过团队 / 有绩效面谈经验】"))
    A("")
    if drops:
        A("**不适合对象**（由画像卡 drop 判据反推，非人工推断）：")
        A("")
        for cond, reason in drops:
            A("- 以「%s」为主要场景的人群 —— 排除理由：%s" % (cond, reason))
        A("")
    else:
        A("**不适合对象**：%s" % (TODO_PREFIX + "画像卡未给出 drop 判据】"))
        A("")
    A("---")
    A("")

    # 四、课程基本信息
    A("## 四、课程基本信息")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 建议时长 | %d 分钟（%s）|" % (total, layout))
    A("| 模块数 | %d 个 |" % n_mod)
    A("| 选用组件 | %d / %d |" % (len(used_ids), len(comps)))
    A("| 培训形式 | %s" % (TODO_PREFIX + "线下工作坊 / 线上直播 / 混合】|"))
    A("| 线上/线下 | %s" % (TODO_PREFIX + "】|"))
    A("| 课程类型 | %s" % (TODO_PREFIX + "技能训练 / 认知纠偏 / 综合】|"))
    A("")
    if plan["level_pct"]:
        A("**层级配比**（由编排方案直接带入）：")
        A("")
        A("| 层级 | %s |" % " | ".join(plan["level_pct"].keys()))
        A("|---|%s|" % "|".join(["---"] * len(plan["level_pct"])))
        A("| 分钟 | %s |" % " | ".join(plan["level_pct"].values()))
        A("")
    A("---")
    A("")

    # 五、业务与学习背景
    A("## 五、业务与学习背景")
    A("")
    if scenes:
        A("**业务现场**：")
        A("")
        for s in scenes:
            A("- %s" % s)
        A("")
    if cons.get("power_effect"):
        A("**权力结构带来的特殊性**：%s" % cons["power_effect"])
        A("")
    if cons.get("primary_risk"):
        A("**最大失败风险**：%s" % cons["primary_risk"])
        A("")
    A("**学习背景**：%s" % (TODO_PREFIX + "学员此前是否接触过同类方法、常见抵触点】"))
    A("")
    A("---")
    A("")

    # 六、课程原材料地图
    A("## 六、课程原材料地图")
    A("")
    A("| 类型 | 从组件库识别出的内容 | 数量 |")
    A("|---|---|---:|")
    for label_, shown, cnt in materials:
        A("| %s | %s | %d |" % (label_, shown, cnt))
    A("")
    if by_type:
        A("> 类型分布：%s" % "、".join(
            "`%s`×%d" % (k, v) for k, v in by_type.most_common()))
        A("")
    A("---")
    A("")

    # 七、能力差距
    A("## 七、能力差距")
    A("")
    A("| 维度 | 当前状态 | 目标状态 | 能力差距 |")
    A("|---|---|---|---|")
    A("| 知识 | %s | %s | %s |" % (
        TODO_PREFIX + "如：把请求当要求而不自知】",
        TODO_PREFIX + "能指认请求与要求的区别】",
        TODO_PREFIX + "】"))
    A("| 方法 | %s | %s | %s |" % (
        TODO_PREFIX + "】", TODO_PREFIX + "】", TODO_PREFIX + "】"))
    A("| 判断 | %s | %s | %s |" % (
        TODO_PREFIX + "】", TODO_PREFIX + "】", TODO_PREFIX + "】"))
    A("| 操作/行为 | %s | %s | %s |" % (
        TODO_PREFIX + "】", TODO_PREFIX + "】", TODO_PREFIX + "】"))
    A("")
    A("> 填写依据：画像卡 pains（当前状态）、acceptance（目标状态）、"
      "编排立意（差距的成因）。")
    A("")
    A("---")
    A("")

    # 八、学习目标
    A("## 八、学习目标")
    A("")
    by_level = OrderedDict()
    for mod in plan["modules"]:
        by_level.setdefault(mod["level"], []).append(mod)
    for lv in ("Know", "Do", "Act"):
        A("### %s" % LEVEL_LABEL.get(lv, lv))
        A("")
        mods = by_level.get(lv, [])
        if not mods:
            A("- %s" % (TODO_PREFIX + "本层级无模块，确认是否有误】"))
            A("")
            continue
        for mod in mods:
            names = "、".join(
                comps[c]["name"] for c in mod["comps"] if c in comps
            ) or "（组件待补）"
            A("- 【%s %s】围绕 %s，掌握：%s" % (
                mod["id"], mod["name"], names, TODO_PREFIX + "写出可观察的学习结果】"))
        A("")

    # 九、课程学习主线
    first = plan["modules"][0]
    last = plan["modules"][-1]
    A("## 九、课程学习主线")
    A("")
    A("> 这门课要带学员从起点走到终点：")
    A(">")
    A("> - 起点：%s" % (TODO_PREFIX + "一句话描述学员当下的状态】"))
    A("> - 终点：%s" % (TODO_PREFIX + "一句话描述结课时的状态】"))
    A("")
    A("编排立意：%s" % (plan["thesis"] or "（未写明）"))
    A("")
    A("路径（由编排方案的模块顺序决定，不另行设计）：")
    A("")
    for i, mod in enumerate(plan["modules"], 1):
        A("%d. %s %s（%s，%d 分钟）"
          % (i, mod["id"], mod["name"], mod["level"], mod["minutes"]))
    A("")
    A("> 首模块「%s」与末模块「%s」在编排方案中已确定，主线应顺着这条序列叙述。"
      % (first["name"], last["name"]))
    A("")
    A("---")
    A("")

    # 十、课程结构总览
    A("## 十、课程结构总览")
    A("")
    A("| 模块 | 模块名称 | 核心问题 | 核心内容 | 学习结果 | 对应组件资产 | 建议时长 |")
    A("|---|---|---|---|---|---|---:|")
    for mod in plan["modules"]:
        names = "、".join(comps[c]["name"] for c in mod["comps"] if c in comps)
        if not names:
            names = "（组件待补）"
        if len(names) > 60:
            names = names[:57] + "…"
        ids = "、".join(mod["comps"])
        A("| %s | %s | %s | %s | %s | %s | %d |" % (
            mod["id"], mod["name"],
            TODO_PREFIX + "一句话】", names,
            TODO_PREFIX + "可观察结果】", ids, mod["minutes"]))
    A("")
    A("| **合计** | %d 个模块 | | | | %d 个组件 | **%d** |"
      % (n_mod, len(used_ids), total))
    A("")
    A("---")
    A("")

    # 十一、模块详细大纲
    A("## 十一、模块详细大纲")
    A("")
    for mod in plan["modules"]:
        A("### %s · %s（%s，%d 分钟）" % (
            mod["id"], mod["name"], mod["level"], mod["minutes"]))
        A("")
        A("**为什么学**：")
        A("")
        reasons = dec_bucket.get(mod["id"], [])
        if reasons:
            for head, reason in reasons:
                A("- %s —— %s" % (head, reason))
            A("")
            A("> 以上取自编排方案的「关键编排决策」，不是大纲撰写时的补想。")
            A("")
        else:
            A("- %s" % (TODO_PREFIX +
                        "编排方案未对本模块单列决策，请结合下列教学价值与画像卡补写】"))
            vals = [comps[c]["value"] for c in mod["comps"]
                    if comps.get(c) and comps[c]["value"]]
            if vals:
                A("")
                A("  可参考的组件教学价值：")
                A("")
                for v in vals[:5]:
                    A("  - %s" % v)
            A("")
        A("**对应学习目标**：%s" % LEVEL_LABEL.get(mod["level"], mod["level"]))
        if mod["intent"] and mod["intent"] not in ("—", "-", ""):
            A("")
            A("**Do 意图标签**：%s" % mod["intent"])
        A("")
        A("**核心内容**（组件及概括，全部为整理者概括）：")
        A("")
        A("| 组件 | 类型 | 概括 | 教学价值 |")
        A("|---|---|---|---|")
        for cid in mod["comps"]:
            c = comps.get(cid)
            if not c:
                A("| %s | — | %s | — |" % (cid, TODO_PREFIX + "组件清单中未找到】"))
                continue
            A("| %s %s | `%s` | %s | %s |" % (
                cid, c["name"], c["type"],
                c["summary"] or "—", c["value"] or "—"))
        A("")
        A("**模块学习结果**：%s" % (TODO_PREFIX + "写可观察行为，参照第十二节】"))
        A("")
        A("**一级学习方式建议**：%s" % (mod["method"] or TODO_PREFIX + "】"))
        A("")
        A("**建议时长**：%d 分钟" % mod["minutes"])
        A("")

    # 未选用组件去向（附在第十一节之后，便于核验取舍）
    if plan["unused"]:
        A("#### 附：未选用组件的去向（每组件都须有交代）")
        A("")
        A("| ID | 组件名 | 类型 | 去向 | 理由 |")
        A("|---|---|---|---|---|")
        for cid, u in plan["unused"].items():
            A("| %s | %s | `%s` | %s | %s |" % (
                cid, u["name"], u["type"], u["dest"], u["reason"]))
        A("")

    A("---")
    A("")

    # 十二、课程核心成果
    A("## 十二、课程核心成果")
    A("")
    if accepts:
        A("**学完能做到**（取自画像卡 acceptance，属可观察行为）：")
        A("")
        for a in accepts:
            A("- %s" % a)
        A("")
    A("**带回岗位的东西**：%s" % (TODO_PREFIX + "如：一份个人高频句式清单 / 一次真实面谈的复盘】"))
    A("")
    A("---")
    A("")

    # 十三、确认
    A("## 十三、进入下一步前确认")
    A("")
    A("请确认以下七项，确认后本大纲方可交给 Step 2（课程计划）：")
    A("")
    A("1. 课程定位")
    A("2. 学习目标")
    A("3. 是否遗漏关键组件（对照第六节原材料地图与第十一节附表）")
    A("4. 模块划分")
    A("5. 模块顺序")
    A("6. 时间比例")
    A("7. 哪些模块必须加强实操")
    A("")
    A("---")
    A("")
    A("*本大纲由 `plan_to_outline.py` 生成骨架，"
      "确定性内容取自编排方案与组件清单，语义部分按方括号标记补写。*")

    return "\n".join(L) + "\n"


def list_todos(text):
    """统计待补标记。

    口径必须带冒号：文档里会出现「按【AI 补】标记补写」这类说明文字，
    不要求冒号的话，说明文字会被当成待补项统计进来，strict 模式永远过不去。
    """
    return re.findall(r"【AI 补：[^】]*】", text)


# ────────────────────────────────────────────────────────────
# 三、校验
# ────────────────────────────────────────────────────────────

def verify(outline_text, plan, comps):
    """校验大纲是否忠实地承接了编排方案。返回 (problems, notes)。

    这里只查「信息有没有丢、有没有错」，不查行文质量——
    质量由 fire-course-dev 自己的阶段闸门管。
    """
    problems, notes = [], []

    # 1. 十三个小节齐全
    need = ["一、课程名称", "二、课程定位", "三、适用对象", "四、课程基本信息",
            "五、业务与学习背景", "六、课程原材料地图", "七、能力差距",
            "八、学习目标", "九、课程学习主线", "十、课程结构总览",
            "十一、模块详细大纲", "十二、课程核心成果", "十三、进入下一步前确认"]
    miss = [x for x in need if ("## " + x) not in outline_text]
    if miss:
        problems.append("缺少小节：%s" % "、".join(miss))
    else:
        notes.append("13 个小节齐全")

    # 2. 模块不漏不多
    in_outline = OrderedDict()
    for ln in outline_text.split("\n"):
        m = re.match(r"^###\s*(M\d+)\s*·\s*(.+?)（", ln.strip())
        if m:
            in_outline[m.group(1)] = m.group(2).strip()
    plan_ids = [m["id"] for m in plan["modules"]]
    lost = [x for x in plan_ids if x not in in_outline]
    extra = [x for x in in_outline if x not in plan_ids]
    if lost:
        problems.append("大纲丢失模块：%s" % "、".join(lost))
    if extra:
        problems.append("大纲多出模块：%s" % "、".join(extra))
    if not lost and not extra:
        notes.append("模块一一对应（%d 个）" % len(plan_ids))

    # 3. 模块名一致（防改名）
    name_map = {m["id"]: m["name"] for m in plan["modules"]}
    diff = [(k, name_map[k], in_outline[k]) for k in in_outline
            if k in name_map and in_outline[k] != name_map[k]]
    if diff:
        problems.append("模块名被改动：" + "；".join(
            "%s「%s」→「%s」" % d for d in diff))
    else:
        notes.append("模块名与编排方案一致")

    # 4. 时长合计一致
    mins = [int(x) for x in re.findall(r"建议时长\*\*：(\d+) 分钟", outline_text)]
    s = sum(mins)
    if mins and s != plan["total_min"]:
        problems.append("模块时长合计 %d ≠ 编排方案 %d" % (s, plan["total_min"]))
    elif mins:
        notes.append("时长合计 %d 分钟，与方案一致" % s)

    # 5. 选用组件必须真的落进模块核心内容表。
    #    判据不是「文档里出现过这个编号」——原材料地图和总览表也会提到它，
    #    那样查等于没查。必须落在第十一节的模块表格行里。
    used = []
    for m in plan["modules"]:
        used.extend(m["comps"])
    used = list(dict.fromkeys(used))

    sec = re.search(r"## 十一、模块详细大纲(.*?)(?=\n## |\Z)", outline_text, re.S)
    body = sec.group(1) if sec else ""
    landed = set()
    for ln in body.split("\n"):
        m = re.match(r"^\|\s*(C\d{3})\b", ln.strip())
        if m:
            landed.add(m.group(1))
    absent = [c for c in used if c not in landed]
    if absent:
        problems.append("选用组件未落进模块核心内容表：%s" % "、".join(absent))
    else:
        notes.append("选用组件 %d 个全部落进模块表" % len(used))

    # 6. 未知组件号（防 AI 补写时编造 ID）
    known = set(comps.keys())
    bogus = sorted(set(re.findall(r"C\d{3}", outline_text)) - known)
    if bogus:
        problems.append("出现组件清单里没有的编号：%s" % "、".join(bogus))
    else:
        notes.append("未出现编造的组件编号")

    # 7. 未选用组件必须交代去向
    if plan["unused"]:
        if "未选用组件的去向" not in outline_text:
            problems.append("方案有 %d 个未选用组件，大纲里没有交代去向"
                            % len(plan["unused"]))
        else:
            notes.append("未选用组件 %d 个已交代去向" % len(plan["unused"]))

    # 8. 待补项统计（默认提示，strict 时才算失败）
    todos = list_todos(outline_text)
    notes.append("待补写标记 %d 处" % len(todos))
    return problems, notes, todos


# ────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="编排方案 → 课程大纲（Stage 4 → Stage 5 交接转换器）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gen", help="生成大纲")
    g.add_argument("--plan", required=True, help="编排方案 md")
    g.add_argument("--components", required=True, help="组件清单 md")
    g.add_argument("--profile", required=True, help="学员画像卡 yaml")
    g.add_argument("--out", required=True, help="输出大纲 md")
    g.add_argument("--strict", action="store_true",
                   help="存在未补写的【AI 补】标记时按失败处理")

    v = sub.add_parser("verify", help="校验已有大纲")
    v.add_argument("--outline", required=True)
    v.add_argument("--plan", required=True)
    v.add_argument("--components", required=True)
    v.add_argument("--strict", action="store_true")

    a = ap.parse_args()

    if a.cmd == "gen":
        plan_path, comp_path = a.plan, a.components
        outline_path = a.out
    else:
        plan_path, comp_path = a.plan, a.components
        outline_path = a.outline

    comps, err = load_components(comp_path)
    if err:
        print("[输入不可用] " + err)
        sys.exit(2)
    plan, err = load_plan(plan_path)
    if err:
        print("[输入不可用] " + err)
        sys.exit(2)

    if a.cmd == "gen":
        profile, err = load_profile(a.profile)
        if err:
            print("[输入不可用] " + err)
            sys.exit(2)
        src = {"plan": a.plan, "components": a.components, "profile": a.profile}
        text = render_outline(plan, comps, profile, src)
        io.open(a.out, "w", encoding="utf-8").write(text)
        print("已生成：%s" % a.out)
        print("  模块 %d 个 · 选用组件 %d 个 · 总时长 %d 分钟"
              % (len(plan["modules"]),
                 len(set(c for m in plan["modules"] for c in m["comps"])),
                 plan["total_min"]))
    else:
        if not os.path.isfile(outline_path):
            print("[输入不可用] 大纲不存在：%s" % outline_path)
            sys.exit(2)
        text = io.open(outline_path, encoding="utf-8").read()
        print("校验：%s" % outline_path)

    problems, notes, todos = verify(text, plan, comps)

    print("\n" + "=" * 68)
    for n in notes:
        print("  · " + n)
    if todos:
        uniq = sorted(set(todos))
        print("\n  待补写（%d 处，去重后 %d 类）：" % (len(todos), len(uniq)))
        for t in uniq[:12]:
            print("    " + t)
        if len(uniq) > 12:
            print("    …… 其余 %d 类" % (len(uniq) - 12))
    print("=" * 68)

    if problems:
        print("❌ 未通过：")
        for p in problems:
            print("  - " + p)
        sys.exit(1)

    if a.strict and todos:
        print("❌ 未通过：strict 模式下不允许残留 %d 处待补标记" % len(todos))
        sys.exit(1)

    print("✅ 通过 —— 大纲与编排方案一致")
    sys.exit(0)


if __name__ == "__main__":
    main()
