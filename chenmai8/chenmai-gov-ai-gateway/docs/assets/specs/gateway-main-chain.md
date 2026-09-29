# M1 网关主链 spec（pipeline + SSE 管线 + 出站全量叶节点规则 + 端口拓扑）

> 状态：frozen。对照 `gateway/{app,pipeline,sse,provider,deps,models,admin_api,mock_upstream}.py`
> 逐行核验于 2026-09-29。目标读者：只凭本页 + eval（`evals.t0_gateway`、`evals.t0_stream`、
> `evals.m10_e2e`）重建本模块的新 agent。

## 1. 主链处理序（gateway/pipeline.py 模块文档，§3 数据流，冻结）

```
1 auth(dept key，app 层) → 2 detect(规则层 + 语义层注入检测，recognizers.pipeline.detect_full)
→ 3 mask(会话稳定占位符) → 4 route(routing.engine) → 5 转发(provider，非流式/流式)
→ 6 还原(占位符→原值) → 7 outguard(复检钩子 + AI 标识；BLOCK 时代答/拒答)
→ 8 audit(零明文硬闸；app 默认=SQLite 写队列)
```

- 非流式与流式共用 `_prepare`（detect+mask+route 一次完成）；差异只在转发与还原形态；
- BLOCK / 上游不可达(502) / 上游协议错误在**开流前**决出，仍返回普通 JSON 信封；
  开流后（已 200）中途断流只能以 SSE 错误事件收尾；
- 流式审计在流收尾时落账（response_preview 为**还原前**占位符版本）；零明文硬闸失败时
  事件不落库并大声记日志（流已 200，500 无法回传）。

## 2. 出站全量叶节点规则（pipeline.py:144-208，冻结——密级词藏哪都要拦）

出站检测面 = **主面 + 辅助面**，任一 BLOCK_FLAG 命中整单拦截：

### 2.1 主面（`_content_segments`，pipeline.py:131-141）

消息 content 的文本段：`str` content 原样一段；`list` content 中的 `str` 片段与
`type=="text"` 的 dict 片段（`piece.get("text")`）。逐段检测/脱敏后**原位替换**
（`_Segment(msg_index, piece_index, text)` 定位）。

### 2.2 辅助面（`_aux_texts`，pipeline.py:161-191）

`_iter_string_leaves`（pipeline.py:144-158）递归产出 JSON 结构中的**字符串叶节点**
（字符串值本身不再下探），覆盖三类：

1. `tools` 定义：function.description / parameters 说明等全部字符串叶；
2. 历史消息的 `tool_calls`（每条 function 的 name/arguments）与 `function_call`
   （legacy 形态）——PII/密级词常藏在历史参数里；
3. content 中**非 text** 多模态段的字符串叶（如 image_url 的 data URL、alt 文本）。

content 的 str 段与 `type=="text"` 段由主面覆盖，辅助面**跳过不重复**。

### 2.3 出站重建（`_apply_aux_masked`，pipeline.py:194-202）

深拷贝式重建：dict/list 结构中的字符串叶按 `原文 → 脱敏文` 精确映射替换；映射中没有的
字符串原样保留（与检测面同一全集，未映射即未检出）。

## 3. 流式管线（gateway/sse.py，三段组合）

1. `iter_sse_data_lines`：字节流 → `data:` 载荷，按 `\n` 切行 + **跨 chunk 缓冲半行**
   （上游任意字节切块——含把多字节 UTF-8 切成两半——都不破行）；多行 data: 按空行组帧；
2. `ToolCallBuffer`（masking.toolbuf）：工具参数 hold-to-finish（见 masking-placeholder spec §6）；
3. `compose_chat_stream`：逐事件透传 + 文本增量过 `StreamRestorer` + finish 时注入 AI
   标识（尾注 delta + finish chunk `choices[0].delta.annotations`，与流式 message.annotations
   同名同形）；`[DONE]` 哨兵与非 JSON 载荷原样透传（不吞不猜）。

## 4. 错误信封（§5.6，冻结）

`{"error": {"code","message","reasons"}}`；code 词表（pipeline.py:87-91）：
`content_blocked`（BLOCK 恒此码，HTTP 403）/ `bad_request`(400) / `unauthorized`(401) /
`payload_too_large`(413) / `internal_error`(500) / `upstream_error`(502)。
文件通道错误映射：FileTooLargeError→413、UnsupportedFileType→400、DocumentParseError→422、
ExportBlockedError→422（gateway/app.py）。

## 5. HTTP 端点全表（2026-09-29 对照 app.py/admin_api.py/webui 逐行）

| 方法 路径 | 鉴权 | 说明 |
|---|---|---|
| POST /v1/chat/completions | 部门 Key | OpenAI 兼容（流式+非流式）；响应头 `x-anongw-route` / `x-anongw-request-id` |
| GET /v1/models | 部门 Key | 路由目标清单（脱敏视图，仅名字） |
| POST /v1/files/inspect | 无（上传者自带文件回显，见 filechannel service 模块文档口径） | multipart → FileReport JSON |
| POST /v1/files/export | 无 | multipart + mode=sanitize → 清理后文件流 + `X-Report-Id` + `X-Sanitize-Method` |
| GET /admin/api/audit | 部门 Key | 分页查询（dept/from/to/route/blocked；limit 缺省 100 上限 1000 越界 400） |
| GET /admin/api/metrics | 部门 Key | 按部门/路由/拦截类别聚合 |
| GET /admin/api/report.csv | 部门 Key | 保密自查报告导出 |
| POST /admin/api/demo/seed | 部门 Key | 三部门演示数据一键注入（webui/demo_api.py） |
| POST /admin/api/demo/clear | 部门 Key | 演示数据清空 |
| GET /admin/api/demo/state | 部门 Key | 演示态查询 |
| POST /internal/detect | 部门 Key | `{text}` → findings+归一化（调试） |
| POST /internal/anonymize / /internal/restore | 部门 Key | `{text, session_id}` 双向（调试/对比屏） |
| GET /healthz | 无 | 存活 |
| GET /webui、/webui/files、/webui/demo、/webui/chat、/webui/dashboard | 无（演示模式） | 演示五页 |
| GET /webui/demo/materials/{filename}（+ /text） | 无 | 场景材料下载/取文（白名单外 404） |

安全注记（README 同款）：`/internal/*` 响应含还原原文，生产只应经 127.0.0.1 管理面或受控内网。

## 6. 端口拓扑（e2e/演示事实）

| 进程 | 端口 | 说明 |
|---|---|---|
| gateway | 9000 | config/app.yaml `listen`；env `ANONGW_LISTEN` 可覆盖 |
| mock 上游（互联网） | 8901 | `python -m gateway.mock_upstream --port 8901` |
| mock 上游（政务云） | 8902 | 同一 app 不同 argv |

mock 上游是一等公民：把收到的最后一条 user 消息原样回显进回答，并把收到的全文写内存
ring buffer（`/admin/text` 查询）——无 key 也能全链路验收。

部署侧已知端口（非契约、非六门依赖）：127.0.0.1:9004 = GPU 机真实上游 ssh 隧道
（T6.1 起，`ops/tunnel_gpu.sh` 常驻；上游池切换在 config/app.yaml upstreams，网关代码
零改动——「改 baseURL 即接入」）。

## 7. eval 指针

| eval | 覆盖 | 通过线 |
|---|---|---|
| `evals.t0_gateway` | 非流式链路 13 项：鉴权/校验/U1 缩小版/会话稳定/批量/密级拦截/审计 v0/internal 三端点/上游不可达 502 | `T0 GATEWAY NONSTREAM: 13/13`，exit 0（2026-09-29 实测 ≈197s） |
| `evals.t0_stream` | SSE 组帧（含字节级切块）/流式还原/工具缓冲/AI 标识 | `T0 GATEWAY STREAM: 11/11`，exit 0（2026-09-29 实测 ≈57s） |
| `evals.m10_e2e` | U1–U7 七用例 + bytes 级零明文断言（见 gates spec §2） | `e2e_smoke: 7 PASS / 0 FAIL / 0 DEFERRED` |
| 六道门指针 | 每门都回归 m10_e2e（gate_d0 ④ → gate_b5 ⑤）；门内断言逐批收紧见 gates spec §2 | — |
