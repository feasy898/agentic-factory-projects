# ASSET-DOC — larksuite/cli（飞书官方 CLI + Agent Skills）

> 刷新日期：2026-09-29（第二次核对）。本次实际访问了 GitHub 仓库主页、raw README.md、skills/ 目录页，
> 与上一版（`evalbench/lark-cli/ASSET-DOC.md`，同为 2026-09-29 抓取）逐项比对：**安装、认证、三层命令体系、
> 输出格式、分页、Agent Skills 清单、安全提示均无实质变更**。引用旧版中来自 raw SKILL.md / ERROR_CONTRACT.md
> 的章节时已注明"本次未重新抓取，沿用同日已验证抓取"。引号内文字为官方原文摘录；其余为整理性转述。

---

## 1. 资产概览

| 项 | 内容 |
|---|---|
| 仓库 | https://github.com/larksuite/cli |
| 名称 | `lark-cli`（npm 包 `@larksuite/cli`） |
| 官方定位 | "The official Lark/Feishu CLI tool, maintained by the larksuite team — built for humans and AI Agents" |
| 规模 | 覆盖 18 个业务域、200+ 命令；README 正文自述 "26 个 Agent Skills"（表格实际列 23 项，见 §6.1）；raw API 层覆盖 2500+ OpenAPI 端点 |
| 语言/许可 | Go 编写；MIT 许可 |
| 热度 | 2026-09-29 仓库主页显示约 17.5k stars / 1.4k forks（页面当日数值，未另行核验） |
| 安装载体 | npm（npx 一键安装）；Skills 经 `npx skills add` 分发 |

---

## 2. 安装与快速开始

环境要求：Node.js（`npm`/`npx`）；仅源码构建时另需 Go 1.23+ 与 Python 3。

### 2.1 安装（二选一）

```bash
# 方式一：npm（推荐）
npx @larksuite/cli@latest install

# 方式二：源码构建
git clone https://github.com/larksuite/cli.git
cd cli
make install
```

**安装 CLI SKILL（必需）**：

```bash
npx skills add larksuite/cli -y -g
```

### 2.2 快速开始（人类用户）

```bash
# 1. 配置应用凭证（仅需一次，交互式引导完成）
lark-cli config init

# 2. 登录授权（--recommend 自动选择常用权限）
lark-cli auth login --recommend

# 3. 开始使用
lark-cli calendar +agenda
```

### 2.3 快速开始（AI Agent）

1. **安装**：`npx @larksuite/cli@latest install`
2. **配置凭证**：后台运行 `lark-cli config init --new`，会输出授权 URL 交由用户在浏览器完成，命令随后自动退出
3. **登录**：同样后台运行 `lark-cli auth login --recommend`，提取授权 URL 发给用户
4. **验证**：`lark-cli auth status`

---

## 3. 认证

| 命令 | 说明 |
|---|---|
| `auth login` | OAuth 登录，支持交互式 TUI 选择或命令行参数指定 scope |
| `auth logout` | 登出并删除已存储的凭证 |
| `auth status` | 查看当前登录状态和已授权的 scope |
| `auth check` | 校验指定 scope（exit 0 = 有权限，1 = 缺失） |
| `auth scopes` | 列出应用的所有可用 scope |
| `auth list` | 列出所有已认证的用户 |

```bash
lark-cli auth login                                   # 交互式 TUI 登录
lark-cli auth login --domain calendar,task            # 按业务域过滤
lark-cli auth login --recommend                       # 推荐自动授权 scopes
lark-cli auth login --scope "calendar:calendar:read"  # 精确指定 scope
lark-cli auth login --domain calendar --no-wait       # Agent 模式：立即返回验证 URL，非阻塞
lark-cli auth login --device-code <DEVICE_CODE>       # 稍后恢复轮询
lark-cli calendar +agenda --as user                   # 身份切换为 user
lark-cli im +messages-send --as bot --chat-id "oc_xxx" --text "Hello"  # 身份切换为 bot
```

---

## 4. 三层命令体系

### 4.1 快捷命令 Shortcuts（`+` 前缀）

面向人和 AI，内置智能默认值、表格输出和 dry-run 预览。运行 `lark-cli <service> --help` 可查看某服务全部 shortcut。

```bash
lark-cli calendar +agenda
lark-cli im +messages-send --chat-id "oc_xxx" --text "Hello"
lark-cli docs +create --doc-format markdown --content $'<title>Weekly Report</title>\n# Progress\n- Completed feature X'   # 支持 --dry-run
```

### 4.2 API 命令

从 Lark OAPI 元数据自动生成，100+ 精选命令与平台端点 1:1 映射：

```bash
lark-cli calendar calendars list
lark-cli calendar events instance_view --params '{"calendar_id":"primary","start_time":"1700000000","end_time":"1700086400"}'
```

### 4.3 通用 API（Raw API）

直接调用任意飞书开放平台端点，覆盖 2500+ API：

```bash
lark-cli api GET /open-apis/calendar/v4/calendars
lark-cli api POST /open-apis/im/v1/messages --params '{"receive_id_type":"chat_id"}' --data '{"receive_id":"oc_xxx","msg_type":"text","content":"{\"text\":\"Hello\"}"}'
```

---

## 5. 全局 flags 与输出

### 5.1 输出格式（`--format`）

```bash
--format json      # 完整 JSON（默认）
--format pretty    # 人类友好格式
--format table     # 可读表格
--format ndjson    # 换行分隔 JSON（适合管道）
--format csv       # 逗号分隔值
```

### 5.2 JSON 输出契约

- **成功**：写 **stdout**、退出码 0：

```json
{ "ok": true, "identity": "user", "data": { "guid": "..." }, "meta": { "count": 1 } }
```

- **错误**：写 **stderr**、退出码非 0：

```json
{ "ok": false, "identity": "user", "error": { "type": "api", "subtype": "...", "code": 99991679, "message": "...", "hint": "..." } }
```

> 关键规则（原文）："判断成功应检查 `ok == true`（或退出码），不要用 `code == 0`"。成功信封**没有顶层 `code`/`msg` 字段**；`code` 仅出现在错误信封内，为上游 OpenAPI 的数字错误码。按旧 OpenAPI 惯例判断会把成功误判为失败——"封装写入类命令时尤其危险"。完整契约见仓库 `errs/ERROR_CONTRACT.md`（见 §7）。

### 5.3 分页

```bash
--page-all          # 自动翻页获取所有数据
--page-limit 5      # 最多获取 5 页
--page-delay 500    # 每页请求间隔 500ms
```

### 5.4 Dry Run

可能有副作用的命令可先预览请求：

```bash
lark-cli im +messages-send --chat-id oc_xxx --text "hello" --dry-run
```

### 5.5 Schema 自省

```bash
lark-cli schema                                  # 列出全部
lark-cli schema calendar.events.instance_view    # 查看某命令的参数/请求体/响应结构/支持身份/scopes
lark-cli schema im.messages.delete
```

---

## 6. Agent Skills 总览

### 6.1 README 官方描述表（中文 README 原文摘录）

README 正文自述 **26 个** Agent Skills，但描述表格实际列出 **23 项**（2026-09-29 两次抓取一致；正文数字与表格数量不一致，以仓库 `skills/` 实际目录为准）。官方描述如下：

| Skill | 说明 |
|---|---|
| `lark-shared` | 应用配置、认证登录、身份切换、权限管理、安全规则（所有其他 skill 自动加载） |
| `lark-calendar` | 日历日程（创建/更新）、议程查看、忙闲查询、时间建议、会议室查找、回复邀请 |
| `lark-im` | 发送/回复消息、群聊管理、消息搜索、上传下载图片与文件、表情回复 |
| `lark-doc` | 创建、读取、更新、搜索文档（基于 Markdown） |
| `lark-drive` | 上传、下载文件，管理权限与评论 |
| `lark-markdown` | 创建、读取、局部 patch、覆盖更新 Drive 中的原生 Markdown 文件 |
| `lark-sheets` | 创建、读取、写入、追加、查找、导出电子表格 |
| `lark-slides` | 创建和管理演示文稿、读取内容、新增或删除幻灯片页面 |
| `lark-base` | 多维表格、字段、记录、视图、仪表盘、数据聚合分析 |
| `lark-task` | 任务、任务清单、子任务、提醒、成员分配 |
| `lark-mail` | 浏览、搜索、阅读邮件，发送、回复、转发，草稿管理，监听新邮件 |
| `lark-contact` | 按姓名/邮箱/手机号搜索用户，获取用户信息 |
| `lark-wiki` | 知识空间、节点、文档 |
| `lark-event` | 实时事件订阅（WebSocket），支持正则路由与 Agent 友好格式 |
| `lark-meeting` | 查询进行中或历史会议、参会人和产物，分析逐字稿，管理妙记并提供会中协助 |
| `lark-whiteboard` | 画板/图表 DSL 渲染 |
| `lark-openapi-explorer` | 从官方文档探索底层 API |
| `lark-skill-maker` | 自定义 skill 创建框架 |
| `lark-attendance` | 查询个人考勤打卡记录 |
| `lark-approval` | 审批任务查询、同意/拒绝/转交、撤回与抄送审批实例 |
| `lark-workflow-meeting-summary` | 工作流：会议纪要汇总与结构化报告 |
| `lark-workflow-standup-report` | 工作流：日程待办摘要 |
| `lark-okr` | 查询、创建、更新 OKR，管理目标、关键结果、对齐、指标和进展记录 |

> 注：README 表格自述口径与 `skills/` 实际目录存在出入。2026-09-29 实测 `skills/` 目录含 **28 个子目录**（多出 `lark-apps`、`lark-minutes`、`lark-note`、`lark-vc`、`lark-vc-agent` 等未在 README 表格列出的目录）。以仓库实际目录为准。

### 6.2 skills/ 目录实测清单（2026-09-29 刷新时再次核对，28 个，与上一版一致）

lark-approval、lark-apps、lark-attendance、lark-base、lark-calendar、lark-contact、lark-doc、lark-drive、lark-event、lark-im、lark-mail、lark-markdown、lark-meeting、lark-minutes、lark-note、lark-okr、lark-openapi-explorer、lark-shared、lark-sheets、lark-skill-maker、lark-slides、lark-task、lark-vc、lark-vc-agent、lark-whiteboard、lark-wiki、lark-workflow-meeting-summary、lark-workflow-standup-report（共 28 个；`skills/` 根下无独立 SKILL.md，各 SKILL.md 位于各子目录内）。

---

## 7. 错误契约（errs/ERROR_CONTRACT.md 摘录）

> 本节为同日上一版抓取的 `errs/ERROR_CONTRACT.md` 内容，本次刷新未重新抓取该文件（README 主页对错误契约的表述与之一致，未发现矛盾）。

### 7.1 错误信封结构（stderr, JSON）

```json
{
  "ok": false,
  "identity": "user",
  "error": {
    "type": "authorization",
    "subtype": "missing_scope",
    "code": 99991679,
    "message": "...",
    "hint": "...",
    "log_id": "20260520-0a1b2c3d",
    "missing_scopes": ["calendar:event:create"]
  }
}
```

字段稳定性（原文）：
- `error.type` / `error.subtype`：**wire-stable**，"Renaming either is a breaking change"
- `error.code`：上游数字码，"`omitempty` and never carries CLI-internal meaning"
- `message` / `hint` / `log_id`：informational，**不可用于分支判断**
- `retryable`："`true` when present; omitted when `false`"
- `retry_after_seconds`：仅可重试的 `api/rate_limit` 与网络错误时由上游提供
- 各 subtype 有扩展字段：如 `missing_scopes`、`console_url`、`param`、`params`

### 7.2 error.type 九大类与退出码

| type | 含义 | 退出码 |
|---|---|---|
| `validation` | 用户输入不合法 | 2 |
| `authentication` | 无有效 token / 需登录 | 3 |
| `authorization` | token 缺 scope / 应用权限不足 | 3 |
| `config` | 本地配置缺失 | 3 |
| `network` | DNS、连接拒绝、超时、传输 | 4 |
| `api` | 服务端 Lark 错误（无特定桶） | 1 |
| `policy` | 内容安全 / 安全挑战 | 6 |
| `internal` | SDK 契约违反 / 解码失败 | 5 |
| `confirmation` | 高风险操作需 `--yes` | **10** |

### 7.3 退出码 10（高风险确认门禁）

命令属 "high-risk action needs `--yes`" 时产生 `type=confirmation`、退出码 10。**这是确认门禁而非错误**：消费者应停下→向用户确认（展示 `action`、`risk` 及关键参数）→取得显式同意后，把 `hint` 指出的确认 flag "追加到你原始 argv 的末尾"后重试；绝不静默加 flag 绕过。

### 7.4 Shell / AI 消费者建议（原文要点）

- 先用 `jq -e .` 防御性校验输出是 JSON 再解析
- 只对 wire-stable 字段分支："Branch only on `type`, `subtype`, `code`, `retryable`, `retry_after_seconds`, and declared extension fields"
- 未知字段前向兼容："ignore, don't fail"
- `authorization` → 读 `missing_scopes` 提示用户授权；`network` → 可安全重试；`internal` → 收集 `log_id` 报 issue
- 特殊路径：谓词命令（如 `auth check`）不写 stderr 信封；批量部分失败在 stdout 输出 `ok:false` 的完整结果，读 `data.summary` / `data.items[]`；`command_unavailable`（validation 子类）表示能力不在当前分发版中，不应视为认证失败或尝试绕过

---

## 8. 代表性 SKILL.md 详细内容

> 每个 skill 目录下含 `SKILL.md`（入口）+ `references/`（分场景参考文件）。SKILL.md 采用"场景路由"模式：入口文件给共性规则与触发索引，命中触发条件时才读对应 reference。
> 以下 5 个代表性 SKILL.md 摘要来自同日上一版对 raw 文件的实测抓取，本次刷新未重新逐一抓取（README 与 skills/ 目录核对未发现相关变更迹象）。

### 8.1 lark-shared（底座 skill，其余 skill 自动加载）

Frontmatter：`name: lark-shared`，`version: 1.1.0`，`metadata.requires.bins: ["lark-cli"]`。

**通用准则（5 条）**：
1. 调用前先确认用法——先读 reference 或跑 `--help`，不要盲猜 flag。
2. **身份决定操作对象**：`--as user` 代表用户本人，可访问其日历、云空间等个人资源；`--as bot` 只能访问 bot 自己的资源，bot 查用户资源会"返回空成功而非报错"。
3. **授权/配置 URL 必须配二维码**：输出 `verification_url`、`verification_uri_complete`、`console_url` 等字段时，须用 `lark-cli auth qrcode` 生成并展示，"URL 在前二维码在后"；优先生成 PNG（`--output`），仅用户明确要求才用 `--ascii`；"URL 原样转发——不编解码、不加标点、不重拼 query"。
4. **成功判定用 `ok == true`（或退出码 0），不要用 `code == 0`**（同 §5.2）。
5. 安全规则（见下）。

**安全规则（5 条）**：
1. 禁止将 appSecret、accessToken 等密钥明文输出到终端。
2. 写入/删除操作前必须确认用户意图。
3. 目标命令支持 `--dry-run` 时，先用其预览危险请求。
4. **退出码 10 是高风险确认门禁**（同 §7.3）。
5. **文件路径只接受相对路径**：`--file`、`--output`、`--output-dir`、`@file` 等仅接受 cwd 下相对路径，绝对路径会报 `unsafe file path`；数据输入优先走 stdin 以避免路径与转义问题。

**Reference 触发索引**：identity-and-permissions（身份/登录/scope）、output-contract（JSON 契约）、high-risk-approval（退出码 10）、config-init（首次配置）、update-notice（`_notice` 版本提示）。

### 8.2 lark-calendar（日历与会议室）

Frontmatter：`version: 1.0.0`。职责："管理日历日程和会议室"。不负责：过去视频会议记录（→ lark-meeting）、待办任务（→ lark-task）。

- **身份选择**：用户本人日程用 `--as user`（默认）；bot 自己创建/拥有的日程用 `--as bot`。人称映射：对话中"我"=登录用户，"你"=应用。
- **CRITICAL**：涉及预约日程/会议室、调整时间或查会议室时，第一步必须读 `references/lark-calendar-schedule-meeting.md`；仅编辑字段或增删参会人可跳过。
- **重复性日程**：操作前必须读 recurring 规范；范围未明确时需先确认「仅此次/全部/此次及后续」，不可默认。
- **时间规则**：周一为一周第一天；不可预约完全过去的时间（唯一例外：跨越当前时间的日程）；日期/时间戳转换必须调用系统工具，禁止依赖容器默认时区（常为 UTC，会导致 8 小时偏移）。

Shortcuts：`+agenda`（默认今天）、`+meeting`、`+create`、`+update`、`+delete`、`+freebusy`、`+room-find`、`+rsvp`、`+join-event`、`+suggestion`、`+transfer`、`+list-attendees`。

```bash
lark-cli calendar +agenda --as user
lark-cli calendar +search-event --query "周会" --start 2026-04-20 --end 2026-04-27 --attendee-ids "ou_user1,oc_chat1,omm_room1"
lark-cli calendar +delete --event-id <event_id> --notify=true
lark-cli calendar +freebusy --start ... --end ... --user-id ou_a,ou_b --type common_free --min-duration 30m
lark-cli calendar events share_info --calendar-id <calendar_id> --event-id <event_id>
```

限制：`--attendee-ids` 同类型内为 OR（并集）非 AND；`+get` 不含参会人/会议室（需 `+list-attendees`）；推荐时段必须用 `+suggestion`，`+freebusy` 只回答哪些区间空闲，`+room-find` 需确定时间块，禁止猜时间；会议室是日程的 resource 参与人，不能脱离日程单独预定；日程分享链接（`/calendar/share?token=`）≠ 会议链接（`/j/<number>`），禁止拼接 applink；description 统一按 Markdown 处理；写操作后直接反馈，不要二次查询确认；搜索用户/群必须 `--as user`。

### 8.3 lark-im（即时通讯）

Frontmatter：`version: 1.0.0`。前置要求（CRITICAL）："开始前 MUST 先用 Read 工具读取 [`../lark-shared/SKILL.md`]，其中包含认证、权限处理"。

核心概念：Message（`om_xxx`）、Chat（`oc_xxx`）、Thread、Reaction、Flag、Feed Shortcut、Feed Group（`ofg_xxx`，分 normal/rule 两类）。

关键规则：
- 链接：优先使用 CLI 返回的 `chat_app_link` / `message_app_link` / `share_link`；手动拼 AppLink 须用 `openChatId=`，禁用 `chatId=` 或 `lark://...`。
- 身份："The same API can succeed with one identity and fail with the other"。
- 消息增强：四个拉取快捷方式自动附加 `reactions` 与 `update_time`（`--no-reactions` 关闭）。
- 紧凑输出：部分列表命令支持 `--concise`，不可与 `--format`、`--json`、`--jq` 同时使用。
- 资源下载：默认关闭，存至 `./lark-im-resources/`；贴纸不可下载；**文件夹**不能直接下载，需先 `lark-cli im files folder --recursive --file-key <folder_key> ...` 展开。
- 卡片：发送/回复/更新卡片前 MUST 先读 `references/card/lark-im-card-create.md` 并按其工作流生成 payload，不可手写。
- 音频：`--audio` 仅支持 Opus（`.opus` / Ogg Opus）；mp3/wav 需先转换或改用 `--file` 发送。
- Feed Shortcut：仅 CHAT 型（`oc_xxx`）、仅 user 身份、create/remove 每次批量上限 10。
- 原生 API：调用前必须 `lark-cli schema im.<resource>.<method>` 查看参数结构，"不要猜测字段格式"。

身份限制（选摘）：`chats.create` 仅 bot；`merge_forward`/三种加急仅 bot 且 bot 须为消息发送者并在会话中；`+messages-edit` 仅 bot；`chat.join_requests.*`、`chat.user_setting.*`、feed 相关仅 user；`messages.patch` 消息须 14 天内发送且 content ≤ 30 KB；`chat.members.delete` 一次最多移除 50 用户或 5 机器人；`chat.managers` 群主才能操作、管理员上限 10（超大群 20）；`messages.read_users` 仅能查 7 天内自己发的消息。

Shortcut 一览：聊天 `+chat-create` `+chat-list` `+chat-search` `+chat-update` `+chat-members-list` `+chat-messages-list`；消息 `+messages-send` `+messages-reply` `+messages-edit` `+messages-mget` `+messages-search` `+messages-resources-download` `+messages-read-status` `+message-read-users`；线程 `+threads-messages-list`；Flag `+flag-create/-cancel/-list`；Feed `+feed-shortcut-create/-remove/-list`、`+feed-group-list` 等。

### 8.4 lark-doc（云文档）

Frontmatter：覆盖飞书云文档（Docx / Wiki）内容操作；触发条件："用户提供文档 URL/token（包括 doubao.com 的 /docx/、/wiki/）时使用；按 URL 路径/token 而非域名路由"；依赖 `lark-shared`。

- 核心原则："先判断场景，再读取该场景的参考文件；不要在任务开始时一次性读取全部参考文件。"
- 身份："文档操作推荐显式指定 `--as user`"。
- 本地文件引用：CWD 内用 `@./相对路径`，其他目录用 `@绝对路径`。
- 场景路由：读取/摘要→`+fetch`；从零创作→创建工作流（"简单任务不是跳过的理由"）；导入/空文档→`+create`；编辑/排版→`+update`。
- 辅助能力：`+script`（解析 URL/token、字数统计；"不支持 Markdown 输入"）；历史版本 `+history-list`/`+history-revert`/`+history-revert-status`；素材 `+media-insert`/`+media-preview`/`+media-download` 等；画板更新须"复用现有 token，禁止新建空白画板"。
- 范围外：Drive 文件级操作（导入导出、复制、权限）走 `lark-drive`；**明确禁止**用 `docs +fetch` + `docs +create` 重建正文来复制文档，应使用 `lark-cli drive files copy`；独立评论操作走 `lark-drive`。

### 8.5 lark-base（多维表格）

Frontmatter：`version: 1.2.23`。覆盖建表、字段、记录、视图、统计、公式/lookup、表单、仪表盘、BaseApp、workflow、角色权限等；触发条件：Base/多维表格/bitable、`/base/` 或 `/app/` 链接。

核心心智模型：Base = Block 资源树 + Base 级配置；Table 是核心数据 Block，Field/Record/View/Form 是 Table 内部对象不是 Block；BaseApp 用 Page/组件组织数据，"不是 Base 的别名"。操作优先 `--as user`。

进入前解析：URL 用 `base +url-resolve --url '<url>' --as user`；标题用 `base +title-resolve`；候选列表用 `drive +search --doc-types bitable`；不按名称猜测 app_token。

```bash
# 一次性建 Base+首表
lark-cli base +base-create --name <n> --table-name <t> --fields '<field-array>'
# Record 筛选导出
lark-cli base +record-list --base-token <bt> --table-id <tid> \
  --filter-json '{"logic":"and","conditions":[["Status","intersects",["Doing"]]]}' \
  --field-id Name --format ndjson --output ./records-preview.ndjson --as user
# 批量写入
lark-cli base +record-batch-create --json '{"create_records":[...]}'
```

CellValue 写入要点：text 可为裸 URL 或 Markdown link；单选/多选为数组；datetime 支持带时区 ISO、不带时区字符串（按 Base 时区）或毫秒时间戳；link 为 `[{id: recX}]`，清空用 `null` 或 `[]`；formula/lookup/auto_number 等只读，误写返回 `ignored_fields` 被静默过滤。

限制：Record 写入单批最多 200 条，同一 Table 串行写（并行可能触发 `1254291` 并发冲突）；`--limit` 缺省与最大均为 2000，只有 `has_more=false` 才是完整结果；日期筛选不支持 `>=`（需用前一天 23:59:59.999 表达）；少于 500 行建议本地 jq/Python 处理，大表用 `--filter-json` 下推；异步写入后立即读可能看不到最新状态；`+form-questions-delete` 高风险——默认删除底层 Field 及所有数据，保留需传 `--keep-field`；不支持 BaseApp 复制、Page 完整复制、页面图标、从 Workspace 移出资源；附件必须走 `+record-upload/download/remove-attachment` 专用命令。

---

## 9. 安全提示与限制（README 原文要点，本次刷新核对无变化）

- **风险声明**：本工具可被 AI Agent 调用，存在模型幻觉、执行不可控、提示词注入等固有风险；授权后 Agent 将以用户身份在授权范围内操作，可能导致敏感数据泄露或越权操作。使用即视为自愿承担相关所有风险与责任。
- **默认安全配置**：已默认启用多层安全保护，"强烈建议不要修改默认安全配置"。
- **机器人使用建议**：建议将该工具集成的机器人作为私人对话助手，勿拉入群聊或让他人与其交互。
- **风控信号**：CLI 默认向官方飞书/Lark HTTPS 精确域名随请求发送最小化风控信号（操作系统类型、硬件产品型号，如 Mac17,9），默认开启，可管理：

```bash
lark-cli config risk-control off      # 关闭（当前 workspace）
lark-cli config risk-control on       # 开启
lark-cli config risk-control default  # 恢复默认
```

- **范围限制**：飞书项目（Projects）由独立的 `meegle-cli` 提供，需单独安装。
- **企业扩展**：通过 `extension/` 包以 wrapper `main` 扩展，无需改 CLI 源码；支持集中凭证（数据库/Vault）、统一审计、受限命令面；官方文档 "embed-feishu-cli-in-agent"（开放平台文档 URL 加 `.md` 可得 Markdown 版）。
- **贡献**：重大变更建议先开 Issue；PR 前参见 `AGENTS.md`。

---

## 10. 抓取与刷新来源清单

### 本次刷新（2026-09-29，实际访问）

| # | 内容 | URL | 方式 |
|---|---|---|---|
| 1 | 仓库主页（概览、stars/forks、功能域总览） | https://github.com/larksuite/cli | WebFetch |
| 2 | README（英文 raw，完整用法核对：安装/认证/三层命令/输出/分页/skills 表格/安全/企业嵌入） | https://raw.githubusercontent.com/larksuite/cli/main/README.md | WebFetch raw |
| 3 | skills/ 目录页（28 个子目录逐一核对） | https://github.com/larksuite/cli/tree/main/skills | WebFetch |

### 沿用自同日上一版（evalbench/lark-cli/ASSET-DOC.md，2026-09-29 抓取，本次比对未发现变更迹象）

| # | 内容 | URL | 方式 |
|---|---|---|---|
| 4 | README（英文，完整用法首次抓取） | https://raw.githubusercontent.com/larksuite/cli/main/README.md | WebFetch raw |
| 5 | README.zh（中文，完整用法首次抓取） | https://raw.githubusercontent.com/larksuite/cli/main/README.zh.md | WebFetch raw |
| 6 | 仓库根目录清单（确认无根级 SKILL.md） | https://github.com/larksuite/cli/tree/main | WebFetch |
| 7 | lark-shared/SKILL.md | https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-shared/SKILL.md | WebFetch raw |
| 8 | lark-doc/SKILL.md | https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-doc/SKILL.md | WebFetch raw |
| 9 | lark-im/SKILL.md | https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-im/SKILL.md | WebFetch raw |
| 10 | lark-base/SKILL.md | https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-base/SKILL.md | WebFetch raw |
| 11 | lark-calendar/SKILL.md | https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-calendar/SKILL.md | WebFetch raw |
| 12 | errs/ERROR_CONTRACT.md | https://raw.githubusercontent.com/larksuite/cli/main/errs/ERROR_CONTRACT.md | WebFetch raw |

**未逐字核验项**：① star/fork 数取自抓取当日 GitHub 主页显示值；② 本次刷新未重新抓取各 SKILL.md 与 ERROR_CONTRACT.md 原文（§7、§8 沿用同日已验证抓取，README/skills 目录核对未见变更迹象）；③ skills/ 子目录内 references/ 文件未逐一抓取；④ README 中文版本次刷新未单独重新抓取（英文版核对一致）。
