# itembank 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> 状态：**frozen**（定稿，2026-09-29）。取代 specs/drafts/itembank.spec.md。
> 定稿依据：对抗评审 6 项问题逐条实证修复，修复记录见附录 A。

**证据标注约定**（全文适用）：

- 【测试】= tests/contract/test_itembank_contract.py 有直接断言，是行为 ground truth。
- 【参考】= 仅由参考实现 src/xuexing/itembank.py 证实。
- 【参考-探针】= 参考实现行为 + 撰写/定稿会话中探针脚本逐条运行核实的记录（探针输出
  摘录在正文中）。测试未覆盖但参考实现明确的行为，按参考实现冻结。
- **冲突规则**：两者冲突时以【测试】为准，并在正文注明。
- **UB（未冻结）**：明确标注 UB 的输入域，规格不作任何承诺，任何行为均合规，契约测试
  不仲裁。UB 条目同时记录参考实现的自然行为，供实现者参考，但不是要求。

## 1. 目的

itembank 是题库模块：在内存中存储 `Item` 对象（xuexing.types.Item），按 id 存取、按知识点检索，
并提供两级校验——逐题校验（字段值域、choice 选项/答案一致性）与全库校验（追加 Q-matrix 引用
完整性：kps 是否落在调用方给定的合法知识点集合内），以及从 JSON 文件/字典载入题库。它是
diagnosis、paper、agent_shell 等模块的数据底座：契约环境夹具 `small_bank`
（tests/contract/conftest.py:50-68）就是一个本模块实例，被 test_diagnosis / test_paper /
test_agent_shell 契约测试消费，因此本规格冻结的 API 面同时被这些测试间接依赖。

## 2. 允许的依赖

- Python 标准库（参考实现仅用 `json`）
- `xuexing.types`（绝对导入：`from xuexing.types import Item`）
- 禁止：其他 xuexing 模块（itembank **不**依赖 kpgraph——Q-matrix 合法性通过 `validate_all`
  的 `valid_kp_ids` 参数注入，不做跨模块查询）、第三方库
- 文件 IO：仅 `load_itembank` 允许读文件（utf-8 JSON，只读）；其余 API 纯内存

## 3. 公开 API

### 3.0 输入域（所有 API 的行为保证范围）

`Item` 是 dataclass，构造时不做类型检查（实测 `Item(id='x', stem=None, ...)` 构造成功），
因此必须先划定本规格的**行为保证域**。域的定义 = 各字段类型符合 xuexing/types.py:27-40
的声明：

| 字段 | 域内类型 |
|---|---|
| id | `str`（允许假值——假值由 R1 报告，仍属域内） |
| item_type | `str` |
| stem / answer | `str` |
| kps / options / misconceptions | `list[str]` |
| difficulty / discrimination | 实数（`int`/`float`） |
| guess | `None` 或实数（`Optional[float]`） |

- **域内**：本文所有 API 的行为条款（含"校验函数不抛异常"）全部适用且被冻结。
- **域外**（如 stem=None、answer=None、difficulty=None、choice 且 options=None、options 含
  非 str 元素、kps=None 等）：**UB**。参考实现的自然行为是异常外溢——探针记录
  （2026-09-29）：stem=None → `AttributeError("'NoneType' object has no attribute 'strip'")`；
  difficulty=None → `TypeError("'<=' not supported between instances of 'float' and 'NoneType'")`；
  choice+options=None → `TypeError("object of type 'NoneType' has no len()")`；
  options=[1,2] → `AttributeError("'int' object has no attribute 'strip'")`。例外：kps=None 在
  `validate_item` 中恰好不崩（falsy → 报 R5 "no kp tags"），但 `by_kp` 对它会在 `in` 检查处
  TypeError——统一按 UB 处理。重生成实现可任选：自然抛异常、防御式报错、或抛
  ItemBankError；契约测试不仲裁。下游契约模块只喂域内 Item（conftest small_bank 及全部
  契约夹具均为良型），故域外自由度不泄漏进任何契约测试。

### 3.1 异常类型

```python
class ItemBankError(ValueError): ...
```

本模块唯一的**契约冻结**异常类型，`ValueError` 的直接子类（MRO：ItemBankError → ValueError →
Exception）【测试 test_add_get_duplicate:19-20 `pytest.raises(ItemBankError)`；【参考】
src/xuexing/itembank.py:10-11】。（域外输入的 UB 异常不在此列，见 §3.0/§6。）

### 3.2 `ItemBank()`

构造空题库，无参数【测试 test_add_get_duplicate:16】。

### 3.3 `ItemBank.add(item: Item) -> None`

按对象引用存入 `item`（不拷贝、不修改传入对象）。**不做任何校验**——非法 Item（如
difficulty=9.9）也允许入库，校验只发生在 `validate_item`/`validate_all`
【测试 test_validate_all_dedup_and_kp_check:59 对 difficulty=-1 的题 add 成功；【参考】探针核实】。

- 若库中已存在同 id 题目：抛 `ItemBankError`，消息 `"duplicate item id: <id>"`
  【测试 test_add_get_duplicate:19-20（类型）；消息格式【参考】itembank.py:20，探针核实 `duplicate item id: a1`】。

例子（摘自 test_add_get_duplicate:15-20）：`add(_item("i1"))` 后 `has("i1")` 为 True 且
`get("i1").id == "i1"`；再次 `add(_item("i1"))` 抛 `ItemBankError`。

### 3.4 `ItemBank.get(item_id: str) -> Item | None`

存在则返回入库的同一 `Item` 对象；不存在则返回 `None`（**不抛异常**）
【测试 test_add_get_duplicate:18（存在路径）；None 语义【参考】itembank.py:23-24，探针
`get('nope') → None`】。

### 3.5 `ItemBank.has(item_id: str) -> bool`

存在 → True，否则 False【测试 test_add_get_duplicate:18；探针 `has('nope') → False`】。

### 3.6 `ItemBank.items() -> list[Item]`

全部题目，按 id 的 **Python 字符串升序**（码点序）返回，与插入顺序无关。每次调用返回新
列表对象，修改返回列表不影响库内数据【参考】。

证据等级更正（对抗评审定稿）：**id 升序仅由【参考-探针】冻结**。契约套件内不存在任何顺序
断言——test_by_kp_primary_semantics:46 的 `== ["i1"]` 是单元素列表（顺序不可区分）、:47 是
set 比较；`items()` 在契约测试中的全部消费是 `len()`（test_agent_shell_contract.py:72,77）
与无序迭代求极值/过滤（test_paper_contract.py:63、test_route_contract.py:15）。探针：按
z3→a1→m2 顺序插入，`items()` 返回 `['a1','m2','z3']`。（tests/unit/test_itembank.py:44-45
确实断言了双元素顺序，但 unit 测试不在仲裁集内——tools/run_contract.py:46 注入重生成实例时
只跑 tests/contract/。）

### 3.7 `ItemBank.by_kp(kp_id: str, primary_only: bool = False) -> list[Item]`

- 成员判定：`kp_id ∈ item.kps`（列表包含，任意位置命中都算）【测试 test_by_kp_primary_semantics:47】。
- `primary_only=True`：仅返回 **kps 非空且 `kps[0] == kp_id`** 的题（主知识点语义；
  kps 为空的题两种模式都不命中）【测试 test_by_kp_primary_semantics:46；空 kps 情形【参考】探针】。
- 返回顺序同 `items()`：按 id 升序【参考-探针，证据等级讨论同 §3.6；测试只以单元素列表/
  set 形式触及顺序】。

例子（摘自 test_by_kp_primary_semantics:42-47）：i1 的 kps=["a","b"]、i2 的 kps=["b"]：

- `by_kp("a", primary_only=True)` → `["i1"]`（顺序严格相等；i2 不命中，因 "a" 不是其主知识点）
- `set(by_kp("b"))` → `{"i1", "i2"}`（i1 凭次要知识点命中）

### 3.8 `ItemBank.validate_item(item: Item) -> list[str]`

逐题校验。对 §3.0 域内的 Item **永不抛异常**，返回 0..n 条错误字符串，按下列固定规则目录
顺序累加（全部消息已由【参考】itembank.py:39-68 冻结，探针逐条核实；契约测试断言其中的
子串）：

| # | 条件（违反则报错） | 错误消息（精确格式） | 测试断言子串 |
|---|---|---|---|
| R1 | `item.id` 为假值 | `missing id`（无 id 前缀） | — |
| R2 | `item.item_type` 不在 `("choice", "fill", "solve")` | `{id}: bad item_type {item_type!r}`（repr，如 `'essay'`） | `item_type` |
| R3 | `item.stem.strip()` 为空 | `{id}: empty stem` | `empty stem` |
| R4 | `item.answer.strip()` 为空 | `{id}: empty answer` | — |
| R5 | `item.kps` 为空 | `{id}: no kp tags` | `no kp tags` |
| R6† | `item.difficulty` 越域（谓词见下） | `{id}: difficulty out of [0,1]` | `difficulty` |
| R7† | `item.discrimination` 越域（谓词见下） | `{id}: discrimination out of [0,1]` | `discrimination` |
| R8† | `item.guess` 非 None 且越域（谓词见下） | `{id}: guess out of [0,1]` | — |
| R9a | 仅 choice：`len(item.options) < 2` | `{id}: choice needs >=2 options` | — |
| R9b | 仅 choice 且选项数 ≥2：`answer.strip()` 不在选项集合 | `{id}: answer not among options` | `answer not among options` |
| R9c | 仅 choice：选项 strip 后存在重复 | `{id}: duplicate options` | — |

† **R6/R7/R8 的越域判定语义冻结为链式比较 `not (0.0 <= x <= 1.0)`**。该谓词下
`NaN` 与 `±Inf` 一律越域、**必须报错**（NaN 使链式比较两段均为 False → `not False` → True）。
写成 `x < 0.0 or x > 1.0`（NaN 时两支均 False → 不报）的实现**不合规**。此路径可达：
标准库 `json` 默认接受 `NaN` 字面量，NaN 可经 `load_itembank` 进入题库——探针：JSON 文件
含 `"difficulty":NaN` 载入成功，`validate_all()` 返回 `['n1: difficulty out of [0,1]']`。

**R1 不短路**：id 为假值时其余规则照常逐条评估累加，各消息前缀按字面
`f"{item.id}: "` 渲染。探针记录（2026-09-29；item_type="essay", stem=" ", answer=" ",
kps=[], difficulty=2.0）：

- `id=""` → `['missing id', ": bad item_type 'essay'", ': empty stem', ': empty answer', ': no kp tags', ': difficulty out of [0,1]']`（注意前缀渲染为冒号+空格开头）
- `id=None`（域外，仅记录参考渲染）→ `['missing id', "None: bad item_type 'essay'", 'None: empty stem', 'None: empty answer', 'None: no kp tags', 'None: difficulty out of [0,1]']`

choice 答案匹配规则（R9b）的精确语义【参考 itembank.py:61-65，探针核实】：

- `labels = [o.strip().split(".")[0].strip() for o in options]`——**第一个 "." 之前**的首段
  （`"B. 2"` → `"B"`；无 "." 的选项如 `"TRUE"` → 整体）
- `texts = [o.strip() for o in options]`——strip 后的完整选项文本
- 合法 ⇔ `answer.strip()` ∈ labels ∪ texts；两侧均 strip（选项 `" A. 1 "`、答案 `" B "` 均可匹配）
- "." 之后的内容不参与匹配：options=["A. 1","B. 2"]、answer="1" → 报 R9b

R9 组内结构【参考，探针核实】：R9a 违反时**跳过 R9b**（选项不足 2 个时只报 a 不报 b）；
R9c 与 a/b 独立、无论选项数多少都执行。非 choice 题完全忽略 `options` 字段——fill 题带重复
options 也返回 `[]`【参考探针】。

多违规累加：一条题可返回多条错误，顺序按上表。探针核实：`item_type="essay", stem=" ",
answer="  ", kps=[], difficulty=2.0, discrimination=-0.1, guess=1.5`（id 非假值）依次返回
R2…R8 共 7 条。

例子（摘自 test_choice_answer_accepts_label_or_text:23-30）：options=["A. 1", "B. 2"] 时——

- answer="B"（标号）→ `[]`
- answer="B. 2"（完整文本）→ `[]`
- answer="C" → 返回的错误中存在包含 `"answer not among options"` 的条目

### 3.9 `ItemBank.validate_all(valid_kp_ids: set[str] | None = None) -> list[str]`

全库校验【测试 test_validate_all_dedup_and_kp_check:57-61；【参考】itembank.py:70-78】：

1. 按 `items()` 顺序（id 升序，§3.6）遍历每题：先 `extend(validate_item(it))`；
2. 若 `valid_kp_ids is not None`：对该题 `kps` 中**每个**不在集合内的 k 追加一条
   `"{id}: unknown kp {k}"`（多个未知 kp 各一条）；
3. `valid_kp_ids=None` 时完全跳过第 2 步（无 kp 检查）【参考探针：`validate_all()` 对
   difficulty 违规题只返回 `['bad: difficulty out of [0,1]']`】；
4. 返回 `sorted(set(errs))`——**先去重再整体按字符串升序排序**，跨题错误混排。

R6–R8 的 NaN/±Inf 语义（†谓词）在 validate_all 中同样适用（内部复用 validate_item）。

探针核实的排序实例（两题 i1、i2 各含 difficulty=-1 与未知 kp "ghost"，valid_kp_ids={"a"}）：

```python
['i1: difficulty out of [0,1]', 'i1: unknown kp ghost',
 'i2: difficulty out of [0,1]', 'i2: unknown kp ghost']
```

### 3.10 `load_itembank(path: str) -> ItemBank`

读 utf-8 JSON 文件并等价于 `itembank_from_dict(json.load(open(path, encoding="utf-8")))`
【参考 itembank.py:81-84；探针核实含中文 stem 的 roundtrip 正确】。文件不存在 → `OSError`、
JSON 非法 → `json.JSONDecodeError`（此两类仅【参考】证实，测试未冻结具体类型，见 §6）。
NaN 语义说明：`json.load` 默认接受 `NaN`/`Infinity` 字面量，因此 NaN 题目可经此入口进入
题库并在校验时按 R6–R8 报错（§3.8 †谓词，探针核实）。

### 3.11 `itembank_from_dict(data: dict) -> ItemBank`

从字典构造题库；`data` 须含 `"items"` 列表。逐项字段映射与类型强制
（【参考 itembank.py:87-105，探针核实】）：

| 字段 | 必填 | 强制 | 缺省 |
|---|---|---|---|
| id / item_type / stem | 是 | 原样 | — |
| answer | 是 | `str(...)`（整数 `1` → `"1"`） | — |
| kps | 是 | `list(...)` | — |
| difficulty | 是 | `float(...)`（字符串 `"0.5"` → `0.5`） | — |
| solution | 否 | 原样 | `""` |
| options | 否 | `list(...)` | `[]` |
| discrimination | 否 | `float(...)` | `0.6` |
| guess | 否 | **原样，不强制**（字符串 `"0.3"` 存为字符串） | `None` |
| misconceptions | 否 | `list(...)` | `[]` |

定稿补充条款（对抗评审修复，探针核实 2026-09-29）：

- **未知键静默忽略**：item dict 中上表之外的键（如 `bogus`、`weight`）被丢弃，不报错、
  不产生属性。因此**禁止** `Item(**it)` 式实现（未知键会 TypeError）。探针：含 `'bogus':1,
  'weight':9` 的 dict 构造成功，`hasattr(it,'bogus')` 为 False。
- **强制失败原样传播**：字段存在但强制失败时，异常**原样**抛出，不包装为 ItemBankError、
  不回退缺省值：`difficulty=None` → `TypeError("float() argument must be a string or a real
  number, not 'NoneType'")`；`difficulty='abc'` → `ValueError("could not convert string to
  float: 'abc'")`；`kps=None` → `TypeError("'NoneType' object is not iterable")`。
  （异常类型本身不冻结——冻结的是"传播且不包装、不回退"。）
- **answer=null 不失败**：`str(None)` → 字符串 `"None"`，该题正常入库且 validate 通过
  （探针：`answer=null` → `repr` 为 `'None'`，`validate_item` 返回 `[]`）。

入库经 `bank.add`，因此 dict 内重复 id 抛 `ItemBankError`【参考】。

### 3.12 `Item.effective_guess() -> float`（types 方法，由本模块契约测试断言）

定义在 xuexing/types.py:42-45（冻结 schema 模块），但 test_effective_guess_contract:50-54
对其断言，故在此冻结：

- `guess is not None` → 原样返回 `guess`（不 clamp）
- 否则按 `item_type` 查表：`choice → 0.25`、`fill → 0.10`、`solve → 0.02`，
  **未知 item_type 回退 `0.1`**【回退分支【参考】types.py:45，探针 `item_type='weird'` → 0.1】

例子（摘自 test_effective_guess_contract:50-54）：`item_type="choice"` → 0.25；
`"fill"` → 0.10；`"solve"` → 0.02；`guess=0.9` 的题 → 0.9。

## 4. 不变量（全部可被契约测试检验）

- I1 **id 唯一**：同一实例内 add 两个同 id 的 Item，第二次必须抛 `ItemBankError`（§3.3）。
- I2 **存取一致**：`has(id)` 为 True ⇔ `get(id)` 非 None；`get(id).id == id`（§3.2–3.4）。
- I3 **缺失安静**：`get`/`has` 对未存 id 返回 None/False，不抛异常（§3.4–3.5）。
- I4 **id 序确定性**（证据等级：【参考-探针】，契约测试无顺序断言，见 §3.6）：
  `items()` 与 `by_kp()` 输出按 id 的字符串升序，与插入顺序无关。规格即契约，重生成实现
  仍必须遵守本条。
- I5 **主知识点语义**：`by_kp` 成员判定为 `kp_id ∈ kps`；`primary_only=True` 时仅
  `kps[0] == kp_id`（kps 非空）（§3.7）。
- I6 **校验显式且域内不抛**：`add`/`itembank_from_dict` 不做内容校验，非法字段可入库；
  在 §3.0 输入域**内**，`validate_item`/`validate_all` 对任意字段值不抛异常，只返回错误
  列表。§3.0 域**外**的输入属 UB，不受本条保护（§6）。
- I7 **校验规则目录固定**：R1–R9 的触发条件、消息格式与累加顺序不允许偏离；非 choice 题
  忽略 options；choice 选项 <2 时跳过 R9b 但执行 R9c；R1 不短路（前缀字面渲染）；
  R6/R7/R8 的越域谓词为 `not (0.0 <= x <= 1.0)`，NaN/±Inf 必须报错（§3.8）。
- I8 **validate_all 结构**：遍历序 = id 升序；每题先题目错误、后 unknown kp 错误；
  `valid_kp_ids=None` 跳过 kp 检查；返回值为 `sorted(set(错误))`（§3.9）。
- I9 **guess 优先级**：`effective_guess` 显式 guess 优先，否则按 item_type 查表
  （choice 0.25 / fill 0.10 / solve 0.02 / 未知 0.1）（§3.12）。
- I10 **无隐藏随机与时间**：模块所有输出（含列表顺序、错误消息及其顺序）只是输入与库内容的
  函数；不读时钟、不用随机源、不产生时间戳字段（§5）。
- I11 **载入等价与容错**：`load_itembank`/`itembank_from_dict` 按 §3.11 的强制表保留各字段；
  item dict 未知键静默忽略；类型强制失败时异常原样传播（不包装、不回退缺省）；
  dict 内重复 id 抛 `ItemBankError`（§3.10–3.11）。

## 5. 确定性与随机性

- 全模块**必须**同输入同输出：同库、同参数 → 相同的返回对象内容、相同的列表顺序、相同的
  错误消息及顺序（I4、I7、I8）。
- **允许的随机：无。** 模块不接受 seed，也不允许内部使用 `random`；这区别于 paper 等
  seed 驱动模块——itembank 是它们确定性的底座。
- **时间：无。** 不产生任何时间戳字段（Item schema 亦无）；不允许读取系统时钟。

## 6. 错误行为

| 非法输入 / 情形 | 必须的行为 | 异常类型 | 证据 |
|---|---|---|---|
| add / from_dict 遇重复 id | 抛异常，消息 `duplicate item id: <id>` | `ItemBankError`（ValueError 子类） | 【测试：类型】+【参考-探针：消息】 |
| Item 字段违规（R1–R9，§3.0 域内） | **不抛异常**，返回错误字符串列表 | 无 | 【测试】 |
| R6/R7/R8 遇 NaN / ±Inf | **必须报越界错误**（不报者不合规，谓词见 §3.8†） | 无 | 【参考-探针】（NaN 可经 load_itembank 进入，探针核实） |
| id 为假值（""/None 等） | R1 报 `missing id` 且**不短路**，其余规则前缀按字面渲染（§3.8） | 无（域内 id=""）；id=None 属 UB，渲染仅作参考记录 | 【参考-探针】 |
| §3.0 域外输入（stem/answer=None、difficulty=None、choice+options=None、options 含非 str、kps=None 等） | **UB——不冻结**。参考实现自然抛 AttributeError/TypeError（各异常消息已探针记录于 §3.0）；实现可任选自然抛 / 防御报错 / ItemBankError，契约测试不仲裁 | 任意 | 【参考-探针：UB】 |
| from_dict 强制失败（difficulty=null / 'abc'、kps=null 等） | 异常**原样传播**：不包装为 ItemBankError、不回退缺省值 | `TypeError` / `ValueError`（类型不冻结，冻结传播语义） | 【参考-探针】 |
| from_dict item dict 含未知键 | 静默忽略（禁止 `Item(**it)` 式实现） | 无 | 【参考-探针】 |
| from_dict `answer=null` | 强制为字符串 `"None"`，正常入库、校验通过 | 无 | 【参考-探针】 |
| `get`/`has` 未存 id | 返回 None / False | 无 | 【参考-探针】 |
| load_itembank 文件不存在 | 抛异常（不得静默） | `OSError` | 【参考】（测试未冻结类型） |
| load_itembank JSON 非法 | 抛异常 | `json.JSONDecodeError` | 【参考】（测试未冻结类型） |
| from_dict 缺 `"items"` 键 / 缺必填字段 | 抛异常 | `KeyError` | 【参考】（测试未冻结类型） |
| 非 choice 题带 options；`guess=None`；solution/misconceptions 缺省 | 容忍并按缺省处理，**必须跳过不报错** | 无 | 【测试】+【参考】 |

## 7. 非目标

- 不判分、不归因误解（`misconceptions` 字段仅透传存储）；判分与诊断属 diagnosis/agent_shell。
- 不选题、不组卷、不调度；与知识图谱零耦合——kp 合法性只通过 `validate_all(valid_kp_ids=...)`
  的参数注入检查，模块内不 import kpgraph。
- 不提供删除、更新、合并、计数类 API（契约测试未要求；重生成实现不得自行添加公开行为）。
- 除 `load_itembank` 外无任何持久化、缓存或全局状态；两个 `ItemBank` 实例完全隔离。
- 不修改传入的 `Item` 对象（存引用，不改写）。
- 不为 §3.0 域外输入定义行为（UB）；不承诺对类型错误字段的防御。

## 附录 A：对抗评审修复记录（drafts → frozen，2026-09-29）

| # | 评审问题（severity） | 复核方式 | 修复 |
|---|---|---|---|
| 1 | I6/§3.8 宣称"任意字段值不抛异常"与字面实现矛盾；None/错型使 .strip()/len()/区间比较崩溃（major） | 探针：`Item(stem=None,...)` 构造成功；validate_item 对 stem/answer=None→AttributeError、difficulty/discrimination=None→TypeError、choice+options=None→TypeError、options=[1,2]→AttributeError；kps=None 不崩反报 "no kp tags" | 新增 §3.0 输入域：域内"不抛"保证成立；域外一律 **UB**（记录参考异常供参考，不作要求）；改写 I6、§3.8 首句、§6 UB 行 |
| 2 | R6/R7/R8 闭区间判定未定 NaN 归类，两种自然写法结论相反（major） | 探针：difficulty/discrimination/guess=NaN 及 ±Inf 在参考实现下全部报越界（即参考用 `not (0.0<=x<=1.0)` 链式语义）；JSON 文件 `NaN` 字面量经 load_itembank 入库成功并被 validate_all 报告 | §3.8 表加 †：越域谓词冻结为 `not (0.0 <= x <= 1.0)`，NaN/±Inf 必报错；`x<0 or x>1` 写法判为不合规；§3.10 注明 NaN 入口；I7 并入 |
| 3 | from_dict 未知键行为未定：显式提取者静默丢弃 vs `Item(**data)` 抛 TypeError（minor） | 探针：`'bogus':1,'weight':9` 静默丢弃、无属性、无异常 | §3.11 定稿条款：未知键静默忽略，禁止 `Item(**it)` 式实现；I11 并入；§6 行 |
| 4 | from_dict 强制失败行为未定：float(None)→TypeError、'abc'→ValueError，§6 原表未覆盖（minor） | 探针：difficulty=null→TypeError、'abc'→ValueError、kps=null→TypeError；answer=null→str "None" 且校验通过 | §3.11 定稿条款：异常原样传播、不包装、不回退（异常类型本身不冻结）；§6 行 |
| 5 | id 假值时 R1 是否早退未钉死，前缀渲染无探针（minor） | 探针：id="" 与 id=None 的完整 6 条消息列表——R1 不短路，前缀字面渲染（": ..." / "None: ..."） | §3.8 新增"R1 不短路"段，附两份探针消息列表；I7 并入；§6 行 |
| 6 | §3.6 称 id 升序"【测试间接断言】"失实——契约套件无任何顺序断言（minor） | grep 全 tests/：契约内 items() 仅 len()/无序迭代（agent_shell:72,77；paper:63；route:15）；by_kp 仅单元素列表/set 断言；unit 的顺序断言不在仲裁集（tools/run_contract.py:46 只跑 tests/contract） | §3.6/§3.7/I4 证据改标【参考-探针】并注明测试无顺序断言；保留顺序冻结（规格即契约），注明以未来测试为准的冲突规则不变 |

## 附录 B：验证方式

- 参考实现基线（定稿时运行核实）：`python -m pytest tests/contract/test_itembank_contract.py -v`
  → 6 passed；全套 `python -m pytest tests/contract/` → 47 passed。
  导入路径由 tests/conftest.py:6-7 注入（`sys.path` 加 `src/`），无需设 PYTHONPATH；
  pytest.ini：testpaths=tests, addopts=-q。
- 重生成实例门控：`python tools/run_contract.py --impl-dir <目录> --modules itembank`
  （tools/run_contract.py:43-52 设 XX_IMPL_DIR/XX_MODULES，只跑
  tests/contract/test_itembank_contract.py）；等价手跑
  `XX_IMPL_DIR=<目录> python -m pytest tests/contract/test_itembank_contract.py`，
  注入机制见 tests/contract/conftest.py:14-26（单文件 itembank.py，顶替
  `sys.modules["xuexing.itembank"]`）。
- 本规格所有【参考-探针】结论均在定稿会话（2026-09-29）以探针脚本对参考实现运行核实，
  探针输出已摘录于正文对应条款。
