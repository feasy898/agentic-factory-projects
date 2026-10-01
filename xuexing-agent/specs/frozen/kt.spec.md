# kt 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> **版本**：定稿 v1（由 drafts 版经对抗评审修复而来，修复记录见附录 A）。
> 标注「〔测试裁定〕」的行为由 tests/contract/test_kt_contract.py（22 项）直接断言；
> 标注「〔参考裁定〕」的行为契约测试未仲裁，按参考实现 `src/xuexing/kt.py` 冻结并在当地
> 注明实测证据。本文自包含：不引用仓库内其他规格文档；全部公式、常量、管线顺序在本文内
> 完整定义。
>
> 冻结基线：参考实现 + 契约测试全量实测于 2026-09-29，CPython 3.12.10 x64
> （`python -m pytest tests/contract/test_kt_contract.py -q` → 22 passed）。

## 1. 目的

kt 是同一学习者跨多次会话的掌握度轨迹追踪器（KT 时序追踪）：把带时间戳的作答事件流
按顺序折叠成一条逐事件的掌握度轨迹——每走到一个新事件，先对所有有直接证据的知识点施加
遗忘曲线衰减（指数半衰期），再按猜测感知 odds 贝叶斯更新写入新证据（公式在 §3.3 完整
定义，本模块不 import 任何其他引擎）。行为契约：**轨迹可重放**（前缀重放逐位复现）、
**可解释**（无新证据时掌握度单调下降、证据方向可解释、闭式数值可手算复核）、**同输入
同输出**。并提供 XES3G5M（pyKT-CSV）序列行到事件流的确定性适配器作为数据基础。

## 2. 允许的依赖与装载约束

- Python 标准库（至少 `dataclasses`、`csv`、`re`、`datetime`）
- `xuexing.types` —— **必须绝对导入**：`from xuexing.types import Profile`
- 禁止：其他 xuexing 模块（**无例外**——不 import 任何诊断/调度引擎；证据强度语义在
  本模块内以本规格 §3.3 的常量与公式自足定义）、第三方库
- 文件 IO 仅允许 `load_xes3g5m_csv`（只读，路径来自入参）；其余 API 禁止任何 IO
- 禁止：隐藏随机、系统时钟（`to_profile` 的 `Profile.updated_at` 是唯一时间戳字段，豁免）
- 注入对象只按成员调用（鸭子类型，不 import 其定义模块）：
  - `bank.get(item_id) -> Item | None`
  - `graph.kps() -> list[KnowledgePoint]`（mastery/evidence 的键与键序基准）
  - `graph.has(kp_id) -> bool`
  - item 上只读 `Item.effective_guess() -> float`、`Item.difficulty`、`Item.kps`

重生成实例的装载约束（自包含实测，2026-09-29，CPython 3.12.10；注入机制：
`tests/conftest.py:22-34` 以顶层模块名 `_regen_kt` 经 `spec_from_file_location` 装载
`<impl_dir>/kt.py` 并顶替 `sys.modules["xuexing.kt"]`）：

- **禁止相对导入**（`from .types import ...`）：实测在 `exec_module` 处抛
  `ImportError: attempted relative import with no known parent package`。
- **禁止 `from __future__ import annotations`**：实测在 dataclass 处理阶段抛
  `AttributeError: 'NoneType' object has no attribute '__dict__'`——CPython 3.12.10
  `dataclasses.py:983`（`_process_class` → `_is_type`）按 `sys.modules.get(cls.__module__)`
  解析字符串注解，注入模块注册名是 `xuexing.kt` 而 dataclass 的 `__module__` 是
  `_regen_kt`，`.get` 得 `None`。注解直接写真实对象（`list[KTEvent]`、`dict[str, float]`）。
- **绝对导入 + 真实对象注解实测可装载**：含全部 6 个公开名字的模块经注入门装载后
  契约测试可正常运行。

## 3. 公开 API

模块必须暴露以下 6 个名字（契约测试
`from xuexing.kt import KTEvent, KTSnapshot, trace, to_profile, xes3g5m_row, load_xes3g5m_csv`）。

### 3.1 `KTEvent`

```python
@dataclass
class KTEvent:
    item_id: str
    correct: bool
    day: float     # 相对轨迹起点的天数；非负；沿列表非降
```

- 支持按位置构造 `KTEvent("a2", True, 0.0)`；构造时不校验（全部校验在 `trace` 内，
  见 §3.3-A）。〔测试裁定：全部测试按位置构造非法值（如 `day=-1.0`、`day="3"`），
  异常都发生在 `trace` 调用〕
- `day` 是唯一的输入时间量纲（天）；不绑定绝对时钟——调用方自选起点（XES3G5M 适配取
  掩码保留位首个时间戳为 day 0，见 §3.5），这是模块确定性的来源。

### 3.2 `KTSnapshot`

```python
@dataclass
class KTSnapshot:
    day: float                    # 本事件 day 的 float 化值（透传）
    item_id: str                  # 触发本快照的事件题 id
    correct: bool
    mastery: dict[str, float]     # 全部图内知识点的掌握度，round 到 6 位
    evidence: dict[str, int]      # 全部图内知识点的直接证据计数
```

- dataclass 逐字段相等（`a == b`）是确定性判定方式（轨迹比较即列表相等）。〔测试裁定〕
- `mastery`/`evidence` 的键集恰为图内知识点全集，键序与 `graph.kps()` 一致；
  每个快照持有**独立的新 dict**（改快照 i 的 dict 不影响快照 j）。〔参考裁定〕
- `day` 是校验时 `float` 化后的本事件 day 值：int 入参转 float（实测
  `KTEvent("a2", True, 3)` → `snapshot.day == 3.0`，类型 float）。〔参考裁定〕

### 3.3 `trace`

```python
def trace(events: list[KTEvent], bank, graph,
          prior: float = 0.5, half_life_days: float = 7.0) -> list[KTSnapshot]
```

`bank` 只用到 `bank.get(item_id) -> Item | None`；`graph` 只用到 `graph.kps()`（键序
基准）与 `graph.has(kp_id) -> bool`。

计算步骤（顺序为绑定条款）：

**A. 校验先于任何其他工作（空 `events` 也必须执行）：**

1. `prior` 域校验。语义为「`0.0 < prior < 1.0`」链式比较的求值结果（**无类型预检**，
   参考裁定）：
   - 数字 ∉ 开区间 (0,1)（含 0、1、负、>1）→ `ValueError`。〔测试裁定〕
   - `bool` 按数值含义参与比较：`prior=True`（≡1.0）、`prior=False`（≡0.0）均落入
     区间拒绝支 → `ValueError`。〔参考裁定〕
   - 与 float 不可比较的类型（实测 `str`、`None`、`list`、`dict`）→ **`TypeError`**——
     本规格唯一的非 ValueError 异常（§6）。〔参考裁定〕
   - 可与 float 比较的数值类型且在 (0,1) 内（实测 `Decimal("0.5")`）→ 接受。
     〔参考裁定〕
2. `half_life_days` 必须为数字（int/float，bool 除外）且 `> 0`，否则 `ValueError`
   （NaN 经「任何链式比较均为 False」落入拒绝支；int 实测合法）。〔测试裁定
   0.0/-1.0/NaN；参考裁定 "7"/None/True 拒绝、int 7 接受〕
3. 逐事件校验 `day`：数字（int/float，bool 除外）否则 `ValueError`；
   `not (day >= 0.0)` 为真（含 NaN）否则 `ValueError`；沿列表顺序非降（严格下降抛
   `ValueError`；相等合法，Δ=0 衰减因子为 1）。〔测试裁定〕

**B. 逐有效事件（先遗忘、后证据）：**

- B1 **遗忘**：Δ = 本事件 day − 上一个**有效**事件的 day；首个有效事件不做衰减
  （Δ 视为 0，且起步 day 再大也不衰减——实测 `a2✓@100` 单事件仍得 0.894737）。
  对所有 `evidence > 0` 的知识点 `m ← m · 0.5^(Δ/H)`（H = half_life_days），无证据者
  保持 `prior` 不变。衰减作用于**全部**有直接证据的知识点，不区分证据正负（负证据的
  掌握度同样向下衰减：保守方向——不会把弱点淡忘成「未测」）。衰减不消耗证据计数。
  〔测试裁定 test_decay_exactly_halves_at_half_life 等〕
- B2 **证据**：`bank.get(item_id)` 查不到则**整条事件跳过**（不产生快照、不推进衰减
  时钟——插入 ghost 事件不改变轨迹）。〔测试裁定 test_unknown_item_dropped_and_clock_untouched〕
  否则按以下次序执行：
  - 单题似然比（每事件一次，与当前掌握度无关）：
    - `p_nm = max(item.effective_guess(), 0.02)`（猜测率下限 0.02；实测
      `guess=0.0` 的 fill 难 0.5 题 → `lr_c = 0.85/0.02 = 42.5` → 掌握度 0.977011）
    - `slip = clamp01(0.05 + 0.20 * item.difficulty)`；`p_m = 1 − slip`（经 clamp01）
    - 高猜度护栏：若 `p_m <= p_nm` 则 `p_m = min(p_m + 0.05, 0.99)`（实测封顶支：
      `difficulty=0.0, guess=0.98` → `p_m=0.95 → 0.99`，`lr_c = 0.99/0.98` → 0.502538）
    - `lr_c = p_m / p_nm`；`lr_w = (1 − p_m) / max(1 − p_nm, 1e-4)`
  - `lr = lr_c if correct else lr_w`，对 `enumerate(item.kps)` 中每个 `(idx, kp_id)`
    按**声明顺序**处理（**允许重复 id；不去重，重复按出现次数分别处理**——每次出现
    独立走一遍下列更新，第一次的输出作为第二次的输入；权重仍按各自声明位次）：
    - `graph.has(kp_id)` 为假 → 仅跳过该知识点（同题其余知识点照常更新；**位次
      不重排**——`["zz","a"]` 中 `"a"` 的 idx 仍是 1，拿 w=0.5，实测 0.744603；
      全部图外（`["zz"]`）时快照照发、不发生任何更新）；
    - `w = 1.0 if idx == 0 else 0.5`；
    - `lr_eff = lr ** w`（当 `lr >= 1`）否则 `max(lr ** w, 1e-4)`；
    - `odds = max(m, 1e-4) / max(1 − m, 1e-4)`；`odds *= lr_eff`；
      `m = clamp01(odds / (1 + odds))`；
    - `evidence[kp_id] += 1`（每次出现各计一次，与对错、主/次无关）。

  重复 kps 的逐位比对点〔参考裁定，测试不覆盖此域〕：fill 难 0.5（lr_c=8.5），
  prior=0.5，单事件——`kps=["a","a"]` 答对 → `mastery=0.961213`、`evidence=2`
  （8.5 → 8.5×√8.5 的链式双更新）；答错 → `0.063707`、`evidence=2`；
  `kps=["a","a","a"]` 答对 → `0.986348`、`evidence=3`（= lr^(1+0.5+0.5) = lr²）。

  odds 下限的实际后果〔参考裁定〕：同日连对 30 次最易题（difficulty=0.0，fill）→
  `0.999989`（内部 m 触达 1.0 后由分母下限 1e-4 重入：odds = 1.0/1e-4 = 10⁴）；
  随后答错一次 → `0.998203`，不塌 0（下限保证饱和态可恢复）。
- B3 **快照**：每处理完一个有效事件输出一个快照；**输出值一次性 round(·, 6)**
  （Python 3 内置 round，银行家舍入），内部状态全程不舍入（这是前缀重放逐位一致的
  前提）；`mastery`/`evidence` 均为该快照的新拷贝，键序随 `graph.kps()`。

**C. 返回**：快照列表；`len(轨迹) == 有效事件数`（`item_id` 能在 bank 查到的事件数）。

**闭式例子**（fixtures：a2=fill 难0.5（lr_c=8.5, lr_w=1/6）、b1=fill 难0.3（lr_c=8.9）、
d1=choice 猜0.25（lr_c=3.4）、d2=fill 难0.5（lr_c=8.5）；prior=0.5，H=7。
全部数值为测试逐位断言值）〔测试裁定〕：

| events | 轨迹值（实测） |
|---|---|
| `[a2✓@0]` | a = 0.894737（17/19），b=c=d=0.5 |
| `[a2✓@0, a2✗@7]` | a: 0.894737 → 0.118881（衰减 17/38，答错 odds=17/21×1/6 → 17/143） |
| `[a2✓@0, b1✓@7]` | a = 0.447368（恰为证据时刻一半），b = 0.898990（8.9/9.9） |
| `[a2✓@0, a2✓@7]` | a = 0.873112（odds=17/21×8.5=289/42 → 289/331） |
| `[a2✓@0, a2✓@0]` | a = 0.986348（同日 Δ=0，odds=8.5² → 289/293） |
| `[d1✓@0]` | d = 0.772727（17/22）；`[d2✓@0]` → d = 0.894737 |
| `[a2✓@0, b1✓@3, b1✓@10]` | a: 0.894737 → 0.664787 → 0.332393（严格递减，evidence 恒 1） |
| `[ab1✓@0]`（kps=["a","b"]） | a = 0.894737（主，w=1.0），b = 0.744603（次，w=0.5） |

非默认 prior 的逐位比对点〔参考裁定，契约测试全部用默认 prior=0.5，此例供重生成
自检〕：`prior=0.3`，`[a2✓@0, b1✓@7]` → a: `0.784615`（odds=3/7×8.5=51/14 → 51/65）
→ `0.392308`（51/130）；b: `0.3` → `0.792285`（odds=3/7×8.9=26.7/7）；c/d 全程 `0.3`。

### 3.4 `to_profile`

```python
def to_profile(snapshot: KTSnapshot, learner_id: str) -> Profile
```

- `mastery`/`evidence` 与快照逐字段一致且为**拷贝**（改动 Profile 不影响快照，
  test_to_profile 断言）；`learner_id` 透传；`updated_at` 取当前 UTC，格式
  `%Y-%m-%dT%H:%M:%SZ`（实测匹配 `YYYY-MM-DDTHH:MM:SSZ`），是唯一豁免字段。
- 用途：把轨迹末状态交给 route/scheduler 等模块；`Profile.confidence` 语义由
  `xuexing.types` 决定（`n/(n+3.0)`，n=evidence；实测 evidence=2 → 0.4）。

### 3.5 `xes3g5m_row` / `load_xes3g5m_csv`

XES3G5M 官方发行版（ai4ed/XES3G5M，NeurIPS 2023 D&B）为 pyKT 风格 CSV 序列：
列 `fold, uid, questions, concepts, responses, timestamps, selectmasks, is_repeat`，
序列填充到 200，`selectmasks="-1"` 标记填充/忽略位，`timestamps` 毫秒级。

```python
def xes3g5m_row(row: dict) -> tuple[str, list[KTEvent]]
def load_xes3g5m_csv(path: str) -> list[tuple[str, list[KTEvent]]]
```

**token 化（共用定义）**：单元格值 `None` → 空 token 序列；其余值先经 `str()` 规范化
再扫描，**每个 token 是「空白或逗号以外字符」的极大连续段**（按出现顺序；空白含空格、
制表、换行）。语义后果（〔测试裁定〕纯空格/纯逗号两形态等价；〔参考裁定〕其余为实测）：
`"101, 102, 103"` → `["101","102","103"]`（**无**带前导空格的 token）；尾随/前导/连续
分隔符不产生空 token（实测 `"101,102,103,"` → 3 个 token）；制表/换行可作分隔符
（实测 `"101\t102\n103"` → 3 个 token）。

**处理管线（编号顺序为绑定条款；〔参考裁定〕指整条顺序本身，各步内部行为另有标注）**：

1. **必需列检查**：`uid`/`questions`/`responses`/`timestamps` 任一缺失（dict 无该键）
   → `ValueError`。〔测试裁定〕
2. `uid = str(row["uid"])` 规范化后透传（实测 uid=17 (int) → `"17"`）。〔参考裁定〕
3. 对 questions/responses/timestamps 三格做 token 化；记 `n` = questions token 数。
4. **长度校验（作用于全列，先于掩码剔除）**：responses 或 timestamps 的 token 数 ≠ n
   → `ValueError`。〔测试裁定〕
5. **selectmasks 读取**：键缺失、值为 `None`、或 `str` 去空白后为空串 → 视为「无掩码」
   （全部位有效；实测空串与全空白单元格均等价于缺列）；否则 token 化，token 数 ≠ n
   → `ValueError`（掩码长度校验同样作用于全列——尾部多出的 `"-1"` 也抛）。
   〔测试裁定缺列/长度；参考裁定空白格〕
6. **掩码剔除先于一切 token 级解析**（附录 A/R1 核心条款）：`keep` = 无掩码时
   `[0..n)`，否则掩码 token ≠ `"-1"` 的位次集合（实测掩码 `x`、`0` 等一切非 `"-1"`
   token 一律视为有效）；`keep` 为空 → 返回 `(uid, [])`。〔测试裁定全剔除〕
7. **仅对 `keep` 位次**按列序解析 timestamps token：经 `float()` 解析，非数字 →
   `ValueError`；`t0` = `keep` 中**首个**时间戳值。**day 0 基准 = 掩码保留位首个
   时间戳，不是列首 token**。〔测试裁定 test_xes3g5m_row_day_conversion；参考裁定
   R1 定序探针：`questions="-1 101 102"`、`timestamps="777 86400000 172800000"`、
   `selectmasks="-1 1 1"` → days `[0.0, 1.0]`——若按废弃读法「先解析全列、t0=列首
   token」会得到 `[0.999991…, 1.999991…]`；且填充位时间戳为非数字 `"x"` 时不抛错〕
8. 按 `keep` 列序构造事件：responses token `== "1"` → True、`== "0"` → False、其余
   → `ValueError`（**仅保留位校验**——填充位 response 可为任意 token，实测填充位
   `"9"` 不抛错）；`item_id` = questions token 原样（含形如 `"-1"` 的 token，一律靠
   掩码剔除，不做值过滤）；`day = (t_i − t0) / 86400000`（IEEE 除法唯一结果，实测
   1 小时 = 1/24 天）。
9. 其余列（`concepts`/`is_repeat`/`fold`/`selectmasks` 本身）一律忽略；事件按列顺序
   排列，**不重排时间戳**（实测时间戳下降照收、days 可为负：`[0.0, -1.0]`）；非降
   校验交给 `trace`。

行内校验次序说明：第 4/5 步长度校验先于第 7/8 步 token 级校验；token 级错误（时间戳
非数字、response 非 "0"/"1"）无论先后均抛 `ValueError`，孰先命中不可观测、不作承诺。

掩码剔除后的事件流与未填充序列**完全一致**（实测相等；契约测试覆盖尾部填充且填充位
时间戳合法的形态，非数字填充位与首部填充的形态由 R1 探针冻结）。〔测试裁定 +
参考裁定〕

`load_xes3g5m_csv`：以 `encoding="utf-8", newline=""` 打开，`csv.DictReader` 逐行 →
`xes3g5m_row`，按文件顺序返回；只读；对同一文件重复加载结果相等；仅表头的文件 →
`[]`（实测）。〔测试裁定除末条外全部；末条参考裁定〕

## 4. 不变量（编号列出，全部可被契约测试或附录 A 探针检验）

- I1 **可重放（前缀一致性）**：对任意 `0 ≤ i ≤ len(events)`，`trace(events[:i])` 等于
  `trace(events)` 的**前** `len(trace(events[:i]))` 个快照组成的列表（逐字段相等）。
  等价的有效事件索引形式：设 `E` 为 `events` 剔除 bank 查不到的事件后的保序子序列，
  则对任意 `1 ≤ i ≤ |E|`：`trace(E[:i])[-1] == trace(events)[i−1]`。
  〔测试裁定 test_prefix_replay_consistency（无 ghost 域）；参考裁定 R3 探针：首位
  ghost 的全前缀成立〕
- I2 **确定性**：同 `(events, bank, graph, prior, half_life_days)` 产生相等的轨迹
  （dataclass 列表相等；无随机源、无系统时钟）。
  〔测试裁定 test_determinism、test_load_xes3g5m_csv〕
- I3 **遗忘非增**：相邻两次快照之间无新证据的知识点掌握度**非增**（衰减只降不升）；
  契约测试域内实测严格递减（0.894737 > 0.664787 > 0.332393）。6 位舍入后相邻相等
  **不违反**本条款（微小 Δ 如 1e-6 天，或深度衰减后舍入不可分/归零：实测 Δ=10000 天
  起连续快照同为 0.0）。从未写入证据的知识点恒等于 `round(prior, 6)`（默认 0.5；
  非默认 prior=0.3 实测 c/d 全程 0.3）。
  〔测试裁定 test_decay_monotone_without_new_evidence；参考裁定舍入边界与非默认
  prior 探针〕
- I4 **半衰期语义**：无新证据的知识点掌握度恰在 Δ=H 时减半（0.447368 =
  round(17/38, 6)）；同日（Δ=0）衰减因子为 1（0.873112 与 0.986348 的推演起点）。
  〔测试裁定 test_decay_exactly_halves_at_half_life、test_consecutive_correct_same_day_increases〕
- I5 **证据方向（条件化）**：在护栏后 `p_m > p_nm` 的题上（此时恰有 `lr_c > 1` 且
  `lr_w < 1`），同一衰减时钟下答对使该知识点高于衰减基线、答错低于之
  （`0.447368 < 0.873112` 且 `0.118881 < 0.447368`）。**条件域豁免**：护栏后
  `p_m ≤ p_nm` 的高猜度-高难度题方向反转，按 §3.3-B2 公式执行、本条款不适用——
  实测反例：`effective_guess=0.9, difficulty=0.6` → 护栏后 `p_m=0.88` 仍 `≤ p_nm=0.9`，
  `lr_c=0.88/0.9≈0.9778 < 1`、`lr_w=0.12/0.1=1.2`：prior=0.5 答对 → 0.494382（降）、
  答错 → 0.545455（升）；同钟第 7 天衰减基线 0.247191，答对后 0.243033（低于基线）、
  答错后 0.282655（高于基线）。性质复验只可对 `p_m > p_nm` 的题作断言，不得全称化。
  〔测试裁定 test_correct_lifts_wrong_drops_at_same_clock（其 fixtures 域内
  p_m > p_nm 成立）；参考裁定反例探针〕
- I6 **猜测感知（条件化）**：在护栏未触发的域（护栏前 `p_m > max(effective_guess, 0.02)`，
  契约测试全域如此），同难度题答对的掌握度抬升随 `effective_guess` 增大而严格减弱
  （fill 0.894737 > choice 0.772727 > 0.5）。跨护栏边界**非单调**（实测：
  difficulty=0.5 时 guess=0.84 → 0.502959、guess=0.86 → 0.511364——guess 升、抬升
  反升），不作全称断言。〔测试裁定 test_guess_aware_same_family_as_diagnosis；
  参考裁定边界反例探针〕
- I7 **权重规则（按声明位次）**：权重只由 `item.kps` 声明位次决定（idx==0 → 1.0，
  其余 → 0.5）；图外知识点跳过**不重排位次**。主知识点（位次 0 且图内）与同参数单
  知识点题完全一致（ab1 → a=0.894737、b=0.744603）；位次 0 图外（`["zz","a"]`）时
  无主知识点，`"a"` 拿 w=0.5（实测 0.744603）；全部图外 → 快照照发、无更新。
  〔测试裁定 test_multi_kp_primary_full_secondary_half、test_graph_outside_kp_skipped；
  参考裁定首位图外/全图外探针〕
- I8 **值域与完备性**：每个快照 mastery/evidence 键集恰为图内知识点全集（键序同
  `graph.kps()`）；mastery ∈ [0,1]；evidence 为非负 int 且衰减不改变计数。空图 →
  空 dict 快照照发（实测 `mastery={}, evidence={}`）。
  〔测试裁定 test_snapshots_always_complete_and_in_range；参考裁定空图探针〕
- I9 **跳过与证据计数**：bank 查不到的题整条丢弃（无快照、时钟不推进，插入 ghost 不
  改变轨迹）；图外知识点仅跳过该知识点。`item.kps` 含重复 id 时**不去重**、按出现
  次数分别处理（权重按各自位次），evidence 按出现次数累计（逐位值见 §3.3-B2
  比对点）。〔测试裁定 test_unknown_item_dropped_and_clock_untouched、
  test_graph_outside_kp_skipped；参考裁定重复 kps 探针〕
- I10 **校验先于计算**：§3.3-A 全部校验在任何折叠之前，空 `events` 也抛
  （异常类型见 §6；prior 不可比较类型是唯一 `TypeError`）。
  〔测试裁定 test_invalid_params_rejected_even_with_empty_events、
  test_invalid_days_rejected〕
- I11 **拷贝隔离**：`to_profile` 输出与快照互不影响（`prof.mastery["a"] = -1.0` 不
  影响快照）；每个快照的 mastery/evidence 亦为独立新 dict。
  〔测试裁定 test_to_profile；参考裁定逐快照独立探针〕

## 5. 确定性与随机性

- `trace`/`xes3g5m_row` 是纯函数：输出只依赖入参；禁止 `random`、hash 序、系统时钟、
  环境读取。`day` 由入参携带，模块内不出现 `datetime.now`（`to_profile.updated_at`
  除外，已豁免并明确标注）。
- 浮点可复现性：衰减因子恒为 `0.5 ** (Δ/H)`（Δ 为相邻**有效**事件 day 差；遥折等价
  于距各自末证据的时长——ghost 不推时钟）；似然比与 odds 运算顺序按 §3.3-B2 逐步
  执行；快照值一次性 `round(·, 6)`（Python 3 内置，银行家舍入），内部状态不舍入。
  §3.3 表中每个数值都是逐位比对点。
- 文件 IO 仅 `load_xes3g5m_csv`，只读、按文件顺序、无排序/去重等隐式变换。

## 6. 错误行为

| 非法输入 | 行为 |
|---|---|
| `prior` ∉ (0,1)（含 0、1、负、>1；bool 按数值参与落入此支） | 计算前抛 `ValueError` |
| `prior` 为不可比较类型（str、None、list、dict 等） | 计算前抛 **`TypeError`**（全规格唯一例外，R2） |
| `prior` 为可比较数值类型且在 (0,1) 内（如 `Decimal("0.5")`) | 接受 |
| `half_life_days` ≤ 0 / 非数字 / bool / NaN | 计算前抛 `ValueError` |
| `event.day` 非数字（含 str、None、bool） | 计算前抛 `ValueError` |
| `event.day` 为负或 NaN | 计算前抛 `ValueError` |
| `event.day` 沿列表严格下降 | 计算前抛 `ValueError`；相等合法 |
| `events` 为空 | 不报错，返回 `[]`（参数校验仍执行） |
| `item_id` 查不到 | 容忍，整条事件跳过（I9） |
| `item.kps` 含图外知识点 | 容忍，仅跳过该知识点，位次不重排（I7/I9） |
| `item.kps` 含重复知识点 | 容忍，不去重，按出现次数分别处理（I9） |
| xes3g5m 缺必需列 / 长度不齐（含掩码列，作用于全列） | 抛 `ValueError` |
| xes3g5m 保留位 response token 非 "0"/"1" / 时间戳非数字 | 抛 `ValueError`（填充位不校验，§3.5） |
| xes3g5m 全部掩码剔除 | 容忍，返回 `(uid, [])` |

异常类型一律 `ValueError`，**唯一例外**为上表第 2 行的 `prior` `TypeError`；
`trace`/`xes3g5m_row`/`load_xes3g5m_csv` 对契约内输入不抛其他异常。异常消息文案
不作承诺（不是契约面）。

## 7. 非目标

- **不做先序平滑/间接证据**：kt 的 mastery 是纯直接证据 + 时间衰减；不实现任何先序
  补证或折价（那类语义属于 diagnosis 引擎，其公式不在本规格，也不被本模块 import）。
  两模块通过 `to_profile` 交接。
- **不做调度**：不产生 due/interval/ease，不做复习队列或每日配额。
- **不做判分**：`correct` 由调用方给定，不解析 `learner_answer`。
- **不做多学习者聚合**：一次 `trace` 只处理一个学习者的有序事件流；批量经
  `load_xes3g5m_csv` 返回逐学习者列表，不做跨学习者统计。
- **不绑定绝对日历**：`day` 是相对天数，不解释为日期；时区/日历换算不在本模块。
- **不重排或清洗事件**：不按时间排序（非降由调用方保证，违反即抛错）、不去重、
  不合并同日事件。
- **不持久化轨迹**：不写文件/数据库；轨迹由调用方持有。
- **不引入 DASH/FSRS/BKT 等具名模型**：遗忘函数冻结为 `0.5^(Δ/H)`，证据更新冻结为
  §3.3 的 odds 规则；换模型 = 换契约，不在本版面。

## 附录 A：对抗评审修复记录

以下为 drafts 版（specs/drafts/kt.spec.md）→ 本定稿的全部修复。证据均为本会话实跑
（2026-09-29，CPython 3.12.10）：契约基线
`python -m pytest tests/contract/test_kt_contract.py -q` → **22 passed**；探针脚本
`_research_tmp/kt_freeze_probes.py`（P1–P10）、`kt_freeze_probes2.py`（P11–P15）、
`kt_freeze_probes3.py`（P16–P17）、`kt_freeze_probes4.py`（P19–P21）；装载门实测
`XX_IMPL_DIR=<dir> XX_MODULES=kt python -m pytest tests/contract/test_kt_contract.py`。

| # | 严重度 | 评审问题 | 修复 | 证据（本会话实跑） |
| --- | --- | --- | --- | --- |
| R1 | major | XES3G5M「掩码剔除 vs timestamps 解析」先后及 day 基准二义：先剔除后解析（填充位非数字不抛、day 0=首个幸存 token）与先解析后剔除（填充位非数字抛、day 序列整体不同）都满足草稿字面；tests:216-218/225-228 填充全在尾部且填充时间戳合法，区分不了 | §3.5 管线冻结为**绑定编号顺序**：第 6 步掩码剔除先于第 7/8 步一切 token 级解析；day 0 = 掩码**保留位**首个时间戳；填充位 response/timestamps 一律不校验；长度校验（第 4/5 步）先于剔除、作用于全列 | 探针 P2：`questions="-1 101 102", timestamps="777 86400000 172800000", selectmasks="-1 1 1"` → `[(101,True,0.0),(102,False,1.0)]`（废弃读法得 `[0.999991, 1.999991]`）；填充位时间戳 `"x"`、填充位 response `"9"` 均 NO RAISE；掩码多 1 位 → ValueError；契约 22 passed |
| R2 | minor | prior 类型校验缺口且与 §6 自相矛盾：草稿只写链式比较区间条款，字面对 `prior="0.5"` 抛 TypeError，违反「异常类型一律 ValueError」；half_life_days/day 都有显式类型条款，唯 prior 没有；tests:175-181 只测数值型 | §3.3-A1 冻结为**链式比较求值语义（无类型预检）**：不可比较类型 → TypeError（全规格唯一例外，§6 表单列一行）；bool 按数值参与（True/False → ValueError）；可比较数值类型（Decimal）接受 | 探针 P1：`prior="0.5"/None/[]/{}` → `TypeError: '<' not supported between instances of 'float' and …`；`prior=True/False` → ValueError；`prior=Decimal("0.5")` → 接受；契约 22 passed |
| R3 | minor | I1 字面「trace(events[:i])[-1] == trace(events)[i−1]」在 events[0] 为 ghost 事件时，trace(events[:1])==[] 取 `[-1]` 抛 IndexError——按字面做性质复验会对合格实现误判失败 | I1 重述为 **ghost 安全形式**：前缀轨迹 == 全程轨迹的前缀（列表前缀相等），并给按有效事件索引的等价形式；字面读法明文废除 | 探针 P7：含首位 ghost 的 3 事件流全部前缀 `trace(evs[:i]) == full[:len(pre)]` 成立；`trace(evs[:1])[-1]` → `IndexError`（证实字面不可执行）；契约 test_prefix_replay_consistency passed |
| R4 | minor | I5 被规格自己的绑定公式在合法参数域内推翻：护栏只 +0.05，高猜度-高难度题（guess=0.9、difficulty=0.6）护栏后 p_m=0.88 ≤ p_nm=0.9，lr_c<1<lr_w，答对降、答错升，与 I5 方向相反；测试域（guess≤0.25）不触及 | I5 **条件化**：仅在护栏后 p_m > p_nm（恰 lr_c>1 且 lr_w<1）时断言方向；条件域豁免明文写入，反例数值冻结进规格，禁止性质复验全称化 | 探针 P6：guess=0.9, difficulty=0.6 → 答对 0.494382 < 0.5 < 0.545455 答错；同钟@7 基线 0.247191，答对后 0.243033（低于）、答错后 0.282655（高于）；对照 a2 域内方向正常（0.447368 < 0.873112、0.118881 < 0.447368） |
| R5 | minor | item.kps 含重复知识点行为未定义：字面循环 = 链式双更新 + evidence=2，去重实现 = 单次更新 + evidence=1；tests:120-127 只测互异 kp | §3.3-B2 冻结：**不去重**，重复按出现次数分别处理（第一次输出作为第二次输入），权重按各自位次，evidence 按出现次数累计；逐位比对点写入规格 | 探针 P4（fill 难 0.5，prior=0.5）：`["a","a"]` 答对 → 0.961213、evidence=2；答错 → 0.063707、evidence=2；`["a","a","a"]` 答对 → 0.986348、evidence=3（=lr²，与同日连对两次的闭式 289/293 一致，交叉印证） |
| R6 | minor | 图外知识点占 item.kps 首位时权重是否重排二义：idx 按声明位次（"a" 拿 0.5）还是跳过后重排（"a" 升主拿 1.0）两可；tests:143-148 用 `["a","zz"]`（图外在尾部）区分不了 | §3.3-B2/I7 冻结：**位次不重排**——idx 恒为声明位次，图外首位时无主知识点、其余全拿 0.5；全部图外快照照发、零更新 | 探针 P5：`["zz","a"]` → mastery[a]=0.744603（= w 0.5 值），evidence[a]=1，"zz" 无键；`["zz"]` → 快照 1 个，mastery 全 0.5、evidence 全 0 |
| R7 | minor | 序列单元格 token 化只定义纯空格/纯逗号两形态：混合形态 `"101, 102"` 按 split(',') 产生带前导空格 token、尾随逗号产生空 token 致长度误判——对真实脏数据容错分叉；tests:201-218 不覆盖 | §3.5 冻结 token 化 = 「空白与逗号以外字符的极大连续段」（扫描语义）：混合分隔得干净 token、尾随/连续分隔符无空 token、制表/换行可分隔；None → 空序列；空白掩码格 → 无掩码 | 探针 P3：`"101, 102, 103"` → 3 干净 token；`"101,102,103,"` 尾随逗号 → 3 events（无误抛长度错）；`"101\t102\n103"` → 3 token；掩码格 `"   "` → 全有效；P20：掩码 `x 0` 全保留 |
| R8 | minor（评审外同类修复） | I6「答对证据力随 effective_guess 增大而减弱」同为全称超claim：护栏在 guess 跨越 p_m 处使 lr_c 跳升，跨边界非单调（与 R4 同类，性质复验者会对合格实现报假失败） | I6 条件化：仅在护栏未触发域（护栏前 p_m > max(effective_guess, 0.02)，即契约测试全域）内断言严格减弱；边界反例数值冻结 | 探针 P19：difficulty=0.5 时 guess=0.1 → 0.894737、0.25 → 0.772727（域内单调，test_guess_aware 域）；guess=0.84 → 0.502959、guess=0.86 → 0.511364（跨边界反转） |

另有两处非评审意见的自包含化修订：§2 装载约束改为本文内实测（原草稿引用另一规格的
结论）——相对导入 → `ImportError`（tests/conftest.py:34 exec_module 处）；
`from __future__ import annotations` → dataclass 解析 `AttributeError: 'NoneType'
object has no attribute '__dict__'`（`dataclasses.py:983`，注入注册名 `xuexing.kt`
≠ dataclass `__module__` `_regen_kt`）；绝对导入 + 真实注解 → 装载成功、测试可运行
（含全部 6 名字的桩模块经真门实测）。§3.3 补非默认 prior 逐位比对点（prior=0.3 →
0.784615/0.392308/0.792285，探针 P17）——契约测试全用默认 prior，无此锚点时 prior
处理无位级验收依据。I3 的「非增为绑定面、严格递减为测试域观察」细化（探针 P16：
Δ=1e-6 与 Δ=10000 天的舍入相等例）亦为评审外一致性修订。
