# route 模块规格（冻结契约·定稿）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> 本定稿根据对抗评审意见修订（相对 specs/drafts/route.spec.md）：更正 I1 的契约引用并注明等价前提、
> 明确 I8 公式优先于边界表述、冻结 I7 异常链语义、限定 §6 包装范围、把 I11 改写为本模块输出属性。
> 与契约测试一致的部分原样保留。

**证据标记**：
- 【契约】= `tests/contract/test_route_contract.py` 明确断言的行为（行为 ground truth）；
- 【参考】= 参考实现 `src/xuexing/route.py` 中可读出、且起草/评审时实际运行复核过的行为（API 发现）。
- **优先级规则**：两者冲突时以【契约】为准——但"冲突"仅在**契约测试可构造、可观察的输入**上有定义；
  对契约测试无法产生的输入类（如 mastery 含图外键、mastery_threshold > 0.8），按【参考】冻结为权威行为，
  并在相应条款注明"测试未覆盖"。禁止为实现通过某条边界表述而偏离参考公式（见 I8）。

## 1. 目的

学习路线规划器：把诊断引擎产出的掌握度画像（`Profile`）映射为一份有序学习计划（`LearningPlan`）。
职责三件事：挑出薄弱知识点（低于掌握度阈值者）排成一个**拓扑有效且按"影响×缺口"优先**的学习步骤序列；
按掌握度/年级从策略库为每步选教学策略；为已达标知识点生成间隔复习日程。
它是纯函数式规划器：不读时钟、无随机、不做 IO，输出完全由入参决定。

## 2. 允许的依赖

- Python 标准库（`datetime.date` 用于 `today` 参数与日期运算）
- `xuexing.types`（**绝对导入**：`from xuexing.types import LearningPlan, PlanStep, ReviewEntry`）
- **经由入参对象**调用其公开方法（无需、也不得 import 其所属模块）：
  `graph.has/prereqs/descendants/kps/get`（KPGraph）、`strategies.select`（StrategyLibrary）。
  在契约测试注入体系下，这些对象是参考实现实例或按其自身规格重生成的实例（tests/contract/conftest.py:1-4）。
- 禁止：import 其他任何 xuexing 模块（`kpgraph`/`itembank`/`pedagogy`/`scheduler`/`diagnosis` 等）。
  参考实现用相对导入协作（route.py:6-10），重生成实例受单文件约束（conftest.py:4），scheduler 的行为
  必须按 §3.1 复习条目 / I10 的固定数值**内联**（等价于 `schedule(kp_id, [ReviewLog(rating=2, days_since_last=0)], today)` 的输出）。
- 禁止：第三方库、任何文件/网络 IO、读系统时钟、随机源。
- 重生成实例必须是**单文件**，由 conftest 以 `spec_from_file_location` 装载并顶替
  `sys.modules["xuexing.route"]`（conftest.py:14-26），**不得使用包内相对导入**；必须暴露本模块全部公开 API（§3）。

## 3. 公开 API

### 3.0 `RouteError(ValueError)`

模块唯一异常类型，**必须**是 `ValueError` 的子类。
【参考】route.py:13-14；运行复核 `issubclass(RouteError, ValueError) == True`。

### 3.1 `build_plan(profile, bank, graph, strategies, today, mastery_threshold=0.65, session_size=4) -> LearningPlan`

生成学习计划。`profile: Profile`、`bank: ItemBank`、`graph: KPGraph`、`strategies: StrategyLibrary`、
`today: datetime.date`；两个带默认值的关键字参数名必须与上式一致（契约以位置与关键字两种方式传参，
test_route_contract.py:25 与 59、61）。【契约】签名用法见 test_route_contract.py:25-26, 59, 61；【参考】route.py:17-25。

#### 参数校验（立即，先于一切计算）

- `mastery_threshold` 不在**开区间** (0,1)（含 0.0、1.0、负数、NaN）→ `RouteError`，参考消息
  `mastery_threshold out of (0,1)`。**时机：调用入口**。【契约】test_param_validation:58-59（1.5 抛 RouteError）；
  【参考】route.py:34-35；运行复核 0.0 / 1.0 / -0.1 / NaN 均抛。
- `session_size < 1` → `RouteError`，参考消息 `session_size must be >=1`。**时机：调用入口**。
  【契约】test_param_validation:60-61（0 抛 RouteError）；【参考】route.py:36-37；运行复核 -3 也抛。
- 两参数同时非法时先报 `mastery_threshold`（route.py:34-37 代码序）。【参考】
- `mastery_threshold` 传入**非数值类型**（如字符串）：比较运算抛 `TypeError`，**原样透传、不包装**为
  RouteError。测试未覆盖；按参考实现冻结。【参考】route.py:34 + 运行复核（`'<' not supported between
  instances of 'float' and 'str'`）。

#### 输入容错（不抛异常）

- `profile.mastery` 中不在 `graph` 里的键：参考实现将其**过滤**——不进弱点集、不进 steps
  （route.py:39 的 `graph.has(k)` 条件）；复习遍历只走 graph 节点（route.py:74-79），故图外键也不进 reviews。
  **与契约字面的关系**：test_plan_covers_weak_and_respects_topology:26-27 计算的 weak 集合**未做图过滤**
  （`weak = {k for k, m in profile.mastery.items() if m < 0.65}`），断言的是未过滤集合相等。两种读法仅在
  `profile.mastery` 的键 ⊆ graph 节点 id 时等价；该前提由 diagnose 保证（diagnosis.py:39-40 只为图节点初始化
  mastery），三个契约场景下运行复核 out_of_graph 均为 `[]`（且图节点无一缺键）。**冻结行为**：契约可达输入上
  以测试为准（两读法均通过套件）；对测试无法产生的输入类（mastery 含图外键），按参考实现冻结为"过滤掉"。
  【契约:26-27（未过滤字面）+ 参考 route.py:39 + 运行复核】
- `graph` 中没有 mastery 键的节点：按 `0.0` 参与复习资格比较（阈值 > 0 时不复习）。弱点集只遍历
  `profile.mastery` 的键，故该缺省只影响复习侧。【参考】route.py:39, 76；运行复核 mastery 只含 `{"a":0.9}` 时
  图中 `b` 无键 → `b` 既不进步骤也不进复习。
- 弱点集为空（如全部达标）→ 返回 `steps=[]` 的合法计划（复习照常生成）。【参考】route.py:40-53 循环体不执行；
  运行复核全对画像 → `steps == []`、`len(reviews) == 18`。

#### 步骤序列（steps）

弱点集（按 I1 的契约字面与参考过滤两层定义，见 §3.1 输入容错第一条；比较含等号边界：恰等于阈值视为
已达标、不弱）。

按如下贪心生成**全序**（route.py:40-53），每轮：

1. 可选取 `pickable` = 弱点集中满足"每个**声明** prereq p：p 不弱 **或** p 已排入计划"的知识点
   （route.py:43-46，经 `graph.prereqs(k)` 取声明，kpgraph.py:92-94）。已掌握/非弱的 prereq **不阻塞**；
   门控只看声明 prereqs，不要求先序边存在。【参考】运行复核：声明 prereq 但未加边 → 弱先序仍阻塞（`["p","q"]`），
   非弱 prereq 不阻塞（`["b"]`）。
2. `pickable` 为空 → `RouteError`，参考消息 `no pickable weak kp: prerequisite deadlock`（弱点子图声明成环时
   才可能触发）。**时机：排序阶段**。【参考】route.py:47-48；运行复核 a、b 互相声明 prereq → 抛。
3. 对每个候选计算 `impact = len(graph.descendants(k))`（传递后继数，基于已加边，kpgraph.py:107-116）与
   `gap = mastery_threshold - profile.mastery.get(k, 0.0)`，取 `sorted(pickable, key=lambda x: (-(impact·gap), x))[0]`
   —— 即 **impact×gap 最大者；平局按 kp_id 升序**。【参考】route.py:49-51；运行复核：三个同后代数同掌握度的
   候选按 `["a","m","x"]` 字典序入选；数据夹具上七轮完整 trace 与最终 steps 序列逐轮吻合。
4. 选出者追加进计划并移出待选集，直到弱点集排尽。每个弱 kp 恰出现**一次**（无重复、无遗漏）。

每个弱 kp 产出一个 `PlanStep`，按上述顺序（route.py:55-72）：

- `kp_id` = 该知识点 id。
- `strategy_id` == `strategies.select(mastery[kp_id], kp.grade).id`（select 语义：priority 降序、第一个
  条件匹配者胜出，pedagogy.py:32-47；grade 取 `graph.get(kp_id).grade`，弱点 ⊆ graph 故节点必存在，缺省 7 的
  分支不可达）。【契约】test_steps_have_strategy_and_target:49（`strategies.get(s.strategy_id) is not None`）与
  :52-53（数据策略库下 `m < 0.4 ⟹ strategy_id == "s_worked_example"`）；【参考】route.py:59-60。
- **异常包装（含链式语义）**：select 抛出的异常若已是 `RouteError` 则原样重抛；其他任何异常**以不带
  `from` 的裸 `raise`** 包装为 `RouteError(f"strategy selection failed for {kp_id}")`——即隐式异常链：
  原异常进入 `__context__`，`__cause__` 保持 `None`。运行复核（空策略库触发）：
  `e.__cause__ is None == True`、`type(e.__context__) is StrategyError`、消息 `no strategy matches
  mastery=0.01024, grade=7`。实现**不得**改用 `raise ... from e`（会将 `__cause__` 置为原异常）、不得吞掉
  原异常链。契约测试不考察链式，行为按参考冻结。**时机：步骤构造阶段（排序完成之后）**；
  典型触发：策略库无匹配条件者（select 抛 StrategyError）。【参考】route.py:59-64。
- `rationale` == `f"mastery={m:.2f} < {mastery_threshold}; {strat.evidence}"`（m 为两位小数定宽格式化）。
  【参考】route.py:69；运行复核样例：`'mastery=0.01 < 0.65; Mayer CTML(2024)；expertise reversal (Tetzlaff et al. 2025)'`。
  契约测试不断言其内容，但格式按本条冻结。
- `target_mastery` == `max(0.85, mastery_threshold + 0.2)`——**公式优先**：只依赖 `mastery_threshold`，与该步的
  kp/mastery 无关，**无任何上截断**。默认阈值 0.65 下精确浮点值为 `0.65 + 0.2`（即 `0.8500000000000001`），
  满足契约边界 `0.5 < target_mastery <= 1.0`（test:50）；该边界对所有 `t ∈ (0, 0.8]` 成立，但测试未考察
  `t > 0.65`：`t ∈ (0.8, 1)` 时 `target_mastery > 1.0` 是**冻结行为**（运行复核 t=0.9 → 全部步骤
  `target_mastery == 1.1`）。实现不得为满足边界表述而加 1.0 截断。【契约:50 + 参考 route.py:70 + 运行复核】

#### 复习日程（reviews）

按 **kp_id 升序**输出（这是本模块输出的冻结属性，见 I11），遍历全部图节点，凡
`profile.mastery.get(kp.id, 0.0) >= mastery_threshold` 者生成一条 `ReviewEntry`（route.py:74-79）：

- `kp_id` = 节点 id；
- `due` = `today + 2 天` 的 ISO 日期字符串——即等价于调度器
  `schedule(kp_id, [ReviewLog(rating=2, days_since_last=0)], today)`（默认 `initial_interval=1`、`initial_ease=2.5`）
  的输出：单条 rating=2 日志 → `interval_days = round(1×2.5) = 2`、`ease = 2.5`、`due = today.toordinal()+2`
  （scheduler.py:33-53）。重生成实例不得 import scheduler，按本条数值内联。
  【契约】test_reviews_only_mastered_and_future:40（`all(r.due > TODAY.isoformat())`，严格晚于当日）；
  【参考】route.py:78 + scheduler.py:33-53；运行复核 today=2026-09-28 → 全部 `due='2026-09-30'`、
  `interval_days=2`、`ease=2.5`。
- 因此弱知识点（mastery < 阈值）必不在 reviews 中。【契约】test_reviews_only_mastered_and_future:41
  （`"kp_power" not in {r.kp_id}`）；【参考】route.py:77 的 `>=` 判定。

#### 返回值

`LearningPlan(learner_id=profile.learner_id, steps=..., reviews=..., created_at=today.isoformat())`。
`created_at` 来自**参数** `today`，不是系统时钟。【参考】route.py:81-86。

#### 无关参数

`bank` 在参考实现函数体内**完全未被读取**（route.py:34-86 无引用）；`session_size` 仅参与入口校验
（route.py:36-37）。两者除上述校验外不得对输出产生任何可观测影响。【参考】

### 3.2 具体输入输出例子（摘自契约测试场景）

场景构造（test_route_contract.py:13-20 的 `_profile` + tests/conftest.py:18-30 的数据夹具）：
对 `bank.items()` 逐题作答——主知识点（`it.kps[0]`）等于 `wrong_kp` 的题答错、其余全对，
`diagnose(rs, bank, graph, learner_id="u")` 生成画像；`TODAY = date(2026, 9, 28)`；其余参数全默认。
例中 mastery 数值是参考 diagnosis 的输出（下列显示四舍五入到 4 位；诊断行为属 diagnosis 自身规格），
plan 为起草时运行复核的完整结果。三个场景的画像 mastery 键均恰为 18 个图节点（运行复核 out_of_graph == []），
故"契约字面（未过滤）"与"参考（图过滤）"两种弱点集读法在这些场景下等值：

**例 1**（test_route_contract.py:23-32 场景，`wrong_kp="kp_rational_add"`）：
weak 共 7 个，steps 全序与策略为

```python
[("kp_rational_add", "s_worked_example", m=0.0012),
 ("kp_rational_mul", "s_worked_example", m=0.1603),
 ("kp_poly_ops",     "s_worked_example", m=0.1585),
 ("kp_eq_concept",   "s_retrieval",      m=0.6124),
 ("kp_eq_solve",     "s_retrieval",      m=0.6277),
 ("kp_power",        "s_retrieval",      m=0.6392),
 ("kp_mixed_ops",    "s_worked_example", m=0.1583)]
# 全部 target_mastery == 0.8500000000000001
reviews: 11 条，kp_id 升序 = [kp_absvalue, kp_algebraic, kp_angles, kp_eq_apply, kp_geometry_basic,
         kp_like_terms, kp_lines_rays, kp_monomial, kp_numberline, kp_opposite, kp_posneg]，
         每条 due="2026-09-30"、interval_days=2、ease=2.5
created_at == "2026-09-28"，learner_id == "u"
```

排序可由 I3/I4 逐轮验证，如第 2 轮 pickable={kp_rational_mul, kp_poly_ops}：
impact×gap = 4×0.4897 ≈ 1.959 > 3×0.4915 ≈ 1.475 → 取 kp_rational_mul（起草时 trace 复核）。

**例 2**（test_route_contract.py:35-41 场景，`wrong_kp="kp_power"`）：

```python
weak == {"kp_power", "kp_mixed_ops"}
steps == [("kp_power", "s_worked_example", m=0.0102),
          ("kp_mixed_ops", "s_worked_example", m=0.1626)]
reviews: 16 条（18 个图节点中除 kp_power、kp_mixed_ops 外全部），全部 due="2026-09-30" > "2026-09-28"，
         且 "kp_power" 不在任何 review 中
```

**例 3**（test_route_contract.py:56-61）：

```python
build_plan(profile, bank, graph, strategies, TODAY, mastery_threshold=1.5)  # raises RouteError
build_plan(profile, bank, graph, strategies, TODAY, session_size=0)         # raises RouteError
```

## 4. 不变量（全部可被契约测试或上述复核检验）

- I1 **弱点覆盖完备且唯一**：`{s.kp_id for s in plan.steps}` == `{k for k, m in profile.mastery.items() if m < mastery_threshold}`
  （**契约字面，未做图过滤**——test_plan_covers_weak_and_respects_topology:26-27 即如此计算 weak 并断言相等）；
  每个弱 kp 恰一个步骤；`steps` 为空 ⟺ 弱点集为空。
  **等价性与冻结细化**：参考实现额外按 `graph.has(k)` 过滤（route.py:39）。两读法在 `profile.mastery` 键 ⊆
  graph 节点时恒等——该前提由 diagnose 保证（diagnosis.py:39-40），且三个契约场景运行复核 out_of_graph == []。
  对契约测试无法产生的输入（mastery 含图外键），冻结为参考行为：图外键被过滤、不进 steps（实现若按测试字面
  不过滤，可通过套件但违反本条细化，且须对图外 id 调 `graph.prereqs`/`get`，行为未定义）。
  【契约:26-27 + 参考 route.py:39 + 运行复核】
- I2 **步骤拓扑有效**：任一步骤的声明 prereq 若同为步骤成员，必排在该步骤之前。【契约】test_plan_covers_weak_and_respects_topology:28-32
- I3 **阻塞语义**：只有"弱且未排入"的**声明** prereq 阻塞；非弱/已排入的不阻塞；门控只依据
  `graph.prereqs` 声明（不要求边存在）。【参考】route.py:43-46 + 运行复核（声明无边仍阻塞；非弱 prereq 不阻塞）。
- I4 **贪心唯一序**：每轮从 pickable 取 `len(descendants) × (mastery_threshold − mastery)` 最大者，
  平局按 kp_id 升序；steps 顺序由此规则唯一决定，不存在其他并列合法序。【参考】route.py:49-51 +
  运行复核（平局字典序 `["a","m","x"]`；七轮 trace 与输出逐步吻合）。
- I5 **死锁拒绝**：pickable 为空 → `RouteError("no pickable weak kp: prerequisite deadlock")`，
  时机在排序阶段。【参考】route.py:47-48 + 运行复核（weak 声明环触发）。
- I6 **策略委托**：每步 `strategy_id == strategies.select(m, kp.grade).id`；契约断言该 id 必在库中
  （`strategies.get(...) is not None`），且数据策略库下 `m < 0.4 ⟹ "s_worked_example"`。
  【契约】test_steps_have_strategy_and_target:49, 52-53；【参考】route.py:59-60 + pedagogy.py:32-47。
- I7 **策略失败包装（隐式链）**：select 抛出的非 RouteError 异常一律包装为
  `RouteError("strategy selection failed for {kp_id}")`，包装方式为**不带 `from` 的裸 raise**：
  `__cause__ is None`、`__context__` 为被包装的原异常（运行复核复核如 §3.1）；RouteError 原样重抛。
  契约测试不考察链式语义，本条按参考实现冻结（`raise ... from e` 形式不合规）。【参考】route.py:59-64 + 运行复核。
- I8 **目标掌握度公式（公式优先）**：每步 `target_mastery == max(0.85, mastery_threshold + 0.2)`，只依赖
  `mastery_threshold`、与 kp/mastery 无关、**无上截断**。契约边界 `0.5 < target_mastery <= 1.0`
  （test:50）仅在默认阈值 0.65（0.8500000000000001）乃至全部 `t ∈ (0, 0.8]` 下成立；`t ∈ (0.8, 1)` 时
  `target_mastery > 1.0` 是冻结行为（运行复核 t=0.9 → 1.1），不得为满足边界表述加截断。
  【契约:50 + 参考 route.py:70 + 运行复核】
- I9 **复习成员**：`{r.kp_id for r in plan.reviews}` == `{kp ∈ graph : mastery.get(kp, 0.0) >= mastery_threshold}`
  （等值集为参考冻结，route.py:74-79；契约断言为**子集**：`{r.kp_id} <= {k : mastery[k] >= 0.65}`，test:38-39——
  该断言在两种读法下恒被满足，因 reviews 只含图节点）；故弱知识点必不在 reviews 中（test:41）。
  缺键节点按 0.0 不复习（运行复核）。【契约:38-41 + 参考 route.py:74-79 + 运行复核】
- I10 **复习日程值**：每条 `due == (today + 2 天).isoformat()`（严格晚于 today 的 ISO 字符串）、
  `interval_days == 2`、`ease == 2.5`，等价于 `schedule(kp_id, [ReviewLog(rating=2, days_since_last=0)], today)`
  默认参数的输出。【契约】test_reviews_only_mastered_and_future:40；【参考】route.py:78 + scheduler.py:33-53 +
  运行复核。
- I11 **复习排序（本模块输出属性）**：reviews 按 kp_id **升序**——这是 route 必须自行保证的输出属性，
  不委派给上游：参考实现经遍历 `graph.kps()`（route.py:75）达成该序，而 kpgraph 自身冻结契约
  （specs/frozen/kpgraph.spec.md:261 之 I14"`kps()` 按 id 升序，与加入顺序无关"；kpgraph.py:80-81）
  保证 `kps()` 升序，故合规组合中"信任 kps() 序"与"自行 sorted()"等价（运行复核两者一致）；
  若上游 `kps()` 失序（违反其契约），本模块输出仍须保持 kp_id 升序。
  【参考 route.py:74-75 + kpgraph.py:80-81 + specs/frozen/kpgraph.spec.md:261 + 运行复核】
- I12 **参数校验**：`mastery_threshold ∈ 开区间 (0,1)`、`session_size >= 1`，违反即抛 `RouteError`，
  时机为调用入口、先于任何计算。范围之外：非数值 `mastery_threshold` 抛原生 `TypeError` 且不包装（§6）。
  【契约】test_param_validation:56-61；【参考】route.py:34-37 + 运行复核。
- I13 **确定性**：`build_plan` 无随机、不读系统时钟；`created_at` 与 `due` 均由参数 `today` 派生；
  同输入重复调用结果全对象相等（至少 steps 的 kp_id 序列与 reviews 的 (kp_id, due) 序列逐项相等）。
  【契约】test_deterministic:64-69；【参考】route.py 全文无 random/clock + 运行复核 `plan1 == plan2`。
- I14 **透传与无副作用**：`learner_id == profile.learner_id`、`created_at == today.isoformat()`；
  不修改任何入参对象。【参考】route.py:81-86 + 运行复核。
- I15 **bank/session_size 无关性**：`bank` 内容与 `session_size`（除 I12 校验）不影响输出的任何字段。
  【参考】route.py:34-86 函数体无引用。

## 5. 确定性与随机性

- **`build_plan` 是纯函数**：同输入恒同输出（起草时运行复核两次调用全对象相等；契约只断言 steps 序列与
  reviews 的 (kp_id, due) 序列相等，test_deterministic:64-69，实现不得弱于此）。
- **无随机源**：无 seed 参数、无 random 调用；贪心循环虽遍历 set，但选择经 `sorted` 全序破平
  （key 元组含唯一 kp_id，route.py:51），set 迭代顺序不得影响输出。
- **无系统时钟**：`datetime` 仅使用参数 `today`；`created_at`（本模块唯一的"时间戳字段"）取
  `today.isoformat()`，`due` 取 `today + 2 天`。实现禁止读取 `datetime.now`/`time.*`。
- 排序即契约：steps 按 I4、reviews 按 I11（kp_id 升序为本模块输出属性，不依赖上游顺序）。
- 禁止：隐藏随机、依赖 dict 插入顺序/哈希序的输出、依赖 locale 的排序或格式化（rationale 中
  `:.2f` 除外，其为定宽格式）。

## 6. 错误行为

| 非法输入 / 情形 | 行为 | 时机 | 证据 |
|---|---|---|---|
| `mastery_threshold ∉ 开区间 (0,1)`（0.0、1.0、负数、NaN） | `RouteError("mastery_threshold out of (0,1)")` | 调用入口，立即 | 【契约:58-59 + 参考 route.py:34-35 + 运行复核】 |
| `session_size < 1`（0、负数） | `RouteError("session_size must be >=1")` | 调用入口，立即 | 【契约:60-61 + 参考 route.py:36-37 + 运行复核】 |
| 两参数同时非法 | 先报 `mastery_threshold` | 调用入口 | 【参考 route.py:34-37 代码序】 |
| `mastery_threshold` 为非数值类型 | 原生 `TypeError` **原样透传、不包装**（测试未覆盖，按参考冻结） | 调用入口 | 【参考 route.py:34 + 运行复核】 |
| 弱点子图声明成环（pickable 为空） | `RouteError("no pickable weak kp: prerequisite deadlock")` | 排序阶段 | 【参考 route.py:47-48 + 运行复核】 |
| 策略库无匹配（select 抛非 RouteError） | `RouteError("strategy selection failed for {kp_id}")`，隐式链（`__cause__ is None`、`__context__` 为原异常） | 步骤构造阶段 | 【参考 route.py:59-64 + 运行复核】 |
| select 抛 RouteError | 原样重抛，不二次包装 | 步骤构造阶段 | 【参考 route.py:61-62】 |
| `profile.mastery` 含图外键 | 容忍：参考实现过滤（不进 steps/reviews）。注：契约测试无法产生该输入（diagnose 只产图节点键；test:26-27 字面为未过滤集合），两种读法在此输入上分叉，冻结为参考行为 | — | 【契约:26-27 + 参考 route.py:39 + 运行复核】 |
| 图节点在 mastery 中缺键 | 容忍：复习侧按 0.0（阈值>0 时不复习）；弱点集侧不适用（weak 只遍历 mastery 键） | — | 【参考 route.py:39, 76 + 运行复核】 |
| 弱点集为空 | 容忍：返回 `steps=[]`、reviews 照常的合法计划 | — | 【参考 + 运行复核全对画像】 |

原则：领域错误一律 `RouteError`（`ValueError` 子类，§3.0）。**包装范围仅限**步骤构造阶段
`strategies.select` 抛出的非 RouteError 异常（I7）；除此之外的一切意外类型异常（含参数类型错误引发的
`TypeError`）不做包装、原样透传。参数校验 fail-fast 于入口，其余错误在对应阶段当场抛出。

## 7. 非目标

- 不选题、不组卷、不读题库内容：`bank` 形参仅为签名占位（I15），选题属 `paper` 模块。
- 不做会话切分：`session_size` 仅参与校验，不产生"每次学习会话 N 题"之类的结构或字段。
- 不追踪计划执行进度：无"完成步骤/更新掌握度后推进计划"的 API；每次调用全量重新生成。
- 不暴露复习策略可插拔性：复习日志固定 `rating=2, days_since_last=0`、间隔参数取调度器默认
  （等价输出冻结于 I10）；升级 FSRS 属 scheduler 模块的事，route 不感知。
- 不校验 `profile`/`graph`/`strategies` 的一致性（图是否无环、grade 域、库是否为空等）；
  不一致的后果即 §6 所列行为，不额外防御。
- 不修改任何入参；无缓存、无持久化、无 IO、无日志。
- `rationale`/`target_mastery` 的教学合理性不在契约范围内——只冻结其字符串格式（§3.1）与计算公式（I8）。
- 不保证并发/线程安全；单线程使用假设。
- 不做计划内知识点的内容推荐（如具体题目、资源链接）；`PlanStep` 只有 types.py 冻结的四个字段。
