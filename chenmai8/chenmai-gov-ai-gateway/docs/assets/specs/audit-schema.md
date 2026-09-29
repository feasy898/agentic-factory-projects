# M7 审计 schema spec（AuditEvent + 库表 + 零明文双闸 + 管理面查询）

> 状态：frozen（§5.4 冻结——字段只增不改名）。对照 `audit/{models,store,writer,query}.py` 与
> `gateway/admin_api.py` 逐行核验于 2026-09-29。

## 1. AuditEvent（audit/models.py:22-45，`extra="forbid"`）

```json
{
  "ts": "2026-09-28T03:00:00Z", "request_id": "req_...", "session_id": "sess_...",
  "dept": "民政局",
  "route": "GOVCLOUD", "blocked": false,
  "reasons": ["SENSITIVE_ATTR"],
  "class_counts": {"ID_CARD": 2, "PHONE_MOBILE": 3},
  "prompt_preview": "〔人名·7f3a2b1c〕提交的〔身份证·…〕…",
  "response_preview": "…",
  "upstream": "govcloud_local", "latency_ms": 812, "flags": []
}
```

字段语义与约束：

| 字段 | 约束 |
|---|---|
| ts | UTC ISO8601（naive 一律视为 UTC，validator models.py:41-45）；库内定长格式 |
| route | Literal `INTERNET / GOVCLOUD / BLOCK` |
| reasons | 理由码字符串（取 RouteReason.code 词汇表，见 routing-matrix spec §4） |
| class_counts | 类别 → 计数（EntityClass 值） |
| prompt_preview / response_preview | ≤500 字符，**必须已是占位符版本** |
| upstream | BLOCK 时 null |
| flags | 如 `injection`（R2 决定性）、`output_flagged`、`route_misconfigured`、`upstream_unavailable`、`upstream_status_<n>` |

**红线**：模型**不含 raw 字段**；密级词/注入词等 BLOCK_FLAG 命中的表面形式在预览中以
`〔密级·已拦截〕` / `〔注入·已拦截〕` 占位（pipeline.py:100-104，拦截语义不进审计明文面）。

## 2. 库表（audit/writer.py:38-55）

SQLite（WAL 模式）表 `audit_events`：

```sql
CREATE TABLE IF NOT EXISTS audit_events (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  ts               TEXT    NOT NULL,
  request_id       TEXT    NOT NULL DEFAULT '',
  session_id       TEXT    NOT NULL DEFAULT '',
  dept             TEXT    NOT NULL DEFAULT '',
  route            TEXT    NOT NULL,
  blocked          INTEGER NOT NULL,
  reasons          TEXT    NOT NULL,   -- JSON 数组（理由码）
  class_counts     TEXT    NOT NULL,   -- JSON 对象（类别计数）
  prompt_preview   TEXT    NOT NULL DEFAULT '',
  response_preview TEXT    NOT NULL DEFAULT '',
  upstream         TEXT,               -- 以下 latency_ms/flags 略（同模型字段）
  ...
);
CREATE INDEX idx_audit_events_ts ON audit_events(ts);
CREATE INDEX idx_audit_events_dept ON audit_events(dept);
```

写入走**后台队列批量写**（audit/writer.py），请求路径不阻塞（阈值：入队 30 次总耗时
< 200ms，thresholds `AUDIT_APPEND_BATCH_MS`）；`AUDIT_FLUSH_TIMEOUT_S=10` 排干等待。

## 3. 零明文双闸（audit/store.py，双层防线）

1. **入库前** `assert_no_raw_pii(event, normalized_values, surface_forms)`：
   - 断言清单 = 调用方合并传入**归一化值 + 表面形式**两类（`13900139000` 与
     `139 0013 9000` 都要查，否则分隔符写法绕闸）；
   - preview 逐字符包含任一敏感值即抛 `RawPiiLeakError("masked_finding")`——失败即 500
     且**不落库**；
   - **截断边界守护**：长度恰为 500 的 preview 若以任一敏感串的 ≥4 字符前缀结尾，判定
     截断点切中敏感串 → `RawPiiLeakError("truncated_sensitive")`；
   - 截断本身走 `safe_preview`：截断点落在敏感串内部时回退到串起点（从源头保证不出现
     "半截敏感串"）；
2. **库文件级** `assert_db_no_raw_pii`：对审计 SQLite 文件（**含 -wal / -shm 旁挂**）做
   bytes 级 grep，任何原值命中即抛错——`evals.m7_audit` 与 e2e U5 的最终口径；
   扫描器有负控（防假绿）：绕过 writer 直插"毒行"（WAL 未合流态），断言必须命中。

边界（有意）：全库断言只对**审计库**成立——masking_map 表按设计必须存归一化原值，
故两会话/审计分文件（见 masking-placeholder spec §4）。

## 4. 管理面查询模型（T5.1 增补，只增不改名；audit/models.py:48-104）

| 模型 | 端点 | 字段 |
|---|---|---|
| `AuditPage` | GET /admin/api/audit | `total`（筛选命中总数）/ `events`（id 降序=新→旧）/ `limit` / `offset` |
| `LatencyStats` | metrics 内嵌 | count / avg_ms / p50/p90/p95/p99_ms（线性插值分位，0 事件全 0.0） |
| `DeptMetrics` | metrics.by_dept 元素 | dept / requests / blocked / block_rate / routes / reasons / latency_ms |
| `MetricsSummary` | GET /admin/api/metrics | window_from/to / requests / blocked / block_rate / routes / reasons / latency_ms / by_dept |

鉴权：三端点均需部门 Key（缺/错 → 401 unauthorized 信封）；分页 limit 缺省 100、
单页上限 1000（越界 400，thresholds `AUDIT_PAGE_LIMIT_DEFAULT/MAX`）。
CSV：GET /admin/api/report.csv 可下载（保密自查报告）。

## 5. 会话稳定审计抽查

thresholds `AUDIT_SESSION_STABILITY_VALUES=100`（m7 内抽查；全量 1000 值在 m3）；
`SESSION_TTL_PROBE_MS=150` 短 TTL 过期探针。

## 6. eval 指针

| eval | 覆盖 | 通过线 |
|---|---|---|
| `evals.m7_audit` | A 落库完整性（WAL/30 事件/字段往返/重开库直读/入队延迟）+ B 零明文硬闸+全库 bytes 扫描（含负控）+ C 会话存储 + D 管理面 20 混合请求（行数/聚合明细一致/CSV/鉴权负例/分页钳位） | `M7 AUDIT(...): 16/16`（gate_b5 实测口径），exit 0 |
| `evals.m10_e2e` U5 | 审计行数 = 用例数；SQLite 文件 bytes 级 grep 全部 normalized 原值零命中 | 见 gates spec §2 |
| 六道门指针 | gate_b1 ⑤ / gate_b2 ②-5（T1.3 口径）→ gate_b5 ③（T5.1 全量口径） | 见 [gates](gates.md) |
| 看板页 | GET /webui/dashboard 指标卡三槽位 + 三张手写 SVG 柱状图 + BLOCK 徽标 + 明细分页钳位 | `evals.m9_webui` 12/13 检查项（T5.2 全量口径） |
