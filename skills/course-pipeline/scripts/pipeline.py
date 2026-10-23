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
import hashlib
import os
import tempfile
import io
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS / 'course-factory' / 'scripts'))
from course_contracts import discover, groups, read, upstream
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
        'out': '00–05 六类教学文件',
        'gate': {'kind': 'rule', 'fn': 'teaching'},
    },
    {
        'id': '6-delivery', 'name': '出厂', 'owner': 'course-pipeline',
        'out': '全部交付物过文本卫生 + 版权扫描',
        'gate': {'kind': 'rule', 'fn': 'delivery'},
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



class Blocked(Exception):
    """A required input or checker is unavailable, not a successful check."""


def state_path(project):
    return Path(project) / STATE_NAME


def log(st, action):
    st.setdefault('history', []).append({'ts': datetime.now().isoformat(timespec='seconds'), 'action': action})


def save_state(project, st):
    st['updated_at'] = datetime.now().isoformat(timespec='seconds')
    # Atomic replacement avoids a half-written state if interrupted.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=project,
                                     prefix='.pipeline-', suffix='.tmp', delete=False) as handle:
        json.dump(st, handle, ensure_ascii=False, indent=2)
        temp = Path(handle.name)
    try:
        os.replace(temp, state_path(project))
    finally:
        if temp.exists():
            temp.unlink()


def load_state(project):
    p = state_path(project)
    if not p.is_file():
        raise Blocked(f'未找到 {p}，请先 init')
    st = json.loads(read(p))
    if not isinstance(st, dict) or not isinstance(st.get('stages'), dict):
        raise Blocked('状态文件结构无效')
    for sid in STAGE_IDS:
        st['stages'].setdefault(sid, {'status': 'pending', 'artifacts': [], 'gate': None})
    if refresh(project, st):
        save_state(project, st)
    return st, p


SKIP_FOR_DATA = {'.git', 'build', 'node_modules'}
SKIP_FOR_MD = SKIP_FOR_DATA | {'kb', 'blind', 'sources', 'derived', '.workbuddy'}


def is_temp(part):
    return part.startswith(('.', '_'))


def find_all(project, pattern, skip=SKIP_FOR_MD):
    root = Path(project).resolve()
    return sorted(p for p in root.rglob(pattern) if p.is_file()
                  and not any(x in skip or is_temp(x) for x in p.relative_to(root).parts))


def find_one(project, patterns, skip=SKIP_FOR_MD):
    hits = sorted({p for pattern in patterns for p in find_all(project, pattern, skip)})
    if len(hits) > 1:
        raise Blocked('找到多份候选，不能猜选哪份：' + ', '.join(str(p) for p in hits))
    return hits[0] if hits else None


def find_components_md(project):
    return find_one(project, ['组件清单*.md'])


def find_plans(project):
    return find_all(project, '编排方案*.md')


def find_outlines(project):
    return find_all(project, '课程大纲*.md')


def locate_by_name(project, name, base=None):
    root = Path(project).resolve()
    candidates = []
    for parent in (Path(base) if base else root, root):
        p = (parent / name).resolve()
        if p.is_relative_to(root) and p.is_file():
            candidates.append(p)
    candidates = sorted(set(candidates))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates and (Path(name).is_absolute() or Path(name).parent != Path('.')):
        return None  # An explicit but wrong path must not fall back to a same-named file.
    hits = [p for p in discover(root) if p.name == Path(name).name]
    if len(candidates) > 1 or len(hits) > 1:
        raise Blocked(f'上游文件名有歧义：{name}；请登记项目相对路径')
    return hits[0] if hits else None


def relative_file(project, value):
    root = Path(project).resolve()
    # CLI paths are explicitly project-relative (absolute project files accepted).
    p = (root / value).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise Blocked(f'产物必须是项目内现存文件：{value}')
    return p.relative_to(root).as_posix()


def gate_intake(project, st):
    problems, notes = [], []
    try:
        import yaml
    except ImportError:
        raise Blocked('接单校验需要 PyYAML，请使用资料整理器的独立 Python 环境')
    prof = Path(st.get('profile') or '')
    if not prof.is_file():
        raise Blocked('未登记可读学员画像卡')
    try:
        profile = yaml.safe_load(read(prof))
    except yaml.YAMLError as exc:
        return ['画像 YAML 无效：' + str(exc)], notes
    rules = profile.get('selection_rules') if isinstance(profile, dict) else None
    if not isinstance(rules, list) or not rules:
        problems.append('selection_rules 必须是非空规则列表')
    else:
        for number, rule in enumerate(rules, 1):
            if not isinstance(rule, dict) or any(not isinstance(rule.get(k), str) or not rule[k].strip()
                                                 for k in ('condition', 'action', 'reason')):
                problems.append(f'规则{number}缺少 condition/action/reason')
            elif rule['action'] not in {'promote', 'demote', 'drop'}:
                problems.append(f'规则{number} action 非法')
    src = Path(st.get('source') or '')
    if not src.is_file():
        raise Blocked(f'素材不是可读文件：{src}')
    with src.open('rb') as handle:
        if not handle.read(1024).strip():
            problems.append('素材为空')
    if st.get('copyright_stance') not in {'strict', 'relaxed'}:
        problems.append('版权口径必须为 strict 或 relaxed')
    if st.get('copyright_stance') == 'relaxed' and not st.get('copyright_note', '').strip():
        problems.append('relaxed 必须写明理由；不自动豁免原文重合检查')
    notes.append('按 YAML 结构与规则字段检查画像')
    return problems, notes


def gate_extract(project, st):
    frag = find_one(project, ['fragments.jsonl'], SKIP_FOR_DATA)
    if not frag:
        raise Blocked('未产出 fragments.jsonl')
    errors, seen = [], set()
    for number, line in enumerate(read(frag).splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('记录必须是对象')
            for key in ('fragment_id', 'source_id', 'revision_id', 'raw_text'):
                if not isinstance(row.get(key), str) or not row[key].strip():
                    raise ValueError(f'{key} 缺失或为空')
            anchor = row.get('anchor')
            if not isinstance(anchor, dict) or not anchor:
                raise ValueError('缺少来源 anchor')
            if row['fragment_id'] in seen:
                raise ValueError('fragment_id 重复')
            seen.add(row['fragment_id'])
        except (ValueError, TypeError) as exc:
            errors.append(f'第{number}条碎片无效：{exc}')
    if not seen:
        errors.append('没有有效碎片')
    return errors, [f'有效碎片 {len(seen)} 条']


def gate_restore(project, st):
    path = find_one(project, ['chapters.json'], SKIP_FOR_DATA)
    if not path:
        raise Blocked('未产出 chapters.json')
    blocks = json.loads(read(path))
    if not isinstance(blocks, list) or len(blocks) < 2:
        return ['章节数据须为至少两章的列表'], []
    errors, previous = [], -1
    for block in blocks:
        if not isinstance(block, dict):
            errors.append('章节记录不是对象')
            continue
        start, end, text = block.get('start_line'), block.get('end_line'), block.get('text')
        if not isinstance(start, int) or not isinstance(end, int) or start <= previous or end <= start:
            errors.append('章节行范围或顺序无效')
        else:
            previous = start
        if not isinstance(text, str) or len(re.sub(r'\s', '', text)) < 200:
            errors.append('章节正文不足 200 字，需检查是否误取目录')
        elif block.get('chars') != len(re.sub(r'\s', '', text)):
            errors.append('章节声明字数与实际文本不符')
    return errors, [f'章节 {len(blocks)} 个']


def run_script(script, args):
    script = Path(script)
    if not script.is_file():
        raise Blocked(f'检查脚本不存在：{script}')
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
    try:
        proc = subprocess.run([sys.executable, str(script), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8',
                              env=env, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked(f'检查未完成：{exc}')
    output = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode == 2:
        raise Blocked(output.strip() or f'{script.name} 无法判定')
    return proc.returncode, output.strip()


def outline_upstream(path):
    names = upstream(path)
    plan = [n for n in names if '编排方案' in n]
    comp = [n for n in names if '组件清单' in n]
    return (plan[0] if len(plan) == 1 else None, comp[0] if len(comp) == 1 else None)


def gate_teaching(project, st):
    errors, notes = [], []
    try:
        bundles = groups(project)
    except (ValueError, OSError) as exc:
        raise Blocked(str(exc))
    for bundle in bundles:
        for path in bundle.values():
            text = read(path).strip()
            if not text or re.search(r'【AI 补[:：]|待填写|尚未生成', text):
                errors.append(f'{path.name} 为空或仍含未完成占位内容')
        outline = bundle['课程大纲']
        plan_name, comp_name = outline_upstream(outline)
        if not plan_name or not comp_name:
            raise Blocked(f'{outline.name} 未登记唯一上游编排方案和组件清单')
        plan = locate_by_name(project, plan_name, outline.parent)
        comp = locate_by_name(project, comp_name, outline.parent)
        if not plan or not comp:
            raise Blocked(f'{outline.name} 登记的上游文件缺失')
        commands = [
            ('plan_to_outline.py', ['verify', '--outline', outline, '--plan', plan, '--components', comp, '--strict']),
            ('check_schedule.py', [bundle['课程计划'], '--outline', outline]),
            ('check_consistency.py', ['--project', project, '--outline', outline, '--plan', bundle['课程计划'], *bundle.values()]),
        ]
        for script, args in commands:
            code, out = run_script(SKILLS / 'course-factory' / 'scripts' / script, args)
            if code:
                errors.append(f'{outline.name} / {script} 未通过：\n{out}')
            else:
                notes.append(f'{outline.name} / {script} 已执行并通过')
    return errors, notes


def delivery_docs(project, st):
    excluded = {Path(st[k]).resolve() for k in ('source', 'profile', 'source_text') if st.get(k)}
    return [p for p in discover(project) if p.resolve() not in excluded]


def gate_delivery(project, st):
    docs = delivery_docs(project, st)
    if not docs:
        raise Blocked('没有可交付的 Markdown 文件')
    src = Path(st.get('source_text') or st.get('source') or '')
    if not src.is_file():
        raise Blocked('原材料文本不可用，版权检查未执行')
    errors, notes = [], []
    for name, args in (
        ('check_text_hygiene.py', docs),
        ('check_copyright.py', ['--source', src, *docs]),
    ):
        code, out = run_script(SKILLS / 'course-factory' / 'scripts' / name, args)
        (errors if code else notes).append(f'{name}：\n{out}')
    return errors, notes


RULES = {'intake': gate_intake, 'extract': gate_extract, 'restore': gate_restore,
         'teaching': gate_teaching, 'delivery': gate_delivery}


def resolve_script_args(project, st, kind):
    comp = find_components_md(project)
    if not comp:
        return None, '未找到组件清单'
    if kind == 'components':
        return [str(comp)], None
    if kind != 'modules':
        return None, '未知参数类型'
    pair = st.get('compared_plans')
    plans = [(Path(project) / n).resolve() for n in pair] if pair else find_plans(project)
    if any(not p.is_file() or not p.is_relative_to(Path(project).resolve()) for p in plans):
        return None, '登记的方案不存在或位于项目外'
    single_reason = st.get('single_course_reason', '').strip()
    if single_reason:
        if len(plans) != 1:
            return None, '单课程模式须恰好一份方案'
        st['compared_plans'] = [relative_file(project, plans[0])]
        return ['--single', str(plans[0]), str(comp)], None
    if len(plans) != 2 or len(set(plans)) != 2:
        return None, '需两份不同方案；有多个版本请用 --plans 明确选择，单课程须登记豁免理由'
    st['compared_plans'] = [relative_file(project, p) for p in plans]
    return [str(p) for p in plans] + [str(comp)], None


def run_gate(project, st, stage):
    try:
        gate = stage['gate']
        if gate['kind'] == 'rule':
            errors, notes = RULES[gate['fn']](project, st)
            return ('fail' if errors else 'pass'), '\n'.join(notes + ['❌ ' + e for e in errors])
        args, reason = resolve_script_args(project, st, gate['args'])
        if args is None:
            raise Blocked(reason)
        code, out = run_script(SKILLS / gate['script'], args)
        return ('pass' if code == 0 else 'fail'), out
    except Blocked as exc:
        return 'blocked', str(exc)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        return 'fail', f'输入/解析错误：{exc}'


def stage_by_id(sid):
    return next((stage for stage in STAGES if sid in (stage['id'], stage['name'])), None)


def sync_pointer(st):
    st['current'] = next((sid for sid in STAGE_IDS if st['stages'][sid]['status'] != 'passed'), STAGE_IDS[-1])


def invalidate(st, sid, reason):
    for affected in STAGE_IDS[STAGE_IDS.index(sid):]:
        info = st['stages'][affected]
        info.update(status='pending', gate=None)
        info.pop('fingerprint', None)
    sync_pointer(st)
    log(st, f'invalidate {sid} 及下游：{reason}')


def fingerprint(project, st, sid):
    patterns = {
        '1-extract': ['fragments.jsonl', 'sources.jsonl'],
        '2-restore': ['chapters.json'],
        '3-components': ['组件清单*.md'],
        '4-modules': ['编排方案*.md'],
    }
    files = []
    config = {}
    if sid == '0-intake':
        files = [Path(st[k]) for k in ('source', 'profile', 'source_text') if st.get(k)]
        config = {k: st.get(k) for k in ('copyright_stance', 'copyright_note')}
    elif sid in patterns:
        files = [p for pattern in patterns[sid] for p in find_all(project, pattern, SKIP_FOR_DATA)]
        if sid == '1-extract':
            files.extend(p for p in find_all(project, '*', SKIP_FOR_DATA)
                         if 'derived' in p.relative_to(Path(project).resolve()).parts)
        if sid == '4-modules':
            config = {k: st.get(k) for k in ('compared_plans', 'single_course_reason')}
    else:
        files = delivery_docs(project, st) if sid == '6-delivery' else [
            p for p in discover(project) if any(tag in p.name for tag, _ in TEACHING_ARTIFACTS)
            or '课程计划' in p.name or 'Storyboard' in p.name or '学员课程讲义' in p.name
            or '教员课程指导手册' in p.name]
        manifest = Path(project) / 'course-deliverables.json'
        if manifest.exists():
            files.append(manifest)
    config['artifacts'] = st['stages'][sid].get('artifacts', [])
    values = []
    for p in sorted(set(files)):
        values.append((str(p.resolve()), hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'MISSING'))
    # Checker upgrades invalidate old passes, including legacy states without fingerprints.
    checker_files = [Path(__file__), *(SKILLS / 'course-factory' / 'scripts').glob('*.py')]
    tools_hash = [(p.name, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(checker_files)
                  if not p.name.startswith(('test_', 'selftest_'))]
    return hashlib.sha256(json.dumps([values, config, tools_hash], sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def refresh(project, st):
    for sid in STAGE_IDS:
        info = st['stages'][sid]
        if info['status'] == 'passed':
            try:
                fresh = info.get('fingerprint') == fingerprint(project, st, sid)
            except OSError:
                fresh = False
            if not fresh:
                invalidate(st, sid, '文件/配置变更或旧版状态缺少校验指纹')
                return True
    old = st.get('current')
    sync_pointer(st)
    return old != st['current']


def prerequisite(st, sid):
    needed = [prior for prior in STAGE_IDS[:STAGE_IDS.index(sid)] if st['stages'][prior]['status'] != 'passed']
    if needed:
        raise Blocked('前置阶段尚未通过：' + ', '.join(needed))


def cmd_init(a):
    project = Path(a.project).resolve()
    project.mkdir(parents=True, exist_ok=True)
    if state_path(project).exists():
        raise Blocked('已有状态文件；请使用 status/check/reset，不覆盖历史')
    st = {
        'schema_version': 2, 'project': str(project),
        'source': str(Path(a.source).expanduser().resolve()),
        'profile': str(Path(a.profile).expanduser().resolve()) if a.profile else None,
        'source_text': str(Path(a.source_text).expanduser().resolve()) if getattr(a, 'source_text', None) else None,
        'copyright_stance': a.copyright, 'copyright_note': a.note or '',
        'single_course_reason': getattr(a, 'single_course_reason', None) or '',
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'current': STAGE_IDS[0], 'history': [],
        'stages': {sid: {'status': 'pending', 'artifacts': [], 'gate': None} for sid in STAGE_IDS},
    }
    result, out = run_gate(project, st, STAGES[0])
    st['stages'][STAGE_IDS[0]].update(status={'pass': 'passed', 'fail': 'failed', 'blocked': 'blocked'}[result],
                                     gate={'result': result, 'detail': out})
    if result == 'pass':
        st['stages'][STAGE_IDS[0]]['fingerprint'] = fingerprint(project, st, STAGE_IDS[0])
    log(st, 'init')
    sync_pointer(st)
    save_state(project, st)
    print(out)
    print(f'已初始化：{state_path(project)}；当前阶段 {st["current"]}')
    return {'pass': 0, 'fail': 1, 'blocked': 2}[result]


def cmd_status(a):
    st, _ = load_state(a.project)
    print('项目：' + st['project'])
    for sid in STAGE_IDS:
        info = st['stages'][sid]
        print(f'{sid}: {info["status"]}')
    print('当前阶段：' + st['current'])
    if a.detail:
        for item in st.get('history', [])[-10:]:
            print(item['ts'], item['action'])
    return 0


def cmd_enter(a):
    st, _ = load_state(a.project)
    stage = stage_by_id(a.stage)
    if not stage:
        raise Blocked('未知阶段')
    sid = stage['id']
    prerequisite(st, sid)
    invalidate(st, sid, '重新进入该阶段')
    st['stages'][sid]['status'] = 'running'
    save_state(a.project, st)
    print('进入 ' + sid)
    return 0


def cmd_artifact(a):
    st, _ = load_state(a.project)
    stage = stage_by_id(a.stage)
    if not stage:
        raise Blocked('未知阶段')
    sid = stage['id']
    paths = [relative_file(a.project, value) for value in a.paths]
    invalidate(st, sid, '产物登记发生变化')
    st['stages'][sid]['artifacts'] = sorted(set(st['stages'][sid].get('artifacts', []) + paths))
    save_state(a.project, st)
    return 0


def cmd_check(a):
    st, _ = load_state(a.project)
    stage = stage_by_id(a.stage)
    if not stage:
        raise Blocked('未知阶段')
    sid = stage['id']
    prerequisite(st, sid)
    if getattr(a, 'plans', None):
        st['compared_plans'] = [relative_file(a.project, p) for p in a.plans]
    if getattr(a, 'single_course_reason', None):
        st['single_course_reason'] = a.single_course_reason.strip()
    invalidate(st, sid, '重新执行检查')
    result, out = run_gate(a.project, st, stage)
    info = st['stages'][sid]
    info.update(status={'pass': 'passed', 'fail': 'failed', 'blocked': 'blocked'}[result],
                gate={'result': result, 'detail': out, 'at': datetime.now().isoformat(timespec='seconds')})
    if result == 'pass':
        info['fingerprint'] = fingerprint(a.project, st, sid)
    log(st, f'check {sid} → {result}')
    sync_pointer(st)
    save_state(a.project, st)
    print(out)
    complete = all(v['status'] == 'passed' for v in st['stages'].values())
    print('全流水线通过（程序检查，不代表教学效果验收）' if complete else f'{sid}: {result}；当前阶段 {st["current"]}')
    return {'pass': 0, 'fail': 1, 'blocked': 2}[result]


def cmd_advance(a):
    st, _ = load_state(a.project)
    sid = st['current']
    if all(v['status'] == 'passed' for v in st['stages'].values()):
        print('全部阶段已通过')
        return 0
    prerequisite(st, sid)
    if st['stages'][sid]['status'] not in {'pending', 'running'}:
        raise Blocked(f'{sid} 需修复并重检，不可跳过')
    st['stages'][sid]['status'] = 'running'
    log(st, 'advance/start ' + sid)
    save_state(a.project, st)
    print('开始当前待办阶段：' + sid)
    return 0


def cmd_reset(a):
    st, _ = load_state(a.project)
    stage = stage_by_id(a.stage)
    if not stage:
        raise Blocked('未知阶段')
    invalidate(st, stage['id'], '用户重置')
    save_state(a.project, st)
    print('已重置指定阶段及全部下游，产物文件保留')
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='课程总控：缺输入阻断、检查失败不放行、上游变化使下游失效')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('init')
    p.add_argument('--project', required=True)
    p.add_argument('--source', required=True)
    p.add_argument('--profile')
    p.add_argument('--source-text', help='PDF 等素材用于版权比对的派生文本')
    p.add_argument('--copyright', default='strict', choices=['strict', 'relaxed'])
    p.add_argument('--note', default='')
    p.add_argument('--single-course-reason', help='仅制作一门课时明确登记不做双画像对照的理由')
    p.set_defaults(fn=cmd_init)
    for name, fn in (('status', cmd_status), ('enter', cmd_enter), ('artifact', cmd_artifact),
                     ('check', cmd_check), ('advance', cmd_advance), ('reset', cmd_reset)):
        p = sub.add_parser(name)
        p.add_argument('--project', required=True)
        if name in {'enter', 'artifact', 'check', 'reset'}:
            p.add_argument('stage', choices=STAGE_IDS)
        if name == 'status':
            p.add_argument('--detail', action='store_true')
        if name == 'artifact':
            p.add_argument('paths', nargs='+')
        if name == 'check':
            p.add_argument('--plans', nargs='+', help='项目相对路径：对照两份；已登记单课程模式时一份')
            p.add_argument('--single-course-reason')
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    a.project = str(Path(a.project).expanduser().resolve())
    try:
        return a.fn(a)
    except Blocked as exc:
        print('BLOCKED：' + str(exc))
        return 2
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        print('FAILED：' + str(exc))
        return 1


if __name__ == '__main__':
    sys.exit(main())
