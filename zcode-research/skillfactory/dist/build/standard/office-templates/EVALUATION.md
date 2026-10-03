# office-templates-skill 评测报告

> 结论先行：同一模型在加载本技能后，中文办公文书生成任务双臂双重复盲评（5 任务）得分从 **7.7 → 8.9（Δ +1.20，任务级胜率 100%，反向任务 0）**，判定**达标**（accepted=true）；确定性评测第 1 轮通过。评测脚本随包附带，本报告的确定性部分任何人可按「四、复现」复跑验证；盲评聚合原始数据见开发方评测存档（未随包分发）。

## 一、评测方法

两层评测，均在本技能的开发管线中执行（评测管线未随包分发；确定性部分可按「四、复现」用随包脚本复跑）：

**第 1 层：确定性评测（机器判定，无随机、无网络）**

`eval/runner.py` 对 8 个官方样例单元（周报/请示函/会议通知/工作总结 × case1/case2）执行六类检查（contract §5）：单元齐全且产物文件集精确 / docx XML 安全（拒绝 DOCTYPE/ENTITY，防 XXE）/ 版式四要素（spec V2–V5）/ fields.json 自洽（spec S1–S3）/ 台账与 docx 实际内容一致且缺失记账正确（F1/F2/F4）/ 与参照产物字段填充一致率 ≥90%（spec §10）。任一失败 exit 1。红绿双向校验成立：`runner reference/out reference/out` 全过为绿、空目录判红（v0.2 ab5 任务 rubric 第 4 条要求并已实测）。

**第 2 层：有无技能对照盲评（A/B，EVAL-SPEC v0.2 双臂双重复）**

- 任务集 5 个（`eval/golden.json` 的 `ab_tasks`）：ab1 标准四类全量生成、ab2 必填缺失边界、ab3 空列表与字符串型列表边界、ab4 非法输入拒绝、ab5 确定性与交付自评；每任务每臂 **2 次独立重复**（双臂双重复，共 5×2×2=20 份盲评产物）。
- 双臂同模型：基线臂裸做任务；治疗臂先读 `SKILL.md` 及其 references 后按技能方法做同一任务；甲乙匿名落盘、交替呈现，裁判盲评（不知道甲乙哪个来自技能组）。
- 聚合口径：逐任务两重复取 majority 判臂，任务级胜率 = majority 为 treatment 的任务占比；判定按 v0.2 复合验收线（结果表 accepted=true）。

## 二、结果

### 2.1 盲评（v0.2 双臂双重复）

| 轮次 | 任务数 | 基线均分 | 治疗均分 | Δ | 任务级胜率 | 反向任务 | 判定 |
|---|---|---|---|---|---|---|---|
| v0.2 双臂双重复 | 5 | 7.7 | 8.9 | **+1.20** | **100%（5/5）** | 0 | **达标**（accepted=true） |

逐任务两臂均分与 majority（聚合字段 `taskAggs`）：

| 任务 | 基线均分 | 治疗均分 | majority |
|---|---|---|---|
| ab1-standard-four-templates（标准四类全量） | 7.0 | 9.0 | treatment |
| ab2-boundary-missing-required（必填缺失边界） | 8.0 | 9.0 | treatment |
| ab3-empty-and-string-lists（列表边界） | 7.5 | 9.0 | treatment |
| ab4-invalid-input-rejection（非法输入拒绝） | 8.5 | 8.5 | treatment |
| ab5-determinism-layout-selfeval（确定性与交付自评） | 7.5 | 9.0 | treatment |

5 个任务 majority 全为 treatment、无一反向；其中 ab4 两臂同分（8.5），该任务考察的退出码契约较易被裸模型答对，技能优势集中在其余四类任务。

### 2.2 确定性评测（第 1 轮通过）

- **开发管线第 1 轮（rep1）留档（存档未随包分发）**：8 样例按 contract §2 命令行全量重生成后 runner 全过（runner_final 留档：ok=true、68 项 checks 全 pass、字段填充一致率 100.0% 66/66）；D1 确定性成立（determinism 留档：四类 case1 的 fields.json 除 outputs 外 0 diff、docx 语义签名逐字节全等 docx_identical_sig=true、字段一致率 4×100%）。
- **分发包复跑（2026-09-30，发包时实跑，命令见「四、复现」）**：8 条生成命令全部 exit=0（Windows x64 / Python 3.12.10 / python-docx 1.2.0）；`python eval/runner.py out reference/out` → `ok=true`、68/68 checks 全 pass、**字段填充一致率 100.0%（66/66，阈值 90%）**、exit 0；绿自检（`runner reference/out reference/out`）exit 0；红检（空目录）exit 1；D1 双跑复验：fields.json 除 outputs 路径外逐字节一致、文书.docx zip 17 条目解压内容 CRC 全等；8 单元新生成产物与 `reference/out` 参照的 fields.json 除 outputs 外逐字段相等。

## 三、局限（诚实声明）

- **合成数据**：盲评任务与黄金集均为合成数据（按典型办公场景构造的数据 JSON 与边界 case，见 `reference/inputs/`），未用真实用户文书；绝对分值不可外推到真实分布，仅说明技能规则在该任务族上的边际贡献。
- 5 任务样本量小，Δ +1.20 幅度中等且含一个两臂同分任务（ab4）；结论取任务级方向一致性（5/5 majority、0 反向）而非单任务分值。
- 裁判为 LLM（盲评），绝对分值可能有偏，但同一裁判同一标准下的组内比较有效。
- 评测在单一环境执行（Windows x64 / Python 3.12.10 / python-docx 1.2.0，与 spec.md 附录 A 一致），跨平台（字体声明渲染、路径分隔符）未验证。
- 盲评逐任务原始评语存开发方评测管线，未随包分发；本报告仅引用其聚合数字。

## 四、复现

```bash
# 在分发包根目录（确定性评测，应 exit 0；runner 必须显式传两参数，见 README 运行目录约定）
for t in 周报 请示函 会议通知 工作总结; do
  for c in case1 case2; do
    python scripts/gen_doc.py --template $t --data reference/inputs/$t/$c.json --outdir out/$t/$c
  done
done
python eval/runner.py out reference/out

# 红绿自校验
python eval/runner.py reference/out reference/out   # 绿：应 exit 0
python eval/runner.py <空目录> reference/out        # 红：应 units_found 失败、exit 1
```

盲评协议（双臂任务指令、rubric、裁判口径）见 `eval/golden.json` 的 `ab_tasks`（5 条）；盲评聚合原始数据见开发方评测存档（未随包分发；含 tasks/baselineMean/treatmentMean/delta/winRate/reverseTasks/accepted 及逐任务 taskAggs）。
