---
name: course-pipeline
description: 从书或知识库到课程的总控层。串联资料萃取、结构还原、组件提取、模块编排和 FIRE 教学开发，执行出口检查，保存阶段状态与产物路径，支持续跑和返工。用于整条课程流水线的启动、状态查询、阶段验收和出厂检查；不代写教学内容。
metadata:
  description_zh: 课程工厂四层流水线的总控层，负责路由、闸门与状态机。
  category: education
  version: 0.3.1
  author: 掌柜
---

# Course Pipeline · L0 总控层

总控负责路由、检查、状态，不代替各层的内容生产和教学质量审核。
所有产物放入用户指定的项目根目录；不要把项目输出写进 Skill 安装目录。

## 环境与依赖

四个 Skill 须位于同一个安装根目录，脚本按自身位置寻找兄弟目录，不依赖特定应用或盘符。
总控需要 Python 和 PyYAML；本机使用已配置的知识库构建器 Python 3.14.9 环境。
从实际安装位置确定脚本路径；不要复制其他机器的用户目录。

PowerShell 示例（先将变量设为实际绝对路径）：

```powershell
$CoursePython = "<安装根目录>/chaoyun-knowledge-base-builder/.venv/Scripts/python.exe"
$CoursePipeline = "<安装根目录>/course-pipeline/scripts/pipeline.py"
$CourseProject = "<课程项目绝对路径>"
& $CoursePython $CoursePipeline init --project $CourseProject --source "<原始素材绝对路径>" --profile "<画像卡绝对路径>"
& $CoursePython $CoursePipeline status --project $CourseProject --detail
```

原始素材为 PDF 等二进制格式时，另加 `--source-text "<可读派生文本绝对路径>"`，供版权重合检查使用。原文件仍单独保留。路径缺失、无足够中文、解析失败，不算扫描通过。

## 七阶段与出口检查

| 阶段 | 执行者 | 产物与检查 |
|---|---|---|
| 0-intake | 本 Skill | 可读非空素材；有效画像 YAML；非空 selection_rules；版权口径 |
| 1-extract | chaoyun-knowledge-base-builder | fragments.jsonl：有效 JSON 对象、非空来源/修订/碎片 ID、raw_text、anchor，ID 不重复 |
| 2-restore | course-factory | chapters.json：至少两章、有效单调行范围、实际正文不少于 200 字且计数字段一致 |
| 3-components | course-factory | 非空组件清单，通过 check_components.py |
| 4-modules | course-factory | 编排方案，通过单方案结构检查和默认双画像差异检查 |
| 5-teaching | fire-course-dev | 每门课程六类材料齐全；严格大纲交接检查、逐模块课表检查、跨文件课时检查 |
| 6-delivery | 本 Skill | 所有交付 Markdown 通过文本卫生和原文重合扫描 |

每层开始时读取对应 Skill；FIRE 按用户所需阶段读取相应 references，不提前生成用户未要求的后续材料。
Stage 5 的六类材料为：培训需求说明书、课程大纲、详细课程计划、学员课程讲义、教员课程指导手册、PPT Storyboard。Storyboard 是页稿，不是 .pptx 文件。

## 命令与状态

```text
pipeline.py status   --project <目录> [--detail]
pipeline.py enter    --project <目录> <阶段>
pipeline.py artifact --project <目录> <阶段> <文件...>
pipeline.py check    --project <目录> <阶段>
pipeline.py check    --project <目录> 4-modules --plans <方案A路径> <方案B路径>
pipeline.py advance  --project <目录>
pipeline.py reset    --project <目录> <阶段>
```

- `init` 初始化并检查接单；已有状态文件时拒绝覆盖。续跑使用 status/check，不重新 init。
- enter/check 不允许跳过前置阶段；artifact 只是登记文件，不能代替检查。
- check 通过后 current 自动指向第一个未通过阶段。advance 进入该阶段，不额外跳过一关；连续 advance 不会跳关。
- reset 撤销本阶段及其下游的通过状态，保留原始产物和历史。
- 上游产物、登记配置或检查脚本变化时，下一次读取状态会撤销受影响阶段及下游的旧通过结果。修改后必须重跑；不会自动重新生成内容。
- 旧版状态没有内容指纹，首次读取时会要求重新验收，不沿用旧通过标记。
- 只有全部七阶段通过才报告整条流水线通过。状态和完整检查输出保存在项目的 pipeline-state.json。

退出码：`0` 通过，`1` 检查不合格，`2` 条件不足/无法判定。两种非零都必须停下；补材料后重跑，不可把 BLOCKED 当成功。

## 输入与路径契约

画像的 selection_rules 是非空列表，每条至少有非空 condition/action/reason，action 只能为 promote、demote、drop。例如：

```yaml
selection_rules:
  - condition: 工作中需要即时操作
    action: promote
    reason: 学员必须能现场完成操作
```

产物登记与 --plans 使用项目根目录相对路径，保留子目录，不能指向项目外。
同名上游文件有多份时必须使用准确路径，不按排序猜测配对。

默认要求两份不同编排方案。只开发一门课时，可在 init 或 check 4-modules 时加
`--single-course-reason "本次只开发一门课的具体理由"`，并指定恰好一份方案。
此模式仍检查组件覆盖、时间、层级、意图、去向，只豁免双画像差异比较；报告不能声称验证了画像差异。
不要为凑双方案或达标而虚构学员画像、修改阈值。

## 教学交接与交付布局

每门课六份文件放同一独立子目录；多个版本需移入以 _ 开头的草稿目录。
需要跨目录或同目录多门课时，用项目根目录的 course-deliverables.json 显式登记。
具体清单格式、课表格式和引用规则见兄弟 Skill 的
`course-factory/references/runtime-contract.md`，在组织交付文件与课表时必须读取。

大纲头部必须写明唯一上游，例如：

```text
**上游**：`plans/编排方案A.md` / `组件清单.md`
```

生成器只出骨架，须补完语义内容并通过 verify --strict。模块顺序、名称、层级、时长和逐模块组件归属均须与方案一致。

课表时间第一列写 HH:MM-HH:MM；跨天使用明确的 Day 1 / 第一天 / 日期标题。
教学行须有 M 编号或可唯一映射的 C 编号；休息行明确标茶歇/午休/休息。
不要用时间倒退暗示换天，或用累计分钟数猜模块归属。

## 版权口径与限制

默认 strict：交付物只用概括和定位。自有/公版等获准放宽时，使用
`--copyright relaxed --note "明确理由"`；此设置登记依据，不关闭扫描。
确有授权的逐行引用可添加 copyright:allow 并注明授权范围；不能用该标记掩盖未授权内容。

扫描去掉标点、空白后比较中文：默认连续 20 字重合阻断，12 字仅提示；支持跨行和任意偏移。
它只能发现精确中文重合，不能证明授权充分、语义忠实或法律合规。
当前非中文素材不可据此自动放行，应另行审查。

kb、blind、sources、derived、build、node_modules 以及以 . 或 _ 开头的目录属于中间目录，不放正式教学交付物。正式清单也不得指向这些排除目录。
结构检查通过不代表教学质量、讲师可执行性或用户确认已通过；这些仍须按 FIRE 闸门与实际试讲验收。
