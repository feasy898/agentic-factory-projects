# 《9 月加班餐费台账》→ 飞书电子表格 录入 + CSV 导出：可执行命令清单

> 生成环境：lark-cli **1.0.97**（win32，`lark-cli --version` 实测）。
> 本清单所有命令、flag、JSON 结构均经 `--help` / `--print-schema` / `schema` **逐条核实**（核实记录见文末附录），未编造任何 flag。任务只要求产出清单，**未执行任何真实写操作、未创建任何线上表格**。

## ⚠️ 开始前必读：本机认证状态与任务前提不符（实测）

任务前提称“lark-cli 已完成认证”，但在本机实测：

```
$ lark-cli profile list
[]

$ lark-cli whoami          # 退出码 3
{"ok":false,"error":{"type":"config","subtype":"not_configured",
 "message":"not configured",
 "hint":"run `lark-cli config init --new` in the background. It blocks and outputs a verification URL — retrieve the URL and open it in a browser to complete setup."}}
```

即当前环境**没有任何已配置 profile**。因此：
- 本清单中所有命令语法经帮助/Schema 核实，但 **3 条 `--dry-run` 预检全部在配置检查处被拦（exit 3），未能实际跑通**；载荷 JSON 已改用 `--print-schema` 逐字段校验。
- 请先执行**步骤 0** 自检；若你的环境同样报 `not_configured`，按 CLI 自带提示先运行 `lark-cli config init --new` 完成配置（会输出验证 URL，需浏览器确认），再继续步骤 1。

## 口径约定

| 项 | 口径 | 依据 |
|---|---|---|
| 表格名 | `9 月加班餐费台账`（**不含书名号**，《》视为题目里的引用记号；若确需含书名号，改 `--title` 实参即可） | 常规理解，已在命令中如实体现 |
| `<SPREADSHEET_TOKEN>` | **占位符**，取步骤 1 返回 JSON 中的 `spreadsheet_token` 字段。来源：`lark-cli schema sheets.spreadsheets.create` 的 outputSchema 定义了 `data.spreadsheet.spreadsheet_token`（另有 `url`/`title`/`folder_token` 字段）；`+workbook-create` 返回中字段名同名，具体 JSON 路径以实际返回为准 | schema 实测 |
| `<SHEET_ID>` | **占位符**，取步骤 2 返回中 `title` 为 `餐费台账` 那条记录的 `sheet_id` 字段 | `+workbook-info --help`：“List sub-sheets of a spreadsheet with metadata (sheet_id, title, ...)” |
| **工号前导 0** | 工号按**文本**写入：`--sheets` 载荷中该列 `dtypes` 给 `"string"`。Schema 原文：dtype `object`/`string`/`category`/未识别 → “string + 文本格式 `@`（**数字样字符串如「00123」不会塌缩成数字**）”。即单元格值为文本、单元格格式为文本 `@`，`00183` 原样保留 | `+workbook-create --print-schema --flag-name sheets` 实测 |
| 次数/金额按数值 | 两列 `dtypes` 给 `"int64"`。Schema 原文：`int*`/`float*` 等 → “number（**精度保留**）”，写入为真实数值而非文本 | 同上 |
| 命令书写形式 | 主形态按 CLI 官方示例用 **bash 单引号**包 JSON。**Windows cmd.exe 不解析单引号**，请改用 `@文件` 形式传 JSON（`--sheets`/`--cells` 的帮助均标注 “supports @file”）或在 Git Bash / PowerShell 中执行；两种形态都在下方给出 | 帮助原文 |
| 风险级别 | 步骤 1/3/4/5 分别为 `write`/`write`/`read`/`read`（各命令 `--help` 标注）；无 `high-risk-write`，故**均不需要 `--yes`**（帮助口径：high-risk-write 才需要） | 帮助原文 |
| 存放位置 | 不传 `--folder-token` → 建在云空间根目录（帮助原文：“placed at the drive root when omitted”）；需要归档到指定文件夹时加 `--folder-token <文件夹token>` | 帮助原文 |

---

## 命令清单（按序执行）

### 步骤 0 — 环境自检（read，不改任何东西）

```bash
lark-cli whoami
```

**理由**：确认 profile/认证确实就绪再动手写；当前配置缺失时它会直接给出修复提示。
**预期**：返回 JSON，含当前身份与 token 状态。若报 `not_configured`：先 `lark-cli config init --new`（CLI hint 原文，需浏览器完成验证）再继续。

---

### 步骤 1 — 新建电子表格《9 月加班餐费台账》并一步写入表头 + 6 行数据（write）

**主形态（bash）**：

```bash
lark-cli sheets +workbook-create \
  --title '9 月加班餐费台账' \
  --sheets '{
  "sheets": [{
    "name": "餐费台账",
    "columns": ["工号", "姓名", "部门", "加班次数", "餐费合计（元）"],
    "dtypes": { "工号": "string", "加班次数": "int64", "餐费合计（元）": "int64" },
    "data": [
      ["00183", "阿岚", "研发", 12, 360],
      ["00241", "阿荔", "设计", 7, 210],
      ["00377", "阿松", "研发", 15, 450],
      ["00410", "阿玫", "市场", 3, 90],
      ["00526", "阿柏", "研发", 9, 270],
      ["00638", "阿棠", "财务", 5, 150]
    ]
  }]
}'
```

**备选形态（cmd.exe，推荐把 JSON 存成文件再传）**：先把上面 `'...'` 内的 JSON 原文保存为 `workbook-payload.json`，然后：

```bat
lark-cli sheets +workbook-create --title "9 月加班餐费台账" --sheets @workbook-payload.json
```

**理由**：`+workbook-create` 是“建表 + 类型保真写入”一步完成的官方快捷方式（帮助：“type-faithful one-step create + write”）；用 `--sheets` 而非 `--values`，因为 `--values` 是无类型写入（帮助：“values are written as-is with their type auto-detected”），无法保证工号文本与数值列类型，而 `--sheets` 按列 dtype 保真写入。
**格式说明（对应要求①）**：
- `dtypes.工号 = "string"` → 文本格式 `@`，`00183` 前导 0 保留（schema 原文见上表）；
- `dtypes.加班次数 / 餐费合计（元） = "int64"` → number，12/360 等按**数值**写入；
- 未传 `header`/`start_cell` → 按默认：`overwrite` 模式写一行列名表头、起点 `A1`（schema：“header…overwrite→true”、“start_cell 默认 A1”）。
**返回值占位**：`<SPREADSHEET_TOKEN>` ← 本命令返回 JSON 的 `spreadsheet_token` 字段（来源见「口径约定」表）。

---

### 步骤 2 — 取子表 `sheet_id`（read）

```bash
lark-cli sheets +workbook-info --spreadsheet-token '<SPREADSHEET_TOKEN>'
```

**理由**：步骤 5 的 CSV 导出**硬性要求 `--sheet-id`**（帮助原文：“csv mode requires `--sheet-id`”），该命令返回每张子表的 `sheet_id`/`title` 等（帮助 Tips：“First step for every sheets task — capture sheet_id from the result”）。
**返回值占位**：`<SHEET_ID>` ← 返回中 `title` 为 `餐费台账` 的那条记录的 `sheet_id` 字段。

---

### 步骤 3 — 数据末尾追加合计行（write，只碰第 8 行）

**正确数字**：加班次数总和 = 12+7+15+3+9+5 = **51**；餐费总和 = 360+210+450+90+270+150 = **1530**（交叉验证：每行金额 = 次数×30 元，51×30 = 1530 ✓）。
**行号推导**：步骤 1 写入 = 表头第 1 行 + 数据第 2–7 行 → 合计行 = **第 8 行**（A8）。

```bash
lark-cli sheets +cells-set \
  --spreadsheet-token '<SPREADSHEET_TOKEN>' \
  --sheet-name '餐费台账' \
  --range 'A8:E8' \
  --cells '[[{"value":"合计"},{},{},{"value":51},{"value":1530}]]' \
  --allow-overwrite=false
```

**cmd.exe 备选**：`--cells` 的 JSON 同样可存文件后 `--cells @total-row.json`（帮助标注 supports @file）。

**理由**：`+cells-set` 对单元格做增量写入（schema：“所有字段均为增量更新”）；本次写入范围**仅第 8 行**，物理上不可能改到第 2–7 行的已有 6 行（对应要求②“不得重写”）。
**格式说明**：
- `--cells` 维度必须与 range 严格一致：`A8:E8` → 1 行 × 5 格（schema：“'A1:C2'→[[_,_,_],[_,_,_]]”）；
- B8/C8 传 `{}` = **不修改**（schema 原文：“不修改的单元格填 {}”），保持为空；
- `51`/`1530` 以 JSON 数值传入 → 写成数值（内容字段 `value` 接受数字/文本）；
- `--allow-overwrite=false` 是双保险：帮助口径 “set false to error if any target cell is non-empty”——若第 8 行意外已有内容会**报错拒写**而不是覆盖。
**可选变体（公式版）**：若希望合计随数据变动，把两个数值换成公式字段（schema：“formula（公式，以 = 开头）”）：`{"formula":"=SUM(D2:D7)"}`、`{"formula":"=SUM(E2:E7)"}`。默认清单按题目“给出正确数字”用字面值 51/1530，CSV 导出所见即所得。

---

### 步骤 4 — 回读自检（read，建议执行）

```bash
lark-cli sheets +cells-get \
  --spreadsheet-token '<SPREADSHEET_TOKEN>' \
  --sheet-name '餐费台账' \
  --range 'A1:E8'
```

**理由**：写入后回读确认（`+cells-set` 帮助 Tips 即要求 “read back to confirm what applied”）：核对第 1 列为 `00183` 等文本、D8=51、E8=1530、第 2–7 行未被改动，再导出。

---

### 步骤 5 — 导出该子表为 CSV 到 `./sep-meal.csv`（read）

```bash
lark-cli sheets +workbook-export \
  --spreadsheet-token '<SPREADSHEET_TOKEN>' \
  --file-extension csv \
  --sheet-id '<SHEET_ID>' \
  --output-path ./sep-meal.csv
```

**理由**：`+workbook-export` 负责导出+轮询+下载一条龙（帮助：“Export a spreadsheet to xlsx or a single sheet to csv (async + poll + optional download)”）。
**本地路径规则（帮助原文口径）**：
- `--output-path` 传**具体文件路径**（官方示例即 `./out.xlsx` 形式，`./sep-meal.csv` 为相对当前工作目录）；或传**目录**（`.` 则保留服务器提供的文件名）；
- **省略该参数则只触发导出任务、不下载**（仅返回 file_token/status）——所以要带上；
- csv 模式必须同时给 `--sheet-id`（步骤 2 的占位符），`--file-extension csv`；
- 帮助 Tips：轮询有界；若导出仍未完成会返回“续传引用”（file_token/status）而非死等，按返回提示续跑/重跑同一命令即可下载。
**预期输出**：本地文件 `./sep-meal.csv`（8 行：表头 + 6 行数据 + 1 行合计）。

---

## 最终成果与校验

**线上表格**：`9 月加班餐费台账`（云空间根目录），子表 `餐费台账`，A1:E8：

| | A | B | C | D | E |
|---|---|---|---|---|---|
| 1 | 工号 | 姓名 | 部门 | 加班次数 | 餐费合计（元） |
| 2 | 00183（文本@） | 阿岚 | 研发 | 12（数值） | 360（数值） |
| 3 | 00241（文本@） | 阿荔 | 设计 | 7 | 210 |
| 4 | 00377（文本@） | 阿松 | 研发 | 15 | 450 |
| 5 | 00410（文本@） | 阿玫 | 市场 | 3 | 90 |
| 6 | 00526（文本@） | 阿柏 | 研发 | 9 | 270 |
| 7 | 00638（文本@） | 阿棠 | 财务 | 5 | 150 |
| 8 | 合计 | | | **51** | **1530** |

**`./sep-meal.csv` 预期内容**：

```csv
工号,姓名,部门,加班次数,餐费合计（元）
00183,阿岚,研发,12,360
00241,阿荔,设计,7,210
00377,阿松,研发,15,450
00410,阿玫,市场,3,90
00526,阿柏,研发,9,270
00638,阿棠,财务,5,150
合计,,,51,1530
```

**给财务的提示**：CSV 文件里工号就是文本 `00183`（前导 0 在文件中真实存在）；若用 Excel 直接双击打开 CSV，Excel 显示层可能把前导 0 吞掉——用记事本或导入向导（列类型选“文本”）核验即可，数据本身无损。

---

## 附录：本机核实记录（本清单语法可靠性的依据）

以下为本会话实际运行过的核实命令与关键结论（均未执行任何写操作）：

| # | 实测命令 | 关键输出/结论 |
|---|---|---|
| 1 | `where lark-cli` + `lark-cli --help` | CLI 存在（npm 全局）；`sheets` 域=“Spreadsheet operations”；帮助给出 quickstart：优先 `+shortcut`、`schema` 查参、风险三级 read/write/high-risk-write（后者才需 `--yes`）、`--dry-run` 预览不执行 |
| 2 | `lark-cli --version` | `lark-cli version 1.0.97` |
| 3 | `lark-cli sheets --help` | 存在 `+workbook-create`/`+cells-set`/`+workbook-info`/`+workbook-export`/`+cells-get`/`+csv-get` 等快捷方式 |
| 4 | `lark-cli sheets +workbook-create --help` | flag：`--title`（required）、`--sheets`（typed JSON，同 +table-put 形状，supports @file）、`--values`（untyped，类型自动探测）、`--folder-token`（省略=根目录）；Risk: write |
| 5 | `lark-cli sheets +workbook-create --print-schema --flag-name sheets` | dtype 规则原文：“int*/float*→number（精度保留）”、“object/string/category/未识别 → string + 文本格式 `@`（数字样字符串如「00123」不会塌缩成数字）”；`header` 默认 overwrite→true；`start_cell` 默认 A1；必填 `name`/`columns`/`data` |
| 6 | `lark-cli schema sheets.spreadsheets.create` | outputSchema 含 `data.spreadsheet.{spreadsheet_token,url,title,folder_token}` —— 占位符 `<SPREADSHEET_TOKEN>` 的来源 |
| 7 | `lark-cli sheets +cells-set --help` | flag：`--spreadsheet-token` XOR `--url`；`--sheet-name` XOR `--sheet-id`（二选一必填）；`--range`+`--cells`；`--allow-overwrite` 默认 true、false=非空即报错；Risk: write |
| 8 | `lark-cli sheets +cells-set --print-schema --flag-name cells` | 维度必须与 range 严格一致（`A8`→`[[_]]`）；“不修改的单元格填 {}”；内容字段四选一 `value`/`formula`（以 `=` 开头）/`rich_text`/`multiple_values`；全字段增量更新 |
| 9 | `lark-cli sheets +cells-set --print-schema --flag-name writes` | 多区域项必须**每项自带** `sheet_name`/`sheet_id`（schema 注明“不认顶层 sheet 定位”）——因此主清单改用单区域 `--range A8:E8` 写法 |
| 10 | `lark-cli sheets +workbook-info --help` | 返回 `sheet_id`/`title`/dimensions 等；Risk: read；Tips 建议作为 sheets 任务第一步 |
| 11 | `lark-cli sheets +workbook-export --help` | `--file-extension`（xlsx\|csv，csv 必须 `--sheet-id`）；`--output-path` 省略=不下载；传具体路径或目录；有界轮询+续传引用；Risk: read |
| 12 | `lark-cli sheets +cells-get --help` | 回读命令：`--range`（required）+ `--sheet-name`/`--sheet-id` + token/url；Risk: read |
| 13 | `lark-cli profile list` | `[]` —— 本机无任何 profile |
| 14 | `lark-cli whoami` | exit 3，`not_configured`（详见文首“开始前必读”） |
| 15 | 三条 `--dry-run` 预检（create/cells-set/workbook-export） | 全部在配置检查处被拦（exit 3，`not_configured`），**未能验证到请求体层**；载荷结构改由 #5/#8/#9 的 `--print-schema` 逐字段校验 |

**诚实声明**：步骤 0–5 的完整链路未在任何环境实际执行过（本机认证缺失所致）；本清单的可靠性 = 官方帮助/Schema 逐条核实 + 载荷经 `--print-schema` 校验，不含任何臆造 flag。
