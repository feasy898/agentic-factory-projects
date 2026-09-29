# multitenant 模块规格（机构多租户）（冻结契约·定稿）

> 本文档是 BACKLOG P2「机构多租户：server 加 org 维度数据隔离（org_id 贯穿
> store/attempt/api）」的唯一权威契约。任何实现只要通过
> tests/contract/test_multitenant_contract.py 全部测试且满足本文全部条款，即为合格实现。
> 本规格对 server 面是**附加式**升级：不带 X-Org-Id 的请求必须与升级前逐字节同行为
> （全部落在缺省机构 `default`），既有端点响应形状、create_app 签名、既有契约/单元/
> 集成测试一律不变；server 面的 org 维度行为定义全部由本规格自包含给出，不依赖
> 任何其它规格文档。
>
> 本定稿根据对抗评审意见修订（相对 specs/drafts/multitenant.spec.md）：
> ① 消除"容器 org_id=None 归并还是 TypeError"的自相矛盾——错误表按参数维度拆分，
>    org 维度接受 None 归并、learner/kp 维度严格 str（新增 I12，修 §3.4/§3.5/§6）；
> ② 冻结 AttemptCounter 的服务端写入时机——选题即计数（bump-on-selection，
>    新增 I13，修 §3.6），并仲裁 POST /responses 不消耗配额；
> ③ 消除 org_ids()"值恒非空"歧义——列表本身可为空，仅指元素值非空串/纯空白
>    （修 I4）；
> ④ 仲裁失败写档（400/422）不留域——先校验后写档（新增 I14）；
> ⑤ 绑定 HTTP 只读端点到不建域读取路径（新增 I15）；
> ⑥ 给出有状态端点的闭式清单与判定规则（新增 I16）。

**证据标记**：
- 【契约】= `tests/contract/test_multitenant_contract.py` 明确断言的行为（行为 ground truth，下称"契约测试"）；
- 【参考】= 参考实现 `src/xuexing/multitenant.py`（内核）与 `src/xuexing/server.py`（HTTP 胶水）
  中可读出、且起草/评审时实际运行复核过的行为（API 发现）；
- 【运行复核】= 本轮在参考实现上实际执行探针得到的结果（下文按 P1–P12 编号引用，
  各处就地给出输入与观察输出；探针脚本为一次性验证，不入库）。
- **优先级规则**：两者冲突时以【契约】为准——但"冲突"仅在契约测试可构造、可观察的输入上有定义；
  对契约测试无法产生的输入/组合（如"404 读之后查 /orgs"、"作答后再选题的配额归属"、
  "失败写档之后查 /orgs"），按【参考】+【运行复核】冻结为权威行为，并在相应条款注明"测试未覆盖"。

## 1. 目的

给会话状态加机构命名空间：同一 learner_id 在不同机构（org_id）下是完全独立的
数据域。两类会话状态都按 (org_id, learner_id) 分域：

- **学习者会话存储**（OrgStore）：每 (org, learner) 一个 entry dict，起步形状恒为
  `{"responses": [], "history": []}`，随业务推进可携带 `"profile"`（画像对象）、
  `"administered"`（已出题 item_id 列表）等附加键；【契约】test_orgstore_isolates…:151
  （新档 `== {"responses": [], "history": []}`）、test_orgstore_profile_helpers:176；
  【参考】server.py:150-152（responses/profile 写入）、server.py:191/195（administered 惰性追加）。
- **每知识点选题计数**（AttemptCounter）：`{org: {learner_id: {kp_id: n}}}`。

org 维度经 HTTP 请求头 `X-Org-Id` 贯穿全部有状态端点（闭式清单见 §3.6/I16）。
内核只提供键派生与两个分域容器，不含任何领域算法；HTTP 穿线在 server.py
（薄胶水层）。org 只改变状态归属，绝不改变领域算法输出值。

## 2. 允许的依赖

- 内核 `xuexing/multitenant.py`：**仅 Python 标准库**（连 xuexing.types 都不需要）；
  零第三方、零文件/网络 IO、零时钟/随机。
- server.py（胶水侧）：fastapi/pydantic（既有）+ `from xuexing.multitenant import …`
  （绝对导入，满足注入装载约定）。
- **重生成装载约定**：重生成实例是单文件 `<impl_dir>/multitenant.py`，由测试根夹具以
  `spec_from_file_location` 装载并顶替 `sys.modules["xuexing.multitenant"]`
  （tests/conftest.py:13 的注入清单含 `"multitenant"`；tests/conftest.py:17-27），
  **不得使用包内相对导入**；必须暴露 §3.1–3.5 全部公开 API（HTTP 穿线 §3.6–3.7
  属薄胶水层，不在重生成范围——契约测试对 HTTP 层的断言由参考 server 叠加重生成
  内核满足）。
- 禁止：内核 import 任何其他 xuexing 模块；任何持久化、环境变量、全局可变状态
  （容器实例只能是 create_app 闭包内局部——server.py:127/129；每次 create_app
  得到全新空容器，故全新应用 `GET /orgs` 必为 `{"orgs": []}`，
  【契约】test_orgs…:401）。

## 3. 公开 API

### 3.1 `DEFAULT_ORG_ID: str`

缺省机构 id，值恒为字符串 `"default"`。【参考】multitenant.py:28；【契约】test_resolve_org_merges_defaults:107。

### 3.2 `resolve_org(org_id: str | None) -> str`

缺省机构归并，全函数：

- `None` / `""` / 纯空白（去首尾空白后为空串）→ 返回 `DEFAULT_ORG_ID`；
  【契约】test_resolve_org_merges_defaults:107-110（含 `" default "` 归并——先去空白、
  恰等于缺省值）。
- 其余 str：**去首尾空白后原样返回**（不做大小写折叠、不做 Unicode 规范化：
  `" a "` → `"a"`；`"A"` 与 `"a"` 是两个机构；`"a:b"`、`"机构-01"` 原样保留）。
  【契约】test_resolve_org_verbatim_and_case_sensitive:114-118。
- 非 str 且非 None（int/bytes/list/object/**bool 亦然**）→ `TypeError`。
  【契约】test_resolve_org_rejects_non_str:121-124（参数化 123/`["a"]`/`b"org"`/object，
  None 不在拒绝列表）；【运行复核】P10：`resolve_org(True)`、`resolve_org(0)`、
  `resolve_org(b"x")` 均 TypeError（`bool` 不是 str 的实例）。
- 对任意 `str | None` 输入不抛 TypeError 以外的任何异常。

### 3.3 `org_key(org_id: str, learner_id: str) -> str`

(org_id, learner_id) 的**单射复合键**，确定性纯函数（同输入恒同输出）。

- **单射**：任意不同的 (org, learner) 对给出不同键；分隔符歧义对不碰撞——
  org 含冒号等字符时 `org_key("a:x", "y") != org_key("a", "x:y")`；空串参数合法。
  【契约】test_org_key_injective_and_deterministic:129-135（八对两两不同，含
  `("", "abc")`/`("abc", "")`）。
- **具体格式（冻结，参考行为；契约只察单射/确定性/类型门）**：返回串 = org_id 的
  十进制字符长度 + `":"` + org_id + learner_id（后两段直接相连、无额外分隔）。
  【运行复核】P7：`org_key("a:x","y") == "3:a:xy"`、`org_key("a","x:y") == "1:ax:y"`、
  `org_key("","abc") == "0:abc"`、`org_key("abc","") == "3:abc"`；【参考】multitenant.py:44-53。
  长度前缀使拆分无歧义，故上述单射对任意输入成立。
- 两参数**均严格 str**：任一为 None 或其它非 str → `TypeError`（无缺省归并——
  本函数不做归并，归并只发生在 §3.2 与容器入口）。
  【契约】test_org_key_rejects_non_str:138-141（`(None,"a")`、`("a",None)`、`(1,"a")`、`("a",2.5)`）。

### 3.4 `class OrgStore`

org 分域的学习者会话存储 `{org: {learner_id: entry}}`。**容器公共入口**：每个方法
先对 org 参数执行 §3.2 归并（容器强制，调用方不会因忘记归并而串域），再对 learner_id
做严格类型门；org 门先于 learner 门。【参考】multitenant.py:56-61；
【运行复核】P9：`entry(1, None)` 报的是 org 侧 TypeError（契约测试不区分异常消息，
仅要求 TypeError 类型）。

方法（org 参数类型一律 `str | None`；learner_id 严格 `str`）：

- `get(org_id, learner_id) -> dict | None`：该 (org, learner) 的 entry；不存在返回
  None，**不建域**（不产生任何中间机构/学习者档）。【契约】test:156-158
  （`get("org-c", "L") is None` 且随后无域产生）；【参考】multitenant.py:75-78。
- `entry(org_id, learner_id) -> dict`：get-or-create；缺失则先建
  `{"responses": [], "history": []}`；同一对重复调用返回**同一 dict**（状态延续）。
  【契约】test:148-151（新档形状）、test:161-166（`entry("o","L") is e1`）。
- `set_profile(org_id, learner_id, profile) -> None`：在（必要时经 entry 新建的）
  entry 上写 profile。【契约】test:174-176；【参考】multitenant.py:89-91。
- `has_profile(org_id, learner_id) -> bool`：entry 存在**且**含 `"profile"` 键。
  未建档 → False；建档无画像 → False；画像不跨 org。【契约】test:169-177。
- `learner_ids(org_id) -> list[str]`：该机构下已知学习者 id，**升序**去重；
  机构无档 → `[]`。经 review/trace 等成功路径建档的学习者即使无 profile 也计入。
  org 参数同样走归并（`learner_ids(None)` 即缺省机构的学习者）。
  【契约】test:198/203/208-210/216；【运行复核】P8：`learner_ids(None)` 返回缺省域
  学习者、`learner_ids(3)` TypeError；【参考】multitenant.py:98-102。
- `org_ids() -> list[str]`：出现过的机构 id，**升序**去重。**列表本身可为空**：
  全新 store → `[]`（test:203）。"值恒非空"仅指**元素值**——归并语义（§3.2）保证
  永不出现空串/纯空白 org id，而非列表恒非空。【契约】test:201-210（空 → 建档 →
  `["o1","o2"]`）、test:188（归并后只剩 `[DEFAULT_ORG_ID, "o"]`）；【参考】multitenant.py:104-106。

**隔离条款**：同 learner_id 不同 org 的 entry 是不同对象，一方任何键的变更在另一方
不可见；`"A"` 与 `"a"` 是不同域；缺省归并同域：`entry(None, L) is entry("default", L)`、
`entry("", L) is entry("default", L)`、`entry(" o ", L) is entry("o", L)`。
**类型门不对称（I12，评审修复①）**：org 参数接受 None（归并，不报错），非 str 且
非 None → TypeError；learner_id 为 None 或任何非 str → TypeError。
【契约】test:182-188（org 维度 None/空白归并）、test:211-216（`get(1,"L")`、
`entry("o",None)`、`learner_ids(3)` 均 TypeError）、test:178（`set_profile(1,…)`）。

### 3.5 `class AttemptCounter`

org 分域的每知识点计数 `{org: {learner_id: {kp_id: n}}}`。所有方法先经 §3.2 归并
（入口类型门与 §3.4 同构：org 门先于 learner 门）。方法（org 参数 `str | None`；
learner_id、kp_id 严格 `str`）：

- `counts(org_id, learner_id) -> dict[str, int]`：get-or-create，返回**活字典**
  （调用方可直接读；server 侧把它整体交给只读选题器消费）。同一对重复调用返回同一
  dict。【契约】test:230-231、test:234-238（`counts(None,"L") is counts("default","L")`、
  `counts(" c ","L") is counts("c","L")`）；【参考】multitenant.py:119-122。
- `bump(org_id, learner_id, kp_id) -> int`：计数 +1 并返回**新值**（首计为 1）。
  【契约】test:222-227。
- `get(org_id, learner_id, kp_id) -> int`：只读单值，未计过 → 0。【契约】test:228-229。

**隔离条款**：同 learner 不同 org、同 org 不同 learner、同对不同 kp 的计数互不影响；
缺省归并同 §3.4（`bump(None, L, kp)` 落在缺省域）。【契约】test:221-231、test:238-239。
**类型门不对称（I12）**：org 维度 None 归并；learner_id/kp_id 为 None 或任何非 str →
TypeError。【契约】test:242-250（`counts(1,"a")`、`counts("a",None)`、`bump("a","L",7)`、
`get("a","L",None)` 均 TypeError）；【运行复核】P8：`bump(None,"L","kp")` 正常返回 1。
【参考】multitenant.py:124-136。

### 3.6 HTTP 穿线（server.py，薄胶水层）

**容器持有**：store 与 attempt 计数都是 create_app 闭包内局部、每应用全新
（server.py:127/129；【契约】test:401 初始 `{"orgs": []}`）。

#### 3.6.1 有状态端点闭式清单（I16，评审修复⑥）

server 全部路由为以下 14 条（【参考】server.py 路由表逐条核实：131、141、156、172、
182、200、211、219、229、256、275、303、327、340 行），**按是否读写分域容器三分**：

| 端点 | 分类 | 状态触及 |
|---|---|---|
| `POST /learners/{id}/responses` | 有状态 | entry（responses+profile） |
| `GET /learners/{id}/profile` | 有状态（只读） | entry 读 |
| `GET /learners/{id}/plan` | 有状态（只读） | entry 读 |
| `GET /learners/{id}/next_item` | 有状态 | entry 读 + administered 写 + attempt 计数 |
| `POST /learners/{id}/reviews` | 有状态 | entry（history） |
| `POST /trace` | 有状态 | 仅 learner_id 非空且成功时写 profile |
| `POST /recommend` | 有状态（学习者模式只读） | 仅 kp 模式以外的画像读取 |
| `GET /orgs` | 只读枚举（§3.7） | store 读 |
| `POST /papers/diagnostic`、`POST /attribute`、`POST /blueprint`、`POST /grade`、`POST /itembank/v2/validate`、`POST /coverage/standard` | 无状态 | 无 |

**仲裁规则**：上表 7 个"有状态"端点是本规格冻结时点 server 的**完备闭式清单**
（对照参考实现路由表核实，无一遗漏、无一多列）；实现必须给且仅给这 7 个穿线。
判定规则（对任何改动/扩展同样适用）：**凡读写 OrgStore/AttemptCounter 的端点一律
按本节穿线 org；不触及两者的端点一律不新增 org 参数**（收到 X-Org-Id 也只是忽略，
不报错，行为不变——【契约】test_stateless_endpoints_ignore_org_header:269-274）。
"按列举"与"按全部有状态"两种字面在此合并为同一清单，不再有解释空间。

#### 3.6.2 X-Org-Id 头语义

- 上述 7 个有状态端点新增**可选**请求头 `X-Org-Id`：端点内一律
  `org = resolve_org(header)`（§3.2）后把 org 传给 OrgStore / AttemptCounter。
  不带头 ≡ `""` ≡ 纯空白 ≡ `"default"`（同域）；因此既有不发头的测试行为与升级前
  逐字节一致。【契约】test_default_org_equivalence:255-266。
- 头值是自由 ASCII 字符串：任意可编码值（含冒号等标点、空格）都被容忍解析，
  **不因头值产生 400/500**。【契约】test_org_header_tolerates_arbitrary_values:427-432
  （`"a:b"` 自成命名空间）、test:361-368（大小写敏感）。
  **范围限定（评审核实）**：非 ASCII 头值无法经 HTTP 传输层编码（【运行复核】P12：
  TestClient 对 `X-Org-Id: 机构-01` 在客户端编码即抛 `UnicodeEncodeError`，请求未达
  应用），不属应用层契约；非 ASCII org id 属内核层行为（§3.2 原样保留，
  契约 test:118 经容器直调覆盖）。
- org 头绝不改变领域算法输出，只改变状态归属（I11）；不进入任何既有端点响应体
  （响应形状不变）。
- `GET /orgs` 自身**不**接收 X-Org-Id（附带时忽略）。【运行复核】P11。

#### 3.6.3 写档与计数时机（I13/I14，评审修复②④）

**先校验后写档（I14）**：一切写端点先完成全部校验与领域计算，全部通过后才首次
调用任何建域方法（OrgStore.entry / set_profile）。校验失败（400/404/422）的请求
**不在任何 (org, learner) 上留下 entry、不产生 org 域**——随后 `GET /orgs` 不可见
该 org。具体顺序（【参考】server.py）：`/reviews` 的 rating∉{0,1,2,3} 检查先于
entry（server.py:203-206）；`/trace` 的事件非法/无快照 400 先于 set_profile
（server.py:234-244）；请求体形态违规由 pydantic 映射 422，先于一切。
【契约】test:276-279（两种 400 的状态码）；"失败不留域"经 /orgs 观察，契约测试未
组合该序列，按【参考】+【运行复核】P2 冻结（rating 9 → 400、空 events → 400、
缺 rating → 422 之后 `/orgs` 仍为 `{"orgs": []}`）。

**选题即计数（I13，bump-on-selection）**：`GET /learners/{id}/next_item` 的写入
时机固定为——

1. 404 判定（无档/无画像）先于一切写（I15）；
2. 取该 (org, learner) 的 counts 活字典（get-or-create）与 entry 的 administered
   列表，连同画像、scope、per_kp_cap 交给只读选题器；
3. **成功选出**（返回具体 item_id）时，于返回响应前同步写两笔：
   a. item_id 追加进该 entry 的 `administered` 尾部；
   b. 对该题的**主知识点**（题库中该题的第一知识点）`attempt_counts.bump(org,
      learner, 主知识点)` +1。
   【参考】server.py:190-197。
4. **耗尽**（选题器返回空 → 响应体 `{"item_id": null, "reason": "exhausted"}`、
   HTTP 200）与 404 路径：**零写入**——不 bump、不追加 administered、不建域。

**推论（即契约场景）**：零作答、仅连续 `GET …/next_item`（per_kp_cap=2）时，第 1、
2 次各消耗 1 点配额（每次选题即时 bump），第 3 次即 exhausted，第 4 次仍 exhausted；
另一 org 从满额开始、首两题与前一 org 逐位相同（选题确定性）。【契约】
test_next_item_attempt_counts_isolated_per_org:373-395；【运行复核】P1b：选题序列
`["g_half","g_unit",None,None]`。

**各写端点的状态触及面（固定，不多不少）**：

- `POST /learners/{id}/responses`：仅写该 (org, learner) entry 的 responses 追加与
  profile 覆写；**不 bump 任何计数、不写 administered**——作答不消耗选题配额。
  【参考】server.py:141-154（函数体不触 attempt_counts）；【运行复核】P1：先作答后
  cap=1 选题，第 1 次仍选出、第 2 次才 exhausted（若作答即计数则第 1 次即耗尽，
  与参考行为矛盾）。测试未直接组合"作答+跨 org 选题配额"，按参考冻结。
- `POST /trace`：仅当 learner_id 非空**且**追踪成功（有快照）时 set_profile 建档；
  learner_id 缺省（空串）→ 零写档（`profile_saved=false`，响应形状不变）；
  不触碰 attempt 计数与 administered。【参考】server.py:239-244；
  【运行复核】P4（空 learner_id → 200/false/`/orgs` 空）、P5（trace 建档后配额满额，
  首次选题不被预扣）。
- `POST /learners/{id}/reviews`：rating 校验通过后 append rating 至 history（建档、
  无画像也计入 /orgs 枚举）。【契约】test:412-413；【参考】server.py:206-207。
- 无任何端点提供删除/迁移/合并（§7）。

#### 3.6.4 只读路径不建域（I15，评审修复⑤）

`GET /learners/{id}/profile`、`GET /learners/{id}/plan`、`GET /learners/{id}/next_item`
与 `POST /recommend`（学习者模式）对画像的探测**一律走不建域的只读读取**
（OrgStore.get 语义：缺 → None）：404 判定（无 entry 或 entry 无 profile →
404 `"learner not found"`）**先于任何 get-or-create 调用**（entry/counts/set_profile
不得在 404 路径执行）。因此对未建档 (org, learner) 的 404 读取**不创建任何 org 域
或学习者档**，随后 `GET /orgs` 不可见。【参考】server.py:160-162、176-178、186-190、
311-313；【运行复核】P3：全新应用对同一 org-ghost 四个读端点全 404 后 `/orgs` 仍为
`{"orgs": []}`（该序列契约未组合，按参考冻结）。

### 3.7 `GET /orgs` —— 机构命名空间枚举（只读，无头端点）

- 200 响应体：`{"orgs": [{"org_id": str, "learner_ids": [str...]}...]}`；org 按
  `org_ids()`（升序）外循环，learner 按 `learner_ids(org)`（升序）内层，如实反映
  store 实况（含 review 建档的无画像学习者）。【契约】test:400-421（期望体含
  default/org-a/org-b 三域、各域升序）。
- 初始（全新应用）恒为 `{"orgs": []}`。【契约】test:401。
- 无副作用：重复请求响应体**逐字节相等**。【契约】test:421-422；`/trace` 同理
  （同 org 同 body 逐字节相等，test:353-358）。
- 不接收 X-Org-Id（附带忽略，P11）；响应不受任何请求头 org 值影响。

## 4. 不变量（全部可被契约测试或上述复核检验）

- I1 **复合键单射**：org_key 对任意不同 (org, learner) 对给出不同键，分隔符歧义对
  （org 含 `:` 等）不碰撞，空串参数合法；同输入恒同输出；具体键格式按 §3.3 冻结
  （十进制长度前缀 + `":"` + org + learner）。【契约:129-135 + 参考 multitenant.py:44-53
  + 运行复核 P7】
- I2 **缺省归并**：resolve_org(None/`""`/纯空白) → DEFAULT_ORG_ID；`" default "` 归并
  等价显式 default；其余去首尾空白原样返回，大小写敏感、非 ASCII 原样保留；
  非 str 且非 None（含 bool）→ TypeError。容器各方法的 org 参数经同一归并。
  【契约:106-118 + 参考 multitenant.py:31-41 + 运行复核 P10】
- I3 **store 隔离**：同 learner_id 不同 org 的 entry 互为独立对象，变更互不可见；
  同对重复 entry() 返回同一 dict（状态延续）；`"A"`/`"a"` 分域；None/`""`/空白与
  default 归并同域；`get` 未档 → None 且不建域。【契约:146-166, 182-188, 191-198】
- I4 **store 枚举确定性**：learner_ids/org_ids 恒升序去重；未知 org → `[]`；
  **org_ids() 列表本身可为空**（全新 store → `[]`），元素值恒非空串/纯空白
  （评审修复③：删除"列表恒非空"的误读）。
  【契约:201-210（含 :203 空列表）+ 参考 multitenant.py:98-106】
- I5 **attempt 隔离**：bump/counts/get 按 (org, learner) 分域、按 kp 分键累加互不影响；
  bump 返回新值、首计 1；get 未计过 → 0；counts 返回活字典、同对同 dict；缺省归并
  同 I3。【契约:221-239】
- I6 **HTTP 缺省等价**：不带 X-Org-Id 的全部既有端点行为与升级前逐字节一致（既有
  test_server_contract / tests/unit/test_server.py 不改一字全绿为证）；`""` 头 ≡ 无头
  ≡ `"default"` 头。【契约:255-266】
- I7 **HTTP org 隔离**：org A 下建档/存画像/复习的学习者，在 org B、default 与无头下
  查 profile/plan/next_item/recommend 学习者模式一律 404；org A 下查 200；同
  learner_id 双 org 可持有互不串扰的独立画像（不同作答 → 不同 mastery，事后互不漂移）。
  【契约:284-358, 361-368】
- I8 **HTTP attempt 隔离**：同 learner 双 org 各自独立的 administered 与每 KP 计数
  ——org A 耗尽 per_kp_cap 后 org B 仍从满额开始，且两 org 相同画像状态下的首次
  选题结果相同（选题确定性，跨域不受对方消耗影响）；org A 耗尽后不因 org B 的消耗
  "复活"。【契约:373-395】
- I9 **/orgs 只读枚举**：初始 `{"orgs": []}`；org 升序、learner 升序、如实反映
  （review 建档的无画像学习者计入对应 org）；重复请求逐字节相等、无副作用。
  【契约:400-422】
- I10 **org 头全容忍（限定域）**：HTTP 层对**任意 ASCII 可编码**头值不因头值产生
  400/500（含空、空白、标点如 `"a:b"`）；无状态端点忽略该头照常 200，既有错误映射
  （400/404/422）不因该头改变。非 ASCII 头值在传输层编码即失败（P12），不属应用
  契约；非 ASCII org id 属内核层契约（I2）。【契约:269-279, 427-432 + 运行复核 P12】
- I11 **内核等价不破坏**：org 只改状态归属，不改任何领域值——同输入事件在任意 org
  下 /trace 快照与直接调用 kt.trace 逐字段相等（mastery/evidence 不因 org 改变）；
  /profile、/recommend 与内核直调结果逐字段对拍一致。【契约:255-266, 284-314,
  317-331】
- I12 **类型门不对称**（评审修复①）：org 维度参数（resolve_org、容器全部方法的
  org 位、learner_ids）类型为 `str | None`——None/`""`/纯空白归并 DEFAULT_ORG_ID、
  不报错，非 str 且非 None → TypeError；learner_id 维度（OrgStore、AttemptCounter、
  org_key）与 kp_id 维度（AttemptCounter.bump/get）严格 `str`——None 或任何非 str
  → TypeError。容器内 org 门先于 learner 门（契约只察 TypeError 类型，不察消息与
  顺序）。【契约:182-188, 211-216, 234-250 + 参考 multitenant.py:56-61 + 运行复核
  P8/P9】
- I13 **选题即计数（bump-on-selection）**（评审修复②）：next_item 的配额消耗只发生
  在"成功选出"时——administered 追加与主知识点 bump 同步于返回前；exhausted 与
  404 零写入；`POST /responses` 不 bump、不写 administered（作答不消耗配额）；
  `POST /trace` 不触碰计数。因此"零作答连续选题"必在第 per_kp_cap+1 次耗尽。
  【契约:373-395 + 参考 server.py:182-198 + 运行复核 P1/P1b/P4/P5】
- I14 **先校验后写档（失败不留域）**（评审修复④）：一切写端点校验/领域计算先行，
  400/404/422 请求不在任何 (org, learner) 留 entry、不产生 org 域（/orgs 不可见）；
  成功路径（含无画像建档的 review）才建域。【契约:276-279（失败状态码）+ 参考
  server.py:203-206, 234-244 + 运行复核 P2】
- I15 **只读路径不建域**（评审修复⑤）：GET profile/plan/next_item 与 POST /recommend
  学习者模式只走不建域读取；404 判定先于任何 get-or-create；404 读取不在 /orgs
  留痕。【参考 server.py:160-178, 186-190, 311-313 + 运行复核 P3】
- I16 **有状态端点闭式清单**（评审修复⑥）：穿线 X-Org-Id 的端点恰为 §3.6.1 表列 7
  个（对照参考实现全部 14 条路由核实）；判定规则"触容器必穿线、不触必忽略"对扩展
  同样适用；GET /orgs 为无头只读枚举。【参考 server.py 路由表 + 契约:269-274 +
  运行复核 P11】

## 5. 确定性与随机性

- 内核全部函数/方法同输入同输出；无时钟、无随机、无 seed；枚举一律升序。
- HTTP 侧 org 头只影响存取路径选择，不引入任何新随机/时间源；既有豁免时间戳字段
  （画像 updated_at、plan.created_at）不在此列、不受 org 影响（org 不改变领域值，
  I11）。
- `/trace` 在同 (org, body) 下、`/orgs` 在同 (依赖, store 状态) 下重复请求逐字节相等。
  【契约:353-358, 421-422】
- 禁止：容器实现依赖 dict 插入顺序输出枚举（一律 sorted）、隐藏随机、全局可变状态。

## 6. 错误行为

| 输入 / 情形 | 结果 |
|---|---|
| org 维度参数（resolve_org、容器各方法 org 位、learner_ids）为 None / `""` / 纯空白 | 归并 `DEFAULT_ORG_ID`，不报错（I2/I12） |
| org 维度参数为非 str 且非 None（int/bytes/list/object/bool） | `TypeError`（I2/I12） |
| learner_id（OrgStore 全部方法、AttemptCounter 全部方法、org_key）为 None 或非 str | `TypeError`（I12） |
| kp_id（AttemptCounter.bump/get）为 None 或非 str | `TypeError`（I12） |
| 同一调用多个维度同时非法（如 `entry(1, None)`） | `TypeError`；org 门先查（【参考】multitenant.py:56-61 + 运行复核 P9；契约只察异常类型） |
| HTTP `X-Org-Id` 为任意 ASCII 可编码值 | 容忍解析，不因头值 400/500（I10） |
| HTTP `X-Org-Id` 为非 ASCII 值 | 传输层编码错误（P12），不属应用层契约 |
| 无状态端点带 `X-Org-Id` | 忽略，行为不变（I16/I10） |
| 有状态写端点校验失败（400/404/422） | 既有错误映射不变，且**不留域**（I14） |
| 只读端点未建档 (org, learner) | 404，且**不建域**（I15） |
| 其它既有错误映射（400/404/422） | 一律不变 |

## 7. 非目标

- 不做鉴权/令牌/org 注册 CRUD/配额限流；org_id 由调用方自担（不校验字符集、
  不设长度上限、不建 org 白名单）；
- 不做持久化与跨 org 数据迁移/合并；不提供删除 learner/org 的 API；
- org 不进入任何领域算法（不改变 diagnose/trace/选题/判分输出值，只改状态归属）；
- 不把 org_id 塞进既有端点响应体（响应形状不变，隔离只经状态可见性与 /orgs 观察）；
- 内核不做 HTTP 概念（不知道请求头）；server 不自造复合键逻辑（一律经内核容器）；
- 内核按标准确定性内核契约（stdlib-only）可重生成；server 穿线部分属薄胶水层，
  不在重生成范围（其行为由 §3.6–3.7 与契约测试的 HTTP 层断言约束）；
- per_kp_cap 的配额语义、选题排序与耗尽判定算法属 paper/选题器职责，本规格只冻结
  其在 server 侧的**写入时机**（I13）与 org 分域归属（I8）；
- 不保证并发/线程安全；单线程使用假设（契约测试均为单线程 TestClient 场景）。
