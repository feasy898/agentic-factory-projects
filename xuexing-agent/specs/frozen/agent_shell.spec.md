# agent_shell 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> 依据：tests/contract/test_agent_shell_contract.py（6 个测试，本仓库 47 契约测试全绿）、
> 参考实现 src/xuexing/agent_shell.py、src/xuexing/types.py、src/xuexing/itembank.py。
> 标注 **[仅参考]** 的条款来自参考实现/探针验证，当前契约测试未直接断言——仍按参考实现冻结，
> 重生成实例必须遵守；未标注的条款均可由契约测试直接检验。

## 1. 目的

Agent 壳：把"LLM 调用"与"确定性业务逻辑"分离。LLM 通过 `LLMClient` 协议注入（测试用确定性
`MockLLM`，运行时用 `OpenAICompatClient`），模块自身沉淀四个纯业务函数：错因归因
（确定性签名匹配优先、LLM 兜底）、错题讲解、出题草稿、草稿入库门（校验+查重+原子入库）。

## 2. 允许的依赖

- Python 标准库（参考实现用到：`json`、`os`、`re`、`typing`）
- `xuexing.types`（**绝对导入**：`from xuexing.types import Item, Misconception`）
- 禁止 import 其他任何 xuexing 模块（明白列出：无）。特别注意**禁止 import `xuexing.itembank`**：
  `try_accept_draft` 的 `bank` 参数按结构使用（duck typing），只需要其暴露
  `validate_item(item) -> list[str]`、`items() -> list[Item]`（按 id 升序）、`add(item) -> None`
  三个方法；契约测试传入的是参考实现 `ItemBank` 实例（tests/contract/conftest.py:51-68）。
  conftest 以独立文件 exec 注入重生成实例并预先完整加载参考包（conftest.py:12-26），
  因此违规 import 在运行时"碰巧可行"且测试照绿——但这属于违规，规格按静态合规要求：
  模块源码中不得出现任何指向 `xuexing.itembank` 的 import。
- 禁止第三方库、文件 IO。唯一豁免：`OpenAICompatClient.complete` 内部**延迟** import `httpx`
  并读环境变量、发网络请求；它不在契约测试覆盖范围（见 §3.4 与 §7）。

## 3. 公开 API

模块必须暴露以下 8 个名字。契约测试直接 import 的恰为 **5 个**：
`MockLLM`、`attribute_error`、`explain_error`、`draft_item`、`try_accept_draft`
（tests/contract/test_agent_shell_contract.py:2-8）。`LLMError`、`LLMClient`、
`OpenAICompatClient` **未被任何契约测试导入**：`LLMClient` 是协议形态约定，
`OpenAICompatClient` 行为不冻结（§3.4）；`LLMError` 仅作为 §3.7 规定的异常类型被间接要求。

### 3.1 `LLMError(RuntimeError)`

LLM 相关失败的异常类型（草稿非 JSON、生产客户端密钥缺失/HTTP 失败/响应形状错）。
必须是 `RuntimeError` 的子类。

### 3.2 `LLMClient`（typing.Protocol）

```python
class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...
```

任何实现该签名的对象均可注入四个业务函数。`MockLLM` 与测试本地的 `ScriptedLLM`
（固定回复、记录调用次数）都满足它。

### 3.3 `MockLLM`

```python
MockLLM(mode: str = "default")
```

确定性 mock，供测试与离线运行。属性 `calls: list[tuple[str, str]]`：每次 `complete` 按
`(system, user)` 顺序追加一条。`complete(system, user) -> str` 按 `mode` 分派（正则原文如下）：

- `mode == "item_drafter"`：在 `user` 上执行 `re.search(r"kp=(\S+).*?difficulty=([\d.]+)", user)`
  （**无任何 flag**，故 `.` 不匹配换行、`\S+` 不跨空白）。命中则 `kp = m.group(1)`、
  `diff = float(m.group(2))`；未命中则 `kp = "kp_unknown"`、`diff = 0.5`。
  令 `a = 3 + int(diff * 10)`、`b = 5`、`ans = a + b`，返回
  `json.dumps({...}, ensure_ascii=False)`，dict 字段恰好为：
  `id=f"draft-{kp}-{int(diff*100)}"`、`item_type="fill"`、
  `stem=f"计算：{a} + {b} = ?"`、`answer=str(ans)`、`kps=[kp]`、
  `difficulty=diff`（提取的 float 原值）、`solution=f"{a} + {b} = {ans}"`。
- `mode == "explainer"`：在 `user` 上执行 `re.search(r"教学提示:\s*(.+)$", user, re.M)`。
  命中则 `hint = m.group(1).strip()`；未命中则 `hint = "回顾基础概念"`；
  返回 `f"【讲解】{hint} 我们一步步来看这道题……"`。
- 其他（含默认 `"default"`）：返回 `"OK"`。

已验证实例（本会话探针实跑输出）：

- `MockLLM('item_drafter').complete('sys', 'kp=a difficulty=0.30')` →
  `{"id": "draft-a-30", "item_type": "fill", "stem": "计算：6 + 5 = ?", "answer": "11", "kps": ["a"], "difficulty": 0.3, "solution": "6 + 5 = 11"}`
- 同上但 user 为 `'kp=a\ndifficulty=0.30'`（两个子串分放两行）→ 正则未命中 →
  `kps` 为 `["kp_unknown"]`、`difficulty` 为 `0.5`、`id` 为 `"draft-kp_unknown-50"`。
- `MockLLM('explainer').complete('sys', '教学提示: 提示X')` → `【讲解】提示X 我们一步步来看这道题……`
- 同上但冒号为全角 `'教学提示：提示X'` → 正则未命中 → 返回
  `【讲解】回顾基础概念 我们一步步来看这道题……`。
- `MockLLM().complete('sys', 'u')` → `OK`

### 3.4 `OpenAICompatClient` **[仅参考]**

```python
OpenAICompatClient(base_url: str, model: str, api_key_env: str = "XX_LLM_API_KEY")
```

构造时 `base_url.rstrip("/")`。`complete`：从 `os.environ[api_key_env]` 读密钥，
缺失/为空 → `LLMError(f"env {self.api_key_env} not set")`；否则 POST
`{base_url}/chat/completions`（Bearer 鉴权，timeout 60.0，messages 为 system+user 两条）；
非 200 → `LLMError(f"llm http {status}")`；解析 `choices[0].message.content`，
KeyError/IndexError → `LLMError(f"bad llm response: {e}")`。
**无契约测试覆盖**，重生成实例只需暴露同签名构造器即可，行为不冻结。

### 3.5 `attribute_error`

```python
def attribute_error(item: Item, learner_answer: str,
                    misconceptions: list[Misconception], client: LLMClient) -> Optional[str]
```

把错误答案归因到误解模式，返回误解 id 或 `None`。算法：

1. `learner_answer.strip()` 为空 → 直接返回 `None`，**不调用 LLM**。
2. 按列表顺序遍历 `misconceptions`，每个再按 `signature` 列表顺序遍历：
   `sig` 非空（strip 后非空）且 `sig.strip() == learner_answer.strip()` → 返回 `mc.id`。
   签名命中**不调用 LLM**。
3. 签名未命中 → **恰好一次** `client.complete`。system 与 user 文案如下（措辞**不冻结**、
   不被契约测试检验——测试 client 忽略提示词内容，可检验的只有调用次数与返回值处理，见 I3）：

   ```text
   system: 你是错因诊断助手。

   user:
   题目: {item.stem}
   正确答案: {item.answer}
   学生答案: {learner_answer}
   候选误解:
   - {mc.id}: {mc.description}        ← 每个候选误解一行，按列表顺序
   只返回最匹配的误解 id，无法判断返回 NONE。
   ```

   回复 `.strip()` 后按 `misconceptions` 列表顺序找**第一个**其 `id` 作为子串出现的误解，
   返回该 id；找不到（如回复 `"NONE"`）→ `None`。

签名匹配对两侧都做 strip：学生答案 `" 7 "` 命中 signature `["7"]` → 返回 `"mc_y"`
（探针已验证）。

例子（摘自契约测试，test_agent_shell_contract.py:36-47）：

- `_mcs()` 为 `[mc_x(signature=["9"]), mc_y(signature=["7"])]` 时：
  `attribute_error(_item(), "9", _mcs(), ScriptedLLM("anything")) == "mc_x"` 且 `llm.calls == 0`。
- 学生答案 `"weird"`（无签名命中）、回复 `"我认为是 mc_y"` → 返回 `"mc_y"` 且 `llm.calls == 1`；
  回复 `"NONE"` → `None`；学生答案 `""`、回复 `"mc_x"` → `None`（空答案不归因）。

### 3.6 `explain_error`

```python
def explain_error(item: Item, learner_answer: str, hint: str, client: LLMClient) -> str
```

生成错题讲解。`hint` 来自误解库（确定性），LLM 只负责展开。要求：

- **冻结耦合（硬性字符要求）**：user 提示词中必须存在一行，内容恰为
  `教学提示: {hint}`——`教学提示` 四字之后是**半角 ASCII 冒号 `:`**（U+003A，
  不得写成全角 `：`），冒号后跟**半角空格**，hint 文本紧随其后直至行尾。
  可自验谓词：对 user 应用 `re.search(r"教学提示:\s*(.+)$", user, re.M)` 必须命中，
  且 `m.group(1).strip() == hint`。此耦合是测试生效的前提：契约测试用 `MockLLM("explainer")`
  按该正则回显提示，若行缺失、冒号为全角或 hint 不在冒号后的同一行内，
  mock 会回退 `"回顾基础概念"`，断言 `assert "提示X" in out`（test:52）必失败。
- 恰好调用一次 `client.complete`；若回复 strip 后非空则原样返回，
  否则回退返回 `f"【讲解】{hint}"`。返回值 strip 后必须非空。
- 不对 `learner_answer` 做空值特判（与 `attribute_error` 不同），恒走 LLM。
- 其余提示词措辞与 system 文案（参考：`"你是耐心的数学辅导老师，遵循教学对齐原则：引导而非代做。"`）
  不冻结。

例子（test_agent_shell_contract.py:50-52）：
`explain_error(_item(), "9", "提示X", MockLLM("explainer"))` 的返回值包含 `"提示X"` 且 strip 后非空。

### 3.7 `draft_item`

```python
def draft_item(client: LLMClient, kp_id: str, difficulty: float) -> dict
```

让 LLM 起草一道题，返回解析后的 dict，**绝不入库**（不触碰任何 bank）。要求：

- **冻结耦合（硬性同行要求）**：user 提示词中 `kp={kp_id}` 与
  `difficulty={difficulty:.2f}`（Python 两位小数格式，如 `0.3` → `"0.30"`）必须出现在
  **同一行**内、`kp=` 在前，两者之间不得有换行符，且 `kp_id` 之后到 `difficulty=` 之前
  不得混入会被误并进 kp 的其他非空白内容。可自验谓词：对 user 应用
  `re.search(r"kp=(\S+).*?difficulty=([\d.]+)", user)`（无 flag）必须命中，
  且 `m.group(1) == kp_id`、`float(m.group(2)) == difficulty`。
  此耦合是测试生效的前提：契约测试用 `MockLLM("item_drafter")` 按该正则提取 kp 与
  difficulty，若两个子串分放不同行（正则无 `re.S`，`.` 跨不过换行）则 mock 回退
  `kp_unknown`/`0.5`，断言 `draft["kps"] == ["a"]`（test:57）及后续入库门测试必失败
  （探针已验证：`'kp=a\ndifficulty=0.30'` → `kps=["kp_unknown"]`）。
- 恰好调用一次 `client.complete`；在回复中取 `raw.find("{")` 到 `raw.rfind("}")`
  的闭区间子串做 `json.loads`；若 `start < 0 or end <= start`（无大括号对）→
  `LLMError("draft is not JSON")`。
- 解析结果若没有 `"kps"` 键则 `setdefault("kps", [kp_id])`（已有键——包括空列表——不覆盖）；
  其余字段原样保留，不做校验。
- 大括号存在但内部不是合法 JSON 时，`json.JSONDecodeError`（ValueError 子类）**原样冒泡**，
  不包装成 `LLMError` **[仅参考，探针已验证]**。

例子（test_agent_shell_contract.py:55-58）：
`draft_item(MockLLM("item_drafter"), "a", 0.3)` → dict 满足
`draft["kps"] == ["a"]`、`draft["stem"]` 非空、`draft["answer"]` 非空、
`0.0 <= draft["difficulty"] <= 1.0`（参考值见 §3.3 第一条实例）。

### 3.8 `try_accept_draft`

```python
def try_accept_draft(draft: dict, bank, valid_kp_ids: set[str]) -> tuple[bool, list[str]]
```

`bank` 为**结构参数**（duck typing），印刷签名中不出现类型标注：实现者可用裸参数如上，
或使用本模块内自定义的 Protocol 标注，唯一硬约束是**不得 import `xuexing.itembank`**（§2）。
参数需暴露：`validate_item(item) -> list[str]`、`items() -> list[Item]`（按 id 升序）、
`add(item) -> None`。

入库门：草稿必须通过题库校验且不与现有题同题干才能入库。**全有或全无**：
只有错误列表为空才 `bank.add(item)`。

**步骤 1（字段收敛，宽容读取，缺键给默认）**——收敛后按下表**逐字段**构造
`xuexing.types.Item`（绝对导入），**七个字段一个不可少**：

| Item 字段 | 取值 |
|---|---|
| `id` | `str(draft.get("id", ""))` |
| `item_type` | `str(draft.get("item_type", ""))` |
| `stem` | `str(draft.get("stem", ""))` |
| `answer` | `str(draft.get("answer", ""))` |
| `kps` | `[str(k) for k in draft.get("kps", [])]` |
| `difficulty` | `float(draft.get("difficulty", -1))`（缺键即 -1.0，必被范围检查拒绝） |
| `solution` | `str(draft.get("solution", ""))` |

`Item` 的其余字段（`options`、`discrimination`、`guess`、`misconceptions`）用 dataclass
默认值。**入库 Item 必须携带草稿的 `solution`（及全部七字段）**：契约测试只断言
`bank.has(...)` 不观察入库字段，但丢失 `solution` 属于存储数据分歧，禁止（探针已验证参考
实现入库 `solution == "6 + 5 = 11"`；itembank 契约亦不校验该字段，
src/xuexing/itembank.py:39-68 的 `validate_item` 无任何 solution 检查）。
若本步骤抛 `TypeError`/`ValueError`（如 `kps=None` 不可迭代、difficulty 无法 float）→
返回 `(False, [f"malformed draft: {e}"])`，bank 不变（此为唯一短路出口）。
`draft` 不是 dict（无 `.get`）时 `AttributeError` 原样冒泡 **[仅参考，未冻结]**。

**步骤 2/3/4（收集式，非短路）**——三步**无条件依序执行**，错误累积到同一个列表；
即使步骤 2 已产生校验错误，步骤 3、4 仍照常执行（**[仅参考]**：契约测试的拒绝用例
stem `"x"`/`"y"` 与 small_bank 各 stem 均不重复，未覆盖"校验错误+重复题干并存"；
参考实现为收集式，探针已验证并存场景返回三条错误，重生成实例必须同型）：

2. `errs.extend(bank.validate_item(item))`——题库校验错误**原样透传**（含
   `"difficulty out of [0,1]"`、`"empty answer"` 等，措辞属 itembank 契约）。
3. 对 `item.kps` 中每个不在 `valid_kp_ids` 的 k 追加
   `f"{item.id}: unknown kp {k}"`（按 kps 顺序，逐个）。
4. 按 `bank.items()`（id 升序）找**第一个** `existing.stem.strip() == item.stem.strip()`
   的既有题，追加 `f"{item.id}: duplicate stem with {existing.id}"` 后**停止查重**
   （至多一条 duplicate 错误）。两侧均 strip 比较。

**步骤 5（裁决）**：`errs` 非空 → `(False, errs)`，bank 不变；否则 `bank.add(item)` 后
`(True, [])`。若 id 与库中既有题重复但题干不同（步骤 4 查不出），`bank.add` 抛的
`ItemBankError`（ValueError 子类）**原样冒泡** **[仅参考，探针已验证]**。

[仅参考] 并存实例（探针实跑，无契约测试覆盖）：bank 已含 `a1`（stem `"stem-a1"`）时，
草稿 `{"id":"q1","item_type":"fill","stem":"stem-a1","answer":"","kps":["ghost"],
"difficulty":0.5}` →
`(False, ['q1: empty answer', 'q1: unknown kp ghost', 'q1: duplicate stem with a1'])`。

例子（摘自契约测试，test_agent_shell_contract.py:61-81）：

- `small_bank` 夹具 + `draft = draft_item(MockLLM("item_drafter"), "a", 0.3)`（id 为
  `"draft-a-30"`）：`try_accept_draft(draft, small_bank, {"a"})` → `(True, [])` 且
  `small_bank.has("draft-a-30")`。再试 `dict(draft, id="draft-a-30-2")`（同题干）→
  `(False, errs)` 且存在含 `"duplicate"` 的错误。
- 草稿 `{"id": "bad1", "item_type": "fill", "stem": "x", "answer": "1",
  "kps": ["ghost"], "difficulty": 0.5}` 对 `valid_kp_ids={"a"}` →
  `(False, errs)` 且存在含 `"unknown kp"` 的错误，且 `len(small_bank.items())` 不变；
  把 `difficulty` 换成 `2.0` → 存在含 `"difficulty"` 的错误。

## 4. 不变量（全部可被契约测试检验）

- I1 **空答案不归因**：`attribute_error` 对 `learner_answer.strip() == ""` 返回 `None`，
  且不调用 LLM（测试以固定回复含合法 id 的 client 证明：若调用 LLM 必返回该 id 而非 None，
  test_agent_shell_contract.py:47）。
- I2 **签名命中确定且免 LLM**：学生答案（strip 后）等于某误解某条 signature（strip 后，
  条目非空）时，按 misconceptions 列表顺序、组内 signature 顺序取第一个命中，
  返回其 `mc.id`，且 client 调用次数为 0（test_agent_shell_contract.py:36-39）。
- I3 **LLM 兜底恰好一次**：签名未命中时恰好调用一次 client；返回列表顺序第一个
  以子串出现在 strip 后回复中的 `mc.id`；无 id 出现（如 `"NONE"`）→ `None`
  （test_agent_shell_contract.py:43-46）。
- I4 **讲解必含提示且非空**：`explain_error` 返回值 strip 后非空且包含 hint；
  达成方式是 §3.6 的冻结耦合（`教学提示:` 半角冒号行 + explainer-mock 回显）
  （test_agent_shell_contract.py:50-52）；client 回复全空白时回退为 `f"【讲解】{hint}"`
  **[仅参考，探针已验证]**。
- I5 **出题草稿为解析 dict**：`draft_item` 返回 dict（JSON 解析结果，kps 缺省补
  `[kp_id]`），提示词满足 §3.7 的冻结耦合（同行 + 可自验正则谓词），
  回复无大括号对 → `LLMError`；全程不触碰 bank（test_agent_shell_contract.py:55-58 及
  61-63 的使用方式）。
- I6 **入库门成功路径**：合法且无重复的草稿 → `(True, [])`，且 `bank.has(draft["id"])`
  为真（test_agent_shell_contract.py:63-65）。
- I7 **同题干拒绝**：与既有题 stem 仅差首尾空白的草稿被拒，错误列表存在含
  `"duplicate"` 子串的条目（test_agent_shell_contract.py:66-68）。
- I8 **未知知识点拒绝**：kps 含 `valid_kp_ids` 之外的 id → 拒绝，错误列表存在含
  `"unknown kp"` 子串的条目（test_agent_shell_contract.py:73-76）。
- I9 **难度越界拒绝**：difficulty 不在 [0,1]（含缺键默认 -1.0）→ 拒绝，错误列表存在含
  `"difficulty"` 子串的条目（test_agent_shell_contract.py:78-81）。
- I10 **全有或全无**：任何被拒草稿不得改变 bank（`len(bank.items())` 不变）；
  只有零错误才 `bank.add`，成功恰新增一题（test_agent_shell_contract.py:71-77）。

## 5. 确定性与随机性

- `attribute_error`、`explain_error`、`draft_item`、`try_accept_draft`、`MockLLM`
  **禁止任何随机与隐藏时间**：不读时钟、不读环境变量、不用 `random`、不产生时间戳字段。
  同输入 + 同 client 行为 ⇒ 同输出（`MockLLM.calls` 这类记录性状态除外）。
- `MockLLM` 是其 mode 与入参的纯函数（追加 `calls` 记录除外），可重复重放。
- 本模块允许的"非确定性"仅来自生产 client（`OpenAICompatClient`）的网络回复；
  契约测试通过 `ScriptedLLM`/`MockLLM` 将其消除，重生成实例不得在业务函数内
  引入测试不可控的随机源。
- `try_accept_draft` 的查重顺序依赖 `bank.items()` 的 id 升序（ItemBank 契约），
  本模块不得自行排序既有题之外的任何东西。

## 6. 错误行为

| 输入/情形 | 行为 |
|---|---|
| `attribute_error` 学生答案空白（strip 后空） | 容忍：返回 `None`，不调 LLM（I1） |
| `attribute_error` 签名未命中且 LLM 无匹配 id | 容忍：返回 `None`（I3） |
| `explain_error` LLM 回复全空白 | 容忍：返回 `f"【讲解】{hint}"`（I4） |
| `draft_item` 回复无大括号对 | `LLMError("draft is not JSON")`（I5） |
| `draft_item` 回复有括号但非法 JSON | `json.JSONDecodeError` 冒泡 **[仅参考]** |
| `try_accept_draft` 字段收敛抛 TypeError/ValueError（如 `kps=None`） | 容忍：`(False, ["malformed draft: …"])`，bank 不变（唯一短路出口） |
| `try_accept_draft` 校验失败/未知 kp/重复题干（单类或多类并存） | 容忍：`(False, errs)`，bank 不变（I7-I10）；多类并存时三步照常执行、错误累积 **[仅参考]** |
| `try_accept_draft` 入库时 id 撞既有题（题干不同） | `ItemBankError`（ValueError 子类）冒泡 **[仅参考]** |
| `try_accept_draft` 收到非 dict 草稿 | `AttributeError` 冒泡 **[仅参考，未冻结]** |
| `OpenAICompatClient` 密钥缺失/HTTP 非 200/响应缺字段 | `LLMError` **[仅参考]** |

异常类型要求：`LLMError` 必须 `RuntimeError` 子类；容忍路径一律返回值表达，不抛异常。

## 7. 非目标

- 不做任何文件/网络 IO（`OpenAICompatClient` 是唯一豁免且无契约测试，重生成实例
  只需暴露同签名类）。业务函数不得读环境变量。
- 不实现重试、退避、超时、缓存、token 计数、限流等 LLM 工程设施；
  每个业务函数每次调用至多一次 `client.complete`。
- 不做题库校验逻辑本身——校验委托 `bank.validate_item`（itembank 模块契约），
  本模块只透传其错误并追加 unknown-kp / duplicate 两类。
- `draft_item` 不入库、不补全缺失字段（除 `kps` 缺省）、不校验 difficulty 范围；
  校验只在 `try_accept_draft` 做。
- 提示词具体措辞不冻结（除 §3.6/§3.7 声明的两处冻结耦合：`教学提示: {hint}` 半角冒号行、
  同行的 `kp={kp_id}` + `difficulty={difficulty:.2f}` 及其自验谓词）；system 文案同样不冻结。
  `attribute_error` 的提示词无任何可检验要求，仅为参考格式（§3.5）。
- 不修改入参：不得变更 `misconceptions`、`draft`、`valid_kp_ids`；
  `bank` 只在 I10 允许的唯一路径上被 `add`。
- 不产生任何时间戳/updated_at 类字段。
