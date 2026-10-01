# ZCode 闲时任务派单 & 额度重置 —— 代码级研究报告

> 研究日期：2026-09-28 · 方法：本机 GUI（ZCode Desktop 3.14.3）asar 解包逆向 + 官方开源仓库源码交叉验证 + 本机凭据解密冒烟测试。
> 按约定：**本次研究未向服务器发起任何业务请求**（未派单、未重置、未领券）；所有契约均来自静态代码分析。

---

## 0. TL;DR

| 问题 | 答案 |
|---|---|
| 三个项目什么关系 | 官方 GUI（`@zcode/desktop`，Electron）已**整体开源**于 [zai-org/ZCode](https://github.com/zai-org/ZCode)；其 agent runtime 打包为 `zcode.cjs`；非官方 CLI `kingsword09/zcode-cli`（npm: `zcode-app-cli`）就是把同一个 `zcode.cjs` 包了个 TUI 壳 |
| 「闲时任务」按钮怎么通信 | 渲染层 → host 进程 `OffPeakTaskService` → **`POST https://zcode.z.ai/api/v1/off-peak/ticket` 取号排队**，轮询 `/ticket/status`，就绪后**本地**跑 agent、模型请求走 `POST /api/v1/off-peak/anthropic/v1/messages`（免费闲时算力），完成后 `POST /ticket/{id}/settle` |
| 「重置 5 小时窗口」按钮 | **`POST https://zcode.z.ai/api/v1/coding-plan/reset/use`**，body `{idempotency_key, reset_type:"FIVE_HOUR"}` |
| 「充值 7 天限制」重置 | 同一 API，`reset_type:"WEEK"`（周额度重置，GUI 文案叫「周额度重置」） |
| 鉴权 | 双 token：`Authorization: Bearer <zcodejwttoken>` + `X-Bigmodel-Authorization: <oauth access_token>`（reset）；off-peak 用 `Authorization: Bearer <jwt>` + `x-coding-plan-api-key: <coding plan API key>` |
| token 在哪 | `C:\Users\Administrator\.zcode\v2\credentials.json`，**AES-256-GCM 加密存储**，密钥本地可推导（已验证可独立解密） |
| 能否 CLI 化 | 额度重置：**完全可以**（纯 HTTP）。闲时任务：协议级操作可以；**完整派单+自动执行依赖 GUI host 进程**（独立 CLI runtime 里没有这套服务），最简单的"派单"路径就是在本 GUI 会话里让我调 OffPeakCreate |
| CLI 产物 | `D:\workspace\zcode研究\zctl\zctl.mjs`（本文 §7），变更类命令默认 dry-run，`--yes` 才真发，`--record` 落盘完整请求/响应 |

---

## 1. 项目关系与架构

### 1.1 三个东西

| 名称 | 是什么 | 位置 |
|---|---|---|
| **ZCode GUI（桌面版）** | 官方 Electron 应用 `@zcode/desktop` v3.14.3，本机安装于 `C:\Users\Administrator\AppData\Local\Programs\ZCode\`。asar 已解包到 `D:\workspace\zcode研究\extracted\app\` | 本机 |
| **agent runtime（zcode.cjs）** | GUI 内置的 agent 运行时单文件 bundle（14.8MB），= 开源仓库 `apps/zcode-cli` 的构建产物 `packages/cli/dist/zcode.cjs`。我现在就是这个 runtime 的一个会话 | `...\ZCode\resources\glm\zcode.cjs` |
| **非官方 CLI** | `kingsword09/zcode-cli`（npm 包 `zcode-app-cli` 3.14.0-27），自述 "Unofficial terminal client for the ZCode agent runtime"：从固定版本 Desktop 提取 `zcode.cjs` + 兼容补丁 + pi-tui 终端壳，`--prompt` 即 headless | `D:\tools\npm-global\node_modules\zcode-app-cli\` |
| **官方开源仓库** | [zai-org/ZCode](https://github.com/zai-org/ZCode)（Apache-2.0，~6.9k star，与桌面版同版本 3.14.x）：桌面端、Web、后端服务、CLI runtime 全部源码 | GitHub |

关键认知：**GUI 与开源仓库源码一一对应**，本报告所有逆向结论均已用仓库未压缩源码核实（源码注释就是中文，契约字段逐一比对一致）。

### 1.2 GUI 进程拓扑（谁在跟服务器说话）

```
┌─ renderer（React UI，out/renderer/）
│    「创建闲时任务」按钮 / 「重置 5 小时额度·周额度」按钮
│        │  Electron IPC / 内部 service proxy
▼
├─ main（Electron 主进程，out/main/）── 也内置一份 usage-stats/reset 客户端（供 codingPlanWebview 用）
│        │
▼
├─ host（GUI 自带的宿主服务进程，out/host/index.js）
│    ├─ OffPeakTaskService + offPeakServerClient   ←── 闲时任务所有 HTTP 出口
│    └─ UsageStatsService（bigmodelUsageQuotaProvider）←── 额度重置所有 HTTP 出口
│        │
▼
├─ scheduler（out/scheduler/index.js）—— 票就绪(ready)后叫醒，在本地把任务当作 agent 会话跑起来
│
└─ agent runtime（resources/glm/zcode.cjs）—— 被 host 承载；它的 OffPeakCreate 工具通过
     JSON-RPC 方法名 "offPeak/create" 请求 host 侧服务（runtime 自己不会发 off-peak HTTP）
```

对应开源源码位置（逆向时的交叉验证文件，已下载到 `D:\workspace\zcode研究\oss-src\`）：

| 功能 | 仓库文件 |
|---|---|
| 闲时 HTTP 客户端 | `packages/services/src/session/offPeakServerClient.ts` |
| 闲时任务编排/本地仓库/轮询 | `packages/services/src/session/offPeakTaskService.ts` / `offPeakTaskRepo.ts` |
| 闲时凭证与请求头 | `packages/services/src/session/offPeakRuntimeModel.ts` |
| 闲时 e2e mock 网关（契约参考） | `packages/services/src/session/offPeakMockGateway.ts` |
| **额度重置全部 4 端点** | `packages/services/src/usage-stats/providers/bigmodelUsageQuotaProvider.ts` |
| 重置类型契约 | `packages/shared/src/coding-plan-reset.ts` |
| 端点解析/默认 origin | `packages/shared/src/zcodeEndpoint.ts` |
| 来源头 | `packages/shared/src/zcode-source-headers.ts` |
| 凭据加解密 | `packages/services/src/credential/providers/credentialCipherProvider.ts`（CLI 侧同款 `apps/zcode-cli/packages/adapters/src/auth/credential-cipher.ts`） |
| 重置按钮 UI | `packages/ui/src/components/coding-plan-quota-reset/*` |
| runtime 侧 OffPeakCreate 工具 | `apps/zcode-cli/packages/core/src/tool/handlers/off-peak.ts` |

---

## 2. 后端与鉴权总纲

- 生产 API origin：**`https://zcode.z.ai`**（测试环境 `https://zcode.chatglm.site`，可用环境变量 `ZCODE_ENV=test` / `ZCODE_BASE_URL` / `ZCODE_ENDPOINT_ORIGIN` 覆盖 —— `zcodeEndpoint.ts`）。
- 响应信封：`{code:number, msg?:string, data?:...}`，`code===0` 为成功（off-peak 接口兼容"裸体 JSON"与信封两种形态，客户端两种都收）。
- 所有请求带 `x-request-id`（客户端生成的 UUID；服务端错误响应会回带，用于对账）。
- 来源头（`zcode-source-headers.ts`）：`User-Agent: ZCode/<版本>`、`X-ZCode-App-Version`、`X-Platform: win32-x64`、`X-Os-Category: windows`、`X-Client-Language/Timezone`、`X-Device-Mid` 等（非敏感）。

### 2.1 凭据存储（本机实测）

文件：`C:\Users\Administrator\.zcode\v2\credentials.json`（GUI 登录后写入；CLI 与 GUI 共享）。

本机现有条目（只列 key，值均为 `enc:v1:` 加密串）：

```
zcodejwttoken                                                     ← zcode.z.ai 的登录 JWT
oauth:bigmodel:access_token / oauth:bigmodel:user_info            ← BigModel 家族 OAuth token
oauth:active_provider = "bigmodel"                                ← 当前激活家族
account-provider:coding-plan:account:bigmodel-individual-coding-plan:account:66321787135908909:api-key   ← 个人套餐 API key
account-provider:coding-plan:account:bigmodel-team-coding-plan:account:66321787135908909:api-key         ← 团队套餐 API key
（另有一条 key-06a03a296fc5de3e9a5773fc 的个人 api-key，历史遗留）
```

加密方案（`credentialCipherProvider.ts`，**完全可离线复现，已本机验证**）：

```
格式:   enc:v1:<iv>.<authTag>.<ciphertext>     （三段 base64url）
算法:   AES-256-GCM，IV 12B，AuthTag 16B
密钥:   SHA256(secret)
secret: 环境变量 ZCODE_CREDENTIAL_SECRET（若设置），
        否则 "zcode-credential-fallback:{platform}:{homedir}:{username}"
        本机 = "zcode-credential-fallback:win32:C:\Users\Administrator:Administrator"
```

> 冒烟测试已通过：解出的 `zcodejwttoken` 是标准 JWT（`eyJ...` 三段式），api-key 49 字符明文。**独立 Node 脚本即可解密，无需 GUI 进程。**

---

## 3. 功能一：闲时任务（off-peak / 闲时算力）

### 3.1 UI 入口与调用链

GUI 左侧栏「闲时任务」区（i18n key `offPeak.*`，「创建闲时任务」按钮）。创建表单提交：

```
renderer「创建闲时任务」
  → host JSON-RPC "offPeak/create"（参数: title, prompt, permissionMode 默认 "yolo",
     model, thoughtLevel, boundSessionId?）
  → OffPeakTaskService.createTask()
      1. 校验标题/模型选择
      2. 生成本地任务 id：`offpeak-<uuid>`
      3. client.takeTicket(taskId)  ──► POST /api/v1/off-peak/ticket
      4. 本地 SQLite 落库（serverTicketId、queuePosition、schedulable=state==="ready"）
      5. 启动轮询循环（首个间隔 0ms，之后按服务端 next_poll_after）
```

而 **runtime 的 OffPeakCreate 工具**（也就是我这个会话里的"闲时任务"派单能力）走的是同一条链：工具处理器 `requestClient("offPeak/create", {...})` → host 侧上面的流程。**这就是"GUI 上的派单入口"在协议层的真身。**

> ⚠️ 架构限制（代码证实）：`offPeakServerClient` / `OffPeakTaskService` 只编进桌面版 host（`packages/desktop` + `packages/services`），**不在 `zcode.cjs` runtime 里**。所以非官方 CLI headless（`zcode --prompt ...`）里调 OffPeakCreate 会得到 `"Off-peak task service is unavailable on this host"`。闲时任务的"完整体验"（排队→就绪→自动执行→结算）目前只能由 GUI host 驱动。

### 3.2 HTTP 契约（全部已用开源源码核实）

Base：`https://zcode.z.ai/api/v1/off-peak`

统一请求头：

```
Authorization: Bearer <zcodejwttoken 明文>
x-coding-plan-api-key: <套餐 API key>
x-request-id: <uuid>
（团队套餐时附加，header 名小写）: bigmodel-organization / bigmodel-project
（来源头见 §2）
```

| # | 端点 | 方法 | 请求体 | 响应（data 或裸体） |
|---|---|---|---|---|
| 1 | `/ticket/availability` | GET | — | `{can_take_number: bool, next_take_at?: 秒级时间戳}`（false 时必带 next_take_at） |
| 2 | `/ticket` | POST | `{task_id: "offpeak-<uuid>"}` | `{ticket_id, state, accepted?, position?, next_poll_after?(秒), queued_at?, ready_deadline?}` |
| 3 | `/ticket/status` | POST | `{ticket_ids: [...]}`（≤100） | `{next_poll_after?, tickets: [{ticket_id, state, position?, active_deadline?}]}` |
| 4 | `/ticket/{ticket_id}/settle` | POST | — | 幂等，重复/未知票一律 2xx，无意义 body |
| 5 | `/anthropic/v1/messages` | POST | Anthropic Messages 标准 body（SSE 流） | 模型流式响应。**必须带 `X-Off-Peak-Ticket-ID: <ticket_id>`**（外加同上鉴权头）。这是"闲时免费算力"通道：任务执行期间 agent 的每次模型调用都走它 |

- 票状态机：`queued → ready → active →(expired|settled)`，另有 `not_found`。`ready_deadline`/`active_deadline` 是服务端给的窗口期限。
- 轮询节奏（`offPeakTaskService`）：就绪前按 `next_poll_after` 轮询（客户端钳制在 5s–5min）；连续失败按 10s×2^n 退避。
- 任务结束（完成/取消/失败）→ settle 入队（outbox）→ 下个同步周期上报。
- 执行窗口到期（跑一半票过期）→ 自动 requeue 续跑，续跑提示词（runtime 内置英文）：`"Continue the previous task from where it left off. The run was interrupted..."`。

### 3.3 错误码（off-peak）

| code | 场景 | 客户端行为 |
|---|---|---|
| 3101 | 无资格（非订阅/未登录） | 永久失败 |
| 3102 | 票无效/过期/已结算（wrong off-peak ticket） | 票作废；运行中则 requeue |
| 3103 | 取号超限（额度用完） | UI 显示"额度已用完，可在 {time} 后再创建"（配合 availability 的 next_take_at） |
| 3105 | 未就绪/模型并发饱和 | HTTP 429 + `Retry-After`，退避重试 |
| 2007 | 上游依赖失败 | 常规错误 |

### 3.4 配额语义

GUI 文案：`offPeak.newTask.bannerTipText`="本功能不消耗订阅用户套餐额度、仅面向订阅用户开放"。即：**闲时任务的模型调用不扣套餐额度**（走 `/off-peak/anthropic/v1/messages` 网关），但**创建资格/频率受服务端限制**（availability + 3103）。

---

## 4. 功能二：额度重置（5 小时窗口 / 周额度=「充值 7 天限制」）

### 4.1 UI 入口与调用链

GUI 侧边栏套餐用量区 / 设置页（i18n `settings.usage.*`、`sidebar.usage.plan.*`）。对话框「可重置额度」（`codingPlan.quotaReset.dialog.title`）里两个按钮：

- 「重置 5 小时额度」（`codingPlan.quotaReset.dialog.fiveHour`，aria 文案 `重置 5 小时额度`）
- 「周额度重置」（`codingPlan.quotaReset.dialog.week`，aria 文案 `重置周额度`）——**即你说的"充值 7 天限制"的重置**（GLM Coding Plan 周额度每 7 天一个周期，官方 FAQ 称 Quota Reset Card / 重置卡：5 小时卡 + 每周卡，每周卡同时恢复 5 小时额度）

链路：`renderer 的 useCodingPlanQuotaResetUi（idempotencyKey = crypto.randomUUID()）→ UsageStatsService.useCodingPlanReset → POST /api/v1/coding-plan/reset/use`。

### 4.2 HTTP 契约（`bigmodelUsageQuotaProvider.ts` 原文核实）

Base：`https://zcode.z.ai/api/v1/coding-plan/reset`

统一请求头（`createCodingPlanResetHeaders`，与 off-peak **不同**）：

```
Authorization: Bearer <zcodejwttoken>          ← 注意 Bearer 前缀
X-Bigmodel-Authorization: <oauth:bigmodel:access_token 明文，无前缀>
Bigmodel-Target-Type: PERSONAL | TEAM
（TEAM 时）Bigmodel-Organization / Bigmodel-Project
content-type: application/json（POST 时）
x-request-id 等来源头
```

| # | 端点 | 方法 | 请求体 | 响应 data |
|---|---|---|---|---|
| 1 | `/status` | GET | — | `{available_five_hour_resets:[{expire_at}], available_week_resets:[{expire_at}], latest_five_hour_reset_history:{used_at}\|null, latest_week_reset_history:{used_at}\|null, has_unread_history:bool}` |
| 2 | `/opportunity` | POST | `{idempotency_key}` | 成功 `{granted:true}`；**code 3301**（未获发券）时 `{next_try_at}`；HTTP 429 = 请求过快（客户端写 30s 冷却） |
| 3 | **`/use`** | POST | `{idempotency_key, reset_type: "FIVE_HOUR" \| "WEEK"}` | `{used: true}` |
| 4 | `/history/read` | POST | —（标记重置历史已读） | 空 |

- `idempotency_key`：1–64 字符，GUI 用 `crypto.randomUUID()`；**幂等**——同 key 重发不会二次消耗。
- `reset_type` 线上值就是**大写** `"FIVE_HOUR"` / `"WEEK"`（`packages/shared/src/coding-plan-reset.ts:1` 原文：`export type CodingPlanResetType = "FIVE_HOUR" | "WEEK"`；请求体构造处直接透传 `reset_type: request.resetType`）。
- 超时 15s。信封 `{code,msg,data}`，`code!==0` 抛 `coding_plan_reset_api_error:<code>`。
- 语义：`/opportunity` 是**领取重置券**（服务端定期发券，券有 `expire_at`），`/use` 是**消耗一张券**执行重置。UI 徽标「{count} 次重置额度」即 `/status` 里两个数组的长度。
- 周期口径（官方 devpack 文档）：5 小时窗口自**开始消费**起算 5 小时；周额度 7 天。重置后周期重新起算。

### 4.3 相关但不同的端点（顺带记录）

- 套餐充值/账单：`/api/v1/zcode-plan/billing/{current,balance,preview,claim}`（claim=兑换码充值）。
- 用量监控（社区已逆向的公开口径）：`GET https://open.bigmodel.cn/api/monitor/usage/quota/limit`，`Authorization: <套餐 API key>`，`unit=3&&number=5` 即 5 小时窗、`unit=6` 周窗，`nextResetTime` 重置时间。GUI 的 entitlement 面板同源。

---

## 5. 「等你真要用时，记录真实请求」的方案

1. **zctl --record**（本次交付，§7）：真发请求时把完整请求（token 可选脱敏）+ 完整响应落盘为 JSON，位于 `zctl\logs\`。这是最直接的"记录对服务器的真实请求"。
2. GUI 自身日志兜底：host 进程日志在 `C:\Users\Administrator\.zcode\v2\logs\`（`off-peak take ticket ok task=... ticket=...`、`off-peak request rejected {bizCode...}` 等结构化日志都有；reset 报错带 `x-request-id`）。
3. 若要抓 GUI 按钮触发的包：GUI 走系统代理（undici/fetch 尊重 `HTTPS_PROXY`），可挂 mitmproxy 观测 —— 本次未做，需要时再上。

## 6. 红线/注意事项

- **凭据不入明文**：zctl 默认输出/落盘一律脱敏（`--record-raw` 才存原文且会打警告）；报告与日志永不写 token 原文。
- 幂等键复用可防误双击/重试双扣，重置类操作失败重试时**沿用同一个 idempotency_key**。
- `/use`、`/opportunity`、`/ticket`、`/settle` 都是**有真实副作用**的调用（消耗重置券/占用取号额度），zctl 默认 dry-run。
- 闲时任务裸调 `/ticket` 取号后若无人轮询执行，票会 `expired` 作废且可能占用一次取号额度 —— 完整派单请走 GUI（或直接让我在本会话调 OffPeakCreate）。

## 7. CLI 产物使用说明

位置：`D:\workspace\zcode研究\zctl\`

```
node zctl.mjs <command> [options]        （或 zctl.cmd / ./zctl）

命令：
  reset status                          GET  /coding-plan/reset/status（只读）
  reset opportunity [--key K]           POST /coding-plan/reset/opportunity（领券，--yes 才发）
  reset use --type FIVE_HOUR|WEEK       POST /coding-plan/reset/use（执行重置，--yes 才发）
  reset history-read                    POST /coding-plan/reset/history/read（--yes）
  offpeak availability                  GET  /off-peak/ticket/availability（只读）
  offpeak take --task-id ID|auto        POST /off-peak/ticket（取号，--yes）
  offpeak status --ids id1,id2          POST /off-peak/ticket/status（只读）
  offpeak settle --ticket ID            POST /off-peak/ticket/ID/settle（--yes）

通用：
  --dry-run   只打印将发送的请求（变更类命令的默认行为；显示完整 body 与脱敏头）
  --yes       真正发送（变更类必须显式给出）
  --record    把请求+响应 JSON 写入 zctl\logs\（token 默认脱敏；--record-raw 存原文）
  --team      使用团队套餐身份（offpeak 用 team api-key；reset 加 TEAM 头，需 --org/--project）
  --origin U  覆盖 API origin（默认 https://zcode.z.ai）
  --timeout ms（默认 15000）
```

凭据自动从 `~/.zcode/v2/credentials.json` 读取并解密（§2.1 方案）；本机已验证解密成功，但**尚未用真请求验证端到端**（遵守约定，等你指令）。

## 8. 证据与参考

- 本机解包源码：`D:\workspace\zcode研究\extracted\app\out\{host,main,scheduler,renderer}\`（host/index.js 内含全部两套客户端的压缩实现）
- 开源源码快照：`D:\workspace\zcode研究\oss-src\`（8 个关键文件）
- 仓库文件树索引：`D:\workspace\zcode研究\repo-tree.json`
- 官方仓库：https://github.com/zai-org/ZCode · 非官方 CLI：https://github.com/kingsword09/zcode-cli
- 套餐/重置卡官方说明：https://docs.z.ai/devpack/overview 、https://docs.z.ai/devpack/faq
- GUI 前人补丁痕迹：`resources\force-dwf-enable.patch.cjs`（此前会话对 asar 的二进制补丁，与本研究无关，顺带记录）
