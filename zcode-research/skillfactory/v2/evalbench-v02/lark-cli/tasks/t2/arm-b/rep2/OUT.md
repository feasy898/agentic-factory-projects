# 「移动端 3.8 缺陷看板」lark-cli 建表 + 12 条记录写入命令清单

> 交付物：可直接按序执行的命令清单。目标 = 一次性新建 Base「移动端 3.8 缺陷看板」+ 首表「缺陷清单」（6 字段），并将 12 条缺陷记录一次性批量写入。
>
> **命令与 flag 无一编造**：全部逐字核对自官方仓库 `larksuite/cli`（2026-09-29 抓取 raw `main` 分支的 `skills/lark-base/SKILL.md` 与 `references/lark-base-field-schema.md`、`references/lark-base-field-create.md`，并浅克隆源码核对 shortcut 定义），出处对照见文末表格。
> 本清单按 bash 书写（官方文档默认形态）。Windows PowerShell/cmd 用户：把单引号 JSON 改用 `--json @records.json` 文件形态（见步骤 3 备选），`sleep 5` 改 `Start-Sleep -Seconds 5`。
>
> **成功判定约定（全程适用）**：每条命令以退出码 0 且输出信封 `ok == true` 为成功；**不要**用旧惯例 `code == 0` 判断——成功信封没有顶层 `code` 字段（ASSET-DOC §5.2）。错误信封写 stderr，只对 `error.type` / `error.subtype` / `error.code` 分支处理。

---

## 0. 可选预检：确认登录态

```bash
lark-cli auth status
```

**理由**：写操作前用官方命令确认当前登录与已授权 scope，避免建表中途才暴露权限缺口。

- 本清单需要的 scopes（源码核实）：`base:app:create`、`base:table:read`、`base:table:create`、`base:table:update`、`base:table:delete`（`+base-create`，user 身份）；`base:record:create`（写入）；`base:record:read`（验收读取）。
- 若后续命令报 `type=authorization`、`subtype=missing_scopes`：按错误信封 `missing_scopes` 字段，用 `lark-cli auth login --scope "<缺失的scope>"` 补授权后重试（官方错误契约建议做法，ASSET-DOC §7.4）。

---

## 1. 一次性创建 Base + 首表「缺陷清单」+ 全部 6 个字段

```bash
BASE_TOKEN=$(lark-cli base +base-create \
  --name "移动端 3.8 缺陷看板" \
  --table-name "缺陷清单" \
  --time-zone Asia/Shanghai \
  --fields '[
  {"name": "缺陷标题", "type": "text"},
  {"name": "严重度", "type": "select", "multiple": false, "options": [{"name": "P0", "hue": "Red"}, {"name": "P1", "hue": "Orange"}, {"name": "P2", "hue": "Gray"}]},
  {"name": "状态", "type": "select", "multiple": false, "options": [{"name": "待处理", "hue": "Gray"}, {"name": "处理中", "hue": "Blue"}, {"name": "已修复", "hue": "Green"}]},
  {"name": "负责人", "type": "text"},
  {"name": "截止日期", "type": "datetime", "style": {"format": "yyyy-MM-dd"}},
  {"name": "修复指引", "type": "text", "style": {"type": "url"}}
]' \
  --as user \
  | tee ./base-create-result.json \
  | jq -r '.data.base.base_token // .data.base.app_token')
```

**理由**：官方推荐的一次性建表路径——单条 `+base-create` 同时创建 Base、首表和全部 fields（SKILL.md：「创建新 Base 使用一次 +base-create --name --table-name --fields 同时创建 Base、首表和 fields」），`tee` 留档完整返回体，`jq` 提取 `base_token` 存入变量供后续命令使用。

执行说明：

- 带 `--fields` 时 CLI 的内部动作（源码 dry-run 描述核实）：创建 Base（含平台默认首表）→ 按 `--fields` 新建自定义首表「缺陷清单」→ 删除默认首表。命令返回成功即首表与 6 个字段均已就绪。
- `--time-zone Asia/Shanghai`：显式固定 Base 时区为东八区，使步骤 3 的不带时区日期字符串有确定语义。
- `hue` 仅是选项颜色（可选属性，取值均在官方枚举内：Red/Orange/Gray/Blue/Green），不需要可整段删去 `"hue": "...", `。
- 若本机无 `jq`：直接打开 `./base-create-result.json`，从 `data.base` 中复制 `base_token`（或 `app_token`）字段的值，手工替换后续命令里的 `$BASE_TOKEN`。
- 想先预览请求而不实际创建：在本条命令（`--as user` 之后）追加 `--dry-run` 再跑一次即可。

---

## 2. 批量写入 12 条记录（先 dry-run 预览，再正式执行）

### 2a. 预览写入请求（可选但建议）

```bash
lark-cli base +record-batch-create \
  --base-token "$BASE_TOKEN" \
  --table-id "缺陷清单" \
  --json '{"create_records": [
  {"缺陷标题": "登录页验证码不刷新", "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-12 00:00", "修复指引": "https://xx.feishu.cn/docx/FixCaptcha01"},
  {"缺陷标题": "首页轮播图偶发白屏", "严重度": ["P1"], "状态": ["待处理"], "负责人": "小郑", "截止日期": "2026-10-15 00:00", "修复指引": "https://xx.feishu.cn/docx/FixBanner02"},
  {"缺陷标题": "消息推送延迟超 30 秒", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-13 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPush03"},
  {"缺陷标题": "订单金额四舍五入错误", "严重度": ["P0"], "状态": ["已修复"], "负责人": "小何", "截止日期": "2026-10-08 00:00", "修复指引": "https://xx.feishu.cn/docx/FixAmount04"},
  {"缺陷标题": "深色模式按钮不可见", "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-20 00:00", "修复指引": "https://xx.feishu.cn/docx/FixDark05"},
  {"缺陷标题": "表单可重复提交", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-14 00:00", "修复指引": "https://xx.feishu.cn/docx/FixForm06"},
  {"缺陷标题": "头像上传裁剪失真", "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-09 00:00", "修复指引": "https://xx.feishu.cn/docx/FixAvatar07"},
  {"缺陷标题": "iOS 下拉刷新卡顿", "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-18 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPull08"},
  {"缺陷标题": "支付回调偶发超时", "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-11 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPay09"},
  {"缺陷标题": "空状态文案错别字", "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-07 00:00", "修复指引": "https://xx.feishu.cn/docx/FixCopy10"},
  {"缺陷标题": "分享链接签名过期", "严重度": ["P1"], "状态": ["待处理"], "负责人": "小周", "截止日期": "2026-10-16 00:00", "修复指引": "https://xx.feishu.cn/docx/FixSign11"},
  {"缺陷标题": "夜间模式耗电异常", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小王", "截止日期": "2026-10-17 00:00", "修复指引": "https://xx.feishu.cn/docx/FixBattery12"}
]}' \
  --as user \
  --dry-run
```

**理由**：`+record-batch-create` 支持 `--dry-run`（源码定义 DryRun），先无副作用地预览将要提交的请求体，符合 lark-shared 安全规则「目标命令支持 --dry-run 时，先用其预览危险请求」。

### 2b. 正式写入（`--json` 参数与 2a 完全相同，去掉 `--dry-run`）

```bash
lark-cli base +record-batch-create \
  --base-token "$BASE_TOKEN" \
  --table-id "缺陷清单" \
  --json '{"create_records": [
  {"缺陷标题": "登录页验证码不刷新", "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-12 00:00", "修复指引": "https://xx.feishu.cn/docx/FixCaptcha01"},
  {"缺陷标题": "首页轮播图偶发白屏", "严重度": ["P1"], "状态": ["待处理"], "负责人": "小郑", "截止日期": "2026-10-15 00:00", "修复指引": "https://xx.feishu.cn/docx/FixBanner02"},
  {"缺陷标题": "消息推送延迟超 30 秒", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-13 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPush03"},
  {"缺陷标题": "订单金额四舍五入错误", "严重度": ["P0"], "状态": ["已修复"], "负责人": "小何", "截止日期": "2026-10-08 00:00", "修复指引": "https://xx.feishu.cn/docx/FixAmount04"},
  {"缺陷标题": "深色模式按钮不可见", "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-20 00:00", "修复指引": "https://xx.feishu.cn/docx/FixDark05"},
  {"缺陷标题": "表单可重复提交", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-14 00:00", "修复指引": "https://xx.feishu.cn/docx/FixForm06"},
  {"缺陷标题": "头像上传裁剪失真", "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-09 00:00", "修复指引": "https://xx.feishu.cn/docx/FixAvatar07"},
  {"缺陷标题": "iOS 下拉刷新卡顿", "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-18 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPull08"},
  {"缺陷标题": "支付回调偶发超时", "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-11 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPay09"},
  {"缺陷标题": "空状态文案错别字", "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-07 00:00", "修复指引": "https://xx.feishu.cn/docx/FixCopy10"},
  {"缺陷标题": "分享链接签名过期", "严重度": ["P1"], "状态": ["待处理"], "负责人": "小周", "截止日期": "2026-10-16 00:00", "修复指引": "https://xx.feishu.cn/docx/FixSign11"},
  {"缺陷标题": "夜间模式耗电异常", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小王", "截止日期": "2026-10-17 00:00", "修复指引": "https://xx.feishu.cn/docx/FixBattery12"}
]}' \
  --as user
```

**理由**：12 条 ≤ 单批 200 条上限（源码：「Batch create supports max 200 records per call」），一次批量调用即合规且天然串行（规避同表并行写触发 `1254291` 并发冲突）；成功响应含 `record_id_list`（12 个记录 ID），它是「写入完成」的第一判定依据。

**备选写法（Windows cmd/PowerShell 推荐）**：把上面 `--json` 引号内的 JSON 原样存为**当前目录**下 `records.json`（UTF-8），然后改用文件形态（`@file` 仅接受 cwd 相对路径，这是官方安全规则）：

```bash
lark-cli base +record-batch-create --base-token "$BASE_TOKEN" --table-id "缺陷清单" --json @records.json --as user
```

成功标准：退出码 0、信封 `ok == true`，`data` 中 `record_id_list` 恰有 12 个记录 ID。**把这 12 个 ID 保存下来**，它是本轮写入的权威凭证（原因见「可见性注意事项」）。

---

## 3. （可选）终态验收：统一读取一次核对条数

```bash
sleep 5; lark-cli base +record-list \
  --base-token "$BASE_TOKEN" \
  --table-id "缺陷清单" \
  --limit 50 \
  --as user
```

**理由**：写入链路异步生效，稍候数秒统一读取一次做终态确认——stdout 摘要中 `records_count` 应为 12 且 `has_more` 为 `false`（`--limit 50` 在 json 格式 1–200 范围内，覆盖 12 条绰绰有余）。

---

## fields 定义 JSON（步骤 1 `--fields` 参数内容，与命令内联完全一致）

```json
[
  {"name": "缺陷标题", "type": "text"},
  {"name": "严重度", "type": "select", "multiple": false, "options": [{"name": "P0", "hue": "Red"}, {"name": "P1", "hue": "Orange"}, {"name": "P2", "hue": "Gray"}]},
  {"name": "状态", "type": "select", "multiple": false, "options": [{"name": "待处理", "hue": "Gray"}, {"name": "处理中", "hue": "Blue"}, {"name": "已修复", "hue": "Green"}]},
  {"name": "负责人", "type": "text"},
  {"name": "截止日期", "type": "datetime", "style": {"format": "yyyy-MM-dd"}},
  {"name": "修复指引", "type": "text", "style": {"type": "url"}}
]
```

形状依据（官方 Field Schema）：字段对象统一 `type` + `name` + 类型特有字段；**禁止**旧结构 `field_name` / `property` / `ui_type` / 数字枚举 `type`；单选与多选同为 `type:"select"`，用 `multiple` 区分（不写 `single_select`）；`options[]` 结构为 `{name, hue?, lightness?}`，`hue`/`lightness` 缺省合法；`style.format` 仅控制前端展示。修复指引为存链接的文本列，用 text 的 `url` 样式（列内容仍是文本，前端渲染为可点链接）；若坚持纯文本样式，删去 `,"style": {"type": "url"}` 即可。

> 以上两段 JSON 已在制单机器上用 `node` 的 `JSON.parse` 实测校验：fields 6 项、create_records 12 项、键序与任务列序（缺陷标题｜严重度｜状态｜负责人｜截止日期｜修复指引）一致、单选均为单元素数组、日期均为 `YYYY-MM-DD 00:00`、URL 全部合法，问题数 0。

## 待写入记录 JSON（步骤 2 `--json` 参数内容，即 `records.json` 的文件内容）

```json
{"create_records": [
  {"缺陷标题": "登录页验证码不刷新", "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-12 00:00", "修复指引": "https://xx.feishu.cn/docx/FixCaptcha01"},
  {"缺陷标题": "首页轮播图偶发白屏", "严重度": ["P1"], "状态": ["待处理"], "负责人": "小郑", "截止日期": "2026-10-15 00:00", "修复指引": "https://xx.feishu.cn/docx/FixBanner02"},
  {"缺陷标题": "消息推送延迟超 30 秒", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-13 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPush03"},
  {"缺陷标题": "订单金额四舍五入错误", "严重度": ["P0"], "状态": ["已修复"], "负责人": "小何", "截止日期": "2026-10-08 00:00", "修复指引": "https://xx.feishu.cn/docx/FixAmount04"},
  {"缺陷标题": "深色模式按钮不可见", "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-20 00:00", "修复指引": "https://xx.feishu.cn/docx/FixDark05"},
  {"缺陷标题": "表单可重复提交", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-14 00:00", "修复指引": "https://xx.feishu.cn/docx/FixForm06"},
  {"缺陷标题": "头像上传裁剪失真", "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-09 00:00", "修复指引": "https://xx.feishu.cn/docx/FixAvatar07"},
  {"缺陷标题": "iOS 下拉刷新卡顿", "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-18 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPull08"},
  {"缺陷标题": "支付回调偶发超时", "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-11 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPay09"},
  {"缺陷标题": "空状态文案错别字", "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-07 00:00", "修复指引": "https://xx.feishu.cn/docx/FixCopy10"},
  {"缺陷标题": "分享链接签名过期", "严重度": ["P1"], "状态": ["待处理"], "负责人": "小周", "截止日期": "2026-10-16 00:00", "修复指引": "https://xx.feishu.cn/docx/FixSign11"},
  {"缺陷标题": "夜间模式耗电异常", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小王", "截止日期": "2026-10-17 00:00", "修复指引": "https://xx.feishu.cn/docx/FixBattery12"}
]}
```

## 12 条数据核对表（任务原文列序：缺陷标题｜严重度｜状态｜负责人｜截止日期｜修复指引）

| # | 缺陷标题 | 严重度 | 状态 | 负责人 | 截止日期 | 修复指引 |
|---|---|---|---|---|---|---|
| 1 | 登录页验证码不刷新 | P0 | 处理中 | 小何 | 2026-10-12 | FixCaptcha01 |
| 2 | 首页轮播图偶发白屏 | P1 | 待处理 | 小郑 | 2026-10-15 | FixBanner02 |
| 3 | 消息推送延迟超 30 秒 | P1 | 处理中 | 小周 | 2026-10-13 | FixPush03 |
| 4 | 订单金额四舍五入错误 | P0 | 已修复 | 小何 | 2026-10-08 | FixAmount04 |
| 5 | 深色模式按钮不可见 | P2 | 待处理 | 小王 | 2026-10-20 | FixDark05 |
| 6 | 表单可重复提交 | P1 | 处理中 | 小周 | 2026-10-14 | FixForm06 |
| 7 | 头像上传裁剪失真 | P2 | 已修复 | 小郑 | 2026-10-09 | FixAvatar07 |
| 8 | iOS 下拉刷新卡顿 | P2 | 待处理 | 小王 | 2026-10-18 | FixPull08 |
| 9 | 支付回调偶发超时 | P0 | 处理中 | 小何 | 2026-10-11 | FixPay09 |
| 10 | 空状态文案错别字 | P2 | 已修复 | 小郑 | 2026-10-07 | FixCopy10 |
| 11 | 分享链接签名过期 | P1 | 待处理 | 小周 | 2026-10-16 | FixSign11 |
| 12 | 夜间模式耗电异常 | P1 | 处理中 | 小王 | 2026-10-17 | FixBattery12 |

（修复指引列省略公共前缀 `https://xx.feishu.cn/docx/`，JSON 中为完整 URL。）

---

## CellValue 写入格式说明（日期与单选按多维表格规范）

| 字段 | 类型 | 写入格式 | 规范依据 |
|---|---|---|---|
| 缺陷标题 / 负责人 | text | 纯字符串，如 `"小何"` | SKILL.md CellValue：`text: string` |
| 严重度 / 状态 | 单选 select | **单元素数组**：`["P0"]`、`["处理中"]` | CellValue 规范：`select: array<string>`，且 `multiple=false` 时数组内只能有一个元素；选项名必须与字段 options 中的 `name` 完全一致（步骤 1 已预置全部 6 个选项，无需在线新增） |
| 截止日期 | datetime | 不带时区字符串 `"2026-10-12 00:00"`，按 Base 时区解析；步骤 1 已用 `--time-zone Asia/Shanghai` 把 Base 时区固定为东八区，故语义即北京时间 2026-10-12 零点 | datetime 三种合法形态：带时区 ISO（如 `"2026-10-12T00:00:00+08:00"`）、不带时区字符串（按 Base 时区）、Unix 毫秒时间戳 |
| 修复指引 | text(url) | 裸 URL 字符串，如 `"https://xx.feishu.cn/docx/FixCaptcha01"` | text(url) 的 CellValue 接受裸 URL 或 Markdown link |

## 写入方式与单批规模合规性

1. **单批规模**：12 条 ≤ 单批 200 条上限 → 一次 `+record-batch-create` 合规，无需分批。
2. **串行写入**：同一 Table 必须串行写，本清单只有一条写入命令、按序执行即为串行；**不要**把 12 条拆成多个并行批次（会触发 `1254291` 并发冲突）。
3. **只读字段**：本表无 formula / lookup / auto_number / 系统字段，`create_records` 中也未写任何此类字段（误写会被 `ignored_fields` 静默过滤）。
4. **确认门禁**：当前版本两条写命令的 Risk 均为 `write`（非 `high-risk-write`），不会触发退出码 10 的 `--yes` 门禁，故清单不加 `--yes`；若你所在版本返回退出码 10（`type=confirmation`），按错误 `hint` 把其指出的确认 flag 追加到原命令末尾重试，不要静默预加。

## 写入后的可见性注意事项（回答：立即读取能否看到全部记录？）

**不能保证立即看到全部 12 条。** 官方 SKILL.md 明确：Table 下的大多数更新通过异步链路生效，「接口成功返回后立即读取可能暂时看不到最新状态」；`+record-batch-create` 的官方提示同样明确「写完不要立即 +record-list」。因此：

- **以写入成功响应为操作结果**：`ok == true` 且 `record_id_list` 恰有 12 个记录 ID，即视为 12 条全部写入成功，不必靠立刻读回确认。
- 如需终态验收，等数秒后**统一**执行一次步骤 3（`records_count == 12` 且 `has_more == false` 为通过）；不要逐条写后立即读回，也不要循环高频读。
- 若首次读取不足 12 条，属最终一致性延迟：隔几秒重读即可；**绝不要因此重跑步骤 2b**——那会再插入 12 条重复记录。

---

## 命令与 flag 出处对照（全部实测核对，无编造）

| 清单内容 | 出处（2026-09-29 抓取/克隆自 github.com/larksuite/cli main 分支） |
|---|---|
| `base +base-create --name --table-name --fields` 一次建 Base+首表+字段 | `skills/lark-base/SKILL.md` L33；`shortcuts/base/base_create.go` L33-39（Flags 定义） |
| `--time-zone`（示例值 Asia/Shanghai）、`--folder-token`（本清单未用） | `shortcuts/base/base_create.go` L35-36 |
| fields 数组 JSON 形状（字符串 type、multiple、options、style；禁数字枚举/property） | `skills/lark-base/references/lark-base-field-schema.md` §1/§3.1/§3.3/§3.4；`base_create.go` L43「与 +field-create 同形状，勿造属性」 |
| `--fields` 时 CLI 新建自定义首表并删除默认首表 | `shortcuts/base/base_ops.go` L95-124（executeBaseCreate）、L37-69（dry-run 动作描述） |
| `base +record-batch-create --base-token --table-id --json`，顶层键 `create_records`，每条记录=字段名→CellValue 平面 map | `SKILL.md` L181-183；`shortcuts/base/record_batch_create.go` L19-28 |
| `--table-id` 可传表 ID 或表名（故写「缺陷清单」合法） | `shortcuts/base/base_command_common.go` L16-18 |
| 单批 200 上限、同表串行（`1254291`）、`--json @file.json` 大 payload 形态 | `record_batch_create.go` L28；`SKILL.md` L191 |
| CellValue：text 字符串、select 单元素数组、datetime 三形态、text(url) 裸 URL、null/[] 清空 | `shortcuts/base/record_ops.go` L21-26；`SKILL.md` L154-175 |
| `--as user`（Base 操作优先 user 身份） | `SKILL.md` L17；两命令 authTypes 均含 user/bot |
| `--dry-run` 预览 | ASSET-DOC §5.4；`base_create.go` L50、`record_batch_create.go` L34 均定义 DryRun |
| `--yes` 门禁仅作用于 `high-risk-write`（本清单两条写命令为 `write`，不触发） | `shortcuts/common/runner.go` L1162 |
| 成功判定 `ok == true`（成功信封无顶层 code） | ASSET-DOC §5.2（官方 README 原文） |
| 验收 `base +record-list --base-token --table-id --limit`，stdout 摘要含 `records_count`/`has_more`；json 格式 limit 1–200 | `SKILL.md` L117/L148；`shortcuts/base/record_list.go` L20-38 |
| 异步生效、立即读可能看不到最新状态、优先以写入响应为准 | `SKILL.md` L79；`record_batch_create.go` Tips 第 5 条；ASSET-DOC §8.5 |
| 所需 scopes（base:app:create、base:table:*、base:record:create/read）；missing_scopes 补授权 | `base_create.go` L17-23、`record_batch_create.go` L17、`record_list.go` L18；ASSET-DOC §7.4 |
| `@file` 仅接受 cwd 相对路径 | ASSET-DOC §8.1（lark-shared 安全规则第 5 条） |

**核对方式与限制说明**：制作本清单的机器未安装 lark-cli（无法实跑命令）；以上出处来自本次实际抓取的官方 raw SKILL.md/reference 文件与浅克隆源码（`git clone --depth 1`）grep 逐字核对。两段 JSON 已在本地用 `node JSON.parse` 校验结构与数量。命令的最终执行效果以用户机器上已认证的 lark-cli 版本实际输出为准。

---

*注（任务与 ASSET-DOC 冲突核对）：本任务与 ASSET-DOC 的 lark-cli 方法**无冲突**——ASSET-DOC §8.5 正是推荐「`+base-create` 一次性建 Base+首表+fields」「`+record-batch-create` 批量写入、单批 ≤200、同表串行」「异步写入后立即读可能看不到最新状态」，本清单全部遵循；任务侧的特定要求（指定 6 字段及选项、固定 12 条数据及其列序）已按任务原文落实。*
