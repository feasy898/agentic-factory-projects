# hot-templates-skill 评测报告

> 结论先行：同一模型在加载本技能后，四平台爆款骨架生成任务 v0.2 双臂双重复盲评（5 任务）得分从 **3.9 → 10.0（Δ +6.10，任务级胜率 100%，反向任务 0）**，判定**达标**（accepted=true）；确定性评测**第 2 轮通过**。评测脚本随包附带，本报告的确定性部分任何人可按「四、复现」复跑验证；盲评聚合原始数据见开发方评测存档（未随包分发）。

## 一、评测方法

两层评测；盲评在本技能的开发管线中执行（评测管线未随包分发；确定性部分可按「四、复现」用随包脚本复跑）：

**第 1 层：确定性评测（机器判定，无随机、无网络）**

`eval/runner.py` 对 8 个官方样例单元（dy/xhs/wx/video × case1/case2）各执行 5 项检查：产物齐全可解析 / structure.json 三层键与计数自洽 / 平台冻结模板齐备与卖点规整 / 样例数据全部落位且无 `{{ }}` 残留 / 与参照产物结构一致率 ≥90%。任一失败 exit 1。红绿双向校验成立：`runner reference/out reference/out` 全过为绿、空目录判红（本包发包时实测，见 §2.2）。

**第 2 层：有无技能对照盲评（A/B，EVAL-SPEC v0.2 双臂双重复）**

- 任务集 5 个（`eval/golden.json` 的 `ab_tasks`，随包附带）：ab-001 dy 满 3 条卖点、ab-002 xhs 5 条截断、ab-003 wx 0 条零卖点边界、ab-004 video 1 条缺失槽位、ab-005 确定性+失败路径工程验收；任务指令自含全部生成材料。每任务每臂 **2 次独立重复**（双臂双重复，共 5×2×2=20 份盲评产物，存档按 `arm-{a,b}/rep{1,2}` 落盘）。
- 双臂同模型：基线臂裸做任务；治疗臂先读 `SKILL.md` 及其 references 后按技能方法做同一任务；甲乙匿名落盘、交替呈现，裁判盲评（不知道甲乙哪个来自技能组）。
- 聚合口径：逐任务两重复取 majority 判臂，任务级胜率 = majority 为 treatment 的任务占比；判定按 v0.2 复合验收线（结果表 accepted=true）。

## 二、结果

### 2.1 盲评（v0.2 双臂双重复）

| 轮次 | 任务数 | 基线均分 | 治疗均分 | Δ | 任务级胜率 | 反向任务 | 判定 |
|---|---|---|---|---|---|---|---|
| v0.2 双臂双重复 | 5 | 3.9 | 10.0 | **+6.10** | **100%（5/5）** | 0 | **达标**（accepted=true） |

逐任务两臂均分与 majority（聚合字段 `taskAggs`）：

| 任务 | 基线均分 | 治疗均分 | majority |
|---|---|---|---|
| ab-001（dy 满 3 条卖点） | 3.0 | 10.0 | treatment |
| ab-002（xhs 5 条截断） | 3.0 | 10.0 | treatment |
| ab-003（wx 0 条零卖点） | 3.0 | 10.0 | treatment |
| ab-004（video 1 条缺失槽位） | 2.0 | 10.0 | treatment |
| ab-005（确定性+失败路径验收） | 8.5 | 10.0 | treatment |

5 个任务 majority 全为 treatment、无一反向。基线臂的典型失分模式：要素 id/顺序与冻结模板不符、emoji 映射与标签数越界、缺卖点时未落 `【占位:价值点N】` 而是自行编造填充（违红线）、`structure.json` 键集与计数不自洽——正是技能用冻结模板与确定性引擎消灭的误差源；ab-005 的确定性/退出码契约裸模型较易答对（8.5），技能优势集中在模板结构类任务（ab-001..004 基线 2–3 分）。

### 2.2 确定性评测（第 2 轮通过）

- **开发管线第 1 轮（r1，失败留档，存档未随包分发）**：8 case 均挂 `structure_consistency_with_reference`（最好 82.9%）——根因是部分模板接口常量（开放槽位 token、要素 name、填充计数语义）文档缺陷，见包内 `CHANGELOG.md` 1.0.1 条目。
- **开发管线第 2 轮（1.0.1 模板常量对齐修复后）**：`python eval/runner.py package/out oracle/out` → exit 0，**40/40 checks 全过，8 例结构一致率均 100%**（CHANGELOG.md 1.0.1 回归记录）。
- **分发包复跑（2026-09-30，发包时实跑，命令见「四、复现」）**：Windows x64 / Python 3.12.10，8 条生成命令全部 exit=0；`python eval/runner.py out reference/out` → `ok=true`、**40/40 checks 全 pass、8 例结构一致率均 100.0%（consistency_min=1.0，阈值 90%）**、exit 0；绿自检（`runner reference/out reference/out`）exit 0（40/40）；红检（空目录）exit 1（40 项全判红，首条「被测用例目录不存在」）；确定性双跑复验：同输入连跑两次 `骨架.md` 与 `structure.json` 均逐字节一致；8 单元新生成产物与 `reference/out` 参照 **16/16 文件逐字节一致**。

## 三、局限（诚实声明）

- **合成数据**：盲评任务与黄金集均为合成数据（按典型自媒体场景构造的主题/卖点组合与边界 case，见 `eval/golden.json` 与 `reference/inputs/`），未用真实用户选题与卖点；绝对分值不可外推到真实分布，仅说明技能规则在该任务族上的边际贡献。
- 5 任务样本量小；治疗臂 5 任务全部满分（10.0）触评分上限，Δ +6.10 同时受基线臂低分（2–3 分）驱动，幅度解释需谨慎；结论取任务级方向一致性（5/5 majority、0 反向）而非单任务分值。
- 裁判为 LLM（盲评），绝对分值可能有偏，但同一裁判同一标准下的组内比较有效。
- 评测在单一环境执行（Windows x64 / Python 3.12.10），跨平台（路径分隔符、控制台编码）未验证；引擎本身无平台相关行为（纯标准库、LF 换行显式指定）。
- 盲评逐任务原始评语与聚合存档（`tasks/baselineMean/treatmentMean/delta/winRate/reverseTasks/accepted` 及逐任务 `taskAggs`）存开发方评测管线，未随包分发；本报告仅引用其聚合数字。

## 四、复现

```bash
# 在分发包根目录（确定性评测，应 exit 0；runner 必须显式传两参数，见 README 运行目录约定）
python scripts/gen.py --platform dy    --topic 时间管理     --points reference/inputs/dy/case1.json    --outdir out/dy/case1
python scripts/gen.py --platform dy    --topic 减脂饮食     --points reference/inputs/dy/case2.json    --outdir out/dy/case2
python scripts/gen.py --platform xhs   --topic Excel函数    --points reference/inputs/xhs/case1.json   --outdir out/xhs/case1
python scripts/gen.py --platform xhs   --topic 租房避坑     --points reference/inputs/xhs/case2.json   --outdir out/xhs/case2
python scripts/gen.py --platform wx    --topic 深度工作     --points reference/inputs/wx/case1.json    --outdir out/wx/case1
python scripts/gen.py --platform wx    --topic 非暴力沟通   --points reference/inputs/wx/case2.json    --outdir out/wx/case2
python scripts/gen.py --platform video --topic 手冲咖啡入门 --points reference/inputs/video/case1.json --outdir out/video/case1
python scripts/gen.py --platform video --topic 城市夜跑装备 --points reference/inputs/video/case2.json --outdir out/video/case2
python eval/runner.py out reference/out

# 红绿自校验
python eval/runner.py reference/out reference/out    # 绿：应 exit 0
python eval/runner.py <空目录> reference/out         # 红：应 artifacts_present 失败、exit 1

# 确定性双跑（同输入两次，两份产物应逐字节一致）
python scripts/gen.py --platform video --topic 任意主题 --points '["甲","乙","丙"]' --outdir <目录1>
python scripts/gen.py --platform video --topic 任意主题 --points '["甲","乙","丙"]' --outdir <目录2>
```

盲评协议（双臂任务指令、rubric、裁判口径）见 `eval/golden.json` 的 `ab_tasks`（5 条，随包附带）；盲评聚合原始数据见开发方评测存档（未随包分发；含 tasks/baselineMean/treatmentMean/delta/winRate/reverseTasks/accepted 及逐任务 taskAggs）。
