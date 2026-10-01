# paper 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> **版本**：定稿 v2（由 drafts 版经对抗评审修复而来，修复记录见附录 A）。
> 标注「〔测试裁定〕」的行为由 tests/contract 直接断言；标注「〔参考裁定〕」的行为契约测试
> 未仲裁（已验证两种实现可通过全部测试），按参考实现 `src/xuexing/paper.py` 冻结并在当地注明。

## 1. 目的

`paper` 模块是出卷引擎，承担两个职责：(a) **静态诊断卷组装** —— 按 `{知识点: 题数}` 蓝图从题库
抽取题目，产出 `xuexing.types.Paper`（分节、题目 id 列表）；(b) **自适应逐题选题（CAT 式）** ——
给定学情画像与约束（已做题、知识点范围、每知识点题量上限、难度带），选出"预测答对概率最接近
0.5"（信息量最大代理指标）的下一题。模块纯计算：无文件/网络 IO，无判分，不更新掌握度。

依据：`src/xuexing/paper.py:1`（模块 docstring）、`tests/contract/test_paper_contract.py:1`。

## 2. 允许的依赖

- Python 标准库（参考实现用到 `random`；禁止其他隐藏依赖）
- `xuexing.types`（绝对导入：`from xuexing.types import ...`；至少需要 `Paper`、`Profile`）
- **禁止：其他一切 xuexing 模块，本模块无例外。** 特别注意：参考实现从 `.diagnosis` 导入了
  `slip_from_difficulty`（`src/xuexing/paper.py:7`），但重生成实现是单文件、只允许标准库 +
  `xuexing.types`（`tests/contract/conftest.py:1-5` 注明注入规则），因此本规格把该公式内联进
  `predicted_correct`（见 I10），重生成实现必须在模块内自行定义等价计算。
- 禁止第三方库、文件/网络 IO。
- 参数对象 `bank`（ItemBank）、`graph`（KPGraph）按结构使用（鸭子类型），**不得 import 其所在模块**。
  允许调用的最小表面：
  - `bank.items() -> list[Item]`：题库全部题目，**id 升序**（`src/xuexing/itembank.py:29-30`）
  - `bank.by_kp(kp_id, primary_only=True) -> list[Item]`：主知识点（`kps[0]`）等于 `kp_id` 的题目，
    id 升序（`src/xuexing/itembank.py:32-37`）
  - `graph.has(kp_id) -> bool`（`src/xuexing/kpgraph.py:86-87`）
  - `graph.get(kp_id) -> KnowledgePoint | None`，只用其 `.name` 字段（`src/xuexing/kpgraph.py:83-84`）
  - `Item` 上只用：`id`、`difficulty`、`kps`、`effective_guess()`（`src/xuexing/types.py:42-45`）
  - `Profile` 上只用：`mastery: dict[str, float]`（`src/xuexing/types.py:60-66`）

## 3. 公开 API

重生成模块必须暴露以下 4 个名字（契约测试直接 import，见
`tests/contract/test_paper_contract.py:5` 与 `:58`）：
`PaperError`、`generate_paper`、`predicted_correct`、`select_next_item`。

### 3.1 `PaperError`

```python
class PaperError(ValueError): ...
```

paper 模块所有校验失败的异常类型；**必须是 `ValueError` 的直接或间接子类**
（测试以 `pytest.raises(PaperError)` 断言，`test_paper_contract.py:26-33`；参考实现
`src/xuexing/paper.py:13-14`）。

### 3.2 `generate_paper`

```python
def generate_paper(
    bank: ItemBank,
    graph: KPGraph,
    blueprint: dict[str, int],
    seed: int,
    title: str = "诊断卷",
    difficulty_target: float = 0.5,
    paper_id: str = "",
) -> Paper:
```

按 `{知识点 id: 题数}` 蓝图组装静态卷。**语义（规范性组装过程，逐条冻结自
`src/xuexing/paper.py:37-59`）：**

1. **前置校验**（I1–I4：空蓝图、蓝图引用不存在的 kp、非正计数、`difficulty_target` 越界），
   任何一条失败即抛 `PaperError`，不返回部分结果。库存充足性（I5）**不属于前置校验**，
   在步骤 3 组装到对应节时检查（见 §6 错误表）。
2. 创建**一个**随机数生成器 `random.Random(seed)`，整个组装过程共用这一个实例。
3. 按 `sorted(blueprint)`（知识点 id 升序）逐节组装，每节：
   a. 候选题 = `bank.by_kp(kp_id, primary_only=True)`（即 `kps[0] == kp_id` 的题，id 升序）；
   b. 若候选数 `< n` → `PaperError`（库存不足，此检查发生在该节任何随机抽取之前）；
   c. 候选题按 `(abs(difficulty - difficulty_target), id)` 升序排名；
   d. **池 = 排名序列的前 2n 道（不足则全取），保持排名顺序进入 shuffle —— 构造池时不得重排。**
      〔参考裁定〕契约测试不仲裁池序：已实证"排名序池"与"id 序池"两种实现均通过全部契约测试
      （附录 A/R2），但二者对多数 seed 产出不同卷面（seed=9、`{"a":2}` 时分别为
      `["a2","a3"]` 与 `["a1","a3"]`）。本条按参考实现 `src/xuexing/paper.py:45-47`
      （`ranked = sorted(...)` 后直接 `pool = ranked[: max(n*2, n)]`）冻结；
   e. 用共享 rng 对池做 `shuffle`；
   f. 取洗牌后前 `n` 道，**按题目 id 升序**作为该节 `item_ids`。
4. 返回 `xuexing.types.Paper`：
   - `paper_id`：若传入 `paper_id` 非空则原样使用；否则由 seed 与蓝图派生
     （参考实现 `paper-{seed}-{abs(hash(tuple(sorted(blueprint.items())))) % 100000}`，
     `src/xuexing/paper.py:58` —— 该默认值**跨进程不稳定**，见 §5）；
   - `title`：原样使用（默认 `"诊断卷"`）；
   - `blueprint`：输入蓝图的**等值副本**（不得与输入 dict 别名共享；实跑验证：`p.blueprint == bp`
     为真、`p.blueprint is bp` 为假，改动输入 dict 不影响已产卷）；
   - `item_ids`：各节 `item_ids` 依节顺序连接；
   - `sections`：list[dict]，每节 `{"kp_id": str, "kp_name": str, "item_ids": list[str]}`，
     `kp_name` 取 `graph.get(kp_id).name`（`src/xuexing/paper.py:54`）。

**副作用：无** —— 不修改 `bank`、`graph`、输入 `blueprint`。

**例 1**〔测试裁定〕（摘自 `test_blueprint_assembly`，`test_paper_contract.py:9-16`；输出为本会话对
参考实现实跑结果）：`small_bank`（8 题：a1/a2/a3 主 kp `a` 难度 0.2/0.5/0.8；b1/b2 主 kp `b`；
c1 主 kp `c`；d1/d2 主 kp `d`，d1 为 choice 难度 0.5 guess 0.25，d2 为 fill 难度 0.5）+
`small_graph`（kp：a,b,c,d，a、d 无先序）时：

```
generate_paper(small_bank, small_graph, {"a": 2, "d": 2}, seed=5)
→ Paper(
    item_ids = ["a1", "a2", "d1", "d2"],
    blueprint = {"a": 2, "d": 2},
    sections = [
      {"kp_id": "a", "kp_name": "甲", "item_ids": ["a1", "a2"]},
      {"kp_id": "d", "kp_name": "丁", "item_ids": ["d1", "d2"]},
    ],
    ... )
```

测试断言：`sorted(item_ids) == ["a1","a2","d1","d2"]`、`len(set(item_ids)) == len(item_ids)`、
每节 `len(sec["item_ids"]) == blueprint[sec["kp_id"]]` 且节内每题 `kps[0] == sec["kp_id"]`。
（该 seed 下两种池序读法产出相同卷面，见附录 A/R2。）

**例 2**〔测试裁定＋参考裁定〕（确定性，摘自 `test_same_seed_same_paper`，
`test_paper_contract.py:19-22`；输出为实跑结果）：同一 bank/graph 下，
`generate_paper(bank, graph, {"a": 2}, seed=9)` 调用两次，`item_ids` 均为 `["a2", "a3"]`，
`sections` 均为 `[{"kp_id": "a", "kp_name": "甲", "item_ids": ["a2", "a3"]}]`，两次完全相等。
注：测试本身只做同实现两次调用的对比；`["a2","a3"]` 这一具体值由 §3.2 步骤 3d 的
排名序池冻结（id 序池会产出 `["a1","a3"]`，附录 A/R2）。

### 3.3 `predicted_correct`

```python
def predicted_correct(profile: Profile, item_difficulty: float, primary_mastery: float, guess: float) -> float:
```

给定主知识点掌握度，预测该题答对概率。**精确公式（冻结，含内联的滑率）**
（参考 `src/xuexing/paper.py:62-66` 与 `src/xuexing/diagnosis.py:19-21`）：

```
slip = clamp01(0.05 + 0.20 * item_difficulty)      # clamp01(x) = max(0.0, min(1.0, x))
p    = primary_mastery * (1 - slip) + (1 - primary_mastery) * guess
```

- **第一参数 `profile` 只为签名兼容而存在，不参与计算**（参考实现未使用它；
  测试按位置传入 profile，`test_paper_contract.py:62,64`）。
- 纯函数：无随机、无时间、无副作用（见 I15）。

**例 3**（实跑参考实现所得数值）：

```
predicted_correct(profile, 0.2, 0.5, 0.10) → 0.505
predicted_correct(profile, 0.5, 0.5, 0.10) → 0.475
predicted_correct(profile, 0.8, 0.5, 0.10) → 0.445
predicted_correct(profile, 0.5, 0.5, 0.25) → 0.55   # choice 题 guess=0.25（d1）
```

### 3.4 `select_next_item`

```python
def select_next_item(
    bank: ItemBank,
    profile: Profile,
    administered: set[str],
    scope: set[str],
    attempt_counts: dict[str, int],
    per_kp_cap: int = 3,
    difficulty_band: tuple[float, float] = (0.2, 0.8),
) -> str | None:
```

CAT 式选题：在约束内选"预测对半开"的题。**语义（冻结自 `src/xuexing/paper.py:83-102`）：**

1. 先校验 `difficulty_band`：不满足 `0.0 <= band[0] <= band[1] <= 1.0` → `PaperError`
   （在任何搜索之前抛出，即使题库为空）。
2. 遍历 `bank.items()`（id 升序），一道题**合格**当且仅当：
   - `item.id not in administered`；且
   - `item.kps` 非空且 `item.kps[0] in scope`（次要知识点不参与；`kps` 为空的题直接跳过、不报错；
     **`scope` 为空集时该条件恒假 → 无合格题 → 返回 `None`**。空 scope 不是"无范围约束"，
     见 §6；〔参考裁定〕契约测试从未传空 scope，此语义按参考 `src/xuexing/paper.py:90-91`
     冻结，并经实跑验证——附录 A/R1）；且
   - `attempt_counts.get(item.kps[0], 0) < per_kp_cap`（缺省计 0）；且
   - `difficulty_band[0] <= item.difficulty <= difficulty_band[1]`（**闭区间**）。
3. 对每道合格题：`m = profile.mastery.get(item.kps[0], 0.5)`（缺省 0.5）；
   `p = predicted_correct(profile, item.difficulty, m, item.effective_guess())`；
   得分 `score = -abs(p - 0.5)`。
4. **选题算法精确冻结（含并列规则，不只是结果）**〔参考裁定〕：契约夹具各题
   `|p-0.5|` 间隔 ≥ 0.005，测试无法触发近似并列；以下按参考 `src/xuexing/paper.py:87-101`
   逐字冻结（实跑验证见附录 A/R3）：

   ```python
   best_id, best_score = None, -2.0
   for item in bank.items():                 # 必须按 id 升序遍历
       <步骤 2 的合格性过滤>
       p = predicted_correct(profile, item.difficulty,
                            profile.mastery.get(item.kps[0], 0.5),
                            item.effective_guess())
       score = -abs(p - 0.5)
       if score > best_score + 1e-12 or (abs(score - best_score) <= 1e-12
                                         and (best_id is None or item.id < best_id)):
           best_id, best_score = item.id, score
   return best_id
   ```

   可观测后果：由于遍历按 id 升序，任何后继题的 id 都大于当前 `best_id`，并列子句
   （`item.id < best_id`）在该遍历序下恒为假，故实际效果是——**严格更优（分差 > 1e-12）才替换；
   分差 ∈ (0, 1e-12] 时保留先出现（更小 id）者**。"全局按 (score, id) 取最小"的等价写法
   **不符合本契约**：两题分数相差 0 < Δ ≤ 1e-12 且更优者 id 更大时，它选更优分，
   参考算法选更小 id（实证：x（d=0.25，p=0.5）与 y（d=0.25+1e-14，|p−0.5|≈9.99e-16），
   参考返回 `"x"`，全局最小返回 `"y"`，附录 A/R3）。
5. 无合格题返回 `None`（I13）。

**副作用：无** —— `select_next_item` **不**修改 `administered`、`attempt_counts`，**不**把选中题
登记到任何内部状态；已做题集合与计数完全由调用方维护（契约测试的用法即证据：
`test_paper_contract.py:39-47` 中测试自身执行 `counts["a"] = counts.get("a", 0) + 1`）。

**例 4**〔测试裁定〕（约束与耗尽，摘自 `test_selector_constraints` /
`test_selector_scope_and_administered`，`test_paper_contract.py:36-52`；序列为实跑参考实现结果）：
空作答画像（全 kp 掌握度 0.5，`src/xuexing/diagnosis.py:35,39`）、`scope={"a"}`、`per_kp_cap=3`
时，逐次调用（调用方每轮把选中 id 加入 administered、`counts["a"]` 自增 1）依次选中
`a1, a2, a3`；第 4 次调用返回 `None`；计数已满（`attempt_counts={"a": 3}`）时第一次调用即返回
`None`。同理，`scope={"a"}` 且 `administered={"a1","a2","a3"}`（cap=9）时返回 `None`；
`scope={"b"}` 时选中题的主知识点必为 `"b"`（实跑选中 `b1`：|p−0.5| = 0.005 < b2 的 0.035）。

**例 5**〔测试裁定〕（最大信息选题，摘自 `test_selector_picks_max_information`，
`test_paper_contract.py:57-65`；数据为实跑结果）：作答 `[Response("a1", True)]` 后画像
`mastery["a"]≈0.90099`、其余 kp 0.5；
`select_next_item(bank, profile, set(), {"a","b","c","d"}, {}, per_kp_cap=99)` 选中 **b1**
（|p−0.5| = 0.005，为全部 8 题最小；c1 为 0.015，d2 为 0.025，a3 为 0.2217…）。

## 4. 不变量（编号列出）

- **I1（空蓝图拒绝）**：`blueprint == {}` 时 `generate_paper` 抛 `PaperError`，且该检查优先于
  其他一切校验（含 `difficulty_target` 非法）。依据 `src/xuexing/paper.py:27-28`（实跑验证：
  空蓝图 + `difficulty_target=1.5` → 报 `"empty blueprint"` 而非难度越界）；
  测试 `test_blueprint_errors`（`test_paper_contract.py:27`）。〔测试裁定〕
- **I2（知识点必须存在）**：蓝图引用的每个 kp 必须 `graph.has(kp_id)` 为真，否则抛 `PaperError`。
  依据 `src/xuexing/paper.py:29-31`；测试 `test_paper_contract.py:29`（`{"ghost": 1}`）。〔测试裁定〕
- **I3（题数必须为正）**：每个蓝图计数必须 `> 0`，否则抛 `PaperError`。依据
  `src/xuexing/paper.py:32-33`；测试 `test_paper_contract.py:33`（`{"a": 0}`）。〔测试裁定〕
- **I4（难度目标越界拒绝）**：`difficulty_target not in [0.0, 1.0]` 时抛 `PaperError`
  （属于前置校验，蓝图非空时必检）。依据 `src/xuexing/paper.py:34-35`；实跑验证：
  `generate_paper(..., {"a": 2}, seed=1, difficulty_target=1.5)` → `PaperError`。〔参考裁定〕
- **I5（库存充足）**：任一 kp 的主知识点题目数 `< 蓝图数` 时抛 `PaperError`；该检查在逐节
  组装到该节时进行（§3.2 步骤 3a–3b）。依据 `src/xuexing/paper.py:42-44`；
  测试 `test_paper_contract.py:31`（`{"a": 99}`，库中仅 3 道 a 题）。〔测试裁定〕
- **I6（输出结构）**：`Paper.blueprint` 与输入蓝图等值（且是副本，非别名）；`len(sections) ==
  len(blueprint)`；sections 按 kp_id 升序；每节 `len(sec["item_ids"]) == blueprint[sec["kp_id"]]`；
  节内每题满足 `bank.get(iid).kps[0] == sec["kp_id"]`；`item_ids` 为各节依节顺序连接、节内 id 升序。
  依据 `src/xuexing/paper.py:40-59`；测试 `test_blueprint_assembly`
  （`test_paper_contract.py:11-16`）。〔测试裁定〕
- **I7（卷内无重复）**：`len(set(item_ids)) == len(item_ids)`。主知识点抽取
  （`primary_only=True`）保证每题至多属于一节。测试 `test_paper_contract.py:12`。〔测试裁定〕
- **I8（同输入同 seed 恒等）**：同一进程内，`(bank, graph, blueprint, seed, title,
  difficulty_target, paper_id)` 全同的两次 `generate_paper` 调用，`item_ids` 与 `sections` 完全
  相等。测试 `test_same_seed_same_paper`（`test_paper_contract.py:19-22`）。〔测试裁定〕
- **I9（选题约束）**：`select_next_item` 返回的 id（非 None 时）满足 I9a–I9d：
  (a) 不在 `administered` 中；(b) 主知识点 `kps[0] in scope`（空 scope ⇒ 任何题都不合格）；
  (c) `attempt_counts.get(kps[0], 0) < per_kp_cap`；(d) `difficulty_band[0] <= difficulty <=
  difficulty_band[1]`（闭区间）。依据 `src/xuexing/paper.py:88-95`；
  测试 `test_selector_constraints`、`test_selector_scope_and_administered`
  （`test_paper_contract.py:36-54`）。〔测试裁定〕
- **I10（预测公式冻结）**：`predicted_correct` 按公式
  `p = m*(1 - clamp01(0.05 + 0.20*d)) + (1 - m)*g` 计算；`profile` 参数不影响结果。
  依据 `src/xuexing/paper.py:62-66`、`src/xuexing/diagnosis.py:19-21`；例 3 数值可复验。〔参考裁定〕
- **I11（最大信息目标）**：在全部合格题中，选中题的 `|predicted_correct(...) - 0.5|` 最小
  （测试以 `p_chosen <= p_other + 1e-9` 容差断言，`test_paper_contract.py:62-65`）。〔测试裁定〕
- **I12（并列规则按流式算法冻结）**：不止冻结结果，还冻结算法——按 §3.4 步骤 4 的伪代码实现：
  id 升序流式遍历，仅当 `score > best_score + 1e-12` 才替换，分差 ∈ (0, 1e-12] 视为并列并保留
  先出现（更小 id）者。"全局按 (score, id) 取最小"**不满足本契约**（分歧场景实证见附录 A/R3）。
  依据 `src/xuexing/paper.py:99-101`。〔参考裁定〕
- **I13（无可选返回 None）**：无合格题时返回 `None`，不抛异常。构成情形包括但不限于：
  scope 空、`administered` 已覆盖 scope 内全部题、计数达 `per_kp_cap`、难度带内无题。
  测试 `test_paper_contract.py:38,47,52`。〔测试裁定〕
- **I14（缺省容忍）**：`profile.mastery` 缺 kp 时掌握度按 `0.5`；`attempt_counts` 缺 kp 时按 0；
  `kps` 为空的题跳过且不报错。依据 `src/xuexing/paper.py:90-96`。〔参考裁定〕
- **I15（选题与预测纯确定性）**：`predicted_correct` 与 `select_next_item` 不使用随机、不使用
  时间；输出由参数唯一决定。`select_next_item` 无 seed 参数也绝无隐藏随机。
  依据 `src/xuexing/paper.py:62-102`（无 `random`/时钟引用）。〔参考裁定〕
- **I16（难度带校验）**：`difficulty_band` 不满足 `0.0 <= band[0] <= band[1] <= 1.0` 时抛
  `PaperError`（在搜索前抛出，与题库内容无关）。依据 `src/xuexing/paper.py:83-84`；实跑验证：
  `difficulty_band=(0.8, 0.2)` → `PaperError`。〔参考裁定〕
- **I17（无状态）**：两个函数对传入对象（`bank`、`graph`、`profile`、`administered`、`scope`、
  `attempt_counts`）只读；跨调用不保留任何记忆，进度由调用方显式传入。
  依据 `src/xuexing/paper.py:37-59,83-102`（无外部状态写入）。〔参考裁定〕
- **I18（组装过程冻结）**：`generate_paper` 的逐节组装必须遵循 §3.2 步骤 2–3 的完整过程：
  单一 `random.Random(seed)` 实例、`sorted(blueprint)` 节序、`(abs(难度−目标), id)` 排名、
  **排名序池**、共享 rng 洗牌、取前 n、节内按 id 升序。该过程使同解释器上任何合格实现对同一
  seed 产出完全相同的卷面。结构部分由 I6–I8 间接检验；池序等细节测试不仲裁
  （附录 A/R2），按参考实现 `src/xuexing/paper.py:37-59` 冻结。〔参考裁定〕

注：错误消息文本（如 `"empty blueprint"`、`"not enough items for a: need 99, have 3"`，实跑捕获）
仅供参考，契约不冻结消息内容，只冻结异常类型与触发条件。

## 5. 确定性与随机性

- **必须同输入同输出**：`predicted_correct`、`select_next_item`（I15）；`generate_paper` 在同进程内
  同输入同 seed 恒等（I8）。
- **唯一允许的随机**：`generate_paper` 内 seed 驱动的 `random.Random(seed)` 洗牌。此处**有意**
  使用可复现的伪随机（加密强度不适用）：契约要求同 seed 同卷面（I8），参考实现即
  `random.Random(seed)`（`src/xuexing/paper.py:37`）。必须按 §3.2 / I18 的规范性过程使用
  （单 rng 实例、按 `sorted(blueprint)` 逐节共享同一随机流、**池保持排名顺序进入 shuffle**），
  使同解释器上任何合格实现对同一 seed 产出完全相同的卷面（例 2 的 `["a2","a3"]` 即此过程的产物；
  池序若按 id 序构造将产出 `["a1","a3"]`，附录 A/R2）。
- **允许的跨进程不稳定**：`paper_id` 为空时参考实现用内建 `hash()` 从 seed+蓝图派生默认 id
  （`src/xuexing/paper.py:58`）；Python 字符串 hash 默认进程级随机化，故**默认 `paper_id` 不保证
  跨进程相同，只保证同进程内同输入相同**。契约测试不断言 `paper_id` 的任何取值
  （`test_paper_contract.py` 中无一处引用）。重生成实现可复刻该派生方式，也可采用同进程稳定的
  其他确定性派生；不得引入时间戳或真随机。
- **禁止隐藏随机与时间**：本模块不产生任何时间戳字段（`Paper` 无时间字段，
  `src/xuexing/types.py:112-118`）；禁止读取时钟、环境、全局状态。

## 6. 错误行为

| 非法输入 | 异常 | 时机 |
| --- | --- | --- |
| `generate_paper`：`blueprint == {}` | `PaperError` | 前置校验，最先检查（I1） |
| `generate_paper`：蓝图引用图中不存在的 kp | `PaperError` | 前置校验阶段（I2） |
| `generate_paper`：某蓝图计数 `<= 0`（含 0、负数） | `PaperError` | 前置校验阶段（I3） |
| `generate_paper`：`difficulty_target` 不在 [0,1] | `PaperError` | 前置校验阶段（I4） |
| `generate_paper`：某 kp 主知识点题目数不足 | `PaperError` | 逐节组装到该节时，抽取前（I5） |
| `select_next_item`：`difficulty_band` 不满足 `0<=lo<=hi<=1` | `PaperError` | 搜索前立即（I16） |

- 全部异常在函数调用内同步抛出；`generate_paper` 不返回部分组装的 `Paper`。
- **必须容忍并跳过（不抛异常）**：
  - 题目 `kps` 为空列表 → `select_next_item` 跳过该题（I14）；
  - `profile.mastery` 缺 kp → 按 0.5；`attempt_counts` 缺 kp → 按 0（I14）；
  - `administered` 为空集合：合法输入，**不构成任何排除**（没有题被"已做"排除）；
  - `attempt_counts` 为空字典：合法输入，所有知识点计数按 0（**不构成排除**，除非 `per_kp_cap <= 0`）；
  - **`scope` 为空集合：不是"无范围约束"** —— `kps[0] in scope` 恒假，排除一切题，返回 `None`
    （I9/I13；〔参考裁定〕按 `src/xuexing/paper.py:90-91` 冻结，实跑验证见附录 A/R1；
    契约测试从未传入空 scope，两种相反读法都能通过全部测试，故明文固定为参考语义）；
  - 无合格题 → 返回 `None`（I13），不是错误。
- 除上表所列与 `PaperError` 外，本模块不引入新的异常类型；`ValueError` 子类优先的要求由
  `PaperError(ValueError)` 满足（`src/xuexing/paper.py:13-14`，实跑确认 `issubclass` 为真）。

## 7. 非目标

- **不判分、不更新掌握度**：作答结果处理是 `diagnosis` 模块的职责；本模块只读 `Profile.mastery`。
- **不读取图谱结构**：`select_next_item` 完全不接触 `KPGraph`（无先序/前沿约束，scope 由调用方给）；
  `generate_paper` 只用 `graph.has` / `graph.get(kp).name`。
- **不使用以下 Item 字段**：`discrimination`、`misconceptions`、`solution`、`stem`、次要知识点
  （`kps[1:]`）。选题与组卷只看 `id`、`difficulty`、`kps[0]`、`effective_guess()`。
- **不做任何 IO 与渲染**：不落盘、不出 HTML/PDF、不调用网络。
- **不维护跨调用状态**：不记忆已出过的卷、不自动登记已做题（I17）；多轮自适应的进度管理在调用方。
- **不保证默认 `paper_id` 跨进程稳定**（§5）；不提供 uuid/时间戳式 id 生成。
- **不做蓝图之外的内容决策**：不自行增删题量、不跨节补题、不支持按次要知识点或 cluster 配题。

## 附录 A：对抗评审修复记录

以下为 drafts 版 → 本定稿的全部修复。除 R4 为纯文本一致性修复外，每条均含本会话实跑证据
（命令 `python ".tmp_review_checks/checks.py"`，脚本含契约夹具的等价复现；脚本为一次性验证
工件，验证后已删除）。

| # | 严重度 | 评审问题 | 修复 | 证据（本会话实跑） |
| --- | --- | --- | --- | --- |
| R1 | major | §6 称空 scope 是"无约束维度"，与 §3.4/I13 的 `kps[0] in scope`（空集恒假）矛盾；测试从未传空 scope，无法仲裁 | §6/I13/I9 明文：空 `administered`、空 `attempt_counts` 不构成排除；**空 `scope` 排除一切题 → 返回 None**，按参考 `paper.py:90-91` 冻结并注明 | `select_next_item(bank, prof, set(), set(), {}, per_kp_cap=9)` → `None`（参考实现实跑） |
| R2 | major | §3.2 未明说池进入 shuffle 前保持排名序；两种读法都能通过全部测试但 seed=9 卷面分歧（`['a2','a3']` vs `['a1','a3']`） | §3.2 步骤 3d、I18、§5 明文"**池保持排名顺序进入 shuffle，不得重排**"，标注〔参考裁定〕并注明测试不仲裁（`paper.py:45-47`） | 构造仅池序不同的两个重生成变体 implA/implB，经 conftest 注入各跑全量契约测试：`set XX_IMPL_DIR=…\implA&& set XX_MODULES=paper&& python -m pytest tests/contract/test_paper_contract.py -q` → **6 passed**；同命令 implB → **6 passed**；卷面对比：seed=9 `{"a":2}` → A=`['a2','a3']`、B=`['a1','a3']`；seed=5 `{"a":2,"d":2}` → 两者同 `['a1','a2','d1','d2']`（故 seed=5 用例无法区分两种读法） |
| R3 | minor | I12 只冻结并列结果未冻结算法；"流式 + 容差保留小 id"与"全局 (score,id) 最小"在 Δ∈(0,1e-12] 时分歧，夹具分数间隔 ≥0.005 无法触发 | §3.4 步骤 4、I12 冻结流式算法精确伪代码（`paper.py:99-101` 逐字），声明全局最小写法不满足契约，标注〔参考裁定〕 | 构造 x（d=0.25，p=0.5，score=-0.0）与 y（d=0.25+1e-14，score≈-9.99e-16，Δ∈(0,1e-12]）：参考 `select_next_item` 返回 `'x'`（流式保小 id），全局 (score,id) 最小返回 `'y'` |
| R4 | minor | §3.2 步骤 1"先做全部校验"与 §3.2 步骤 3b、§6"组装到该节时"矛盾 | 统一为：**前置校验仅 I1–I4**（§3.2 步骤 1 改写）；I5 库存检查在逐节组装到该节时进行；§6 表格时机列同步。两种表述的可观测行为本就相同（都只抛 `PaperError`、不返回部分卷），无行为变更 | 文本一致性修复；检查位置依据 `src/xuexing/paper.py:27-44` 实读 |
