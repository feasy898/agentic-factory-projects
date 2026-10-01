# pedagogy 模块规格（冻结契约 v1.0）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> 范围说明：契约文件 `tests/contract/test_scheduler_pedagogy_contract.py` 同时覆盖 scheduler 与
> pedagogy。本规格只约束 pedagogy 部分（`test_strategy_band_selection`、
> `test_strategy_fallback_covers_band_holes`、`test_strategy_priority_ordering` 及其 `_library`
> 夹具）；该文件中 4 个 scheduler 测试属 scheduler 规格，与本模块无关。
>
> 依据标注：标【契约】的行为由契约测试断言；标【参考实现】的行为来自
> `src/xuexing/pedagogy.py` 并已在定稿会话实际运行验证，但契约测试未覆盖——它们同样冻结，
> 重生成实现必须满足。

## 1. 目的

把学习科学的循证结论（提取练习、样例学习、交错练习等）编码为带优先级与适用条件的
策略注册表：`StrategyLibrary` 存储策略、按 `(-priority, id)` 给出全序，并在给定
（掌握度, 年级）时选出**唯一一个**适用策略；`load_strategies` 从 JSON 文件装载该注册表。
策略选择是 `route` 模块生成 `LearningPlan` 的输入（`src/xuexing/route.py:21,55-66`），
本模块本身不生成任何计划。

## 2. 允许的依赖

- Python 标准库（参考实现仅用到 `json`）
- `xuexing.types`（绝对导入：`from xuexing.types import Strategy`）
- 禁止：其他 xuexing 模块（无例外，参考实现也不 import 任何兄弟模块）、第三方库
- 文件 IO：仅 `load_strategies` 允许读一个 JSON 文件；其余 API 禁止任何文件/网络 IO
- 重生成实例还必须满足注入环境约束（`tests/contract/conftest.py:1-5`）：单文件
  `<impl_dir>/pedagogy.py`、顶层暴露模块全部公开 API。参考实现用相对导入
  （`pedagogy.py:10`）是包内运行的特权；重生成实例必须用绝对导入。

## 3. 公开 API

策略数据结构即 `xuexing.types.Strategy`（`src/xuexing/types.py:73-85`），本模块**不得**
重新定义。字段与默认值：`id/name/description` 必填；`priority=0`、`evidence=""`、
`effect_size=None`、`mastery_lt=None`、`mastery_gte=None`、`grade_max=None`、
`grade_min=None`。条件字段语义见 I2。

### 3.1 `class StrategyError(ValueError)`

本模块唯一异常类型，必须继承 `ValueError`【参考实现 pedagogy.py:13；契约测试仅按
`StrategyError` 名字捕获，子类关系已在定稿会话运行验证：`issubclass(StrategyError,
ValueError) is True`】。

### 3.2 `class StrategyLibrary`

无参构造 `StrategyLibrary()`，初始为空库。

- `add(s: Strategy) -> None`：按引用注册策略。若 `s.id` 与任一已注册策略的 id 相等，
  抛 `StrategyError`，且库内容保持不变（失败调用不得覆盖已有条目）
  【参考实现 pedagogy.py:21-24，已运行验证：重复 add 抛 `StrategyError`；契约测试未覆盖】。
- `get(sid: str) -> Strategy | None`：命中返回**注册时的同一对象**（`is` 相等），
  未命中返回 `None`【参考实现 pedagogy.py:26-27，已运行验证；契约测试未覆盖】。
- `strategies() -> list[Strategy]`：返回包含库内全部策略、每个恰好一次的新建 list，
  顺序为 `(-priority, id)` 字典序（见 I4）。每次调用返回新 list，修改返回值不影响库
  【参考实现 pedagogy.py:29-30，已运行验证；契约测试覆盖排序（见 I4）】。
- `select(mastery: float, grade: int) -> Strategy`：按 I1–I3 选择。**返回库内注册的
  同一 Strategy 对象**——与传给 `add` 的对象 `is` 相等，不得构造副本或新建等值对象
  【参考实现 pedagogy.py:46 `return s`，已运行验证：`lib.select(...) is s == True`；
  契约测试只能观测 `.id`（`test_scheduler_pedagogy_contract.py:54-59`），对象同一性按
  参考实现冻结】。`mastery`/`grade` 只做数值比较，不做 [0,1]/年级域校验、不 clamp、
  不抛域错误【参考实现 pedagogy.py:37-47 无任何校验；契约测试未覆盖，见 §7 非目标】。

### 3.3 `load_strategies(path: str) -> StrategyLibrary`

读取 `path` 的 JSON 文件（UTF-8），期望顶层对象含键 `"strategies"`（条目列表），
对每条按 `add` 语义注册后返回库【参考实现 pedagogy.py:50-69】。

**输入形态规则**（全部【参考实现】，已在定稿会话对每种形态实际运行验证）：

- 顶层必须是 JSON 对象且含键 `"strategies"`；顶层非对象（如数组）→ 抛 `TypeError`
  （运行验证：`[1,2,3]` → `TypeError: list indices must be integers or slices, not str`）。
- `"strategies"` 的值必须是 JSON 对象（dict）的**列表**；值不是列表（如 `5`、`"abc"`）
  → 抛 `TypeError`（运行验证：`5` → `'int' object is not iterable`；`"abc"` →
  `string indices must be integers, not 'str'`）。
- 每个条目必须是 JSON 对象；条目为字符串、数组、`null` 等 → 抛 `TypeError`
  （运行验证：`"a"` → `string indices must be integers, not 'str'`；`[1,2]` →
  `list indices must be integers or slices, not str`；`null` →
  `'NoneType' object is not subscriptable`）。
- **条目中的未知键必须忽略**：实现按下方字段映射表逐键提取，不得以
  `Strategy(**entry)` 整体透传（否则未知键会变成 `TypeError`）。运行验证：含
  `"bogus": 123` 键的条目正常装载为 `id="x"` 的策略。
- 禁止宽松容错：遇到形态违规必须抛上述异常，**不得跳过非法条目继续装载**。

**字段映射表**（条目为对象时）：

| JSON 键 | 必需？ | 映射 |
|---|---|---|
| `id`、`name` | 必需 | 原样；缺失 → `KeyError`（运行验证：缺 `name` → `KeyError: 'name'`） |
| `description` | 可选 | 缺省 `""` |
| `priority` | 可选 | 缺省 `0`，经 `int()` 强转 |
| `evidence` | 可选 | 缺省 `""` |
| `effect_size`、`mastery_lt`、`mastery_gte`、`grade_max`、`grade_min` | 可选 | 缺省 `None` |

同一文件内出现重复 `id` → 经 `add` 抛 `StrategyError`（运行验证：
`StrategyError: duplicate strategy id: x`）。以上均为【参考实现】，契约测试未覆盖。
`data/pedagogy/strategies.json` 是合法样例（已运行 `load_strategies` 验证：装载后
`strategies()` ids 依次为 `s_gamified, s_worked_example, s_retrieval, s_interleave,
s_guided_practice`）。

### 3.4 具体输入输出例子（摘自契约测试）

例 1（band 选择 + 优先级胜出，`test_strategy_band_selection`：43-59）——库为
`_library()` 五策略：`low(priority=10, mastery_lt=0.4)`、`mid(priority=8,
mastery_gte=0.4, mastery_lt=0.65)`、`high(priority=6, mastery_gte=0.65)`、
`young(priority=12, mastery_lt=0.5, grade_max=6)`、`fallback(priority=1)`：

```
select(0.2, 4).id == "young"   # young 优先级最高(12)，0.2<0.5 且 4<=6，压过 low(10)
select(0.8, 4).id == "high"    # young 因 0.8>=0.5 出局；high 无年级条件，接管
select(0.2, 9).id == "low"     # young 因 9>6 出局；low 无年级条件，接管
```

例 2（band 空档由兜底接管 + 空库报错，`test_strategy_fallback_covers_band_holes`：62-69）
——库仅含 `low(mastery_lt=0.4, priority=10)`、`high(mastery_gte=0.65, priority=6)`、
`fallback(priority=1)`：

```
select(0.5, 7).id == "fallback"    # 0.4<=0.5<0.65 是空档，两条件策略都不匹配，兜底接管
StrategyLibrary().select(0.5, 7)   # 空库 -> 抛 StrategyError
```

例 3（全序，`test_strategy_priority_ordering`：72-74）——对例 1 的库，契约断言的**原文
形式是相对次序**（用 `list.index` 两两比较）：

```
ids = [s.id for s in lib.strategies()]
ids.index("young") < ids.index("low") < ids.index("mid") < ids.index("high") < ids.index("fallback")
```

在该库（无同优先级策略）下，I4 的排序键 `(-priority, id)` 进一步给出完整序列
`["young", "low", "mid", "high", "fallback"]`（优先级依次 12, 10, 8, 6, 1）。注意：
契约测试只断言相对次序；完整序列相等是本规格 I4 + 参考实现排序键的冻结要求，超出
契约断言的强度。

## 4. 不变量（编号列出，全部可被契约测试检验）

- I1（优先级扫描，首个命中胜出）`select(mastery, grade)` 按 `strategies()` 的顺序
  （priority 降序）逐个检验适用条件，返回**第一个**条件全部满足的策略，随后立即停止，
  不再扫描。【契约：`test_strategy_band_selection`、`test_strategy_priority_ordering`】
- I2（条件语义）四个条件字段的匹配规则：`mastery_lt` ⇒ 要求 `mastery < mastery_lt`；
  `mastery_gte` ⇒ 要求 `mastery >= mastery_gte`；`grade_max` ⇒ 要求 `grade <= grade_max`；
  `grade_min` ⇒ 要求 `grade >= grade_min`；取值为 `None` 的字段不施加任何约束。
  【契约（不等式方向）：0.2 匹配 `mastery_lt=0.4`、0.8 匹配 `mastery_gte=0.65`、grade 9
  被上限 6 排除、全 `None` 的 fallback 匹配一切。】
  **等值边界**（`mastery == mastery_lt` 不匹配；`mastery_gte`/`grade_min`/`grade_max`
  含等号，`==` 匹配）【参考实现 pedagogy.py:38-45，已运行验证】：
  契约测试**未钉死**等值边界——定稿会话以变异实验证实：把参考实现的四处比较全部翻转
  （`mastery_lt: < → <=`、`mastery_gte: >= → >`、`grade_max: <= → <`、`grade_min: >= → >`，
  其余逐字不变）后，`XX_IMPL_DIR=<变异体> XX_MODULES=pedagogy python -m pytest
  tests/contract/test_scheduler_pedagogy_contract.py` 仍 **7 passed**。注意
  `select(0.5, 7) == "mid"`（test:55）并**不能**钉死 `mastery_lt` 的严格性：候选
  `young` 虽有 `mastery_lt=0.5`，但同一调用 `grade=7 > grade_max=6`（test:47），
  无论 `<` 还是 `<=`，young 都先被年级门排除，仍返回 `"mid"`（已在变异体上运行复核：
  `select(0.5, 7) = mid`；变异只在契约未测的输入上可见，如变异体 `select(0.5, 4) = young`
  而参考实现为 `"mid"`）。因此等值边界由本规格 + 参考实现约束，重生成实现必须照此实现。
- I3（无匹配必须报错）若没有任何策略通过全部条件检验（包括库为空的情形），
  `select` 抛 `StrategyError`。【契约：`test_strategy_fallback_covers_band_holes:68-69`】
- I4（strategies 全序）`strategies()` 返回库内全部策略、每个恰好一次，顺序为
  `(-priority, id)`：priority 降序，同分按 id 升序；调用前后库内容不变。【契约：
  `test_strategy_priority_ordering`（相对次序断言，见例 3）；id 同分决胜为参考实现
  pedagogy.py:30 排序键（已运行验证：同优先级 b/a/c 输出 a/b/c），契约测试只覆盖
  异优先级情形】
- I5（兜底穿透）某策略条件不满足时，`select` 继续按 I1 向下扫描：适用条件的空档区间
  必须由更低优先级的匹配策略（兜底）接管，而不是报错、也不是取"条件最接近"的策略。
  【契约：`test_strategy_fallback_covers_band_holes:67`】

## 5. 确定性与随机性

- 全模块**禁止**任何随机源、时钟读取与环境/全局可变状态依赖。允许的依赖里没有
  `random`/`time`/`datetime`。
- `add`/`get`/`strategies`/`select` 是纯内存操作：同一库状态与同一实参下，重复调用
  必须产出相同结果——`select` 每次返回**同一个注册对象**（`is` 相等，见 §3.2）；
  `strategies()` 返回相同顺序的新 list。
- 库的可见内容只由 `add` 的调用序列决定；`strategies()` 的输出顺序与插入顺序无关
  （由 I4 排序键决定）。
- `load_strategies` 只读文件：同一文件内容必装载出行为等价的库。除该函数外无任何 IO。
- 本模块不生成、不修改任何时间戳字段（`Strategy` 无时间字段；`LearningPlan.created_at`
  等是其他模块的职责）。

## 6. 错误行为

| 非法输入 | 必须的行为 | 依据 |
|---|---|---|
| `select` 无任何匹配策略 | 抛 `StrategyError` | 【契约】I3 |
| `select` 作用于空库 | 抛 `StrategyError` | 【契约】I3 |
| `add` 重复 `id` | 抛 `StrategyError`，库内容不变 | 【参考实现 pedagogy.py:22-23】 |
| `load_strategies` 文件不存在 | 抛 `FileNotFoundError`（`OSError` 子类，不吞不换） | 【参考实现】 |
| `load_strategies` 非法 JSON | 抛 `json.JSONDecodeError` | 【参考实现】 |
| `load_strategies` 顶层非对象、`"strategies"` 非列表、条目非对象 | 抛 `TypeError`（六种形态已逐一运行验证，见 §3.3） | 【参考实现】 |
| `load_strategies` 顶层缺 `"strategies"` 键、条目缺 `id`/`name` | 抛 `KeyError` | 【参考实现】 |
| `load_strategies` 条目 `priority` 不可转 int | 按 `int()` 原生异常（`ValueError`/`TypeError`） | 【参考实现】 |
| `load_strategies` 条目含未知键 | 不是错误：忽略该键，按字段映射表装载 | 【参考实现，已运行验证】 |

必须容忍（不得报错）的输入：

- 条件字段为 `None`（= 不约束）；`description`/`evidence` 为空串。
- `mastery` 超出 [0,1] 或 `grade` 超出常规年级范围：只按数值比较走匹配逻辑，
  不做域校验、不 clamp。
- `StrategyError` 是 `ValueError` 子类，调用方以 `except ValueError` 捕获亦须生效。

## 7. 非目标

- 不做 `mastery`/`grade` 的域校验、clamp 或类型转换（§6 只要求数值可比较时的行为）。
- 不生成 `LearningPlan`/`PlanStep`/`ReviewEntry`，不做学情诊断——策略到计划步骤的
  组合是 `route` 模块职责（`route.py:55-66`）。
- 不实现间隔重复/FSRS 算法——那是 `scheduler` 模块；同契约文件中 4 个 scheduler
  测试不在本规格范围（见文首范围说明）。
- 不返回多策略、不打分排序：`select` 恰好返回一个策略对象；`effect_size`/`evidence`
  是纯元数据，**不参与**选择逻辑。
- 不持久化库状态、无缓存、无日志、无网络；除 `load_strategies` 外无文件 IO。
- 不校验或改写传入 `Strategy` 的其余字段（如 `name` 是否为空）。
- `load_strategies` 不做宽松容错（跳过非法条目、忽略缺失键并填默认对象等）：
  §3.3/§6 规定的异常必须原样抛出。

## 8. 修订记录

- v0（2026-09-29，`specs/drafts/pedagogy.spec.md`）：依据契约测试 + 参考实现起草。
- v1.0（2026-09-29，本文件）：对抗评审 4 条逐条处理后定稿。
  1.（major）`load_strategies` 未定义形态 → 已冻结：未知键忽略、顶层/值/条目形态违规
     抛 `TypeError`、禁止跳过非法条目（§3.3、§6、§7）；六种形态 + 未知键 + 缺
     `name` + 文件内重复 id 共九种输入已逐一运行验证，输出记录于 §3.3。
  2.（minor）`select` 同一性含糊 → 已冻结：返回注册对象本身（`is` 相等，不得副本），
     §3.2/§5 修改；已运行验证 `lib.select(...) is s == True`。
  3.（minor）例 3 引用失实 → 已改为契约断言的原文形式（`.index()` 相对次序，
     `test_strategy_priority_ordering:73-74`），并注明完整序列相等是 I4 冻结、超出
     契约断言强度（§3.4 例 3）。行为本身无分歧。
  4.（minor）I2 等值边界覆盖声明被质疑 → 经变异实验裁决，原声明**成立**：四处边界
     比较全部翻转后契约套件仍 7 passed；评审者反例（young 在 `select(0.5,7)` 以
     `<=` 胜出）不成立，因 young 的 `grade_max=6` 先被 `grade=7` 排除（test:47 vs
     test:55），已在变异体上运行复核 `select(0.5, 7) = mid`。I2 已补记全部证据。
