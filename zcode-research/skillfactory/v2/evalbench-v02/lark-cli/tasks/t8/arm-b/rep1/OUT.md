# 《9 月加班餐费台账》录入飞书电子表格 + 导出 CSV —— 可按序直接执行的命令清单

> 交付物：行政助手按序执行的完整命令清单。所有命令与 flag 均经本机 `lark-cli`（v1.0.97，`lark-cli --version` 实测）的 `--help` 与官方 skill 文档（`lark-cli skills read lark-shared` / `lark-sheets` 及其 references）逐条核实，无编造；拿不准的用法均按「先 `--help` / schema 核实」处理并在文中注明核实结果。

---

## 一、执行前提（先读 30 秒）

1. **运行环境**：在用户已安装并完成认证的 lark-cli 环境执行。制作本清单的机器上 `lark-cli auth status` 实测返回 `ok:false, error.type=config, subtype=not_configured`（退出码 3）——即本机未配置。若执行时遇到同样报错，先按 hint 完成 `lark-cli config init --new` 与 `lark-cli auth login --recommend` 再继续。
2. **工作目录（cwd）**：lark-cli 的 `@file`、`--output-path` 等文件参数**只接受 cwd 下的相对路径**，绝对路径会被拒（`unsafe file path`）——来源：`lark-cli skills read lark-shared` 安全规则 5。**执行前先 `cd` 到你希望 `sep-meal.csv` 落地的目录**，之后所有文件参数都写相对路径。
3. **身份**：所有命令统一加 `--as user`。台账要落在用户本人云空间；lark-shared 通用准则 2：`--as bot` 只能访问 bot 自己的资源。下文命令输出中的默认 identity 亦显示为 bot，故显式指定。
4. **成功判定**：每条命令看返回 JSON 的 `ok == true`（或退出码 0），**不要**看 `code == 0`——成功信封没有顶层 `code` 字段（ASSET-DOC §5.2、lark-shared 准则 4）。
5. **shell 适配**：两份 JSON 载荷**先保存为文件**再以 `@./文件名` 传入，不要在 cmd.exe 里内联多行 JSON（cmd 会吃掉内层双引号；官方 skill「非 POSIX shell 适配」表口径：cmd 一律走 `@file`）。文件用 **UTF-8（无 BOM）** 保存。
6. **占位符约定**（只有两个，来源均在对应命令下注明）：
   - `<表格URL>` —— 新建工作簿的链接；
   - `<SHEET_ID>` —— 子表 reference_id。
   - 备选：`--url "<表格URL>"` 与 `--spreadsheet-token <TOKEN>` 二选一（XOR，`--help` 已核实），二者可互换。

## 二、数据与合计（预先核对，执行时可对照）

| 工号 | 姓名 | 部门 | 加班次数 | 餐费合计（元） |
|---|---|---|---|---|
| 00183 | 阿岚 | 研发 | 12 | 360 |
| 00241 | 阿荔 | 设计 | 7 | 210 |
| 00377 | 阿松 | 研发 | 15 | 450 |
| 00410 | 阿玫 | 市场 | 3 | 90 |
| 00526 | 阿柏 | 研发 | 9 | 270 |
| 00638 | 阿棠 | 财务 | 5 | 150 |

- **加班次数总和 = 12+7+15+3+9+5 = 51**
- **餐费总和 = 360+210+450+90+270+150 = 1530**（勾稽：51 次 × 30 元/次 = 1530，一致）
- 以上两数已用本地 Python 脚本对载荷文件实算复核（`sum(r[3])=51`、`sum(r[4])=1530`，本次会话实测通过）。

## 三、第 0 步：在 cwd 保存两份载荷文件（内容逐字如下）

**文件 1：`./sep-meal-payload.json`**（建表 + 写 6 行的 typed 载荷）

```json
{
  "sheets": [
    {
      "name": "9月台账",
      "columns": ["工号", "姓名", "部门", "加班次数", "餐费合计（元）"],
      "dtypes": {"工号": "object", "加班次数": "int64", "餐费合计（元）": "int64"},
      "data": [
        ["00183", "阿岚", "研发", 12, 360],
        ["00241", "阿荔", "设计", 7, 210],
        ["00377", "阿松", "研发", 15, 450],
        ["00410", "阿玫", "市场", 3, 90],
        ["00526", "阿柏", "研发", 9, 270],
        ["00638", "阿棠", "财务", 5, 150]
      ]
    }
  ]
}
```

**文件 2：`./totals-cells.json`**（合计行载荷，A 列「合计」，D/E 列落 SUM 公式）

```json
[
  [{"value": "合计"}, {}, {}, {"formula": "=SUM(D2:D7)"}, {"formula": "=SUM(E2:E7)"}]
]
```

> 两份文件内容已在本会话实存实校：UTF-8 无 BOM、JSON 语法合法、文件 1 为 6 行 × 5 列、文件 2 为 1 行 × 5 列（与 `--range "A8:E8"` 的维度契约一致）。子表名「9月台账」为本清单显式指定（官方 workbook reference：create 时应显式传子表名，不要依赖默认命名；任务只点名了工作簿标题）。

## 四、命令清单（按序执行）

### ① 建表并写入表头与 6 行

**1. 确认登录态**
```bash
lark-cli auth status
```
理由：前置自检——确认已认证、identity 为 user 且 scope 足够，避免写到一半才发现未授权。

**2. 新建电子表格并一步写入表头与 6 行数据**
```bash
lark-cli sheets +workbook-create --as user --title "9 月加班餐费台账" --sheets @./sep-meal-payload.json
```
理由：`+workbook-create --sheets` 是官方「一步建表 + 类型保真写入」首选——string 列保前导零、int 列保持数值，且 `--title` 即工作簿在云空间的名称（必填，不会从数据推断，`--help` 与 skill 文档均已核实）。

- **返回值占位符 `<表格URL>` 来源**：本命令成功响应（`ok:true`）返回体中的新表链接；若返回体给的是 token，后续所有 `--url "<表格URL>"` 可等价换成 `--spreadsheet-token <TOKEN>`（二者 XOR，`--help` 已核实）。

**3. 查询工作簿结构，取子表 `sheet_id`**
```bash
lark-cli sheets +workbook-info --as user --url "<表格URL>"
```
理由：官方规定任何 sheet 级操作前必须先 `+workbook-info` 拿真实 `sheet_id`，禁止猜 `Sheet1`（skill 强触发规则原文）。

- **返回值占位符 `<SHEET_ID>` 来源**：本命令返回 `sheets[]`，取 `title == "9月台账"` 那一项的 `sheet_id` 字段（`+workbook-info` 输出契约原文：每项含 `sheet_id` / `title`）。

**4. 回读校验第 1 步写入结果（首行 + 6 数据行）**
```bash
lark-cli sheets +csv-get --as user --url "<表格URL>" --sheet-id "<SHEET_ID>" --range "A1:E7"
```
理由：skill「回读抽样校验」准则——写后必回读，核对表头 5 列、6 行数据、**工号前导零（首行 00183、末行 00638）未被数值化**（带前导零的列要专挑前导零代表值核对，官方原文）。

### ② 数据末尾追加合计行（不重写已有 6 行）

**5. 预检合计行落区（零副作用）**
```bash
lark-cli sheets +cells-set --as user --url "<表格URL>" --sheet-id "<SHEET_ID>" --range "A8:E8" --cells @./totals-cells.json --dry-run
```
理由：lark-shared 安全规则 3——支持 `--dry-run` 的写入先预览；确认落区就是第 8 行（表尾新行），不波及第 1–7 行。

**6. 正式写入合计行**
```bash
lark-cli sheets +cells-set --as user --url "<表格URL>" --sheet-id "<SHEET_ID>" --range "A8:E8" --cells @./totals-cells.json
```
理由：表头在第 1 行、数据在第 2–7 行（第 4 步已确认），故合计行=第 8 行；`--range "A8:E8"` 矩形是**边界**，写入物理上锁定第 8 行，不可能重写已有 6 行；合计按 skill「公式闭环」准则落 `=SUM(D2:D7)` / `=SUM(E2:E7)` 公式（预期 **D8=51、E8=1530**），而不是算好的死数。

- 为什么不用 `+table-put --mode append`：它确能自动定位末行追加，但 `+table-put` **没有公式字段**（官方 write-cells reference 明示），写不了 SUM 公式；本表行数已知（第 8 行），`+cells-set` 定点写入同样满足「不重写已有行」且能落公式。
- 合计行 A 列写「合计」，B/C 列用空对象 `{}` 占位（官方语义：该格不做修改，保持空白）；若财务一定要静态数字而非公式，把 `totals-cells.json` 里的 `{"formula": "=SUM(D2:D7)"}` 换成 `{"value": 51}`、`{"formula": "=SUM(E2:E7)"}` 换成 `{"value": 1530}`，命令不变。

**7. 回读校验合计行**
```bash
lark-cli sheets +csv-get --as user --url "<表格URL>" --sheet-id "<SHEET_ID>" --range "A8:E8"
```
理由：写后必回读（skill Execute 约束）；确认 A8=「合计」、D8=51、E8=1530 与第二节手工核对值一致。

**8.（可选，按 skill 准则）冻结表头行**
```bash
lark-cli sheets +dim-freeze --as user --url "<表格URL>" --sheet-id "<SHEET_ID>" --rows 1 --cols 0
```
理由：skill 流程准则——「加汇总行这类会改变表长的任务，收尾把表头行冻住」；`--rows`/`--cols` 必须一次给全（冻结状态是整体声明，官方 tip：`--rows 1 --cols 0` = 只冻首行）。任务未点名，可跳过。

### ③ 导出 CSV 到本地 `./sep-meal.csv`

**9. 导出该子表为 CSV 并下载**
```bash
lark-cli sheets +workbook-export --as user --url "<表格URL>" --file-extension csv --sheet-id "<SHEET_ID>" --output-path ./sep-meal.csv
```
理由：官方 CSV 导出入口；`--help` 明示 **csv 模式必须配 `--sheet-id`**（该命令专有 flag，一次只导一张子表），且**省略 `--output-path` 时只建导出任务、不下载文件**——所以要落盘必须显式给路径。
- 路径规则：`--output-path` 只接受 cwd 相对路径（同前提 2），写 `./sep-meal.csv`，不写绝对路径。
- 该命令内置异步轮询；若返回「仍在导出」的续传引用，原命令重跑一次即可继续下载（官方 Tips）。

**10. 本地核验导出文件**
```bash
type sep-meal.csv
```
理由：导出物落盘核验——应共 8 行（1 表头 + 6 数据 + 1 合计），工号列仍是 `00183`–`00638` 字面（文本导出），合计行数值 51 / 1530；末尾「合计」行的 B/C 列为空。（bash 环境用 `cat ./sep-meal.csv`。）

## 五、关键写入格式说明（对应要求 ①②③）

| 项 | 按什么格式写 | 依据（均已核实） |
|---|---|---|
| 工号（00183 等） | **字符串**写入：payload 中 `"dtypes": {"工号": "object"}`（pandas object = string），CLI 端 string 列默认带 `@` 文本数字格式 → 飞书不会把 00183 解析成数字 183，前导零字面保留 | `lark-sheets` reference 原文：「编号 001、身份证/单据号等本质是标识符……以字符串类型写入（dtypes 设 object）并把 number_format 设为 "@"，字面保真」；workbook reference：「string 列保前导零（如订单号 00123）」 |
| 加班次数 / 餐费合计 | **数值**写入：data 数组中为 JSON 数字字面量（`12`、`360`，无引号）+ `"dtypes": {"加班次数": "int64", "餐费合计（元）": "int64"}` | reference 原文：「金额/百分比/比率/计数……本质是量值的数据，优先以数字类型写入」 |
| 表头 | `--sheets` 协议 `columns` 数组，mode 默认 overwrite 时「表头 + 数据」整块写入第 1 行起 | `+workbook-create --sheets` schema 原文 |
| 合计行 | A8=文本「合计」，D8/E8 落 `=SUM(D2:D7)`、`=SUM(E2:E7)` 公式；**正确数字：次数 51、餐费 1530** | skill「公式闭环」准则；数字由本会话 Python 实算复核 |
| 不重写已有 6 行 | 写入范围仅 `A8:E8`（矩形边界语义：数组超出会被拒、不足收窄），第 8 行写入前为空（第 4 步回读确认末行为第 7 行） | `+cells-set` 边界语义原文 + 第 4 步回读步骤 |
| 本地文件参数 | `@./xxx.json`、`./sep-meal.csv` 一律 cwd 相对路径，绝对路径报 `unsafe file path` | lark-shared 安全规则 5、`+workbook-import` 文档同口径原文 |

## 六、本次会话已实测 / 未实测事项（如实声明）

**已实测（本机制作环境）**：
- `lark-cli --version` → 1.0.97；`lark-cli sheets --help` 及 6 条目标命令（`+workbook-create` / `+workbook-info` / `+cells-set` / `+csv-get` / `+dim-freeze` / `+workbook-export`）的 `--help` 逐条核对 flag；
- `lark-cli skills read lark-shared`、`lark-sheets` 及 references（workbook、write-cells）全文读取；
- 两份载荷文件实存实校：UTF-8 无 BOM、JSON 合法、6×5 与 1×5 维度、合计实算 51 / 1530（Python `sum`）。

**未能实测（受本机限制，如实说明）**：
- `lark-cli auth status` → `ok:false, type=config, not_configured`（退出码 3）：**本机未配置认证**，与任务前提「用户已认证」不符；清单按任务前提编写，并把 `auth status` 列为第 1 步。
- 两份载荷的 `--dry-run` 试跑被同一配置门挡下（同样 `not_configured`，退出码 3），因此**载荷未能过 CLI 的参数校验层**，仅过了本地 JSON/编码/维度校验；载荷结构本身与官方 reference 的 schema 原文逐字段一致。
- 步骤 1–10 的实际建表/写入/导出未执行（交付物为命令清单，且本机无认证；避免在未配置环境产生半途资源）。

## 七、与任务/资产说明的冲突处理（按任务要求注明）

ASSET-DOC 及官方 skill 与本任务无实质冲突。三点口径差异按「以任务为准」处理并说明如下：
1. 任务要求导出 CSV 到本地，而 skill 提醒「普通在线交付不得为内部验证主动导出」——本任务的导出是**用户点名要本地 CSV 给财务**，正落在 skill 允许的「用户明确要求本地文件」例外内，按任务执行。
2. skill 建议加汇总行后冻结表头行，任务未要求——列为可选步骤 8，执行者可跳过，不影响 ①②③ 验收。
3. 本机制作环境 CLI 未配置认证，与任务前提「已完成认证」不符——按任务前提（用户环境已认证）产出清单，并以 `auth status` 作为执行首步自检，未达前提即停下补配置。
