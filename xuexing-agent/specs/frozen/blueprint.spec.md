# blueprint 模块规格（已冻结）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
> 冻结基线：`src/xuexing/blueprint.py` + `tests/contract/test_blueprint_contract.py`
> （18 项，2026-09-29 于 CPython 3.12.10 x64 全绿实测）。行为 ground truth 是契约测试；
> 本文数值例子均为实测值，位级可复现。

## 1. 目的

blueprint 是**诊断卷蓝图生成器**（组卷的前置规划器）：输入目标知识点集合、预算题数与
认知维度配比（记忆/理解/应用——TIMSS 2019 数学框架"内容域 × 认知域"二维矩阵中认知域
一侧的本土化记法；官方 8 年级 knowing/applying/reasoning ≈ 40/40/20，冻结为缺省配比），
输出一份 `Blueprint` 规划：每个目标知识点各出几道题（`counts()` 产出可直接传给
paper.generate_paper 的 `blueprint: dict[str, int]`）、每个认知维度合计几道题、以及
(知识点 × 维度) 细目。行为契约：**认知维度配比约束**（各维度合计恰好落在最大余数法
容许集合 {floor(q), floor(q)+1} 内，q 为该维度配额）、**覆盖约束**（预算足够时每个
目标知识点 ≥1 题，预算不足则拒绝）、**同输入同输出**（含输入顺序无关）。

本模块是**纯规划**：不查题库、不选题、不看难度——选题与库存满足性是 paper 的职责。

## 2. 允许的依赖与装载约束

- Python 标准库（至少 `dataclasses`、`math`）
- `xuexing.types` 允许绝对导入，但**本模块未使用任何共享类型**（Blueprint 是本模块
  私有数据类；graph 按鸭子类型消费）——实现可以不 import types
- 禁止：其他 xuexing 模块（**无例外**——不 import paper/kpgraph；graph 用鸭子类型）、
  第三方库、文件/网络 IO、`random`、系统时钟、环境读取

鸭子类型参数表面（禁止 import 其所在模块）：

- `graph`: `has(kp_id) -> bool`（仅此一个方法；用于目标知识点存在性校验）

重生成实例的装载约束（实测于测试注入器：实现文件以
`spec_from_file_location("_regen_blueprint", <impl_dir>/blueprint.py)` 顶层装载）：
禁止相对导入（装载为顶层模块名 `_regen_blueprint`）；不使用
`from __future__ import annotations`；注解直接写真实对象。

## 3. 公开 API

模块必须暴露以下 6 个名字（契约测试
`from xuexing.blueprint import Blueprint, BlueprintError, DEFAULT_RATIOS, DIFFICULTY_TARGET, DIMENSIONS, build_blueprint`）。

### 3.1 常量（冻结值）

```python
DIMENSIONS = ("记忆", "理解", "应用")          # 规范维度序（一切并列破缺与输出序的基准）
DEFAULT_RATIOS = {"记忆": 0.4, "理解": 0.4, "应用": 0.2}   # TIMSS 8 年级 40/40/20
DIFFICULTY_TARGET = {"记忆": 0.2, "理解": 0.5, "应用": 0.8}  # 维度 -> generate_paper 难度目标
```

### 3.2 `Blueprint`

```python
@dataclass
class Blueprint:
    targets: list[str]                    # 排序去重后的目标知识点 id（升序）
    budget: int                           # 预算题数 N
    ratios: dict[str, float]              # 生效配比：按规范维度序、仅含正配比维度、已归一化
    allocation: dict[str, dict[str, int]] # kp -> {维度: n}；仅含正数格；内层键按规范维度序
    dimension_totals: dict[str, int]      # 维度 -> 合计；仅含正配比维度，值可为 0（§3.6）
```

- 字段序固定为 targets, budget, ratios, allocation, dimension_totals；dataclass 逐字段
  相等（`a == b`）是确定性判定方式。
- **键集精确性（双向）**：`ratios` 与 `dimension_totals` 的键集**恰好等于**
  `{d ∈ DIMENSIONS : 生效权重 w_d > 0}`（正配比维度集）——既无零配比键，也不缺
  正配比键。`dimension_totals` 的值可为 0（正配比但分得 0 题，§3.6）；`ratios`
  的值恒 > 0。`allocation` 只含正数格；`counts()` 的键集 == targets。
- **无别名条款**：Blueprint 实例持有的四个容器字段全部是构造期新建的容器，不得与
  入参 targets/ratios、`DEFAULT_RATIOS` 或任何模块级容器共享同一对象。
  特别地 `bp.ratios is DEFAULT_RATIOS` 必须为假（参考实现实测为 False；
  `ratios=None` 时取 DEFAULT_RATIOS 的**复制**）。调用方原地修改 `bp.ratios`
  不得影响 `DEFAULT_RATIOS`，也不得影响任何后续 `build_blueprint` 调用的结果。
- 字段构造只经 `build_blueprint`；契约测试不手工构造 `Blueprint`。
- `counts()`：返回 `{kp: 该 kp 各维度合计}`（键 = targets 升序），**合计恰为 budget**；
  每次调用返回**新 dict**（与 allocation 无别名共享，改动返回值不影响 Blueprint）。
- `per_dimension()`：按规范维度序、**仅合计 ≥ 1 的维度**，返回
  `(维度, {kp: 该维度题数}, DIFFICULTY_TARGET[维度])`；各维度的 sub-dict 恰好划分
  `counts()`（对每个 kp：Σ 各维 sub-dict 的 `get(kp, 0)` == 该 kp 总数）。
  sub-dict 是新 dict。合计为 0 的维度不出现（避免向 generate_paper 传空蓝图触发
  其空蓝图拒绝）。

### 3.3 `build_blueprint` —— 校验（先于任何计算，顺序为绑定条款）

```python
def build_blueprint(targets, budget, graph, ratios=None) -> Blueprint
```

按 V1 → V2 → V3 → V4 顺序执行，任何一条失败抛 `BlueprintError`。契约测试逐类
断言抛错，不依赖消息文本——**异常类型才是契约**。

- **V1 targets**：
  1. 裸 `str`（含 str 子类）→ 拒绝（字符串按字符迭代是调用方错误；本检查先于一切
     可迭代判定）。
  2. **不可迭代对象 → 拒绝**：物化为 list 失败（迭代触发 `TypeError`，如 `None`、
     `42`）即拒绝，抛 `BlueprintError`（契约测试明确要求 None 与 42 抛
     BlueprintError，而非 TypeError）。
  3. **其余一切可迭代对象接受**：list / tuple / set / dict（按键迭代）/ 生成器 /
     dict_keys 等视图均合法（参考实现实测全部接受）。规格不限制容器种类，只约束
     迭代所得元素。对一次性迭代器，物化即消费属迭代语义，不另作承诺。
  4. 逐元素校验：每个元素必须是**非空 str 实例**；**元素校验先于去重**（因此
     `["a", ["b"]]` 这类不可哈希元素抛 BlueprintError，而不是去重阶段的 TypeError）。
  5. 去重（重复元素容忍、静默合并）并按 Python `sorted`（码点序）升序排列；
     结果为空（如空容器）→ 拒绝。
- **V2 budget**：必须是 `int` 实例且非 `bool`（`4.0`、`True`、`"5"`、`None` 均拒绝）；
  `budget < len(去重后 targets)` 拒绝（覆盖不可能，见 I4；含 budget ≤ 0。
  重复元素按去重后数目计，实测 5 元素含重复、去重后 K=4、budget=4 可接受）。
- **V3 ratios**：
  1. `None` → 取 `DEFAULT_RATIOS` 的**复制**（新建 dict；禁止别名，见 §3.2）。
  2. 非 dict → 拒绝（如 list of pairs）。
  3. 键必须是 `DIMENSIONS` 的子集（未知维度名拒绝）；缺省键视为 0。
  4. 值必须是 int/float 实例（bool 拒绝，数字字符串等非数字类型拒绝），float 化后
     必须有限（NaN/inf 拒绝）且 ≥ 0（`-0.0` 视为 0：合法但非正配比维度）。
  5. Σw ≤ 0 → 拒绝（全部为 0 或空 dict）。
- **V4 图存在性**：每个去重目标 `graph.has(kp)` 为假则拒绝。

### 3.4 计算（顺序为绑定条款，浮点为位级条款）

记生效维度集 P = {d ∈ DIMENSIONS : t_d > 0}，其中 t_d = float(V3 校验后的 w_d，
缺省键为 0.0）。

- **P0 归一化（Σw 的冻结求和语义）**：
  `Σw = fsum(t_记忆, t_理解, t_应用)`——即全部 t_d 的**精确数学和经 IEEE 754 双精度
  正确舍入**（`math.fsum` 语义）。该定义**与迭代序、结合序无关**：按输入 dict
  插入序、按规范维度序、或任何排列求和必须得到同一逐位结果。
  **禁止以朴素逐项 `+` 折叠替代**——实测（CPython 3.12.10 x64）朴素折叠依赖结合序：
  `(0.1+0.2)+0.3 = 0.6000000000000001`，`(0.3+0.2)+0.1 = 0.6`，而 fsum = 0.6；朴素折叠
  与 fsum 语义在一般权重下产出不同的 `bp.ratios` 位型（随机权重实测约 17% 输入
  `w_d/Σw` 位级不同）。
  生效权重 `w'_d = t_d / Σw`（仅 d ∈ P；键按 DIMENSIONS 序）。
  注：契约语料内所有权重和均精确（DEFAULT_RATIOS 任意结合序 = 1.0；{0.6,0.4}、
  {0.999,0.001} 均 = 1.0；整数权重精确），故 18 项契约测试对本条款的选择不敏感；
  本条款仍为绑定条款，用语料外位级一致性。
- **C1 维度配额**：`Σ' = fsum(w'_d, d ∈ P)`（同 P0 语义，序无关）；
  配额 `q_d = (budget * w'_d) / Σ'`（按书写序：先乘后除，IEEE 双精度）；
  各维度合计 `T_d` 按**最大余数法**分配：`T_d = floor(q_d)`，再把剩余
  `R = budget − Σ T_d` 个逐个给余数 `r_d = q_d − T_d` 最大者，
  **余数并列（精确 float 相等）时按 DIMENSIONS 序取最前**（实测：N=12 缺省配比 →
  q=(4.800000000000001, 4.800000000000001, 2.4000000000000004)，floor=(4,4,2)，
  余 2 给 记/理 → T=(5,5,2)；等权 {1,1,1}、N=5 → 三者余数逐位相同 → T=(2,2,1)）。
- **C2 维度内均分**：每个维度把 `T_d` 均分给 K 个目标：`base = T_d // K`，
  按目标 id 升序的前 `T_d mod K` 个各 +1。
- **C3 覆盖修复**：只要存在合计为 0 的知识点（每轮取 id 升序最前的零额者）：
  从"合计最大者（并列取 id 最小）"处移 1 题给零额知识点，移出维度 = 捐出者内部
  计数最大的维度（并列按 DIMENSIONS 序取最前者）。**移动发生在同一维度内**——
  C1 的维度合计不变。可行性（预算 ≥ K 时必然成立）：若某 kp 为 0，则非零 kp ≤ K−1
  个却持有 N ≥ K 题，由抽屉原理必有 kp 合计 ≥ 2 可作捐出者。
- **C4 组装**：`allocation` 只保留正数格（外层键 = targets 升序，内层键按
  DIMENSIONS 序）；`ratios` = 生效权重 w'（键集 = P，键序 = DIMENSIONS 序）；
  `dimension_totals` = {d: T_d : d ∈ P}（键集 = P，值可为 0）；`targets` =
  去重升序 list。全部容器为新建（§3.2 无别名条款）。

### 3.5 闭式例子（targets={a,b,c,d}，graph 含这 4 点；全部实测、位级比对点）

| 输入 | 实测输出 |
|---|---|
| N=10，缺省配比 | T=(记4,理4,应2)（q 恰为整数 4.0/4.0/2.0）；counts: a=3, b=3, c=2, d=2；allocation: a={记1,理1,应1}, b={记1,理1,应1}, c={记1,理1}, d={记1,理1} |
| N=12，缺省配比 | T=(5,5,2)；counts: a=5, b=3, c=2, d=2 |
| N=4，缺省配比 | T=(2,1,1)；经 C3 两次修复后 counts 全为 1：a={应1}, b={记1}, c={记1}, d={理1} |
| N=6，缺省配比 | T=(3,2,1)；经 C3 一次修复：a={理1,应1}, b={记1,理1}, c={记1}, d={记1}（counts: 2,2,1,1） |
| N=5，ratios={记:1,理:1,应:1} | T=(2,2,1)（C1 三方余数并列→规范序）；经 C3 两次修复：a={应1}, b={记1,理1}, c={记1}, d={理1}；ratios 三键均 = 1/3 |
| N=2，K=2，ratios={理:0.999,应:0.001} | T=(理2,应0)（正配比维度允许合计 0）；counts: a=1, b=1，全部在 理解；per_dimension() == [("理解", {a:1, b:1}, 0.5)] |
| N=7，K=4，ratios={理:0.6,应:0.4} | T=(理4,应3)；counts: a=2, b=2, c=2, d=1；全程无 记忆；ratios/dimension_totals 键集均为 {理解, 应用} |
| K=1，N=5，缺省配比 | 一切题归该点：counts={a:5}，T=(2,2,1)，allocation={a:{记2,理2,应1}} |

### 3.6 边界语义

- **正配比维度合计为 0**：极小配比（如 0.001）经 C1 可能拿不到题；`dimension_totals`
  保留该键、值为 0（诚实反映请求），`allocation`/`per_dimension`/`counts` 中不出现。
  零**配比**（w_d = 0）维度则从一切输出中省略（§3.2 键集精确性）。
- **单知识点**：K=1 时一切题归它，维度配比仍按 C1（test_single_kp）。
- **budget == K**：覆盖修复后每个目标恰 1 题（实测 N=4/K=4 例）。

## 4. 不变量（编号列出；与契约测试 18 项逐一对应，无未引用测试、无虚构测试名）

- I1 **确定性与输入顺序无关**：同一 (目标集合, budget, ratios) 产出一一相等的
  Blueprint——targets 以 set/list/tuple（含重复元素）任给、ratios 以任意键序的 dict
  给定，输出 dataclass 相等；缺省配比与显式 {0.4,0.4,0.2} 等价；`list(bp.ratios)`
  恒为规范维度序（`test_determinism_and_order_independence`）。
- I2 **配比约束（最大余数容许集）**：对每个正配比维度 d，
  `T_d ∈ {floor(q_d), floor(q_d)+1}` 且 `|T_d − q_d| < 1.0`，其中 q_d 为 §3.4 C1
  冻结管道所定义（fsum 归一化 + 先乘后除）。契约测试侧以输入权重原样计
  `q = N·w_d/Σw输入`——语料内与冻结管道的偏差 ≤ 1ulp，不改变任何被断言的
  T_d（`test_dimension_totals_largest_remainder`、`test_ratio_property_sweep`——
  3000 组随机 (K ∈ [1,8], N ∈ [K,60], 三类配比) 扫描零违例，实测）。
- I3 **总量守恒**：`Σ T_d == budget`；`Σ counts() == budget`；`counts()` 与各维度
  sub-dict 构成划分（`test_counts_partition_budget`、`test_per_dimension_partition`）。
- I4 **覆盖约束**：去重后每个目标知识点在 `counts()` 中 ≥ 1；`budget < 去重目标数`
  在校验期拒绝（`test_full_coverage_at_minimum_budget`；拒绝行为由
  `test_invalid_budget_rejected` 的 budget=3 < K=4 用例断言）。
- I5 **修复不越维**：覆盖修复前后维度合计不变——凡触发 C3 的输入（N=4、N=6、
  等权 N=5 实测例），其 T 仍等于最大余数法直接配额结果
  （`test_coverage_repair_hand_cases`、`test_equal_weight_tie_break`）。
- I6 **纯函数与无别名**：不修改入参（targets 迭代对象、ratios dict、graph 均不被
  改动；调用方构造后追加/改写自己的容器不影响已产出的 Blueprint）；Blueprint
  持有容器与 `counts()`/`per_dimension()` 返回值均为新容器——含 §3.2 无别名条款：
  `bp.ratios is DEFAULT_RATIOS` 为假，原地改 `bp.ratios` 不跨调用泄漏
  （`test_purity_and_copy_semantics`。注：契约语料未原地改写 bp.ratios，本条款
  后半为规格显式冻结项，实测别名实现 `self.ratios = DEFAULT_RATIOS` 可通过全部
  18 项测试——故以本条款冻结复制语义，实现不得别名）。
- I7 **常量冻结**：`DIMENSIONS`/`DEFAULT_RATIOS`/`DIFFICULTY_TARGET` 逐值等于 §3.1
  （`test_frozen_constants`）。
- I8 **校验完备性**：§3.3 V1–V4 各类非法输入逐一抛 `BlueprintError`——含 targets
  不可迭代对象（None、42）；`BlueprintError` 是 `ValueError` 子类；
  `ratios=None` 合法并取缺省配比（`test_invalid_targets_rejected`、
  `test_invalid_budget_rejected`、`test_invalid_ratios_rejected`、
  `test_unknown_kp_rejected`；issubclass 断言在 `test_frozen_constants`）。
- I9 **可组装性（供 generate_paper）**：`counts()` 输出可直接作 paper.generate_paper
  的 blueprint：对契约夹具 small_bank（a:3,b:2,c:1,d:2 题）+鸭子 graph，
  `generate_paper(small_bank, duck_graph, bp.counts(), seed=3)` 成功产出
  `len(item_ids) == budget` 的互异题目，各节题数与 counts 一致
  （`test_feeds_generate_paper`；契约测试允许 import paper——模块本身不 import）。
- I10 **输出键集精确性**：`set(bp.ratios)` 与 `set(bp.dimension_totals)` 均恰好等于
  正配比维度集（零配比维度不存在于任何输出字段）；正配比零合计维度仅出现在
  `dimension_totals`（值 0）（`test_partial_ratios_restrict_dimensions` 的键集
  精确相等断言、`test_zero_total_dimension` 的全字典相等断言；
  `test_ratio_property_sweep` 对随机零权重仅作宽容断言，键集以本条前两测试为
  绑定依据）。

18 项契约测试全部被 I1–I10 及 §3.5/§3.6 引用，无遗漏、无虚构名。

## 5. 确定性与随机性

- `build_blueprint` 是纯函数：输出只依赖 (去重排序后的目标集, budget, 生效配比)；
  禁止 `random`、hash 序、系统时钟、环境读取、任何 IO。
- **浮点可复现性**：P0/C1 的全部求和一律取**精确和的正确舍入**（`math.fsum` 语义，
  序无关）；配额恒为 `(budget * w'_d) / Σ'`（按书写序，IEEE 双精度）；余数比较用
  **精确 float 相等**（逐位相同才并列），并列破缺固定为规范维度序 / 目标 id 升序。
  禁止以朴素逐项 `+` 折叠、Kahan 变体或任何补偿/非补偿的其它求和实现替代
  （它们在一般权重下与正确舍入和位级不同，实测反例见 §3.4 P0）。
  §3.5 表中每个输出都是逐位比对点（CPython 3.12.10 x64 实测）。
- `sorted`（码点序）是唯一排序来源：目标 id 升序、维度规范序。

## 6. 错误行为

| 非法输入 | 行为 |
|---|---|
| `targets` 为裸 str / **不可迭代对象（None、42 等物化失败）** / 空 / 含非 str（None、3）/ 含空串 | 校验期抛 `BlueprintError` |
| `budget` 非 int（float/str/None）或为 bool | 校验期抛 `BlueprintError` |
| `budget < 去重目标数`（含 budget ≤ 0） | 校验期抛 `BlueprintError`（覆盖不可能） |
| `ratios` 非 dict；键不在 DIMENSIONS；值非数字/bool/NaN/inf/负；全零（含 -0.0）或空 dict | 校验期抛 `BlueprintError` |
| 目标知识点 `graph.has` 为假 | 校验期抛 `BlueprintError` |
| 正配比维度分得 0 题 | 容忍：`dimension_totals` 保留键值 0，其余输出省略该维度（§3.6） |
| 目标含重复元素 | 容忍：静默去重 |

异常类型一律 `BlueprintError`（`ValueError` 子类）；对契约内输入不抛其他异常。
契约语料 = 本文 §3.3–§3.6 与 §4 所列输入类；契约外语料（如权重和溢出到 inf 的
极端量级）行为不作规定。

## 7. 非目标

- **不选题、不查题库**：库存充足性、难度筛选、去重抽题全部是 paper 的职责
  （库存不足时 paper.generate_paper 自身报错）。bank 不是本模块的入参。
- **不给真实题目标注认知维度**：题库 Item 数据结构无维度字段；本模块产出的是
  *规划格* (kp × 维度) 的题数，题目与维度的绑定由出卷/命题环节实现。
- **不做掌握度加权配比**：不接 diagnosis/Profile；按目标均分是本版面的唯一分配策略
  （掌握度加权属 route/后续迭代）。
- **不跨维度去重出卷**：`per_dimension()` 的多份子蓝图分别喂 generate_paper 时可能
  抽到同一道题（各次调用互不知情）；消重是调用方编排职责，规格仅冻结单蓝图
  `counts()` 路径（I9）。
- **不引入 DIF/信息量等测量学目标函数**：配比由调用方给定，模块只做确定性落实。
- **不做多套卷/多学习者**：一次调用产出一份蓝图。
- **不持久化**：不写文件/数据库。

## 8. 冻结修订记录（2026-09-29，对抗评审 6 项修复落点）

1. **Σw 求和语义冻结**（原草稿未定）：P0/C1 全部求和冻结为精确和的正确舍入
   （fsum 语义、序无关），含实测反例与"测试盲区仍为绑定条款"的声明（§3.4 P0、
   §5）。评审建议的"朴素左折叠"未被采纳：实测参考实现在 CPython 3.12 的求和与
   fsum 逐位一致（100 万组随机权重 0 分歧），而朴素折叠与参考实现在 ~17% 随机
   权重下 `bp.ratios` 位级不同——冻结朴素折叠反而背离参考实现。
2. **targets 不可迭代对象**：V1.2 新增（None、42 → BlueprintError，对齐
   test_invalid_targets_rejected），§6 表首行同步。
3. **targets 容器种类**：V1.3 冻结为"除裸 str 外一切可迭代接受"（参考实现实测
   dict/生成器/dict_keys 均接受），并冻结"元素校验先于去重"（V1.4）。
4. **ratios=None 的别名语义**：§3.2 无别名条款 + I6 后半冻结复制语义
   （bp.ratios is DEFAULT_RATIOS 必须为假；实测别名实现可通过全部测试，故以
   条款显式冻结）。
5. **零配比键集条款**：§3.2/I10 改为双向精确键集语义并绑定到
   test_partial_ratios_restrict_dimensions / test_zero_total_dimension 的精确断言。
   （评审所称"保留 0 配比键可通过全部契约测试"经变异实验否定：该实现使
   test_partial_ratios_restrict_dimensions 与 test_zero_total_dimension 失败。）
6. **测试名引用修正**：I4 的 `test_budget_below_targets_rejected`、I8 的
   `test_error_is_valueerror_subclass` 在契约测试文件中不存在，分别改为
   `test_invalid_budget_rejected`（budget=3<K 用例）与 `test_frozen_constants`
   （issubclass 断言）。全文 18 个测试名逐一核对存在。
