# -*- coding: utf-8 -*-
"""Course Pipeline · 流水线总控状态机（L0）

总控自己不产出任何教学内容，只做三件事：
  1. 路由  —— 当前该跑哪个阶段、调谁的执行脚本
  2. 闸门  —— 每个阶段出口真跑检查脚本，退码决定放不放行
  3. 状态机 —— 把进度与产物路径持久化，中断后可续跑，不必从头来

命令：
  python pipeline.py init   --project <目录> --source <素材> [--profile <yaml>] [--copyright relaxed --note 理由]
  python pipeline.py status
  python pipeline.py enter  <stage>
  python pipeline.py artifact <stage> <路径...>
  python pipeline.py check  <stage>
  python pipeline.py advance
  python pipeline.py reset  <stage>

退码：0 = 放行；1 = 闸门未过；2 = 条件不足（BLOCKED，不算失败）
"""
import argparse
import io
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILLS = Path.home() / '.workbuddy' / 'skills'
STATE_NAME = 'pipeline-state.json'

# ── 阶段定义：id → (名称, 执行者, 闸门类型, 闸门目标) ───────────────────────
STAGES = [
    {
        'id': '0-intake', 'name': '接单校验', 'owner': 'course-pipeline',
        'out': '已确认的版权口径 + 可用画像卡 + 可读素材',
        'gate': {'kind': 'rule', 'fn': 'intake'},
    },
    {
        'id': '1-extract', 'name': 'L1 萃取', 'owner': 'chaoyun-knowledge-base-builder',
        'out': 'fragments.jsonl（及其 sources/derived）',
        'gate': {'kind': 'rule', 'fn': 'extract'},
    },
    {
        'id': '2-restore', 'name': 'L1.5 结构还原', 'owner': 'course-factory',
        'out': 'chapters.json',
        'gate': {'kind': 'rule', 'fn': 'restore'},
    },
    {
        'id': '3-components', 'name': 'L2 组件提取', 'owner': 'course-factory',
        'out': '组件清单.md',
        'gate': {'kind': 'script', 'script': 'course-factory/scripts/check_components.py', 'args': 'components'},
    },
    {
        'id': '4-modules', 'name': 'L2 模块编排', 'owner': 'course-factory',
        'out': '编排方案A.md + 编排方案B.md（双画像对照）',
        'gate': {'kind': 'script', 'script': 'course-factory/scripts/check_modules.py', 'args': 'modules'},
    },
    {
        'id': '5-teaching', 'name': 'L3 教学流水线', 'owner': 'fire-course-dev',
        'out': '00–05 七件套',
        'gate': {'kind': 'rule', 'fn': 'teaching'},
    },
    {
        'id': '6-delivery', 'name': '出厂', 'owner': 'course-pipeline',
        'out': '全部交付物过卫生与版权抽查',
        'gate': {'kind': 'script', 'script': 'course-factory/scripts/check_text_hygiene.py', 'args': 'delivery'},
    },
]
STAGE_IDS = [s['id'] for s in STAGES]

# L3 教学流水线应产出的文件（文件名特征）
TEACHING_ARTIFACTS = [
    ('培训需求说明书', '培训需求说明书*.md'),
    ('课程大纲', '课程大纲*.md'),
    ('详细课程计划', '*课程计划*.md'),
    ('学员讲义', '*学员课程讲义*.md'),
    ('教员手册', '*教员课程指导手册*.md'),
    ('PPT 页稿', '*Storyboard*.md'),
]


# ── 状态文件读写 ─────────────────────────────────────────────────────────
def state_path(project):
    return Path(project) / STATE_NAME


def load_state(project):
    p = state_path(project)
    if not p.exists():
        print(f'[FATAL] 未找到 {p} —— 先跑 init')
        sys.exit(2)
    return json.loads(io.open(p, encoding='utf-8').read()), p


def save_state(project, st):
    st['updated_at'] = datetime.now().isoformat(timespec='seconds')
    io.open(state_path(project), 'w', encoding='utf-8').write(
        json.dumps(st, ensure_ascii=False, indent=1))


def log(st, action):
    st.setdefault('history', []).append({
        'ts': datetime.now().isoformat(timespec='seconds'), 'action': action})


# ── 产物发现 ─────────────────────────────────────────────────────────────
# 数据类产物（chapters.json / fragments.jsonl）就住在 kb/ 下，扫它们时不能排除 kb
# ——曾经把 kb 放进通用排除表，导致自己把自己的产物判成"没产出"。
SKIP_FOR_DATA = {'.git', 'build', 'node_modules'}
# 交付物类（md）扫描才需要排除中间目录，避免把 kb 里的中间文件当成品出厂
SKIP_FOR_MD = SKIP_FOR_DATA | {'kb', 'blind', 'sources', 'derived', '.workbuddy'}


def find_all(project, pattern, skip=SKIP_FOR_MD):
    hits = []
    for p in Path(project).rglob(pattern):
        rel = p.relative_to(project)
        if any(part in skip for part in rel.parts):
            continue
        hits.append(p)
    return sorted(hits)


def find_one(project, patterns, skip=SKIP_FOR_MD):
    for pat in patterns:
        for p in Path(project).rglob(pat):
            rel = p.relative_to(project)
            if any(part in skip for part in rel.parts):
                continue
            return p
    return None


def find_components_md(project):
    return find_one(project, ['组件清单*.md', '**/组件清单*.md'])


def find_plans(project):
    return find_all(project, '编排方案*.md') + find_all(project, '**/编排方案*.md')


# ── 各种 rule 型闸门 ──────────────────────────────────────────────────────
def gate_intake(project, st):
    problems, notes = [], []
    prof = st.get('profile')
    if not prof:
        problems.append('未登记学员画像卡（init 时用 --profile）')
    else:
        prof_p = Path(prof)
        if not prof_p.exists():
            problems.append(f'画像卡不存在：{prof}')
        else:
            txt = io.open(prof_p, encoding='utf-8').read()
            # 必须是「键行」且键下有内容。曾经用全文子串匹配，结果注释里写了
            # 「没有 selection_rules」几个字的空卡也被判成通过——
            # 与 Stage 3「受控 ID 全文扫描」是同一类病：朴素匹配会被字面巧合骗过。
            m = re.search(r'^\s*selection_rules\s*:\s*(\S.*)?$', txt, re.M)
            if not m or not (m.group(1) or '').strip():
                problems.append('画像卡缺少有效的 selection_rules 键（须为非空 YAML 键，'
                                '且不能只出现在注释里）——没有判据的画像等于没有画像')
            else:
                notes.append('画像卡含非空 selection_rules 键')
    src = st.get('source')
    if not src or not Path(src).exists():
        problems.append(f'素材不可读：{src}')
    else:
        notes.append(f"素材可读（{Path(src).stat().st_size // 1024} KB）")
    if not st.get('copyright_stance'):
        problems.append('未声明版权口径（默认应为 strict：只概括+定位）')
    else:
        notes.append(f"版权口径：{st['copyright_stance']}"
                     + (f"（{st.get('copyright_note', '')}）" if st.get('copyright_note') else ''))
    return problems, notes


def gate_extract(project, st):
    problems, notes = [], []
    frag = find_one(project, ['fragments.jsonl', '**/fragments.jsonl'], SKIP_FOR_DATA)
    if not frag:
        problems.append('未产出 fragments.jsonl —— L1 萃取尚未交付')
        return problems, notes
    n = sum(1 for ln in io.open(frag, encoding='utf-8') if ln.strip())
    notes.append(f'{frag.name}：{n} 条碎片')
    if n == 0:
        problems.append('fragments.jsonl 为空')
    return problems, notes


def gate_restore(project, st):
    """chapters.json 健康度：复刻 restore_structure.py 的判据，独立于 Happy Path。"""
    problems, notes = [], []
    ch = find_one(project, ['chapters.json', '**/chapters.json'], SKIP_FOR_DATA)
    if not ch:
        problems.append('未产出 chapters.json —— L1.5 尚未交付')
        return problems, notes
    try:
        blocks = json.loads(io.open(ch, encoding='utf-8').read())
    except Exception as e:
        problems.append(f'chapters.json 解析失败：{e}')
        return problems, notes
    notes.append(f'{ch.name}：{len(blocks)} 个章节块，合计 {sum(b.get("chars", 0) for b in blocks)} 字')
    if len(blocks) < 2:
        problems.append(f'章节块仅 {len(blocks)} 个，结构还原失败')
    for a, b in zip(blocks, blocks[1:]):
        if b.get('start_line', 0) <= a.get('start_line', 0):
            problems.append(f"{b.get('chapter')} 起始行未晚于 {a.get('chapter')}，章节顺序异常")
    for b in blocks:
        if b.get('chars', 0) < 200:
            problems.append(f"{b.get('chapter')} 仅 {b.get('chars')} 字，疑似定到目录行")
    return problems, notes


def gate_teaching(project, st):
    problems, notes = [], []
    missing = []
    for label, pat in TEACHING_ARTIFACTS:
        if find_one(project, [pat, f'**/{pat}']):
            notes.append(label)
        else:
            missing.append(label)
    if missing:
        problems.append('L3 缺失：' + '、'.join(missing))
    return problems, notes


RULES = {'intake': gate_intake, 'extract': gate_extract,
         'restore': gate_restore, 'teaching': gate_teaching}


# ── 闸门参数解析 ──────────────────────────────────────────────────────────
def resolve_script_args(project, st, kind):
    """返回 (args, blocked_reason)。缺材料 → BLOCKED，不算失败。"""
    if kind == 'components':
        md = find_components_md(project)
        if not md:
            return None, '未找到组件清单 md（文件名需以「组件清单」开头）'
        return [str(md)], None
    if kind == 'modules':
        comp = find_components_md(project)
        if not comp:
            return None, '未找到组件清单 md'
        # 去重并保持顺序
        plans, seen = [], set()
        for p in find_plans(project):
            if str(p) not in seen:
                seen.add(str(p))
                plans.append(p)
        pair = st.get('compared_plans')
        if pair:                       # 显式指定的一对优先，不猜
            paths = [Path(project) / n for n in pair]
            miss = [str(p) for p in paths if not p.exists()]
            if miss:
                return None, f'状态文件里登记的对照方案不存在：{miss}'
        elif len(plans) >= 2:
            paths = plans[:2]
            print(f"  ⚠️  未显式指定对照组，按文件名顺序取了 {paths[0].name} 与 {paths[1].name}；"
                  f"若这两份不是「同批组件 / 不同画像」，指标无意义。用 --plans A B 指定。")
        else:
            return None, f'双画像对照需 ≥2 份编排方案，当前 {len(plans)} 份'
        st['compared_plans'] = [str(p.name) for p in paths]
        return [str(paths[0]), str(paths[1]), str(comp)], None
    if kind == 'delivery':
        files = find_all(project, '*.md')
        files = [f for f in files if f.name != STATE_NAME]
        if not files:
            return None, '无 md 交付物可扫'
        st.setdefault('scanned_files', len(files))
        return [str(f) for f in files], None
    return None, f'未知参数类型 {kind}'


def run_gate(project, st, stage):
    """执行闸门，返回 ('pass'|'fail'|'blocked', 输出文本)"""
    g = stage['gate']
    if g['kind'] == 'rule':
        problems, notes = RULES[g['fn']](project, st)
        lines = [f'  · {n}' for n in notes]
        if problems:
            return 'fail', '\n'.join(lines + [f'  ❌ {p}' for p in problems])
        return 'pass', '\n'.join(lines) if lines else '  (无附加检查项)'
    script = SKILLS / g['script']
    if not script.exists():
        return 'blocked', f'  ⛔ 闸门脚本不存在：{script}'
    args, reason = resolve_script_args(project, st, g.get('args', ''))
    if args is None:
        return 'blocked', f'  ⛔ {reason}'
    proc = subprocess.run([sys.executable, str(script)] + args,
                          capture_output=True, text=True, encoding='utf-8')
    out = (proc.stdout or '') + (proc.stderr or '')
    return ('pass' if proc.returncode == 0 else 'fail'), out.rstrip()


# ── 命令实现 ──────────────────────────────────────────────────────────────
def sync_pointer(st):
    """指针自愈：永远指向第一个未通过闸门的阶段。

    为什么不用「检查了谁就推进到谁」：实际跑流水线常常是乱序的
    （先补跑某个历史阶段的闸门、或上游返工后重跑），那种写法会把指针卡死在
    起始阶段。按状态推导反而稳定。
    """
    for sid in STAGE_IDS:
        if st['stages'][sid]['status'] != 'passed':
            st['current'] = sid
            return
    st['current'] = STAGE_IDS[-1]


def cmd_init(a):
    st = {
        'project': a.project,
        'source': a.source,
        'profile': a.profile,
        'copyright_stance': a.copyright,
        'copyright_note': a.note or '',
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'updated_at': '',
        'current': STAGE_IDS[0],
        'stages': {sid: {'status': 'pending', 'artifacts': [], 'gate': None}
                   for sid in STAGE_IDS},
        'history': [],
    }
    Path(a.project).mkdir(parents=True, exist_ok=True)
    log(st, 'init')
    # init 后立即校验接单条件，条件不足当场说清
    res, out = run_gate(a.project, st, STAGES[0])
    st['stages'][STAGE_IDS[0]].update({
        'gate': {'result': res, 'detail': out},
        'status': {'pass': 'passed', 'fail': 'failed', 'blocked': 'blocked'}[res],
    })
    save_state(a.project, st)
    print(f'已初始化：{state_path(a.project)}')
    print(f"版权口径：{a.copyright}" + (f"（{a.note}）" if a.note else ''))
    print('\n接单校验：')
    print(out if out.strip() else '  ✅ 通过')
    print('\n下一步：填入缺失项后跑  python pipeline.py check 0-intake')
    sys.exit(0 if res == 'pass' else (2 if res == 'blocked' else 1))


def cmd_status(a):
    st, _ = load_state(a.project)
    print(f"项目：{st['project']}")
    print(f"素材：{st['source']}")
    print(f"画像：{st.get('profile') or '（未登记）'}")
    print(f"版权：{st.get('copyright_stance')} {st.get('copyright_note') or ''}")
    print(f"当前阶段：{st['current']}    更新于 {st['updated_at']}")
    print()
    buf = []
    print(f"{'阶段':<16}{'状态':<10}{'闸门':<8}  产出")
    print('-' * 76)
    for s in STAGES:
        info = st['stages'][s['id']]
        g = info.get('gate') or {}
        print(f"{s['id']:<17}{info['status']:<10}{(g.get('result') or '-'):<9} {s['out']}")
        if s['id'] == st['current']:
            buf.append(f"  ↑ 当前位置：{s['name']}（执行者 {s['owner']}）")
    print('-' * 76)
    for ln in buf:
        print(ln)
    if a.detail:
        print('\n最近操作：')
        for h in st.get('history', [])[-10:]:
            print(f"  {h['ts']}  {h['action']}")
    sys.exit(0)


def stage_by_id(sid):
    for s in STAGES:
        if s['id'] == sid or s['name'] == sid:
            return s
    return None


def cmd_enter(a):
    st, _ = load_state(a.project)
    s = stage_by_id(a.stage)
    if not s:
        print(f'[FATAL] 未知阶段 {a.stage}，可选：{STAGE_IDS}')
        sys.exit(2)
    st['current'] = s['id']
    st['stages'][s['id']]['status'] = 'running'
    log(st, f"enter {s['id']}")
    save_state(a.project, st)
    print(f"进入 {s['id']}（{s['name']}）—— 执行者 {s['owner']}")
    print(f"本阶段产出应为：{s['out']}")
    sys.exit(0)


def cmd_artifact(a):
    st, _ = load_state(a.project)
    s = stage_by_id(a.stage)
    if not s:
        print(f'[FATAL] 未知阶段 {a.stage}')
        sys.exit(2)
    for p in a.paths:
        rel = Path(p).name
        if rel not in st['stages'][s['id']]['artifacts']:
            st['stages'][s['id']]['artifacts'].append(rel)
    log(st, f"artifact {s['id']}: {','.join(Path(p).name for p in a.paths)}")
    save_state(a.project, st)
    print(f"已登记 {s['id']} 的产物：{st['stages'][s['id']]['artifacts']}")
    sys.exit(0)


def cmd_check(a):
    st, _ = load_state(a.project)
    s = stage_by_id(a.stage)
    if not s:
        print(f'[FATAL] 未知阶段 {a.stage}')
        sys.exit(2)
    print(f"闸门 · {s['id']}（{s['name']}）")
    print('=' * 76)
    if a.plans:
        st['compared_plans'] = [Path(x).name for x in a.plans]
        print(f"对照组：{st['compared_plans'][0]}  ×  {st['compared_plans'][1]}")
    res, out = run_gate(a.project, st, s)
    print(out if out.strip() else '  (闸门无输出)')
    print('=' * 76)
    st['stages'][s['id']]['gate'] = {'result': res,
                                     'detail': out[:2000],
                                     'at': datetime.now().isoformat(timespec='seconds')}
    st['stages'][s['id']]['status'] = {'pass': 'passed', 'fail': 'failed',
                                       'blocked': 'blocked'}[res]
    log(st, f"check {s['id']} → {res}")
    # 过闸或没过闸，指针都按实际状态重算，避免乱序跑闸门时卡死。
    # 必须在 save_state 之前同步——曾经先存后算，改完没落盘，等于没改。
    sync_pointer(st)
    save_state(a.project, st)
    if res == 'pass':
        idx = STAGE_IDS.index(s['id'])
        nxt = STAGE_IDS[idx + 1] if idx + 1 < len(STAGE_IDS) else None
        print(f"✅ 放行" + (f"　下一步：{nxt}" if nxt else "　全流水线通过"))
        sys.exit(0)
    if res == 'blocked':
        print(f"⛔ 条件不足（不是失败）：补齐材料后重跑 python pipeline.py check {s['id']}")
        sys.exit(2)
    print(f"❌ 未通过 —— 不许进入下一阶段，退回 {s['id']} 返工")
    sys.exit(1)


def cmd_advance(a):
    st, _ = load_state(a.project)
    idx = STAGE_IDS.index(st['current'])
    cur = st['stages'][st['current']]
    if cur['status'] != 'passed':
        print(f"[FATAL] {st['current']} 尚未通过闸门（当前 {cur['status']}），不许推进")
        print(f"先跑：python pipeline.py check {st['current']}")
        sys.exit(1)
    if idx + 1 >= len(STAGE_IDS):
        print('已在末阶段，流水线完成')
        sys.exit(0)
    nxt = STAGE_IDS[idx + 1]
    st['current'] = nxt
    st['stages'][nxt]['status'] = 'running'
    log(st, f"advance → {nxt}")
    save_state(a.project, st)
    s = stage_by_id(nxt)
    print(f"推进到 {nxt}（{s['name']}）—— 执行者 {s['owner']}")
    print(f"本阶段产出应为：{s['out']}")
    sys.exit(0)


def cmd_reset(a):
    st, _ = load_state(a.project)
    s = stage_by_id(a.stage)
    if not s:
        print(f'[FATAL] 未知阶段 {a.stage}')
        sys.exit(2)
    st['stages'][s['id']] = {'status': 'pending', 'artifacts': [], 'gate': None}
    st['current'] = s['id']
    log(st, f"reset {s['id']}")
    save_state(a.project, st)
    print(f"已重置 {s['id']}，当前指针回到该阶段")
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser(description='课程流水线总控状态机')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('init', help='初始化流水线状态')
    p.add_argument('--project', required=True)
    p.add_argument('--source', required=True)
    p.add_argument('--profile', default=None)
    p.add_argument('--copyright', default='strict', choices=['strict', 'relaxed'])
    p.add_argument('--note', default=None, help='relaxed 时必须写明理由')
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser('status', help='查看流水线状态')
    p.add_argument('--project', required=True)
    p.add_argument('--detail', action='store_true')
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser('enter', help='进入某阶段')
    p.add_argument('--project', required=True)
    p.add_argument('stage')
    p.set_defaults(fn=cmd_enter)

    p = sub.add_parser('artifact', help='登记某阶段的产物')
    p.add_argument('--project', required=True)
    p.add_argument('stage')
    p.add_argument('paths', nargs='+')
    p.set_defaults(fn=cmd_artifact)

    p = sub.add_parser('check', help='跑某阶段闸门')
    p.add_argument('--project', required=True)
    p.add_argument('stage')
    p.add_argument('--plans', nargs=2, default=None, metavar=('A', 'B'),
                   help='4-modules 闸门用：显式指定参与对照的两份编排方案')
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser('advance', help='推进到下一阶段（要求当前已过闸）')
    p.add_argument('--project', required=True)
    p.set_defaults(fn=cmd_advance)

    p = sub.add_parser('reset', help='重置某阶段')
    p.add_argument('--project', required=True)
    p.add_argument('stage')
    p.set_defaults(fn=cmd_reset)

    args = ap.parse_args()
    args.fn(args)


if __name__ == '__main__':
    main()
