# kpgraph 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。

**证据标记**：
- 【契约】= `tests/contract/test_kpgraph_contract.py` 明确断言的行为（行为 ground truth）；
- 【参考】= 参考实现 `src/xuexing/kpgraph.py` 中可读出、且起草/定稿时实际运行复核过的行为（API 发现）。
- 两者冲突时以【契约】为准；仅【参考】的条款同样是冻结契约（重生成实例不得偏离）。
- **精确性规则**：凡【契约】只断言部分性质（如"非空""成员属于""长度与偏序"）的条款，本文明确写出测试钉住的范围；
  超出该范围的精确输出（完整序列、精确消息文本、消息判定顺序）由【参考】单独冻结，不得误读为有测试兜底。

## 1. 目的

知识点图谱：以 `KnowledgePoint` 为节点、以"先序边"（prereq → kp，含义：prereq 必须先于 kp 掌握）为边，
提供图谱构建、一致性校验（含环检测）、确定性拓扑排序、祖先/后代传递闭包查询，以及
"前沿知识点"（当前即可学习：自身未掌握且所有先序已掌握）计算。
供诊断、路径规划等下游模块消费。

## 2. 允许的依赖

- Python 标准库（其中 `json` 仅用于 `load_kpgraph` 的文件读取）
- `xuexing.types`（**绝对导入**：`from xuexing.types import KnowledgePoint`）
- 禁止：其他 xuexing 模块、第三方库、除 `load_kpgraph` 读入 `path` 参数所指文件之外的任何文件/网络 IO
- 重生成实例必须是**单文件**，由 conftest 以 `spec_from_file_location` 独立装载并顶替
  `sys.modules["xuexing.kpgraph"]`（tests/contract/conftest.py:14-26、conftest.py:3-4），
  因此**不得使用包内相对导入**（参考实现的 `from .types import`（kpgraph.py:7）在重生成实例中必须改写为绝对导入）。

### 2.1 `xuexing.types` 是冻结 schema，不随模块重生成

- conftest 的重生成注入只顶替 `MODULES` 列表中的模块（conftest.py:10：kpgraph/itembank/diagnosis/paper/
  scheduler/pedagogy/route/agent_shell），**不含 `types`**；且 conftest.py:12 先 `import xuexing`
  完整加载参考包，之后才做顶替。因此重生成实例内的 `from xuexing.types import KnowledgePoint`
  绑定的就是参考包的 dataclass。
  **注入实验（定稿时执行）**：以 `XX_IMPL_DIR` 注入一个仅含 `from xuexing.types import KnowledgePoint`
  的 stub，conftest 以 `ImportError: cannot import name 'KPGraph' from '_regen_kpgraph'` 证实顶替发生；
  stub 装载时写下的快照为字段 `['id','name','subject','grade','cluster','description','standard_ref','prereqs']`、
  `__module__ == "xuexing.types"`——即参考 dataclass 本尊。
- 冻结签名（src/xuexing/types.py:12-23，`@dataclass`）：

  ```python
  KnowledgePoint(id: str, name: str, subject: str, grade: int, cluster: str,
                 description: str = "", standard_ref: str = "",
                 prereqs: list[str] = field(default_factory=list))
  ```

  前 5 个字段必填，后 3 个有默认值。
- 重生成实例**不得重定义、影子化或本地复制**任何 `xuexing.types` 中的类，一律绝对导入使用。
- 推论（消除实现分歧点）：`kpgraph_from_dict` 构造节点时，显式传满 8 个具名参数与只传必填
  6 项（`description`/`standard_ref`/`prereqs` 由 dataclass 默认值兜底）产出**逐字段相同**的对象，
  两种写法均合规且不可观察地区分。

## 3. 公开 API

重生成实例必须暴露下列全部名字（conftest.py:4 "暴露模块全部公开 API"）。

### 3.0 `KPGraphError(ValueError)`

模块唯一异常类型，**必须**是 `ValueError` 的子类。
【契约】test_duplicate_and_unknown_errors（test_kpgraph_contract.py:31-39）以其捕获全部三类构建错误；
【参考】issubclass(KPGraphError, ValueError) 为 True（kpgraph.py:10，运行复核）。

### 3.1 `KPGraph`

`__init__(self) -> None` —— 无参构造空图。【参考】

#### `add_kp(self, kp: KnowledgePoint) -> None`

加入一个知识点节点。语义：注册 `kp.id`，并为其初始化空的后继边表。
- 重复 id → `KPGraphError`（消息含该 id；参考消息 `duplicate kp id: {id}`）。**时机：立即**。
  【契约】test_duplicate_and_unknown_errors:33-35（异常类型）+【参考】消息文本。
- `kp.prereqs` 声明**不在此时校验**（未知 prereq、未加边、重复声明都容忍，由 `validate()` 事后报告）。【参考】kpgraph.py:20-24

#### `add_edge(self, prereq_id: str, kp_id: str) -> None`

加入先序边：`prereq_id` 必须先于 `kp_id` 掌握（kpgraph.py:27 docstring）。
检查**有固定顺序**：先端点存在性、后自环（kpgraph.py:28-31 的先后即冻结语义）。
- 任一端点未 `add_kp` → `KPGraphError`（参考消息 `unknown endpoint in edge {prereq_id} -> {kp_id}`）。**时机：立即**。
  【契约】test_duplicate_and_unknown_errors:36-37（异常类型）+【参考】消息文本。
- `prereq_id == kp_id`（自环）→ `KPGraphError`（参考消息 `self loop`）。**时机：立即**。
  【契约】test_duplicate_and_unknown_errors:38-39（异常类型）+【参考】消息文本。
- **两条件同时成立时端点检查优先**：`add_edge("x", "x")`（x 未加入）报 unknown endpoint 而非 self loop。
  运行复核：`unknown endpoint in edge x -> x`。【参考】（契约只钉异常类型，消息与判定顺序由参考冻结。）
- 重复加同一条边 → **不报错、不产生重复边**（幂等）。【参考】kpgraph.py:32-33；运行复核：`add_edge("a","b")` 两次后 `children("a") == ["b"]` 且 `validate() == []`。

#### `validate(self) -> list[str]`

一致性检查，**以返回值报告错误，不抛异常**。恰好检查四类问题，每条问题一个 `str`，**每类检查有明确的信息源**：

| # | 检查 | 信息源 | 参考消息 |
|---|---|---|---|
| 1 | 声明的 prereq 指向不存在的节点 | 声明（`p` 不在图中） | `"{kp_id}: unknown prereq {p}"`（kpgraph.py:40） |
| 2 | 声明了 prereq 但未加对应边 | 声明 ∘ 边（逐条声明查直连边） | `"{kp_id}: prereq {p} missing edge"`（kpgraph.py:42） |
| 3 | 加了边但未在 `prereqs` 中声明 | 边 ∘ 声明 | `"edge {p}->{c} not declared in prereqs"`（kpgraph.py:46） |
| 4 | 图含先序环 | **只依据已添加的边**（kpgraph.py:54-77 遍历 `_children`；不看声明） | `"graph contains a prerequisite cycle"`（kpgraph.py:48） |

- **环检测只看边，不看声明**：声明成环但未加边不报 cycle。运行复核——
  `a.prereqs=[b]`、`b.prereqs=[a]`、无任何 `add_edge`：`validate() == ["a: prereq b missing edge", "b: prereq a missing edge"]`（无 cycle 条目，且 `topological_order()` 不抛，返回 `["a","b"]`）；
  补上 `add_edge("a","b")`、`add_edge("b","a")` 后：`validate() == ["graph contains a prerequisite cycle"]`。
- 返回 `sorted(set(errors))`：升序、按字符串精确相等去重。检查 2 按**每次声明**独立检查，同一缺陷的重复声明产生相同消息，去重后只出现一条（运行复核：`prereqs=["a","a"]` 且未加边 → 恰一条 `"... prereq a missing edge"`）。【参考】kpgraph.py:49
- **返回 `[]` ⟺ 无上述四类问题**（图完全一致且边集无环）。【契约】test_validate_reports_missing_edge_declaration:56-62（非空/为空断言）+【参考】精确消息、排序与去重。
- 【契约】test_cycle_is_rejected:26 环图 `validate()` 非空。

#### `kps(self) -> list[KnowledgePoint]`

返回全部知识点，**按 id 升序**（与加入顺序无关）。【参考】kpgraph.py:80-81；运行复核：按 d,b,a,c 顺序加入 → 返回 a,b,c,d。
返回的 **list 是新建容器**（外部 append/重排不影响图），但其中是与图内**共享的同一批 KnowledgePoint 对象**（见下"副本语义"）。
被 conftest `small_graph` 夹具用于遍历（conftest.py:44），空图返回 `[]`。【参考】运行复核。

#### `get(self, kp_id: str) -> Optional[KnowledgePoint]`

按 id 取节点；不存在返回 `None`。返回的是图内存储的**同一对象**（重复调用 `is` 相同；对其字段赋值会反映到图中）。【契约】test_get_and_has:67-68（`get("a").name == "甲"`、`get("z") is None`）+【参考】共享语义（运行复核）。

#### `has(self, kp_id: str) -> bool`

id 是否在图中。【契约】test_get_and_has:66。

#### `children(self, kp_id: str) -> list[str]`

`kp_id` 的直接后继（已加边的、比它晚学的节点 id），**升序**；未知 id 返回 `[]`；返回**新建 list**（外部修改不影响图，运行复核：向返回值 append 后再查不变）。【参考】kpgraph.py:89-90；排序运行复核：乱序加边 → `children("a") == ["b","c","d"]`；`children("x") == []`。

#### `prereqs(self, kp_id: str) -> list[str]`

`kp_id` 声明的先序 id 列表，**保持声明顺序、原样保留重复项**（声明 `["a","a"]` → 返回 `["a","a"]`，运行复核）；不排序；未知 id 返回 `[]`；返回**副本**（修改返回值不影响图）。【参考】kpgraph.py:92-94；
【契约】test_ancestors_transitive:45（`prereqs("c") == ["b"]`）。

#### `ancestors(self, kp_id: str) -> set[str]`

`kp_id` 全部传递先序（**只依据 `prereqs` 声明**；合法无环图下不含 `kp_id` 自身）；返回新建 set。【参考】kpgraph.py:96-105（经 `self.prereqs` 递归；声明中的重复项由 seen 集合天然吸收）。

#### `descendants(self, kp_id: str) -> set[str]`

`kp_id` 全部传递后继（**只依据已添加的边**；合法无环图下不含 `kp_id` 自身）；返回新建 set。【参考】kpgraph.py:107-116（经 `self.children` 递归）。

【契约】test_ancestors_transitive:42-44（small_graph：`ancestors("c") == {"a","b"}`、`descendants("a") == {"b","c"}`，均为集合精确相等断言）。

> **副本语义（适用于全部查询返回值）**：容器一律新建——修改 `children`/`kps` 返回的 list、
> `ancestors`/`descendants` 返回的 set、`prereqs` 返回的 list，都不影响图内部状态；
> 但容器内的 **KnowledgePoint 对象与图共享同一实例**——经 `get`/`kps` 拿到的对象做字段变更会反映到图中。
> 测试未覆盖，按参考实现冻结（运行复核：向 `children("a")` 返回值 append "hacked" 后再查仍 `["b"]`；
> `kps()[0].name = "RENAMED"` 后 `get("a").name` 同步变化且 `get("a") is kps()[0]`）。

#### `topological_order(self) -> list[str]`

拓扑排序：返回**全部已注册节点** id 的列表，任何边的 prereq 都排在其后继之前。
- **只依据已添加的边**，不看 `prereqs` 声明。可观察证据（完整前提，运行复核）：

  ```python
  g = KPGraph()
  g.add_kp(kp("z")); g.add_kp(kp("b", prereqs=["z"]))   # z、b 均已 add_kp；未加任何边
  g.topological_order()   # == ["b", "z"]：无边 → 两者入度同为 0，字典序 b < z；声明的 z 不会被隐式注册、也不产生入度
  h = KPGraph()
  h.add_kp(kp("z")); h.add_kp(kp("b"))                    # 均已注册；未声明 prereqs
  h.add_edge("z", "b")
  h.topological_order()   # == ["z", "b"]：边约束推翻字典序
  ```

  【参考】kpgraph.py:120-124
- **确定性**：Kahn 算法 + **字典序破平**（ready 集与后继扩展均按 id 升序）。
  【契约】test_topological_order_places_prereqs_first:12-16 **只断言** `len(order) == 4` 且
  `pos["a"] < pos["b"] < pos["c"]`（例如 `["a","b","d","c"]` 亦能通过）；
  **精确序列** `["a","b","c","d"]` 由【参考】冻结（kpgraph.py:124-134；运行复核输出 `["a","b","c","d"]`，20 次调用同一结果）。
- 图含环（边环）→ `KPGraphError`（参考消息 `cycle detected in topological_order`），**时机：调用时**。
  【契约】test_cycle_is_rejected:27-28（断言 raises Exception；异常的具体类型按本条冻结为 KPGraphError）。【参考】kpgraph.py:135-136、运行复核。
- 空图返回 `[]`。【参考】运行复核。

#### `frontier(self, mastery: dict[str, float], threshold: float) -> list[str]`

前沿（当前可学）知识点：`kp` 入选 ⟺ `mastery.get(kp.id, 0.0) < threshold` **且** 对其声明的每个 prereq `p`：
`mastery.get(p, 0.0) >= threshold`。
- 缺失的 mastery 键一律按 `0.0`（未掌握）参与两侧比较；`mastery` 中多余的键忽略。【参考】kpgraph.py:142-145；运行复核：空 mastery → 所有零声明 prereq 的节点入选；多余键不改变结果。
- 边界含等号：mastery 恰等于 threshold 视为"已掌握"（自身等于 → 不入选；prereq 等于 → 不阻塞）。运行复核：`{"a":0.65,"b":0.65}`、threshold 0.65 → `[]`；`{"a":0.65,"b":0.64}` → `["b"]`。
- **只看声明的 prereqs，不看边**（运行复核：加边 a→b 但 b 未声明 prereqs，mastery a=0.0 → b 仍入选）。声明中的重复项不影响 `all()` 判定。【参考】
- 排序：按 `(-后代数, id)` —— 后代数（`len(descendants(k))`）降序，平局按 id 升序。【参考】kpgraph.py:147-148；
  运行复核：零声明图 x/y/z 平局 → `["x","y","z"]`；a 有 2 个后代、d 有 1 个 → `["a","d"]`。

【契约】test_frontier_semantics:48-53 —— small_graph、`mastery={"a":0.9,"b":0.2,"c":0.1,"d":0.9}`、`threshold=0.65`：
**测试只断言成员/非成员**（`"b" ∈`、`"c" ∉`、`"a","d" ∉`）；完整返回值 `["b"]` 由【参考】冻结（运行复核）。

#### `kpgraph_from_dict(data: dict) -> KPGraph`

从 dict 构图。**结构性条款**（全部【参考】，运行复核）：
- 顶层必需键 `"knowledge_points"`；每个节点必需键 `id`、`name`。
- **拣选式构造**：只读取节点的 8 个已知键（id/name/subject/grade/cluster/description/standard_ref/prereqs）；
  节点 dict 中的**额外键被忽略**，不泄漏到产出对象（复核：含 `bogus_key` 的节点正常构建，产出对象无该属性）。
- 字段映射与缺省：`subject` 缺省 `"math"`；`grade` 缺省 `7` 且**经 `int()` 强转**（字符串 `"8"` → `8`）；
  `cluster`/`description`/`standard_ref` 缺省 `""`；`prereqs` 缺省 `[]` 且**经 `list()` 强转**——
  字符串会被拆成单字符列表（`"ab"` → `["a","b"]`；若拆出的 id 恰为节点自身将触发自环 KPGraphError），
  不可迭代值（如 `5`）→ 原生 `TypeError`。
- 构造顺序：先对全部节点 `add_kp`，再对每条声明 prereq `add_edge`（补边由 I3 幂等性兜住重复声明）。
- 构建期错误（**时机：构建时**）：重复 id、未知 prereq、自引用 prereqs → `KPGraphError`（复核三种情形，消息同 §3.1 add_kp/add_edge）。
- 缺 `"knowledge_points"` 键或节点缺 `id`/`name` → 原生 `KeyError`（未包装）。
- `"knowledge_points"` 值非列表（str/dict/None）或节点元素非 dict → 原生 `TypeError` 透传
  （复核：`'string indices must be integers, not 'str''` / `"'NoneType' object is not iterable"`）。
- 构建出的图含环**不被拒绝**（环只在 `topological_order` 时暴露）。【参考】kpgraph.py:157-175 无环检查。

构造机制（8 具名参数或 mapping 展开）自由，但产出对象的 8 个字段必须等于上述映射（§2.1 已保证 types 冻结，
传参与否不可观察地区分）。

#### `load_kpgraph(path: str) -> KPGraph`

`open(path, encoding="utf-8")` 读 JSON 后交给 `kpgraph_from_dict`。运行复核：正常文件往返成功。
错误路径（运行复核）：路径不存在 → `FileNotFoundError`；JSON 非法 → `json.JSONDecodeError`；
文件内容含未知 prereq → `KPGraphError`（经 from_dict）。

### 3.2 具体输入输出例子（摘自契约测试；证据精确性按证据标记规则标注）

**例 1**（conftest.py:37-47 夹具 + test_kpgraph_contract.py:12-16, 42-45, 65-68）：

```python
small_graph:  节点 a(甲,c1) b(乙,c1,prereqs=[a]) c(丙,c2,prereqs=[b]) d(丁,c2)，并按声明补边 a→b, b→c
small_graph.topological_order()   # 测试仅断言 len==4 且 pos a<b<c；精确序列 ["a","b","c","d"] 为【参考】冻结
small_graph.ancestors("c")        # == {"a", "b"}      【契约】集合精确相等
small_graph.descendants("a")      # == {"b", "c"}      【契约】集合精确相等
small_graph.prereqs("c")          # == ["b"]           【契约】列表精确相等
small_graph.get("a").name         # == "甲"            【契约】；get("z") is None【契约】；has("a") True / has("z") False【契约】
```

**例 2**（test_kpgraph_contract.py:48-53）：

```python
small_graph.frontier({"a": 0.9, "b": 0.2, "c": 0.1, "d": 0.9}, threshold=0.65)
# 【契约】只断言: "b" ∈ 结果、("c"、"a"、"d") ∉ 结果
# 【参考】冻结完整返回值: ["b"]（运行复核）
```

**例 3**（test_kpgraph_contract.py:19-28）：

```python
g = KPGraph(); 加入 a、b、c（无声明）；add_edge a→b, b→c, c→a
g.validate()            # 【契约】非空；【参考】冻结恰 4 条且有序：3 条 "edge ... not declared in prereqs" + "graph contains a prerequisite cycle"（运行复核）
g.topological_order()   # 【契约】raises Exception；【参考】冻结异常类型为 KPGraphError（运行复核）
```

## 4. 不变量（全部可被契约测试或上述运行复核检验）

- I1 **节点唯一**：图中 id 互不重复；重复 `add_kp` → `KPGraphError`。【契约:33-35】
- I2 **边端点合法且检查有序**：`add_edge` 两端点必须已 `add_kp`，且两端不同（禁止自环），违者 `KPGraphError`；
  两条件同时成立时按"先端点后自环"判定。【契约:36-39（类型）】+【参考（顺序与消息）】
- I3 **边幂等**：同一 `add_edge` 调用两次不报错、后继表不出现重复 id。【参考（运行复核）】
- I4 **信息源分工**：`topological_order`、`descendants`/`children` 只依据**已添加的边**；
  `ancestors`/`prereqs`/`frontier` 只依据 **`KnowledgePoint.prereqs` 声明**；
  `validate` 的检查 1、2 以声明为主语，检查 3 以边为主语，检查 4（环）**只看边**。
  声明与边一致（合法图）时两种视角等价；不一致时各函数按本条取数，模块**不自动同步**两者（差异由 `validate` 报告）。
  【参考（kpgraph.py:98/109/120-124/145/54-77 + 运行复核，含"声明环不报 cycle"例）】
- I5 **拓扑正确与拒环**：`topological_order` 返回恰含全部**已注册**节点 id（声明不隐式注册节点），
  且每条边 prereq 位置在前；边集含环时抛 `KPGraphError`。【契约:12-16, 27-28】
- I6 **拓扑确定性**：破平规则唯一（字典序），同图重复调用结果相同；small_graph 的精确序列
  `["a","b","c","d"]` 由参考冻结（测试只钉长度与偏序，见 §3.1）。【契约:12-16】+【参考（运行复核 20 次一致）】
- I7 **闭包正确**：`ancestors`/`descendants` 分别是声明先序边/已加边的传递闭包，合法图下不含起点自身。【契约:42-45】
- I8 **frontier 成员语义**：入选 ⟺ 自身 mastery（缺省 0.0）< threshold 且全部声明 prereq 的 mastery（缺省 0.0）≥ threshold；
  比较含等号边界；多余 mastery 键无效；声明重复项不影响判定。【契约:48-53（成员断言）+ 参考（运行复核边界）】
- I9 **frontier 排序**：后代数降序、id 升序破平。【参考（运行复核）】
- I10 **validate 完备且无副作用**：四类问题（未知声明 prereq / 声明未加边 / 边未声明 / 边环）各产出一条错误；
  结果升序去重（重复声明产生的同文消息合并为一条）；`[]` ⟺ 图合法；调用不抛异常、不改图。【契约:56-62 + 参考（运行复核）】
- I11 **环只被两处处理**：`validate` 报告（返回值），`topological_order` 拒绝（KPGraphError）；其余查询在含环图上的行为不在本契约内（测试未覆盖，重生成实现可沿用参考实现的终止性保证即可）。【契约:19-28】
- I12 **查询安全**：`get` 未知 → `None`；`has` 未知 → `False`；`children`/`prereqs` 未知 id → `[]`。【契约:65-68】
- I13 **副本语义**：全部查询返回**新建容器**（修改返回的 list/set 不影响图）；
  但容器内的 KnowledgePoint 对象与图**共享同一实例**（经 `get`/`kps` 取得的对象做字段变更反映到图，`get` 重复调用 `is` 相同）。
  `prereqs` 额外保证返回 list 副本且保留声明顺序与重复项。【参考（运行复核；测试未覆盖，按参考冻结）】
- I14 **kps 排序**：`kps()` 按 id 升序，与加入顺序无关。【参考（运行复核）】
- I15 **序列化构造语义**：`kpgraph_from_dict`/`load_kpgraph` 的必需键、拣选式字段映射、缺省值、
  `grade`→`int()` 与 `prereqs`→`list()` 强转、额外键忽略、构建期 KPGraphError、
  KeyError/TypeError 透传，如 §3.1 所列。【参考（运行复核）】
- I16 **无随机、无时钟**：模块不使用 random、不读取系统时间；所有输出由输入唯一决定（见 §5）。【参考（kpgraph.py 全文无 random/time；契约测试无任何 seed/时间断言）】

## 5. 确定性与随机性

- **全部公开函数同输入同输出**：本模块无任何随机源、无 seed 参数、无时间戳字段（`KnowledgePoint` 无时间字段；
  `Profile.updated_at`/`LearningPlan.created_at` 属其他模块，kpgraph 不读写）。
- 排序即契约：`kps`/`children` 升序、`prereqs` 保持声明序（含重复项）、`topological_order` 字典序破平（I6）、
  `frontier` 按 `(-后代数, id)`（I9）、`validate` 升序去重（I10）。
- 唯一的环境读取是 `load_kpgraph` 打开 `path` 所指文件；文件字节相同则结果相同。
- 禁止：隐藏随机、依赖 dict 插入顺序/哈希序的输出、依赖 locale 的排序。

## 6. 错误行为

| 非法输入 | 行为 | 时机 | 证据 |
|---|---|---|---|
| `add_kp` 重复 id | `KPGraphError` | 立即 | 【契约:33-35】 |
| `add_edge` 端点未知 | `KPGraphError`（消息 `unknown endpoint in edge {p} -> {k}`） | 立即 | 【契约:36-37（类型）+参考（消息）】 |
| `add_edge` 自环 | `KPGraphError`（消息 `self loop`） | 立即 | 【契约:38-39（类型）+参考（消息）】 |
| `add_edge` 端点未知且自环同时成立 | `KPGraphError`，按"先端点后自环"报 unknown endpoint | 立即 | 【参考（运行复核）】 |
| `add_edge` 重复边 | 容忍（幂等，I3） | — | 【参考】 |
| `topological_order` 遇边环 | `KPGraphError` | 调用时 | 【契约:27-28（Exception）+参考（类型）】 |
| 声明的 prereq 未知 / 未加边 / 重复声明 | 容忍，不在 `add_*` 报错；由 `validate()` 以字符串报告（重复声明同文去重） | 校验时 | 【契约:56-62 + 参考】 |
| `kpgraph_from_dict` 缺 `knowledge_points` / 节点缺 `id`/`name` | 原生 `KeyError` | 构建时 | 【参考（运行复核）】 |
| `kpgraph_from_dict` 节点含额外键 | 忽略（拣选式构造） | 构建时 | 【参考（运行复核）】 |
| `kpgraph_from_dict` `knowledge_points` 非列表 / 节点非 dict | 原生 `TypeError` 透传 | 构建时 | 【参考（运行复核）】 |
| `kpgraph_from_dict` `prereqs` 非可迭代 / 字符串 | `TypeError` / 拆成单字符列表（可致自环 KPGraphError） | 构建时 | 【参考（运行复核）】 |
| `kpgraph_from_dict` 重复 id / 未知 prereq / 自引用 prereqs | `KPGraphError` | 构建时 | 【参考（运行复核）】 |
| `load_kpgraph` 路径不存在 | `FileNotFoundError` | 调用时 | 【参考（运行复核）】 |
| `load_kpgraph` JSON 非法 | `json.JSONDecodeError` | 调用时 | 【参考（运行复核）】 |

原则：`ValueError` 子类（`KPGraphError`）优先用于领域错误；结构性/环境性错误（缺键、类型不符、文件、JSON）透传原生异常。
所有 `KPGraphError` 在违规操作**当下**抛出（fail-fast），不留迟到失败。

## 7. 非目标

- 不校验 `KnowledgePoint` 的业务字段（subject/grade 取值域、name 非空等）；只管理 id 唯一性与图结构。
- 不检查 `mastery` 数值域（[0,1] 之外的值不拒绝，按数值直接参与 I8 比较）；不检查 threshold 域。
- 不提供删除节点/边的 API；不支持图的修改通知、事件、监听。
- 不自动补边、不自动同步声明与边（两者独立存储，差异只由 `validate` 报告，见 I4）。
- 节点 dict 的未知额外键不做透传或保留（拣选后丢弃，见 I15）；不校验其类型。
- 除 `load_kpgraph` 只读外无任何持久化；无 save/导出/序列化输出（`KnowledgePoint` 的序列化属 `xuexing.types`）。
- 不做掌握度推断、不做推荐排序之外的学习分析（frontier 是本模块唯一的"教学语义"函数）。
- 不处理并发/线程安全；单线程使用假设。
- 含环图上除 `validate`（报告）与 `topological_order`（拒绝）外的行为不定义（I11），重生成实现无需额外保证。
