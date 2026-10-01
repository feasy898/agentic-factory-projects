# grading 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> **版本**：定稿 v1（由 drafts 版经对抗评审修复而来，修订记录见附录 A）。
> 标注「〔测试裁定〕」的行为由 `tests/contract/test_grading_contract.py` 直接断言；
> 标注「〔参考裁定〕」的行为契约测试未仲裁，按参考实现 `src/xuexing/grading.py` 冻结，
> 并在当地注明本冻结轮的实测探针（CPython 3.12.10 x64；测试基线
> `python -m pytest tests/contract/test_grading_contract.py -q` 全绿）。未标注裁定的
> 实测例子同样取自参考实现并有测试对照。本文自包含，不引用其他规格文档。

## 1. 目的

grading 是主观题判分接口：在此之前 `Response.correct` 只能由教师/批改端外部给定，
本模块把 fill/solve 的**数值答案**（分数/带分数/百分数/小数，可带单位）做规则化归一化后
按值比对，choice 题按选项标签/全文自动判，并经 `grade_to_response` 直接产出
`Response`（correct 字段由系统判出）。行为契约：**归一化规则表**（N1–N5，逐条可手算
复核）、**判分确定性**（全模块纯函数，同输入同输出）与**判定次序**（§3.7/§3.8/§3.9
的步骤顺序为绑定条款——次序不同会在本文覆盖的输入上产生不同结果，见附录 A/R4）。

## 2. 允许的依赖

- Python 标准库（至少 `re`）
- `xuexing.types` —— **必须绝对导入**：`from xuexing.types import Response`
- 禁止：其他 xuexing 模块（**无例外**）、第三方库、文件/网络 IO、全局可变状态
- 禁止：随机、系统时钟、环境读取（全模块无时间戳字段，无豁免）

重生成实例的装载约束（实测结论）：禁止相对导入（注入装载为顶层模块名
`_regen_grading`，相对导入在装载时失败）；不使用 `from __future__ import annotations`；
注解直接写真实对象（`tuple[str, str | None]` 等，装载环境不做延迟求值）。

## 3. 公开 API

模块必须暴露以下名字（契约测试以
`from xuexing.grading import GradingError, GRADE_TOLERANCE, UNIT_ALIASES, normalize_answer,
parse_numeric, split_unit, numeric_equal, grade_fill, grade_choice, grade, grade_to_response`
导入）：

### 3.1 常量与异常

- `GradingError(ValueError)`：本模块唯一异常类型（ValueError 直接子类）
  〔测试裁定 `test_frozen_constants`〕。
- `GRADE_TOLERANCE = 1e-9`：数值判等的相对容差（见 §3.5）〔测试裁定〕。
- `UNIT_ALIASES: dict[str, str]`：单位别名表，键为**表层写法**（含规范形自身），
  值为**规范单位**；不变式：每个值本身也是键（规范闭包）〔测试裁定〕。
  冻结内容（28 表层写法 → 23 规范单位）：

  | 规范单位 | 表层写法 |
  |---|---|
  | 千米 | 千米、公里 |
  | 米 / 厘米 / 毫米 | 各自同名 |
  | 平方千米 | 平方千米、平方公里 |
  | 平方米 / 平方分米 / 平方厘米 | 各自同名 |
  | 立方米 / 立方分米 / 立方厘米 | 各自同名 |
  | 公顷 | 公顷 |
  | 吨 / 克 | 各自同名 |
  | 千克 | 千克、公斤 |
  | 元 / 角 / 分 | 各自同名 |
  | 升 / 毫升 | 各自同名 |
  | 小时 | 小时、时 |
  | 分（时间） | 分钟 |
  | 秒 / 度 | 各自同名 |

  规范形自映射对照：千米、米、千克、元、分、小时、度等均
  `UNIT_ALIASES[canon] == canon`〔测试裁定〕。注意表中**没有**裸的「分米」，
  只有 平方分米 / 立方分米。

- **不做单位换算，只做别名归一**：
  - 跨规范单位的换算一律不存在：`2千米 ≠ 2000米`、`2米 ≠ 200厘米`——单位门
    （§3.7 步骤 5）判 `False`〔测试裁定 `test_unit_gate`：`2米` 配 `2千米` → False〕；
  - 同一规范单位的**别名写法判等**：`grade_fill(answer="2千米", learner_answer="2公里")`
    → **True**、`grade_fill(answer="2千克", "2公斤")` → True、
    `grade_fill(answer="2小时", "2时")` → True、`grade_fill(answer="30分钟", "30分")`
    → True〔以上均参考裁定，实测探针；是别名表 + 单位门的直接推论。契约测试只覆盖
    反向对照（`answer="2米"` 配 `"2公里"`/`"2千米"` → False，因 米≠千米），
    未覆盖"答案写规范单位、作答写别名"的输入对，本冻结按别名表钉死为判等〕；
  - 单位只做"归一别名后字符串相等"比较，无任何数值换算。

### 3.2 `normalize_answer(text: str) -> str` —— 归一化规则表 N1–N5

输入必须为 `str`（非 str，含 None/bool/int/float/bytes/list → `GradingError`）。
五条规则**按序**执行：

- **N1 全角折叠**：码点在 `[0xFF01, 0xFF5E]` 的字符映射为 `chr(ord(c) − 0xFEE0)`
  （`３`→`3`、`．`→`.`、`，`→`,`、`＜`→`<`、`＋`→`+`、`－`→`-`、`Ａ`→`A`，
  大小写最终由 N5 统一）；`U+3000` 全角空格 → 半角空格。其余字符原样保留
  （`。`、`、`、`²`、`π`、`≤` 等不在折叠范围）。
- **N2 空白折叠**：内部空白串（Python `re` 语义的 `\s+`）折叠为单个半角空格，
  再去首尾空白。
- **N3 尾部剥离**：从右端循环删除集合 `{'。', '、', ',', '.', ';', '!', '?', 空白}`
  中的字符（`"3.5。"`→`"3.5"`、`"3 。"`→`"3"`、`"c."`→`"c"`、`"三角形、"`→`"三角形"`）。
  只剥尾部，不动内部。（N2 执行后串内空白只可能是单个半角空格，故此处的
  「空白」实践上即半角空格。）
- **N4 千分位逗号删除**：删除所有满足"左侧是 ASCII 数字 `0-9`、右侧**恰为 3 位
  ASCII 数字**（第 4 位仍是数字则不算）"的逗号（`"1,234"`→`"1234"`、
  `"1,234,567"`→`"1234567"`、`"1,234.5"`→`"1234.5"`；保留：`"12,34"`、`"1,2345"`、
  坐标 `"(4,1)"`、`"(-1,-1)"`、`"x=5,y=2"`）。
- **N5 小写化**：`str.lower()`。

实测〔测试裁定 `test_normalize_rule_table`〕：`"３.５元"`→`"3.5元"`；
`"　X＋１　"`→`"x+1"`；`"１，２３４"`→`"1234"`；`"x=5，y=2"`→`"x=5,y=2"`；
`"  3.5   元 "`→`"3.5 元"`；`"a\n\tb"`→`"a b"`；`"－300元"`→`"-300元"`；
`"＜"`→`"<"`；`"ACE"`→`"ace"`。对规则表内全部输入**幂等**
（`normalize_answer(normalize_answer(x)) == normalize_answer(x)`，
`test_normalize_idempotent_on_rule_table`）。

### 3.3 `parse_numeric(text: str) -> float | None`

解析**已归一化**的数值文本（本函数不做归一化、不做全角折叠/小写化）；不可解析 →
`None`（不抛异常）；输入非 str → `GradingError`〔测试裁定
`test_parse_numeric_rejects_non_str`〕。两个全局限定〔参考裁定，实测探针〕：

- 数字字符类一律是 ASCII `[0-9]`：`parse_numeric("１/２")` → `None`（unicode 数字不匹配）；
- 每条模式必须匹配**整个**输入（全文锚定）：`parse_numeric("1\n")` → `None`
  （尾随换行也算不匹配）。

按序尝试（前一步命中即返回；全表〔测试裁定 `test_parse_numeric_table`〕）：

1. **百分数**：以 `%` 结尾时剥掉 `%`（余部再 `strip()`）按 2–4 解析，值再除以 100
   （`"50%"`→`0.5`、`"50 %"`→`0.5`、`"-50%"`→`-0.5`、`"1/2%"`→`0.005`、
   `"1 1/2%"`→`0.015`；`"50%%"` 的余部含 `%`，2–4 均不匹配 → `None`）。
2. **带分数**：`[+-]?[0-9]+` 后接**一个空格**、`[0-9]+`、`\s*/\s*`、`[0-9]+`（全文）→
   `sign · (|a| + b/c)`，`sign` 只取整数部的符号、作用于整体，`a` 为整数部绝对值，
   `b`、`c` 为分子分母；分母 0 → `None`（`"1 1/2"`→`1.5`、`"1 2/4"`→`1.5`、
   `"-1 1/2"`→`-1.5`、`"1 1 / 2"`→`1.5`、`"1 1/0"`→`None`）。
3. **分数**：`[+-]?[0-9]+ \s*/\s* [0-9]+`（全文）→ `a/b`；分母 0 → `None`
   （`"1/2"`→`0.5`、`"2/4"`→`0.5`、`"1 / 2"`→`0.5`、`"1 /2"`→`0.5`、`"0/5"`→`0.0`、
   `"-1/2"`→`-0.5`、`"3/0"`→`None`）。
4. **小数**：`[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?`（全文）→ 按
   IEEE 754 浮点字面量解析（`"0.5"`、`"-8"`、`"+3"`、`".5"`→`0.5`、`"3."`→`3.0`、
   `"1e3"`→`1000.0`；`"nan"`/`"inf"`/`"Infinity"` 不匹配文法，一律 `None`）。
5. 其余（`""`、`"abc"`、`"1 2"`、`"--1"`、`"3..5"`）→ `None`。

所有正例的返回值与上述字面值**逐位相等**（IEEE 754 解析与除法的唯一结果）。

### 3.4 `split_unit(text: str) -> tuple[str, str | None]`

从字符串尾部剥离单位。本函数不做任何归一化（先 `normalize_answer` 再调用）
〔测试裁定 `test_split_unit_does_not_normalize`：`split_unit("3.5元 ")` →
`("3.5元 ", None)`，尾部空格阻断命中〕。扫描规则（顺序为绑定条款）：

1. 记 `L` = `UNIT_ALIASES` 键的最大字符数（= 4，如 `平方公里`）。对宽度
   `w = min(len(text), L), …, 1` 依次取后缀 `text[-w:]`。
2. **首个**命中 `UNIT_ALIASES` 的后缀（即最长后缀优先：`"3平方米"`→`("3","平方米")`
   而非 `("3平方","米")`〔测试裁定〕）：
   - 剩余部 `text[:-w].strip()` 非空 → 返回 `(剩余部, 规范单位)`；
   - 剩余部为空（纯单位词）→ **立即返回 `(原文, None)`，不再尝试更短后缀**
     〔参考裁定，实测探针〕：`split_unit("小时")` → `("小时", None)`（不回退到
     `时` 而产生 `("小", "小时")`）；`split_unit("千米")` → `("千米", None)`；
     `split_unit("公里")` → `("公里", None)`。
3. 所有宽度都未命中 → `(原文, None)`。

实测全表〔测试裁定 `test_split_unit_table`〕：`"3.5元"`→`("3.5","元")`；
`"2千米"`→`("2","千米")`；`"2公里"`→`("2","千米")`；`"3平方米"`→`("3","平方米")`；
`"3平方公里"`→`("3","平方千米")`；`"30分钟"`/`"30分"`→`("30","分")`；
`"2时"`/`"2小时"`→`("2","小时")`；`"2公斤"`→`("2","千克")`；`"3 米"`→`("3","米")`
（剩余部 strip）；`"50%"`→`("50%",None)`（`%` 不是单位）；`"元"`→`("元",None)`；
`"2kg"`→`("2kg",None)`（表外写法）；`"1小时30分"`→`("1小时30","分")`。

### 3.5 `numeric_equal(a: float, b: float) -> bool`

`abs(a − b) <= GRADE_TOLERANCE * max(1.0, |a|, |b|)`（相对容差，零附近为绝对带
`1e-9`）。实测〔测试裁定 `test_numeric_equal_tolerance_semantics`〕：
`(1/3, 0.3333333333333333)`→True；`(1/3, 0.33)`→False；`(0.5, 0.5+5e-10)`→True；
`(1.0, 1.0+2e-9)`→False；`(0.0, 1e-12)`→True；`(0.5, 0.25)`→False；交换参数结果不变。

### 3.6 字符串等值键（内部规则，适用范围穷举）

**键形态** `key(s) = 删除 normalize_answer(s) 中全部空白字符`
（`"x＋1"` 与 `"x+1"` 等键；`"鸡 6 只，兔 4 只"` 与 `"鸡6只,兔4只"` 等键；
`"(4, 1)"` 与 `"(4,1)"` 等键）。**键形态只用于以下两处比较**（穷举，无其他）：

1. `grade_fill` 步骤 6 的字面等值支（§3.7）；
2. `grade_choice` 解析过程的**全文趟**（§3.8）。

**标签比较不用键形态**〔参考裁定，实测探针〕：`grade_choice` 的标签趟使用归一化标签上的
**直接字符串相等（`==`）**。标签是 `normalize_answer(option)` 在第一个 `"."` 前的段再
`strip()`，无首尾空白但**可能含内部空白**（选项 `"a b. x"` 的标签为 `"a b"`），此时
作答必须逐字符含该空格才命中。分叉探针：options `["ab. 1", "a b. x"]`、answer 存全文
`"a b. x"`、learner `"a b"` → 判 **True**（标签趟 `==` 命中下标 1）；若标签趟改用键
形态会命中下标 0 而判 False。契约测试的标签均为无空白单词（`a`–`d`、`甲`/`乙`），
两种读法在测试输入上不可区分，本冻结按参考实现钉死 `==` 读法。

### 3.7 `grade_fill(item, learner_answer) -> bool`

`item` 鸭子类型：用到 `item.answer: str`。`learner_answer` 为 `None` → `False`
（未作答）；非 str 非 None → `GradingError`。**步骤（顺序为绑定条款，不得调换）**：

1. **类型与未作答**：`learner_answer` 非 str 且非 None → `GradingError`；
   `learner_answer is None` → `False`。**未作答短路先于一切题目侧校验**
   〔参考裁定，实测探针：`item.answer=None` 的题配 `None` → `False`，不抛错〕。
2. `ca = normalize_answer(item.answer)`。`item.answer` 非 str 在此抛 `GradingError`
   ——**即使 `learner_answer` 是空白串**〔参考裁定，实测探针：
   `item.answer=None` 的题配 `""` → `GradingError`，而非 False〕。
3. `la = normalize_answer(learner_answer)`；`la == ""` → `False`。
4. `(ca_num, ca_unit) = split_unit(ca)`；`(la_num, la_unit) = split_unit(la)`。
5. **单位门**：`ca_unit != la_unit` → `False`（缺单位、异单位判错；`None == None`
   通过；别名已在步骤 2–4 归一并拆分到同一规范单位）。
6. `ca_val = parse_numeric(ca_num)`；`la_val = parse_numeric(la_num)`；
   两者皆非 `None` → `numeric_equal(ca_val, la_val)`；否则 →
   `key(ca_num) == key(la_num)`（字面等值支，如 `两元`、`x+1`、`鸡6只，兔4只`、
   `(4,1)`）。

实测行为表（canon 值 → 学习者答案 → 结果；除标注外全部〔测试裁定
`test_numeric_equivalence_closure` / `test_fill_unknown_and_empty_answers` /
`test_unit_gate` / `test_literal_string_branch` / `test_coordinate_comma`〕）：

| item.answer | True 的写法 | False 的写法 |
|---|---|---|
| `1/2` | `0.5`、`2/4`、`50%`、`１/２`、`1 /2`、`0.5 ` | `0.33`、`1/3`、`abc`、`1/2 元`〔参考裁定〕、None、`""`、`"   "` |
| `-300元` | `－300元`、` -300 元 ` | `-300`（缺单位）、`-300米`（异单位）、`-600元`、`负300元`（字面支） |
| `2米` | `2 米` | `2`、`2公里`、`2千米`、`两米` |
| `30%` | `0.3`、`3/10`、`30 %` | `0.31`、`0.3元` |
| `1 1/2` | `1.5`、`3/2`、`１ １/２`、`1 2/4` | `11/2`（=5.5） |
| `x+1` | `X＋1`、`x + 1` | `x+2`、`2x+1` |
| `鸡6只，兔4只` | `鸡 6 只，兔 4 只` | `鸡7只，兔4只` |
| `(4,1)` | `(4, 1)`、`(4，1)` | `(41)`、`(4,2)` |
| `<` | `<` | `>`、`＞`、`≤` |

注意区分：本表 `2公里`/`2千米` 出现在 **False** 列，是相对答案 `2米`（跨规范单位，
无换算）；相对答案 `2千米` 时 `2公里` 判 **True**（别名判等，见 §3.1）。

### 3.8 `grade_choice(item, learner_answer) -> bool`

`item` 鸭子类型：用到 `item.options: list[str]`、`item.answer: str`、`item.id`。
**步骤（顺序为绑定条款，不得调换）**：

1. **类型与未作答**：`learner_answer` 非 str 且非 None → `GradingError`；`None` →
   `False`。**未作答短路优先于题目校验**——answer 不在任何选项中、options 为空时
   配 `None` 仍判 `False`〔测试裁定
   `test_grade_choice_invalid_item_raises_but_none_short_circuits`〕。
2. `texts = [normalize_answer(o) for o in item.options]`（选项含非 str 在此抛
   `GradingError`）；`labels = [t.split(".", 1)[0].strip() for t in texts]`（全角
   句点经 N1 折叠后同样切分：`"A. 1"`→label `"a"`、`"甲. 3"`→`"甲"`〔测试裁定〕；
   无句点的选项其整个归一化文本即标签）。
3. `la = normalize_answer(learner_answer)`；`la == ""` → `False`。该短路在**选项归一
   之后、正确项解析之前**〔参考裁定，实测探针：非法题目（answer=`"E"` 不在选项）+
   空白作答 → `False`，不是 `GradingError`〕。
4. **解析正确项**：`correct = resolve(normalize_answer(item.answer), labels, texts)`；
   `correct is None` → `GradingError`（题目本身非法：answer 不在任何选项的标签/全文
   中，options 为空亦然）〔测试裁定〕。
5. **解析学习者项**：`given = resolve(la, labels, texts)`；`given is None` → `False`
   （写了不存在的内容，如作答 `2` 而选项标签是 `A`–`D`）〔测试裁定〕。
6. 判分 = `given == correct`。

**`resolve(t, labels, texts)`** —— 两趟全局扫描（趟序与取法均为绑定条款
〔参考裁定〕）：

- **第一趟（标签）**：返回 `labels` 中与 `t` **直接相等（`==`；键形态不适用，见
  §3.6）** 的**最小下标**；命中则整个 resolve 结束——**标签优先于全文**：即使全文趟
  能在更小下标命中，也以标签趟结果为准。
- **第二趟（全文）**：仅当第一趟未命中，返回满足 `key(t) == key(texts[i])` 的
  **最小下标 i**。
- 两趟都未命中 → `None`。

**并列裁定**〔参考裁定，实测探针〕：两趟各自都取 options 顺序的**第一个（最小下标）**
命中——选项全文（去空白后）重复时选最前面的那个，不存在"取末个"的读法。探针：
options `["A. x", "A.x"]`（两选项全文键同为 `"a.x"`）、answer 存 `"A.x"`、
learner `"a"` → `True`（正确项与作答都解析到下标 0；若全文趟取末个，正确项为下标 1，
会判 False）。

实测〔测试裁定 `test_grade_choice_label_and_text` /
`test_grade_choice_answer_stored_as_full_text` / `test_grade_choice_chinese_labels` /
`test_grade_choice_invalid_item_raises_but_none_short_circuits`〕：options
`["A. -2a>-2b","B. ac²>bc²","C. a-1>b-1","D. 1/a<1/b"]`、answer `"C"`：
`"C"`/`"c"`/`"c."`/`" C "`/`"C. a-1>b-1"`/`"c．a-1>b-1"` 均 True；`"A"`/`"D"`/
`"a-1>b-1"`/`"E"`/`"2"`/`""`/`"   "`/`None` 均 False。answer 存为全文 `"A. x≤3"`
时 `"a"`/`"A"` 仍 True、`"b"`/`"x≤3"`（全文片段）False。中文标签 options
`["甲. 3", "乙. 4"]`、answer `"乙"`：`"乙"` True、`"甲"`/`"3"` False。

### 3.9 `grade(item, learner_answer) -> bool` 与 `grade_to_response`

- `grade`：按 `item.item_type` 分派——`"choice"` → `grade_choice`；`"fill"`/`"solve"`
  → `grade_fill`；其他 → `GradingError`〔测试裁定 `test_grade_dispatch_and_errors`〕。
  **分派先于未作答短路**〔参考裁定，实测探针〕：`item_type` 非法时即使
  `learner_answer=None` 也抛 `GradingError`，不返回 `False`。
- `grade_to_response(item, learner_answer, response_ms=None) -> Response`：
  返回 `Response(item_id=item.id, correct=grade(item, learner_answer),
  learner_answer=learner_answer, response_ms=response_ms)`（字段原样透传，含 None）
  〔测试裁定 `test_grade_to_response`〕。

## 4. 不变量（编号列出，全部可被契约测试检验）

- I1 **归一化规则表**：N1–N5 按序执行、逐条有实测对照（§3.2；
  `test_normalize_rule_table`）。
- I2 **幂等性**：规则表内全部输入 `normalize∘normalize == normalize`
  （`test_normalize_idempotent_on_rule_table`）。
- I3 **数值等价闭包**：`{"0.5", "1/2", "2/4", "50%"}` 两两互判 True，且 `1/2` 题
  另接受 `１/２`、`1 /2`、`0.5 `（§3.7 表；`test_numeric_equivalence_closure`）；
  ε 语义按 §3.5 全部手算对照（`test_numeric_equal_tolerance_semantics`）。
- I4 **单位门**：缺单位/异单位判错；无换算（`2千米 ≠ 2米`、`2千米 ≠ 2000米`）；
  别名写法判等由 §3.1 别名表 + 单位门推出（`公里`→规范 `千米`，
  `grade_fill(answer="2千米", "2公里")` = True〔参考裁定〕；`公斤=千克`、
  `时=小时`、`分钟=分` 同理）（`test_unit_gate`、`test_frozen_constants`、
  `test_split_unit_table`）。
- I5 **千分位逗号不伤坐标**：`"(4,1)"` 自身判对、与 `"(4, 1)"`/`"(4，1)"` 判对、
  与 `"(41)"`/`"(4,2)"` 判错（`test_coordinate_comma`）。
- I6 **choice 解析确定性**：两趟全局扫描（标签趟先于全文趟、各自取最小下标、
  标签比较用直接相等，§3.6/§3.8）；未作答/未知 token 一律 False；非法 choice 题
  （answer 不在任何选项、options 空）抛 `GradingError`（`test_grade_choice_*`）。
- I7 **分派完备与判定次序**：choice/fill/solve 三型可判，未知 item_type 抛
  `GradingError` 且**先于未作答短路**；`learner_answer` 非 str 非 None 抛
  `GradingError`，None 一律 `False` 且先于题目侧校验；空白作答的短路位置按
  §3.7 步骤 2–3、§3.8 步骤 2–3 的绑定次序（`test_grade_dispatch_and_errors`、
  `test_fill_unknown_and_empty_answers`、
  `test_grade_choice_invalid_item_raises_but_none_short_circuits`）。
- I8 **Response 产出**：`grade_to_response` 字段透传、dataclass 相等可复判
  （`test_grade_to_response`）。
- I9 **判分确定性**：同一 `(item, learner_answer)` 重复判分（≥30 次）结果恒等；
  全模块无随机/时钟/IO（`test_determinism`）。
- I10 **纯度**：判分不修改入参 item（dataclass 快照前后相等）（`test_purity`）。

## 5. 确定性与随机性

- 全部公开函数为纯函数：输出只依赖入参；禁止 `random`、hash 序、系统时钟、
  环境读取、文件/网络 IO、全局可变状态。无时间戳字段（无豁免）。
- 浮点可复现性：`float()` 解析与 `/` 除法为 IEEE 唯一结果；判等只经
  §3.5 的容差式，不做 round。§3.3/§3.5/§3.7 表中每个值都是逐位对照点。

## 6. 错误行为

| 非法输入 | 行为 |
|---|---|
| `normalize_answer`/`parse_numeric`/`split_unit` 入参非 str | `GradingError` |
| `grade*` 的 `learner_answer` 非 str 且非 None | `GradingError` |
| `learner_answer` 为 `None`（item_type 合法） | 容忍，判 `False`；**先于 grade_fill/grade_choice 内一切题目侧校验**（题目非法也 False） |
| fill 题目 `item.answer` 非 str | `GradingError`（§3.7 步骤 2）；`learner_answer=None` 先短路 `False`〔参考裁定〕 |
| choice 题目 options 含非 str / `item.answer` 非 str | `GradingError`（§3.8 步骤 2/4；`learner_answer=None` 先短路 `False`） |
| `learner_answer` 归一化后为空 | fill：`item.answer` 归一**之后**判 `False`（answer 非法时抛 `GradingError`）〔参考裁定〕；choice：选项归一之后、正确项解析**之前**判 `False`（非法题目 + 空白作答 → `False`）〔参考裁定〕 |
| choice 题答案无法解析为任何选项（含 options 空） | `GradingError`（但 `None`/空白学习者先短路 `False`） |
| `item.item_type` 不在 {choice, fill, solve} | `GradingError`（**分派先于未作答短路**，`learner_answer=None` 也抛）〔参考裁定〕 |
| 数值解析失败（`"abc"`、`"3/0"`、`"nan"`…） | 容忍，走字面等值支或 `False` |

异常类型一律 `GradingError`（ValueError 直接子类）；契约内输入不抛其他异常。

## 7. 非目标

- **不做单位换算**：米/厘米、千米/米之间不折算；只做别名归一后的字符串相等
  （同一规范单位的别名判等，见 §3.1）。
- **不做方程/过程判分**：不剥 `x=` 前缀、不解方程、不识别多步过程；
  `x=5` 与 `5` 判错（字面支）。
- **不做中文数字解析**：`两元` 走字面支，与 `2元` 判错。
- **不做"或"式多答案**：`-4或2` 只与自身（字面）相等；备选答案支持交给出题侧。
- **不做书写形式约束**：`0.5` 与 `1/2` 按值判等；要求特定书写形式由题干负责。
- **不做多选/组合作答**：choice 仅单标签或单全文。
- **不做半对/部分分**：输出恒为 bool。
- **不接 LLM**：语义判分（"意思对即可"）不在确定性内核。

## 附录 A 修订记录（drafts → 冻结）

- **R1（major，§3.1/I4）自相矛盾例子**：草稿 §3.1 写「`2千米 ≠ 2公里`」，与同节别名表
  （公里→千米）、§3.4 实测（`"2公里"`→`("2","千米")`）及 I4「公里=千米 判对」直接冲突；
  该输入对契约测试从未覆盖（`grade_fill` 测试中 `2公里` 只作 `2米` 题的反例出现）。
  已按别名表 + 单位门的推论钉死：`grade_fill(answer="2千米", "2公里")` → True（实测），
  并把"不做换算"的例子换成真实跨单位的 `2千米 ≠ 2000米`（实测 False）；§3.1 同时补齐
  `2千克/2公斤`、`2小时/2时`、`30分钟/30分` 判等的实测对照，§3.7 表加区分注。
- **R2（minor，§3.6/§3.8）标签比较算子**：草稿 §3.6「所有字符串等值比较都在键形态上」
  与 §3.8「ans 等于某 label」的 `==` 读法冲突（选项标签含内部空白时两读法在
  `options=["ab. 1","a b. x"]`、作答 `"a b"` 上分叉：True vs False）。冻结为参考实现
  行为：标签趟用归一化标签上的直接 `==`；§3.6 改为穷举键形态的两个适用点（fill 字面支、
  choice 全文趟）。
- **R3（minor，§3.8）「标签优先于全文」的粒度**：草稿可读作两趟全局扫描或逐选项交替
  扫描（`options=["ab","a b. x"]`、作答 `"a b"` 时两读法解出不同下标）。冻结为**两趟
  全局扫描**：先扫全部标签、命中即止；未命中再扫全部全文键。交替扫描读法被排除。
- **R4（minor，§3.7/§3.8/§6）learner 短路与非法 item 的先后**：钉死绑定次序——
  learner 类型检查与 `None` 短路先于一切题目侧校验（fill/choice 同）；fill 的空白短路
  在 `item.answer` 归一之后（answer 非法 + `""` → `GradingError`，实测）；choice 的
  空白短路在选项归一之后、正确项解析之前（非法题目 + `""` → `False`，实测）；`grade`
  的分派先于 `None` 短路（非法 item_type + `None` → `GradingError`，实测）。草稿的
  「步骤顺序为绑定条款」由此获得对题目侧非法输入的完全指定。
- **R5（minor，§3.8）全文并列平局**：草稿只对标签趟写明「取 options 顺序第一个」。
  冻结为两趟一致取**最小下标**（探针：`options=["A. x","A.x"]`、answer=`"A.x"`、
  作答 `"a"` → True，排除"取末个"读法）。
- **R6（随冻结顺带钉死，均实测于参考实现）**：§3.2 N4/N3 写明 ASCII 数字类与
  "空白此时只可能是半角空格"的前提；§3.3 写明数字类为 ASCII `[0-9]`、模式全文锚定
  （`parse_numeric("1\n")`/`("１/２")` → `None`）、带分数符号语义为
  `sign·(|a| + b/c)`（消除草稿 `sign*(a+b/c)` 的符号歧义）；§3.4 写明纯单位词命中即
  返回、不回退更短后缀（`split_unit("小时")` → `("小时", None)`）；§2 装载约束改为
  自包含表述（草稿此处引用其他规格文档，违反自包含要求）。
