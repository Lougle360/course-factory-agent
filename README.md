# course-factory-agent

> 给它一本书或一个知识库，它产出一门能上的课。
>
> 一个由四个 Skill 串联而成的课程工厂流水线：**萃取 → 还原 → 编排 → 教学**，每阶段出口有真闸门，退码即判决。

---

## 一、它解决什么问题

把一本书变成一门课，难的不是"写内容"，而是**中间那几步全靠人脑托盘**：

- 素材转出来是一整条没有层级的文本流，直接切组件等于随机下刀
- 组件好摘，但"这批组件给不同的人该怎么取舍排序"没有判据
- 一层一环往下做，各段之间无人互检，返工成本全堆到最后

本仓库把这个流程做成了**可执行流水线**：每一层做什么、上一层交什么、出口过什么闸、不过往哪退，全部明文规定，并且**由脚本执行**（不是写在文档里等人自觉）。

---

## 二、四层结构

| 层 | Skill | 职责 | 位置 |
|---|---|---|---|
| **L0 总控** | `course-pipeline` | 路由 / 闸门 / 状态机，自己不产内容 | 本仓库 `skills/course-pipeline` |
| **L1 萃取** | `chaoyun-knowledge-base-builder` | 多格式素材 → 可追溯碎片 | 外部仓库（submodule） |
| **L1.5 + L2 编排** | `course-factory` | 结构还原 → 组件提取 → 模块编排 | 本仓库 `skills/course-factory` |
| **L3 教学** | `fire-course-dev` | 需求→大纲→计划→讲义→教员手册→PPT 页稿 | 本仓库 `skills/fire-course-dev` |

流水线七阶段：

```
0 接单校验 → 1 L1 萃取 → 2 L1.5 结构还原 → 3 L2 组件提取
           → 4 L2 模块编排 → 5 L3 教学流水线 → 6 出厂
```

**Stage 2 常被忽略，却是全链路成败关键**：多数 PDF 经转换后 H1/H2/H3 全丢，
此时在上层切组件，等于在没有语义边界的文本上随机下刀。

---

## 三、闸门：写给人看的规矩会失效，写成退码的规矩不会

| 阶段出口 | 闸门 | 检查什么 |
|---|---|---|
| 0 接单 | rule | 画像卡必须有非空 `selection_rules` 键、素材可读、版权口径已声明 |
| 1 萃取 | rule | 碎片数 > 0 |
| 2 还原 | rule | 章节 ≥2、起始行单调递增、无 <200 字空章 |
| 3 组件 | `check_components.py` | ID 唯一、类型受控、locator 齐备、声明数=实际数、缺号有说明 |
| 4 编排 | `check_modules.py` | 组件无孤儿、时长自洽、双画像对照指标 |
| 5 教学 | rule | 六类教学文件齐备 |
| 6 出厂 | `check_text_hygiene.py` | 外来字符 + 中文散文里混入的英文单词 |

**退码契约**：`0` 放行 · `1` 闸门未过 · `2` 条件不足（BLOCKED）· 可直接 `&&` 串联自动化。

> BLOCKED ≠ FAILED。**材料缺失 ≠ 质量不合格**，两者混为一谈会制造"补了材料还报错"的排查灾难。

---

## 四、实证记录（《非暴力沟通》全书）

这条流水线不是在纸上画的，用一整本书跑通过：

| 阶段 | 实测结果 |
|---|---|
| L1 萃取 | 1939 条碎片，但 heading_path 全空、粒度退化到句子级（中位 32 字）→ **催生了 L1.5** |
| L1.5 还原 | 14 章，顺序正确，平均 7808 字/章，健康度校验通过 |
| L2 组件 | 736 候选段 → AI 精读 12,317 字 → **63 个组件**，14 章全覆盖 |
| L2 编排 | 同批组件换画像：**位次反转 14 处、Do 层意图占比差 27.5pp** |
| 外部盲测 | 双盲评审逐字反推出「有制裁权的管理者」vs「无权力、单次接触 3–8 分钟的一线服务者」 |
| 文案产出 | 组件清单 + 三套编排方案，全部通过文本卫生闸门 |

**实测换来的三条硬规矩**（都已在代码/文档里固化）：

1. **脚本做定位强、做判定弱**——规则大候选类型准确率约 40%。脚本只出候选队列，**绝不许直接写 `type` 字段**。
2. **`Know/Do/Act` 三段配比不能做画像验收判据**——两轮对照均恒为 8.3pp。它在中文技能里主要由技能性质定，粒度选错了层。已用 Do 层内 P/E/T/R 意图占比替代。
3. **指标会被"预算"污染**——压到同样课时后 Jaccard 从 51.6% 掉到 36.2%，先看变量是不是被别的因素绑架。

---

## 五、安装

```bash
# 1. 连同子模块一起拉取
git clone --recurse-submodules https://github.com/Lougle360/course-factory-agent.git

# 2. 把 skills/ 下的三个 skill 放进你的 skills 目录
cp -r skills/course-pipeline  ~/.workbuddy/skills/
cp -r skills/course-factory   ~/.workbuddy/skills/
cp -r skills/fire-course-dev  ~/.workbuddy/skills/

# 3. L1 的 kb-builder 走子模块（自带 requirements.txt，需建 venv）
python -m venv vendor/chaoyun-knowledge-base-builder/.venv
vendor/chaoyun-knowledge-base-builder/.venv/Scripts/python.exe \
  -m pip install -r vendor/chaoyun-knowledge-base-builder/scripts/requirements.txt
```

**运行本仓库的脚本只需 Python 3.13 + 标准库，无第三方依赖。**

### 跑一条流水线

```bash
PL=~/.workbuddy/skills/course-pipeline/scripts/pipeline.py

python "$PL" init --project . --source <素材.pdf> --profile <画像卡.yaml>
python "$PL" status
python "$PL" check  --project . <stage>          # 退码 0 才准进下一阶段
python "$PL" check  --project . 4-modules --plans <方案A.md> <方案B.md>
python "$PL" advance --project .
```

---

## 六、⛔ 版权硬约束（最高优先级）

本流水线是为**受版权保护的材料**也能合规使用而设计的：

> **交付物只能含「概括 + 定位」，严禁摘录原文。**
> 改写成自己的话，保留 `locator`（章 + 行区间）以便回溯；课堂要用原文另走授权。

这是 `course-factory` 的硬约束，写在 SKILL.md 而不是注释里。若材料为自有知识库或公版作品，
可按你的指示放宽，但**必须在产出文件头部明示已放宽及理由**。

---

## 七、组件出处与许可

| 组成 | 许可 / 出处 |
|---|---|
| `skills/course-pipeline` | MIT（本仓库）|
| `skills/course-factory` | MIT（本仓库）|
| `skills/fire-course-dev/SKILL.md` | MIT（本仓库）|
| `skills/fire-course-dev/references/*.md` | **改编自一份署名 "FIRE 课程开发" 的内部方法稿（V1.0），原件未标注许可证**。本仓库仅作方法论重组与工程化，若你持有该稿权利且不希望公开，请提 issue 或邮件联系，将在 48 小时内下架相关文件。|
| `vendor/chaoyun-knowledge-base-builder` | **第三方仓库，以 git submodule 引用**，版权归原作者所有，本仓库不主张任何权利 |

---

## 八、已知限制

- Stage 3/4/5 的语义判定必须由 AI 完成，脚本只能验闸门，不能代替判断
- 结构还原依赖"章节标题重复出现"这一排版惯例；换成无章节号的文集需要改 `--pattern`
- Stage 5 只检查教学文件是否齐备，不校验内容质量（质量由 `fire-course-dev` 自己的阶段闸门管）
- 版权检查目前是登记制（`strict`/`relaxed` 记进状态文件），**不自动扫描违规摘录**

---

## 九、开发纪律（本项目自己遵守的）

这几条不是口号，是踩过的坑：

1. **闸门必须能真拦**——新写的检查要用负例试一遍，退码正确才算落地。天天误报的闸门会被当噪音忽略，比没有更糟
2. **写完就拿真东西跑一遍**——本仓库的 Stage 2/3 闸门与总控状态机，都是被真实素材逼出 bug 后才修好的
3. **不许为了让数字好看而改阈值**——判据失效时写清根因并给替代方案
4. **脚本错了不要改上游**——在自家层加校验，避免跟随上游升级而失效
5. **同一个坑踩到第四次就升级工具**——别再加强记性了

---

## License

MIT © Lougle360
