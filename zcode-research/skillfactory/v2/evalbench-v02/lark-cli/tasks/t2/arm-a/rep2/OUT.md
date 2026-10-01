# 「移动端 3.8 缺陷看板」多维表格搭建命令清单（lark-cli）

> 交付物：可按序直接执行的完整命令清单（含完整 fields 定义 JSON 与 12 条待写入记录 JSON）。
> 工具：官方 `lark-cli`（npm 包名 `@larksuite/cli`，命令入口 `lark-cli`），Base 域 shortcut 命令。
> 前提（任务给定）：lark-cli 已安装并完成认证（`lark-cli config init` + `lark-cli auth login` 已完成）。

**语法依据说明（不编造命令/flag）**：本清单全部命令与 flag 逐条核对自 lark-cli 自带文档与源码：`skills/lark-base/SKILL.md`、`skills/lark-base/references/lark-base-field-schema.md`、`skills/lark-base/references/lark-base-field-create.md`、`shortcuts/base/base_create.go`、`shortcuts/base/record_batch_create.go`、`shortcuts/base/record_ops.go`、`shortcuts/base/base_command_common.go`、`shortcuts/base/table_list.go`、`shortcuts/base/base_ops.go`、根 `README.md`（本机 `%TEMP%\lark-cli-ref` 下的一份完整源码/文档副本，2026-09-29 版）。执行环境若版本不同，可先用文档内置的自省命令核对：`lark-cli base --help`（SKILL.md frontmatter `cliHelp`）与 `lark-cli schema base.record_batch_create`（README「Schema Introspection」）。

**Shell 说明**：以下命令为 bash/Git Bash 风格（单引号包 JSON，`\` 续行）。Windows cmd.exe 下单引号不生效，请用步骤 3 的 `--json @./records.json` 文件变体（`@文件` 语法为 CLI 官方支持，见 SKILL.md「大 payload 可用脚本生成 json 后用 `--json @file.json`」及 `shortcuts/common/runner.go` 对 `@file` 的解析）。

---

## 步骤 0（可选）：核验登录状态

```bash
lark-cli auth status
```

**理由**：一条只读命令确认当前已认证身份与 granted scopes（README「Authentication」节文档命令），避免写操作执行到一半才发现 scope 缺失。

---

## 步骤 1：一次调用创建 Base + 首表「缺陷清单」+ 全部 6 个字段

```bash
lark-cli base +base-create \
  --name "移动端 3.8 缺陷看板" \
  --table-name "缺陷清单" \
  --time-zone Asia/Shanghai \
  --fields '[
  {"name":"缺陷标题","type":"text"},
  {"name":"严重度","type":"select","multiple":false,"options":[{"name":"P0"},{"name":"P1"},{"name":"P2"}]},
  {"name":"状态","type":"select","multiple":false,"options":[{"name":"待处理"},{"name":"处理中"},{"name":"已修复"}]},
  {"name":"负责人","type":"text"},
  {"name":"截止日期","type":"datetime","style":{"format":"yyyy-MM-dd"}},
  {"name":"修复指引","type":"text","style":{"type":"url"}}
]' \
  --as user
```

**理由**：官方推荐路径就是用一条 `+base-create --name <base-name> --table-name <table-name> --fields '<field-array>'` 同时创建 Base、首表和 fields（SKILL.md「写入 Base」节），避免分步建 Base、建表、逐个建字段带来的中间状态。

### fields 定义 JSON（与命令内完全一致，便于复制）

```json
[
  {"name":"缺陷标题","type":"text"},
  {"name":"严重度","type":"select","multiple":false,"options":[{"name":"P0"},{"name":"P1"},{"name":"P2"}]},
  {"name":"状态","type":"select","multiple":false,"options":[{"name":"待处理"},{"name":"处理中"},{"name":"已修复"}]},
  {"name":"负责人","type":"text"},
  {"name":"截止日期","type":"datetime","style":{"format":"yyyy-MM-dd"}},
  {"name":"修复指引","type":"text","style":{"type":"url"}}
]
```

### 字段类型映射依据（逐项）

| 目标字段 | 用的类型/属性 | 依据 |
|---|---|---|
| 缺陷标题 | `text` | Field Schema §3.1：text 最小写法 `{"type":"text","name":"标题"}`（默认 `style.type=plain`） |
| 严重度 | `select`，`multiple:false`，`options` 仅 `name` | Schema §3.3：单选/多选同为 `select`，用 `multiple` 区分（默认 false，此处显式写出）；`options[]` 结构 `{name, hue?, lightness?}`，仅 `name` 必填。**不要写 `single_select`**（§6 易错点原文） |
| 状态 | 同上，选项 待处理/处理中/已修复 | 同上 |
| 负责人 | `text`（按任务要求是文本，不是人员类型） | 任务明确「负责人：文本」；若日后要换成人员字段应为 `user`（Schema §3.6），本次遵任务不换 |
| 截止日期 | `datetime` + `style.format:"yyyy-MM-dd"` | CLI 字段模型**没有独立 `date` 类型**：§2 字段速查中手动日期字段只有 `datetime`（§6 原文「datetime 是手动日期字段」）；`style.format` 枚举含 `yyyy-MM-dd`（§3.4），只控制前端展示，满足「日期」列的呈现 |
| 修复指引 | `text` + `style.type:"url"` | Schema §3.1：超链接属于 `text`，用 `style.type:"url"` 区分；CellValue 可写裸 URL |

flag 依据：`--name`（必填）、`--folder-token`（可选，本例不用）、`--time-zone`（可选，"time zone, e.g. Asia/Shanghai"，显式固定时区让日期语义确定）、`--fields`（首表字段 JSON 数组，须与 `--table-name` 同用）、`--table-name`（首表名）——见 `shortcuts/base/base_create.go:33-46`；官方提示原文：`--fields` 的字段 JSON 形状与 `+field-create` 相同，"do not invent field properties"。

### 步骤 1 返回值的读取

成功响应为 `{"ok":true,...,"data":{"base":{...},"table":{...},"fields":[...]}}` 信封（README「JSON Output Contract」：成功走 stdout、`ok==true`、exit 0）：

- `base_token`：`data.base.base_token`（实现里同时兼容 `app_token` 键，见 `base_ops.go:160-167`）；
- 首表 `table_id`：`data.table` 对象内的 `table_id`（或 `id`）键（`base_ops.go:186-188`）。`--fields` 路径下 CLI 会新建自定义首表并删除平台默认首表（`base_ops.go:169-199`），所以最终只剩「缺陷清单」一张表。

---

## 步骤 2（兜底/核验）：获取 table_id

若步骤 1 返回已能读出 table_id，此步可跳过；否则执行：

```bash
lark-cli base +table-list --base-token <base_token> --as user
```

**理由**：`+table-list` 是官方定位 Table 的统一入口（SKILL.md「Table Block」节；`table_list.go`，flag 仅 `--base-token`），用于兜底拿到「缺陷清单」的 `table_id`，同时顺带确认首表已建成。

---

## 步骤 3：批量写入 12 条记录（单批一次提交）

```bash
lark-cli base +record-batch-create \
  --base-token <base_token> \
  --table-id <table_id> \
  --json '{"create_records":[
{"缺陷标题":"登录页验证码不刷新","严重度":["P0"],"状态":["处理中"],"负责人":"小何","截止日期":"2026-10-12 00:00","修复指引":"https://xx.feishu.cn/docx/FixCaptcha01"},
{"缺陷标题":"首页轮播图偶发白屏","严重度":["P1"],"状态":["待处理"],"负责人":"小郑","截止日期":"2026-10-15 00:00","修复指引":"https://xx.feishu.cn/docx/FixBanner02"},
{"缺陷标题":"消息推送延迟超 30 秒","严重度":["P1"],"状态":["处理中"],"负责人":"小周","截止日期":"2026-10-13 00:00","修复指引":"https://xx.feishu.cn/docx/FixPush03"},
{"缺陷标题":"订单金额四舍五入错误","严重度":["P0"],"状态":["已修复"],"负责人":"小何","截止日期":"2026-10-08 00:00","修复指引":"https://xx.feishu.cn/docx/FixAmount04"},
{"缺陷标题":"深色模式按钮不可见","严重度":["P2"],"状态":["待处理"],"负责人":"小王","截止日期":"2026-10-20 00:00","修复指引":"https://xx.feishu.cn/docx/FixDark05"},
{"缺陷标题":"表单可重复提交","严重度":["P1"],"状态":["处理中"],"负责人":"小周","截止日期":"2026-10-14 00:00","修复指引":"https://xx.feishu.cn/docx/FixForm06"},
{"缺陷标题":"头像上传裁剪失真","严重度":["P2"],"状态":["已修复"],"负责人":"小郑","截止日期":"2026-10-09 00:00","修复指引":"https://xx.feishu.cn/docx/FixAvatar07"},
{"缺陷标题":"iOS 下拉刷新卡顿","严重度":["P2"],"状态":["待处理"],"负责人":"小王","截止日期":"2026-10-18 00:00","修复指引":"https://xx.feishu.cn/docx/FixPull08"},
{"缺陷标题":"支付回调偶发超时","严重度":["P0"],"状态":["处理中"],"负责人":"小何","截止日期":"2026-10-11 00:00","修复指引":"https://xx.feishu.cn/docx/FixPay09"},
{"缺陷标题":"空状态文案错别字","严重度":["P2"],"状态":["已修复"],"负责人":"小郑","截止日期":"2026-10-07 00:00","修复指引":"https://xx.feishu.cn/docx/FixCopy10"},
{"缺陷标题":"分享链接签名过期","严重度":["P1"],"状态":["待处理"],"负责人":"小周","截止日期":"2026-10-16 00:00","修复指引":"https://xx.feishu.cn/docx/FixSign11"},
{"缺陷标题":"夜间模式耗电异常","严重度":["P1"],"状态":["处理中"],"负责人":"小王","截止日期":"2026-10-17 00:00","修复指引":"https://xx.feishu.cn/docx/FixBattery12"}
]}' \
  --as user
```

**理由**：`+record-batch-create` 是官方批量新增入口，一次调用写入全部 12 条（远低于"单批最多 200 条"上限），成功响应直接返回 `record_id_list` 作为写入凭证（SKILL.md「新增记录」节；`record_batch_create.go:19-30`）。

### 12 条记录 JSON（与命令内完全一致，便于复制/存文件）

```json
{"create_records":[
{"缺陷标题":"登录页验证码不刷新","严重度":["P0"],"状态":["处理中"],"负责人":"小何","截止日期":"2026-10-12 00:00","修复指引":"https://xx.feishu.cn/docx/FixCaptcha01"},
{"缺陷标题":"首页轮播图偶发白屏","严重度":["P1"],"状态":["待处理"],"负责人":"小郑","截止日期":"2026-10-15 00:00","修复指引":"https://xx.feishu.cn/docx/FixBanner02"},
{"缺陷标题":"消息推送延迟超 30 秒","严重度":["P1"],"状态":["处理中"],"负责人":"小周","截止日期":"2026-10-13 00:00","修复指引":"https://xx.feishu.cn/docx/FixPush03"},
{"缺陷标题":"订单金额四舍五入错误","严重度":["P0"],"状态":["已修复"],"负责人":"小何","截止日期":"2026-10-08 00:00","修复指引":"https://xx.feishu.cn/docx/FixAmount04"},
{"缺陷标题":"深色模式按钮不可见","严重度":["P2"],"状态":["待处理"],"负责人":"小王","截止日期":"2026-10-20 00:00","修复指引":"https://xx.feishu.cn/docx/FixDark05"},
{"缺陷标题":"表单可重复提交","严重度":["P1"],"状态":["处理中"],"负责人":"小周","截止日期":"2026-10-14 00:00","修复指引":"https://xx.feishu.cn/docx/FixForm06"},
{"缺陷标题":"头像上传裁剪失真","严重度":["P2"],"状态":["已修复"],"负责人":"小郑","截止日期":"2026-10-09 00:00","修复指引":"https://xx.feishu.cn/docx/FixAvatar07"},
{"缺陷标题":"iOS 下拉刷新卡顿","严重度":["P2"],"状态":["待处理"],"负责人":"小王","截止日期":"2026-10-18 00:00","修复指引":"https://xx.feishu.cn/docx/FixPull08"},
{"缺陷标题":"支付回调偶发超时","严重度":["P0"],"状态":["处理中"],"负责人":"小何","截止日期":"2026-10-11 00:00","修复指引":"https://xx.feishu.cn/docx/FixPay09"},
{"缺陷标题":"空状态文案错别字","严重度":["P2"],"状态":["已修复"],"负责人":"小郑","截止日期":"2026-10-07 00:00","修复指引":"https://xx.feishu.cn/docx/FixCopy10"},
{"缺陷标题":"分享链接签名过期","严重度":["P1"],"状态":["待处理"],"负责人":"小周","截止日期":"2026-10-16 00:00","修复指引":"https://xx.feishu.cn/docx/FixSign11"},
{"缺陷标题":"夜间模式耗电异常","严重度":["P1"],"状态":["处理中"],"负责人":"小王","截止日期":"2026-10-17 00:00","修复指引":"https://xx.feishu.cn/docx/FixBattery12"}
]}
```

### CellValue 写入格式规范对照（多维表格 CellValue 规范）

| 字段（类型） | 写入形态 | 示例 | 规范依据 |
|---|---|---|---|
| 缺陷标题（text） | 字符串 | `"登录页验证码不刷新"` | SKILL.md CellValue 示例：`text: string`；`record_ops.go:22`「text/phone/url -> "text"」 |
| 严重度（select 单选） | **字符串数组，最多 1 个元素** | `["P0"]` | SKILL.md：`select: array<string>`，"单选时数组最多一个值"；`record_ops.go:22`「select -> ["Todo"] … multiple=false 时数组只能含一个选项」；且必须是字段已有选项名 |
| 状态（select 单选） | 同上 | `["处理中"]` | 同上 |
| 负责人（text） | 字符串 | `"小何"` | 同 text；字段按任务定义为文本而非 `user`，故不写 `{"id":"ou_xxx"}` 形态 |
| 截止日期（datetime） | 不带时区的时间字符串 `"YYYY-MM-DD HH:mm"` | `"2026-10-12 00:00"` | SKILL.md CellValue 示例：`"不带时区时间": "2026-03-24 10:00"`（自动按 Base 时区解析）；`record_ops.go:22` happy path 同格式。**裸日期 `"2026-10-12"` 不在文档列出的 datetime 合法形态（带时区 ISO / 不带时区 "yyyy-MM-dd HH:mm" / Unix 毫秒）中，故补 `" 00:00"`**；字段展示格式为 `yyyy-MM-dd`，界面呈现即 2026-10-12 |
| 修复指引（text/url） | 裸 URL 字符串 | `"https://xx.feishu.cn/docx/FixCaptcha01"` | SKILL.md CellValue 示例：`text(url)`「裸 URL 或 Markdown link」均可，此处用裸 URL |

### 写入方式与单批规模合规性

- **单批规模**：CLI 硬性上限为单批最多 200 条（`record_batch_create.go:28`"Batch create supports max 200 records per call"；SKILL.md 同义原文），本次 12 条 → **单批一次提交即可，无需分批**。
- **串行写入**：同一 Table 的写入要串行；并发写同一表可能触发 `1254291` 并发冲突错误（SKILL.md「大 payload…」节原文）。本清单本身就是单调用，天然合规；后续若追加批次，请逐批串行执行。
- **禁止写系统/只读字段**：不要在 `create_records` 里提交 formula/lookup/created_at 等只读字段（`record_batch_create.go:27`），本 JSON 只含 6 个自建字段，合规。
- **成功判定**：看 stdout 信封 `ok == true` 与 exit code 0，**不要**用平台 `code == 0` 判断（README「JSON Output Contract」明确信封无 `code` 字段）；成功响应里拿 `record_id_list` 留档。
- **Windows cmd.exe 变体**：把上面的记录 JSON 原样存为 UTF-8 文件 `records.json` 后执行 `lark-cli base +record-batch-create --base-token <base_token> --table-id <table_id> --json @./records.json --as user`（`@相对路径` 为 CLI 官方 JSON 输入语法）。

---

## 步骤 4（可选，验收读取）：全部写入完成后统一读回一次

```bash
lark-cli base +record-list --base-token <base_token> --table-id <table_id> --format table --as user
```

**理由**：官方契约是"先完成本轮相关变更，再统一读取验收"（SKILL.md「Table Block」节），12 条远小于 `+record-list` 默认 limit 2000，一条命令即可完整读回核对行数与内容。

---

## 写入后的可见性注意事项（立即读取能否看到全部记录？）

**不一定能看到全部 12 条——这是预期行为，不代表写入失败。**

1. **写入走异步链路**：Base Table 下的更新大多经异步链路生效，"接口成功返回后立即读取可能暂时看不到最新状态"（SKILL.md 原文）。因此批量写入成功后的**秒级**读回可能短暂出现记录数少于 12 或个别行字段尚未就绪的情况。
2. **以写入成功响应为准**：官方契约要求"优先以写入成功响应作为操作结果"——`+record-batch-create` 返回的 `record_id_list`（应含 12 个 record_id）就是写入成功的权威凭证；官方 tip 进一步说明：批量创建后"使用返回的 record IDs 和你提交的行即可，除非需要服务端归一化的公式/查找值或故障诊断，不要立即 `+record-list` 同一张表"（`record_batch_create.go:29` 原文）。
3. **正确的验收姿势**：如任务需要核对，先完成全部写入（本方案只有一批），再统一执行一次步骤 4 的读取；若首次读回不足 12 条，稍候重试一次统一读取即可，不要逐条"写一条读一条"。
4. **前端可见性**：新 Base 创建成功后，响应中会带 Base URL/链接（`data.base` 内），在飞书客户端打开即可看到「移动端 3.8 缺陷看板」→「缺陷清单」；若以 bot 身份创建可能返回 `permission_grant` 字段（自动给当前用户授权，`base_ops.go:154-158`），本清单用 `--as user`（Base 域官方首选身份，SKILL.md「身份选择」节），一般无此问题。

---

## 失败处理速查

| 现象 | 处理 |
|---|---|
| 步骤 1 报 scope 不足 | 按错误 `hint` 补授权（`base:app:create`、`base:table:*` 等，见 `base_create.go:17-23`），必要时 `lark-cli auth login --scope <缺失scope>` |
| 步骤 3 报 1254291 并发冲突 | 说明有并行写同表；停止并行，串行重跑失败的批次（SKILL.md 原文） |
| 部分字段写不进去并出现 `ignored_fields` | 该字段是只读类型被静默过滤；本清单不含只读字段，出现即说明表结构被改动过，先 `+field-list` 核对 |
| 单条记录选项值报错 | 单选值必须是字段已有选项名（区分大小写），与步骤 1 `options[].name` 完全一致 |

---

## 依据清单（本机可复核位置）

- `%TEMP%\lark-cli-ref\README.md`：安装/auth 命令（L133-174）、三层命令体系、`--format`/输出信封契约（L244-260）、`schema` 自省（L278-286）。
- `%TEMP%\lark-cli-ref\skills\lark-base\SKILL.md`：`+base-create` 一次建 Base+首表+fields（L33）、`--as user` 优先（L17）、异步可见性契约（L79）、select/datetime 等 CellValue 规范（L152-175）、`+record-batch-create` 用法与 200 条上限/串行/`--json @file`（L179-191）、`+record-list`（L95）。
- `%TEMP%\lark-cli-ref\skills\lark-base\references\lark-base-field-schema.md`：字段类型 source of truth——text/url（§3.1）、select 单选用 `multiple`（§3.3，禁写 `single_select`）、datetime 为唯一手动日期类型与 `style.format` 枚举（§3.4、§6）。
- `%TEMP%\lark-cli-ref\skills\lark-base\references\lark-base-field-create.md`：字段 JSON 形状与 `options[] {name,hue?,lightness?}` 约定。
- `%TEMP%\lark-cli-ref\shortcuts\base\base_create.go`（L33-46）、`record_batch_create.go`（L19-30）、`record_ops.go`（L21-26）、`base_command_common.go`（L12-18）、`table_list.go`、`base_ops.go`（L95-124、L154-199）：各命令 flag 与返回结构的一手定义。

**诚实声明**：本机 PATH 与常见安装位置未检出 `lark-cli` 可执行文件（`command -v lark-cli` 为空；npm 全局、Program Files、盘符根目录、WSL 均未命中），故本清单基于该工具随仓库分发的官方文档与源码逐条核对产出，未在本机实际运行；执行前可按文首"语法依据说明"用 `--help`/`schema` 自省命令二次确认与所装版本一致。
