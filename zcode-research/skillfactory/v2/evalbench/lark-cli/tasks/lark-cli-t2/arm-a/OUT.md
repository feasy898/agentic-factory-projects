# lark-cli 命令清单：新建「报销」多维表格并写入 6 行数据

> 工具：飞书官方 `lark-cli`（larksuite/cli，npm `@larksuite/cli`）。
> 本文使用其 Raw API 形式 `lark-cli api <METHOD> <path> --data '<json>'`（与官方 README 示例 `lark-cli api POST /open-apis/im/v1/messages --params '...' --data '...'` 同构），路径与请求体遵循飞书多维表格（Bitable）OpenAPI v1 规范。
> 引号为 bash / PowerShell 风格；cmd.exe 不支持单引号包裹 JSON，请在 bash 或 PowerShell 下执行。
> 命令清单按任务要求产出，未实际执行。

## 0）前置：配置与授权（一次性）

应用需开通多维表格权限（scope：`bitable:app`）。

```bash
lark-cli config init
lark-cli auth login --recommend
# 若未覆盖多维表格权限，改用显式 scope：
# lark-cli auth login --scope "bitable:app"
```

## 1）新建多维表格（Base）

```bash
lark-cli api POST /open-apis/bitable/v1/apps --data '{"name":"报销多维表格"}'
```

从返回 JSON 取 `data.app.app_token`（形如 `{"code":0,"data":{"app":{"app_token":"APPXXX","default_table_id":"tblxxx","url":"…"}}}`）：

```bash
# 手动复制，或用 jq 自动提取：
# APP_TOKEN=$(lark-cli api POST /open-apis/bitable/v1/apps --data '{"name":"报销多维表格"}' | jq -r '.data.app.app_token')
APP_TOKEN=<上一步返回的 app_token>
```

## 2）建数据表「报销记录」，一次性创建 5 个字段

```bash
lark-cli api POST /open-apis/bitable/v1/apps/${APP_TOKEN}/tables --data '{
  "table": {
    "name": "报销记录",
    "default_view_name": "全部记录",
    "fields": [
      {"field_name": "提交人",   "type": 1},
      {"field_name": "日期",     "type": 5, "property": {"date_formatter": "yyyy-MM-dd"}},
      {"field_name": "金额(元)", "type": 2, "property": {"formatter": "¥0.00"}},
      {"field_name": "类型",     "type": 3, "property": {"options": [{"name":"交通"},{"name":"餐费"},{"name":"培训"},{"name":"差旅"},{"name":"设备"}]}},
      {"field_name": "状态",     "type": 3, "property": {"options": [{"name":"已批"},{"name":"待审"},{"name":"驳回"}]}}
    ]
  }
}'
```

字段类型对照（飞书 Bitable 字段 type 编码）：

| 字段 | type | 含义 | 关键 property |
|---|---|---|---|
| 提交人 | 1 | 多行文本 | — |
| 日期 | 5 | 日期 | `date_formatter: yyyy-MM-dd` |
| 金额(元) | 2 | 数字（货币格式 ¥0.00） | `formatter: ¥0.00` |
| 类型 | 3 | 单选 | 枚举：交通/餐费/培训/差旅/设备 |
| 状态 | 3 | 单选 | 枚举：已批/待审/驳回 |

从返回 JSON 取 `data.table_id`：

```bash
TABLE_ID=<上一步返回的 table_id>
```

## 3）批量写入全部 6 行记录

单选字段直接写选项名；日期字段写北京时间 0 点的毫秒时间戳（数值原文零改动）。

```bash
lark-cli api POST /open-apis/bitable/v1/apps/${APP_TOKEN}/tables/${TABLE_ID}/records/batch_create --data '{
  "records": [
    {"fields": {"提交人": "张三", "日期": 1788364800000, "金额(元)": 128.5, "类型": "交通", "状态": "已批"}},
    {"fields": {"提交人": "李四", "日期": 1788537600000, "金额(元)": 356,   "类型": "餐费", "状态": "已批"}},
    {"fields": {"提交人": "王五", "日期": 1788796800000, "金额(元)": 89,    "类型": "培训", "状态": "待审"}},
    {"fields": {"提交人": "赵六", "日期": 1788969600000, "金额(元)": 1240,  "类型": "差旅", "状态": "待审"}},
    {"fields": {"提交人": "张三", "日期": 1789142400000, "金额(元)": 45.8,  "类型": "交通", "状态": "已批"}},
    {"fields": {"提交人": "钱七", "日期": 1789401600000, "金额(元)": 680,   "类型": "设备", "状态": "驳回"}}
  ]
}'
```

日期→毫秒时间戳对照（`2026-09-03T00:00:00+08:00` 等，已用本机 node 实测校验）：

| 日期 | 毫秒时间戳 |
|---|---|
| 2026-09-03 | 1788364800000 |
| 2026-09-05 | 1788537600000 |
| 2026-09-08 | 1788796800000 |
| 2026-09-10 | 1788969600000 |
| 2026-09-12 | 1789142400000 |
| 2026-09-15 | 1789401600000 |

## 4）（可选）回读校验

```bash
lark-cli api GET /open-apis/bitable/v1/apps/${APP_TOKEN}/tables/${TABLE_ID}/records --params '{"page_size":20}'
```

## 字段类型选择理由（≤100 字）

提交人用文本；日期用日期字段，存毫秒时间戳、显示 yyyy-MM-dd；金额用数字字段并配货币格式 ¥0.00；类型、状态取值固定，用单选枚举防脏数据。
