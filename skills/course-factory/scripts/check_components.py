# -*- coding: utf-8 -*-
"""组件清单自检（L2 编排层 · Stage 2 闸门）

校验五件事，任一不过不得进入 Stage 3 编排：
  1. ID 不重号——但允许"索引引用"（后出现的同名同类型行视为引用，给 warn）
  2. type 必须是 taxonomy-v2 受控类型，且不得为 course（课程编排属 L2 职责）
  3. 每条组件必须有 locator——取所在最近的「### 第X章」标题继承
  4. 声明的数量必须与表格实际行数一致（防止"写了 66 个实际 63 个"）
  5. 编号缺号必须有明文说明

用法：
  python check_components.py <组件清单.md>
"""
import io
import re
import sys
from collections import Counter

# taxonomy-v2 受控类型（course 已被 L2 独占，组件层不得出现）
CONTROLLED = {
    'concept', 'principle', 'viewpoint', 'misconception', 'guideline',
    'framework', 'rule', 'workflow', 'tool', 'solution', 'scene', 'case',
    'analogy', 'story', 'boundary', 'source', 'data', 'quote', 'paradigm',
}
BANNED = {'course'}

# 常见伪类型提示：这些"类型"在 taxonomy-v2 里不存在，多是教学处理方式被误当知识类型
PSEUDO_TYPES = {
    'exercise': '练习是教学处理方式，不是知识类型。归入 tool／misconception 等本体类型，练习属性写进备注',
    'practice': '同上，练习不是知识类型',
    'method': '请使用 tool（如何用某个工具得到结果）',
    'technique': '请使用 tool',
    'knowledge': '过于笼统，请细分到 concept／principle／rule 等',
    'skill': '技能是学习目标，不是知识组件类型',
}

ROW = re.compile(
    r'^\|\s*\*{0,2}(C\d+)\*{0,2}\s*\|\s*([^|]+?)\s*\|\s*([a-zA-Z, +\-]+?)\s*\|\s*([^|]+)\|'
)
CHAPTER = re.compile(r'^###\s*(第[一二三四五六七八九十]+章)')

# locator 两种写法都支持：
#   ① 表格单元格里显式写「第X章」——优先采用
#   ② 不写，则继承所在最近的「### 第X章」标题
LOC = re.compile(r'第[一二三四五六七八九十]+章')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    text = io.open(path, encoding='utf-8').read()
    lines = text.split('\n')

    seen, errors, warns = {}, [], []
    current_chapter = None

    for i, l in enumerate(lines, 1):
        ch = CHAPTER.match(l)
        if ch:
            current_chapter = ch.group(1)
            continue

        m = ROW.match(l)
        if not m:
            continue
        cid, name, typ, _ = m.groups()
        types = [t.strip() for t in re.split(r'[,\s]+', typ)
                 if t.strip() and t.strip() != '+']
        name = name.strip()

        # locator：单元格显式写法优先，否则继承最近章节标题
        loc_cell = LOC.findall(l)
        chapter = loc_cell[0] if loc_cell else current_chapter

        # --- 规则 1：ID 重号 vs 索引引用 ---
        if cid in seen:
            prev = seen[cid]
            if prev['name'] == name and prev['types'] == types:
                warns.append(f'行{i}：{cid} 与行{prev["line"]}重复（内容一致，判为索引引用）')
            else:
                errors.append(
                    f'行{i}：{cid} 重复定义且与首次不一致\n'
                    f'          首次(行{prev["line"]}): {prev["name"]} / {prev["types"]}\n'
                    f'          本次: {name} / {types}')
            continue
        seen[cid] = {'line': i, 'types': types, 'name': name, 'chapter': chapter}

        # --- 规则 2：类型合法性 ---
        for t in types:
            if t in BANNED:
                errors.append(f'行{i}：{cid} 使用了被禁用类型「{t}」——'
                              f'课程编排属 L2 职责，组件层不得产出')
            elif t in PSEUDO_TYPES:
                errors.append(f'行{i}：{cid} 类型「{t}」不存在于 taxonomy-v2。'
                              f'{PSEUDO_TYPES[t]}')
            elif t not in CONTROLLED:
                errors.append(f'行{i}：{cid} 类型「{t}」不在 taxonomy-v2 受控类型内')

        if not types:
            errors.append(f'行{i}：{cid} 缺少 type 字段')

        # --- 规则 3：locator（显式优先，否则继承）---
        if not chapter:
            errors.append(f'行{i}：{cid} 所在章节未识别，无法定位（locator 缺失）')

    # --- 规则 4：数量一致性 ---
    actual = len(seen)
    if actual == 0:
        errors.append('未解析到任何组件，空清单或格式不受支持不得放行')
    for i, line in enumerate(lines, 1):
        if re.match(r'^\|\s*[*`]*(C\d+)', line) and not ROW.match(line):
            errors.append(f'行{i}：组件行格式无法解析，不得静默跳过')
    m_dec = re.search(r'\*\*(\d+)\s*个组件\*\*', text)
    declared = int(m_dec.group(1)) if m_dec else None
    if declared is not None and declared != actual:
        errors.append(f'数量不一致：文件声明 {declared} 个，表格实际 {actual} 个')

    # --- 规则 5：编号缺号说明 ---
    if seen:
        nums = sorted(int(k[1:]) for k in seen)
        missing = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
        if missing and '编号不连续说明' not in text:
            errors.append(f'编号缺号 {missing}，且文件未提供缺号说明')
        elif missing:
            warns.append(f'编号缺号 {missing}（文件已提供说明，可接受）')

    if seen:
        no_loc = [k for k, v in seen.items() if not v['chapter']]
        if no_loc:
            warns.append(f'{len(no_loc)} 个组件无章节定位：{no_loc[:8]}')

    print(f'组件清单自检：{path.split(chr(92))[-1]}')
    print('-' * 66)
    print(f'  唯一组件数      : {actual}')
    print(f'  文件声明数      : {declared or "未声明"}')
    if seen:
        maint = Counter(v['types'][0] if v['types'] else '缺失类型' for v in seen.values())
        print(f'  主类型分布      : ' + ', '.join(f'{k}×{v}' for k, v in maint.most_common()))
        ch_cnt = Counter(v['chapter'] for v in seen.values())
        print(f'  章节覆盖        : {len([c for c in ch_cnt if c])} 章')
    print()
    for w in warns:
        print(f'  ⚠️  {w}')
    if not warns:
        print('  无警告')
    print()
    if errors:
        print(f'  ❌ {len(errors)} 项未过：')
        for e in errors:
            print(f'     - {e}')
        print()
        print('  ⛔ 不得进入 Stage 3 编排')
        return 1
    print('  ✅ 闸门通过，可进入 Stage 3 编排')
    return 0


if __name__ == '__main__':
    sys.exit(main())
