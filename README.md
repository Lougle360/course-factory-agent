# course-factory-agent

> 给它一本书或一套知识库，把可追溯资料组织成可继续开发、可检查的培训课程。

本仓库由三个本地 Skill 和一个资料整理器子模块组成：

| 层 | Skill | 职责 |
|---|---|---|
| L0 | `course-pipeline` | 路由、阶段检查、状态保存和返工失效 |
| L1 | `chaoyun-knowledge-base-builder` | 多格式资料转为可追溯碎片（Git 子模块） |
| L1.5 + L2 | `course-factory` | 结构还原、组件提取、模块编排和大纲交接 |
| L3 | `fire-course-dev` | 需求、大纲、计划、讲义、教员手册和 PPT Storyboard |

总控不代写内容。脚本检查可计算的结构和一致性，AI/人工负责语义判断、内容复核与试讲。

## 流程

```text
0 接单校验
→ 1 资料萃取
→ 2 章节结构还原
→ 3 组件提取
→ 4 模块编排
→ 5 六类教学材料
→ 6 文本卫生与原文重合扫描
```

每个阶段只有三种结果：

- `0`：通过；
- `1`：检查不合格；
- `2`：输入不足或无法判定，必须补材料后重试。

不能跳过前置阶段。素材、方案、教学文件、检查脚本或登记配置变化后，受影响阶段及下游的旧通过结果会自动失效。

## 主要检查

- 画像必须是有效 YAML，`selection_rules` 为非空规则列表。
- 碎片、章节、组件清单不能只“有文件”，内容也必须可解析且非空。
- 单课保留组件、时长、层级、意图和去向检查；双画像额外检查位次反转与 Do 意图差异。
- 大纲逐模块核对名称、顺序、层级、时长和组件归属。
- 课表使用显式 Day/日期标题，检查钟点范围、重叠、空隙、逐模块实排和短课总量。
- 六类教学文件逐门课程对账 GROSS 总包、NET 净教学和 PERDAY 每日时长。
- 中文原文重合扫描默认连续 20 字阻断、12 字提示，支持跨行和任意偏移。
- 缺检查脚本、缺原材料文本、无法解析或无足够中文都不会被当成成功。

这些自动检查不等于教学效果、内容忠实度、授权充分性或法律合规已经验收。

## 安装

需要 Git、Python，以及能使用 PyYAML 的 Python 环境。当前版本已在 Python 3.14.9 验证。

```bash
git clone --recurse-submodules https://github.com/Lougle360/course-factory-agent.git
```

把 `skills/` 下三个目录复制到同一个 Skill 根目录，再把子模块放到同级目录：

```text
<skills-root>/
├─ course-pipeline/
├─ course-factory/
├─ fire-course-dev/
└─ chaoyun-knowledge-base-builder/
```

四个目录必须同级，因为总控按自身位置寻找兄弟 Skill；不依赖 WorkBuddy、固定盘符或特定用户名。

为资料整理器创建独立环境：

```powershell
py -3.14 -m venv <skills-root>\chaoyun-knowledge-base-builder\.venv
& <skills-root>\chaoyun-knowledge-base-builder\.venv\Scripts\python.exe -m pip install -r <skills-root>\chaoyun-knowledge-base-builder\scripts\requirements.txt
```

## 快速开始

PowerShell 示例：

```powershell
$CoursePython = "<skills-root>\chaoyun-knowledge-base-builder\.venv\Scripts\python.exe"
$CoursePipeline = "<skills-root>\course-pipeline\scripts\pipeline.py"
$CourseProject = "<课程项目绝对路径>"

& $CoursePython $CoursePipeline init --project $CourseProject --source "<素材绝对路径>" --profile "<画像卡绝对路径>"
& $CoursePython $CoursePipeline status --project $CourseProject --detail
& $CoursePython $CoursePipeline check --project $CourseProject 1-extract
```

素材为 PDF 等二进制时，初始化另加 `--source-text "<可读派生文本>"`，用于版权重合检查。原文件仍应保留。

单门课必须明确登记不做双画像对照的理由：

```powershell
& $CoursePython $CoursePipeline init --project $CourseProject --source "<素材>" --profile "<画像>" --single-course-reason "本次只开发一门课程"
```

双画像在 Stage 4 显式指定两份不同方案：

```powershell
& $CoursePython $CoursePipeline check --project $CourseProject 4-modules --plans "plans/方案A.md" "plans/方案B.md"
```

详细文件结构、组件表、编排表、课表和多课程清单格式见
[`runtime-contract.md`](skills/course-factory/references/runtime-contract.md)。

## 大纲交接

生成器会自动创建输出父目录，并在大纲头部保留相对于大纲文件的上游路径：

```powershell
$FactoryScripts = "<skills-root>\course-factory\scripts"

& $CoursePython "$FactoryScripts\plan_to_outline.py" gen `
  --plan "<编排方案.md>" `
  --components "<组件清单.md>" `
  --profile "<画像卡.yaml>" `
  --out "<课程大纲.md>"

# 补完【AI 补：…】后严格复核
& $CoursePython "$FactoryScripts\plan_to_outline.py" verify `
  --outline "<课程大纲.md>" `
  --plan "<编排方案.md>" `
  --components "<组件清单.md>" `
  --strict
```

生成器区分：

- 教学净时长：模块分钟之和；
- 总时长：教学、休息、午休等全部排期之和。

未选用组件也必须写明舍、自学、备选或带出及理由，不能在生成时静默丢失。

## 多门课交付

默认每门课一个目录，每目录恰好一份：

1. 培训需求说明书
2. 课程大纲
3. 详细课程计划
4. 学员课程讲义
5. 教员课程指导手册
6. PPT Storyboard

跨目录或同目录多门课时，在项目根目录用 `course-deliverables.json` 显式登记。正式材料不要放在 `kb`、`derived`、`_drafts` 等中间目录。

## 验证

```powershell
$CoursePython = "<skills-root>\chaoyun-knowledge-base-builder\.venv\Scripts\python.exe"

& $CoursePython -B -m unittest discover -s "skills\course-factory\scripts" -p "test_regressions.py" -v
& $CoursePython -B -m unittest discover -s "chaoyun-knowledge-base-builder\scripts" -p "test_*.py" -v
& $CoursePython -m pip check
```

本次修复版验收基线：

- 课程流水线 44 项测试通过；
- 资料整理器 15 项测试通过；
- 四个 Skill 的格式校验通过；
- 独立合成样例从接单到出厂七阶段全部通过。

测试夹具是结构验证样例，不是实际教学成品。

## 版权边界

处理受版权保护材料时，默认交付物只包含整理者概括和来源定位，不包含未授权原文。需要逐字使用时另行取得授权并登记范围。

扫描只覆盖中文精确重合，不能识别所有改写、非中文引用或授权状态；它是出厂检查之一，不是法律结论。

## 已知限制

- 组件分类、模块取舍和教学内容仍需要 AI/人工做语义判断。
- PDF 容器可解析不代表提取完整；扫描件可能需要 OCR 与人工抽检。
- 结构还原依赖可识别章节标题；不符合排版惯例时要调整模式并复核。
- Stage 05 输出 PPT Storyboard，不生成最终 `.pptx`。
- 自动门禁不替代真实学员试讲、培训师可执行性和组织验收。

## License

MIT © Lougle360
