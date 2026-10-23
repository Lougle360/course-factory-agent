"""Shared file discovery, lineage, and explicit-day timetable contracts."""
import json
import re
from pathlib import Path

SKIP = {'.git', 'build', 'node_modules', 'kb', 'blind', 'sources', 'derived'}
TAGS = ('培训需求说明书', '课程大纲', '课程计划', '学员课程讲义', '教员课程指导手册', 'Storyboard')
TIME = re.compile(r'^(\d{1,2}):(\d{2})\s*[–—\-~～]\s*(\d{1,2}):(\d{2})$')
MODULE = re.compile(r'^###\s*(M\d+)\s*·\s*(.+?)[（(]\s*(Know|Do|Act)\s*[，,]\s*(\d+)\s*分钟')
DAY = re.compile(r'\bDay\s*(\d+)\b|第\s*([一二三四五六七八九十\d]+)\s*天', re.I)


def read(path):
    return Path(path).read_text(encoding='utf-8-sig')


def discover(root, pattern='*.md'):
    root = Path(root).resolve()
    return sorted(p for p in root.rglob(pattern) if p.is_file() and not any(
        x in SKIP or x.startswith(('.', '_')) for x in p.relative_to(root).parts))


def upstream(path):
    return [name for line in read(path)[:4000].splitlines() if '上游' in line
            for name in re.findall(r'`([^`]+)`', line)]


def groups(root):
    """Use an explicit six-file manifest or one unambiguous course per directory."""
    root = Path(root).resolve()
    manifest = root / 'course-deliverables.json'
    if manifest.exists():
        data = json.loads(read(manifest))
        courses = data.get('courses') if isinstance(data, dict) else None
        if not isinstance(courses, list) or not courses:
            raise ValueError('course-deliverables.json 缺少非空 courses 列表')
        candidates = []
        for course in courses:
            if not isinstance(course, dict) or not isinstance(course.get('files'), list):
                raise ValueError('每门课程必须登记 files 列表')
            paths = [(root / name).resolve() for name in course['files'] if isinstance(name, str)]
            if len(paths) != len(course['files']) or any(not p.is_relative_to(root) or not p.is_file() for p in paths):
                raise ValueError('交付清单包含无效、项目外或不存在的文件')
            visible = set(discover(root))
            if any(p not in visible for p in paths):
                raise ValueError('交付清单不得指向中间/隐藏目录或非 Markdown 文件')
            candidates.append(paths)
    else:
        docs = discover(root)
        directories = sorted({p.parent for p in docs if any(tag in p.name for tag in TAGS)})
        candidates = [[p for p in docs if p.parent == folder and any(tag in p.name for tag in TAGS)]
                      for folder in directories]
    if not candidates:
        raise ValueError('没有教学文件；每门课程放独立目录或显式登记交付清单')
    result, claimed = [], set()
    for files in candidates:
        if len(files) != len(set(files)):
            raise ValueError('交付清单重复登记同一文件')
        bundle = {}
        for tag in TAGS:
            matches = [p for p in files if tag in p.name]
            if len(matches) != 1:
                raise ValueError(f'{tag} 需要唯一一份文件，实际 {len(matches)}；请分目录或登记 course-deliverables.json')
            bundle[tag] = matches[0]
        if len(files) != len(TAGS) or len(set(bundle.values())) != len(TAGS):
            raise ValueError('每门课程须恰好六份互不混用的教学文件')
        if claimed.intersection(files):
            raise ValueError('不同课程不得共用同一份教学交付文件')
        claimed.update(files)
        result.append(bundle)
    if manifest.exists():
        unclaimed = {p for p in discover(root) if any(tag in p.name for tag in TAGS)} - claimed
        if unclaimed:
            raise ValueError('存在未登记教学文件：' + ', '.join(str(p.relative_to(root)) for p in sorted(unclaimed)))
    return result


def quote_spans(line):
    spans, start, close = [], None, None
    pairs = {'「': '」', '“': '”', '‘': '’', '"': '"', "'": "'"}
    for i, ch in enumerate(line):
        if start is not None:
            if ch == close:
                spans.append((start, i))
                start, close = None, None
        elif ch in pairs:
            start, close = i, pairs[ch]
    return spans


def outside_quotes(line):
    chars = list(line)
    for start, end in quote_spans(line):
        chars[start:end + 1] = ' ' * (end - start + 1)
    return ''.join(chars)


def schedule_data(path):
    rows, day = [], '1'
    cn_days = dict(zip('一二三四五六七八九十', map(str, range(1, 11))))
    for number, raw in enumerate(read(path).splitlines(), 1):
        line = raw.strip().replace('**', '')
        if line.startswith('#'):
            match = DAY.search(line)
            date = re.search(r'\b\d{4}-\d{2}-\d{2}\b', line)
            if date:
                day = date.group()
            elif match:
                token = match.group(1) or match.group(2)
                day = cn_days.get(token, token)
            continue
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        match = TIME.fullmatch(cells[0])
        if not match:
            if re.match(r'^\d{1,2}:', cells[0]):
                raise ValueError(f'第{number}行时间区间无法解析')
            continue
        h1, m1, h2, m2 = map(int, match.groups())
        if not (0 <= h1 < 24 and 0 <= h2 < 24 and 0 <= m1 < 60 and 0 <= m2 < 60):
            raise ValueError(f'第{number}行时间超出有效范围')
        rows.append({'line': number, 'day': day, 'start': h1 * 60 + m1, 'end': h2 * 60 + m2,
                     'name': cells[1] if len(cells) > 1 else '',
                     'ids': set(re.findall(r'\bC\d{3}\b', line)),
                     'modules': set(re.findall(r'\bM\d+\b', line))})
    if not rows:
        raise ValueError('未解析到课程计划时间轴')
    errors, days, closed, previous = [], {}, set(), None
    for row in rows:
        duration = row['end'] - row['start']
        if duration <= 0:
            errors.append(f"第{row['line']}行结束时间不晚于开始时间")
        if previous and row['day'] != previous['day']:
            closed.add(previous['day'])
            if row['day'] in closed:
                errors.append(f"第{row['line']}行重复进入已结束的日期 {row['day']}")
        elif previous:
            gap = row['start'] - previous['end']
            if gap:
                errors.append(f"第{row['line']}行时间{'空隙' if gap > 0 else '重叠'} {abs(gap)} 分钟；换天须显式标题")
        days[row['day']] = days.get(row['day'], 0) + duration
        previous = row
    return rows, days, errors


def outline_data(path):
    modules, current = {}, None
    for line in read(path).splitlines():
        match = MODULE.match(line.strip())
        if match:
            mid, name, level, duration = match.groups()
            if mid in modules:
                raise ValueError(f'大纲模块 {mid} 重复')
            current = {'name': name, 'level': level, 'minutes': int(duration), 'ids': set()}
            modules[mid] = current
        elif line.startswith(('## ', '#### 附：未选用')):
            current = None
        elif current and (match := re.match(r'^\|\s*(C\d{3})\b', line.strip())):
            current['ids'].add(match.group(1))
    if not modules or any(m['minutes'] <= 0 for m in modules.values()):
        raise ValueError('大纲缺少有效的正时长模块声明')
    return modules
