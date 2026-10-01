# paper_layout 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> **版本**：定稿 v1（由 drafts 版经对抗评审修复而来，修复记录见附录 A）。
> 标注「〔测试裁定〕」的行为由 tests/contract/test_paper_layout_contract.py 直接断言
> （下文行号简写为 `test:NN`）；标注「〔参考裁定〕」的行为契约测试未仲裁，按参考实现
> `src/xuexing/paper_layout.py` 冻结并在当地注明（行号简写为 `impl:NN`）。
> 本文全部数值例子均为本会话（2026-09-29 冻结评审）实跑实测值。

## 1. 目的

paper_layout 是**静态卷打印友好排版**的确定性内核：把 `paper.generate_paper` 产出的
`Paper` 渲染为可直接交付排版/PDF 管线的**打印友好 JSON**——页眉（机构注记 · 卷名 ·
卷号）、按节分组的顺序题号（1..N 贯穿全卷）、选择题选项的标签解析（`"A. x"` -> 标签 A +
正文 x）、按题型冻结的留白规则（choice 题内括号 / fill 一条下划线 / solve 六行解答留白）、
固定每页题数的分页与「第 p 页 / 共 P 页」页脚，为机构分发与离线渠道落格式。

面向**学生卷**（打印分发）：输出不含题目答案、解析、误解标签等作答依据（I9）；完整性门
（未知题、缺合法选项、重复选项标签、入参表面畸形——**含属性/键缺失**）在排版期报错，
不静默出残卷（I8）。

全内核纯函数：无 IO、无随机、无时钟、不读环境，同输入同输出。真正的 PDF 渲染属渠道层
职责，不在本模块范围。

## 2. 允许的依赖与入参表面

### 2.1 依赖

- Python 标准库（re 级别即可）。**不使用** `from __future__ import annotations`，签名注解
  直接写真实对象（重生成实现以单文件注入装载为顶层模块名 `_regen_paper_layout`：
  `tests/conftest.py:22-34` 用 `spec_from_file_location` 直载并顶替 `sys.modules`）。
- 本模块**不需要** `xuexing.types`（鸭子类型参数表面）；禁止 import paper/itembank 等
  任何其他 xuexing 模块。
- 禁止：第三方库、文件/网络 IO、`random`、系统时钟、环境读取。

### 2.2 入参鸭子表面与「缺失」语义

- `paper`：属性 `paper_id: str`、`title: str`（均可空串）；`sections: list 或 tuple`
  （每个元素为 dict：键 `item_ids` **必需**、`kp_name` 可选，其余键忽略）；`sections` 为
  **空 list/tuple** 时回退属性 `item_ids: list/tuple[str]` 构造单一匿名隐式节。
- `bank`：方法 `items() -> 题目可迭代`；题目对象只读属性 `id / item_type / stem`
  （`item_type` 为 choice 时另读 `options`）；`answer / solution / misconceptions` 等其余
  属性一概不读（I9）。
- **缺失 ≠ 空容器**（本条的裁决背景见附录 A/R1）：上表任一属性/键**缺失**（对象无该
  属性、dict 无该键）时，实现必须把「缺失值」送入对应类型校验并抛 `LayoutError`——
  不得用字面属性访问/下标访问把 `AttributeError`/`KeyError` 漏给调用方（实测二者均不是
  `ValueError` 子类，`pytest.raises(LayoutError)` 捕获不到）。特别地：
  **`paper.sections` 属性缺失不触发 `item_ids` 回退**——回退仅在 `sections` 为**空
  list/tuple** 时发生（`test_malformed_paper_and_bank_surfaces_rejected`，test:365-367,
  379-380）。

## 3. 公开 API

模块必须暴露以下 8 个名字（契约测试 `test:13-22` 直接 import）：
`LayoutError`、`FORMAT_VERSION`、`HEADER_SEPARATOR`、`DEFAULT_QUESTIONS_PER_PAGE`、
`ANSWER_SPACE_RULES`、`parse_option`、`section_ordinal`、`render_paper_layout`。

### 3.1 常量

```python
FORMAT_VERSION = "1"                 # 排版 JSON schema 版本
HEADER_SEPARATOR = " · "             # 页眉文本段连接符（空格+U+00B7+空格）
DEFAULT_QUESTIONS_PER_PAGE = 10
ANSWER_SPACE_RULES = {               # 留白规则表（冻结）
    "choice": {"style": "bracket",   "lines": 0},   # 答案写在题干括号内
    "fill":   {"style": "underline", "lines": 1},   # 一条作答下划线
    "solve":  {"style": "ruled",     "lines": 6},   # 六行解答留白
}
```

`ANSWER_SPACE_RULES` 键集合恰为 {choice, fill, solve}。`LayoutError` 是 `ValueError` 的
**直接子类**，是本模块唯一校验异常类型（`test_frozen_constants`，test:86-96）。

### 3.2 `parse_option`

```python
def parse_option(option_text, position) -> tuple[str, str]
```

选项字符串 -> (标签, 选项正文)。

1. **入参门**：`option_text` 非 str、或 strip 后为空；`position` 非 int（bool 算非 int）、
   或不在 [0, 25] -> `LayoutError`（test_parse_option_input_guards，test:179-182：
   `("",0)/(None,0)/(5,0)/("x",26)/("x",-1)/("x",True)/("x",1.0)` 全拒）。
2. `text = option_text.strip()`。
3. **显式标签匹配锚定 strip 后串首**：从 `text` 的第一个字符起匹配「单 ASCII 字母
   （`[A-Za-z]`）+ 分隔符（`.` `．` `、` `)` `）` 之一）+ `[ \t]*`（可为零个）+ 正文」；
   标签归一为大写；正文 = 分隔符后直至串尾的全部剩余字符（可含换行）strip 后，**可为
   空串**。**不做串内搜索**——串中部出现的「字母+分隔符」不构成显式标签（该锚定语义
   为〔参考裁定〕，实证见附录 A/R3；下表「锚定补充」各条即按串首匹配才成立的行为）。
4. 不匹配（含串首非 ASCII 字母、首字母后非分隔符）-> **按位回退**：标签 =
   `"ABCDEFGHIJKLMNOPQRSTUVWXYZ"[position]`，正文 = `text`（strip 后整串）。

探针全表〔测试裁定，test:166-176 逐字〕：

```
("A. 0",0)->("A","0")     ("b、题干",0)->("B","题干")   ("C）文本",0)->("C","文本")
("D．四",0)->("D","四")   ("2",1)->("B","2")            ("（4,1）",0)->("A","（4,1）")
("(4,1)",3)->("D","(4,1)")("x=5",0)->("A","x=5")         ("  B. 2  ",0)->("B","2")
("A.",0)->("A","")
```

锚定补充〔参考裁定，实跑 `impl:57,79`：正则 `([A-Za-z])[.．、)）][ \t]*(.*)\Z` 以
`match`（串首锚定）施加〕：

```
("(a) 选项",0)->("A","(a) 选项")   # 串内 "a)" 不触发；若按串内搜索会得 ("A","选项")——二者可区分
("xa. 5",0)->("A","xa. 5")         # 首字母后非分隔符 -> 回退
("a) 选项",0)->("A","选项")        # 串首即标签
("A.0",0)->("A","0")               # 分隔符后空白可为零个
("A. 第一行\n第二行",0)->("A","第一行\n第二行")   # 正文可跨换行、延伸到串尾
```

### 3.3 `section_ordinal`

```python
def section_ordinal(n) -> str
```

节序号 -> 中文序号闭式：1-9 -> 一…九；10 -> 十，11-19 -> 十一…十九；整十 ->
二十/三十/…/九十；其余两位数按「几十几」；n ≥ 100 -> `str(n)`。

实测〔测试裁定，test:260-263 逐字〕：`(1)->"一" (2)->"二" (9)->"九" (10)->"十"
(11)->"十一" (19)->"十九" (20)->"二十" (21)->"二十一" (90)->"九十" (99)->"九十九"
(100)->"100" (101)->"101"`。

入参门：n 非 int（含 bool；2.0/"3"/None 同拒）或 < 1 -> `LayoutError`
（test:265-267：`(0,-3,True,2.0,"3",None)` 全拒）。

### 3.4 题块形状

`render_paper_layout` 内部对每道题产出**新构造** dict（不引用入参内部对象）：

```python
{
  "kind": "question",
  "number": <1 起全卷顺序题号>,
  "item_id": <该次出现的题 id（paper 节内原样）>,
  "item_type": <choice|fill|solve>,
  "stem": <题干原文，原样透传不 strip；仅要求 strip 后非空>,
  "options": [{"label": ..., "text": ...}, ...],   # choice：逐个 parse_option；非 choice 恒 []
  "answer_space": {"style": ..., "lines": ...},    # 查 ANSWER_SPACE_RULES，每次新 dict
}
```

键集合恰为上列 7 个（test:116-118）。

对每道被排版的题，在 V6 按卷面顺序执行以下校验（**首个坏题即抛，其余题不再校验**
〔参考裁定〕；题目对象属性缺失按 §2.2 进入对应校验 → `LayoutError`〔参考裁定，
实跑 impl:115-124〕）：

1. `item_type` ∈ {choice, fill, solve}（即 ANSWER_SPACE_RULES 键集），其余值（含缺失）->
   `LayoutError`（test_unknown_item_type_rejected，test:331-335）；
2. `stem` 必须为 str 且 strip 后非空（空白/非 str -> `LayoutError`，test:338-343）；
3. `item_type == "choice"` 时：`options` 必须为 list/tuple 且长度 ≥2（缺失/长度不足 ->
   `LayoutError`，test:318-328 bad1）；逐元素 `parse_option(o, i)`（i = 该选项下标）；
   **最终标签必须互不重复（显式标签与回退标签同样参与判重）**（test:318-328
   bad2=`["A. 1","A. 2"]`、bad3=`["1","A. 2"]` 回退 A 撞显式 A）；违反 -> `LayoutError`
   （消息含题 id）；
4. 非 choice 题：`options` 字段即使有值也忽略，输出恒 `[]`（test:151-163 末断言）。

options 元素 dict 键集合恰为 `{"label", "text"}`；`answer_space` 每次**新构造** dict、与
ANSWER_SPACE_RULES 常量表互不别名（test:196-203）。

### 3.5 `render_paper_layout`

```python
def render_paper_layout(paper, bank, questions_per_page=DEFAULT_QUESTIONS_PER_PAGE,
                        header_note="") -> dict
```

校验顺序冻结（V1→V8；多种缺陷并存时的报错先后按本序——契约测试只单一缺陷注入，
并存先后为〔参考裁定〕），任何一步失败抛 `LayoutError`：

- **V1 `questions_per_page`**：必须为 int（bool 拒绝）且 ≥1
  （test:353-356：0/-2/True/"3"/3.0/None 全拒）；
- **V2 `header_note`**：必须为 str（test:359-361）；空串合法；
- **V3 paper 表面**：`paper.paper_id` / `paper.title` 必须为 str（可空串；属性缺失按
  §2.2 -> `LayoutError`）；`paper.sections` 必须为 list/tuple（**属性缺失/None 同**
  -> `LayoutError`，test:365-367,379-380；缺失**不**触发 V5 回退）；
- **V4 bank 索引**：`bank.items` 缺失或不可调用 -> `LayoutError`（test:372-373,381-382）；
  `items()` 返回值不可迭代 -> `LayoutError`（test:368-370,383-384）；逐题 `id` 必须为
  「strip 后非空的 str」（缺失按 §2.2 -> `LayoutError`，test:375-377,385-386）；
  **bank 内 id 重复** -> `LayoutError`（test:312-315）。本步只建 `id -> 题对象` 映射，
  题目内容延迟到该题被排版（V6）时才校验；
- **V5 节规整化**：仅当 `sections` 为**空 list/tuple** 时回退：`paper.item_ids` 必须为
  list/tuple（否则 `LayoutError`，test:396-398），并构造单一匿名隐式节（kp_name 为空，
  走与普通节完全相同的 V5b/V6 校验）。否则逐节：必须 dict（否则 `LayoutError`，
  test:387 `["x"]`）；**键 `item_ids` 缺失（dict 无该键）或值非 list/tuple ->
  `LayoutError`**（test:387 `[{"kp_name": "甲"}]`）；元素必须为 strip 后非空的 str
  （非 str -> `LayoutError`，test:387 `[{"item_ids": [3]}]`）；键 `kp_name` 可选，存在则
  必须为 str（否则 `LayoutError`，test:388 `[{"kp_name": 5, …}]`）；`kp_name` 取 strip 后
  参与命名判定与渲染（**全空白的 kp_name 等价未命名**，附录 A/R2 实测）；
- **V6 逐节逐题构建**：卷面顺序 = 节序 × 节内 item_ids 序；bank 查无此 id ->
  `LayoutError`（消息含该 id，test:305-309）；随后按 §3.4 校验该题。
  **节序号计数器从 0 起，仅当节「kp_name strip 后非空 且 item_ids 非空」时自增 1，
  该节序号取自增后的值（1,2,3…）**；未命名节（无 kp_name 键 / kp_name 全空白 /
  回退隐式节）与有名字但无题的节**不消耗号段、不渲染标题块**（命名空节跳号：
  test:276-286；单一未命名节无块但有题：test:289-293；混合排布的号段归属为
  〔参考裁定〕，按附录 A/R2 实测冻结）；
- **V7 空卷门**：总题数 0 -> `LayoutError`（`sections=[]` 且 `item_ids=[]`、或全部节
  无题均命中，test:346-350）；
- **V8 分页 + 页眉页脚**（闭式见下）。

**分页闭式**：共 `N = question_count` 题、每页 `qpp` 题 -> `page_count = ceil(N/qpp)`；
第 p 页（1 起）承载全卷第 `(p-1)*qpp+1 .. min(p*qpp, N)` 题。**节标题块
`{"kind": "section", "text": "<中文序号>、<strip 后节名>"}` 恒出现在其节首题所在页、
且紧邻该题之前，不占每页题数位**（同一页可出现多个节标题块；节中途换页不重复标题）。

返回顶层 dict（全部新构造、JSON 可序列化），键集合恰为（test:103-106）：

```python
{
  "format_version": FORMAT_VERSION,
  "paper_id": ..., "title": ...,            # 原样透传（不 strip）；顶层为〔参考裁定〕，见 I5
  "question_count": N, "page_count": P,
  "by_item_type": {<题型>: <计数>, ...},    # 仅含出现的题型，键码点升序，合计 = N
  "pages": [...],
}
```

页 dict 键集合恰为 {page_number, page_count, header, footer, blocks}（test:213）：

```python
{
  "page_number": p, "page_count": P,   # 逐页 page_count 一致且等于顶层（test:211-212）
  "header": {
    "title":    <paper.title 原样，不 strip>,      # 〔测试裁定〕test:226
    "paper_id": <paper.paper_id 原样，不 strip>,
    "note":     <header_note.strip()>,
    "text":     <HEADER_SEPARATOR.join(
                  [header_note.strip(), title.strip(), paper_id.strip()] 中非空段)>,
  },
  "footer": {"text": "第 {p} 页 / 共 {P} 页"},
  "blocks": [<section|question 块，卷面顺序>],
}
```

header 键集合恰为上列 4 键〔参考裁定：测试逐键取值但不查集合，test:214-217〕；
section 块键集合恰为 `{"kind", "text"}`〔参考裁定：测试只取 kind/text 值，
impl:256-259〕。

实测探针（与契约测试逐字对应；**夹具 = test:46-58：五题两节**——节 1「有理数」=
(c1, f1)、节 2「一元一次方程」= (s1, f2, c2)；c1 = choice 4 选项、c2 = choice 2 选项
（无显式标签，按位回退）、f1/f2 = fill、s1 = solve；paper_id="paper-77"、
title="七年级诊断卷"）：

- qpp=2 -> `question_count=5, page_count=3,
  by_item_type={"choice":2,"fill":2,"solve":1}`，题序 `[c1,f1,s1,f2,c2]`、题号 1..5
  （test:101-118）；第 1 页块序 = [节"一、有理数", 题1, 题2]，第 2 页 =
  [节"二、一元一次方程", 题3, 题4]，第 3 页 = [题5]（test:237-248）；
- qpp=3 -> 第 1 页块序 = ["section","question","question","section","question"]（同页
  两个节标题块，test:251-257）；qpp=100 -> 单页 7 块 [节,题,题,节,题,题,题]
  （test:121-129）；
- 页眉无注记 -> text = `"七年级诊断卷 · paper-77"`、note = ""（test:208-218）；注记
  `"  XX中学数学科  "` + 卷名 `"  七年级诊断卷  "` -> text =
  `"XX中学数学科 · 七年级诊断卷 · paper-77"`、note = `"XX中学数学科"`、
  **header["title"] = `"  七年级诊断卷  "`（原样，不 strip）**（test:221-227）；
  三段全空 -> text == ""（test:230-232）；
- 页脚闭式 `"第 1 页 / 共 3 页"` … `"第 3 页 / 共 3 页"`（test:208-218）；
- c1 选项解析 = `[{"label":"A","text":"0"},{"label":"B","text":"-2/3"},
  {"label":"C","text":"+1.5"},{"label":"D","text":"2026"}]`；c2 无标签选项
  `["2","3"]` -> `[{"label":"A","text":"2"},{"label":"B","text":"3"}]`
  （test:151-163）；
- 真实库端到端（tests/data，grade7：37 KP × 每 KP 2 题、seed=11、qpp=15）->
  `question_count=74, page_count=5, by_item_type={"choice":23,"fill":46,"solve":5}`，
  37 个节标题块 `"一、绝对值"` … `"三十七、消元法解二元一次方程组"`
  （tests/data/test_paper_layout_data.py:37-67；本轮实跑 6 passed）。

## 4. 不变量（编号列出，全部可被契约测试检验）

- **I1 常量冻结**：FORMAT_VERSION/HEADER_SEPARATOR/DEFAULT_QUESTIONS_PER_PAGE/
  ANSWER_SPACE_RULES 取值如 §3.1（键集合 {choice,fill,solve}）；`LayoutError` 是
  ValueError 直接子类（test:86-96）。〔测试裁定〕
- **I2 题号与卷面顺序**：题号 1..N 全卷连续；题块顺序恒等于节序 × 节内 item_ids 序
  （`sections=[]` 回退时等于 item_ids 序，test:296-300）；同一题 id 出现两次按出现次数
  分别编号、两块互不别名、输出互不污染（test:132-146）。〔测试裁定〕
- **I3 选项解析**：§3.2 探针全表（test:166-176）；choice 选项块形状 `{"label","text"}`；
  非 choice options 恒 `[]`（test:151-163）；串首锚定的串中部探针为〔参考裁定〕
  （附录 A/R3）。〔测试裁定〕
- **I4 留白规则**：answer_space 按 ANSWER_SPACE_RULES 逐题型取值；输出中的 answer_space
  与规则表互不别名（改输出不影响常量表与重渲染，test:187-203）。〔测试裁定〕
- **I5 页眉/页脚**：header 三段各自 strip 后以 HEADER_SEPARATOR 连接、空段跳过；
  `header["note"]` = header_note.strip()；**`header["title"]`/`header["paper_id"]` =
  paper.title/paper.paper_id 原样透传（不 strip）**（test:221-226）；顶层
  `doc["title"]`/`doc["paper_id"]` 亦原样透传〔参考裁定：test:109 的夹具无首尾空白，
  strip 与否不可区分；impl:280-281 原样〕；每页 footer `"第 {p} 页 / 共 {P} 页"`、
  逐页 page_count 一致（test:208-218）。〔测试裁定除注明外〕
- **I6 分页与节标题块**：§3.5 分页闭式；节标题块 text = `<section_ordinal(节序号)>、
  <strip 后节名>`（test:270-273），只在节首题前、不占题数位、同页可多个、跨页不重复
  （test:237-257）；**节序号只发给「命名且有题」的节，未命名节与空节不消耗号段**
  （test:276-293；混合排布号段归属见附录 A/R2）。〔测试裁定除混合排布外〕
- **I7 顶层形状**：顶层/页/question 块键集合封闭如 §3.5；by_item_type 仅含出现的题型、
  键码点升序、合计 = N（test:101-118,213,296-300）。〔测试裁定〕
- **I8 完整性门（不出残卷）**：未知题 id（消息含该 id）、bank 内重复 id、choice <2 选项、
  选项标签判重（显式/回退混合）、未知 item_type、空白/非 str stem、空卷、非法
  questions_per_page/header_note、paper/bank/节**表面畸形——含属性/键缺失**（sections
  属性缺失、节缺 item_ids 键、items() 缺失/返回不可迭代、题目 id 非非空 str、sections 非
  list/tuple、节非 dict、item_ids 含非 str、kp_name 非 str、回退时 item_ids 非 list）
  全部抛 `LayoutError`，**不得漏出 AttributeError/KeyError**（二者非 ValueError 子类，
  实测确认；test:305-398）。〔测试裁定；题目对象 item_type/stem/options 属性缺失同样
  LayoutError 为〔参考裁定〕，由 §3.4 校验路径覆盖〕
- **I9 学生卷不泄作答依据**：(a) 题目对象只读 `id/item_type/stem`（choice 另读
  `options`），answer/solution/误解标签等属性**不读取、不出现在输出的任何键名或模块
  构造的值中**；(b) 输出中由模块构造的键名里，唯一含 "answer" 子串的是 `answer_space`；
  (c) **透传优先，不做子串过滤**：用户文本（paper_id/title/header_note/stem/kp_name/
  选项正文）按 §3.4/§3.5 透传或 strip 透传，若其自身含 "answer"/"solution" 等子串，
  序列化输出亦含之——不得为满足字面子串检查而过滤、报错或截断（附录 A/R5 实测）；
  (d) 因此「序列化输出不含 answer/solution/misconception 字样」这一断言
  （test:403-409）的适用前提是**透传文本本身不含这些子串**（契约夹具即如此）。数据侧
  在真实题库上复验键集合封闭（tests/data/test_paper_layout_data.py:91-96）。
  〔测试裁定 (a)(b)(d)；(c) 为〔参考裁定〕〕
- **I10 纯函数性与确定性**：不改 paper/bank（深照相机比对，test:414-422）；同输入同输出；
  输出全量 JSON 可序列化且 round-trip 等值（test:425-431）。〔测试裁定〕
- **I11 真实库可跑通**：grade7 全图谱蓝图（37 KP × 2 题）可组卷、可排版，闭式计数如
  §3.5 探针末条（tests/data/test_paper_layout_data.py，本轮实跑 6 passed）。
  〔测试裁定（数据侧）〕

## 5. 确定性与随机性

- 全部函数纯函数：输出只依赖入参值；禁止 `random`、系统时钟、环境读取、任何 IO、
  hash 序依赖（by_item_type 键序显式 sorted；节/题顺序全部来自入参序列）。
- dict 构造序固定；`json.dumps(doc, ensure_ascii=False, sort_keys=True)` 逐位可复现
  （test:429-430）。
- 本模块**没有** seed/时间戳豁免：同输入字节级同输出。

## 6. 错误行为

`LayoutError`（ValueError 直接子类）是本模块唯一校验异常类型。`render_paper_layout`
抛错时机按 §3.5 校验顺序 V1→V8 冻结；`parse_option`/`section_ordinal` 各自的入参门在
§3.2/§3.3 签名处另列。

- **缺失/类型不符统一路径**（§2.2，附录 A/R1）：入参对象（paper、节 dict、bank、题目
  对象）表面上约定要读的属性或键**缺失**时，一律按「缺失值」进入对应类型校验并抛
  `LayoutError`。禁止以字面属性访问/下标访问把 `AttributeError`/`KeyError` 漏给调用方
  （实测二者均非 ValueError 子类，`pytest.raises(LayoutError)` 捕获不到；
  test:379-380 缺 sections 属性、test:387-388 缺 item_ids 键均断言 LayoutError）。
  **缺失不等于空**：sections 属性缺失 -> 报错；空 list/tuple -> 触发回退。
- **必须容忍并跳过（不抛错）**：paper/bank 的多余属性与节内多余键（如契约夹具节中的
  `kp_id`，忽略）；非 choice 题的 `options` 字段有值（忽略）；`kp_name` 带首尾空白
  （strip 后渲染，test:270-273）；`kp_name` 键不存在（按未命名节处理，不渲染标题块、
  不占号，test:289-293）；`paper_id`/`title`/`header_note` 为空串（对应页眉段跳过，
  note 为 ""，test:230-232）。
- **域外输入（唯一不作承诺的情形）**：入参对象的属性**读取本身**抛出非 AttributeError
  异常（自定义 `__getattr__`/property 抛错等）时，该异常原样传播，不承诺转成
  `LayoutError`；契约测试不构造此类对象。〔参考裁定；实跑：property 抛 RuntimeError ->
  原样传播，附录 A/R1〕
- 错误消息逐字文本不是契约，但必须含关键标识（题 id / 非法值 repr）；契约测试仅对未知
  题 id 断言消息含该 id（test:305-309）。

## 7. 非目标

- **不渲染 PDF**：输出止于打印友好 JSON；字体/页边距/换行折行等视觉排版属渠道层。
- **不判分、不带答案**：本模块产出学生卷（I9）；教师卷/答案卷的排版不在范围。
- **不组卷**：题的选择与节的结构完全沿用入参 paper——本模块不读 blueprint、不查知识
  图谱、不增删题、不改节序。
- **不做高度估算折页**：分页按「每页题数」闭式切分，不做按行高的文本测量折页（如需按
  物理行高分页，属渠道层在 blocks 上的再加工）。
- **不修改任何入参对象**（I10）；鸭子类型表面仅约定属性/方法读取，不 import 其所在
  模块。
- **不承诺跨实现字节一致的错误消息文本**：须含关键标识（§6），逐字文本不是契约。

## 附录 A：对抗评审修复记录

以下为 drafts 版 -> 本定稿的全部修复。R1/R2/R3/R5/R6 各含本会话实跑证据（命令：
`python _research_tmp/probe_paper_layout_freeze.py`，脚本复用契约测试夹具
`ITEMS/BANK/_paper` 做只读探针，一次性验证工件，验证后删除）；方括号引用为该脚本输出行。

| # | 严重度 | 评审问题 | 修复 | 证据（本会话实跑） |
| --- | --- | --- | --- | --- |
| R1 | major | 规格未规定「缺失表面」必须转 LayoutError：`_NoSections`（无 sections 属性，test:365-367,379-380）与缺 item_ids 键的节（test:387-388）按草稿字面会抛 AttributeError/KeyError（实测二者均非 ValueError 子类），或被误读成「缺失回退」静默渲染；§6 免责句拗口且与该测试相抵 | §2.2 新增「缺失 ≠ 空容器」统一规则（缺失送类型校验 -> LayoutError；sections 属性缺失不触发回退）；V3/V5 明写属性/键缺失 -> LayoutError；I8 明写「不得漏出 AttributeError/KeyError」；§6 重写免责句：唯一域外 = 属性读取本身抛非 AttributeError 异常时原样传播 | `[I1.no_sections_attr] LayoutError: paper.sections must be a list`；`[I1.missing_item_ids_key] LayoutError: section '' item_ids must be a list`；`[I1.sections_none_attr] LayoutError`；`[I1.AttributeError_is_ValueError_subclass] False`、`[I1.KeyError_is_ValueError_subclass] False`；缺失 item_type/stem/options 均 LayoutError；`[I1.getattr_raises_nonAttributeError] WRONG EXC RuntimeError: boom-prop`（原样传播，即域外样例） |
| R2 | minor | V6 节序号对「未命名但有题的节」是否消耗号段未写死：草稿句可读成「只在合格节内计数」（不占号）或「按有题节计数」（占号），混合排布差一号；测试只锁单一未命名节（test:289-293） | V6/I6 写死：**计数器仅对「kp_name strip 后非空且有题」的节自增，未命名节与空节不消耗号段**；混合排布 [未命名(有题), 命名(有题)] 中命名节得序号 1。标注〔参考裁定〕 | `[I2.unnamed_then_named] ['一、甲']`（未命名节不占号，命名节为「一」）；`[I2.named_unnamed_named] ['一、甲', '二、乙']`；`[I2.whitespace_name_is_unnamed] ['一、甲']`（全空白 kp_name 等价未命名） |
| R3 | minor | parse_option 显式标签未说明是否锚定串首：按 re.search 语义 `(a) 选项` 会被解析成 ("A","选项")，按前缀语义则回退；现有探针（test:166-176）无串中部用例，两种实现都能过测试但行为不同 | §3.2 明写「**匹配锚定 strip 后串首，不做串内搜索**」；正文为分隔符后至串尾全部剩余字符；增补串首锚定探针并标注〔参考裁定〕 | `[I3.mid_string_letter_dot] ('A', '(a) 选项')`（若按串内搜索会得 ('A','选项')——可区分）；`[I3.mid_string_xa_dot] ('A', 'xa. 5')`；`[I3.leading_a_paren] ('A', '选项')`；`[I3.no_space_label] ('A', '0')`；`[I3.multiline_body] ('A', '第一行\n第二行')` |
| R4 | minor | §3.5 探针夹具描述自相矛盾（「两节六题」「f1=s1」均与测试不符；实际为两节五题） | §3.5 夹具描述改为与 test:46-58 逐字一致：五题两节（有理数: c1,f1 / 一元一次方程: s1,f2,c2；c1=choice 4 选项、c2=choice 2 选项无显式标签） | 文本一致性修复；夹具数值复核 `[F.qpp2] (5, 3, {'choice': 2, 'fill': 2, 'solve': 1})`、`[F.qpp100_block_kinds] ['section','question','question','section','question','question','question']` |
| R5 | minor | I9 草稿「除 answer_space 外不含 answer/solution 字样」是无条件断言，与 I5 的 title/paper_id/header_note/stem 等透传条款冲突（用户文本含该子串时两条款不可同时满足）；test:403-409 夹具无该子串，未暴露矛盾 | I9 重写为四条：(a) 作答依据属性不读取不输出；(b) 模块构造的键名中唯一 "answer" 子串是 answer_space；(c) **透传优先，不做子串过滤**；(d) 字面子串断言的适用前提是透传文本不含这些子串 | `[I5.title_passthrough] 'answer key'`（title 含 "answer" 原样透传）；`[I5.answer_substring_beyond_answer_space] True`、`[I5.solution_substring_present] True`（输出含之，不过滤不报错）；`[I5.stem_passthrough_raw] '本题 stem 含 solution 字样'` |
| R6 | minor | 页眉 header['title']/header['paper_id'] 原样透传（不 strip）只在 I5 以未限定范围的一句话出现，§3.5 页 schema 注释只定义 note/text 的 strip/join，照注释实现会一并 strip，挂 test:226 | §3.5 页 schema 逐键写明：header title/paper_id **原样透传不 strip**〔测试裁定 test:226〕、note = header_note.strip()、text 三段 strip 后连接；I5 同步并区分顶层透传为〔参考裁定〕 | `[I6.header_title_raw] '  七年级诊断卷  '`（原样）；`[I6.header_note_stripped] 'XX中学数学科'`；`[I6.header_text] 'XX中学数学科 · 七年级诊断卷 · paper-77'`；`[I6.toplevel_title_raw] '  七年级诊断卷  '`（顶层亦原样） |

冻结评审会话套件回归：`python -m pytest tests/contract/test_paper_layout_contract.py -q`
-> 32 passed；`python -m pytest tests/data/test_paper_layout_data.py -q` -> 6 passed。
