# diagnosis 模块规格（冻结契约 v2，定稿）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。
>
> **约束力**：本文全部条款均为验收条款。实现代码结构自由，但对外行为——包括全部数值后果、
> 舍入规则、迭代次数、合成规则——必须与本文一致；不存在"仅参考性"的条款。
>
> **证据来源标注**（仅供审阅，不构成约束力差别）：
> -【测试】= tests/contract/test_diagnosis_contract.py 直接断言的行为（行为 ground truth）；
> -【探针】= 本规格定稿时对参考实现运行核实的数值或规则（契约测试仅覆盖其不等式/集合等弱后果）。
> 规格与测试冲突时以测试为准；本文定稿时两者已对齐（`PYTHONPATH=src python -m pytest
> tests/contract/` → 47 passed）。
> 本文所有【探针】数值均经过双重验证：闭式手工计算 + 按本文文本独立重写的引擎与参考实现
> 逐位对拍（300 组良构图模糊用例 0 不匹配，见 §8）。

## 1. 目的

诊断引擎：把一个学习者的作答序列（`list[Response]`）折叠成知识点掌握度画像（`Profile`）：
每个知识点一个 `[0,1]` 掌握度 + 作答证据计数 + 置信度，并提供按章节聚类的聚合视图。
只依据 `ItemBank` 中的题目属性（知识点、难度、猜测率）与 `KPGraph` 中的先序结构做更新与平滑，
不做任何选题、规划或 IO。

## 2. 允许的依赖

- Python 标准库（参考实现仅用 `datetime`/`timezone` 生成时间戳）
- `xuexing.types`（**绝对导入**：`from xuexing.types import ...`；`Profile`、`Response` 等）
- 禁止：其他 xuexing 模块（包括 `xuexing.kpgraph`、`xuexing.itembank` —— bank 与 graph 只作为
  注入参数使用）、第三方库、文件/网络 IO。
- 对注入对象只允许调用以下成员（鸭子类型，重生成实现不得 import 其定义模块）：
  - `bank.get(item_id) -> Item | None`
  - `graph.kps() -> list[KnowledgePoint]`（参考 KPGraph 按 id 升序返回）
  - `graph.has(kp_id) -> bool`
  - `graph.prereqs(kp_id) -> list[str]`（**直接**前序，即 `KnowledgePoint.prereqs` 的声明列表，
    非传递闭包——【探针】`small_graph` 上 `prereqs("c") == ["b"]`）
  - `Item.effective_guess() -> float`、`Item.difficulty`、`Item.kps`
  - `Response.item_id`、`Response.correct`（`learner_answer`、`response_ms` 不参与诊断）
- 不要求调用 `graph.topological_order()`：平滑每轮只读上一轮快照（见 §3.2.3），轮内遍历顺序
  不影响结果，实现可任选遍历基准（本文独立验证引擎用 `kps()`、参考实现用拓扑序，输出逐位一致）。
- 输入图假定良构（`KnowledgePoint.prereqs` 声明与边一致、无环，如 `validate()` 为空）。劣构图上
  行为仍由 §3.2.3 算法唯一定义（只读 `prereqs()` 声明列表），但不作额外承诺。

## 3. 公开 API

模块必须暴露且仅暴露以下 3 个公开函数（conftest 按此装载重生成实例）：

### 3.1 `slip_from_difficulty(difficulty: float) -> float`

- 语义：P(答错 | 已掌握)。难度越高，掌握者失误概率越高。
- **精确定义（绑定）**：`clamp01(0.05 + 0.20 * difficulty)`，其中 `clamp01(x) = max(0.0, min(1.0, x))`。
  输出**不做**任何舍入。
- 参考值【探针】：difficulty 0.0→0.05，0.1→0.07，0.5→`0.15000000000000002`（浮点原样），
  0.9→`0.23000000000000004`，1.0→0.25。在 [0,1] 上严格递增、恒正、值域 [0,1]。
-【测试】`slip_from_difficulty(0.9) > slip_from_difficulty(0.1) > 0`（test_slip_monotone）。

### 3.2 `diagnose(responses: list[Response], bank: ItemBank, graph: KPGraph, learner_id: str = "anon", prior: float = 0.5) -> Profile`

语义：逐条处理作答（按列表顺序），对每题所涉知识点做贝叶斯式更新（感知猜测率与难度滑率），
再做先序一致性平滑，返回 `xuexing.types.Profile` 实例。算法分四步，全部为绑定条款。

#### 3.2.1 步骤 A：校验与初始化

- A1 若 `not (0.0 < prior < 1.0)`（开区间，含 0.0、1.0、负数、>1）：立即抛
  `ValueError`（【测试】test_invalid_prior_rejected；【探针】消息 `"prior must be in (0,1)"`）。
  校验先于任何其他工作——`responses` 为空列表也必须抛。
- A2 `mastery = {kp.id: prior for kp in graph.kps()}`；`evidence = {kp.id: 0 for kp in graph.kps()}`。
  两个 dict 的键序与 `graph.kps()` 返回顺序一致（【探针】300 组模糊对拍含键序逐位比较）。

#### 3.2.2 步骤 B：逐题更新（按 `responses` 列表顺序，逐条执行）

对每条 response `r`：

- B1 `item = bank.get(r.item_id)`；为 `None`（题库中不存在）→ **整条跳过**，不影响任何
  mastery/evidence。【测试】test_unknown_item_ignored。
- B2 计算该题的似然比（与当前掌握度无关，每题一次，先于知识点循环）：
  - `g = max(item.effective_guess(), 0.02)`（猜测率下限 0.02）
  - `s = slip_from_difficulty(item.difficulty)`
  - `p_m = clamp01(1.0 - s)`；`p_nm = g`
  - 高猜度护栏：若 `p_m <= p_nm`，则 `p_m = min(p_m + 0.05, 0.99)`。
    护栏修正后的 `p_m` **同时**进入 `lr_c` 与 `lr_w`，且发生在逐知识点加权（B4）之前；
    封顶 0.99 在护栏内完成。护栏触发后的似然比：
    【探针】`guess=0.8, difficulty=0.9` 的 fill 题：`s=0.23`、`p_m=0.77≤0.8 → p_m=0.82`，
    `lr_c=1.025`、`lr_w=0.18/0.2=0.9`；答对一次 mastery=0.506173，答错一次 mastery=0.473684
    （独立引擎与 oracle 逐位一致）。
  - `lr_c = p_m / p_nm`
  - `lr_w = (1.0 - p_m) / max(1.0 - p_nm, 1e-4)`（分母下限 1e-4）
- B3 对 `enumerate(item.kps)` 中每个 `(idx, kp_id)`（**声明顺序，可含重复 id，重复按出现次数
  分别处理**）：
  - `graph.has(kp_id)` 为假 → 跳过该知识点（同题其余知识点照常更新）；
  - 权重 `w = 1.0 if idx == 0 else 0.5`（主知识点= `item.kps[0]`，次要 0.5）；
  - `lr = lr_c if r.correct else lr_w`
  - `lr_eff = lr ** w  if lr >= 1.0  else max(lr ** w, 1e-4)`（放大不打折，衰减有下限 1e-4）
  - odds 更新：
    `odds = max(mastery[kp_id], 1e-4) / max(1.0 - mastery[kp_id], 1e-4)`，
    `odds *= lr_eff`，`mastery[kp_id] = clamp01(odds / (1.0 + odds))`。
    （ mastery 趋近 0/1 有渐近界：【探针】最易题连对 30 次 → 0.999989，最易题连错 30 次 → 8e-06。）
  - `evidence[kp_id] += 1`（与对错、主/次无关；同一题答多次按多条 response 各计一次；
    `item.kps` 含重复 id 时按出现次数各计一次——【探针】`kps=["a","a"]` 答对一次 →
    `evidence["a"] == 2`，mastery 0.961213）。

#### 3.2.3 步骤 C：先序一致性平滑（逐题更新完成后执行，恰好 2 轮）

记号：`m` 为上一轮结束时的掌握度快照（第 1 轮的 `m` = 步骤 B 结束后的原始值），
本轮结果 `ch` 初始为 `m` 的拷贝；`evidence` 为步骤 B 累计的证据计数。每轮依次执行：

- C1（上行补证）对每个 `evidence[d] > 0` 的知识点 `d`，对 `d` 的每个**直接**前序
  `p ∈ graph.prereqs(d)`：若 `evidence[p] == 0`，则
  `ch[p] = max(ch[p], 0.6 * m[d])`。
- C2（下行折价）对每个 `evidence[k] > 0` 的知识点 `k`，对 `k` 的每个直接前序
  `p ∈ graph.prereqs(k)`：若 `evidence[p] > 0`，则
  `ch[k] = min(ch[k], m[k] * (0.4 + 0.6 * m[p]))`。
- C3 本轮结束：`m ← ch`。共执行 **2** 轮，不多不少。

由上述定义直接推出的性质（实现自检用，与定义同等绑定）：

- C-a Jacobi 语义：所有读都来自快照 `m`，所有写都进 `ch` ⇒ **轮内遍历顺序不影响结果**
  （【探针】独立引擎以 `kps()` 序、oracle 以拓扑序遍历，300 组逐位一致）。
- C-b 两组规则触集不相交：补证只写零证据知识点，折价只写有证据知识点 ⇒ 同一轮内二者不叠加。
- C-c 多个有证据后代补证同一零证据前序：取 `max` ⇒ 等价于 `max(prior, 0.6 × 最强后代掌握度)`；
  若最强后代的 0.6 倍仍 ≤ 当前值（如 prior=0.5 时的 0.6×后代<0.5），前序保持不变。
  【探针】`w`（零证据，前序被 u、v 声明）在 u=0.988322、v=0.89011 时 `w=0.592993`
  `== max(0.5, 0.6×0.988322)`（最强后代主导）。
- C-d 多个有证据前序折价同一有证据知识点：对每个前序逐个 `min` ⇒ 因 `m ≥ 0`，等价于
  **最弱前序的因子主导**（`m[k] × min_p(0.4 + 0.6 × m[p])`）。
  【探针】`z`（前序声明为 x、y；x 全错 → 0.056274，y 全对 → 0.988570）答对一次后
  `z = 0.168346`，恰为按最弱前序 x 的因子折价 2 轮：`0.894737 × 0.433764 = 0.388105`（第 1 轮）
  `→ × 0.433764 = 0.168346`（第 2 轮）。
- C-e **折价逐轮复利**：第 2 轮用第 1 轮折价后的值再乘因子（因子仍读快照 `m[p]`）。
  【探针】worked example（test_prereq 场景）：a 两错、b 两对的直接更新值
  `raw_a = 0.016393443`、`raw_b = 0.986643515`，因子 `f = 0.4 + 0.6×raw_a = 0.409836066`：
  第 1 轮 `b₁ = raw_b × f = 0.404362`，第 2 轮 `b₂ = b₁ × f = 0.165722` == oracle 输出；
  单次折价（0.404362）≠ oracle。契约测试只断言 `mastery[a] < 0.5`，轮数由本条款绑定。
- C-f **只作用于直接前序，无传递级联**：补证驱动者必须自身有证据，受惠者必须是零证据的
  直接前序；中间知识点无证据时链条不延伸。
  【探针】small_graph 链 a→b→c（c 的前序声明为 b）：仅 `c1` 答对一次 →
  `mastery == {"a": 0.5, "b": 0.538144, "c": 0.896907, "d": 0.5}`：b 被抬到 `0.6×0.896907`，
  而 a 保持先验 0.5（b 无证据，不再向 a 传递）。
- C-g 补证跨轮幂等保持：第 2 轮重新 `max` 不会降低第 1 轮的抬升。

#### 3.2.4 步骤 D：输出构造

- D1 舍入：**仅在最终值上一次性执行** `round(v, 6)`（Python 内建 round，banker's rounding）。
  步骤 B/C 全程全精度，逐题更新后不得舍入。【探针】逐题舍入变体与 oracle 在 300 组中 235 组
  出现分歧，而按本条款的引擎 0 分歧 ⇒ 该条款可观测且为 oracle 行为。
  因此空 `responses` 时返回 `round(prior, 6)`（【探针】`prior=0.123456789` → `0.123457`，
  ≠ 原始 prior）；`prior=0.5` 时两者重合（契约测试因此不可区分）。
- D2 `updated_at`：UTC 当前时间，格式 `%Y-%m-%dT%H:%M:%SZ`（秒级，如 `2026-09-28T17:01:40Z`）。
  这是模块唯一允许的非确定字段。
- D3 `learner_id` 透传（默认 `"anon"`）；返回值是 `xuexing.types.Profile` 实例，字段为
  `learner_id`、`mastery`、`evidence`、`updated_at`。

#### 3.2.5 具体输入输出例子（夹具 small_bank/small_graph 见 tests/contract/conftest.py:37-68）

- 例 1【测试】（test_evidence_and_confidence）+【探针】逐值：
  `diagnose([Response("a1", True), Response("a2", False)], small_bank, small_graph)` →
  `mastery == {"a": 0.602649, "b": 0.5, "c": 0.5, "d": 0.5}`、
  `evidence == {"a": 2, "b": 0, "c": 0, "d": 0}`、
  `confidence("a") == 0.4 > confidence("b") == 0.0`。
- 例 2【测试】（test_prereq_fill_only_without_direct_evidence）+【探针】逐值：
  `diagnose([Response("b1", True), Response("b2", True)], small_bank, small_graph)` →
  `mastery["a"] == 0.591986 > 0.5`（b 答对把零证据的 a 抬过先验：`0.6×0.986644`），
  `mastery["b"] == 0.986644 > mastery["a"]`，`mastery["c"] == mastery["d"] == 0.5`。
- 例 3【测试】（test_unknown_item_ignored）+【探针】逐值：
  `diagnose([Response("ghost", True)], small_bank, small_graph)` →
  `mastery == {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5}`、`evidence` 全 0。
- 例 4【测试】（test_correct_above_prior_wrong_below / test_monotone_in_number_of_correct /
  test_guess_aware）+【探针】逐值：a 组 3 题全对 → `mastery["a"] == 0.998366 > 0.6`；
  3 题全错 → `0.003874 < 0.4`；仅 1 题对 → `0.90099 ∈ (0.5, 0.998366)`；
  同为答对、难度同为 0.5：选择猜度题 `d1`（guess 0.25）→ `mastery["d"] == 0.772727`，
  低于填空题 `d2`（guess 0.10）→ `0.894737`。
- 例 5【测试】（test_invalid_prior_rejected）+【探针】扩展：
  `diagnose([], small_bank, small_graph, prior=1.0)` 抛 `ValueError`；
  `prior ∈ {0.0, -0.1, 1.5}` 同样抛。
- 例 6【探针】（平滑直接性，对应 §3.2.3 C-f）：
  `diagnose([Response("c1", True)], small_bank, small_graph)` →
  `mastery == {"a": 0.5, "b": 0.538144, "c": 0.896907, "d": 0.5}`。
- 例 7【探针】（多前序/多后代合成，对应 §3.2.3 C-c/C-d）。构造良构图：
  知识点 x、y、z（z.prereqs=["x","y"]）、w、u（u.prereqs=["w"]）、v（v.prereqs=["w"]），
  全部注册对应边；题库（均 fill、guess 默认）：
  x1(d=0.9)、x2(d=0.8)、y1(d=0.1)、y2(d=0.1)、z1(d=0.5)、u1(d=0.1)、u2(d=0.2)、v1(d=0.7)；
  作答 x1、x2 错，y1、y2、z1、u1、u2、v1 对 →
  `mastery == {"u": 0.988322, "v": 0.89011, "w": 0.592993,
              "x": 0.056274, "y": 0.988570, "z": 0.168346}`（闭式复算与 oracle 一致，见 C-c/C-d）。

### 3.3 `aggregate_to_clusters(profile: Profile, graph: KPGraph) -> dict[str, float]`

- 语义：把画像按知识点的 `cluster` 字段求平均，得到章节聚类掌握度。
- 键集合【测试】恰为 `graph.kps()` 中出现过的全部 cluster 标签（small_graph 上
  `set(clusters) == {"c1", "c2"}`，test_cluster_aggregation）。
- **键序（绑定）**：按 cluster 标签的 Python 字符串升序输出（即 `sorted`）。
  【探针】cluster 为 `zz` 的知识点先于 `aa` 注册，输出键序仍 `["aa", "zz"]`。
- 值：该 cluster 下各知识点 `profile.mastery` 的算术平均，**仅在最终值上** `round(·, 6)`；
  ∈ [0,1]【测试】；`profile.mastery` 缺失的知识点按 `0.0` 计入平均
  （【探针】`mastery={"a": 0.9}`、a/b 同属 c1 → `{"c1": 0.45}`）。
  成员累加顺序按 `graph.kps()` 返回顺序。
- 不修改 `profile`，不读写任何文件。
- 例【测试】+【探针】逐值：`diagnose([Response("a1", True)], ...)` 后聚合 →
  `{"c1": 0.700495, "c2": 0.5}`（c1 = (0.90099 + 0.5)/2）。

## 4. 不变量（编号列出，全部可被契约测试或 §8 探针检验）

- I1 确定性：同 `(responses, bank, graph, learner_id, prior)` 两次调用产生完全相等的
  `mastery` 与 `evidence`（test_determinism）。`updated_at` 是唯一例外（§3.2.4 D2）。
- I2 先验域：`prior` ∉ 开区间 (0,1)（含 0.0、1.0、负数、>1）⇒ 抛 `ValueError`，且在任何
  处理之前抛出，空 `responses` 时也抛（test_invalid_prior_rejected + 探针）。
- I3 未知即忽略：`item_id` 不在题库中的 response 被完整忽略；不存在的知识点不产生 mastery
  键，也不产生证据。完全无更新时每个知识点 `mastery == round(prior, 6)`、`evidence == 0`
  （test_unknown_item_ignored + 探针；默认 prior=0.5 时与先验重合）。
- I4 方向性：对同一知识点，全对 ⇒ mastery > 0.6，全错 ⇒ mastery < 0.4；答对条数越多 mastery
  越高（1 对时 ∈ (0.5, 3 对值)）（test_correct_above_prior_wrong_below、
  test_monotone_in_number_of_correct）。
- I5 猜测感知：难度相同时，题目 `effective_guess()` 越高，同样"答对"带来的掌握度抬升越弱
  （`lo > hi > 0.5`，test_guess_aware）。
- I6 证据计数：`evidence[kp]` == 引用 kp 的作答条数（`item.kps` 重复出现按次数累计），与对错、
  主/次无关；未引用的 kp 恒为 0（test_evidence_and_confidence + 探针）。
- I7 置信度：`Profile.confidence(kp_id) == n/(n+3.0)`（`n = evidence.get(kp_id, 0)`，未知 kp 得
  0.0）；证据多者置信度严格更高（test_evidence_and_confidence）。该公式属
  `xuexing.types.Profile`（types.py:67-69），diagnosis 不得另造。
- I8 先序一致性（按 §3.2.3 算法执行，含全部 C-a…C-g 性质；契约测试锁定以下后果，
  test_prereq_fill_only_without_direct_evidence）：
  (a) 后代全对可把零证据直接前序抬过先验（`mastery[a] > 0.5`）；
  (b) 抬升后仍保持后代 > 前序（`mastery[b] > mastery[a]`）；
  (c) 前序有直接负证据时，间接补证不得覆盖直接证据
      （探针：a 两错 + b 两对 → `mastery["a"] == 0.016393 < 0.5`，
      且 `mastery["b"] == 0.165722`，即 C-e 复利折价后的值）。
- I9 值域与完备性：`mastery`/`evidence` 的键集合恰为 `graph.kps()` 的 id 集合（键序亦与
  `graph.kps()` 一致）；所有 mastery ∈ [0,1] 且经最终一次性 `round(·,6)`；evidence 为非负 int。
- I10 滑率单调：`slip_from_difficulty` 在 [0,1] 上随 difficulty 严格递增且恒正
  （test_slip_monotone）。
- I11 聚合完备性：`aggregate_to_clusters` 键集合 == 图中出现过的 cluster 标签集合，键按标签
  升序；每个值 ∈ [0,1]、为成员算术平均（缺失按 0.0）经最终一次性 `round(·,6)`
  （test_cluster_aggregation + 探针）。

## 5. 确定性与随机性

- `diagnose`、`aggregate_to_clusters`、`slip_from_difficulty` 全部同输入同输出；**禁止**一切
  随机源（不得用 `random`、不得依赖 set/dict 遍历顺序等隐性不确定性）。
- 唯一允许的时间依赖：`Profile.updated_at`（UTC，秒级，`%Y-%m-%dT%H:%M:%SZ`）。契约测试刻意
  只比较 `mastery` 与 `evidence`（test_diagnosis_contract.py:12）。
- response 处理顺序：按 `responses` 列表顺序逐条执行。单题似然比与当前掌握度无关，但饱和钳位
  （B3 的 odds 下限/clamp01）可破坏交换律——【探针】12 条混合对错作答参照值 0.599135，
  20 次随机洗牌中出现不同结果 ⇒ **不得**宣称或依赖顺序无关；实现必须按列表顺序处理。
- 平滑轮内遍历顺序无关（C-a），轮数固定为 2（C3）；实现不得增减轮数或改为单次变换。
- 舍入只在最终值上做一次（D1、§3.3）；内部计算全程全精度。
- 键序：`mastery`/`evidence` 随 `graph.kps()`；`aggregate_to_clusters` 键按标签升序（§3.3）。

## 6. 错误行为

| 非法输入 | 行为 |
| --- | --- |
| `prior <= 0` 或 `prior >= 1`（含 0.0、1.0、-0.1、1.5） | 抛 `ValueError`（【探针】消息 `"prior must be in (0,1)"`），在处理任何 response 之前（步骤 A1） |
| `item_id` 不在 `bank` | 容忍：整条 response 跳过，不抛错（B1） |
| `item.kps` 含不在 `graph` 中的知识点 | 容忍：仅跳过该知识点，同题其余知识点照常更新（B3） |
| `item.kps` 含重复知识点 id | 合法：按出现次数分别更新与计证据（B3） |
| 空 `responses` | 合法：返回全 `round(prior,6)`、全 0 证据的画像（prior 合法时，D1） |

- 未发现其他异常路径；`Profile.confidence` 对未知/零证据 kp 返回 0.0 而非抛错（types.py:67-69）。

## 7. 非目标

- 不做判分：`Response.correct` 视为已判定的输入，模块不比对 `learner_answer` 与 `answer`。
- 不选题、不排课、不给教学建议（那是 paper/scheduler/pedagogy/route 的职责）。
- 不持久化画像、不做文件/网络 IO、不做时间戳以外的任何时间/随机行为。
- 不修改传入的 `bank`、`graph`、`responses`、`profile`（aggregate 为纯函数）。
- 不引入遗忘/时间衰减：掌握度只由作答证据与先序结构决定，与 `response_ms` 无关。
- 不校验图/题库的良构性（校验是 kpgraph/itembank 的职责）；遇到劣构输入时行为仍按 §3.2.3
  算法定义，但不承诺额外容错。

## 8. 验证记录（本规格的可复现性证据）

本规格定稿时执行了以下核查（命令均在仓库根目录，`PYTHONPATH=src`）：

1. 契约基线：`python -m pytest tests/contract/` → **47 passed**；
   `python -m pytest tests/contract/test_diagnosis_contract.py -v` → **10 passed**。
2. 独立引擎对拍：按本文 §3.2/§3.3 文本独立重写引擎（不 import 任何 `xuexing.diagnosis`
   函数；平滑遍历刻意用与 oracle 不同的 `kps()` 序），与参考实现在 **300 组随机良构图**上
   逐位比较 `mastery`（含键序）、`evidence`、聚合键序与值：**0 不匹配**（其中 242 组平滑
   真实触发）；"逐题舍入"变体在 235 组与 oracle 分歧，证实 D1 的可观测性。
   核查脚本：`_research_tmp/spec_review_v2.py`、`_research_tmp/spec_review_v3.py`。
3. 闭式手工复算与探针互证：折价复利（§3.2.3 C-e：单次 0.404362 ≠ oracle，复利 0.165722 ==
   oracle）、最弱前序主导（C-d：z 两轮 0.894737→0.388105→0.168346）、最强后代抬升
   （C-c：w=0.592993）、护栏分支（B2：0.506173/0.473684）、空作答先验舍入
   （D1：0.123456789→0.123457）、聚合键序（`["aa","zz"]`）、重复 kps 计证
   （`evidence==2`）。
