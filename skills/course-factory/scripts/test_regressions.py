"""Portable regressions; all fixtures are synthetic and live in temporary folders."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
sys.path.insert(0, str(HERE))
import course_contracts as contracts
import plan_to_outline as bridge
import restore_structure as restore

spec = importlib.util.spec_from_file_location('course_test_pipeline', SKILLS / 'course-pipeline/scripts/pipeline.py')
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

HEADINGS = ['一、课程名称', '二、课程定位', '三、适用对象', '四、课程基本信息',
            '五、业务与学习背景', '六、课程原材料地图', '七、能力差距', '八、学习目标',
            '九、课程学习主线', '十、课程结构总览', '十一、模块详细大纲',
            '十二、课程核心成果', '十三、进入下一步前确认']


def put(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def fixture(root, dual=False):
    """Six-module, 90-minute sample; dual version reverses order and changes intent."""
    text = '资料只为程序验证编写，保存来源便于检查内容是否被准确记录。' * 12
    put(root, '素材.md', '第一章 来源\n' + text + '\n第二章 组织\n' + text)
    put(root, '画像.yaml', 'label: 新员工\nselection_rules:\n  - condition: 操作方法\n    action: promote\n    reason: 工作中需要实际使用\n')
    put(root, 'kb/fragments.jsonl', json.dumps({'fragment_id': 'F001', 'source_id': 'S001',
        'revision_id': 'R001', 'raw_text': text, 'anchor': {'kind': 'line_range', 'start': 1, 'end': 2}}, ensure_ascii=False))
    blocks = [{'chapter': ch, 'start_line': i * 10, 'end_line': (i + 1) * 10,
               'chars': len(text), 'text': text} for i, ch in enumerate(['第一章', '第二章'])]
    put(root, 'kb/chapters.json', json.dumps(blocks, ensure_ascii=False))
    components = '# 组件清单\n**6 个组件**\n## 三、逐章组件明细\n### 第一章（来源）\n'
    components += '| ID | 名称 | 类型 | 概括 | 价值 |\n|---|---|---|---|---|\n'
    for n in range(1, 7):
        components += f'| C{n:03d} | 方法{n} | tool | 识别任务后完成对应行动{n} | 实际应用 |\n'
    put(root, '组件清单.md', components)
    for variant in (['A', 'B'] if dual else ['A']):
        ids = list(range(1, 7)) if variant == 'A' else list(range(6, 0, -1))
        plan = '# 编排方案\n## 二、模块序列\n| # | 模块名 | 层级 | 分钟 | Do意图 | 组件 ID | 主教学处理 |\n|---|---|---|---|---|---|---|\n'
        for i, cid in enumerate(ids):
            plan += f'| M{i} | 方法{cid} | Do | 15 | {"P" if variant == "A" else "T"} | C{cid:03d} | 演练 |\n'
        put(root, f'plans/编排方案{variant}.md', plan)
        folder = f'courses/{variant}/'
        outline = f'# 课程大纲\n**上游**：`plans/编排方案{variant}.md` / `组件清单.md`\n总时长 90 分钟。\n'
        for heading in HEADINGS:
            outline += f'## {heading}\n围绕岗位任务学习方法，完成演练并回顾行动。\n'
            if heading.startswith('十一'):
                for i, cid in enumerate(ids):
                    outline += f'### M{i} · 方法{cid}（Do，15 分钟）\n**建议时长**：15 分钟\n| 组件 | 内容 |\n|---|---|\n| C{cid:03d} | 方法{cid} |\n'
        put(root, folder + f'课程大纲{variant}.md', outline)
        schedule = f'# 详细课程计划\n**上游**：`课程大纲{variant}.md`\n总时长 90 分钟。\n## Day 1\n| 时间 | 教学单元 | 组件 |\n|---|---|---|\n'
        for i, cid in enumerate(ids):
            start, end = 540 + i * 15, 555 + i * 15
            schedule += f'| {start//60:02d}:{start%60:02d}-{end//60:02d}:{end%60:02d} | M{i} 方法{cid} | C{cid:03d} |\n'
        put(root, folder + f'详细课程计划{variant}.md', schedule)
        for tag in ['培训需求说明书', '学员课程讲义', '教员课程指导手册', '教员课程PPT-Storyboard']:
            put(root, folder + tag + variant + '.md', f'# {tag}\n总时长 90 分钟。\n教学时长 90 分钟。\n针对新员工的任务安排练习，记录行动结果并由讲师反馈。\n')
    return root


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='course-regression-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def cli(self, name, *args, expected=None, utf8='1'):
        script = pipeline.__file__ if name == 'pipeline' else HERE / name
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': utf8, 'PYTHONDONTWRITEBYTECODE': '1'}
        result = subprocess.run([sys.executable, '-B', str(script), *map(str, args)],
                                capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stdout + result.stderr)
        return result

    def init(self, dual=False):
        fixture(self.root, dual)
        args = ['init', '--project', self.root, '--source', self.root / '素材.md', '--profile', self.root / '画像.yaml']
        if not dual:
            args += ['--single-course-reason', '本次只开发一门课程，不声称双画像差异通过']
        return self.cli('pipeline', *args, expected=0)

    def check(self, sid, expected=0):
        return self.cli('pipeline', 'check', '--project', self.root, sid, expected=expected)

    def complete(self, dual=False):
        self.init(dual)
        for sid in pipeline.STAGE_IDS[1:]:
            self.check(sid)
        state = json.loads((self.root / 'pipeline-state.json').read_text(encoding='utf-8'))
        self.assertTrue(all(s['status'] == 'passed' for s in state['stages'].values()))

    def test_full_single_course_and_repeat_status(self):
        self.complete()
        self.cli('pipeline', 'status', '--project', self.root, expected=0)
        self.cli('pipeline', 'advance', '--project', self.root, expected=0)

    def test_full_dual_course_nested_directories(self):
        self.complete(dual=True)

    def test_skip_upstream_is_blocked(self):
        self.init()
        out = self.check('6-delivery', expected=2)
        self.assertNotIn('全流水线通过', out.stdout)

    def test_reset_cascades_and_preserves_files(self):
        self.complete()
        self.cli('pipeline', 'reset', '--project', self.root, '2-restore', expected=0)
        state, _ = pipeline.load_state(self.root)
        self.assertTrue(all(state['stages'][sid]['status'] == 'pending' for sid in pipeline.STAGE_IDS[2:]))
        self.assertTrue((self.root / '组件清单.md').exists())

    def test_upstream_edit_invalidates_and_rerun_completes(self):
        self.complete()
        p = self.root / '组件清单.md'
        p.write_text(p.read_text(encoding='utf-8') + '\n审核记录：已核对。\n', encoding='utf-8')
        self.check('6-delivery', expected=2)
        for sid in pipeline.STAGE_IDS[3:]:
            self.check(sid)

    def test_source_edit_invalidates_intake(self):
        self.complete()
        put(self.root, '素材.md', '原材料已经更新。')
        self.check('6-delivery', expected=2)
        st, _ = pipeline.load_state(self.root)
        self.assertEqual(st['stages']['0-intake']['status'], 'pending')

    def test_advance_after_check_starts_pending_without_skipping(self):
        self.init()
        self.check('1-extract')
        self.cli('pipeline', 'advance', '--project', self.root, expected=0)
        st, _ = pipeline.load_state(self.root)
        self.assertEqual(st['current'], '2-restore')
        self.assertEqual(st['stages']['2-restore']['status'], 'running')

    def test_init_does_not_overwrite_history(self):
        self.init()
        old = (self.root / 'pipeline-state.json').read_bytes()
        self.cli('pipeline', 'init', '--project', self.root, '--source', self.root / '素材.md', expected=2)
        self.assertEqual(old, (self.root / 'pipeline-state.json').read_bytes())

    def test_legacy_passes_require_revalidation(self):
        self.init()
        st, _ = pipeline.load_state(self.root)
        for info in st['stages'].values():
            info.update(status='passed')
            info.pop('fingerprint', None)
        pipeline.save_state(self.root, st)
        st, _ = pipeline.load_state(self.root)
        self.assertTrue(all(info['status'] == 'pending' for info in st['stages'].values()))

    def test_intake_rejects_empty_comment_and_scalar_rules(self):
        fixture(self.root)
        for invalid in ['[]', '# 稍后填写', 'hello', '{}', 'null']:
            put(self.root, 'bad.yaml', 'selection_rules: ' + invalid + '\n')
            errors, _ = pipeline.gate_intake(self.root, {'source': str(self.root/'素材.md'), 'profile': str(self.root/'bad.yaml'), 'copyright_stance': 'strict'})
            self.assertTrue(errors, invalid)

    def test_invalid_fragment_json_and_missing_fields(self):
        for value in ['not json', '{}', '[]']:
            put(self.root, 'fragments.jsonl', value)
            result, _ = pipeline.run_gate(self.root, {}, pipeline.stage_by_id('1-extract'))
            self.assertEqual(result, 'fail')

    def test_empty_and_malformed_component_tables_fail(self):
        for value in ['# 组件清单\n尚未生成', '| C001 | 名称 | `tool` | 第一章 |']:
            p = put(self.root, '组件清单.md', value)
            self.cli('check_components.py', p, expected=1)

    def test_text_hygiene_missing_file_fails(self):
        self.cli('check_text_hygiene.py', self.root/'missing.md', expected=1)

    def test_overlap_not_treated_as_new_day(self):
        p = put(self.root, '排期.md', '总时长 120 分钟\n| 09:00-10:00 | C001 |\n| 09:30-10:30 | C002 |')
        self.cli('check_schedule.py', p, expected=1)

    def test_short_total_conflict_fails(self):
        p = put(self.root, '排期.md', '总时长 90 分钟\n| 09:00-10:00 | C001 |')
        self.cli('check_schedule.py', p, expected=1)

    def test_explicit_two_days_pass(self):
        p = put(self.root, '排期.md', '总时长 120 分钟\n## Day 1\n| 09:00-10:00 | C001 |\n## Day 2\n| 09:00-10:00 | C002 |')
        self.cli('check_schedule.py', p, expected=0)

    def test_missing_total_is_blocked(self):
        p = put(self.root, '排期.md', '| 09:00-10:00 | C001 |')
        self.cli('check_schedule.py', p, expected=2)

    def test_bad_time_is_blocked(self):
        p = put(self.root, '排期.md', '总时长 60 分钟\n| 09:70-10:70 | C001 |')
        self.cli('check_schedule.py', p, expected=2)

    def test_module_assignment_order_and_duration(self):
        fixture(self.root)
        outline = self.root/'courses/A/课程大纲A.md'
        text = outline.read_text(encoding='utf-8')
        plan, _ = bridge.load_plan(self.root/'plans/编排方案A.md')
        comps, _ = bridge.load_components(self.root/'组件清单.md')
        self.assertEqual(bridge.verify(text, plan, comps)[0], [])
        swapped = text.replace('| C001 |', '| TEMP |').replace('| C002 |', '| C001 |').replace('| TEMP |', '| C002 |')
        self.assertTrue(bridge.verify(swapped, plan, comps)[0])
        a, b, c = text.index('### M0'), text.index('### M1'), text.index('### M2')
        self.assertTrue(bridge.verify(text[:a]+text[b:c]+text[a:b]+text[c:], plan, comps)[0])
        self.assertTrue(bridge.verify(text.replace('（Do，15 分钟）', '（Do，20 分钟）', 1), plan, comps)[0])

    def test_teaching_without_time_axis_never_passes(self):
        fixture(self.root)
        put(self.root, 'courses/A/详细课程计划A.md', '总时长 90 分钟\n没有排期轴。')
        result, _ = pipeline.run_gate(self.root, {}, pipeline.stage_by_id('5-teaching'))
        self.assertEqual(result, 'blocked')

    def test_missing_source_delivery_blocked(self):
        put(self.root, '成品.md', '这是教学材料。')
        result, _ = pipeline.run_gate(self.root, {'source': str(self.root/'missing.md')}, pipeline.stage_by_id('6-delivery'))
        self.assertEqual(result, 'blocked')

    def test_nested_plan_paths_survive_resolution(self):
        fixture(self.root, True)
        state = {}
        first, reason = pipeline.resolve_script_args(self.root, state, 'modules')
        second, reason = pipeline.resolve_script_args(self.root, state, 'modules')
        self.assertEqual(first, second)
        self.assertTrue(all('/' in p for p in state['compared_plans']))

    def test_explicit_wrong_upstream_path_does_not_guess(self):
        fixture(self.root)
        self.assertIsNone(pipeline.locate_by_name(self.root, 'wrong/编排方案A.md'))
        self.assertEqual(pipeline.locate_by_name(self.root, '编排方案A.md'), self.root/'plans/编排方案A.md')

    def test_real_outline_generator_with_unused_component(self):
        fixture(self.root)
        comp = self.root / '组件清单.md'
        comp.write_text(comp.read_text(encoding='utf-8').replace('**6 个组件**', '**7 个组件**')
                        + '| C007 | 方法7 | tool | 非本课岗位职责 | 参考 |\n', encoding='utf-8')
        plan = self.root / 'plans/编排方案A.md'
        plan.write_text(plan.read_text(encoding='utf-8') + '\n## 四、未选用组件清单\n'
                        '| C007 | 方法7 | tool | 舍 | 非本课岗位职责 |\n', encoding='utf-8')
        output = self.root / 'new/deep/课程大纲.md'
        self.cli('plan_to_outline.py', 'gen', '--plan', plan, '--components', comp,
                 '--profile', self.root/'画像.yaml', '--out', output, expected=0)
        self.cli('plan_to_outline.py', 'verify', '--plan', plan, '--components', comp,
                 '--outline', output, '--strict', expected=1)
        text = output.read_text(encoding='utf-8')
        refs = contracts.upstream(output)
        self.assertEqual(pipeline.locate_by_name(self.root, refs[0], output.parent), plan)
        self.assertEqual(pipeline.locate_by_name(self.root, refs[1], output.parent), comp)
        self.assertIn('C007', text)
        self.assertIn('| 教学净时长 | 90 分钟 |', text)
        self.assertIn('确认含休息的总包时长', text)
        completed = re.sub(r'【AI 补：[^】]*】', '合成教学内容用于结构测试', text)
        self.assertNotEqual(text, completed)
        output.write_text(completed, encoding='utf-8')
        self.cli('plan_to_outline.py', 'verify', '--plan', plan, '--components', comp,
                 '--outline', output, '--strict', expected=0)

    def test_generator_does_not_silently_drop_unsupported_inputs(self):
        fixture(self.root)
        comp = self.root / '组件清单.md'
        comp.write_text(comp.read_text(encoding='utf-8').replace('| 价值 |', '| 定位 |'), encoding='utf-8')
        self.cli('plan_to_outline.py', 'gen', '--plan', self.root/'plans/编排方案A.md',
                 '--components', comp, '--profile', self.root/'画像.yaml', '--out', self.root/'out.md', expected=2)
        fixture(self.root)
        comp.write_text(comp.read_text(encoding='utf-8')+'| C007 | 方法7 | tool | 其他任务 | 参考 |\n', encoding='utf-8')
        self.cli('plan_to_outline.py', 'gen', '--plan', self.root/'plans/编排方案A.md',
                 '--components', comp, '--profile', self.root/'画像.yaml', '--out', self.root/'out.md', expected=1)

    def test_single_mode_requires_reason(self):
        fixture(self.root)
        self.assertIsNone(pipeline.resolve_script_args(self.root, {}, 'modules')[0])
        args, reason = pipeline.resolve_script_args(self.root, {'single_course_reason': '只做一门课'}, 'modules')
        self.assertEqual(args[0], '--single')

    def test_copyright_offset_and_line_wrapping_fail(self):
        source = put(self.root, '来源.md', '甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉')
        for text in ['前'+source.read_text(encoding='utf-8')+'后', '甲乙丙丁戊己庚辛壬癸\n子丑寅卯辰巳午未申酉']:
            out = put(self.root, '交付.md', text)
            self.cli('check_copyright.py', '--source', source, out, expected=1)

    def test_copyright_warning_not_failure(self):
        source = put(self.root, '来源.md', '甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉')
        out = put(self.root, '交付.md', '甲乙丙丁戊己庚辛壬癸子丑')
        result = self.cli('check_copyright.py', '--source', source, out, expected=0)
        self.assertIn('警告', result.stdout)

    def test_copyright_no_comparable_text_blocked(self):
        source = put(self.root, '来源.md', 'This is an English source.')
        self.cli('check_copyright.py', '--source', source, source, expected=2)

    def test_copyright_missing_file_and_invalid_threshold(self):
        source = put(self.root, '来源.md', '甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉')
        self.cli('check_copyright.py', '--source', source, self.root/'missing.md', expected=1)
        self.cli('check_copyright.py', '--source', source, source, '--min', '0', expected=2)

    def test_twenty_four_chapters_keep_source_order(self):
        names = ['一','二','三','四','五','六','七','八','九','十','十一','十二','十三','十四','十五','十六','十七','十八','十九','二十','二十一','二十二','二十三','二十四']
        lines = []
        for name in names:
            lines += [f'第{name}章 标题'] + ['完整章节正文用于验证排序和结构还原。'*4]*10
        hits = restore.load_chapters(lines, restore.DEFAULT_PATTERN)
        starts = restore.pick_body_starts(hits, lines, restore.DEFAULT_GAP)
        self.assertEqual([s[0] for s in starts], [f'第{name}章' for name in names])
        self.assertFalse(any(kind == 'FATAL' for kind, _ in restore.health_check(restore.slice_blocks(lines, starts, len(lines)))))

    def test_consistency_missing_files_blocked_not_traceback(self):
        self.cli('check_consistency.py', '--project', self.root, expected=2)

    def test_consistency_checks_all_nested_courses(self):
        fixture(self.root, True)
        self.cli('check_consistency.py', '--project', self.root, expected=0)
        p = self.root/'courses/B/培训需求说明书B.md'
        p.write_text(p.read_text(encoding='utf-8').replace('总时长 90', '总时长 80'), encoding='utf-8')
        self.cli('check_consistency.py', '--project', self.root, expected=1)

    def test_ambiguous_versions_blocked(self):
        fixture(self.root)
        put(self.root, 'courses/A/课程大纲旧版.md', (self.root/'courses/A/课程大纲A.md').read_text(encoding='utf-8'))
        self.cli('check_consistency.py', '--project', self.root, expected=2)

    def test_ascii_quotes_ignore_quoted_durations(self):
        fixture(self.root)
        p = self.root/'courses/A/培训需求说明书A.md'
        p.write_text(p.read_text(encoding='utf-8')+'\n引用 "总时长 720 分钟" 不是本课声明。', encoding='utf-8')
        self.assertTrue(contracts.quote_spans('引用 "总时长 720 分钟"'))
        self.cli('check_consistency.py', '--project', self.root, expected=0)

    def test_windows_non_utf8_parent(self):
        fixture(self.root)
        result = self.cli('pipeline', 'init', '--project', self.root, '--source', self.root/'素材.md', '--profile', self.root/'画像.yaml', utf8='0', expected=0)
        self.assertNotIn('UnicodeDecodeError', result.stderr)
        code, output = pipeline.run_script(HERE/'check_consistency.py', ['--project', self.root])
        self.assertEqual(code, 0, output)

    def test_missing_mandatory_checker_blocks(self):
        fixture(self.root)
        with patch.object(pipeline, 'SKILLS', self.root / 'missing-skills'):
            status, _ = pipeline.run_gate(self.root, {}, pipeline.stage_by_id('3-components'))
        self.assertEqual(status, 'blocked')

    def test_same_plan_twice_is_not_dual_validation(self):
        fixture(self.root)
        args, _ = pipeline.resolve_script_args(self.root, {'compared_plans': ['plans/编排方案A.md'] * 2}, 'modules')
        self.assertIsNone(args)

    def test_bridge_rejects_missing_module_id_section_and_disposition(self):
        fixture(self.root)
        text = (self.root / 'courses/A/课程大纲A.md').read_text(encoding='utf-8')
        plan, _ = bridge.load_plan(self.root / 'plans/编排方案A.md')
        comps, _ = bridge.load_components(self.root / '组件清单.md')
        a, b = text.index('### M0'), text.index('### M1')
        variants = [text[:a] + text[b:], text.replace('方法1（Do', '别的方法（Do'),
                    text.replace('| C001 | 方法1 |', ''), text + '\n新增 C999。',
                    text.replace('## 七、能力差距', '能力差距正文')]
        for variant in variants:
            self.assertNotEqual(variant, text)
            self.assertTrue(bridge.verify(variant, plan, comps)[0])
        # A known but deliberately unselected component must retain its disposition.
        plan['unused'] = {'C007': {'name': '附加方法', 'type': 'tool', 'dest': '舍', 'reason': '不适用'}}
        comps['C007'] = comps['C001'].copy()
        self.assertTrue(bridge.verify(text, plan, comps)[0])
        appendix = '#### 附：未选用组件的去向\n| C007 | 附加方法 | tool | 舍 | 不适用 |\n---\n'
        good = text.replace('## 十二、课程核心成果', appendix + '## 十二、课程核心成果')
        self.assertEqual(bridge.verify(good, plan, comps)[0], [])
        self.assertTrue(bridge.verify(good.replace('| 舍 |', '| 自学 |'), plan, comps)[0])

    def test_consistency_rejects_each_time_contract(self):
        fixture(self.root)
        changes = [
            ('培训需求说明书A.md', '总时长 90', '总时长 80'),
            ('课程大纲A.md', '总时长 90', '总时长 80'),
            ('教员课程PPT-StoryboardA.md', '教学时长 90', '教学时长 70'),
            ('课程大纲A.md', '（Do，15 分钟）', '（Do，105 分钟）'),
        ]
        for name, before, after in changes:
            p = self.root / 'courses/A' / name
            original = p.read_text(encoding='utf-8')
            self.assertIn(before, original)
            p.write_text(original.replace(before, after, 1), encoding='utf-8')
            self.cli('check_consistency.py', '--project', self.root, expected=1)
            p.write_text(original, encoding='utf-8')
        p = self.root / 'courses/A/培训需求说明书A.md'
        original = p.read_text(encoding='utf-8')
        p.write_text(original + '\n2 天 × 45 分钟。\n', encoding='utf-8')
        self.cli('check_consistency.py', '--project', self.root, expected=1)

    def test_manifest_accepts_complete_and_rejects_hidden_or_omitted_files(self):
        fixture(self.root, True)
        bundles = contracts.groups(self.root)
        data = {'courses': [{'files': [p.relative_to(self.root).as_posix() for p in bundle.values()]} for bundle in bundles]}
        put(self.root, 'course-deliverables.json', json.dumps(data, ensure_ascii=False))
        self.cli('check_consistency.py', '--project', self.root, expected=0)
        put(self.root, 'course-deliverables.json', json.dumps({'courses': data['courses'][:1]}, ensure_ascii=False))
        self.cli('check_consistency.py', '--project', self.root, expected=2)
        p = self.root / data['courses'][0]['files'][0]
        hidden = put(self.root, '_drafts/' + p.name, p.read_text(encoding='utf-8'))
        data['courses'][0]['files'][0] = hidden.relative_to(self.root).as_posix()
        put(self.root, 'course-deliverables.json', json.dumps(data, ensure_ascii=False))
        self.cli('check_consistency.py', '--project', self.root, expected=2)

    def test_teaching_edit_invalidates_delivery(self):
        self.complete()
        p = self.root / 'courses/A/教员课程指导手册A.md'
        p.write_text(p.read_text(encoding='utf-8') + '\n新增观察项。\n', encoding='utf-8')
        self.check('6-delivery', expected=2)
        state, _ = pipeline.load_state(self.root)
        self.assertEqual(state['stages']['5-teaching']['status'], 'pending')

    def test_derived_source_edit_invalidates_extraction(self):
        self.complete()
        put(self.root, 'kb/derived/素材.md', '新派生内容。')
        self.check('6-delivery', expected=2)
        state, _ = pipeline.load_state(self.root)
        self.assertEqual(state['stages']['1-extract']['status'], 'pending')

    def test_non_utf8_parent_runs_full_child_gates(self):
        self.init()
        for sid in pipeline.STAGE_IDS[1:]:
            self.cli('pipeline', 'check', '--project', self.root, sid, utf8='0', expected=0)


if __name__ == '__main__':
    unittest.main()
