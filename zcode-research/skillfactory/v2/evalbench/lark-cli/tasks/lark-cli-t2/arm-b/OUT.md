# lark-cli-t2 · 飞书报销多维表格命令清单（arm-b）

> 编写依据：`skillfactory/v2/evalbench/lark-cli/ASSET-DOC.md`（larksuite/cli 官方 CLI 资产档），并核对了 2026-09-29 抓取的官方 `skills/lark-base/SKILL.md` 与 `references/lark-base-field-schema.md`、`references/lark-base-field-create.md` 原文。
> 按任务要求**未实际执行**，以下为可执行的命令序列。

## 0. 前置（仅首次，一次性；非本序列核心）

```bash
lark-cli config init            # 配置应用凭证（一次性）
lark-cli auth login --recommend # 登录授权
```

## 1. 建 Base + 首表 + 5 个字段（一条命令，官方推荐「一次性建 Base+首表」）

```bash
lark-cli base +base-create \
  --name "报销单" \
  --table-name "报销明细" \
  --fields '[
    {"name":"提交人","type":"text"},
    {"name":"日期","type":"datetime","style":{"format":"yyyy-MM-dd"}},
    {"name":"金额(元)","type":"number","style":{"type":"currency","precision":2,"currency_code":"CNY"}},
    {"name":"类型","type":"select","multiple":false,"options":[{"name":"交通"},{"name":"餐费"},{"name":"培训"},{"name":"差旅"},{"name":"设备"}]},
    {"name":"状态","type":"select","multiple":false,"options":[{"name":"已批"},{"name":"待审"},{"name":"驳回"}]}
  ]' \
  --as user
```

成功判定：输出信封 `ok == true`（或退出码 0），**不要**用 `code == 0` 判断。从返回 JSON 的 `data` 中取新建 Base 的 `app_token` 与 `table_id`，代入第 2 步（字段路径以实际返回为准）。

## 2. 写入全部 6 行记录（单批 ≤200 条，6 条一次写完）

```bash
lark-cli base +record-batch-create \
  --base-token <app_token> \
  --table-id <table_id> \
  --json '{"create_records":[
    {"提交人":"张三","日期":"2026-09-03 00:00","金额(元)":128.5,"类型":["交通"],"状态":["已批"]},
    {"提交人":"李四","日期":"2026-09-05 00:00","金额(元)":356,"类型":["餐费"],"状态":["已批"]},
    {"提交人":"王五","日期":"2026-09-08 00:00","金额(元)":89,"类型":["培训"],"状态":["待审"]},
    {"提交人":"赵六","日期":"2026-09-10 00:00","金额(元)":1240,"类型":["差旅"],"状态":["待审"]},
    {"提交人":"张三","日期":"2026-09-12 00:00","金额(元)":45.8,"类型":["交通"],"状态":["已批"]},
    {"提交人":"钱七","日期":"2026-09-15 00:00","金额(元)":680,"类型":["设备"],"状态":["驳回"]}
  ]}' \
  --as user
```

写入要点（均出自官方文档）：
- 单选 CellValue 必须是**数组**且最多一个值（如 `["交通"]`）；选项必须是第 1 步已建的枚举。
- 日期值用不带时区字符串 `"2026-09-03 00:00"`，自动按 Base 时区解释；字段显示格式 `yyyy-MM-dd`，时间部分不显示。
- 数字为纯 double（`128.5`、`356`、`89`、`1240`、`45.8`、`680`），值与原始数据零改动；precision 仅影响显示。
- 6 条 < 200 条单批上限；同一 Table 请串行写入，勿并行。

Windows（cmd.exe）提示：官方示例为 bash 单引号风格；在本机 cmd 下建议把两段 JSON 存为 cwd 下的相对路径文件（如 `fields.json`、`records.json`），改用 `--fields @fields.json` / `--json @records.json`（lark-cli 仅接受相对路径，绝对路径会报 unsafe file path）。

## 3. 字段类型选择理由（≤100 字）

提交人存姓名用文本；日期用日期型（datetime 配 yyyy-MM-dd）便于排序筛选；金额用数字字段配货币样式（CNY）可加总统计；类型、状态取值固定，用单选约束枚举、便于过滤。

## 附：任务措辞与 lark-cli 类型串对照

- 任务「日期」→ 官方类型串为 `datetime`（无 `date` 类型串），配 `style.format:"yyyy-MM-dd"` 即纯日期字段。
- 任务「货币或数字」→ 官方无独立 `currency` 类型串，货币即 `number` + `style.type:"currency"`（`currency_code:"CNY"`），本序列选货币样式。
- 任务「单选」→ 官方类型串为 `select` + `"multiple":false`（无 `single_select` 串）；枚举选项仅 `name` 必填，hue 可省略（默认 Blue）。
