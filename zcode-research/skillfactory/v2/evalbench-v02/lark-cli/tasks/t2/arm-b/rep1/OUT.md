# 「移动端 3.8 缺陷看板」建表 + 首表录入命令清单（lark-cli，可按序直接执行）

**目标**：一次性新建 Base「移动端 3.8 缺陷看板」与首表「缺陷清单」（6 个字段），随后把 12 条缺陷记录**一批**写入。
**前置条件**：用户本机已安装 lark-cli 并完成认证（任务前提，Step 0 仍复核一次登录态）。
**执行环境约定**：命令为 bash / Git-Bash 语法（JSON 载荷用单引号包裹，单引号字符串可跨行）；在 PowerShell/cmd 下执行需自行调整引号规则。

> **核实口径声明（如实）**：本清单撰写环境未安装 lark-cli（已实际运行 `command -v lark-cli` 与 npm 全局目录检查，均无结果），以下命令**未经本机实测**。全部子命令与 flag 逐一核对自官方仓库 [larksuite/cli](https://github.com/larksuite/cli) main 分支（2026-09-29 抓取）的 `skills/lark-base/SKILL.md` 与 `skills/lark-base/references/lark-base-field-schema.md`（依据清单见附录 C），无任何编造 flag。若本地 CLI 版本与 main 分支有差异，按「先 --help / schema 核实」约定先执行 Step 0 再继续。

---

## Step 0 · 执行前核实（约定动作）

```bash
lark-cli auth status
```
理由：复核登录态与已授权 scope（建表/写记录需要 base 相关写权限，token 失效时快速失败）。

```bash
lark-cli base +base-create --help
lark-cli schema base.+base-create
lark-cli base +record-batch-create --help
lark-cli schema base.+record-batch-create
```
理由：按「先 --help / schema 核实」约定，确认本机版本下两条命令存在、flag 名称一致（`--name` / `--table-name` / `--fields`；`--base-token` / `--table-id` / `--json`），并预览 `+base-create` 的响应结构（下一步要从响应里取 Base token 与 table_id，键名以 schema/实际响应为准）。

```text
写入意图确认：lark-shared 安全规则要求「写入操作前必须确认用户意图」。本任务用户已明确下达
「新建看板并写入下列 12 条记录」的指令，即视为意图已确认，无需再次询问。
```

---

## Step 1 · 一次性新建 Base + 首表「缺陷清单」+ 6 个字段

```bash
lark-cli base +base-create --name "移动端 3.8 缺陷看板" --table-name "缺陷清单" --as user --fields '[
  {"type": "text",     "name": "缺陷标题"},
  {"type": "select",   "name": "严重度", "multiple": false,
   "options": [{"name": "P0"}, {"name": "P1"}, {"name": "P2"}]},
  {"type": "select",   "name": "状态", "multiple": false,
   "options": [{"name": "待处理"}, {"name": "处理中"}, {"name": "已修复"}]},
  {"type": "text",     "name": "负责人"},
  {"type": "datetime", "name": "截止日期", "style": {"format": "yyyy-MM-dd"}},
  {"type": "text",     "name": "修复指引"}
]'
```
理由：官方对「新建一个 Base」的标准做法是**一条 `+base-create` 同时创建 Base、首表和 fields**（`--name <base-name> --table-name <table-name> --fields '<field-array>'`），避免分步建库建表再补字段；`--as user` 是官方推荐的用户身份（在用户自己的云空间建表）。

要点与合规说明：

- **字段类型名用官方小写枚举**：`text` / `select` / `datetime`（来自官方 Field Schema SSOT）。任务里的「日期」列在官方枚举中**没有独立的 `date` 类型串，对应 `datetime`**；`style.format` 只控制 Base 前端展示（这里按任务日期写法定为 `yyyy-MM-dd`），不影响读写。
- **两个单选字段**：`"multiple": false`（默认即 false，显式写出更清晰），`options` 选项只需 `name`（`hue`/`lightness` 可选）——P0/P1/P2 与 待处理/处理中/已修复 与任务给定选项**逐一一致**。
- **全部 6 列均为可写类型**（text×3、select×2、datetime×1），未把任何列误设为 `formula` / `lookup` / `auto_number` 等只读类型。
- **字段数组顺序 = 任务给定列序**（缺陷标题｜严重度｜状态｜负责人｜截止日期｜修复指引）。
- **成功判定**：stdout 返回 `ok == true` 且退出码 0（不要用 `code == 0` 判断）。
- **占位符来源**：成功后记下响应 `data` 中新建 Base 的 token 与首表的 table_id，下文记作 **`<base_token>`** 与 **`<table_id>`**（具体键名以本步实际响应 / Step 0 schema 预览为准，取自本步输出）。

---

## Step 2 · （可选）写入前预览

```bash
# 仅当 Step 0 的 --help 确认本命令支持 --dry-run 时执行；不支持则跳过本步（意图已在 Step 0 确认）
lark-cli base +record-batch-create --base-token <base_token> --table-id <table_id> --as user --dry-run --json '<Step 3 的完整 JSON>'
```
理由：README 全局说明快捷命令（`+` 前缀）支持 dry-run 预览请求，但 **lark-base 官方文档未逐条记载 `+record-batch-create` 的 `--dry-run`**，故本步以 Step 0 的 `--help` 输出为准——支持则先预览请求体，不支持则直接人工核对 Step 3 的 JSON 后执行。

---

## Step 3 · 一批写入 12 条记录

```bash
lark-cli base +record-batch-create \
  --base-token <base_token> \
  --table-id <table_id> \
  --as user \
  --json '{
  "create_records": [
    {"缺陷标题": "登录页验证码不刷新",   "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-12T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixCaptcha01"},
    {"缺陷标题": "首页轮播图偶发白屏",   "严重度": ["P1"], "状态": ["待处理"], "负责人": "小郑", "截止日期": "2026-10-15T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixBanner02"},
    {"缺陷标题": "消息推送延迟超 30 秒", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-13T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixPush03"},
    {"缺陷标题": "订单金额四舍五入错误", "严重度": ["P0"], "状态": ["已修复"], "负责人": "小何", "截止日期": "2026-10-08T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixAmount04"},
    {"缺陷标题": "深色模式按钮不可见",   "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-20T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixDark05"},
    {"缺陷标题": "表单可重复提交",       "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-14T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixForm06"},
    {"缺陷标题": "头像上传裁剪失真",     "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-09T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixAvatar07"},
    {"缺陷标题": "iOS 下拉刷新卡顿",     "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-18T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixPull08"},
    {"缺陷标题": "支付回调偶发超时",     "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-11T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixPay09"},
    {"缺陷标题": "空状态文案错别字",     "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-07T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixCopy10"},
    {"缺陷标题": "分享链接签名过期",     "严重度": ["P1"], "状态": ["待处理"], "负责人": "小周", "截止日期": "2026-10-16T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixSign11"},
    {"缺陷标题": "夜间模式耗电异常",     "严重度": ["P1"], "状态": ["处理中"], "负责人": "小王", "截止日期": "2026-10-17T00:00:00+08:00", "修复指引": "https://xx.feishu.cn/docx/FixBattery12"}
  ]
}'
```
理由：官方批量写入命令即 `+record-batch-create --base-token … --table-id … --json '<body>'`，payload 为对象包裹 `create_records` 数组、每条是「字段名 → CellValue」映射；12 条 ≤ 官方单批 200 条上限，**一批写完**，无需分批。

写入合规要点：

- **单批规模**：12 条，远低于官方「单批最多 200 条，超过后分批」的上限；本任务一批即可。
- **串行写入**：对同一 Table **串行**发起写入、不要并行或重复触发（例如脚本重试未做去重）——官方明确「同一 Table 串行写入」，并行可能触发 `1254291` 并发冲突错误。
- **单选格式**：CellValue 为**数组**形式且单选最多一个值（`"严重度": ["P0"]`）；值必须是字段**已有选项**——Step 1 已建齐全部选项，故合法。
- **日期格式**：官方接受「带时区 ISO / 不带时区字符串（按 Base 时区转换）/ Unix 毫秒时间戳」三种；本表 **12 条统一用带时区 ISO**（`"2026-10-12T00:00:00+08:00"`：纯日期取当日 00:00:00，显式 `+08:00` 固定东八区，避免依赖 Base 时区的歧义），全表格式一致。
- **链接格式**：`修复指引` 为文本字段，按官方 text(url) 规范直接写**裸 URL** 字符串（官方亦接受 Markdown link 写法，本清单统一裸 URL）。
- **只读字段**：payload 中未给任何只读字段赋值（本表无只读列）。
- **成功判定**：`ok == true` 且退出码 0；官方口径**成功时返回 `record_id_list`**——应包含 **12 个 record_id**，此即本步写入成功的权威凭证，记下备用。
- **大载荷备选**：若将来记录数多、命令行超长，官方支持把 JSON 存文件后用 `--json @file.json` 传入（lark-shared 规则：`@file` 只接受 cwd 下**相对路径**）。

---

## Step 4 · 可见性注意事项（写入后立即读取能否看到全部记录？）

**结论：不能假定立即读取能看到全部 12 条——这是正常现象，不代表写入失败。**

- 官方口径：**「Table 下的大多数更新通过异步链路生效，接口成功返回后立即读取可能暂时看不到最新状态」**，因此应「优先以写入成功响应作为操作结果」「先完成本轮相关变更，再统一读取验收」。
- 换言之：写入是否成功**以 Step 3 的 `ok == true` + `record_id_list`（12 个）为准**；刚写完立刻 `+record-list` 可能读到不足 12 条甚至 0 条，属异步生效延迟。
- 若安排回读验收，**前提**是：稍候片刻（而非紧随写入）再统一读取一次，例如：

```bash
lark-cli base +record-list --base-token <base_token> --table-id <table_id> --as user
```
理由：核对表中记录总数与内容（12 条、各字段值与任务一致）；注意**若读到条数 < 12，不要立即重发写入**——那会产生重复记录，稍后重读即可，仍以 Step 3 返回值为准。

- 补充：若任一命令返回**退出码 10**（`type=confirmation` 高风险确认门禁），正确处理是停下、向用户展示 `action`/`risk` 取得明确同意后，把 `--yes` **追加到原始 argv 末尾**重试；绝不静默加 flag 绕过。本清单两条写命令在官方 lark-base 文档中未记载强制确认门禁，如遇按此流程处理。

---

## 附录 A · CellValue 写入格式规范（本清单采用的口径，均出自官方文档）

| 字段 | 类型 | 写入格式（官方规范） | 本清单取值 |
|---|---|---|---|
| 缺陷标题 / 负责人 | text | string | 中文字符串 |
| 严重度 / 状态 | select（单选） | **数组** `array<string>`，单选最多 1 个值；必须是已有选项 | `["P0"]` / `["处理中"]` 等 |
| 截止日期 | datetime | 带时区 ISO ／ 不带时区串（按 Base 时区）／ Unix 毫秒时间戳，**三选一且全表一致** | 带时区 ISO `2026-10-12T00:00:00+08:00` |
| 修复指引 | text(url) | 裸 URL 或 Markdown link | 裸 URL |

## 附录 B · 12 条记录保真核对表（任务数据 ↔ 写入 JSON，逐条一致）

| # | 缺陷标题 | 严重度 | 状态 | 负责人 | 截止日期 | 修复指引 |
|---|---|---|---|---|---|---|
| 1 | 登录页验证码不刷新 | P0 | 处理中 | 小何 | 2026-10-12 | …/FixCaptcha01 |
| 2 | 首页轮播图偶发白屏 | P1 | 待处理 | 小郑 | 2026-10-15 | …/FixBanner02 |
| 3 | 消息推送延迟超 30 秒 | P1 | 处理中 | 小周 | 2026-10-13 | …/FixPush03 |
| 4 | 订单金额四舍五入错误 | P0 | 已修复 | 小何 | 2026-10-08 | …/FixAmount04 |
| 5 | 深色模式按钮不可见 | P2 | 待处理 | 小王 | 2026-10-20 | …/FixDark05 |
| 6 | 表单可重复提交 | P1 | 处理中 | 小周 | 2026-10-14 | …/FixForm06 |
| 7 | 头像上传裁剪失真 | P2 | 已修复 | 小郑 | 2026-10-09 | …/FixAvatar07 |
| 8 | iOS 下拉刷新卡顿 | P2 | 待处理 | 小王 | 2026-10-18 | …/FixPull08 |
| 9 | 支付回调偶发超时 | P0 | 处理中 | 小何 | 2026-10-11 | …/FixPay09 |
| 10 | 空状态文案错别字 | P2 | 已修复 | 小郑 | 2026-10-07 | …/FixCopy10 |
| 11 | 分享链接签名过期 | P1 | 待处理 | 小周 | 2026-10-16 | …/FixSign11 |
| 12 | 夜间模式耗电异常 | P1 | 处理中 | 小王 | 2026-10-17 | …/FixBattery12 |

（修复指引列缩写，完整 URL 形如 `https://xx.feishu.cn/docx/FixCaptcha01`，与 Step 3 JSON 逐字一致。）

## 附录 C · 用法核实依据（官方仓库 larksuite/cli main 分支，2026-09-29 抓取）

- `skills/lark-base/SKILL.md`：`+base-create --name … --table-name … --fields '<field-array>'` 一条命令同时建 Base、首表和 fields；`+record-batch-create --base-token <base_token> --table-id <table_id> --json '{"create_records":[…]}' --as user` 完整示例（含 `--json @file.json` 大载荷提示）；成功返回 `record_id_list`；「单批最多 200 条，超过后分批，同一 Table 串行写入」「并行可能触发 `1254291` 并发冲突错误」；「Table 下的大多数更新通过异步链路生效，接口成功返回后立即读取可能暂时看不到最新状态」；select 写入为数组、单选最多一个值、值须为已有选项；datetime 三种写入格式；text(url) 裸 URL 或 Markdown link。
- `skills/lark-base/references/lark-base-field-schema.md`（Field Schema SSOT）：合法类型枚举（`text`、`number`、`select`、`datetime`、…，无独立 `date` 串）；select 用 `multiple:false` + `options:[{name,…}]`（选项只需 `name`，静态 `options` 与动态 `dynamic_options_source` 二选一）；`datetime` 的 `style.format` 只控制前端展示、默认 `yyyy/MM/dd`；字段必填仅 `type` + `name`；避免遗留键 `field_name`/`property`/`ui_type`/数字枚举。
- 全局（README / lark-shared）：`--as user` 身份与「身份决定操作对象」；JSON 输出契约「成功看 `ok == true`（或退出码 0），不要用 `code == 0`」；退出码 10 = 高风险确认门禁、`--yes` 须在用户同意后追加到原始 argv 末尾；`@file`/`--output` 等只接受相对路径；`lark-cli schema <command>` 自省。

---

**冲突声明**：ASSET-DOC 及官方文档说明与任务要求如有冲突，以任务为准。本清单未发现实质冲突；仅两处口径对齐说明——① 任务「日期」列在官方类型枚举中对应 `datetime`（无独立 `date` 类型串），展示格式已按任务样式定为 `yyyy-MM-dd`；② 「单批规模」按官方上限 200 条执行，本任务 12 条一批合规。
