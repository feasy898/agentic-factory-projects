# M3 可逆脱敏 spec（占位符冻结算法 + 会话存储 + 流式还原 + 工具还原）

> 状态：frozen（契约冻结，字段只增不改名）。对照 `masking/{mapper,models,session_store,remap,toolbuf}.py`
> 逐行核验于 2026-09-29。目标读者：只凭本页 + eval（`evals.m3_masking`、`evals.m7_audit` C 节）重建本模块的新 agent。

---

## 1. 职责与边界

**做**：会话稳定占位符的生成与可逆还原（§5.3.1 冻结算法）、归一化值承接（§5.3.2，见
[masking-normalize](masking-normalize.md)）、会话映射存储（内存 LRU + SQLite 落盘 + TTL）、
SSE 文本增量的流式还原状态机、流式工具调用参数的缓冲还原。

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
| 分隔符（摘要 msg 内） | `\x1f`（ASCII 单元分隔符） | mapper.py:46 |
| 摘要 | HMAC-SHA256，key=MASK_KEY 的 UTF-8 字节，msg UTF-8 | mapper.py:68-70 |
| 占位符三件套 | 开 `〔`、隔 `·`、闭 `〕`（全角括号+间隔点） | mapper.py:30-32 |
| 升位序列 | `DIGEST_WIDTHS = (8, 10, 12)`，逐级重试；12 位仍碰撞抛 RuntimeError（概率可忽略） | mapper.py:35, 79-102 |
| 中文标签 | `EntityClass.label`（如 人名/手机号/身份证，见 recognizers-rule spec §2） | mapper.py:81 |

三条设计语义（冻结）：

- **会话稳定**：同 session 同 (type, normalized) → 恒同占位符；首次插入后复用，
  `first_seen` 不变（mapper.py:73-77）；
- **跨 session 必不同**：session_id 参与摘要 msg（设计如此，演示时说明）；
- **归一化等价**：同一实体的不同写法 → 同 normalized → 同占位符（上游识别层统一调
  `masking.normalize.normalize_value`，两张写法同号同占位符）。

### 2.1 还原形状正则（mapper.py:38-43，冻结）

```
〔 + (不含 〔〕· 的非空标签) + · + ([0-9a-f]{8,12}) + 〕
```

- `restore(text)`：整段正则替换，映射表外占位符形状**原样保留**（不吞不放行语义）；
- `lookup(placeholder)`：单条查找，未命中返回 `None`——流式状态机的查找入口；
- `mask(text, spans)`：span 按 start 降序替换（避免位移），返回条目按正文升序。

## 3. 会话存储（masking/session_store.py，T1.3）

双层结构：

- **写路径**：`SessionMapper.on_insert` 回调 → 即时 `INSERT OR REPLACE INTO masking_map`
  （主键 `(session_id, placeholder)`，session_store.py:40-49 SCHEMA；含
  `idx_masking_map_first_seen` 索引）；
- **读路径**：进程内 `SessionRegistry`（LRU，默认容量 1024，mapper.py:158-185）未命中 →
  工厂按 session_id 从库恢复**未过期**行 → `SessionMapper.hydrate()`（恢复行不触发
  on_insert、不覆盖内存已有条目，mapper.py:129-142）；
- **确定性**：占位符是纯 HMAC 函数——重启、换出、甚至 TTL 过期后同 session 同值再到达
  仍得**同一占位符**；过期后映射行被删，还原能力失效（lookup→None，占位符原样保留）；
- **TTL**：默认 24h（config `session_ttl_h`）；`cleanup()` 删过期行 + 换出空闲会话，
  `cleanup_loop()` 为事件循环清理协程；
- **线程模型**：SQLite 连接 `check_same_thread=False` + 内部锁（网关事件循环 get、
  清理协程/eval 线程 cleanup 共用一把）。

`MappingEntry`（masking/models.py，§5.3.3 冻结形状，`extra="forbid"`）：

```json
{"placeholder": "〔手机号·9a1b2c3d〕", "type": "PHONE_MOBILE",
 "normalized": "13800138000", "first_seen": "2026-09-28T03:00:00Z",
 "session_id": "sess_...", "preserve_semantic": false}
```

## 4. 库文件边界（有意分文件，审计红线）

`masking_map` 按设计**必须存归一化原值**才能还原；审计库要过 bytes 级全文件零明文扫描
（§9 U5）。**两表不得同文件**：审计库 `data/audit.db`，会话库 `data/session_map.db`
（config/app.yaml `audit_db` / `session_db` 两键，session_store.py 模块文档）。

## 5. 流式还原状态机（masking/remap.py，spec 一字不差）

问题：上游把回答切成 SSE 增量块，占位符可能被切进相邻两个 chunk，逐块整段正则替换必然漏配。

状态机（`StreamRestorer`，单响应实例不可跨响应复用；状态只有一项有界缓冲 `_pending`）：

1. 扫描到 `〔` 即开始**缓冲**（候选态），不再放行任何字符；
2. 候选凑成完整形状 `〔<标签>·<hex8-12>〕`（总长 ≤ `MAX_PLACEHOLDER_LEN = 32`）→ 查映射，
   命中替换为原值发出，未命中**原样发出**（未知形状不放行也不吞掉）；
3. 缓冲**超过 32 字符**仍无 `〕` → 判定普通文本：放行候选首字符 `〔`，其余重新扫描
   （内部再遇 `〔` 自然开启新候选）；
4. `flush()`：流结束，残留候选按普通文本放行。

不变式：任意 1..N 字符切块方式下，`feed()*k + flush()` 的拼接输出恒等于整段
`SessionMapper.restore` 的结果（`evals.m3_masking` 以 1–7 字节随机切块 fuzz 500 条钉死，
thresholds `MASK_STREAM_FUZZ_CASES=500`、`MASK_CHUNK_MIN/MAX_BYTES=1/7`）。

## 6. 工具调用参数还原（masking/toolbuf.py，spec 一字不差）

- **流式**：`tool_call.arguments` 增量累积、**finish 前不发**（明示行为变化：客户端在
  finish 前收不到任何 tool_calls 增量）；finish 时整体还原后作为**单个 delta** 发出
  （按 index 分槽累积、finish 收尾幂等、缓冲有界 `MAX_ARGUMENTS_CHARS` 安全阀——超限
  响亮失败而非静默截断）；
- **非流式**：`restore_arguments` 直接整体还原；
- 与流式文本还原的分工：文本流必须在线放行（状态机缓冲）；参数流允许整段 hold 到
  finish，拼接视角逐字相等，整段 restore 与"逐块还原"严格等价——后者正是占位符被
  切进两个 arguments 增量时漏配的根源。

## 7. eval 指针

| eval | 覆盖 | 通过线 |
|---|---|---|
| `evals.m3_masking` | 稳定性 1000 值同 session 全等/跨 session 不同；归一化等价；流式 fuzz 500 条；工具调用还原；10 万值碰撞抽样；还原性能 | 8/8 checks passed，exit 0（2026-09-29 实测 4.3s） |
| `evals.m7_audit` C 节 | 会话存储落库/重启恢复/LRU 换出复活/TTL 过期/窗口内不误删 | 见 audit-schema spec §6 |
| `evals.t0_stream` | SSE 组帧 + 流式还原 + 工具缓冲管线级 | gate_d0 ③ 固化 |
| 六道门指针 | gate_b2 ③-3 起逐批回归；gate_b4/b5 经整门链间接覆盖 | 见 [gates](gates.md) |
