"""文本卫生闸门：扫非法混入的外来字符，以及中文散文里夹的英文单词。

为什么需要：字符层面的问题在 Stage 2 / Stage 3 连着犯了三次——
西里尔字母串位、希伯来字母串位、Latin-1 乱码 À-ÿ、以及无意义字母粘连。
第四次犯在 Stage 4 的中文文档里，混入了两个英文单词（Myers / instructors），
这类因为是合法 ASCII，字符白名单拦不住，故补一格「散英文词」检查：
跳过代码块与行内代码后，在中文正文里出现的英文单词要报警。

用法:
    python check_text_hygiene.py <file1.md> [file2.md ...]

退出码: 0 = 干净 / 1 = 发现非法字符（英文单词只报警，不拦截）
"""

import re
import sys
import unicodedata

WORD_RE = re.compile(r"(?<![A-Za-z0-9_\-./])[A-Za-z]{3,}(?![A-Za-z0-9_\-./])")

# 技术白名单：这些词在中文交付物里是正常的（标识符 / 术语 / 命令名）。
# 表要有节制——白名单太宽的闸门等于没有闸门。
TECH_WORDS = {
    # 本流水线固有名词
    "python", "json", "yaml", "md", "pdf", "docx", "pptx", "api", "cli", "git",
    "kb", "pipeline", "skill", "skills", "stage", "taxonomy", "rules",
    "markitdown", "jaccard", "html", "css", "http", "https", "url", "uuid",
    # 通用技术词
    "the", "and", "for", "with", "from", "not", "none", "true", "false", "null",
    "import", "def", "return", "args", "arg", "argparse", "path", "home", "dir",
    "warn", "fail", "info", "exit", "code", "usage", "help", "init",
    "print", "read", "write", "open", "sort", "parse", "main", "test",
    "windows", "linux", "macos", "node", "npm", "venv", "pip",
    # 组件类型与本流水线术语
    "know", "act", "locator", "chapters", "fragments", "candidates", "passages",
    "components", "modules", "profiles", "delivery", "restore", "structure",
    "export", "locate", "promote", "demote", "misconception", "concept",
    "guideline", "principle", "framework", "workflow", "boundary", "scene",
    "story", "analogy", "quote", "course", "factory", "hygiene", "check",
    # 闸门口径语（这些在本流水线里是约定俗成的状态 / 判定名）
    "fatal", "warn", "failed", "blocked", "passed", "pending", "running",
    "top", "bug", "promote", "demote", "drop", "evidence", "negative", "type",
    "rule", "level", "report", "gap", "pair", "single", "strict", "relaxed",
    "status", "detail", "project", "source", "profile", "current", "history",
    # taxonomy-v2 类型名（组件清单表格里必然出现）
    "case", "tool", "viewpoint", "solution", "data", "locator", "id",
}

# 「真·错误」：中文交付物里几乎不该出现的字母系统。
# 理由写在旁边，方便以后增删时能回溯决策依据。
BLOCKED_RANGES = [
    ("\u0400-\u04FF", "西里尔字母"),        # емu 这种串位  # hygiene:allow
    ("\u0590-\u05FF", "希伯来字母"),        # וי 这种串位  # hygiene:allow
    ("\u0600-\u06FF", "阿拉伯字母"),
    ("\u0370-\u03FF", "希腊字母"),          # 注意 ⚠️ α β 等符号要放行，单独处理
    ("\u0900-\u097F", "天城文"),
    ("\u0E00-\u0E7F", "泰文"),
    ("\uAC00-\uD7AF", "韩文谚文"),
    ("\u3040-\u30FF", "日文假名"),
    ("\u1E00-\u1EFF", "拉丁扩展附加"),      # 越南语等，中文交付物不该有
]

# 希腊字母要放行少量常见符号（α β π 等在公式/标签里正常）
GREEK_ALLOW = set("αβγδεζηθικλμνξοπρστυφχψωΔΠΣΩ")

# 「警告」：Latin-1 补充区。法语/西语人名合法，但 Stage 2 的 À-ÿ 乱码就是它，  # hygiene:allow
# 所以只报警不拦截，交给人工确认。
WARN_RANGES = [
    ("\u00C0-\u00FF", "Latin-1 补充（可能是人名，也可能是乱码）"),
]

# 常见合法数学符号（课时预算写作「2 天 × 360 分钟」会用到）。
# 不加入白名单的话，每次扫都报警，久了闸门会被当噪音忽略——那比没有闸门更糟。
WARN_ALLOW = set("×÷°±‰′″")

ALLOWED_PUNCT = set("，。、；：？！「」『』（）—…·《》%℃")

# 显式豁免标记：写在行尾即可让该行的一切检查放行。
# 用途是文档里必须举例演示"什么是乱码"——否则举例的那行会被自己的闸门判死。
EXEMPT_MARKER = "hygiene:allow"


def classify(ch):
    for rng, label in BLOCKED_RANGES:
        lo, hi = rng.split("-")
        if lo <= ch <= hi:
            if label == "希腊字母" and ch in GREEK_ALLOW:
                return None
            return ("FAIL", label)
    for rng, label in WARN_RANGES:
        lo, hi = rng.split("-")
        if lo <= ch <= hi:
            if ch in WARN_ALLOW:
                return None
            return ("WARN", label)
    return None


def strip_code(ln):
    """去掉行内代码 `...` —— 那里面的英文是标识符，不是杂质。"""
    return re.sub(r"`[^`]*`", " ", ln)


def scan_words(lines):
    """在中文正文里找混入的英文单词（代码块整体跳过）。

    判据：一行里若含中日韩字符，则视为"中文正文行"；其中的英文单词若不在
    技术白名单里，多半是生成时串进来的杂质。代码块内的行不参与。

    ⚠️ 只对 Markdown 生效。源码文件里中英混排是正常的（注释里的标识符），
    照扫会一次冒出几百条告警——天天误报的闸门会被当噪音忽略，比没有更糟。
    """
    out = []
    in_fence = False
    in_front = False   # YAML frontmatter：其中的键名是固定写法，不报警
    for lineno, ln in enumerate(lines, 1):
        stripped = ln.strip()
        if lineno == 1 and stripped == "---":
            in_front = True
            continue
        if in_front:
            if stripped == "---":
                in_front = False
            continue
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        plain = strip_code(ln)
        if not any("\u4e00" <= ch <= "\u9fff" for ch in plain):
            continue  # 整行没有中文，多半是纯代码/表格表头，不判
        for m in WORD_RE.finditer(plain):
            w = m.group(0)
            if w.lower() in TECH_WORDS:
                continue
            ctx = plain[max(0, m.start() - 12):m.end() + 12].strip()
            out.append((lineno, "WARN", "中文正文中的英文单词", f"{w!r} …{ctx}…"))
    return out


def scan(path, check_words=True):
    findings = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return [(0, "FATAL", "文件不存在", "")]
    for lineno, ln in enumerate(lines, 1):
        # 显式豁免：文档里要举例说明"什么是乱码"时，那行本身必须允许写乱码
        if EXEMPT_MARKER in ln:
            continue
        for pos, ch in enumerate(ln, 1):
            r = classify(ch)
            if r:
                ctx = ln[max(0, pos - 12):pos + 12].strip()
                findings.append((lineno, r[0], r[1], f"{ch!r} @列{pos} …{ctx}…"))
    if check_words:
        findings.extend(scan_words(lines))
    findings.sort(key=lambda x: x[0])
    return findings


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    total_fail = total_warn = 0
    for path in sys.argv[1:]:
        check_words = path.lower().endswith((".md", ".markdown"))
        fs = scan(path, check_words)
        name = path.replace("\\", "/").split("/")[-1]
        if not fs:
            print(f"[OK]   {name}")
            continue
        fails = [f for f in fs if f[1] == "FAIL"]
        warns = [f for f in fs if f[1] == "WARN"]
        total_fail += len(fails)
        total_warn += len(warns)
        flag = "[FAIL]" if fails else "[WARN]"
        print(f"{flag} {name}  — 非法 {len(fails)} / 可疑 {len(warns)}")
        for lineno, level, label, detail in fails[:20]:
            print(f"     ✗ 行{lineno}  {label}: {detail}")
        for lineno, level, label, detail in warns[:10]:
            print(f"     ⚠ 行{lineno}  {label}: {detail}")
        if len(fails) > 20:
            print(f"     … 其余 {len(fails) - 20} 处略")

    print("-" * 60)
    print(f"文本卫生：非法 {total_fail} 处 · 可疑 {total_warn} 处")
    if total_fail:
        print("⛔ 存在非法字符，不得交付")
        sys.exit(1)
    print("✅ 通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
