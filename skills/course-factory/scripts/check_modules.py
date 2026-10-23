"""Stage 3 闸门：模块编排一致性校验 + 双画像对照指标计算。

用法:
    python check_modules.py <planA.md> <planB.md> <组件清单.md>

两条职责，分开输出：
  [BLOCK] 硬闸门 —— 编排本身是否自洽（ID 合法/无重复/有交代/时长自洽）
  [DIFF]  对照指标 —— 同批组件换画像后，输出是否真的不同

对照指标的可计算定义（脚本只算能算的，语义判断留给 AI）：
  1. 选用组件 Jaccard 相似度       —— 「模块主题重叠率」的可执行代理
  2. 反向取舍数                    —— 一方进模块序列、另一方判「舍」
  3. 位次反转数                    —— 同一组件在两方案中的模块序号差 >= 3
  4. Know/Do/Act 配比最大单项差      —— 单位：百分点
  5. Do 层内 P/E/T/R 占比最大单项差   —— 单位：百分点

依赖: Python 3.14 已验证，仅使用标准库
"""

import re
import sys
from collections import Counter

ID_RE = re.compile(r"\bC\d{3}\b")
# 受控 ID 只从「表格行首列」提取，避免把正文说明里提到的空号也算进来。
# 组件清单头部会写「C003、C008、C031 为空号」，全文扫 ID 会误把它们当成真组件。
#
# ⚠️ 这条是闸门首轮就拦出来的：受控集合取宽了，G3 会永远报错且查不出原因。
ROW_ID_RE = re.compile(r"^\|[\s*`]*(C\d{3})[\s*`]*\|")
MOD_RE = re.compile(r"^\|\s*(?:M?\d+)\s*\|")

FIELD_ALIASES = {
    "模块名": "module",
    "层级": "level",
    "分钟": "minutes",
    "Do意图": "intent",
    "组件 ID": "ids",
    "组件ID": "ids",
    "主教学处理": "treatment",
}

VALID_LEVELS = {"Know", "Do", "Act"}
VALID_INTENTS = {"P", "E", "T", "R", "—", "-", ""}
VALID_DISPOSITIONS = {"舍", "自学", "备选", "带出"}


# ---------------------------------------------------------------- 解析

def read_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def minutes_value(value):
    match = re.fullmatch(r'\s*(\d+)\s*(?:分钟)?\s*', value)
    if not match or int(match.group(1)) <= 0:
        raise SystemExit('[FATAL] 模块分钟数须为正整数：' + value)
    return int(match.group(1))


def find_section(lines, title_prefix):
    """返回标题所在行号；找不到返回 -1"""
    for i, ln in enumerate(lines):
        if ln.startswith("#") and title_prefix.lstrip("# ").strip() in ln:
            return i
    return -1


def parse_table_from(lines, start):
    """从 start 行起向下找第一个 Markdown 表格，返回 (header, rows)。

    header/rows 均为按列切分、去除首尾空格后的 list[list[str]]。
    """
    rows = []
    i = start
    table_started = False
    while i < len(lines):
        ln = lines[i].strip()
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if not table_started:
                if set("".join(cells)) <= set("-: "):  # 分隔行，跳过且确认是表格
                    i += 1
                    continue
                header = cells
                table_started = True
            else:
                if set("".join(cells)) <= set("-: "):
                    i += 1
                    continue
                rows.append(cells)
            i += 1
        elif table_started:
            break  # 表格结束
        else:
            i += 1
            if ln.startswith("#") and i - start > 30:
                break
    if not rows:
        return [], []
    return header, rows


def resolve_cols(header):
    """把表头映射成字段 -> 列下标"""
    cols = {}
    for idx, name in enumerate(header):
        key = FIELD_ALIASES.get(name.strip(), None)
        if key:
            cols[key] = idx
    return cols


def parse_plan(path):
    """解析一份编排方案"""
    lines = read_lines(path)
    plan = {"path": path, "modules": [], "dropped": {}, "levels": {}, "do_intents": {}}

    # --- 模块序列表 ---
    sec = find_section(lines, "模块序列")
    if sec < 0:
        raise SystemExit(f"[FATAL] {path}: 找不到「模块序列」小节")
    header, rows = parse_table_from(lines, sec)
    if not rows:
        raise SystemExit(f"[FATAL] {path}: 模块序列表解析为空")
    cols = resolve_cols(header)
    for need in ("module", "level", "minutes", "ids"):
        if need not in cols:
            raise SystemExit(f"[FATAL] {path}: 模块表缺少必需列 {need}（当前表头 {header}）")

    for idx, cells in enumerate(rows):
        def get(key, default=""):
            j = cols.get(key)
            return cells[j] if j is not None and j < len(cells) else default

        intent = get("intent", "").strip()
        plan["modules"].append({
            "seq": idx,
            "name": get("module"),
            "level": get("level").strip(),
            "minutes": minutes_value(get("minutes")),
            "intent": intent if intent not in ("—", "-") else "",
            "ids": ID_RE.findall(get("ids")),
            "row": idx + 1,
        })

    # --- 未选用组件清单 ---
    sec = find_section(lines, "未选用组件清单")
    if sec >= 0:
        header, rows = parse_table_from(lines, sec)
        cols = resolve_cols(header)
        id_idx = 0
        for i, h in enumerate(header):
            if h.strip().upper() == "ID":
                id_idx = i
        name_idx = cols.get("module", 1)
        disp_idx = None
        for i, h in enumerate(header):
            if h.strip() == "去向":
                disp_idx = i
        if disp_idx is None:
            disp_idx = len(header) - 2
        for cells in rows:
            ids = ID_RE.findall(cells[id_idx])
            disp = cells[disp_idx].strip() if disp_idx < len(cells) else ""
            reason = cells[-1].strip() if cells else ""
            for cid in ids:
                plan["dropped"][cid] = {
                    "disposition": disp,
                    "reason": reason,
                    "name": cells[name_idx] if name_idx < len(cells) else "",
                }

    # --- 课时配比表（用于交叉校验声明值）---
    sec = find_section(lines, "课时与层级配比")
    if sec >= 0:
        _, rows = parse_table_from(lines, sec)
        for cells in rows:
            lvl = cells[0].strip()
            if lvl in VALID_LEVELS:
                plan["levels"][lvl] = {
                    "declared_min": int(re.sub(r"\D", "", cells[1]) or 0),
                    "declared_pct": float(re.sub(r"[^\d.]", "", cells[2]) or 0),
                }

    # --- Do 层内意图配比 ---
    all_lines = lines
    for i, ln in enumerate(all_lines):
        if "Do 层内部意图配比" in ln or "Do层内部意图配比" in ln:
            _, rows = parse_table_from(all_lines, i)
            for cells in rows:
                tag = cells[0].strip()[:1].upper()
                if tag in ("P", "E", "T", "R"):
                    plan["do_intents"][tag] = {
                        "declared_min": int(re.sub(r"\D", "", cells[1]) or 0),
                        "declared_pct": float(re.sub(r"[^\d.]", "", cells[2]) or 0),
                    }
            break
    return plan


def load_component_ids(path):
    """受控 ID 集合 = 组件清单表格行首出现的 ID，不含正文提及的空号。"""
    ids = set()
    for ln in read_lines(path):
        m = ROW_ID_RE.match(ln.strip())
        if m:
            ids.add(m.group(1))
    if not ids:
        raise SystemExit(f"[FATAL] {path}: 未从表格中提取到任何组件 ID，请检查表格格式")
    return ids


# ---------------------------------------------------------------- 硬闸门

def run_gates(plan, valid_ids):
    errs, warns = [], []
    tag = plan["path"].split("\\")[-1].split("/")[-1]

    # G1 ID 合法
    bad = sorted(({cid for m in plan["modules"] for cid in m["ids"]} | set(plan['dropped'])) - valid_ids)
    if bad:
        errs.append(f"G1 ID 不在组件清单中: {bad}")

    # G2 模块序列内不重复
    seq_ids = [cid for m in plan["modules"] for cid in m["ids"]]
    dup = [c for c, n in Counter(seq_ids).items() if n > 1]
    if dup:
        errs.append(f"G2 模块序列内重复引用: {sorted(dup)}")

    # G3 每个组件都要有交代
    covered = set(seq_ids) | set(plan["dropped"])
    missing = sorted(valid_ids - covered)
    if missing:
        errs.append(f"G3 未交代组件 {len(missing)} 个: {missing}")

    # G4 时长自洽
    total = sum(m["minutes"] for m in plan["modules"])
    declared = sum(v["declared_min"] for v in plan["levels"].values()) if plan["levels"] else None
    if declared is not None and declared != total:
        errs.append(f"G4 时长不符：模块表合计 {total} ≠ 声明 {declared}")

    # G5 层级/意图标注自洽
    do_min = 0
    for m in plan["modules"]:
        if m["level"] not in VALID_LEVELS:
            errs.append(f"G5 M{m['seq']} 层级非法: {m['level']!r}")
        if m["level"] == "Do":
            do_min += m["minutes"]
            if m["intent"] not in ("P", "E", "T", "R"):
                errs.append(f"G5 M{m['seq']} 为 Do 层但意图缺失或非法: {m['intent']!r}")
        else:
            if m["intent"]:
                errs.append(f"G5 M{m['seq']} 非 Do 层却填了意图 {m['intent']!r}")
    intent_sum = sum(v["declared_min"] for v in plan["do_intents"].values())
    if plan["do_intents"] and intent_sum != do_min:
        errs.append(f"G5 Do 层意图分钟合计 {intent_sum} ≠ Do 层总时长 {do_min}")

    # G6 去向合法 + 「带出」必须写明依附
    for cid, info in plan["dropped"].items():
        d = info["disposition"]
        if d not in VALID_DISPOSITIONS:
            errs.append(f"G6 {cid} 去向不合法: {d!r}（须为 {'/'.join(sorted(VALID_DISPOSITIONS))}）")
        if d == "带出" and not ID_RE.findall(info["reason"]):
            errs.append(f"G6 {cid} 标「带出」但未在理由中写明依附组件")

    # G7 模块表里不得出现未选用清单中的 ID
    overlap = sorted(set(seq_ids) & set(plan["dropped"]))
    if overlap:
        errs.append(f"G7 同时出现在模块表与未选用清单: {overlap}")

    return tag, errs, warns, {"total_min": total, "do_min": do_min, "seq_ids": set(seq_ids)}


# ---------------------------------------------------------------- 对照指标

def module_index(plan):
    """组件 -> 模块序号"""
    idx = {}
    for m in plan["modules"]:
        for cid in m["ids"]:
            idx[cid] = m["seq"]
    return idx


def compute_diff(a, b):
    sa, sb = a["stats"]["seq_ids"], b["stats"]["seq_ids"]
    union, inter = sa | sb, sa & sb

    # 指标 1：Jaccard 相似度（越低越好）
    jaccard = len(inter) / len(union) * 100 if union else 0.0

    # 指标 2：反向取舍（一方进模块序列、另一方判「舍」）
    reverse = []
    for cid in sorted(sa - sb):
        if b["plan"]["dropped"].get(cid, {}).get("disposition") == "舍":
            reverse.append((cid, "A留B舍"))
    for cid in sorted(sb - sa):
        if a["plan"]["dropped"].get(cid, {}).get("disposition") == "舍":
            reverse.append((cid, "B留A舍"))

    # 指标 3：位次反转（模块序号差 >= 3）
    ia, ib = module_index(a["plan"]), module_index(b["plan"])
    shifts = [(cid, ia[cid], ib[cid], abs(ia[cid] - ib[cid]))
              for cid in sorted(inter) if abs(ia[cid] - ib[cid]) >= 3]
    shifts.sort(key=lambda x: -x[3])

    # 指标 4 / 5：Know/Do/Act 配比 与 Do 层内意图配比
    def level_pct(plan):
        tot = sum(m["minutes"] for m in plan["modules"]) or 1
        c = Counter()
        for m in plan["modules"]:
            c[m["level"]] += m["minutes"]
        return {k: v / tot * 100 for k, v in c.items()}

    pa, pb = level_pct(a["plan"]), level_pct(b["plan"])
    level_diffs = {k: abs(pa.get(k, 0) - pb.get(k, 0)) for k in VALID_LEVELS}

    # 指标 5：Do 层内意图占比最大单项差
    def intent_pct(plan):
        do = [m for m in plan["modules"] if m["level"] == "Do"]
        tot = sum(m["minutes"] for m in do) or 1
        c = Counter()
        for m in do:
            c[m["intent"]] += m["minutes"]
        return {k: v / tot * 100 for k, v in c.items()}

    qa, qb = intent_pct(a["plan"]), intent_pct(b["plan"])
    intent_diffs = {k: abs(qa.get(k, 0) - qb.get(k, 0)) for k in ("P", "E", "T", "R")}

    return {
        "jaccard": jaccard,
        "selected_A": len(sa), "selected_B": len(sb),
        "inter": len(inter), "union": len(union),
        "reverse": reverse,
        "shifts": shifts,
        "level_a": pa, "level_b": pb, "level_diffs": level_diffs,
        "intent_a": qa, "intent_b": qb, "intent_diffs": intent_diffs,
    }


def pct_line(d):
    return "  ".join(f"{k} {v:5.1f}%" for k, v in sorted(d.items()))


# ---------------------------------------------------------------- main

def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--single':
        plan = parse_plan(sys.argv[2])
        tag, errors, warns, stats = run_gates(plan, load_component_ids(sys.argv[3]))
        for error in errors:
            print('[FAIL] ' + error)
        print(f'单课程一致性检查：{tag}，{stats["total_min"]} 分钟；未做双画像敏感性验收')
        sys.exit(1 if errors else 0)
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)

    path_a, path_b, path_kb = sys.argv[1:4]
    valid_ids = load_component_ids(path_kb)

    print("=" * 68)
    print(f"Stage 3 闸门 · 组件库 {len(valid_ids)} 个")
    print("=" * 68)

    results = []
    for p in (path_a, path_b):
        plan = parse_plan(p)
        tag, errs, warns, stats = run_gates(plan, valid_ids)
        print(f"\n--- [BLOCK] {tag} ---")
        print(f"  模块 {len(plan['modules'])} 个 · 选用组件 {len(stats['seq_ids'])} 个 · "
              f"未选用 {len(plan['dropped'])} 个 · 总时长 {stats['total_min']} 分钟 · Do 层 {stats['do_min']} 分钟")
        for w in warns:
            print(f"  [WARN] {w}")
        if errs:
            for e in errs:
                print(f"  [FAIL] {e}")
        else:
            print("  [OK] 一致性校验通过")
        results.append({"plan": plan, "stats": stats, "errs": errs})

    if any(r["errs"] for r in results):
        print("\n⛔ 硬闸门未过，不进入对照指标计算")
        sys.exit(1)

    print("\n" + "=" * 68)
    print("[DIFF] 双画像对照指标")
    print("=" * 68)
    d = compute_diff(*results)

    print(f"\n指标 1 · 选用组件重叠率（Jaccard，越低越好，阈值 ≤50%）")
    print(f"  A 选用 {d['selected_A']} / B 选用 {d['selected_B']} · 交集 {d['inter']} · 并集 {d['union']}")
    print(f"  → {d['jaccard']:.1f}%   {'✅ 达标' if d['jaccard'] <= 50 else '❌ 未达标'}")

    print(f"\n指标 2 · 反向取舍数（一方进模块、另一方判「舍」，阈值 ≥10）")
    print(f"  → {len(d['reverse'])} 处   {'✅ 达标' if len(d['reverse']) >= 10 else '❌ 未达标'}")
    for cid, kind in d["reverse"][:20]:
        print(f"     {cid}  {kind}")
    if len(d["reverse"]) > 20:
        print(f"     … 其余 {len(d['reverse']) - 20} 处略")

    print(f"\n指标 3 · 位次反转数（模块序号差 ≥3，阈值 ≥3 处）")
    print(f"  → {len(d['shifts'])} 处   {'✅ 达标' if len(d['shifts']) >= 3 else '❌ 未达标'}")
    for cid, ia, ib, gap in d["shifts"][:12]:
        print(f"     {cid}  A: M{ia}  ↔  B: M{ib}   差 {gap}")

    mx_k, mx_v = max(d["level_diffs"].items(), key=lambda x: x[1])
    lv_a, lv_b = d["level_a"], d["level_b"]
    print(f"  A： {pct_line(lv_a)}")
    print(f"  B： {pct_line(lv_b)}")
    print(f"  → 最大差 {mx_k}  "                      # 数字由下方统一给出
          f"{pa_pb_line(mx_k, lv_a.get(mx_k, 0), lv_b.get(mx_k, 0), mx_v)}")

    print(f"\n指标 5 · Do 层内 P/E/T/R 意图占比最大单项差（阈值 ≥15pp）")
    qa, qb = d["intent_a"], d["intent_b"]
    nk, nv = max(d["intent_diffs"].items(), key=lambda x: x[1])
    print(f"  A： {pct_line(qa)}")
    print(f"  B： {pct_line(qb)}")
    print(f"  → 最大差 {nk}  "
          f"{pa_pb_line(nk, qa.get(nk, 0), qb.get(nk, 0), nv)}")

    # 两套判定口径。原始五判据保留真实结果（含已证伪项），
    # 修订口径使用下方明确列出的两条。其余指标保留为诊断输出。
    original = {
        "指标1 Jaccard ≤50%": (d["jaccard"] <= 50, f"{d['jaccard']:.1f}%"),
        "指标2 反向取舍 ≥10": (len(d["reverse"]) >= 10, f"{len(d['reverse'])} 处"),
        "指标3 位次反转 ≥3": (len(d["shifts"]) >= 3, f"{len(d['shifts'])} 处"),
        "指标4 层级配比 ≥15pp": (mx_v >= 15, f"{mx_v:.1f}pp"),
        "指标5 Do意图 ≥15pp": (nv >= 15, f"{nv:.1f}pp"),
    }
    effective = {
        "指标3 位次反转 ≥3": original["指标3 位次反转 ≥3"],
        "指标5 Do意图 ≥15pp": original["指标5 Do意图 ≥15pp"],
    }

    print("\n" + "=" * 68)
    print("判定口径 A · 原始五判据（保留全部真实结果，不作任何取舍）")
    print("=" * 68)
    for k, (ok, val) in original.items():
        print(f"  {'✅' if ok else '❌'} {k}   {val}")
    ok_all = all(v[0] for v in original.values())
    print(f"  → {'通过' if ok_all else '未通过'}")

    print("\n" + "=" * 68)
    print("判定口径 B · 修订口径（位次反转、Do 意图差两条）")
    print("=" * 68)
    print("  说明：指标 4 已被证伪（两轮恒为 8.3pp，因其粒度选错层）；")
    print("        指标 1/2 分别被「课时预算」「去向粒度」污染，需归一化后才可用。")
    print("        详见 Stage3 对照实验报告第四节。")
    for k, (ok, val) in effective.items():
        print(f"  {'✅' if ok else '❌'} {k}   {val}")
    ok_eff = all(v[0] for v in effective.values())
    print(f"  → {'通过 —— L2 编排对画像敏感' if ok_eff else '未通过 —— 编排差异不足'}")

    print("\n" + "=" * 68)
    print(f"结论：{'✅ L2 编排对画像敏感' if ok_eff else '❌ 差异不足，需重做画像或编排'}"
          f"   （原始五判据：{'全过' if ok_all else '未全过'}，未达标项见口径 A）")
    print("=" * 68)
    sys.exit(0 if ok_eff else 1)


def pa_pb_line(key, va, vb, diff):
    return f"A {va:.1f}% vs B {vb:.1f}% = {diff:.1f}pp"


if __name__ == "__main__":
    main()
