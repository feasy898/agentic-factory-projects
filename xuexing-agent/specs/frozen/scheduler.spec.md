# scheduler 模块规格（冻结契约 v1.0）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。

**范围说明**：scheduler 的契约测试在 `tests/contract/test_scheduler_pedagogy_contract.py`。
该文件同时覆盖 pedagogy 模块（`StrategyLibrary.select`/`strategies` 排序/`StrategyError`，
见该文件第 42–74 行）；pedagogy 部分不属于本规格，由 pedagogy 规格单独冻结。
本规格覆盖该测试文件中 scheduler 相关的全部断言（第 13–39 行，共 4 个测试）。
`tools/run_contract.py` 将 scheduler 与 pedagogy 映射到同一测试文件（`tools/run_contract.py:22-23`）。

**效力层级**：契约测试是行为 ground truth；测试未覆盖、但参考实现
（`src/xuexing/scheduler.py`）行为明确输入域，本文按参考实现冻结，并逐处标注
"（实测，测试不覆盖此域）"；两者冲突时以测试为准。

## 1. 目的

scheduler 是间隔重复调度器（SM-2 变体）：给定一个知识点的历史复习记录序列，
计算该知识点下次应当复习的日期（`due`）、本次成功间隔（`interval_days`）与当前难度系数
（`ease`）。行为契约：连续成功则间隔递增、遗忘则重置、同输入恒等输出。
升级为 FSRS 等其他算法时必须保持本契约不变（`src/xuexing/scheduler.py:1-4`）。

## 2. 允许的依赖

- Python 标准库（至少 `dataclasses`、`datetime.date`）
- `xuexing.types` —— **必须绝对导入**：`from xuexing.types import ReviewEntry`
- 禁止：其他 xuexing 模块（无例外）、第三方库、文件/网络 IO、隐藏随机与系统时钟

重生成实例的装载约束（经实验证实，`tests/contract/conftest.py:20-26`）：

- 注入模式下实现被以顶层模块名 `_regen_scheduler` 经 `spec_from_file_location` 装载，
  **相对导入 `from .types import ...` 会直接 `ImportError`**（实测：
  `python tools/run_contract.py --impl-dir <dir> --modules scheduler` 报
  "attempted relative import with no known parent package"）。
- **禁止 `from __future__ import annotations`**：注入装载时 dataclass 的字符串注解
  解析路径会访问 `sys.modules[cls.__module__]`（名为 `_regen_scheduler`，未注册），
  实测在 `exec_module` 处抛 `AttributeError: 'NoneType' object has no attribute '__dict__'`。
  去掉该 future 导入后，同一实现 7/7 通过。注解直接写成真实对象
  （`list[ReviewLog]`、`date` 等，Python ≥3.10 语法）。

## 3. 公开 API

模块必须暴露以下两个名字（契约测试 `from xuexing.scheduler import ReviewLog, schedule`，
`test_scheduler_pedagogy_contract.py:7`）。

### 3.1 `ReviewLog`

```python
@dataclass
class ReviewLog:
    rating: int            # 0=遗忘 1=勉强 2=良好 3=轻松
    days_since_last: int   # 距上次复习的天数；首次复习填 0
```

- 支持按位置构造 `ReviewLog(2, 0)`（测试全程如此使用）。
- 构造时不做任何校验。
- **`days_since_last` 不参与任何计算**，是纯记录字段。证据：
  - 实测 `[ReviewLog(2,0), ReviewLog(2,5)]` 与 `[ReviewLog(2,0), ReviewLog(2,999)]`
    的 `schedule` 输出相等；
  - 契约测试向它传入的是 `schedule(...).interval_days` 返回的 int（i1=2、i2=5、
    i3=12，`test_scheduler_pedagogy_contract.py:14-16`），无任何类型校验。

### 3.2 `schedule`

```python
def schedule(
    kp_id: str,
    history: list[ReviewLog],
    today: date,
    initial_interval: int = 1,
    initial_ease: float = 2.5,
) -> ReviewEntry:
    """根据复习历史给出下次复习日期。确定性：同输入恒等输出。"""
```

语义：按顺序重放 `history` 中每条记录的 `rating`，维护内部 `ease`（初值
`initial_ease`）与 `interval`（初值 `initial_interval`），返回下一次复习安排。

参数约束与校验（在任何重放之前执行，`history` 为空也执行）：

- **校验顺序固定**：先检查 `initial_interval`，后检查 `initial_ease`；两参数同时非法时
  抛出的是 interval 的 `ValueError`（实测 `initial_interval=0, initial_ease=9.9` →
  消息 `initial_interval out of [1, 365]`；测试不覆盖此域，按参考实现
  `scheduler.py:29-32` 冻结）。
- **范围判定语义固定为链式比较**：`initial_interval` 合法 ⇔ `1 <= initial_interval <= 365`
  整体为 True；`initial_ease` 合法 ⇔ `1.3 <= initial_ease <= 3.0` 整体为 True。
  因此 NaN（任何比较均为 False）与 ±inf 必须被拒绝、抛 `ValueError`
  （实测 `initial_ease=nan/inf`、`initial_interval=nan` 均 ValueError）。
  实现不得把判定改写为 `x < lo or x > hi` 之类的等价观感形式——那会放行 NaN。
- `initial_interval=1`、`365`、`initial_ease=1.3`、`3.0` 边界值均合法（实测）。
- `initial_interval` 通过范围校验的非有限数值已被上条拒绝；有限非整数（如 `2.5`）
  属契约外输入，行为不定义（实测参考实现在空 `history` 时抛 `TypeError`、
  有 `history` 时截断，属意外行为，不得依赖）。

重放规则（**运算顺序逐步冻结**，浮点结果要求跨实现逐位一致）：

1. `rating == 0`（遗忘）：`interval = initial_interval`（直接重置，**不做**乘法）；
   `ease = max(1.3, ease - 0.2)`。
2. `rating == 1`（勉强）：`ease = max(1.3, ease - 0.15)`；
   `interval = max(interval, initial_interval)`；
   然后 `interval = max(1, round(interval * ease))`（用更新后的 ease 与更新后的 interval）。
3. `rating == 2`（良好）：ease 不变；`interval = max(1, round(interval * ease))`。
4. **其余一律按"轻松"处理**：分支判定机制是依次做三个相等比较
   `rating == 0`、`rating == 1`、`rating == 2`，三者全部不成立即进入本分支——
   对任意类型的 rating 都成立（`None`、`"2"`、`nan`、任意对象与 int 比较均为 False），
   rating 上**没有类型校验**。本分支执行：
   `ease = min(3.0, ease + 0.15)`；`interval = max(1, round(interval * ease))`。
   （实测 rating=4、-1、2.5、None、`"2"`、nan、`object()` 全部得 interval=3、ease=2.65，
   不抛异常；测试只覆盖 0–3，其余按参考实现冻结。）
5. `round` 是 Python 3 内置 round（**银行家舍入，half-to-even**）：`round(2.5)=2`、
   `round(12.5)=12`，直接决定下方例 1 的 2 和 12，重生成必须一致。

返回值：

```python
ReviewEntry(
    kp_id=kp_id,                                  # 原样透传，不影响任何计算
    due=date.fromordinal(today.toordinal() + interval).isoformat(),  # ISO 日期字符串
    interval_days=int(interval),
    ease=round(ease, 4),                          # 最多 4 位小数
)
```

其他行为：`schedule` 不修改传入的 `history`（实测原列表不变）；对输出对象相等性使用
dataclass 逐字段相等（测试 `a == b`）。

**具体输入输出例子**（TODAY = `date(2026, 9, 28)`，均为实测值）：

例 1 —— 间隔增长与遗忘重置（对应 `test_interval_grows_then_lapse_resets`）：

| 输入 history | 输出 ReviewEntry |
|---|---|
| `[ReviewLog(2,0)]` | `kp_id="k", due="2026-09-30", interval_days=2, ease=2.5` |
| `[ReviewLog(2,0), ReviewLog(2,2)]` | `due="2026-10-03", interval_days=5, ease=2.5` |
| `[ReviewLog(2,0), ReviewLog(2,2), ReviewLog(2,5)]` | `due="2026-10-10", interval_days=12, ease=2.5` |
| `[ReviewLog(2,0), ReviewLog(2,2), ReviewLog(0,5)]` | `due="2026-09-29", interval_days=1, ease=2.3` |

（注意 `interval_days` 序列 2→5→12：`round(1*2.5)=2`（half-even），`round(2*2.5)=5`，
`round(5*2.5)=round(12.5)=12`（half-even）；遗忘一行 ease 从 2.5 降到 2.3，
interval 直接回到 initial_interval=1，不乘 ease。）

例 2 —— ease 随评分移动（对应 `test_ease_moves_with_rating`）：

| 输入 history | 输出 ReviewEntry |
|---|---|
| `[ReviewLog(3,0), ReviewLog(3,4)]` | `due="2026-10-06", interval_days=8, ease=2.8` |
| `[ReviewLog(1,0), ReviewLog(1,4)]` | `due="2026-10-02", interval_days=4, ease=2.2` |

且断言 `easy.ease > hard.ease`、`1.3 <= hard.ease <= 3.0`。

例 3 —— 空历史直通：`schedule("k", [], TODAY)` →
`interval_days=1, ease=2.5, due="2026-09-29"`；`schedule("k", [], TODAY,
initial_interval=7, initial_ease=2.0)` → `interval_days=7, ease=2.0, due="2026-10-05"`。

## 4. 不变量（编号列出，全部可被契约测试检验）

- I1 **间隔增长**：连续成功复习使间隔严格递增——默认参数下三次 `rating=2` 复习得到
  `1 <= i1 < i2 < i3`（实测 2 < 5 < 12；`test_interval_grows_then_lapse_resets:17`）。
- I2 **遗忘重置**：任一 `rating=0` 把 interval 直接重置为 `initial_interval`
  （不经乘法），并使 ease 恰好下降 0.2（下限 1.3）；故遗忘后
  `interval_days < 重置前路径的间隔`（测试 `lapsed.interval_days < i3`，第 19 行）。
- I3 **ease 移动规则**：`rating=1` 时 ease −0.15；`rating=2` 时不变；
  其余 rating 一律 +0.15。ease 每次更新后立即夹紧到 `[1.3, 3.0]`
  （实测连续遗忘序列 ease = 2.3, 2.1, 1.9, 1.7, 1.5, 1.3, 1.3…；
  连续轻松序列 = 2.65, 2.8, 2.95, 3.0, 3.0…）。
- I4 **值域**：输出恒满足 `1 <= interval_days`、`1.3 <= ease <= 3.0`
  （测试第 26、32 行）。
- I5 **due 一致性**：`due` 是 ISO 日期字符串且等于 `today + interval_days` 天；
  因 `interval_days >= 1`，恒有 `due > today.isoformat()`（按 ISO 字符串比较成立；
  测试第 32 行）。
- I6 **确定性**：`schedule` 是纯函数——同 `(kp_id, history 的 rating 序列, today,
  initial_interval, initial_ease)` 恒产生相等的 `ReviewEntry`（dataclass 相等；
  测试第 29-32 行）。无任何随机源。
- I7 **无关字段**：`kp_id` 只透传到输出；`days_since_last` 完全不影响输出（见 3.1）。
- I8 **输出精度**：`ease` 输出为 `round(ease, 4)`（≤4 位小数）；`interval_days` 为 int。
- I9 **无副作用**：不修改 `history`；无模块级可变状态。
- I10 **校验先于计算**：参数校验（§3.2）在重放任何 history 之前进行，空 history 也校验
  （测试第 36-39 行用空 history 触发 ValueError）。

## 5. 确定性与随机性

- `schedule` 必须同输入同输出（I6）：不允许任何 `random`、hash 种子、dict 迭代序等
  隐藏随机源；输出只依赖 §3.2 列出的输入。
- **禁止隐藏时间**：一切日期由入参 `today: date` 派生（`due` 是唯一日期输出）；
  不读系统时钟，输出中没有时间戳字段。
- 浮点可复现性：ease 的全部运算限定为 IEEE-754 双精度的
  `±0.15 / ±0.20` 与 `max/min` 夹紧，interval 为 `max(1, round(interval*ease))`，
  输出 ease 经 `round(…, 4)` 量化。重生成必须按 §3.2 的运算顺序执行，
  保证与参考实现逐位一致（例 1、例 2 的每个数值都是逐位比对点）。
- `round` 语义：Python 3 内置 round（half-to-even），不得替换为四舍五入。

## 6. 错误行为

非法/边界输入的完整行为表（"容忍"指不抛异常、按冻结语义处理）：

| 输入 | 行为 |
|---|---|
| `initial_interval` ∉ [1, 365]（含 0、负数、366、NaN、±inf） | **第一个**被检查的参数，在任何计算前抛 `ValueError`（实测消息 `initial_interval out of [1, 365]`；契约只测异常类型，`test_bad_params_rejected:35-39`） |
| `initial_ease` ∉ [1.3, 3.0]（含 1.29、3.01、9.9、NaN、±inf） | 在 interval 通过校验后、任何计算前抛 `ValueError`（实测消息 `initial_ease out of [1.3, 3.0]`）。NaN/±inf 因链式比较为 False 被拒绝（§3.2） |
| `initial_interval` 与 `initial_ease` 同时非法 | 抛 interval 的 `ValueError`——校验顺序固定为先 interval 后 ease（§3.2；实测两参数皆非法时报 `initial_interval out of [1, 365]`） |
| `initial_interval` 为通过校验的有限非整数（如 2.5） | 契约外输入，行为不定义（见 §3.2，不得依赖） |
| `history` 为空列表 | 不报错；等价于零次重放，直接返回初值直通（例 3） |
| `history` = None 或其他不可迭代对象 | 抛 `TypeError`（实测 `None` → `TypeError: 'NoneType' object is not iterable`；测试不覆盖此域，按参考实现冻结） |
| `history` 可迭代但元素无 `rating` 属性（如字符串列表） | 抛 `AttributeError`（实测 `history="ab"` → `AttributeError: 'str' object has no attribute 'rating'`；测试不覆盖此域，按参考实现冻结） |
| `ReviewLog.rating` 数值 ∈ {0,1,2} 之外（含 3 以外越界值、负数、其他数值） | **容忍**，按 `rating=3`（轻松）处理（§3.2 规则 4），不抛异常（实测 rating=4、-1、2.5） |
| `ReviewLog.rating` 为非数值任意对象（None、字符串、NaN、任意对象） | **容忍**，同样落入轻松分支——分支判定只依赖三个相等比较全为 False，无类型校验（§3.2 规则 4；实测 None/`"2"`/nan/`object()` 均得 interval=3、ease=2.65。测试不覆盖此域，按参考实现冻结，实现不得在此域改为抛错） |
| `ReviewLog.days_since_last` 为任意值/任意类型 | 容忍，忽略（I7；测试传 int，实测任意值不影响输出） |
| `today` = None 或无 `toordinal` 属性的对象 | 抛 `AttributeError`（实测 None 与字符串均 → `AttributeError: ... has no attribute 'toordinal'`；测试不覆盖此域，按参考实现冻结） |

异常类型总结：契约内输入只有参数校验会抛异常，类型一律 `ValueError`；
`schedule` 对契约内输入不抛出参数校验之外的任何异常。

## 7. 非目标

- **不是复习队列管理器**：不做多知识点排队、每日配额、优先级排序——那是 route /
  agent_shell 的职责。`schedule` 一次只处理一个知识点。
- **不持久化**：不读写文件/数据库/网络；复习历史由调用方持有并传入。
- **不校验或解释 history 语义**：不检查间隔是否与 `days_since_last` 一致，
  不假设 `history` 按时间排序（只按列表顺序重放 rating），不对 `ReviewLog`
  字段做类型校验。
- **不生成学习计划**：不产出 `PlanStep`/`LearningPlan`（types.py 中二者归 route 使用）。
- **不本地化日期格式**：`due` 恒为 `date.isoformat()` 的 `YYYY-MM-DD`，无时区处理。
- **不引入 FSRS 或其他算法**：参考实现注释提到可替换为 FSRS（`scheduler.py:3`），
  但那是未来升级路径；本契约期内算法行为必须与 §3.2 逐步一致。
- **不新增公开 API**：模块公开面只有 `ReviewLog` 与 `schedule`；
  `ReviewEntry` 从 `xuexing.types` 导入，不在本模块定义。

## 附录 A：修订记录

v1.0（自 specs/drafts/scheduler.spec.md 冻结），对齐对抗评审 4 条意见：

1. **rating 非数值域二义性消除**：原 §3.2 规则 4"一切非 0/1/2 值按轻松处理"与原 §6
   "rating 为 None/非数值 → 行为不定义"字面冲突。定稿：规则 4 明确判定机制为三个
   相等比较全 False 即入轻松分支、无类型校验，§6 对应行改为"容忍"
   （实测 oracle 对 None/`"2"`/nan/`object()` 均按轻松处理且不抛错）。
2. **校验顺序冻结**：明确先 `initial_interval` 后 `initial_ease`（实测双参数皆非法时
   抛 interval 错误；对应 `scheduler.py:29-32` 的检查顺序）。
3. **引证更正**：§3.1 原称"测试把 ReviewEntry 对象传入 days_since_last"失实——
   测试传入的是 `schedule(...).interval_days` 返回的 int（test:14-16）。
   结论（纯记录字段、I7）不变，证据改为 int 传参 + 实测 5/999 输出相等。
4. **跨类型输入域穷尽**：§6 补齐 `history=None`（TypeError）、history 元素无 rating
   （AttributeError）、`today` 非 date（AttributeError）、`initial_ease`/`initial_interval`
   为 NaN/±inf（ValueError，并冻结链式比较判定语义，禁止改写为会放行 NaN 的形式）。
   以上均为参考实现实测行为、测试不覆盖，按"参考实现明确则冻结"原则写入。
