# recommend 模块规格（冻结契约·定稿）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> 本定稿根据对抗评审意见修订（相对 specs/drafts/recommend.spec.md）：
> ① §3.3 明确「limit 校验先于池访问」——空池容忍只在校验通过后适用，冻结
> `recommend_for_kp('ghost', …, limit=0)` 抛 `RecommendError`；
> ② §3.5 明确 attach 的 limit 校验时机为**入口无条件校验**（先于步骤遍历、先于
> `plan.steps` 属性访问），空 steps 计划配非法 limit 同样抛错；
> ③ 冻结 `mastery_threshold` 的**校验谓词精确形式** `not (0 < t < 1)`：NaN 抛
> `RecommendError`、非数值类型抛原生 `TypeError` 不包装，并收窄 §6「异常类型一律
> RecommendError」的适用范围；
> ④ 更正 §3.2：`Recommendation` 是公开可关键字构造的 dataclass，契约测试**确有**
> 手工构造（test_profile_purity:157），删除「不手工构造」的错误承诺；
> ⑤ 重写 §6 limit 错误行并声明 §3.3 为准：str/float/bool/＜1 一律抛 `RecommendError`；
> ⑥ I11 改写为本模块可检验义务（复用共享 `xuexing.types.PlanStep`、禁止影子复制），
> 并注明 `test_planstep_field_default` 由共享 types 承载、非 recommend 实现者可影响。
> 另更正 I7 的测试名引用（`test_attach_fills_steps_without_mutating_input`）。
> 与契约测试一致的部分原样保留。

**证据标记**：
- 【契约】= `tests/contract/test_recommend_contract.py` 明确断言的行为（行为 ground truth）；
- 【参考】= 参考实现 `src/xuexing/recommend.py` 中可读出、且起草/评审时实际运行复核过的行为（API 发现）。
- **优先级规则**：两者冲突时以【契约】为准——但"冲突"仅在**契约测试可构造、可观察的输入**上有定义；
  对契约测试无法产生的输入类（如空池 × 非法 limit、非数值 threshold、空 steps 计划 × 非法 limit），
  按【参考】冻结为权威行为，并在相应条款注明"测试未覆盖"。

## 1. 目的

recommend 是**「知识点掌握 -> 母题推荐」引擎**：从题库为主知识点挑针对性练习题，
并把推荐挂到学习计划的步骤上（`PlanStep.recommended_item_ids`）。触发输入是
**掌握度**（Profile）而非原始作答——掌握度低于阈值的知识点视为薄弱点，为其产出
一份有序练习题 id 列表；`attach_recommendations` 再把列表逐项挂到 route 产出的
`LearningPlan.steps` 上。

选题规则（冻结）——**误解标签优先**：

- **Tier 1（误解针对性）**：主知识点等于目标知识点、且带有"误解库中绑定到该知识点
  的误解标签"的题（`item.misconceptions ∩ M ≠ ∅`，`M` 见 §3.3）；
- **Tier 2（一般巩固）**：池内其余主知识点题；
- 每层内按 `(difficulty, id)` 升序，输出 = Tier 1 在前 + Tier 2 在后。

本模块是**纯规划**：不判分、不更新掌握度、不做拓扑排序、不出卷、不持久化。

## 2. 允许的依赖

- Python 标准库（至少 `dataclasses`）
- `xuexing.types`（绝对导入：`from xuexing.types import LearningPlan, PlanStep, Profile`；
  `ReviewEntry` 允许 import 但本模块仅浅拷贝容器、不构造新条目）
- 禁止：其他 xuexing 模块（**无例外**——不 import route/itembank/kpgraph/diagnosis），
  第三方库，文件/网络 IO，`random`，系统时钟，环境读取

鸭子类型参数表面（禁止 import 其所在模块）：

- `bank`: `by_kp(kp_id, primary_only=True) -> list[Item]`（仅此一个方法；Item 需有
  `id`、`difficulty`、`misconceptions` 字段）
- `misconceptions`: 元素需有 `.id` 与 `.kp_id`（均为 str；`xuexing.types.Misconception`
  即满足）
- `plan`: `LearningPlan` 形状（`learner_id` / `steps` / `reviews` / `created_at`）

重生成实例的装载约束（注入机制实测：tests/conftest.py:24-34 以 `spec_from_file_location`
把 `<impl_dir>/recommend.py` 装载为顶层模块名 `_regen_recommend` 并顶替
`sys.modules["xuexing.recommend"]`；注入清单 MODULES（tests/conftest.py:18）**不含
`types`**——`xuexing.types` 恒为参考包模块，重生成实现共享它）：

- 禁止相对导入（顶层装载下无包上下文）；
- 不使用 `from __future__ import annotations`——dataclass 字符串注解在
  `_regen_recommend` 顶层模块名下会触发未受保护的 `sys.modules` 解析；注解直接写真实对象；
- 单文件，且必须暴露本模块全部公开 API（§3）。

## 3. 公开 API

模块必须暴露以下 5 个名字（契约测试
`from xuexing.recommend import RecommendError, Recommendation, attach_recommendations, recommend_for_kp, recommend_for_profile`，
test_recommend_contract.py:14-20）。

### 3.1 `RecommendError`

`RecommendError(ValueError)`——本模块唯一异常类型，所有校验失败抛它。
【契约】test_validation_errors:176（`issubclass(RecommendError, ValueError)`）；
【参考】recommend.py:28-29。

### 3.2 `Recommendation`

```python
@dataclass
class Recommendation:
    kp_id: str          # 薄弱知识点 id
    item_ids: list[str] # 有序推荐题 id（可为空列表）
```

`Recommendation` 是**公开可构造的 dataclass**：`Recommendation(kp_id=…, item_ids=…)`
以这两个字段名关键字（或位置）构造即可成功，字段形状与上式一致，**逐字段相等**
（`a == b`）是确定性判定方式。【契约】test_profile_purity:157 **手工构造**
`Recommendation(kp_id="junk", item_ids=[])` 并把结果 append 进输出列表——实现不得把
构造收窄为模块私有；test_weakest_first_tie_by_kp_id:149 断言输出元素
`isinstance(r, Recommendation)`；【参考】recommend.py:32-37（dataclass，两字段）。
产出侧的唯一来源仍是 `recommend_for_profile`（每弱 kp 恰一个，§3.4）。

### 3.3 `recommend_for_kp`

```python
def recommend_for_kp(kp_id, bank, misconceptions=None, limit=None) -> list[str]
```

- **校验先于任何计算**：`limit` 校验在**函数入口**完成，先于误解库消费、先于
  `bank.by_kp` 调用。【参考】recommend.py:73（`_validated_limit` 为函数体第一条语句）；
  运行复核：bank 缺 `by_kp` 且 `limit=0` 时抛 `RecommendError`（而非 AttributeError）。
  因此**空池容忍只在校验通过后适用**——冻结行为：`recommend_for_kp('ghost', bank, mcs,
  limit=0)` 抛 `RecommendError`，不返回 `[]`（测试未覆盖该组合：test_unknown_kp_empty:106-108
  只用合法/None limit，test_validation_errors:168-170 只用非空池 'a'；两种读法均能通过
  全部契约测试，按参考冻结，**§3.3 为准**）。
- `M = {mc.id for mc in misconceptions if mc.kp_id == kp_id}`；`misconceptions=None`
  或空可迭代 → `M = ∅`；重复 id 容忍（集合语义）；**误解库输入顺序无关**。
- 池 = `bank.by_kp(kp_id, primary_only=True)`；目标 kp 只是次要知识点的题**永不入选**。
- Tier 1 = 池内 `set(item.misconceptions) ∩ M ≠ ∅` 者；Tier 2 = 池内其余
  （含带标签但标签均不属于 `M` 的题，以及不带任何标签的题）。
- 每层内 `(difficulty, id)` 升序；输出 = Tier1 + Tier2 的 `item.id` 列表。
  这是**唯一排序来源**——不依赖 `by_kp` 的返回序。
- 池为空（含未知 kp）→ `[]`（容忍，不抛错；前提是上一条的 limit 校验已通过）。
- `limit`：`None` → 不截断；否则必须是 **int 且非 bool 且 ≥ 1**，违反抛
  `RecommendError`——**str、float、bool、NaN 等一切非 int 类型与 ＜1 的 int 都抛**，
  无例外（§6 错误表以此行措辞为准）。运行复核：`limit='3'`、`2.5`、`True`、`0`、`-1`、
  `float('nan')` 均抛 `RecommendError`。【契约】test_validation_errors:168-172
  （0/-1/True/'3'/2.5 各抛）；【参考】recommend.py:42-50。
- `limit` 超过池长 → 全量返回（容忍）。截断是**前缀截断**（保留排序头部）。
- 返回**新列表**：改动返回值不影响 bank、不泄漏进后续调用。

### 3.4 `recommend_for_profile`

```python
def recommend_for_profile(profile, bank, misconceptions=None,
                          mastery_threshold=0.65, limit=None) -> list[Recommendation]
```

- **校验先于任何计算**：`mastery_threshold` 的校验谓词**精确为**
  `not (0 < mastery_threshold < 1)`，为真即抛 `RecommendError`。由此：
  - `t ∈ {0, 1, 1.5, -0.1}`（含一切区间外数值）→ 抛 `RecommendError`
    【契约】test_validation_errors:164-167；
  - `t = float('nan')`：与 NaN 的两处比较皆为 False，谓词为真 → **抛
    `RecommendError`**（运行复核；测试未覆盖，按参考冻结——实现若写成
    `t <= 0 or t >= 1` 会让 NaN 漏检并在比较 mastery 时返回空列表，**不合规**）；
  - `t = True`：`0 < True` 成立但 `True < 1` 不成立，谓词为真 → 抛
    `RecommendError`（运行复核）；
  - `t` 为**非数值类型**（如 `'0.5'`）：比较运算抛原生 `TypeError`，
    **原样透传、不包装**为 `RecommendError`（运行复核
    `'<' not supported between instances of 'int' and 'str'`；测试未覆盖，按参考冻结）。
  - **先查 threshold、后查 limit**（两参同错时异常归因 threshold）
    【契约】test_validation_errors:174-175。【参考】recommend.py:98-100。
- 弱点集 = `{kp : profile.mastery[kp] < mastery_threshold}`（**恰等于阈值视为达标**，
  不推荐）；不做图过滤——`profile.mastery` 的全部键都是候选（图无关）。
- 输出：每个弱 kp **恰一个** `Recommendation`（kp_id 互异、无遗漏），按
  `(mastery 升序, kp_id 升序)` 排列（**最弱优先**）；每项 `item_ids` 逐个等于
  `recommend_for_kp(kp, bank, misconceptions, limit)`（校验后的 limit，语义含 §3.3
  全部条款——含"校验先于池访问"，故弱 kp 的池为空**不会**豁免入口已通过的 limit）。
  池空的 kp 产出 `Recommendation(kp, [])`（诚实暴露缺口，不静默丢弃）。
  【契约】test_weak_only_and_threshold_boundary:134-141（ghost → ("ghost", [])）、
  test_weakest_first_tie_by_kp_id:144-149；【参考】recommend.py:101-110。

### 3.5 `attach_recommendations`

```python
def attach_recommendations(plan, bank, misconceptions=None, limit=None) -> LearningPlan
```

- **校验先于任何计算**：`limit` 校验在 **attach 入口无条件执行**，先于步骤遍历、
  也先于 `plan.steps` 属性访问。【参考】recommend.py:122（`_validated_limit` 为函数体
  第一条语句）；运行复核：空 steps 计划配 `limit=0` 抛 `RecommendError`；
  `plan` 连 `steps` 属性都没有时配 `limit=0` 仍抛 `RecommendError`（而非
  AttributeError）。因此"计划无步骤"**不豁免** limit 校验（测试未覆盖空 steps 场景：
  test_attach_limit_passthrough_and_duplicate_kp:209-214 只用两步计划；两种读法均能通过
  全部契约测试，按参考冻结）。
- 返回**新** `LearningPlan`：`learner_id`、`created_at` 原样保留；`steps` 是新列表，
  逐项新建 `PlanStep`——原四字段（`kp_id`/`strategy_id`/`rationale`/`target_mastery`）
  复制原值，`recommended_item_ids = recommend_for_kp(step.kp_id, bank, misconceptions, limit)`；
  `reviews` 是**新列表**、条目对象复用原对象（ReviewEntry 按值对象对待，不做深拷贝）。
  【契约】test_attach_fills_steps_without_mutating_input:181-189、
  test_attach_preserves_fields:192-206；【参考】recommend.py:123-139。
- **输入 plan 不被修改**：调用后原 plan 各步骤的 `recommended_item_ids` 仍为构造时的值
  （route 产出即为 `[]`），原 `steps`/`reviews` 列表不被别名共享。
- `plan` 本身不做校验：limit 合法而 plan 缺字段/缺方法（鸭子失配）时原生异常传播，
  不包装。【参考】recommend.py:123-133 + 运行复核（`Bare()` + `limit=None` →
  AttributeError）。
- 重复 kp 的多个步骤容忍：各自独立计算、结果一致。【契约】
  test_attach_limit_passthrough_and_duplicate_kp:210-212（两步 'a' 配 limit=1 各得
  `["a_t2"]`）。

## 4. 不变量（编号列出，全部可被契约测试检验或按参考冻结）

- I1 **确定性 + 误解库顺序无关**：同入参两次调用输出逐项相等；`misconceptions`
  以任意元素顺序（含反转）给出，输出逐位相等
  （`test_tier_order_and_misconception_order_independence:83-89`）。
- I2 **误解标签优先**：`M` 非空且 Tier 1 非空时，输出头部恰为全部 Tier 1 id，
  其后才是 Tier 2；带"他知识点误解标签"的题归 Tier 2——实测合同夹具
  `a_x`（difficulty 0.05，标 `mc_b1`）排在 `a_t2`/`a_t1` 之后
  （`test_tier_order_and_misconception_order_independence:84-85`、
  `test_foreign_tag_is_general:92-96`）。
- I3 **排序条款**：层内 `(difficulty, id)` 升序，插入序无关——夹具以乱序难度注册
  （mc_bank 夹具 test_recommend_contract.py:34-54；闭式序列断言于
  `test_tier_order_and_misconception_order_independence:84`、
  `test_empty_misconception_library_all_general:111-114`）。
- I4 **主知识点约束**：输出 id 全部来自 `by_kp(kp, primary_only=True)`；仅作次要
  知识点的题永不出现（`test_secondary_kp_never_recommended:99-103`）。
- I5 **分划完整性 + 前缀截断**：无 limit 时输出 = Tier1 ∪ Tier2、无重复、恰为池的
  全体 id；有 limit 时输出 = 全量输出的前 `limit` 项，`limit` 超池长全量返回
  （`test_limit_semantics:117-122`）。
- I6 **阈值语义**：恰等于阈值不推荐；输出 Recommendation 数 = 弱 kp 数、kp 唯一、
  最弱优先、平局 kp_id 升序；图外键照常产出（可为空 ids）
  （`test_weak_only_and_threshold_boundary:134-141`、
  `test_weakest_first_tie_by_kp_id:144-149`）。
- I7 **纯函数**：不修改入参（profile.mastery、misconceptions、plan 均不变）；
  `recommend_for_kp` 返回新列表（`test_output_independence:125-129`、
  `test_attach_fills_steps_without_mutating_input:188-189`、
  `test_profile_purity:152-158`）。
- I8 **挂载语义**：attach 后每步 `recommended_item_ids == recommend_for_kp(该步 kp)`；
  原四字段与 reviews 逐字段/逐项不变；原 plan 步骤保持 `[]`；输出容器均为新列表
  （`test_attach_fills_steps_without_mutating_input:181-189`、
  `test_attach_preserves_fields:192-206`）。
- I9 **可组装性（route 编排闭环）**：真实 grade7 题库 + math_misconceptions.json，
  `diagnose -> build_plan -> attach` 后 kp_rational_add 步骤的
  `recommended_item_ids == ["m7_010", "m7_011", "m7_012", "m7_115"]`（前两项为
  mc_sign_neg 针对题，均 difficulty 0.2、id 升序破缺）
  （`test_composable_with_route_plan:219-238`）。
- I10 **校验完备性与时机**：
  `mastery_threshold ∉ (0,1)`（0/1/1.5/负数）与 `limit` 非法（0/负/bool/str/float）
  各抛 `RecommendError` 且其为 `ValueError` 子类；threshold 与 limit 同错先报
  threshold（类型断言，不依赖消息文本）；threshold 校验先于 limit（§3.4）、limit
  校验先于池/步骤访问（§3.3/§3.5）；NaN threshold 抛 `RecommendError`、非数值
  threshold 抛原生 `TypeError` 不包装（后两者测试未覆盖，按参考冻结）
  （`test_validation_errors:163-176` + 运行复核）。
- I11 **共享 `xuexing.types.PlanStep` 复用（本模块义务）**：本模块**从
  `xuexing.types` import `PlanStep` 并用其构造** `attach_recommendations` 输出的每个
  步骤——禁止在 recommend 内影子复制/重新定义 PlanStep 形状。**权属说明**：
  `test_planstep_field_default:243-252` 考察的是共享 `xuexing.types.PlanStep`
  （测试直接 `from xuexing.types import`，test_recommend_contract.py:25；注入清单
  MODULES 不含 types，tests/conftest.py:18），该测试恒打在参考包 types 上，
  **recommend 的重生成实现既无法也无需影响它**——其通过与否由 types 自身保证
  （`recommended_item_ids` 缺省 `[]`、缺省与显式 `[]` 构造相等、`to_dict` 含键、
  字段全集恰为五者，均已运行时实测满足）。本模块的可检验义务仅为：输出步骤是
  共享 `PlanStep` 实例且带五字段值（I8），不重复定义、不绕开 types。
  【契约】test_attach_preserves_fields:197-199；【参考】recommend.py:17, 123-133。

## 5. 确定性与随机性

- 三个入口均为纯函数：输出只依赖入参值；禁止 `random`、hash 序、系统时钟、环境
  读取、任何 IO。
- 唯一排序来源：题目 `(difficulty, id)` 升序、弱点 `(mastery, kp_id)` 升序；并列
  用精确 float 相等 + id 码点序破缺；`M` 与标签交用集合语义（顺序无关）。
- §3.3/§3.4/§4-I9 的闭式序列都是逐位比对点（CPython 3.12 x64 实测；
  `python -m pytest tests/contract/test_recommend_contract.py` 16 passed，2026-09-29 复核）。

## 6. 错误行为

| 非法输入 / 情形 | 行为 | 证据 |
|---|---|---|
| `mastery_threshold ∉ 开区间 (0,1)`（0、1、1.5、-0.1） | 抛 `RecommendError`（先于 limit 校验） | 【契约:164-167, 174-175 + 参考 recommend.py:98-100】 |
| `mastery_threshold = NaN` | 抛 `RecommendError`（谓词 `not (0<t<1)` 对 NaN 为真；测试未覆盖，按参考冻结） | 【参考 recommend.py:98 + 运行复核】 |
| `mastery_threshold` 为非数值类型（str 等） | 原生 `TypeError` **原样透传、不包装**（测试未覆盖，按参考冻结） | 【参考 recommend.py:98 + 运行复核】 |
| `limit` 非 None 且：非 int（**含 str、float、NaN**）或 bool 或 **＜1** | 抛 `RecommendError`（以 §3.3 措辞为准；0/-1/True/'3'/2.5 为契约断言） | 【契约:168-172 + 参考 recommend.py:42-50 + 运行复核】 |
| 两参（threshold、limit）同错 | 先报 `mastery_threshold` | 【契约:174-175 + 参考 recommend.py:98-100 代码序】 |
| 校验已通过，目标 kp 无主知识点题（含未知 kp） | 容忍：`[]` / `Recommendation(kp, [])`。注意：**非法 limit 不因池空豁免**——`recommend_for_kp('ghost', …, limit=0)` 抛 `RecommendError`（测试未覆盖，按参考冻结） | 【契约:106-108 + 参考 recommend.py:73, 77 + 运行复核】 |
| 校验已通过，`plan.steps` 为空 | 容忍：返回 steps 为空列表的新 LearningPlan。**非法 limit 不因无步骤豁免**（测试未覆盖，按参考冻结） | 【参考 recommend.py:122 + 运行复核】 |
| `misconceptions` 为 None / 空 / 含重复 id | 容忍：`M` 为空或去重 | 【契约:89, 111-114 + 参考 recommend.py:53-57】 |
| `bank` 无 `by_kp`、`plan` 缺字段、误解条目缺 `id`/`kp_id` | 原生异常传播，不包装 | 【参考 recommend.py:77, 123-133, 53-57】 |
| `limit` 大于池长 | 容忍：全量返回 | 【契约:122 + 参考 recommend.py:84-85】 |

原则：**领域校验错误**一律 `RecommendError`（`ValueError` 子类，§3.1）——具体仅指
§3.3/§3.4/§3.5 中 limit 与 mastery_threshold 的显式校验；契约内输入不抛
`RecommendError` 以外的异常。**范围限定**：非数值 `mastery_threshold` 引发的
`TypeError` 与鸭子失配（bank 缺方法、plan 缺字段、误解条目缺属性）的原生异常**不在
包装范围内**，原样透传。

## 7. 非目标

- **不做误解归因**：不比对作答与 `Misconception.signature`、不产出"学习者犯了哪个
  误解"的结论；推荐是掌握度驱动的题集排序，误解诊断属后续迭代。
- **不链接母题库（archetypes）**：题库 items 现无指向 archetype 的字段，母题库
  （52 模式）与题目的绑定属数据侧工程（P1）；本模块的"母题推荐"落地为**按误解
  标签挑针对性题**（BACKLOG 条目原文），archetype 接入不做。
- **不做拓扑/先序处理**：弱点的学习顺序、先序门控是 route 的职责；本模块不收
  graph 参数，`attach_recommendations` 只消费现成计划。
- **不更新掌握度、不判分**：diagnosis / grading 的职责。
- **不选题组卷、不感知会话切分**：paper 负责蓝图选题与抽题；`session_size` 不进入
  本模块签名。
- **不持久化、不做多学习者**：一次调用产出一份结果。
