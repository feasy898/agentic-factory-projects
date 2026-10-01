# 移动端 3.8 缺陷看板 · lark-cli 建表与录入命令清单（可按序直接执行）

- 适用工具：**lark-cli v1.0.97**（官方 `@larksuite/cli`，bin 名 `lark-cli`）。本清单全部命令与 flag 均逐一对照该版本真实 `--help` 输出与内嵌技能文档（`lark-cli skills read lark-base`，lark-base v1.2.23）核实，无虚构。
- 前提：lark-cli 已安装并完成认证（本清单不再含认证步骤；不放心可先跑第 0 步自检）。
- 执行顺序：0（可选）→ 1 → 2 → 3（可选）。
- 建议 shell：Windows PowerShell 或 Git Bash（JSON 用单引号包裹即可）；cmd.exe 的转义方式见第 1 步备注。两条写命令首次执行前都可先加 `--dry-run` 预览请求（不实际执行，官方 flag）。

---

## 0.（可选）执行前自检

```powershell
lark-cli whoami
```

**理由**：确认当前已认证、生效身份与 token 状态（Base 操作官方建议用用户身份 `--as user`，此命令可先确认身份可用）。

---

## 1. 一次性创建多维表格 Base「移动端 3.8 缺陷看板」+ 首表「缺陷清单」（含全部 6 个字段）

```powershell
lark-cli base +base-create --name "移动端 3.8 缺陷看板" --table-name "缺陷清单" --time-zone "Asia/Shanghai" --fields '[{"type":"text","name":"缺陷标题"},{"type":"select","name":"严重度","multiple":false,"options":[{"name":"P0"},{"name":"P1"},{"name":"P2"}]},{"type":"select","name":"状态","multiple":false,"options":[{"name":"待处理"},{"name":"处理中"},{"name":"已修复"}]},{"type":"text","name":"负责人"},{"type":"datetime","name":"截止日期","style":{"format":"yyyy-MM-dd"}},{"type":"text","name":"修复指引"}]' --as user
```

**理由**：`+base-create` 带 `--table-name` + `--fields` 时一条命令同时创建 Base、首表和字段 schema（官方推荐做法），一步到位满足"一次性新建 Base 和首表"。

### fields 定义 JSON（与上面 `--fields` 参数完全一致，便于审阅）

```json
[
  { "type": "text",     "name": "缺陷标题" },
  { "type": "select",   "name": "严重度", "multiple": false, "options": [ { "name": "P0" }, { "name": "P1" }, { "name": "P2" } ] },
  { "type": "select",   "name": "状态",   "multiple": false, "options": [ { "name": "待处理" }, { "name": "处理中" }, { "name": "已修复" } ] },
  { "type": "text",     "name": "负责人" },
  { "type": "datetime", "name": "截止日期", "style": { "format": "yyyy-MM-dd" } },
  { "type": "text",     "name": "修复指引" }
]
```

字段说明（依据内嵌 `lark-base-field-schema.md`）：

| 字段 | 类型定义 | 依据 |
|---|---|---|
| 缺陷标题 | `text`，且位于首位 | 数组第一项自动成为首列/主字段（`+table-create` 官方 Tip）；最小写法 `type`+`name` |
| 严重度 | `select` + `multiple:false` + 3 个 `options[].name` | 单选/多选同为 `select`，用 `multiple` 区分，默认 `false`；选项只需 `name`（hue/lightness 可省略） |
| 状态 | 同上 | 同上 |
| 负责人 | `text` | 按需求为文本（不建为 user 人员字段，避免写 ID） |
| 截止日期 | `datetime` + `style.format: yyyy-MM-dd` | 多维表格的"日期"字段即 `datetime` 类型；`style.format` 只控制前端展示，`yyyy-MM-dd` 使看板只显示到日 |
| 修复指引 | `text` | 按需求为文本；CellValue 直接写裸 URL 字符串（官方 CellValue 规则：text(url) → 裸 URL 或 Markdown link） |

备注：
- 执行成功后**从返回 JSON 中复制 Base 的 token**（响应里形如 `app_token`/`base_token` 的字段，以实际返回为准），第 2 步的 `--base-token` 要用。
- 若想把 Base 建到指定云文件夹，可追加官方可选 flag `--folder-token <文件夹token>`；不加则由平台放入默认位置。
- cmd.exe 用户：把外层单引号改为双引号，并把 JSON 内层的 `"` 改成 `\"` 转义；或直接改用 PowerShell。
- 可选变体：若希望"修复指引"列里的链接在表格内可点击，可将该字段加上同为官方定义的文本子样式 `"style":{"type":"url"}`（仍是 text 类型，写入值不变）；本清单按需求字面采用纯文本。

---

## 2. 一次性写入全部 12 条记录（单批合规）

### 2.1 先把待写入记录 JSON 存为本地文件 `records.json`（内容如下，原样保存）

```json
{
  "create_records": [
    { "缺陷标题": "登录页验证码不刷新", "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-12 00:00", "修复指引": "https://xx.feishu.cn/docx/FixCaptcha01" },
    { "缺陷标题": "首页轮播图偶发白屏", "严重度": ["P1"], "状态": ["待处理"], "负责人": "小郑", "截止日期": "2026-10-15 00:00", "修复指引": "https://xx.feishu.cn/docx/FixBanner02" },
    { "缺陷标题": "消息推送延迟超 30 秒", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-13 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPush03" },
    { "缺陷标题": "订单金额四舍五入错误", "严重度": ["P0"], "状态": ["已修复"], "负责人": "小何", "截止日期": "2026-10-08 00:00", "修复指引": "https://xx.feishu.cn/docx/FixAmount04" },
    { "缺陷标题": "深色模式按钮不可见", "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-20 00:00", "修复指引": "https://xx.feishu.cn/docx/FixDark05" },
    { "缺陷标题": "表单可重复提交", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小周", "截止日期": "2026-10-14 00:00", "修复指引": "https://xx.feishu.cn/docx/FixForm06" },
    { "缺陷标题": "头像上传裁剪失真", "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-09 00:00", "修复指引": "https://xx.feishu.cn/docx/FixAvatar07" },
    { "缺陷标题": "iOS 下拉刷新卡顿", "严重度": ["P2"], "状态": ["待处理"], "负责人": "小王", "截止日期": "2026-10-18 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPull08" },
    { "缺陷标题": "支付回调偶发超时", "严重度": ["P0"], "状态": ["处理中"], "负责人": "小何", "截止日期": "2026-10-11 00:00", "修复指引": "https://xx.feishu.cn/docx/FixPay09" },
    { "缺陷标题": "空状态文案错别字", "严重度": ["P2"], "状态": ["已修复"], "负责人": "小郑", "截止日期": "2026-10-07 00:00", "修复指引": "https://xx.feishu.cn/docx/FixCopy10" },
    { "缺陷标题": "分享链接签名过期", "严重度": ["P1"], "状态": ["待处理"], "负责人": "小周", "截止日期": "2026-10-16 00:00", "修复指引": "https://xx.feishu.cn/docx/FixSign11" },
    { "缺陷标题": "夜间模式耗电异常", "严重度": ["P1"], "状态": ["处理中"], "负责人": "小王", "截止日期": "2026-10-17 00:00", "修复指引": "https://xx.feishu.cn/docx/FixBattery12" }
  ]
}
```

写入格式依据（内嵌 lark-base skill 的 CellValue 规范原文要点）：

- **单选**：CellValue 是 `array<string>`，元素为选项名；单选（`multiple:false`）数组最多一个值 → 写 `["P0"]`、`["待处理"]`。✅ 不能写裸字符串 `"P0"`。
- **日期**：`datetime` 接受三种文档化写法——带时区 ISO8601（如 `2026-10-12T00:00:00+08:00`）、**不带时区**的 `"yyyy-MM-dd HH:mm"`（自动按 Base 时区解析）、或 Unix 毫秒时间戳。本清单统一用无时区写法 `"2026-10-12 00:00"`（配合第 1 步 `--time-zone Asia/Shanghai`，即北京时间当日零点），前端 `yyyy-MM-dd` 格式下显示为 `2026-10-12`。注意：裸 `"2026-10-12"` 不是文档列出的写入格式，故补 `00:00`。
- **文本/链接**：直接写字符串；`修复指引` 按规范写裸 URL（如 `https://xx.feishu.cn/docx/FixCaptcha01`）。
- **键名**：`{字段名或 field_id: CellValue}`，可直接用字段中文名。

### 2.2 执行批量写入

```powershell
lark-cli base +record-batch-create --base-token <第1步返回的base_token> --table-id "缺陷清单" --json @records.json --as user
```

**理由**：`+record-batch-create` 是官方批量新增 shortcut，12 条 ≤ 单批上限 200 条，一批写完即可，无需分批。

写入方式与规模合规性：
- **单批规模**：官方限制"Batch create supports max 200 records per call"（`--help` Tips 原文）；12 条远低于上限，**一批发送**即合规。
- **串行写入**：官方规则"单批最多 200 条，超过后分批，同一 Table 串行写入；并行可能触发 `1254291` 并发冲突错误"——本任务只有一批，天然串行；若日后追加数据，请勿对同一表并行发批。
- `--table-id` 传表 ID（`tbl` 开头）或**表名**均可（`--help` 原文），这里直接用表名「缺陷清单」，省去查 table_id。
- `--json @records.json` 是官方支持的大 payload 文件读法（skill 原文："大 payload 可用脚本生成 json 后用 `--json @file.json`"）；如需内联，把同一 JSON 用单引号包在 PowerShell/Git Bash 里直接传给 `--json` 即可。
- 成功响应会返回 `record_id_list`（12 个 `rec` 开头的记录 ID）——**请保存该响应**，它就是本批写入成功的凭证（见第 4 节）。

---

## 3.（可选）统一读取验收

```powershell
lark-cli base +record-list --base-token <第1步返回的base_token> --table-id "缺陷清单" --as user
```

**理由**：全部写入完成后一次性读回核验总数（官方要求"先完成本轮相关变更，再统一读取验收"），确认 12 条齐全。

---

## 4. 写入后的可见性注意事项（立即读取能否看到全部记录？）

**结论：不保证立即读回就能看到全部 12 条。**

官方 skill（lark-base）对 Table 写入的可见性有明确规则，原文要点：

1. "Table 下的大多数更新通过**异步链路**生效，**接口成功返回后立即读取可能暂时看不到最新状态**。优先以**写入成功响应**作为操作结果；任务必须确认最终状态时，**先完成本轮相关变更，再统一读取验收**，避免逐项写后立即读回。"
2. `+record-batch-create` 官方 Tips 亦明确："After batch-creating known helper rows, **use the returned record IDs and your submitted rows**; do not immediately +record-list the same table unless you need server-normalized formula/lookup values or failure diagnosis."（写完不要立刻列表读回，以返回的 record_id 和提交内容为准。）

落到本任务的操作含义：

- **以命令 2 的成功响应（`record_id_list` 含 12 个 ID）为写入完成凭证**，不要以"马上 record-list 能看到几条"判断成败。
- 立即执行命令 3 可能出现**暂时少于 12 条甚至读不到**的情况（最终一致，通常短时间内收敛）；遇到不足时**稍候重试**，不要重复执行命令 2，否则会产生重复记录。
- 多维表格前端界面同理：写入成功后记录会陆续出现，刷新即可，短暂延迟不代表丢失。

---

## 5. 本清单的验证情况（诚实披露）

以下为本清单产出环境中的实测记录（2026-09-29）：

- 实测运行 `npx -y @larksuite/cli@1.0.97 --version` → `lark-cli version 1.0.97`；`lark-cli --help`、`base --help`、`base +base-create --help`、`base +table-create --help`、`base +record-batch-create --help`、`base +app-create --help`、`skills read lark-base`、`skills read lark-base references/lark-base-field-schema.md` 均实际执行，本清单全部命令名、flag 名、JSON 结构、CellValue 规则、200 条/批与串行限制、异步可见性规则皆引自上述真实输出。
- 两段 JSON（fields 定义、12 条记录）已用 Python `json.load` 校验通过，并逐行比对与任务给定的 12 条数据完全一致（6 字段 × 12 行）。
- **未实际执行**：第 1、2 步写操作（产出环境 CLI 未配置认证，`whoami` 返回 `not_configured`，本清单假定在你的已认证环境执行）；执行时若遇权限/`--as` 身份问题，按 CLI 提示以当前身份修复 scope，勿静默换身份。
