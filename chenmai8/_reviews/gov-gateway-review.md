这是一次只读的独立评审。我先读规划契约、门禁脚本和网关主链路，再对照 eval 断言找盲区。门禁和 e2e 脚本已经看过。接下来对照主链路、还原状态机和审计落库，核对原文会不会漏到上游或日志。磁盘上的网关和 e2e 与我刚读到的版本不一致，像是批次 1 正在写入。我按当前文件重新核对审计落库和扫描范围。结论：**需修后继续**。评审以已提交的 `HEAD`（`T0.6` 端到端 + `T1.4` 标签文档）为准。工作区里未提交的 T1.3（SQLite 审计队列、`session_store`）正在改 U5，不计入这轮绿灯。

身份证和手机号若在消息 `content` 字符串里，提交版会先换成占位符再转发；`content` 里的密级词会在转发前 403。还原结果只回给客户端，现有日志调用不写正文。绿灯没有证明 §9 的「人名零原值」和「审计零明文」。

## A. 安全核心

**1) 还原路径会不会把原文送上游或写进日志**

还原发生在上游返回之后，替换结果只进客户端响应。`chat.unhandled_error` / `audit.raw_pii_gate.tripped` 只记 `exc_type` 和 `kind`，没有 `exc_info`，异常文案也不含原值。

原文是在**出站组装**时漏出去的，不是还原分支写回去的：

- [high] `recognizers/rule/detect.py:91` — 规则层只认身份证、手机号、密级词，夹具里的「张三」没有任何 span，`mask()` 原样保留，U1/U4 会把它发给 mock。把 `PERSON` 纳入检测，并把 `U_TEXT` 里出现过的每个人名放进上游黑名单。
- [high] `gateway/pipeline.py:406` — `_out_payload` 除 `messages`/`stream` 外整包原样转发；`tools` 定义、历史消息里的 `tool_calls.arguments`、`function_call` 都不经过 `detect`。出站前对所有字符串叶节点做同一套 detect→mask，命中 `BLOCK_FLAG` 就整单拦截。
- [med] `gateway/pipeline.py:423` — 文本段在映射表里找不到时回退为原始 `content`；`type` 不是 `"text"` 的多模态段直接透传。缺段应失败关闭（400），禁止用原文填空。
- [high] `gateway/app.py:160` — `/internal/detect`、`/internal/anonymize`、`/internal/restore` 无鉴权，响应含 `Finding.raw` 和 `normalized`。这三个调试端点复用部门 Key，或只绑本地管理面。

**2) 「审计零明文」扫了什么**

- [high] `ops/e2e_smoke.py:137` — U5 把内存里的 `AuditEvent` 序列化后，只搜索 `RAW_VALUES` 里的证件号和电话；`PERSON = "张三"` 和密级词都不在清单里，而 `prompt_preview` 会留下未替换的人名和「机密★」。黑名单改为「本请求原文里出现过的全部敏感表面形式」，并断言预览等于脱敏后的全文（截断前）。
- [high] `audit/store.py:25` — 运行时硬闸只查 `prompt_preview + response_preview` 是否包含**归一化值**。表面形式（`139 0013 9000`）对不上归一化串时闸门放行；预览在 500 字处截断时，被切断的号码也不会整段命中。硬闸同时查 `raw` 表面形式，截断处若切中敏感串则拒写。
- [med] `ops/e2e_smoke.py:521` — 已提交的 U5 不读库文件。WAL、`-shm`、临时文件、stdout 都不在扫描范围内（提交版审计是内存 `deque`，本来就没有库文件）。未提交的 `assert_db_no_raw_pii` 会带上 `-wal`/`-shm`，但扫描清单仍是同一份 `RAW_VALUES`，且不扫 `session_map.db`（该库按设计保存归一化原值）。文件扫描落地时把会话库排除在审计库之外，并单独做权限与加密，不能把它算进「零明文」。

**3) 流式 remap**

`StreamRestorer.feed` 对「占位符被切成 1–2 个字符」的纯文本增量是对的：从 `〔` 起缓冲，凑齐 `〔标签·hex〕` 再查表。显式跨块和 300 次字符 fuzz 在 `evals/t0_stream.py`，**不在** `gate_d0` 的三项里。

- [med] `gateway/sse.py:245` — `finish_reason` 非空时先 `flush()` 并 `tools.finalize()`，再 `transform()` 本块。占位符后缀或工具参数最后一片若跟 `finish_reason` 在同一 chunk，前缀会被当成普通文本吐出，参数尾片被从 delta 删掉且不再发出。mock 的 finish 块是空 delta，所以 U2/U4 全绿。收尾改为先 `feed` 本块，再 `flush`。
- [med] `ops/e2e_smoke.py:391` — U2 的 20 次重放是 mock 按 1–7 **字符**随机切，不断言切点真的落在占位符上。UTF-8 多字节切断由 `iter_sse_data_lines` 按行缓冲后整行解码，只在 `t0_stream` 里测过。把 `t0_stream` 的字节切块用例并进 `gate_d0`，并固定至少一组「每个占位符在第 1、2 个字符处切开」的夹具。
- [low] `gateway/sse.py:71` — 每个 `data:` 行单独当一条 JSON。同一 SSE 事件里连续多行 `data:`（中间没有空行）不会按 SSE 规范拼成一个事件，解析失败时原样透传，绕过 `StreamRestorer`。按空行组帧，把同一事件的多行 `data:` 用换行拼起来再解析。

**4) 密级拦截是否到处生效**

`system` 与多轮里每条消息的 `content` 字符串走同一个 `_prepare`，流式和非流式共用，这块是一致的。`content` 里的「机密★」会 403，且 mock 计数不增加。

- [high] `gateway/pipeline.py:108` — 密级词若在 `tools[].function.description`、历史 `tool_calls.arguments`，或 `type != "text"` 的片段里，检测不到，也不会拦截，并随 `_out_payload` 原样出去。与第 1 条同一处修：所有出站字符串都进 `detect`。

## B. 假绿灯

断言是**夹具子串黑名单 + 占位符前缀计数**，不是原文与上游报文的全文 diff。

- [high] `gateway/mock_upstream.py:126` — `/admin/text` 只拼接 `last_user_content` 和 `tool_arguments`，ring 里保存的 `messages` 全文（system、更早轮次）不参与断言。对 `records[].messages` 的序列化字节做全文 diff：上游文本应等于「原文经占位符替换后的那一份」。
- [high] `ops/e2e_smoke.py:142` — U1 期望的占位符只有「〔身份证·」×2 和「〔手机号·」×3。人名不在 `RAW_VALUES` 里，所以上游带着「张三」也能 PASS。§9 写了「1 人名 → 零原值」。把人名计入期望占位符和黑名单。
- [med] `ops/e2e_smoke.py:177` — U6 在 `/v1/files/inspect` 返回 404 时记 `DEFERRED`，退出码仍为 0。「六用例全绿」包含一条未执行的用例。D0 报告里把 U6 标成未测；文件通道落地前不要把它算进通过数。
- [med] `ops/e2e_smoke.py:457` — U4 只覆盖「mock 把已脱敏的 user 文本回显进 arguments」。入站 `tool_calls` 自带明文 PII 或密级词的用例不存在。补一条历史 `assistant.tool_calls` 携带证件号和「机密★」的请求，断言 403 或上游字节里没有原值。

## C. 契约

§5 六件契约模型的字段集与 `evals/m0_infra.py` 的钉扎一致。`Finding.subtype` 来自 §5.1.1。`FileFinding.location`（`filechannel/models.py:37`）是 §5.5 示例之外的增补，符合「只增不改名」。

- [med] `evals/m0_infra.py:270` — 往返测试使用不含未知字段的示例 JSON。删掉 `extra="forbid"` 这 19 项仍然能过。给每个契约模型加一条带多余字段的 `model_validate`，必须拒绝。
- [low] `common/config.py:31` — `UpstreamCfg` / `ThresholdsCfg` / `AppConfig` 是 `extra="allow"`。配置模型会吞掉写错的键。配置模型改为 `extra="forbid"`，新键显式加字段。
- [low] `masking/mapper.py:32` — 碰撞升位实现是 8/10/12，§5.3.1 只写到 10 位。把第三档写进 §5，或在 10 位仍碰撞时直接失败。
- [low] `routing/engine.py:39` — `active` 先去掉 `whitelisted`，后面的 `WHITELIST_ONLY` 分支到不了。白名单命中要留在理由列表里再决定路由。

契约模型本身（`recognizers`、`routing`、`masking`、`audit`、`filechannel`、`gateway` 的 `models.py`）都设置了 `extra="forbid"`。

## D. Windows

- [med] `ops/e2e_smoke.py:149` — 8901/8902/9000 只做 `connect_ex`，占用就抛异常，不结束残留进程。mock 的 stdout/stderr 是 `DEVNULL`，崩溃没有输出。`terminate()` 在 Windows 上是直接 `TerminateProcess`，不处理子进程组。启动前按端口找到监听进程并退出，或把端口改成临时端口。
- [low] `ops/gate_d0.py:45` — 门脚本给子进程设了 `PYTHONUTF8=1`。直接跑 `e2e_smoke.py` 时，脚本自己没有 `reconfigure`，GBK 控制台打印中文摘要会 `UnicodeEncodeError`，通过变成崩溃。`e2e_smoke` 入口同样把 stdout/stderr 设成 UTF-8。
- [med] `masking/session_store.py:71`（未提交）— 已提交的 D0 没有 SQLite。T1.3 使用 WAL + `check_same_thread=False`，连接超时仍是默认 5 秒；e2e 在 Windows 上 `unlink` 仍被占用的 `audit.db`/`-wal`/`-shm` 会 `PermissionError`（中文路径下同样如此）。`_drop_db` 捕获共享违例并标明是残留进程；写失败不要只打 `exc_type` 然后 `task_done` 把事件丢掉（`audit/writer.py:166`）。

## E. 公开仓库卫生

标准档 `name_lint` 能绿，是因为豁免面够大。

- [med] `ops/name_lint.py:43` — `pyproject.toml`、`constraints.txt`、词表自身、`clone_oss.sh` 永远不扫；默认后缀不含 yaml/json。`pyproject.toml:26` 写着 `PyMuPDF`，`:47` 写着 `presidio-analyzer`，注释里还有 `pikepdf`、`faker`、`litellm`。补上 `ops/export_public.py`（仓库里还没有），导出目录用 `--strict` 再扫一遍，依赖清单由那一步替换。
- [low] `config/app.yaml:11` — 注释里的 `open.bigmodel.cn` 和 `glm-4-flash` 不在 `forbidden_names.txt`，严格档也扫不到。词表加上真实上游产品名，或删掉这条注释。

## F. 工程债 Top 5

1. [high] 出站只扫 `message.content` 的文本段，人名不识别。阻塞把当前绿灯当成批次 1–2 的安全基线。规则层可以开工，但不能再用现在的 U1 验收「人名已脱敏」。
2. [high] 审计零明文 = 夹具号码黑名单，预览里仍有人名和密级词。阻塞任何「零明文已证明」的对外说法，不阻塞写识别器。
3. [med] 流式 finish 块与 `flush` 的顺序反了。不阻塞批次 1。批次 2 接真实流式上游之前要修，并把 `t0_stream` 纳入门禁。
4. [med] U6 的 404 算通过，`/admin/text` 不看 `messages` 全文，U2 不证明切到了占位符，`extra="forbid"` 没有负例。不阻塞写功能，阻塞用门禁代替评审。
5. [med] 端口残留会让下一轮门禁直接失败；未提交的 SQLite 在 Windows 上会卡在文件锁；公开名靠 lint 豁免维持干净。不阻塞批次 1 的识别器，阻塞反复跑门和公开导出。

主路径（正文字符串里的身份证/手机号 → 占位符 → 上游；`content` 内密级词 → 403；还原不进日志）可以留着继续做规则层。在收紧 U1/U5 断言、并把 `tool_calls` / `tools` / 非 `text` 段纳入检测之前，不要把 `gate_d0` 的退出码 0 当作安全签收。
