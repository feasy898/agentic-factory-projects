# xapi 模块规格（冻结契约）

> 本文档是唯一权威契约。任何实现（参考实现或重生成实例）只要通过 tests/contract/ 全部测试
> 且满足本文全部条款，即为合格实现。实现算法自由，行为不允许偏离。
>
> **版本**：定稿 v1（由 drafts 版经对抗评审修复而来，修复记录见附录 A）。
> 标注「〔测试裁定〕」的行为由 tests/contract/test_xapi_contract.py（33 项）直接断言；
> 标注「〔参考裁定〕」的行为契约测试未仲裁，按参考实现 `src/xuexing/xapi.py` 冻结并在
> 当地注明实测证据。本文自包含：不引用仓库内其他规格文档。
>
> 冻结基线：参考实现 + 契约测试全量实测于 2026-09-29，CPython 3.12.10 x64
> （`python -m pytest tests/contract/test_xapi_contract.py -q` → 33 passed）。
> 标准事实于同日实读 adlnet/xAPI-Spec `xAPI-Data.md` 核对：statement MUST 含
> actor/verb/object；id 为标准形式 UUID；Agent 恰一个反向功能标识符；
> verb.id / object(Activity).id 必为 IRI；duration 为 ISO 8601 时长（spec 例 `"PT1234S"`）；
> timestamp 为 ISO 8601 日期时间；提供方写 version 必为 `"1.0.0"`；extensions 键必为 IRI。

## 1. 目的

xapi 是**学习事件导出**（BACKLOG P2「xAPI 学习事件导出」）的确定性内核：把内核三类
学习事件——作答 `Response`、复习调度 `ReviewEntry`、学习计划步骤 `PlanStep`——映射为
xAPI 1.0.3 statement JSON（actor=学习者 Agent、verb、object=题目/知识点 Activity、
result 携带判分/调度/计划载荷），并提供**学习记录标准符合性校验器**
`validate_statement`（xAPI 数据 API 离线可检验 MUST 规则子集，返回违规清单），
供对接任意 LRS / 学习记录平台前的自检。

映射总表（冻结）：

| 事件 | 动词键 | verb IRI | object |
|---|---|---|---|
| `Response` | `answered` | `http://adlnet.gov/expapi/verbs/answered`（ADL 动词表） | `…/activity/items/<item_id>` |
| `ReviewEntry` | `review-scheduled` | `https://xuexing.example.com/xapi/verbs/review-scheduled`（自有扩展动词） | `…/activity/kps/<kp_id>` |
| `PlanStep` | `plan-assigned` | `https://xuexing.example.com/xapi/verbs/plan-assigned`（自有扩展动词） | `…/activity/kps/<kp_id>` |

全模块纯函数：无 IO、无随机、无时钟、不读环境。statement id 由 uuid5（固定命名空间 +
`learner|verb键|object键|sequence`）派生——确定性 UUID，不是随机豁免；`timestamp` 必须
由调用方传入（ISO 8601 字符串），不传则输出不含该字段。

## 2. 允许的依赖与参数表面

- Python 标准库（`math`、`re`、`uuid`、`datetime` 级别）
- 本模块**不需要** `xuexing.types`（鸭子类型参数表面，禁止 import 其他 xuexing 模块；
  契约测试用真实 `types.Response/ReviewEntry/PlanStep/LearningPlan` 喂入验证兼容性）
- 禁止：第三方库、文件/网络 IO、`random`、系统时钟、环境读取
- **不使用** `from __future__ import annotations`：模块以顶层模块名注入装载（如
  `_regen_xapi`），延迟求值注解在注入装载环境下无必要且引入名字解析风险（实测结论，
  全部重生成模块一律遵守）

鸭子类型参数表面（只按 `getattr` 读取以下属性，禁止 isinstance 具体类）：

- `response`：`item_id: str`、`correct: bool`、`learner_answer: str|None`、
  `response_ms: int|None`
- `entry`（ReviewEntry）：`kp_id: str`、`due: str`（ISO 日期）、`interval_days: int`、
  `ease: 数值`
- `step`（PlanStep）：`kp_id: str`、`strategy_id: str`、`rationale: str`、
  `target_mastery: 数值∈[0,1]`、`recommended_item_ids: list[str]`（缺省按 `[]`）
- `plan`（LearningPlan）：`learner_id: str`、`steps: list`、`reviews: list`

## 3. 公开 API

模块必须暴露以下名字（契约测试 `from xuexing.xapi import ...`）：
`XAPIError`、`XAPI_VERSION`、`ACTIVITY_PREFIX`、`ACTOR_HOME_PAGE`、`NAMESPACE_UUID`、
`EXTENSION_PREFIX`、`EXT_DUE`、`EXT_EASE`、`EXT_INTERVAL_DAYS`、`EXT_RATIONALE`、
`EXT_RECOMMENDED_ITEM_IDS`、`EXT_STRATEGY_ID`、`EXT_TARGET_MASTERY`、`VERB_ANSWERED`、
`VERB_REVIEW_SCHEDULED`、`VERB_PLAN_ASSIGNED`、`VERBS`、`SCORE_TOLERANCE`、`is_iri`、
`is_lang_tag`、`is_iso8601_duration`、`is_iso8601_datetime`、`is_uuid`、`duration_iso`、
`make_actor`、`make_verb`、`make_activity`、`statement_id`、`response_statement`、
`review_entry_statement`、`plan_step_statement`、`export_statements`、`plan_statements`、
`validate_statement`。

### 3.1 常量

```python
XAPI_VERSION    = "1.0.0"
ACTIVITY_PREFIX = "https://xuexing.example.com/xapi/activity/"
ACTOR_HOME_PAGE = "https://xuexing.example.com/learners/"
NAMESPACE_UUID  = "579bef2f-ca51-4a19-8b5d-ce167fe911fa"   # statement id 命名空间
EXTENSION_PREFIX = "https://xuexing.example.com/xapi/extensions/"
EXT_DUE   = EXTENSION_PREFIX + "due"
EXT_EASE  = EXTENSION_PREFIX + "ease"
EXT_INTERVAL_DAYS = EXTENSION_PREFIX + "interval-days"
EXT_RATIONALE = EXTENSION_PREFIX + "rationale"
EXT_RECOMMENDED_ITEM_IDS = EXTENSION_PREFIX + "recommended-item-ids"
EXT_STRATEGY_ID = EXTENSION_PREFIX + "strategy-id"
EXT_TARGET_MASTERY = EXTENSION_PREFIX + "target-mastery"
VERB_ANSWERED = "answered"
VERB_REVIEW_SCHEDULED = "review-scheduled"
VERB_PLAN_ASSIGNED = "plan-assigned"
SCORE_TOLERANCE = 1e-9
VERBS = {  # 冻结（键-> {id, display 语言映射}）
    "answered": {"id": "http://adlnet.gov/expapi/verbs/answered",
                 "display": {"zh-CN": "回答", "en-US": "answered"}},
    "review-scheduled": {"id": "https://xuexing.example.com/xapi/verbs/review-scheduled",
                         "display": {"zh-CN": "已安排复习", "en-US": "review-scheduled"}},
    "plan-assigned": {"id": "https://xuexing.example.com/xapi/verbs/plan-assigned",
                      "display": {"zh-CN": "已分配学习任务", "en-US": "plan-assigned"}},
}
```

`XAPIError`（ValueError 直接子类）是本模块唯一异常类型。

### 3.2 判定积木（validate_statement 的构件，独立导出、闭式）

- `is_iri(v)`：`v` 为 str 且非空，且开头匹配方案正则 `^[A-Za-z][A-Za-z0-9+.\-]*:`，
  且不存在字符 `c` 使 `c.isspace()` 为真或 `ord(c) < 0x20` 或 `ord(c) == 0x7F`
  （无空白、无控制字符；非 ASCII 字符不拒绝——IRI 非 URI）。
  实测〔测试裁定〕：`http://a/b`→True、`https://xuexing.example.com/xapi/activity/items/q1`→True；
  `answered`（无方案）→False、`""`→False、`http://a b`→False、`http://a\nb`→False、
  `42`/`None`→False。实测〔参考裁定，本会话探针〕：`http://a\x07b`、`http://a\x7fb`→False。
- `is_lang_tag(v)`：str 且匹配 `^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$`
  （RFC 5646 闭式子集：主子标签 1-8 字母，后续子标签 1-8 字母数字）。
  实测〔测试裁定〕：`zh-CN`、`en-US`、`e`→True；`"not a tag"`、`zh_CN`、`""`、
  `回答`、`42`→False。
- `is_iso8601_duration(v)`：str 且匹配下列显式正则（**冻结文法；小数分量仅允许出现在秒**）：

  ```
  \AP(?=(?:[0-9]|T[0-9]))(?:[0-9]+Y)?(?:[0-9]+M)?(?:[0-9]+D)?(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+(?:\.[0-9]+)?S)?)?\Z
  ```

  散文语义（辅助理解，与正则冲突时以正则为准）：大写 `P` 开头；日期分量 `[0-9]+Y`、
  `[0-9]+M`、`[0-9]+D` 各至多一次、固定顺序；其后可选 `T` 段，`T` 后必须至少跟一个
  数字分量（`P` 后为数字或 `T` 后为数字，二者居其一，故 `P`、`PT` 单独不合法）；
  `T` 段内 `[0-9]+H`、`[0-9]+M`、`[0-9]+S` 各至多一次、固定顺序；**只有 `S` 允许小数**
  （`[0-9]+(?:\.[0-9]+)?`，小数点后至少一位），其余分量纯整数；`M` 按位置消歧
  （日期段=月、`T` 段=分）；整串锚定、大小写敏感、禁空白与其余字符；非 str → False。
  实测〔测试裁定〕：`PT0S`、`PT45.2S`、`P1DT2H`、`PT1234S`→True；
  `PT`、`P`、`pt5s`、`5 seconds`、`PT1234 s`、`42`→False。
  实测〔参考裁定，本会话探针〕：`P1D`、`P0D`、`P1Y2M3D`、`PT1H30M`、`PT1M`、`P1M`、
  `PT0.000001S`→True；`P1DT`、`P1.5D`（小数越位）、`PT.5S`、`PT45,2S`、`P1D2D`、
  `P1DT2HT3S`、`PT1H1H`（分量重复）、`P1W`（周不是本子集分量）、`" PT1S"`、`"PT1S "`→False。
- `is_iso8601_datetime(v)`：str、含大写 `"T"`、`datetime.fromisoformat(v)` 可解析
  （ValueError → False）。
  实测〔测试裁定〕：`2026-09-29T12:17:00+00:00`→True、`2026-09-29T12:17`→True；
  `2026-09-29`（无 T）→False、`nope`、`""`、`42`、`None`→False。
  实测〔参考裁定，本会话探针〕：`2026-09-29t12:17`（小写 t）→False、
  `2026-09-29 12:17`（空格分隔）→False。
- `is_uuid(v)`：str 且匹配
  `^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`
  （标准 8-4-4-4-12 连字符形式，十六进制大小写均可）。
  实测〔测试裁定〕：`1ad1c8b8-5dad-5a3c-8ebb-e4a0baab4e57`→True；
  `abc`、无连字符 32 位 hex、`""`、`42`、`None`→False。
  实测〔参考裁定，本会话探针〕：大写 `1AD1C8B8-…`→True。

### 3.3 `duration_iso(ms) -> str`

毫秒 -> ISO 8601 时长，**整型运算闭式**（不走浮点）：`whole, rem = divmod(ms, 1000)`；
`rem == 0` → `"PT{whole}S"`；否则 frac = rem 的三位零填充十进制去尾部 `"0"` →
`"PT{whole}.{frac}S"`。守卫：`ms` 必须为 int（bool 拒绝）且 ≥ 0，否则 `XAPIError`。

实测〔测试裁定〕：`(0)->"PT0S" (1)->"PT0.001S" (500)->"PT0.5S" (999)->"PT0.999S"
(1000)->"PT1S" (1234)->"PT1.234S" (45200)->"PT45.2S" (60000)->"PT60S"
(7200000)->"PT7200S"`；`-1`、`True`、`1.5`、`"5"`、`None` → `XAPIError`。

### 3.4 `statement_id(learner_id, verb_key, object_key, sequence=0) -> str`

守卫（先于计算，违规 → `XAPIError`）：`learner_id`/`verb_key`/`object_key` 各过 §3.5
id 类守卫；`sequence` 为 int（bool 拒绝）且 ≥ 0。值为
`str(uuid.uuid5(uuid.UUID(NAMESPACE_UUID), learner_id + "|" + verb_key + "|"
+ object_key + "|" + str(sequence)))`。

实测〔测试裁定〕：`("stu-1","answered","items/q1",0)->"1ad1c8b8-5dad-5a3c-8ebb-e4a0baab4e57"`、
`("stu-1","review-scheduled","kps/kp7",1)->"b9c9beab-f031-5496-ac79-51bf2bfbb099"`、
`("stu-9","plan-assigned","kps/kp3",0)->"4dcf3f0e-e2bf-5cef-b8cb-839d61f9107e"`；
同输入恒同 id；learner/verb键/object键/sequence 任一不同则 id 不同；
`("", "answered","k",0)`、`("s","","k",0)`、`("s","answered","",0)`、
`("s","answered","k",-1)`、`("s","answered","k",True)`、`("s","answered","k",0.0)`、
`("s","answered","k",None)` 均 `XAPIError`。

### 3.5 `make_actor / make_verb / make_activity`

**id 类守卫**（本节与 §3.6 共用）：值必须为 str 且 `strip()` 后非空；违规 → `XAPIError`。
实测〔测试裁定〕：make_actor 对 `("", "   ", None, 5)` 抛 `XAPIError`；
make_activity 对 `("", "   ", None, 5, "has space", "tab\there")` 抛 `XAPIError`。

**object_key 附加守卫**（仅 make_activity 与三类产器的 object 构造）：在 id 类守卫之上，
`object_key` 还**不得含任何空白字符**（任一字符 `c.isspace()` 为真即失格）；违规 →
`XAPIError`。三类产器的 object 一律经 `make_activity("items/" + item_id)` 或
`make_activity("kps/" + kp_id)` 构造，故 `item_id`/`kp_id` **传递地不得含空白**
（含空白 → make_activity 拒绝 → `XAPIError`）。〔参考裁定〕含空白的 `item_id=" q1 "`、
`kp_id="kp 7"` 实测被拒（拒绝点是 make_activity 的空白扫描，非字段守卫）；
`strategy_id="s drill"`、`learner_id="stu 1"` 实测放行（二者只进扩展值/account.name，
不进 IRI）。

- `make_actor(learner_id)`：id 类守卫 → 返回
  `{"objectType": "Agent", "account": {"homePage": ACTOR_HOME_PAGE, "name": learner_id}}`
  （键序 objectType、account；account 键序 homePage、name；恰一个反向功能标识符）。
  **每次调用返回全新容器**：顶层 dict 与内层 account dict 均新建，任意两次调用的顶层与
  `["account"]` 互不 `is` 别名。〔测试裁定〕
- `make_verb(verb_key)`：`verb_key` ∉ VERBS → `XAPIError`；否则返回
  `{"id": VERBS[verb_key]["id"], "display": dict(VERBS[verb_key]["display"])}` ——
  恰两键，顶层与 display 均为新 dict（改动返回值不污染 VERBS 表）。〔测试裁定〕
- `make_activity(object_key)`：object_key 双重守卫 → 返回
  `{"objectType": "Activity", "id": ACTIVITY_PREFIX + object_key}`（原值拼接）。
  **每次调用返回新 dict**（两次调用 `is not`）。〔测试裁定〕

产出**一律原值透传，无 strip/去空格步骤**（附录 A/R7：草稿"是否去空格"分叉的裁定）。

### 3.6 三类事件 -> statement（键构造顺序冻结）

statement 顶层键构造顺序冻结：`id, actor, verb, object, result?, timestamp?, version`
（timestamp 仅当入参非 None；result 恒出现）。actor/verb/object 分别按 §3.5 构造；
id 按 §3.4（sequence 透传）；version 恒 `XAPI_VERSION`；timestamp **原文透传**。

`response_statement(response, learner_id, timestamp=None, sequence=0)`：
object_key = `"items/" + item_id`。result 键构造顺序冻结 `response?, duration?, score,
success`：

- `response`：仅 `learner_answer` 非 None 时出现，原文透传；
- `duration`：仅 `response_ms` 非 None 时出现，值 = `duration_iso(response_ms)`；
- `score = {"scaled": 1.0|0.0, "raw": 1|0, "min": 0, "max": 1}`（correct 映射；
  键序冻结；`scaled` 必为 float 型，`raw`/`min`/`max` 为 int 型）；
- `success = correct`（原 bool）。

实测全量闭式〔测试裁定〕（`Response(item_id="q1", correct=True, learner_answer="B",
response_ms=45200)`，learner `"stu-1"`，timestamp `"2026-09-29T12:17:00+00:00"`，
sequence 0）——statement 整体恰为：

```json
{"id": "1ad1c8b8-5dad-5a3c-8ebb-e4a0baab4e57",
 "actor": {"objectType": "Agent", "account": {"homePage": "https://xuexing.example.com/learners/", "name": "stu-1"}},
 "verb": {"id": "http://adlnet.gov/expapi/verbs/answered", "display": {"zh-CN": "回答", "en-US": "answered"}},
 "object": {"objectType": "Activity", "id": "https://xuexing.example.com/xapi/activity/items/q1"},
 "result": {"response": "B", "duration": "PT45.2S",
            "score": {"scaled": 1.0, "raw": 1, "min": 0, "max": 1}, "success": true},
 "timestamp": "2026-09-29T12:17:00+00:00", "version": "1.0.0"}
```

可选缺席分支〔测试裁定〕：`learner_answer=None, response_ms=None` 且不传 timestamp →
顶层恰 `[id, actor, verb, object, result, version]`、result 恰 `[score, success]`。
`correct=False` → `{"scaled": 0.0, "raw": 0, "min": 0, "max": 1}`、`success=False`
（scaled 为 float、raw 为 int）。timestamp 传 `"2026-09-29T08:00:00+08:00"` → 原文透传。

`review_entry_statement(entry, learner_id, timestamp=None, sequence=0)`：
object_key = `"kps/" + kp_id`；result 恒
`{"extensions": {EXT_DUE: due, EXT_EASE: float(ease), EXT_INTERVAL_DAYS: interval_days}}`
（扩展键插入序 = IRI 码点升序 due < ease < interval-days；`ease` 恒转 float——入参 int 3
产出 float `3.0`；`due`/`interval_days` 原值）。实测〔测试裁定〕：
`ReviewEntry("kp7","2026-10-02",3,2.5)` learner `"stu-1"` sequence 1 → id
`"b9c9beab-f031-5496-ac79-51bf2bfbb099"`、object `"…/activity/kps/kp7"`、extensions 恰为
`{"…/extensions/due": "2026-10-02", "…/extensions/ease": 2.5,
"…/extensions/interval-days": 3}`。

`plan_step_statement(step, learner_id, timestamp=None, sequence=0)`：
object_key = `"kps/" + kp_id`；result 恒
`{"extensions": {EXT_RATIONALE: rationale, EXT_RECOMMENDED_ITEM_IDS: list(recommended_item_ids),
EXT_STRATEGY_ID: strategy_id, EXT_TARGET_MASTERY: float(target_mastery)}}`
（插入序 = 码点升序 rationale < recommended-item-ids < strategy-id < target-mastery；
推荐列表为**新 list 拷贝**——改入参列表不影响已产 statement；`rationale` 空串原样入扩展；
`target_mastery` 恒转 float）。实测〔测试裁定〕：
`PlanStep("kp3","s-drill","先序薄弱",0.85,["i1","i2"])` learner `"stu-9"`
timestamp `"2026-09-29T08:00:00+08:00"` sequence 0 → id
`"4dcf3f0e-e2bf-5cef-b8cb-839d61f9107e"`、extensions 恰为
`{"…/rationale": "先序薄弱", "…/recommended-item-ids": ["i1","i2"],
"…/strategy-id": "s-drill", "…/target-mastery": 0.85}`。

**校验清单**（全部 `XAPIError`；任一失格都在任何构造/返回之前抛出；守卫的相互次序不作
承诺，因所有守卫失败均抛同一类型且测试只断言类型）：

- `learner_id` / `item_id` / `kp_id` / `strategy_id` / `recommended_item_ids` 元素：
  §3.5 id 类守卫（strip 后非空的 str）；〔测试裁定：`""`/`None`/`5` 均拒〕
- object_key：§3.5 双重守卫 —— 故 `item_id`/`kp_id` 不得含空白（传递性，见 §3.5）；
  〔参考裁定：`" q1 "`/`"kp 7"` 实测被拒〕
- `correct`：严格 bool（`isinstance(x, bool)`；`1`、`0`、`None` 拒绝）；〔测试裁定〕
- `learner_answer`：None 或 str；〔测试裁定：`5` 拒〕
- `response_ms`：None 或 int（bool 拒绝）且 ≥ 0；〔测试裁定：`-5`、`True`、`1.5` 拒〕
- `due`：str 且 `date.fromisoformat(due)` 可解析（实测 `"2026-10-02T05:00:00"` 在
  CPython 3.12 被 date.fromisoformat 拒绝 → `XAPIError`）；〔测试裁定〕
- `interval_days`：int（bool 拒绝）且 ≥ 0；〔测试裁定：`-1`、`True`、`None` 拒〕
- `ease`：int/float（bool 拒绝）且有限（nan/inf 拒）；〔测试裁定〕
- `target_mastery`：实数有限且 ∈ [0,1]（bool 拒绝）；〔测试裁定：`1.5`、`-0.1`、nan、
  `True`、`None` 拒〕
- `rationale`：str（空串合法；None/非 str 拒）；〔测试裁定〕
- `recommended_item_ids`：list/tuple（其他类型拒；属性缺省按 `[]`——实测无该属性的
  简单对象可导出），元素各过 id 类守卫（`""` 拒）；〔测试裁定〕
- `timestamp`：None 或 `is_iso8601_datetime` 为真；〔测试裁定：`"2026-09-29"`、`"nope"`、
  `""`、`42`、`True` 均拒；None 合法 = 不出 timestamp 键〕

### 3.7 `export_statements(records, learner_id, timestamp=None) -> list[dict]`

混合事件批量导出。`records` 必须 list/tuple，否则 `XAPIError`〔测试裁定：None、42、
`"records"`、dict、单个事件对象均拒〕；`learner_id` 过 id 类守卫。

逐元素鸭子分类，**"有"的判定冻结为 hasattr 语义（属性名存在性，与属性值无关）**：

1. `hasattr(record, "item_id")` 为真 → Response 型；
2. 否则 `hasattr(record, "strategy_id")` 为真 → PlanStep 型；
3. 否则 `hasattr(record, "due")` 为真 → ReviewEntry 型；
4. 三属性名全缺 → `XAPIError`，**消息必须含位置下标（0 起）的十进制表示**。

属性存在但值非法（如 `item_id=None`）落入对应类型产器，由 §3.6 字段守卫拒绝（`XAPIError`；
该路径的消息是否含位置下标不作承诺）。〔测试裁定〕：无任何属性的 `_Ghost` 在下标 1 处 →
消息含 `"1"`；〔参考裁定，本会话探针〕`item_id=None` 的对象被拒于字段守卫
（消息 `"response.item_id must be a non-empty str"`，无下标）。

statement 顺序 = 输入顺序；**sequence = 0 起的位置下标**进入 statement id。

### 3.8 `plan_statements(plan, timestamp=None) -> list[dict]`

`learner_id` 取 `plan.learner_id`（过 id 类守卫）；`plan.steps` 与 `plan.reviews` 各必须为
list/tuple（缺失、None 或其他类型 → `XAPIError`）。合并序列 = `list(steps) + list(reviews)`
（**steps 全部在前、reviews 在后，各自保持原序**）；对合并序列逐元素按 §3.7 **同一**
鸭子分类规则分类（不按来源列表强判类型）；sequence = 合并序列中 0 起的连续下标。
空合并序列 → 空列表（〔参考裁定〕）。

实测〔测试裁定〕：`LearningPlan("stu-9", steps=[PlanStep kp3], reviews=[ReviewEntry kp7])`
→ 2 条 statement，verb 依序 `[plan-assigned, review-scheduled]`，id 依次
`"4dcf3f0e-…"`、`"509234c9-6db9-59b5-b24f-a447ba29955b"`（本会话探针复核）；
steps=[kp3, kp4] + reviews=[kp7] → id 依次为 statement_id("stu-9","plan-assigned","kps/kp3",0)、
`…kp4,1`、`("stu-9","review-scheduled","kps/kp7",2)`。

### 3.9 `validate_statement(stmt) -> list[str]`

xAPI 1.0.3 数据 API「离线可检验 MUST 子集」符合性校验。返回违规字符串清单
（空列表 = 符合）。**对任何输入不抛异常。**

**总则（冻结）：**

- **A0 非 dict 输入**：返回**恰一条**违规，消息含子串 `"dict"`，随即终止（不做其他判定）。
  〔测试裁定：`42`、`"x"`、`None`、`[]`、`1.5` → len==1 且含 `"dict"`〕
- **判定顺序冻结：A0 → A1 actor → A2 verb → A3 object → A4 → A5 result → A6 context**；
  违规清单顺序 = 判定顺序（草稿"见实现注释"的引用废除，顺序以本节为准）。
- **发射粒度**：下文每标注一个"违规"处即产生恰一条违规字符串；多处失格按序各产生一条，
  不聚合、不去重。〔参考裁定，本会话探针：account 缺 homePage 且缺 name → 恰 2 条；
  Group 坏 account + 坏 member → 恰 3 条〕契约测试对清单的断言只有：`== []`、`!= []`、
  一处场景恰 1 条（见 A3 definition 例）、A0 的 `"dict"` 子串——除这些外消息文案不冻结，
  但每条违规必须是非空 str。
- **容器属性通则**（适用于 result、context、score、extensions、contextActivities、
  display、definition）：键不存在**或值恰为 None** → 跳过（0 条）；否则先判形态：非 dict →
  **恰一条**形态违规，且不再深入该属性。〔参考裁定，本会话探针：显式 `result=None`、
  `context=None`、`score=None` → 0 条；`score="score"`、`extensions=[1]` → 恰 1 条〕
  例外：A1–A3 的 actor/verb/object 与 A4 的三个标量**无 None 豁免**（探针：`actor=None`、
  `id=None`、`timestamp=None`（键存在）各 1 条违规）。
- **范围外属性**（authority/stored/attachments 等）一律不校验、不产生违规。

**【语言映射】**（共享判定，输入记 `v`）：`v` 为 None（或键不存在）→ 0 条；非 dict →
恰 1 条；dict → 按 dict 迭代序逐键：键非 `is_lang_tag` → 1 条；值非 str → 1 条
（键、值失格相互独立，可各罚一条）。〔测试裁定：坏键 `zh_CN` → 违规、`display="answered"`
（非 dict）→ 违规；〔参考裁定，本会话探针〕`display={"zh-CN": 42}` → 恰 1 条——
与契约测试自带独立复核（键过语言标签正则且值 isinstance str）同口径〕

**【Agent/Group 校验】**（共享判定，输入记 `agent`；violations 前缀区分 actor/object，
文案自由）：

- a. `objectType` 缺省按 `"Agent"`；值非 `"Agent"`/`"Group"` → 恰 1 条，**终止该 agent
  的其余检查**；〔测试裁定：`"Robot"` → 违规〕
- b. IFI 键集 = {`mbox`, `mbox_sha1sum`, `openid`, `account`} 与 agent 键集的交
  （按键名存在计，不看值）；|交| ≠ 1（0 个或 ≥2 个）→ 恰 1 条，终止该 agent；
  〔测试裁定：双 IFI、零 IFI 均违规〕
- c. 按 IFI 种类校验（account 的 homePage 与 name 相互独立）：
  - `mbox`：须 str 且以 `"mailto:"` 开头且 `is_iri`，否则 1 条；〔测试裁定：
    `"mailto:stu@example.com"` 合法〕
  - `mbox_sha1sum`：须 str 且匹配 `^[0-9a-fA-F]{40}$`，否则 1 条；
  - `openid`：须 `is_iri`，否则 1 条；
  - `account`：非 dict → 1 条；dict 则 homePage 非 `is_iri` → 1 条、name 非 str → 1 条。
    〔测试裁定：坏 homePage、缺 homePage 均违规〕
- d. `objectType == "Group"` 时 member 检查**独立于 c 的结果执行**：member 非 list
  或任一元素非 dict → 恰 1 条（member 元素**不递归**校验内容）。〔测试裁定：member 为
  Agent dict 列表 → 合法；`member="x"` → 违规；Group 无 member 键 → 违规〕

**逐类判定：**

- **A1 actor（必需）**：`actor` 非 dict（缺席、None、其他类型均算）→ 恰 1 条；否则按
  【Agent/Group 校验】。〔测试裁定：删 actor → 违规〕
- **A2 verb（必需）**：非 dict → 恰 1 条；dict：`id` 非 `is_iri` → 1 条；
  `display` 按【语言映射】。〔测试裁定：相对引用 `"answered"` → 违规〕
- **A3 object（必需）**：非 dict → 恰 1 条；dict 按 `objectType`（缺省 `"Activity"`）：
  - `"Activity"`：`id` 非 `is_iri` → 1 条；`definition` 按容器通则（非 dict → 恰 1 条）；
    dict 时对 `name`、`description` 各自（仅当键存在，按 name→description 序）按
    【语言映射】校验。〔测试裁定：相对 id `"items/q1"`、`id=None` → 违规；
    `definition.name` 合法 + `description` 键 `"zh_CN"` → **恰 1 条**〕
  - `"Agent"` / `"Group"`：按【Agent/Group 校验】。〔测试裁定：account 型 Agent object
    合法〕
  - `"StatementRef"`：`id` 非 `is_uuid` → 1 条。〔测试裁定：合法 UUID → 合法、`"abc"`
    → 违规〕
  - 其余任何 `objectType` 值 → 恰 1 条。〔测试裁定：`"SubStatement"` → 违规〕
- **A4 顶层标量**（三者相互独立；**无 None 豁免**）：
  - `"id"` 键存在且 `is_uuid` 失败 → 1 条；〔测试裁定：`"abc"` → 违规〕
  - `"timestamp"` 键存在且 `is_iso8601_datetime` 失败 → 1 条；〔测试裁定：
    `"2026-09-29"` → 违规〕
  - `"version"` 键存在且非（str 且匹配 `^1\.0\.[0-9]+$`）→ 1 条；**键缺席 → 0 条
    （放行）**。〔测试裁定：`"0.9.0"`、浮点 `1.0` → 违规；〔参考裁定，本会话探针〕
    删除 version 键 → `[]`、`"1.0.0rc1"`、`version=None` → 1 条。附录 A/R5：
    草稿对缺失 version 未定的裁定为放行，生产侧恒写 `"1.0.0"`〕
- **A5 result**：按容器通则（非 dict → 恰 1 条）。dict，按序：
  1. `success`、`completion`：各自键存在且值非 bool → 各 1 条（先 success 后 completion）；
     〔测试裁定：`success=1` → 违规〕
  2. `response`：键存在且非 str → 1 条；〔测试裁定：`response=7` → 违规〕
  3. `duration`：键存在且非 `is_iso8601_duration` → 1 条；〔测试裁定：
     `"5 seconds"` → 违规〕
  4. `score`：按容器通则（非 dict → **恰 1 条**，测试裁定 `"score"` → 违规）。dict，按序：
     i. 未知键（∉ {scaled, raw, min, max}）：每键 1 条（按 dict 迭代序）；
        〔测试裁定：多出 `"x"` → 违规〕
     ii. 已知四键按 scaled→raw→min→max（仅存在者）：值 bool / 非 (int,float) / 非有限
         → 各 1 条；合格者记入数值集；〔测试裁定：`scaled=True`、`scaled=nan` → 违规〕
     iii. scaled 在数值集且 ∉ [-1, 1] → 1 条；〔测试裁定：`1.5`、`-1.1` → 违规〕
     iv. min、max 均在数值集且 min > max → 1 条；〔测试裁定：`raw=1, min=5, max=1`
         → 违规〕
     v. raw、min、max 均在数值集且 raw ∉ [min, max] → 1 条；〔测试裁定：`raw=7` → 违规〕
     vi. 四值均在数值集且 max > min 且
         |scaled − (raw−min)/(max−min)| > SCORE_TOLERANCE → 1 条
         （**max == min 时不查一致性**）。〔测试裁定：`(0.5, 2, 0, 4)` 合法、
         全 0 score 合法、`(0.5, 1, 0, 1)` 不一致 → 违规〕
  5. `extensions`：按容器通则；dict → 每个非 `is_iri` 键 1 条（迭代序）。
     〔测试裁定：`{"interval": 3}` → 违规；`{EXT_INTERVAL_DAYS: 3}` → 合法；
     `extensions=[1]` → 违规〕
- **A6 context**：按容器通则（非 dict → 恰 1 条）。dict，按序：
  1. `extensions`：同 A5.5；
  2. `contextActivities`：按容器通则（非 dict → 恰 1 条）。dict → 逐项（迭代序）：
     键 ∉ {parent, grouping, category, other} → 1 条；值非 list 则视为单元素列表 `[值]`；
     每个元素非 dict 或其 `id` 非 `is_iri` → 每元素 1 条。
     〔测试裁定：键 `"xyz"` → 违规；`parent` dict + `grouping` 单元素 list → 合法；
     元素 id `"no-scheme"` → 违规〕

## 4. 不变量（编号列出，全部可被契约测试检验）

- I1 **常量冻结**：§3.1 全部常量取值如上；NAMESPACE_UUID 可被 `uuid.UUID` 解析且
  `is_uuid(NAMESPACE_UUID)` 为真；7 个 EXT_* IRI 均以 EXTENSION_PREFIX 开头且
  `is_iri` 为真；`XAPIError` 是 ValueError 子类；VERB_* 三键恰为 VERBS 的键集。
- I2 **动词表**：VERBS 恰三键、整表取值如 §3.1 字面；全部 id 为绝对 IRI、display 全部为
  合法语言映射（键过 is_lang_tag、值为 str）；`make_verb` 返回新拷贝（顶层与 display
  均新建，改动返回值不污染 VERBS 表）；未知键 → `XAPIError`。
- I3 **statement 骨架**：顶层键集恰为 {id, actor, verb, object, result, [timestamp],
  version}；键构造顺序如 §3.6（`list(stmt)` 逐位断言）；actor 恒为 account 型 Agent；
  verb.id/object.id 恒为绝对 IRI；version 恒 `"1.0.0"`；id 恒为 §3.4 的 uuid5 闭式；
  timestamp 键当且仅当入参非 None（原文透传）。
- I4 **Response 映射**：result 键序与 §3.6 冻结规则逐字一致（可选字段缺席规则、
  score/success 的 correct 映射与类型、duration 闭式）；object = `…/items/<item_id>`。
- I5 **ReviewEntry/PlanStep 映射**：extensions 键集与值、插入序如 §3.6；ease 与
  target_mastery 恒转 float；推荐题列表为拷贝（改入参列表不影响已产 statement）；
  object = `…/kps/<kp_id>`。
- I6 **批量导出**：export_statements 顺序保持、sequence=位置；plan_statements
  steps 在前 reviews 在后、sequence 连续；分类按 hasattr 语义（§3.7）；不可分类元素按
  位置报 `XAPIError`（消息含位置下标十进制）；records/steps/reviews 容器失格 →
  `XAPIError`。
- I7 **标准符合性（产出侧）**：三类产器与两个批量导出对**一切通过 §3.5/§3.6 守卫的输入**
  （含/不含 timestamp、全部枚举分支）产出 `validate_statement(stmt) == []` 的 statement；
  且契约测试另以独立正则/解析复核（不信模块自身的判定积木），全量 JSON 可序列化
  （含中文 display）。〔全称成立的依据：object.id 经 §3.5 无空白守卫恒为 IRI，见附录 A/R7〕
- I8 **标准符合性（校验器负向）**：§3.9 各〔测试裁定〕负向例的每个变异至少命中一条违规
  （缺 actor/verb/object、双 IFI、零 IFI、坏/缺 homePage、member 非 list、非法 actor
  objectType、相对 verb.id、坏 display 键与非 dict display、相对/None object.id、
  非法 object objectType、非 UUID id、date-only timestamp、version `"0.9.0"` 与浮点
  `1.0`、非 bool success、response 非 str、非法 duration、score 非 dict、scaled 越界、
  score 未知键、bool/nan scaled、min>max、raw 越界、scaled 不一致、非 IRI 扩展键、
  extensions 非 dict、context.extensions 坏键、非法 contextActivities 键、contextActivities
  元素 id 无方案、非 dict 输入）。
- I9 **纯函数性**：不改入参（`vars()` 快照比对）；输出全部为新构造容器（含 make_actor
  内层 account、make_verb display、推荐题列表拷贝）；同输入同输出
  （`json.dumps(..., ensure_ascii=False, sort_keys=True)` 逐位一致）且全量 JSON
  round-trip 等值。
- I10 **无隐藏随机/时钟**：statement id 由 uuid5 冻结命名空间派生；timestamp 只来自
  入参（None -> 输出无该键）；同输入两次调用产出的 id 相同；任一部分不同则 id 不同。

## 5. 确定性与随机性

- 全部函数纯函数：输出只依赖入参值；禁止 `random`、系统时钟、环境读取、任何 IO。
- statement id = `uuid5(NAMESPACE_UUID, "learner|verb键|object键|sequence")`——
  uuid5 是 SHA-1 名字派生，属确定性运算，不是随机豁免。
- 扩展 dict 插入序冻结（§3.6）；`json.dumps(doc, ensure_ascii=False, sort_keys=True)`
  逐位可复现。
- 本模块**没有** seed/时间戳豁免：timestamp 由调用方显式传入，不传即不出。

## 6. 错误行为

`XAPIError`（ValueError 直接子类）是本模块唯一异常类型；所有产器在构造前完成校验
（§3.6 校验清单；守卫相互次序不作承诺）。`validate_statement` **不抛异常**：对任何
Python 对象输入返回违规清单（非 dict → A0 单条；其余全部以清单返回；域外情形如 dict
子类覆写 `get` 抛错不作承诺）。批量导出的分类失败（三属性名全缺）消息必须含位置下标。

必须容忍并跳过的输入（合法，不抛异常）：`rationale` 空串（原样入扩展）、
`learner_answer=None`/`response_ms=None`（result 相应键缺席）、`timestamp=None`
（顶层无 timestamp 键）、`recommended_item_ids` 属性缺省（按 `[]`）、
`ease`/`target_mastery` 为 int（产出转 float）。

## 7. 非目标

- **不接 LRS、不做网络发送**：输出止于 statement JSON 列表；HTTP/认证/批量提交属渠道层。
- **不维护已发送状态、不做去重账本**：statement id 确定性带来同批幂等，但跨会话
  去重/续传不是本模块职责。
- **不完整实现 xAPI 规范**：`validate_statement` 只覆盖离线可检验 MUST 子集
  （§3.9 范围）；LRS 侧行为（authority/stored 填写、voiding、attachments、
  Agent Group member 递归校验、未来时间戳检查）不在范围。
- **不生成 Activity definition 元数据**：不读题干/知识点名（避免引入 itembank/kpgraph
  依赖）；object 只含 id 与 objectType。
- **不做中文/英文文本回退策略**：display 恒按 §3.1 双语冻结。
- **不改冻结模块**：types/grading/scheduler/route 等一律不动；鸭子类型表面仅约定
  属性读取。

## 附录 A：对抗评审修复记录

以下为 drafts 版 → 本定稿的全部修复，每条含本会话实跑证据（2026-09-29，CPython
3.12.10）。证据命令：`python -m pytest tests/contract/test_xapi_contract.py -q`
（→ 33 passed）；探针脚本 `_probe_xapi_frozen.py` 与一段 `python -c` 直查
（脚本为一次性验证工件，验证后已删除）。

| # | 严重度 | 评审问题 | 修复 | 证据（本会话实跑） |
| --- | --- | --- | --- | --- |
| R1 | major | `is_iso8601_duration` 闭式文法未提小数分量，字面纯整数实现挂 `PT45.2S`→True（tests:252，并经 duration_iso 产出 + I7 传递要求）；小数允许在哪个分量未定 | §3.2 写成**显式冻结正则**：小数仅允许在 `S` 分量（`[0-9]+(?:\.[0-9]+)?S`），其余分量纯整数；`P`/`PT` 单独不合法（P 后为数字或 T 后为数字）；附实测清单（含小数越位/分量重复/大小写/空白拒绝例） | 探针：`PT45.2S`→True、`PT0.000001S`→True；`P1.5D`、`PT.5S`、`PT45,2S`、`P1D2D`、`P1DT2HT3S`、`PT1H1H`、`P1W`、`pt5s`、`5 seconds`→False；契约 33 passed（`test_predicate_predicates_closed_forms`、`test_all_produced_statements_conformant` 在内） |
| R2 | major | §3.5 输入守卫缺失/归属不清：make_actor 无守卫条目；"strip 非空"挂在 §3.6 标题下可被读作不约束 make_actor/make_activity；make_activity 对 None/5、make_actor 对 5 的行为未写；"每次新 dict"只写在 make_actor | §3.5 重写：**id 类守卫**定义于 §3.5 并声明与 §3.6 共用；make_actor 守卫 + 顶层与 account 均新容器；make_activity 守卫（str+非空+无空白）+ 每次新 dict；make_verb 深拷贝承诺 | 契约 33 passed（`test_make_actor_closed_form_and_guards`：`("", "   ", None, 5)` 抛；`test_make_activity_closed_form_and_guards`：`("", "   ", None, 5, "has space", "tab\there")` 抛；`is not` 双层断言）；探针同值复现 |
| R3 | minor | §3.9 "判定顺序冻结（见实现注释）"引用了重生成工程师不可见的实现注释；类内多条违规的顺序与消息文案未定 | §3.9 总则**内联**判定顺序 A0→A6 与类内子序；发射粒度冻结（每处失格恰一条、不聚合）；消息文案除 `"dict"` 子串与长度语义外明文不冻结；废除"实现注释"引用 | 探针：非 dict `42` → 恰 1 条含 `"dict"`；account 缺 homePage+name → 恰 2 条；Group 坏 account+坏 member → 恰 3 条（顺序 = c 内 homePage→name→d）；definition name 合法 + description 坏标签 → 恰 1 条（tests:658-661 场景） |
| R4 | minor | A5/A6 对 score/extensions/context/contextActivities 只写键集/键 IRI，未写属性本身必须为 dict；字面实现对 str 调 `.items()` 会 TypeError 违反"不抛异常" | §3.9 增加**容器属性通则**：result、context、score、extensions、contextActivities（及 display、definition）出现（非 None）须为 dict，否则恰一条形态违规且不再深入；无 None 豁免的例外清单（actor/verb/object/id/timestamp/version）明示 | 探针：`score="score"` → 恰 1 条；`extensions=[1]` → 恰 1 条（tests:621、tests:633 同例）；显式 `result=None`/`context=None`/`score=None` → 0 条；`actor=None`/`id=None`/`timestamp=None` → 1 条 |
| R5 | minor | A4 对 version 未写可否缺失：validate_statement 对缺 version 键放行还是违规未定，测试未覆盖 | §3.9 A4 冻结：**version 键缺席 → 0 条（放行）**；出现时须为 str 且匹配 `^1\.0\.[0-9]+$`；无 None 豁免 | 探针：删除 version 键 → `[]`；`version=None`、`"1.0.0rc1"` → 1 条；契约 33 passed（`"0.9.0"`、浮点 `1.0` → 违规） |
| R6 | minor | §3.7 "有 item_id"未定义（hasattr / 非 None / 真值三种读法行为不同：item_id=None 走哪个分支未消歧） | §3.7 冻结为 **hasattr 语义**（属性名存在性，与值无关）；属性存在但值非法 → 对应类型产器字段守卫拒绝（消息含不含位置不作承诺）；三属性名全缺 → 消息必须含位置下标 | 探针：无属性 `_Ghost` → `"record at index 0 …"`（含下标；契约 tests:464-469 断言下标 `"1"`）；`item_id=None` 的对象 → `"response.item_id must be a non-empty str"`（无下标要求） |
| R7 | minor | §3.6 id 类守卫放行 `" q1 "`，产出 object.id 用原值还是去空格未写；若用原值则 object.id 含空白 → 与 I7 全称矛盾（工程师会分叉） | §3.5 冻结：产出**原值透传，无去空格步骤**；`object_key` 附**无空白守卫**，三类产器 object 经 `make_activity("items/"+item_id / "kps/"+kp_id)` 构造 → item_id/kp_id **传递地禁止空白**；故 object.id 恒为 IRI，I7 全称成立、无需任何范围豁免；`strategy_id`/`learner_id` 允许内部空白（只进扩展值/account.name） | 探针：`item_id=" q1 "`、`kp_id="kp 7"` → `XAPIError`（拒绝点为 make_activity 空白扫描）；`strategy_id="s drill"` 放行入扩展；`learner_id="stu 1"` 放行且 statement_id 确定性可复现；契约 33 passed（全部 id 入参无空白） |
| R8 | minor | "语言映射"被多处引用但从未定义：值是否必须为 str 未写；tests:110-111 独立复核要求值 isinstance str，校验器是否对齐无规格依据 | §3.9 定义共享判定【语言映射】：非 dict → 1 条；逐键键须过 is_lang_tag、**值须为 str**，各自独立罚 1 条；VERBS display（I2）与 A2/A3 definition 校验统一引用该定义 | 探针：`display={"zh-CN": 42}` → 恰 1 条（`…must be str`）；契约 33 passed（坏键 `zh_CN` → 违规；独立复核 `_conformance_recheck` 对全部 12 条产出通过） |
