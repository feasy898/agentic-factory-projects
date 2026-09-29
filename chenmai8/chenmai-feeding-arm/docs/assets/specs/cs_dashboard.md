# cs_dashboard spec（数据层：HTTP 契约 + SQLite + 单页看板 + SSE）

> 状态：**frozen**（2026-09-29 测试实测 5/5 全绿）。本页对照 `chengshao/cs_dashboard/`
>（app.py / store.py / __main__.py / static/）逐行核验于 2026-09-29。

---

## 1. 职责与边界

**做**：进餐会话/单口记录的唯一持久化点；冻结 HTTP 契约 + 追加端点；SSE 实时推送；
离线单页看板（静态资源本地化）。

**不做**：不做聚合计算之外的业务逻辑（克数聚合口径在 store，见 §4）；静态资源不引第三方
CDN（Chart.js 单文件 vendor 随仓分发）。

## 2. HTTP 契约（app.py，冻结 = 只增不改名）

| 方法/路径 | 语义 | 状态码 |
|---|---|---|
| POST `/api/session/start` body `{user_id}`（min_length=1，空→422） | 新开会话 → `{session_id}` | 已有进行中会话 → 409 |
| POST `/api/bite` body 裸 BiteRecord | 写入**当前进行中会话**（契约：body 无会话字段，归属即当前会话） | 204；无会话/重复 bite_id → 409；校验失败 422 |
| GET `/api/session/current` | 进行中会话；全部已结束则取最近一餐 | 无任何会话 → 409 |
| GET `/api/stream` | SSE（text/event-stream） | — |

追加端点（只增纪律允许）：`GET /api/health`（存活探针）、`GET /api/summary`（聚合快照）、
`POST /api/session/end`（结束当前会话）、`GET /api/events?limit=100`（事件镜像倒序）、
`GET /`（单页看板）+ `/static`。

**SSE 事件**：连接建立即推 `snapshot` `{session, summary}`；随后 `bite` /
`session_started` / `session_ended`（各带 session+summary）；每 15s 推注释心跳
（`: keepalive`）防中间层空闲断连。订阅队列 maxsize=256，**慢消费者丢帧优先于阻塞主链路**。

## 3. 存储层（store.py，SQLite 单文件）

- 库文件：仓库根 `data/care.db`（data/ 已 gitignore）；env `CS_DASHBOARD_DB` 覆盖。
  连接 `check_same_thread=False` + RLock（uvicorn 单事件循环 + 测试线程共用安全）；
  `PRAGMA journal_mode=WAL` + `foreign_keys=ON`。
- 表：`sessions(session_id PK, user_id, started_ns, ended_ns)`；
  `bites(session_id+bite_id PK, ts_start/end_ns, outcome, grams_before/after)`（防双计）；
  `events(id, ts_ns, kind, payload)`（事件流镜像，回放/取证）+ ts 索引。
- 领域错误 → HTTP 映射：`NoActiveSessionError`/`ActiveSessionExistsError`/`DuplicateBiteError` → 409。

## 4. 聚合口径（summary()）

- `bite_count`：会话内单口数；`outcomes`：success/retry/rejected/aborted 分布。
- **克数 all-or-none**：全部单口都有 grams_before/after 时
  `total_grams = Σ max(0, before−after)`（碗/勺减重口径）；**任一缺失 → total_grams=None**
  （无称重硬件的既定口径）。注意 `MealSession.total_grams` 字段留给有称重的上游填，
  store 聚合不受它影响。
- `duration_s`：已结束 = ended−started；进行中 = 当前时间−started（实数秒，3 位小数）。
- `current_session`：进行中优先；否则最近一餐（按 started_ns DESC）。

## 5. 单页看板（static/）

- `index.html` + `app.js` + `style.css` + `static/vendor/chart.umd.js`
  （Chart.js 4.4.1 单文件 UMD，sha256 锁定见 reports/upstream_lock.md `vendor-chart-lib` 条目；
  文件字节原样分发）。看板内容：口数/时长/克数曲线、当前状态、报警高亮；SSE 实时刷新；
  **离线可开**（零第三方外链）。
- 启动：`python -m cs_dashboard`（uvicorn，缺省 `http://127.0.0.1:8100`）。

## 6. eval（精确命令与通过线）

```bash
# cwd = 仓库根（进程内 ASGI 测试，随机端口+临时库，不触碰 data/care.db）
.venv/Scripts/python.exe -m pytest tests/test_dashboard.py -q
#   → exit 0；2026-09-29 实测 5 passed（POST 30 口无丢失、GET 聚合一致、
#     首页 200+静态资产全 200+零一方外链、SSE snapshot/bite 收达、
#     422/409 负例、克数聚合口径）。
# 手工验收（演示用）：
.venv/Scripts/python.exe -m cs_dashboard   # → http://127.0.0.1:8100 截图入 reports/
```

- 通过线：30/30 口数据无丢失、聚合字段一致；离线可开（外链数=0）。
- 生产接线：cs_orchestra.runtime.HttpDashboardSink 消费本契约
  （start_session/post_bite/end_session，httpx 5s 超时；连接失败上抛由上层降级）。
