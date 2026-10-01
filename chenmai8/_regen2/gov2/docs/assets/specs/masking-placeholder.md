# M3 可逆脱敏 spec（占位符冻结算法 + 容错改形还原 + 会话存储 + 流式还原 + 工具还原）

> 状态：frozen（契约冻结，字段只增不改名）。对照 `masking/{mapper,models,session_store,remap,toolbuf}.py`
> 逐行核验于 2026-09-30（含 T8.4 容错改形还原增补，`88b176f`/`515d024`/`80d87ae` 三提交）。
> 目标读者：只凭本页 + eval（`evals.m3_masking` 9 检查、`evals.m7_audit` C 节）重建本模块的新 agent。

---

## 1. 职责与边界

**做**：会话稳定占位符的生成与可逆还原（§5.3.1 冻结算法）、改形占位符的容错还原与泄漏
检测面（T8.4，见 §2.2）、归一化值承接（§5.3.2，见 [masking-normalize](masking-normalize.md)）、
会话映射存储（内存 LRU + SQLite 落盘 + TTL）、SSE 文本增量的流式还原状态机、流式工具调用
参数的缓冲还原。

**不做**：识别（recognizers 包）、归一化规则本体（同包 `normalize.py`，独立 spec）、
路由决策（routing 包）、审计（audit 包——审计红线：占位符原文 normalized 只进
`masking_map` 表，**永不进审计库**，两库分文件见 §4）。

## 2. 占位符冻结算法（§5.3.1，一字不差）

```
digest  = HMAC-SHA256(key=MASK_KEY, msg=f"{session_id}\x1f{type}\x1f{normalized}").hexdigest()
digest8 = digest[:8]；同 session+type 内碰撞则升位（插入时检测）
placeholder = "〔" + 中文标签 + "·" + digest8 + "〕"      # 例：〔人名·7f3a2b1c〕
```

代码对照 `masking/mapper.py`：

| 冻结点 | 值 | 位置 |
|---|---|---|
| 括号三件套 | 开 `〔`、隔 `·`、闭 `〕`（全角括号+间隔点；模块常量 `PLACEHOLDER_OPEN/SEPARATOR/CLOSE`） | mapper.py:31-33 |
| 分隔符（摘要 msg 内） | `\x1f`（ASCII 单元分隔符，`_DIGEST_SEPARATOR`） | mapper.py:47 |
| 摘要 | HMAC-SHA256，key=MASK_KEY 的 UTF-8 字节，msg UTF-8（`SessionMapper._digest`——白盒覆写点，见 §2.3） | mapper.py:186-188 |
| 升位序列 | `DIGEST_WIDTHS = (8, 10, 12)`，逐级重试；12 位仍碰撞抛 RuntimeError（概率可忽略） | mapper.py:36, 218-220 |
| 中文标签 | `EntityClass.label`（如 人名/手机号/身份证，见 recognizers-rule spec §2） | mapper.py:199-201 |

三条设计语义（冻结）：

- **会话稳定**：同 session 同 (type, normalized) → 恒同占位符；`placeholder_for` 首查
  `(type.value, normalized)` 快路径复用，`first_seen` 不变，条目不重复建（mapper.py:192-195）；
- **跨 session 必不同**：session_id 参与摘要 msg（设计如此，演示时说明）；
- **归一化等价**：同一实体的不同写法 → 同 normalized → 同占位符（上游识别层统一调
  `masking.normalize.normalize_value`，两张写法同号同占位符）。

碰撞升位插入期检测的精确语义（mapper.py:196-220，`evals.m3_masking` 白盒钉死）：

1. 首选 8 位；若该 8 位占位符已被**异值**（normalized 或 type 不同）占用 → 升 10 位重试；
2. 8/10 位全被异值占 → 升 12 位；12 位仍被占 → `RuntimeError`（拒绝插入）；
3. **同值再到达复用升位条目**：某值曾因碰撞升位后，同 (type, normalized) 再次到达经快路径
   复用；极端序列（低 8 位先被异值 A 占住 → 值 B 升位插入 → 此后 A 的同值再到达）也直接
   复用 B 之前已有的同占位符条目，不新插、不抛错（mapper.py:213-216）；
4. 升位与摘要的关系统计口径：全量插入后「最终占位符 >8 位」的条数 == 「digest8 前缀重复值」
   的条数（10 万值探测零最终碰撞，`evals.m3_masking` step `collide:100k-insert-escalation`）。

### 2.1 还原形状正则（`RESTORE_PATTERN`，mapper.py:39-44，冻结）

```
〔 + (不含 〔〕· 的非空标签) + · + ([0-9a-f]{8,12}) + 〕
```

- **T8.4 起 `SessionMapper.restore` 走 §2.2 的 `restore_tolerant` 容错扫描**（mapper.py:233-240），
  本正则不再是还原主路径，保留为**检测面**：冻结 eval 的 fixture 自检（构造占位符数、还原后
  零占位符断言）与审计预览占位符在位断言（预览=还原前占位符版本）用严格口径；
- `lookup(placeholder)`：单条查找，未命中返回 `None`——流式状态机与容错还原的查找入口
  （mapper.py:242-245）；
- `mask(text, spans)`：span 按 start 降序替换（避免位移），返回条目按正文升序（mapper.py:222-231）。

### 2.2 容错改形还原（T8.4 增补，mapper.py:49-164，spec 一字不差）

问题（gate_final b6 一轮 U8 GOVCLOUD 腿实锤）：真实大模型回复会把占位符 token **改形**
（模型输出随机性）：反引号/代码样式包裹、空白与换行插入拆开、hex 大小写与全半角转写、
易混字符（O→0、I/l→1）、同形括号（`〔`→`【`/`[`）与间隔号（`·`→`・`/`•`/`.`）替换——超出
`RESTORE_PATTERN` 匹配面（或形状匹配而查表键不等，如「〔人名 ·…〕」标签内空白），还原漏配
→ 改形残留直达客户端。

**冻结常量**（mapper.py:59-75）：

| 常量 | 值 | 用途 |
|---|---|---|
| `PLACEHOLDER_OPEN_VARIANTS` | `〔【〖［[`（5 字符） | 开括号同形变体 |
| `PLACEHOLDER_CLOSE_VARIANTS` | `〕】〗］]`（5 字符） | 闭括号同形变体 |
| `PLACEHOLDER_SEP_VARIANTS` | `·・•‧⋅﹒．.`（8 字符） | 间隔号同形变体 |
| `PLACEHOLDER_TOLERANT_MAX_LEN` | `48`（字符） | 改形候选最大扫描窗（规范形状 ≤32，容忍反引号/空白/换行噪声放宽到 48；remap 缓冲上限与之同源） |
| `_MANGLE_NOISE_RE` | `[\s`]+` | 改形噪声字符类：全部空白/换行/反引号 |
| `_DIGEST_CONFUSABLE` | `o→0、i→1、l→1` | hex 转写易混兜底（仅作用于 digest 段） |

**`canonical_placeholder(inside: str) -> str | None`**（mapper.py:78-99）：候选括号内文本 →
规范占位符键 `〔标签·hex〕`；规范化三步，**顺序固定**：

1. 剥除改形噪声：`_MANGLE_NOISE_RE.sub("", inside)`（空白/换行/反引号全删）；剥后为空 → None；
2. 按间隔号变体切分：`_SEP_VARIANTS_RE.split(compact)` 必须恰 **2** 段（多段/单段=不是占位符
   → None）；标签段与摘要段均非空；**标签段不得含任何括号变体**（含 → None）；
3. 摘要段规范化：`NFKC` 全半角归一 → 小写 → `_DIGEST_CONFUSABLE` 兜底翻译后，必须
   `[0-9a-f]{8,12}` fullmatch（mapper.py:75 `_DIGEST_SHAPE_RE`），否则 None。

通过后返回规范键 `f"〔{label}·{digest}〕"`（标签**原样**保留，不做任何归一——查表键即注册键）。

**`restore_tolerant(text, lookup) -> str`**（mapper.py:102-138）：整段容错还原扫描，判定链：

1. 从当前位找下一个**开括号变体**；其后不再有 → 余下全部普通文本；
2. 在 `[开括号+1, 开括号+47)` 字符窗内找**闭括号变体**（窗= `min(n, open_at + 48 - 1)`）；
3. 找到闭括号 → 括号内文本经 `canonical_placeholder` 规范化 → `lookup(规范键)`：
   命中 → 输出原值，消费到闭括号后继续；未命中/规范化失败 → **放行开括号字符本身**，
   从开括号后一位重扫（内部若再出现开括号自然开启新候选）——输出逐字无损；
4. 窗内无闭括号 → 同样放行开括号、后移一位重扫。

与 `StreamRestorer`（§5）共用同一判定链（canonical_placeholder + lookup），fuzz 断言保证
整段与流式严格等价。误替防线：结构 `〔标签·hex8-12〕` 本身特异 + 映射表命中这道终审闸。

**`tolerant_placeholder_hits(text) -> list[str]`**（mapper.py:141-164）：泄漏检测面（比
`RESTORE_PATTERN` 宽）——返回文本中全部「可规范化为占位符形状」候选的**规范键**（按出现序，
不去重），不管是否仍在会话映射表内。真实大模型腿的「占位符零泄漏」断言以此为准：
还原正则不可见的改形残留（静默泄漏）也能抓到。

### 2.3 白盒契约（eval 依赖，冻结）

- `SessionMapper._digest(type_value: str, normalized: str) -> str`：摘要计算唯一入口，
  冻结 eval 以子类覆写它确定性复现碰撞升位路径（`_ForcedDigestMapper`）；
- 构造形状：`SessionMapper(session_id, key, *, on_insert=None)`；
  `placeholder_for(entity_type, normalized) -> tuple[placeholder, MappingEntry]`；
  `hydrate(entries) -> int`；`purge_expired(cutoff) -> int`；`entries() -> list[MappingEntry]`。

已知改形形态目录（`evals.m3_masking` step `remap:mangled-forms` 冻结 11 形态 + 4 负例，
构造样本直测、不依赖模型随机性）：verbatim / backtick-wrap（反引号在括号**外**，属普通文本
原样保留 → 还原槽位为 `` `原值` ``）/ space-around-sep（`〔人名 ·hex〕`）/ newline-split /
uppercase-hex / fullwidth-hex / confusable-o（0→O）/ katakana-sep（`・`）/ ascii-brackets
（`[...]`）/ corner-brackets（`【...】`）/ combo-worst（空白+片假名隔点+反引号+大写 hex 组合）。
负例（零误替，原样放行）：`【注·见附件】`、`[链接](https://example.com)`、
`〔本段·没有占位符〕`（hex 段非 hex）、`〔未知·deadbeef〕`（形状合规但查表未命中）。

## 3. 会话存储（masking/session_store.py，T1.3）

双层结构：

- **写路径**：`SessionMapper.on_insert` 回调 → 即时 `INSERT OR REPLACE INTO masking_map`
  （主键 `(session_id, placeholder)`，session_store.py:39-50 SCHEMA；含
  `idx_masking_map_first_seen` 索引）；
- **读路径**：进程内 `SessionRegistry`（LRU，默认容量 1024，容量下限钳 1、key 空抛
  ValueError；get 时 move_to_end、超容 popitem(last=False)；另备 `evict_where`/`apply`，
  mapper.py:276-317）未命中 → 工厂按 session_id 从库恢复**未过期**行 →
  `SessionMapper.hydrate()`（已在内存的占位符不覆盖——内存态为准；恢复行不触发
  on_insert；返回实际恢复条数，mapper.py:247-260）；
- **确定性**：占位符是纯 HMAC 函数——重启、换出、甚至 TTL 过期后同 session 同值再到达
  仍得**同一占位符**；过期后映射行被删，还原能力失效（lookup→None，占位符原样保留）；
- **TTL**：默认 24h（config `session_ttl_h`，`SessionStore.DEFAULT_TTL`）；`cleanup()` 删
  `first_seen < cutoff` 的库行 + 内存条目同口径 `purge_expired` + 换出空闲超 TTL 会话
  （按 `time.monotonic()` 活跃度），`cleanup_loop(interval_s=300)` 为事件循环清理协程
  （sqlite3.Error 捕获记日志、下轮重试）；
- **线程模型**：SQLite 连接 `check_same_thread=False` + WAL + 内部锁（网关事件循环 get、
  清理协程/eval 线程 cleanup 共用一把）。

`MappingEntry`（masking/models.py，§5.3.3 冻结形状，`extra="forbid"`）：

```json
{"placeholder": "〔手机号·9a1b2c3d〕", "type": "PHONE_MOBILE",
 "normalized": "13800138000", "first_seen": "2026-09-28T03:00:00Z",
 "session_id": "sess_...", "preserve_semantic": false}
```

- `first_seen` validator：naive datetime 一律补 UTC（工程约定：时间统一 UTC ISO8601
  存储，models.py:30-34）；
- `preserve_semantic` 默认 False（P1 语义保留替换预留位，CONTRACTS 痛点 #3 如实标注）。

## 4. 库文件边界（有意分文件，审计红线）

`masking_map` 按设计**必须存归一化原值**才能还原；审计库要过 bytes 级全文件零明文扫描
（§9 U5）。**两表不得同文件**：审计库 `data/audit.db`，会话库 `data/session_map.db`
（config/app.yaml `audit_db` / `session_db` 两键，session_store.py 模块文档）。

## 5. 流式还原状态机（masking/remap.py，spec 一字不差）

问题：上游把回答切成 SSE 增量块，占位符可能被切进相邻两个 chunk，逐块整段正则替换必然漏配。

状态机（`StreamRestorer`，单响应实例不可跨响应复用；状态只有一项有界缓冲 `_pending`）：

1. 扫描到**开括号变体**（`〔【〖［[` 之一，T8.4：模型会转写同形括号）即开始**缓冲**
   （候选态），不再放行任何字符；
2. 候选凑成完整括号对（闭括号变体出现在开括号后 47 字符窗内）→ 内文经
   `masking.mapper.canonical_placeholder` **规范化**（§2.2 容错改形）成规范键 → 查会话
   映射表，命中 → **替换为原值发出**；未命中/规范化失败 → **原样放行开括号字符本身**，
   其余重新扫描（未知形状不放行也不吞掉）；
3. 缓冲超过 `MAX_PLACEHOLDER_LEN = PLACEHOLDER_TOLERANT_MAX_LEN = 48` 字符仍无闭括号 →
   判定普通文本：放行候选首字符（开括号），其余重新扫描（remap.py:43 与 mapper 侧同源；
   T8.4 前为 32，升 48 以容纳改形噪声字符）；
4. `flush()`：流结束，残留候选按普通文本原样放行。

缓冲精确语义（remap.py:102-105）：数据尾距开括号 `< MAX_PLACEHOLDER_LEN - 1`（47）字符
且窗内未见闭括号 → 整段候选进 `_pending` 等下一增量（占位符前缀可能跨块）；候选起点距
数据尾 ≥47 仍无闭括号 → 超窗，放行开括号重扫。`_pending` 恒 ≤48，有界即安全。

API 面（冻结）：`StreamRestorer(lookup)`——lookup 须 callable，否则 TypeError
（remap.py:59-60）；`feed(text) -> str`（空块返回空串；返回本块可安全发出的还原文本）；
`flush() -> str`；`pending_len`（观测口，恒 ≤48）；`reset()`（丢弃缓冲，仅测试/异常恢复用）。

不变式：任意 1..N **字符**切块方式下，`feed()*k + flush()` 的拼接输出恒等于整段
`SessionMapper.restore`（即 restore_tolerant）的结果（`evals.m3_masking` 以 1–7 字符随机
切块 fuzz 500 条钉死——阈值常量名 `MASK_CHUNK_MIN/MAX_BYTES` 沿用历史名，语义是**字符**）。
T8.4 起改形形态同样逐条以 2 个随机种子走流式还原全等断言。

## 6. 工具调用参数还原（masking/toolbuf.py，spec 一字不差）

- **流式**：`tool_call.arguments` 增量累积、**finish 前不发**（明示行为变化：客户端在
  finish 前收不到任何 tool_calls 增量；`feed` 恒返回 `None`）；finish 时整体还原后每个
  工具作为**单个 delta** 发出；
- **非流式**：`restore_arguments(mapper, arguments)` 直接整体还原。

冻结细节（toolbuf.py）：

- **缓冲上限**：`MAX_ARGUMENTS_CHARS = 1_000_000`（:47）——hold-to-finish 是流式路径唯一
  无上界显式缓冲点，故设安全阀；语义为**绊线**：追加后检查，超限抛
  `ToolArgumentsOverflowError`（`RuntimeError` 子类，:52-53），**缓冲状态原样保留（含触发
  块）**供上层诊断——绝不静默截断；构造参数 `max_arguments_chars` 可调（<1 抛
  ValueError；冻结 eval 以阀=16 验证响亮失败+状态完好+finalize 仍确定性整体还原，:91-97）；
- **分槽**：按 `index` 分槽累积；无 `index` 的增量按 index=0 归槽（:104-105）；非 dict
  元素跳过不炸（:102-103）；同一调用的 `id`/`function.name` 可能只在首个增量出现（也可能
  重复）——按槽位保留**首见非空值**（:107-112）；delta 中其余字段（OpenAI 兼容扩展）存入
  extra 并在 finalize 时原样并入 delta（:121-123, 142）；
- **finalize**：按 index 升序返回，每工具一个完整 delta（`{"index", "type": "function",
  "id", "function": {"name", "arguments"}}` 形状 + extra）；返回后缓冲清空——重复 finalize
  返回空表，幂等收尾（:130-145）；finalize 结果与 `mapper.restore(拼接原文)` 逐字相等；
- **观测口**：`held_events`（累计吞下的含参增量数）、`held_arguments(index)`（当前槽位
  拼接、不还原）、`__bool__`（有在途槽位即真）（:89-97, 125-128, 147-148）；
- **restore_arguments**：还原是纯串级替换（占位符形状不含 `"`/`\` 等 JSON 结构字符，替换
  只发生在字符串字面量内部）；还原改变了串且原串可 JSON 解析、还原后不可解析 → 记结构化
  warning（`toolbuf.restore_broke_json`）但**保留还原结果**（占位符→原值是正确语义，不回退）；
  纯文本非 JSON 参数照常替换、无占位符原样返回（:64-75）；
- 与流式文本还原的分工：文本流必须在线放行（状态机缓冲）；参数流允许整段 hold 到
  finish，拼接视角逐字相等，整段 restore 与"逐块还原"严格等价——后者正是占位符被
  切进两个 arguments 增量时漏配的根源。冻结验收含：显式两块切分全扫描（切点扫过全部
  位置）+ 200 种子随机切块 fuzz + 双工具交错（id/name 只在各自首块）+ 无 index 归槽。

## 7. eval 指针

| eval | 覆盖 | 通过线 |
|---|---|---|
| `evals.m3_masking` | 稳定性 1000 值同 session 全等/跨 session 不同；归一化等价 6 类 18 变体；流式 fuzz 500 条；**改形还原 11 形态+4 负例（T8.4）**；工具调用还原（hold-to-finish/全切分扫描/fuzz/多工具/溢出阀）；10 万值碰撞抽样+白盒升位单测；还原性能 | **9/9 checks passed，exit 0**（2026-09-30 实测；T8.4 增 `remap:mangled-forms` 后由 8/8 变 9/9） |
| `evals.m7_audit` C 节 | 会话存储落库/重启恢复/LRU 换出复活/TTL 过期/窗口内不误删 | 见 audit-schema spec §6 |
| `evals.t0_stream` | SSE 组帧 + 流式还原 + 工具缓冲管线级 | gate_d0 ③ 固化 |
| 六道门指针 | gate_b2 ③-3 起逐批回归；gate_b4/b5 经整门链间接覆盖；gate_final b6 以 U8 改形泄漏实锤驱动 T8.4 增补 | 见 [gates](gates.md) |
