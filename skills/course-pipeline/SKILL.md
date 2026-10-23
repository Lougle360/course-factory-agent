---
name: course-pipeline
description: 「从书/知识库到课程」课程工厂的 L0 总控层——把 chaoyun-knowledge-base-builder（L1 萃取）、course-factory（L1.5 结构还原 + L2 组件提取 + L2 模块编排）、fire-course-dev（L3 教学流水线）四层串联成一条可执行流水线。总控自己不产出任何教学内容，只负责路由、闸门与状态机：哪一阶段该跑谁、每个阶段出口过什么闸、不过往哪退、进度与产物路径持久化以便续跑。触发词：从书到课、知识库转课程、课程流水线、课程工厂、一键出课、排课流水线、流水线状态、闸门放行、pipeline course、course pipeline、L0 总控。
description_zh: 课程工厂四层流水线的总控层，负责路由、闸门与状态机，本身不产出教学内容。
category: education
version: 0.3.0
author: 掌柜
---

# Course Pipeline · L0 总控层

## 一、这层解决什么问题

四个 skill 各自可用，但**串不起来就不是一个产品**：

换一次会话、换一个人来跑，阶段顺序、层间接口、闸门阈值全靠临时记忆——
这条链随时会断。总有人为此专门补一块东西把顺序和闸门口径固定下来。

**总控只做三件事，自己不生产任何教学内容：**

| 职责 | 具体做什么 |
|---|---|
| **路由** | 当前该跑哪个阶段、由哪个 skill 执行、需要什么输入 |
| **闸门** | 每个阶段出口真跑检查脚本，**用退码**决定放不放行 |
| **状态机** | 把阶段状态、闸门结果、产物路径持久化，中断后可续跑 |

> 边界：总控**不得代写组件、不得代排模块、不得代写教学材料**。
> 那是各层 skill 的活。总控越界写内容 = 绕过自己的闸门。

---

## 二、七阶段流水线

| # | 阶段 | 执行者 | 产出 | 出口闸门 |
|---|---|---|---|---|
| 0 | 接单校验 | 本 skill | 版权口径 + 可用画像卡 + 可读素材 | rule：画像卡含非空 `selection_rules` 键、素材可读、版权口径已声明 |
| 1 | L1 萃取 | `chaoyun-knowledge-base-builder` | `fragments.jsonl` | rule：碎片数 > 0 |
| 2 | L1.5 结构还原 | `course-factory` | `chapters.json` | rule：章节 ≥2、起始行单调递增、无 <200 字的空章 |
| 3 | L2 组件提取 | `course-factory` | `组件清单.md` | `check_components.py` |
| 4 | L2 模块编排 | `course-factory` | 编排方案 ≥2 份 | `check_modules.py`（双画像对照）|
| 4→5 | **交接：编排方案 → 课程大纲** | `course-factory` | 《课程大纲》 | `plan_to_outline.py verify --strict` |
| 5 | L3 教学流水线 | `fire-course-dev` | 00–05 七件套 | rule：六类教学文件齐备 **+ 大纲交接核验 + 课程计划时间自洽** |

> **4→5 这一棒此前是断的**：`fire-course-dev` 全文检索「组件清单 / 编排方案」命中 0 处，
> 两边各说各话。现已双向写死——`course-factory` 出 `plan_to_outline.py`，
> `fire-course-dev` 的 01 阶段写入「输入材料两种入口」与三条硬约束。
> 总控在 Stage 5 会读大纲头部的「上游」登记行，找到对应编排方案后跑严格校验。
| 6 | 出厂 | 本 skill | 全部交付物 | `check_text_hygiene.py` + **`check_copyright.py`（版权扫描制）** |

---

## 三、状态机

状态文件：`<项目目录>/pipeline-state.json`

```json
{
  "project": "...", "source": "...", "profile": "...",
  "copyright_stance": "strict|relaxed", "copyright_note": "放宽理由",
  "current": "5-teaching",
  "stages": { "0-intake": {"status": "passed", "artifacts": [], "gate": {...}} },
  "history": [{"ts": "...", "action": "check 4-modules → pass"}]
}
```

### 命令

```bash
PY="<python>"; PL="~/.workbuddy/skills/course-pipeline/scripts/pipeline.py"

# 初始化（顺带跑一遍接单校验）
"$PY" "$PL" init --project . --source <素材> --profile <画像卡.yaml> [--copyright relaxed --note 理由]

"$PY" "$PL" status  --project . [--detail]     # 总览 / 追加操作日志
"$PY" "$PL" enter   --project . <stage>        # 进入某阶段
"$PY" "$PL" artifact --project . <stage> <文件...>   # 登记产物
"$PY" "$PL" check   --project . <stage>        # 跑闸门（退码即判定）
"$PY" "$PL" check   --project . 4-modules --plans <方案A> <方案B>
"$PY" "$PL" advance --project .                # 推进（要求当前阶段已过闸）
"$PY" "$PL" reset   --project . <stage>        # 重置某阶段
```

**退码契约**：`0` 放行 · `1` 闸门未过 · `2` 条件不足（BLOCKED，不是失败）。
所以可以直接 `&&` 串起来做自动化。

### 指针自愈

指针**按状态推导**，永远指向第一个未过闸的阶段，而不是"上次跑到哪"。

> 实际跑流水线常常是乱序的（补跑历史阶段、上游返工后重跑），
> 「检查了谁就推进到谁」的写法会把指针卡死在起始阶段。

---

## 四、闸门路由与失败回退

| 在哪失败 / 被拦 | 判定 | 回退到 |
|---|---|---|
| 画像卡无 `selection_rules` | fail | **拒收**，退回补画像，不许开工 |
| 素材不可读 | fail | 拒收 |
| 版权口径未声明 | fail | 拒收；默认 `strict`（只概括 + 定位） |
| `fragments.jsonl` 为空 | fail | 回 Stage 1，检查上游转换是否静默降级 |
| 章节数 < 2 / 顺序错乱 / 空章 | fail | 回 Stage 2，换 `--pattern` 重做结构还原 |
| `check_components` 不过 | fail | 留在 Stage 3 修组件，不进 Stage 4 |
| 少于 2 份编排方案 | **blocked** | 补齐双画像方案；若确实只出一门课、不做对照，须在状态文件里写明豁免理由 |
| `check_modules` 不过 | fail | 留在 Stage 4 重排，**不许靠改阈值过关** |
| 教学文件不齐 | fail | 回 Stage 5 补 00–05 |
| 文本卫生有非法字符 | fail | 逐个清干净，**不许交付** |

**BLOCKED ≠ FAILED**：材料不齐是为 BLOCKED（退码 2），补齐即可；
判定不合格才是 FAIL（退码 1）。两者混为一谈会导致"补了材料还报错"的排查灾难。

---

## 五、⛔ 本次开发实测抓到的三个自身缺陷（留作反面样本）

写这个 skill 时，用一个真项目（V1《非暴力沟通》）端到端跑，当场咬出三个 bug：

| 缺陷 | 表现 | 根因 |
|---|---|---|
| **朴素子串匹配被字面巧合骗过** | 一张注释里写着「没有 selection_rules」的空画像卡，被判成"含 selection_rules"放行 | 用 `'selection_rules' not in text` 做存在性判断；改为认 YAML 键行且键下非空 |
| **自己把自己的产物排除了** | `1-extract`/`2-restore` 恒报"未产出"，但 `kb/chapters.json` 明明在 | 通用排除目录表含 `kb`，而数据类产物本就住在 `kb/`。拆成 `SKIP_FOR_DATA` / `SKIP_FOR_MD` |
| **改完没落盘** | 指针自愈逻辑写了却不生效 | `save_state()` 在 `sync_pointer()` 之前，改完没保存 |

第三个尤其典型：**代码顺序错误是最难自查的一类 bug，因为两行看起来都对。**

> 这三处全是被"拿真东西跑一遍"逼出来的。写完就交付，等于把 debug 留给了掌柜。

**顺带带出的一条**：写这份文档时又混进了两个英文单词（`Myers`/`instructors`）——
这是语言杂质犯的**第四次**，前三轮靠字符级闸门（`check_text_hygiene.py`）已能拦，
但英文单词是合法 ASCII，字符级白名单看不见。因此给卫生闸门补了「中文散文中的
非白名单英文单词」检查：跳过代码块与行内代码后报警，举例乱码的行用
`hygiene:allow` 豁免。**同一个坑踩到第四次，就说明该升级工具而不是加强记性。**

---

## 六、已知限制

| 限制 | 说明 |
|---|---|
| Stage 3/4/5 必须由 AI 执行 | 总控只能验闸门，不能代替语义判定 |
| `compared_plans` 需人工指定 | 自动按文件名排序取前两份会抓错对照对象（会取到同画像不同时长的两份），**已加显式 `--plans`**，未指定时输出告警 |
| Stage 5 验「文件齐备 + 大纲交接 + 计划时间自洽」 | 仍不校验教学内容质量，质量由 `fire-course-dev` 自己的阶段闸门管 |
| 版权扫描依赖原材料可读 | `init` 时须用 `--source` 指到**可提取文本的原材料**（如 derived 下的 .md）。指向 PDF 会读成乱码，闸门会明示「未执行」而非静默跳过 |
| 大纲与方案的配对靠头部「上游」登记行 | 手写的大纲没有这行，会被判「未登记上游」；这是有意为之——交接必须可追溯 |
| 版权检查目前是登记制 | `strict`/`relaxed` 口径会写进状态文件并在 status 显示，但**不会自动扫描违规摘录** |
| Stage 6 扫描排除 `kb/`、`blind/` 等中间目录 | 若交付物放在这些目录名下的子目录会被漏扫 |

---

## 七、执行纪律

1. **闸门必须能真拦**——新写的检查要用负例试一遍，退码正确才算落地（天天误报的闸门会被当噪音忽略，比没有更糟）
2. **不许为了让数字好看而改阈值**——判据失效时写清根因并给替代方案，由掌柜裁定口径
3. **BLOCKED 与 FAILED 必须区分**——材料缺失 ≠ 质量不合格
4. **每次跑完 `check` 都看退码**，不要只看屏幕上的 ✅
5. **总控不代写内容**——越界写内容等于绕过自己管的闸门
6. **交付前必跑 Stage 6 文本卫生**——同一个坑踩过三次，不再相信"下次注意"
