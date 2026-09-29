# itembank_v2 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> 状态：**frozen**（定稿，2026-09-29）。取代 specs/drafts/itembank_v2.spec.md。
> 定稿依据：对抗评审 5 项问题逐条实证修复，修复记录见附录 A。
> 本文全部数值例子均为实测值（参考实现 `src/xuexing/itembank_v2.py` +
> `tests/contract/test_itembank_v2_contract.py`，2026-09-29 定稿会话实测，
> CPython 3.12.10 x64 / Windows）。

**证据标注约定**（全文适用）：

- 【测试】= tests/contract/test_itembank_v2_contract.py 有直接断言，是行为 ground truth。
- 【参考】= 仅由参考实现 src/xuexing/itembank_v2.py 证实。
- 【参考-探针】= 参考实现行为 + 定稿会话探针脚本逐条运行核实（输出摘录于正文）。测试未
  覆盖但参考实现明确的行为，按参考实现冻结。
- **冲突规则**：两者冲突时以【测试】为准，并在正文注明。

## 1. 目的

itembank_v2 是**题库 schema v2 校验器**（BACKLOG「题库 schema v2」的确定性内核）。
在题库 dict（item json 反序列化后的对象）上定义两个溯源/质检字段并机器强制其完整性：

- `source`：题目来源，枚举 `original`（原创）/ `adapted`（真题改编——必须附非空
  `source_ref` 注明出处）/ `llm_generated`（LLM 生成+验证——必须附**通过的**
  双代理独立解题一致性记录）。对应 README 的入库原则：LLM 生成内容只有经验证才可入库。
- `verification`：双代理独立解题一致性记录 `{"agents": [...], "answers_agree": true}`——
  两个**互不相同**的独立解题者标识（≥2 个无首尾空白的非空字符串、按原始字面值互不重复）
  + 标答一致判定（必须恰为 `True`：记录为"不一致"的题不得留在库内）。
- **完整性语义（已定语义决策）**：`original`/`adapted` 允许无 `verification`
  （键缺失与显式 `null` 等价，含义均为"尚未做双代理验证"——诚实缺口而非伪造记录）；
  `llm_generated` 必须带通过的记录。

**真实题库现状（2026-09-29 定稿实测；属数据事实陈述，非本模块行为条款）**：
data/items/ 共 321 题（math_grade7 129 + math_grade8 87 + math_grade9 105），source
全部为 `original`（来源闭式由 tests/data/test_itembank_v2_data.py 的
`test_real_provenance_all_original` 锁定）；且 2026-09-29 双代理独立复验运行回填后，
**全库每题均带通过的 verification 记录**——`verified == total` 由同文件
`test_real_verification_records_honest` 锁定（记录可追溯性由
tests/data/test_dual_verify_data.py 强制）。库内记录形状即本规格记录目录的合规实例，
如 `{"agents": ["m3-reviewer", "night-reverify-20260929"], "answers_agree": true}`。

校验器是返回错误消息列表的**全函数**：`validate_item_v2` 对任意输入对象不抛异常、
纯函数（无 IO、无随机、无时钟、不读环境）；`validate_bank_v2` / `source_counts` /
`verification_stats` 对可迭代入参同样不抛异常，入参不可迭代时 TypeError 原样传播
（§6、I11）。冻结模块 itembank.py 的 `validate_item`/`validate_all` 保持现状不动
（v1 字段校验不在本规格范围内，本模块不修改、也不重复定义其行为）；数据侧接线由
`tools/validate_knowledge.py`（非重生成范围）完成，数据闭环由
tests/data/test_itembank_v2_data.py 强制。

## 2. 允许的依赖

- Python 标准库（实际仅需内建类型）
- **注入装载约束**：重生成实例由测试夹具按单文件以 importlib 装载为顶层模块名
  `_regen_itembank_v2` 并顶替 `sys.modules["xuexing.itembank_v2"]`
  （tests/conftest.py:22-34），不经过包 `__init__`。因此**不使用**
  `from __future__ import annotations`，注解直接写真实对象。
- 本模块**不需要** `xuexing.types`（校验面向题库 dict，不构造 Item 对象）
- 禁止：其他 xuexing 模块、第三方库、文件/网络 IO、`random`、系统时钟、环境读取

输入表面：题库 dict（含 `id`/`source`/`source_ref`/`verification` 等键的任意 dict）、
dict 的可迭代对象。校验只依赖上述键，其余键一律忽略（前向兼容）。

## 3. 公开 API

模块必须暴露以下 6 个名字（契约测试
`from xuexing.itembank_v2 import (SCHEMA_VERSION, SOURCE_VALUES, validate_item_v2,
validate_bank_v2, source_counts, verification_stats)`）。

### 3.1 常量

```python
SCHEMA_VERSION = 2                                  # int
SOURCE_VALUES = ("original", "adapted", "llm_generated")   # tuple，canonical 顺序
```

### 3.2 `validate_item_v2`

```python
def validate_item_v2(item) -> list
```

单题 v2 完整性校验。对**任意**输入对象不抛异常，返回 0..n 条错误消息（str 列表）。
非 dict 输入只返回 `["item is not a dict"]`（无前缀）。

消息前缀 `p = f"{id}: "`：`id` 键存在时按其值字面渲染（f-string/str 渲染，**不带
repr 引号**；falsy/非 str 照渲染——`id=None` → `"None: "`、`id=""` → `": "`、
`id=42` → `"42: "`、`id={"x": 1}` → `"{'x': 1}: "`【参考-探针】）；
键缺失 → `"<no-id>: "`。

规则目录（V1 → V2 → V3 固定顺序累积、**不短路**；各规则独立评估实际值——source
缺失/非法时不连锁触发 adapted/llm 专属规则，但 V1 自身照报）：

| # | 条件（违反则报错） | 错误消息（精确格式） |
|---|---|---|
| V1a | `"source"` 键缺失，或值为 str 且 strip 后为空 | `{p}missing source` |
| V1b | `"source"` 值非 str（含 None） | `{p}bad source {value!r}` |
| V1c | `"source"` 值为非空 str，但其**原始值**（不 strip、不归一化大小写）不在 SOURCE_VALUES | `{p}bad source {value!r}` |
| V2 | `source` **原始值**恰为 `"adapted"`（`==` 恰等比较，不 strip）且 `source_ref` 缺失/非 str/strip 后空 | `{p}adapted requires non-empty source_ref`（至多一条） |
| V3a | verification 缺失或 None 且 `source` 原始值恰为 `"llm_generated"` | `{p}llm_generated requires verification` |
| V3b | verification 非 None 且非 dict | `{p}bad verification {value!r}` |
| V3c | verification 为 dict 时逐条记录检查（见记录目录） | 见记录目录 |

**V1c 原始值口径（评审问题 4 定稿）**：strip 只用于 V1a 的空判；V1c 的枚举成员判定
恒用原始字面值。探针（【参考-探针】）：

- `source=" original "`（strip 后合法）→ `["x: bad source ' original '"]`——
  strip 归一化后再判成员的实现在此**静默放行，不合规**；
- `source="LLM_Generated"` → `["x: bad source 'LLM_Generated'"]`（大小写敏感）；
- 同一口径贯穿 V2/V3a 与 source_counts：`source=" adapted "` 只报
  `bad source ' adapted '`、**不**触发 V2（探针）；非 None 非 dict 的 verification
  在 `llm_generated` 下只报 V3b、不报 V3a（探针：
  `{"id": "x", "source": "llm_generated", "verification": "no"}` →
  `["x: bad verification 'no'"]`）。

记录目录（verification 为 dict 时，按下序累积；`record.get` 语义）：

**门控（评审问题 1/2 定稿）**：C1 恒评估；**C2、C3 仅在 C1 未触发时评估**（即
`agents` 为 list 且 `len(agents) >= 2`——agents 非 list 或长度不足时只报 C1 一条，
**绝不对非 list 入参迭代求值 C2/C3**）；C4 三条恒独立评估、与 C1 门控无关。

| # | 评估时机 | 条件（违反则报错） | 错误消息（精确格式） |
|---|---|---|---|
| C1 | 恒评估 | `agents` 缺失/非 list（含 tuple、str）/长度 <2 | `{p}verification needs >=2 agents`（一条） |
| C2 | 仅当 C1 未触发 | 逐元素（列表序）：非 str，或 `el != el.strip()`，或 strip 后空 | `{p}bad verification agent {el!r}`（每坏元素一条，列表序） |
| C3 | 仅当 C1 未触发 | 在 agents 的**全部 str 元素**中按**原始字面值**判重——不做 strip 归一化，**含同时违反 C2 的 str 元素**；存在相等值即报 | `{p}duplicate verification agents`（至多一条，恒在全部 C2 消息之后） |
| C4a | 恒评估 | `"answers_agree"` 键缺失 | `{p}verification missing answers_agree` |
| C4b | 恒评估 | 存在但非 bool（含 None/1/0/"yes"） | `{p}bad answers_agree {value!r}` |
| C4c | 恒评估 | 存在且恰为 `False` | `{p}verification not passed` |

**C3 比较域探针（评审问题 1 定稿；【参考-探针】）**——判重比较域冻结为
"原始 str 字面值"（而非"strip 后的干净元素"），两组实现的分叉输入逐一定音：

- `agents=[" b", " b"]` →
  `["x: bad verification agent ' b'", "x: bad verification agent ' b'",
  "x: duplicate verification agents"]`（原始值相等 → 判重命中，尽管两元素均违反 C2）
- `agents=["", ""]` →
  `["x: bad verification agent ''", "x: bad verification agent ''",
  "x: duplicate verification agents"]`
- `agents=["a", "a "]` → `["x: bad verification agent 'a '"]`——原始值 `"a" != "a "`
  → **不判重**（按 strip 后值判重的实现在此追加 duplicate，不合规）
- `agents=["a", "a", " b"]` →
  `["x: bad verification agent ' b'", "x: duplicate verification agents"]`
  【测试：test_agent_duplicate_rules】

**门控探针（评审问题 2 定稿；【参考-探针】，`source="original"`）**：

- `agents="aa"` → `["x: verification needs >=2 agents"]`——对非 list 入参迭代求值
  C2/C3 的实现会追加 duplicate 消息，不合规；
- `agents=[" b"]`（长度 1，元素坏）→ `["x: verification needs >=2 agents"]`
  （C2 亦不评估——门控条件是"list 且 len ≥ 2"，非"是 list"）；
- `agents=[]` 且 `answers_agree=None` →
  `["x: verification needs >=2 agents", "x: bad answers_agree None"]`
  （C4 不受 C1 门控）；
- `agents=("a", "b")`（tuple）→ C1 一条【测试：test_agents_requirement】。

实测探针（与契约测试逐字对应）：

- `validate_item_v2({})` → `["<no-id>: missing source"]`
- `validate_item_v2({"id": "x", "source": "adapted", "verification": {}})` →
  `["x: adapted requires non-empty source_ref", "x: verification needs >=2 agents",
  "x: verification missing answers_agree"]`
- `validate_item_v2({"id": "m", "source": "nope",
  "verification": {"agents": ["a", "a"], "answers_agree": False}})` →
  `["m: bad source 'nope'", "m: duplicate verification agents", "m: verification not passed"]`
- `validate_item_v2({"id": "n", "verification": "no"})` →
  `["n: missing source", "n: bad verification 'no'"]`（V1 与 V3b 各自独立触发）
- `source="original"` 题带多余键（notes/tags 等）或带 `source_ref` → `[]`（多余键忽略）

### 3.3 `validate_bank_v2`

```python
def validate_bank_v2(items) -> list
```

逐题 `validate_item_v2` 并按**输入原序**拼接；不去重、不排序。空输入 → `[]`。
入参须为可迭代对象；**不可迭代时 TypeError 原样传播**（探针：`validate_bank_v2(42)`
→ `TypeError: 'int' object is not iterable`，§6/I11）；可迭代时对任意元素不抛异常。

### 3.4 `source_counts`

```python
def source_counts(items) -> dict
```

按 source 值计数。返回 dict 的键**恒为 SOURCE_VALUES 全集**（canonical 顺序，含 0）。
**只认原始 str 值恰等于 SOURCE_VALUES 成员的 source**（与 V1c 同一原始值口径——
`" original "` 带空白**不**入 `original` 桶，探针：
`source_counts([{"id": "x", "source": " original "}])` → 三桶全 0）；非 dict 元素、
键缺失、非 str/非法 source 不入任何桶（完整性由校验器负责，计数只认合法声明值；
记录不完整不影响计数）。每次返回新 dict（修改返回值不影响后续调用）。
不可迭代入参 → TypeError 原样传播（§6/I11）。

### 3.5 `verification_stats`

```python
def verification_stats(items) -> tuple
```

返回 `(total, verified)` 二元组（tuple，防原地改写）：`total` = 可迭代元素总数
（非 dict 元素也计入）；`verified` = 带完整且通过的双代理验证记录的条数——
判定谓词 = verification 为 dict 且记录目录 C1..C4 零消息（**与 source 无关**：
original 题带通过记录同样计入，探针：
`verification_stats([{"id": "x", "source": " original ", "verification": {"agents": ["a", "b"], "answers_agree": True}}])` → `(1, 1)`，
另见【测试：test_verification_stats_closed_form】）。不可迭代入参 → TypeError
原样传播（§6/I11）。

## 4. 不变量（编号列出；证据标注见各条）

- I1 **常量冻结**：`SCHEMA_VERSION == 2`；`SOURCE_VALUES` 恰为
  `("original", "adapted", "llm_generated")` 且为 tuple（【测试：test_schema_constants】）。
- I2 **合法输入零消息**：original（无/None/完整 verification 均可）、adapted（非空
  source_ref）、llm_generated（通过的完整记录）都返回 `[]`；多余键一律忽略
  （【测试：test_valid_original_without_verification_passes、test_valid_adapted_passes_with_source_ref、
  test_valid_llm_generated_with_full_record_passes、test_extra_keys_ignored】）。
- I3 **source 完整性与原始值口径**：键缺失/str 且 strip 后空 → `missing source`；
  非 str → `bad source {repr}`；非空 str 的**原始值**不在 SOURCE_VALUES →
  `bad source {repr}`（strip 仅用于空判；`" original "` 必报不放行）。
  （【测试：test_missing_source、test_bad_source】+【参考-探针】）
- I4 **改编溯源强制**：source 原始值恰为 `"adapted"` 时必须附非空 str `source_ref`，
  缺失/空/空白/非 str 一律同一条消息；其他情形（含只报 V1c 的 `" adapted "`）的
  `source_ref` 不检查不报错（【测试：test_adapted_requires_non_empty_source_ref、
  test_source_ref_ignored_for_other_sources】+【参考-探针】）。
- I5 **LLM 入库门与 C1 门控**：source 原始值恰为 `"llm_generated"` 必须带
  verification（缺失与 null 同罪；非 None 非 dict 只报 V3b）。记录要求：
  C1 恒评估——agents 缺失/非 list/长度 <2 → `needs >=2 agents` 恰一条，**此时
  C2/C3 不评估**；C1 未触发时 C2 对每个坏元素报一条（列表序）、C3 对全部 str 元素
  按**原始字面值**判重（不 strip、含 C2 坏元素）至多一条且居全部 C2 消息之后；
  C4 三条恒独立评估；`answers_agree` 必须恰为 bool `True`——缺失/非 bool/`False`
  各有专属消息（【测试：test_llm_generated_requires_verification、
  test_agents_requirement、test_agent_element_rules、test_agent_duplicate_rules、
  test_answers_agree_rules】+【参考-探针：C3 比较域与门控探针】）。
- I6 **累积纪律**：单题消息按 V1→V2→V3、C1→C2→C3→C4 固定顺序累积、不短路、
  规则独立评估实际值（【测试：test_rule_accumulation_order】）。
- I7 **全函数**：非 dict 输入（None/int/str/list/bool/float）只返回
  `["item is not a dict"]`；对恶劣输入电池（嵌套容器/错型/空结构）永不抛异常、
  消息全为 str（【测试：test_non_dict_items、test_never_raises_battery】）。
- I8 **前缀纪律**：id 缺失 → `<no-id>: `；id 存在按值字面渲染（f-string，无 repr
  引号；含 falsy/非 str/dict id）（【测试：test_id_prefix_rendering】+
  【参考-探针：`id={"x": 1}` → `"{'x': 1}: "`】）。
- I9 **bank 语义**：输入原序累积、不去重不排序；空输入 → `[]`；非 dict 元素产生
  `item is not a dict` 消息（【测试：test_bank_accumulates_in_input_order_without_dedup、
  test_bank_empty_and_non_dict_elements】）。
- I10 **统计闭式与纯函数性**：source_counts 键恒为 canonical 全集（含 0）、只认与
  SOURCE_VALUES 恰等的原始 str 值、非 dict 与非法值不入桶、每次新 dict；
  verification_stats 返回 tuple 且 verified 判定与记录目录 C1..C4 零消息精确一致、
  与 source 无关；三个函数不改入参、同输入同输出
  （【测试：test_source_counts_canonical_and_fresh、test_verification_stats_closed_form、
  test_purity_inputs_not_modified_and_repeatable】+【参考-探针】）。
- I11 **域外传播纪律**：validate_bank_v2 / source_counts / verification_stats 对
  **不可迭代**入参 TypeError 原样传播——不得捕获、吞掉、转为消息列表或返回部分
  结果（异常文本不冻结，冻结传播语义）；对可迭代入参则对任意元素不抛异常
  （【参考-探针：三函数对 `42` 均自然抛 `TypeError: 'int' object is not iterable`】）。

## 5. 确定性与随机性

- 全部四个函数均为纯函数：输出只依赖入参值；禁止 `random`、hash 序、系统时钟、
  环境读取、任何 IO。
- 错误消息中嵌入的违规值一律经 `repr` 渲染（str 值因此带引号：`'scraped'`；非 str
  值如 `42`/`None` 同其 repr——CPython 3.12 x64 下逐位确定）；消息前缀中的 id 经
  f-string 字面渲染（不带引号，见 I8）。
- I3–I6 的消息全等断言与 I10 的统计闭式是逐位比对点。

## 6. 错误行为

| 输入情形 | 必须的行为 | 证据 |
|---|---|---|
| `validate_item_v2`，任意输入（含恶劣电池） | **不抛异常**，返回 0..n 条 str 消息 | 【测试：test_never_raises_battery】 |
| 三个可迭代消费函数（validate_bank_v2 / source_counts / verification_stats），入参可迭代 | 不抛异常，逐元素按 §3 对应条款处理 | 【测试：test_bank_*、test_source_counts_canonical_and_fresh、test_verification_stats_closed_form、test_purity_inputs_not_modified_and_repeatable】 |
| 同上三函数，入参**不可迭代**（int/None 等） | **TypeError 原样传播**——不捕获、不转消息、不返回部分结果（评审问题 3 定稿：防御式吞掉返回空统计 = 不合规；异常文本不冻结） | 【参考-探针：`source_counts(42)` / `verification_stats(42)` / `validate_bank_v2(42)` 均 `TypeError: 'int' object is not iterable`】 |
| bank/统计中的非 dict 元素 | `item is not a dict` 一条后继续（bank）；跳过不入桶 / 仅计 total（统计） | 【测试：test_bank_empty_and_non_dict_elements、test_source_counts_canonical_and_fresh、test_verification_stats_closed_form】 |
| 未知键 | 忽略 | 【测试：test_extra_keys_ignored】 |
| original/adapted 缺 verification | 合法的"未验证"状态，零消息 | 【测试：test_valid_original_without_verification_passes】 |

错误经消息通道上报，供 `tools/validate_knowledge.py` 累积打印。"本模块不抛异常"
的精确范围：`validate_item_v2` 对任意输入；三个可迭代消费函数对可迭代入参——
不可迭代入参的 TypeError 传播（I11）是唯一例外。

## 7. 非目标

- **不改冻结模块**：itembank.py 的 `validate_item`/`validate_all`（v1 字段校验）、
  `xuexing.types.Item`、`agent_shell.try_accept_draft` 均保持现状不动；v2 校验
  面向 dict 层，与 Item 对象层解耦。
- **不做双代理解题**：verification 记录的真实性由入库流程与数据测试保证；本模块
  只验证记录的结构完整性与通过态，不重解题、不验证 `source_ref` 指向的真题存在性。
- **不读文件、不合并年级**：题库装载/合并属 `tools/validate_knowledge.py`；模块只吃
  现成 dict。
- **不产出修复建议/报告对象**：消息字符串列表即终点，无 report dataclass。
- **不管 v1 字段**（item_type/stem/answer/kps/difficulty/options…）：仍由冻结模块
  itembank.py 校验，本模块不检查。
- **不强制 original/adapted 带双代理验证**：verification 键缺失/null 是合法状态；
  覆盖推进属数据侧迭代（validate_knowledge 摘要行披露 verified 计数；当前库内
  321/321 全覆盖是数据现状——§1，本模块对此不作要求）。

## 附录 A：对抗评审修复记录（drafts → frozen，2026-09-29）

| # | 评审问题（severity） | 复核方式（定稿会话实测） | 修复 |
|---|---|---|---|
| 1 | C3 判重比较域未定：按 str 元素原始字面值（含 C2 坏元素）判重 vs 仅在通过 C2 的干净元素间按 strip 后值判重——`[" b"," b"]`/`["",""]` 与 `["a","a "]` 两组输入两读法结论相反（minor） | 探针（参考实现记录目录）：`[" b"," b"]` → 坏×2 + duplicate；`["",""]` → 坏×2 + duplicate；`["a","a "]` → 仅坏 `'a '`、**无** duplicate；`["a","a"," b"]` → 均在前 + duplicate（与 test_agent_duplicate_rules 一致） | §3.2 记录目录 C3 行冻结：比较域 = agents 全部 str 元素的**原始字面值**（不 strip、含 C2 坏元素），附 4 组探针定音；I5 并入 |
| 2 | C3（及 C2）在 agents 非 list 时是否求值未定：按"不短路、规则独立评估"字面执行会对 str 迭代求值追加 duplicate vs 门控为"元素=列表元素"只报 C1——`agents="aa"` 两实现均可通过 test_agents_requirement 而行为不同（minor） | 探针：`agents="aa"` → 仅 `needs >=2 agents`；`agents=[" b"]`（长度 1）→ 仅 C1（C2 亦不评估）；`agents=[]`+`answers_agree=None` → C1 + C4b（C4 不受门控）；tuple → 仅 C1【测试】 | §3.2 记录目录新增显式门控：C2/C3 仅在 C1 未触发（list 且 len ≥ 2）时评估，附门控探针；I5/§4 并入 |
| 3 | source_counts/verification_stats 对域外（不可迭代）入参行为未定：自然抛 TypeError vs 按"不抛异常"防御式吞掉返回空统计——契约测试从不传不可迭代对象，两实现均合法（minor） | 探针：`source_counts(42)` / `verification_stats(42)` / `validate_bank_v2(42)` 均自然抛 `TypeError: 'int' object is not iterable`（无捕获） | §6 错误行为表 + I11 + §3.3/3.4/3.5：TypeError 原样传播冻结为**要求**（吞掉 = 不合规）；§1/§6 的"不抛异常"表述限定精确范围 |
| 4 | V1c 的 SOURCE_VALUES 成员判定用原始值还是 strip 后值未定：`" original "` 按字面应报 bad source，strip 归一化后判定的实现会静默放行（minor） | 探针：`source=" original "` → `bad source ' original '`；`"LLM_Generated"` → `bad source`（大小写敏感）；`" adapted "` 不触发 V2；source_counts 对 `" original "` 不入桶（同一原始值口径）；llm + 非 dict verification 只报 V3b | §3.2 V1c/V2/V3a 行冻结原始值口径 + 探针；I3/I4 并入；source_counts 同口径（§3.4/I10） |
| 5 | §1 事实性陈述与数据测试相反：草稿称真实题库"无双代理验证记录、由数据测试锁定"，而 tests/data/test_itembank_v2_data.py 的 `test_real_verification_records_honest` 断言 `verified == total`（minor） | 运行 `python -m pytest tests/contract/test_itembank_v2_contract.py tests/data/test_itembank_v2_data.py -q` → 28 passed；grep data/items/*.json：321 题（129+87+105）均带 `"agents": ["m3-reviewer", "night-reverify-20260929"]`；全套 558 collected、退出码 0 | §1 事实段重写：全库 original（来源闭式）+ 2026-09-29 双代理回填后全库带通过记录（verified==total），标注锁定测试；注明属数据现状陈述、非模块行为条款 |

## 附录 B：验证方式

- 参考实现基线（定稿会话运行核实）：`python -m pytest
  tests/contract/test_itembank_v2_contract.py tests/data/test_itembank_v2_data.py -q`
  → 28 passed（24 契约 + 4 数据）；全套 `python -m pytest -q` → 558 collected、
  退出码 0（全绿）。Python：CPython 3.12.10 x64（Windows）。
- 导入路径由 tests/conftest.py:14-16 接入（`sys.path` 加 `src/`），无需设
  PYTHONPATH；pytest.ini：testpaths=tests, addopts=-q。
- 重生成实例门控：`python tools/run_contract.py --impl-dir <目录> --modules itembank_v2`
  （tools/run_contract.py 的 MODULE_TEST_FILES 将 itembank_v2 登记为
  test_itembank_v2_contract.py；`--impl-dir` 经 XX_IMPL_DIR/XX_MODULES 注入，
  装载机制见 tests/conftest.py:22-34——单文件装载为顶层模块名
  `_regen_itembank_v2`，顶替 `sys.modules["xuexing.itembank_v2"]`）。等价手跑：
  `XX_IMPL_DIR=<目录> python -m pytest tests/contract/test_itembank_v2_contract.py`。
- 本规格所有【参考-探针】结论均在定稿会话（2026-09-29）以探针脚本对参考实现运行
  核实，探针输出已摘录于正文对应条款。
