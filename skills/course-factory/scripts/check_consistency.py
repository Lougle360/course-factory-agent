"""Check every unambiguous course bundle. 0 pass, 1 conflict, 2 missing input."""
import argparse
from pathlib import Path
import re
import sys
from course_contracts import groups, TAGS, read, outside_quotes, quote_spans, schedule_data, outline_data


def plan_actual(path):
    _, days, errors = schedule_data(path)
    if errors:
        raise ValueError('; '.join(errors))
    return sum(days.values()), list(days.values())


def outline_module_sum(path):
    modules = outline_data(path)
    return sum(m['minutes'] for m in modules.values()), [(k, v['minutes']) for k, v in modules.items()]


def scan_duration(path):
    out = {'gross': [], 'net': [], 'perday': []}
    pats = {
        'gross': [r'\|\s*(?:建议)?时长\s*\|\s*(\d+)\s*分钟',
                  r'(?:总时长|总课时|总包时长)[^\d\n]{0,16}(\d+)\s*分钟'],
        'net': [r'教学(?:净)?时长[：:\s|]*(\d+)\s*分钟', r'模块[^\d\n]{0,10}合计\s*(\d+)\s*分钟'],
        'perday': [r'每天\s*(\d+)\s*分钟', r'\d+\s*天\s*[×x]\s*(\d+)\s*分钟'],
    }
    for number, raw in enumerate(read(path).splitlines(), 1):
        line = outside_quotes(raw).replace('*', '')
        for key, patterns in pats.items():
            for pat in patterns:
                for match in re.finditer(pat, line):
                    out[key].append((number, int(match.group(1)), raw.strip()))
    return out


def check_bundle(bundle, outline=None, plan=None):
    outline = Path(outline) if outline else bundle['课程大纲']
    plan = Path(plan) if plan else bundle['课程计划']
    modules = outline_data(outline)
    _, days, errors = schedule_data(plan)
    net, gross = sum(m['minutes'] for m in modules.values()), sum(days.values())
    print(f'课程 {outline.name}：NET={net} GROSS={gross}，每天={days}')
    if net > gross:
        errors.append('休息时间为负：NET 大于 GROSS')
    for tag, path in bundle.items():
        data = scan_duration(path)
        for key, expected in (('net', net), ('gross', gross)):
            for line, value, _ in data[key]:
                if value != expected:
                    errors.append(f'{path.name}:{line} {key.upper()} 声明{value} ≠ 实算{expected}')
        for line, value, _ in data['perday']:
            if any(duration != value for duration in days.values()):
                errors.append(f'{path.name}:{line} PERDAY 声明{value} 与实际各天{list(days.values())}不一致')
        if tag in {'培训需求说明书', '课程大纲', '课程计划'} and not data['gross']:
            raise ValueError(f'{path.name} 缺少明确总时长声明')
        for line in read(path).splitlines():
            plain = outside_quotes(line).replace('*', '')
            match = re.search(r'\bDay\s*(\d+)[^（(]{0,10}[（(]\s*(\d+)\s*分钟', plain, re.I)
            if match and (match.group(1) not in days or days[match.group(1)] != int(match.group(2))):
                errors.append(f'{path.name} Day {match.group(1)} 时长声明不符')
            match = re.search(r'(\d+)\s*天\s*[×x]\s*(\d+)\s*分钟', plain)
            if match and (int(match.group(1)) != len(days) or int(match.group(1)) * int(match.group(2)) != gross):
                errors.append(f'{path.name} 天数或总包时长声明不符')
    return errors


def main():
    ap = argparse.ArgumentParser(description='跨文件课程口径检查')
    ap.add_argument('--project', default='.')
    ap.add_argument('files', nargs='*', help='显式指定同一课程的六份文件')
    ap.add_argument('--outline')
    ap.add_argument('--plan')
    a = ap.parse_args()
    try:
        if a.files:
            files = [(Path(a.project) / p).resolve() for p in a.files]
            if len(files) != 6 or len(set(files)) != 6:
                raise ValueError('需显式指定六份不同的教学文件')
            bundle = {}
            for tag in TAGS:
                matches = [p for p in files if tag in p.name]
                if len(matches) != 1:
                    raise ValueError(f'{tag} 必须唯一')
                bundle[tag] = matches[0]
            bundles = [bundle]
        else:
            bundles = groups(a.project)
        if (a.outline or a.plan) and len(bundles) != 1:
            raise ValueError('多课程场景不能用单个 --outline/--plan 覆盖全部课程')
        errors = []
        for bundle in bundles:
            errors.extend(check_bundle(bundle, a.outline, a.plan))
        for error in errors:
            print('❌ ' + error)
        print('判定：' + ('❌ 未通过' if errors else '✅ 通过'))
        return 1 if errors else 0
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print('无法判定：' + str(exc))
        return 2


if __name__ == '__main__':
    sys.exit(main())
