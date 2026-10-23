"""Validate explicit-day timetables and module ownership. 0 pass, 1 fail, 2 blocked."""
import argparse
import re
import sys
from course_contracts import read, schedule_data, outline_data, outside_quotes


def main():
    ap = argparse.ArgumentParser(description='课程计划时间与模块归属校验')
    ap.add_argument('plan')
    ap.add_argument('--outline')
    ap.add_argument('--total', type=int)
    a = ap.parse_args()
    try:
        rows, days, errors = schedule_data(a.plan)
        claims = []
        for raw in read(a.plan).splitlines()[:80]:
            line = outside_quotes(raw).replace('*', '')
            claims.extend(int(x) for x in re.findall(r'(?:总时长|总课时|总包时长)[^\d\n]{0,12}(\d+)\s*分钟', line))
        if a.total is not None:
            claims.append(a.total)
        if not claims:
            raise ValueError('未声明总时长；请写总时长 N 分钟或使用 --total')
        total = sum(days.values())
        if any(n <= 0 or n != total for n in claims):
            errors.append(f'总量不符：声明 {claims}，实排 {total} 分钟')
        if a.outline:
            modules = outline_data(a.outline)
            used = {mid: 0 for mid in modules}
            sequence = []
            for row in rows:
                owners = set(row['modules'])
                for cid in row['ids']:
                    targets = {mid for mid, m in modules.items() if cid in m['ids']}
                    if len(targets) != 1:
                        errors.append(f"第{row['line']}行组件 {cid} 无唯一大纲归属")
                    owners.update(targets)
                if not owners:
                    if not re.search(r'茶歇|午休|休息|签到|过渡', row['name']):
                        errors.append(f"第{row['line']}行教学/活动须登记模块 M 编号或组件 C 编号")
                    continue
                if len(owners) != 1 or not owners.issubset(modules):
                    errors.append(f"第{row['line']}行跨模块或未知模块：{sorted(owners)}")
                    continue
                mid = next(iter(owners))
                used[mid] += row['end'] - row['start']
                if not sequence or sequence[-1] != mid:
                    sequence.append(mid)
            if sequence != list(modules):
                errors.append(f'教学模块顺序不一致：{sequence}，大纲 {list(modules)}')
            for mid, module in modules.items():
                if used[mid] != module['minutes']:
                    errors.append(f"{mid} 声明{module['minutes']}实排{used[mid]}分钟")
        print(f'解析 {len(rows)} 段，{len(days)} 天，实排 {total} 分钟')
        for error in errors:
            print('❌ ' + error)
        print('判定：' + ('❌ 未通过' if errors else '✅ 通过'))
        return 1 if errors else 0
    except (OSError, UnicodeError, ValueError) as exc:
        print('无法判定：' + str(exc))
        return 2


if __name__ == '__main__':
    sys.exit(main())
