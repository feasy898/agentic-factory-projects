# idle-research-1：ZCode CLI 能力与 GUI 内在机制研究（7 问）

> 执行方式：本报告是闲时任务 `offpeak-f888d6ff-664c-4eff-bacd-3b5f0167d56b`（票 2104536815074418688）的执行产物——即"通过 host RPC 派发闲时任务 → 服务端就绪后在本会话注入执行"的全流程实证。
> 证据标注：**[实测]**=本机真实请求/行为验证；**[代码]**=源码/反编译引用（附文件路径）；**[文档]**=官方文档；**[推断]**=基于以上推理，未单独验证。
> 前置成果复用：`../zcode-闲时任务与额度重置-研究报告.md`、`extracted/app/`（asar 解包）、`oss-src/`（开源源码快照）、`zctl/`（CLI 工具）。

---

## Q1 闲时任务的模型计价

### 闲时任务本身免费，5.3 与 Flash 在闲时价格相同（都是 0）

- **[代码]** `apps/zcode-cli/packages/core/src/tool/handlers/off-peak.ts` 工具描述原文：`"...later runs unattended in THIS session (with the full conversation history) when the server grants off-peak compute, **at no plan-quota cost**"`。
- **[代码]** GUI i18n（`renderer/assets/IntlProvider-BMWo3Clv.js`）：`offPeak.newTask.bannerTipText` = "本功能不消耗订阅用户套餐额度、本功能仅面向订阅用户开放"。
- 机制：闲时轮的模型请求走专用网关 `POST https://zcode.z.ai/api/v1/off-peak/anthropic/v1/messages`，带 `X-Off-Peak-Ticket-ID` 头凭票免费（provider 注册见 `resources/config/provider/zcode-builtin.json`：`account:bigmodel-offpeak-idle-plan` → baseUrl `.../api/v1/off-peak/anthropic`）。
- 因此 **GLM 5.3 与 GLM 5.3 Flash 在闲时任务里都没有价格差异**（都不扣额度）；它们只受同一套服务端准入约束：取号资格（`/ticket/availability`）、取号配额（错误码 3103）、排队与执行窗口（`ready_deadline`/`active_deadline`）。客户端允许的闲时模型就两个：`GLM-5.3`、`GLM-5.3-Flash`（zcode-builtin.json `builtinModelIds`）。

### 对比：正常派发 agent 的计价（走套餐 credit）

- **[文档]** docs.z.ai/devpack/overview：`Model credit usage = (Input×输入倍率 + Cached Input×缓存倍率 + Output×输出倍率) / 10,000`：

| 模型 | 输入倍率 | 缓存输入倍率 | 输出倍率 |
|---|---|---|---|
| GLM-5.3 | 6.9 | 1.7 | 24 |
| GLM-5.3-Flash | 2.3 | 0.56 | 8 |

  即 **Flash 各项都是 5.3 的 1/3**。另外 devpack 还有一个"闲时时段五折"概念（非周一至周五 14:00–18:00 SGT 按 50% credit 计费，9/25–10/7 活动期全天五折）——**注意这是 API 计费折扣，与 ZCode「闲时任务」（免费凭票）是两个不同机制，不要混淆**。

### 任务跑完后继续在该会话对话 → 正常计费

- **[实测]** 票过期/settled 后，闲时网关拒绝服务（我方实验票过期后请求 → HTTP 400 code=3001）；生产对过期票也不放行 → 续聊只能走普通 provider。
- **[代码]** 票中途过期的官方口径就是转正常：GUI 错误文案 `zcode.error.providerBusiness.3102` = "已超过单次最长运行时间，请创建新的闲时任务继续"。
- **[代码]** 闲时 provider 是**按轮绑定**的（`packages/desktop/src/host/offPeakDispatchPlan.ts`：dispatch 时构建 request auth 绑定 serverTicketId；轮结束 finalizeOffPeakRun 收尾）。

### 闲时会话中开工作流怎么计费？——设计上禁止

- **[代码]** `off-peak.ts` 的 `assertNotOffPeakTurn()`：闲时轮内 `Workflow` / `SendMessage` 工具直接 PermissionDenied，源码注释原文：**"SendMessage / Workflow 复用本函数——它们会绕开本轮 modelExecution 重新启动子 Agent 并落到用户套餐"**——这是防套利设计（防止用免费的闲时轮去孵化按套餐计费/或绕过限额的子任务）。
- 闲时轮内**前台**子代理允许（e2e 场景 `foreground-subagents` 专门验证），其模型调用随本轮走同一张闲时票（**[推断]**，高置信：e2e capture 场景统计的就是票网关收到的全部请求）；**后台**子代理被禁：`"Idle-time tasks do not support background agents. Run this agent in the foreground."`
- 任务结束后的会话里再开工作流 → 正常套餐计费。

---

## Q2 z.ai start plan 的 CLI 查询与"不同模型"问题

### 可以 CLI 实时查询剩余 token

- **[代码]** `packages/services/src/model-provider/zaiStartPlanBilling.ts`：`GET https://zcode.z.ai/api/v1/zcode-plan/billing/balance?app_version=<版本号>`，头 `Authorization: <oauth access_token 原文>`。响应结构：
  ```
  data.plans[]:    { user_plan_id, plan_id, name, status(active/expired), starts_at, ends_at }
  data.balances[]: { show_name, meter, unit_type, total_units, used_units,
                     remaining_units, available_units, expires_at,
                     capabilities: ["model:GLM-5.3-Flash", ...] }
  ```
  `remaining_units` 即剩余 token；`capabilities` 说明每个余额桶适用于哪些模型。客户端还做了服务端时间配对防过期桶误报（`normalizeStartPlanExpiry`）。
- **[实测]** 本机当前凭据只有 bigmodel 家族（`oauth:active_provider=bigmodel`），无 zai 登录态：oauth token 调它 → 401；zcode JWT → 400。接口存在、鉴权形态已确认，**待 zai start plan 到账后即可用 CLI 实测**（该接口按类名 `ZaiStartPlanBalance` 是 zai start-plan 专用）。
- 顺带：coding plan 的 credit 窗口查询另有社区成熟端点 `GET /api/monitor/usage/quota/limit`（用 coding plan API key），查的是 5 小时/周 credit 池，不是 start plan 的 token 桶。

### "start plan 和 coding plan 是不同模型/不同接口" —— 理解正确

- **[代码]** `resources/config/provider/zcode-builtin.json` 的 provider→端点映射（实测提取）：

| providerId | baseUrl |
|---|---|
| `account:bigmodel-individual/team-coding-plan` | `https://open.bigmodel.cn/api/anthropic`（直连） |
| `account:zai-individual/team-coding-plan` | `https://api.z.ai/api/anthropic`（直连） |
| `account:bigmodel-start-plan` / `account:zai-start-plan` | `https://zcode.z.ai/api/v1/zcode-plan/anthropic`（**ZCode 网关**） |
| `account:*-offpeak-idle-plan` | `https://zcode.z.ai/api/v1/off-peak/anthropic`（闲时网关） |

- 同一个 "GLM-5.3-Flash" 在内部是**不同 provider 条目下的不同模型实例**：不同凭证（各 plan 独立 api-key，如本机 `account-provider:coding-plan:account:bigmodel-individual-coding-plan:...:api-key`）、不同请求端点、不同的访问模式枚举（`access.mode: "start-plan" | "individual-coding-plan" | "team-coding-plan" | "off-peak"`）。这直接解释了 Q7：**3007 滑块风控就是专门挂在 start-plan 模式上的**（见下）。

---

## Q3 GUI 左下角"领取"能否 CLI 化

涉及两套系统：

1. **运营活动弹窗（marketing touch）——可完全 CLI 化 [代码]**
   - `GET /api/v1/marketing/touch?seq=<n>`：查询当前可参与的活动（弹窗内容来源）；
   - `POST /api/v1/marketing/touch/action`：body `{campaign_id, action_type: "confirm"|"cancel"}`，即"点击领取/关闭"；
   - 头：`X-Device-Mid`（本机设备 uuid）、`X-Client-Language`、`X-ZCode-App-Version`、`Authorization: Bearer <zcodejwttoken>`（token 为空时允许匿名）。
   - 源码：host 内 `createMarketingTouchService`（host/index.js，`parseMarketingTouchResponse` 配套）。纯 REST，无验证码。
2. **start plan 免费 token 领取——查询可 CLI，领取动作被人机校验挡住 [代码]**
   - 领取 = `claimManualPlan` → `POST /api/v1/zcode-plan/billing/claim`，body `{plan_id}`，**强制头 `X-Aliyun-Captcha-Verify-Param`**（可选 `X-Aliyun-Captcha-Verify-Region`）——滑块验证通过后才生成的凭证。
   - 结论：CLI 可以轮询"何时可领"（balance/preview/marketing touch），但**"直接领取"必须先解阿里云滑块**。务实方案：CLI 监听 + 通知，人点一下 GUI 领取；或 GUI 自动化（浏览器/Computer Use）过滑块。

---

## Q4 工作流/子代理会话的服务端识别与并发

- **[代码] 每个模型请求都带归因头**（runtime `createModelRequestAttributionHeaders`，zcode.cjs）：
  - `x-session-id`：主会话 `sess_` 前缀、子代理会话 `subagent_agent_` 前缀；
  - `x-query-id`、`x-zcode-trace-id`、`x-request-id`；
  - `x-zcode-session-type`: **`main` | `subagent` | `other`**（`WR={Main:"main",Other:"other",Subagent:"subagent"}`）。
  - → 官方服务端**完全可以区分**主会话/子代理/其他来源的每次模型调用。工作流派发的子代理同样带 `subagent` 标记。
- **[代码] 工作流会话没有专用 endpoint**：工作流在本机运行，其模型请求与普通会话走同一 provider 端点；区分只靠上面的归因头。
- **[代码] "工作流并发更高"是客户端行为，不是服务端特权**：工作流运行器的并发是**客户端信号量**（GUI 配置项，i18n `chat.toolCall.workflow.run.concurrency.label`=“并发数 {c}”），工作流可同时 fan-out 多个子代理请求；每个请求各自过服务端限流（超了返回 429/3105 "model concurrency saturated"，客户端退避重试）。普通单会话一次一个 turn，在途请求天然少。所以你的观察对——工作流期间**在途并发**确实高，但那是客户端并行发出的，不是服务端给了更高配额。

---

## Q5 跨会话引用工作流 ID 运行/续跑

- **[代码+产品文档] 可以，限同一项目（工作目录）**：
  - 工作流定义保存在项目 `.zcode/workflows/`（project scope）或全局 `~/.zcode/workflows`——B 会话可直接按**名字**运行 A 会话保存的工作流（`CreateWorkflow saved:{name,args}`）。
  - 运行实例（run）的 journal 按**项目**存储，跨会话共享：官方工具文档明示 ListWorkflowRuns "Includes runs started by other sessions — the run journal is per-project"。B 会话能看到并操作 A 会话的 run。
  - **续跑**：`ResumeWorkflowRun(run_id)` 恢复 stopped 的 run（原 run id 原地续，已完成步骤从 journal 重放不重复计费）；`AmendWorkflow(run_id, 修订脚本)` 可对 errored/completed/stopped/running 的任意 run 修订后续跑（旧 run 的已完成工作作为缓存导入）。errored 不能直接 resume（需先 amend 修脚本）；completed 不能 resume。
  - 换项目/目录则不可见（按工作目录做项目键）。源码：`apps/zcode-cli/packages/bootstrap/src/app/dynamic-workflow-run-{journal,lineage,replay,lifecycle,reconcile}.ts`。

---

## Q6 无头模式的能力边界与"直接同意"

- **[实测+文档] 无头会话可以：**
  - **启动子代理**：可以（AGENTS.md §七实测：headless 下需在 prompt 中明确指示用 Explore/general-purpose；子代理异步，用 `--resume <sessionId>` 收结果）。
  - **再启动另一个无头 zcode 会话**：可以——用 Bash 工具直接嵌套 `zcode --prompt ...`（本会话已多次这样做 zctl/子进程）。
  - **启动工作流**：可以，但 CLI 下**动态工作流默认被服务端下发的开关关闭**（`getDynamicWorkflowClientConfig` gate，`packages/services`+`dynamic-workflow-gate.ts` 装配层连技能发现都会剔除 dynamic-workflows 技能）。开启途径：`--enable-workflow` 启动参数，或（本机 GUI 曾被前人实施过）asar 二进制补丁强开（`resources/force-dwf-enable.patch.cjs` 把 gate 替换为 `Promise.resolve({enabled:!0})`）。
- **"首次创建工作流要确认"如何绕过**：那是权限系统（工具 `needsApproval`，经 `interaction/requestPermission` RPC 问 UI）。CLI 途径：`--mode yolo`（常规操作自动执行）/ `--auto`（全自动不中断）；headless 下没有 UI，确认类交互由权限模式直接裁决。OffPeakCreate 这类 medium 风险工具同样走这套（`offpeak.create` permission, needsApproval: true, off-peak.ts）。
- 边界：闲时轮（offPeakTurn）内上述统统受限——Workflow/SendMessage 被 deny、后台子代理被禁（Q1）。

---

## Q7 滑块验证码之谜

**结论：不是"并发太多"的通用风控，而是（主要）挂在 start-plan 通道上的定向风控 + 领取操作的强制校验。**

- **[代码] 集成**：桌面端内置**阿里云 CAPTCHA（SAF）**SDK（`captcha-open.aliyuncs.com`、`static-captcha-*.aliyuncs.com`、`o.alicdn.com/captcha-frontend/AliyunCaptcha.js`、设备指纹 `*.device.saf.aliyuncs.com`）。是否启用由服务端配置下发：`getCaptchaConfig()` ← `GET /api/v1/client/configs` 的 `configs.captcha`。
- **[代码] 触发点 1（必然）**：领取套餐 `POST /api/v1/zcode-plan/billing/claim` 强制要求 `X-Aliyun-Captcha-Verify-Param` 头 → 每次领取必弹滑块。
- **[代码] 触发点 2（风控，与你最近的体验吻合）**：模型请求被服务端以**业务码 3007** 拒绝（runtime `isCaptchaRejection`，错误码常量 `x4s="3007"`）时，runtime 弹出滑块交互（interaction reason 枚举 `"model-request" | "captcha-retry"`），用户通过后带 `x-aliyun-captcha-verify-param` 头**自动重试一次**（`CaptchaRequestRetry`，`extraAttempts=1`）。关键源码条件：
  ```js
  claim(...){
    return ... !this.request.refreshRuntimeHeadersBeforeAttempt
        || this.model.accountAccess?.mode !== "start-plan"   // ← 只对 start-plan 生效
        || !uOe(t)  // isCaptchaRejection
      ? !1 : (this.used = !0, ...)
  }
  ```
  即 **3007 滑块重试机制是 start-plan 专属**。你"时不时会有 z.ai start plan（活动 token）"，最近开发时若会话落在 start-plan 通道（或领取动作触发），就会频繁见到滑块——这是智谱对**免费额度反滥用**的风控（频率/指纹/环境综合判定，阈值在服务端，客户端只见"被拒→滑块→重试一次"）。
- **[代码] 旁证**：模型请求还可能携带 `x-client-sig` / `x-client-pow`（请求签名 / 工作量证明，见 runtime 日志脱敏清单 `RFs=new Set([...,"x-client-sig","x-client-pow","x-aliyun-captcha-verify-param"])`）——通道本身有签名与 PoW 机制。
- **缓解建议**：开发期间把 active 连接保持在 coding plan（避免 start-plan 通道）；领取操作集中处理；保持设备指纹/网络环境稳定（`X-Device-Mid` 持久化在本地状态文件，勿频繁清除 `~/.zcode` 状态）。

---

## 附：CLI 直接启动闲时会话（会话中追加的实验）

**"能否用 CLI 直接启动闲时会话"——两条路，一条全通，一条差最后一步：**

1. **经 host RPC 派发（推荐，已全通）[实测]**：`OffPeakCreate` 工具 / 协议方法 `offPeak/create` → GUI host 自动完成取号→排队→就绪→注入本会话执行。本报告就是这个方式跑出来的（创建时排队 #8，约 3 分钟就绪）。非官方 CLI headless（`zcode --prompt`）**不可用**此路（runtime 不含 offPeakServerClient/OffPeakTaskService，会报 "Off-peak task service is unavailable on this host"），必须有 GUI host 进程在线。
2. **纯协议裸调（zctl，协议操作全通、对话差最后一步）[实测]**：
   - ✅ `POST /off-peak/ticket` 取号（task_id `offpeak-<uuid>`）→ `queued #6`；
   - ✅ `POST /off-peak/ticket/status` 轮询 → `ready`（就绪窗口 `ready_deadline` ≈ 4.5 分钟）；
   - ✅ `POST /off-peak/ticket/{id}/settle` 结算（幂等，2xx+`settled_at`）；
   - ✅ `GET /off-peak/ticket/availability` 资格查询；
   - ❌ `POST /off-peak/anthropic/v1/messages` 直连对话：就绪窗口内多轮尝试（stream:true/false、`GLM-5.3-Flash`/`glm-5.3-flash`、补 `x-api-key`、补 `system`+`metadata.user_id`）均 **HTTP 400 code=3001 parameter error**。缺的是 GUI runtime 的完整 anthropic SDK 请求形态（工具数组、完整系统提示、可能的签名头）。**下一步**：对本机 GUI 的真实闲时流量做一次 MITM 抓包对比即可补齐（未做，留待下次）。
   - 意外收获：过期票调 messages 也返回 3001（e2e mock 契约是 3102）——生产网关错误码与 mock 不完全一致。
   - 实验残留：占用过 3 次取号（主任务 1 + 实验 2），实验票已全部 settle。

## 本次执行消耗记录

- 5 小时重置卡 ×1（用户指令；`reset/use` → `used:true`，留档 `zctl/logs/2026-09-28T11-39-22-906Z-reset-use.json`）；剩余 5h 卡 5 张、周卡 5 张（`reset status`，11:39 时点）。
- 闲时取号 3 次（1 主任务 + 2 实验，实验票已结算）；闲时对话 0 次成功（全部 3001，未产生模型调用）。
- 所有真实请求均已留档于 `zctl/logs/`（token 脱敏）。

## 证据索引

- 本机 asar 解包：`extracted/app/out/{host,main,scheduler,renderer,preload}`（host/index.js：marketing touch、claim+captcha、off-peak 客户端、billing）
- 开源快照：`oss-src/{off-peak.ts, offPeakDispatchPlan.ts, offPeakServerClient.ts, zaiStartPlanBilling.ts, bigmodelUsageQuotaProvider.ts, coding-plan-reset.ts, zcodeEndpoint.ts, credentialCipherProvider.ts, dynamic-workflow-gate.ts}`
- 内置 provider 注册表：`C:\Users\Administrator\AppData\Local\Programs\ZCode\resources\config\provider\zcode-builtin.json`
- 实测留档：`zctl/logs/*.json`（reset status/use、offpeak availability/take/status/settle/messages×4、billing balance 失败样本）
- 官方文档：docs.z.ai/devpack/overview（倍率表/五折/窗口）
