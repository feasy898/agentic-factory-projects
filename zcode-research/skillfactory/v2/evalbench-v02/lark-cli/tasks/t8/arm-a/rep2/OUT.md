# 《9 月加班餐费台账》飞书电子表格（spreadsheet）录入 → 导出 CSV · 可直接按序执行的命令清单

> 目标：用 lark-cli 新建名为《9 月加班餐费台账》的**电子表格**（不是多维表格/base），写入表头 + 6 行数据（工号保留前导 0，次数与金额为数值），末尾追加「合计」行（不重写已有 6 行），最后导出 CSV 到 `./sep-meal.csv`。
> 本清单里每条命令的用法均已在本机用 `lark-cli <命令> --help` 与官方指南（`lark-cli skills read lark-sheets` 及其 references）逐条核实，未核实过的命令/flag 一律不出现。文中所有「返回值」均为**占位符**，来源在其后标注。

---

## 0. 使用前提与全局约定

1. **Shell**：按 Windows cmd.exe 语法给出（本机默认 shell）。若改用 Git Bash / PowerShell，只需把 `%变量%` 换成 `$变量` / `$env:变量`，其余命令完全一致（所有 JSON 都走 `@file`，不受 shell 引号规则影响——官方指南明确：cmd.exe 下不要内联 JSON，cmd 会吃掉内层双引号，一律走 `@file`）。
2. **`@file` 路径规则**：CLI 的 `@file` 只接受**当前目录的相对路径**（如 `@./sheets-payload.json`），绝对路径会被拒绝。所以第 1 步前先 `cd /d` 到存放 JSON 的目录，后续所有命令（包括导出的 `./sep-meal.csv`）都在该目录执行。
3. **JSON 文件编码**：含中文，保存为 **UTF-8（无 BOM）**（记事本「另存为」右下角编码选 UTF-8）。
4. **风险级别**：清单中只有 write（第 1、4、7 步）与 read（其余）级别命令，**无 high-risk-write，全程不需要 `--yes`**。任何一步想先看请求内容，可在命令后加 `--dry-run`（零副作用，只打印请求不执行）。
5. **占位符约定**：
   - `%SPREADSHEET_TOKEN%` ← 第 1 步 `+workbook-create` 返回 JSON 中的电子表格 token（同一响应里也给出新表 URL，token 即 URL 中 `/sheets/` 后那一段；以实际返回字段为准）。
   - `%SHEET_ID%` ← 第 2 步 `+workbook-info` 输出 `sheets[]` 数组中 `title` 为 **台账** 的那条记录的 `sheet_id` 字段（官方输出契约：`sheets[]` 每项含 `sheet_id` / `title` / `index` / `resource_type` / `row_count` 等）。
6. 表名说明：题目中《9 月加班餐费台账》是工作簿名，写入 `--title` 时取书名号内文字 `9 月加班餐费台账`（书名号是中文书名引号，不属于名字本身）。子表名自定为 **台账**（后面命令里的 `--sheet-name "台账"` 与 payload 里的 `"name": "台账"` 必须一致；如想改名，全部同步替换）。

### 步骤总览

| 步 | 命令 | 作用 | 风险 |
|---|---|---|---|
| 0 | `lark-cli whoami` | （可选）自检认证 | read |
| 1 | `+workbook-create` | 新建《9 月加班餐费台账》并一次写入表头 + 6 行 | write |
| 2 | `+workbook-info` | 取子表 `sheet_id`（CSV 导出必须用它） | read |
| 3 | `+csv-get` A1:E8 | 回读校验：表头/6 行/前导零/第 8 行为空 | read |
| 4 | `+cells-set` A8:E8 `--allow-overwrite=false` | 追加「合计」行（公式求和，防覆盖） | write |
| 5 | `+formula-verify` D8:E8 | 公式诊断（写公式后的必做验证） | read |
| 6 | `+csv-get` A8:E8 | 回读合计值 = 51 / 1530 | read |
| 7 | `+dim-freeze` --rows 1 | （可选）冻结表头行 | write |
| 8 | `+workbook-export` csv → `./sep-meal.csv` | 导出 CSV 给财务 | read |

---

## 1. 第 0 步：准备两个 JSON 载荷文件（cmd.exe 不内联 JSON，先落盘）

在执行目录下用编辑器分别新建以下两个文件（UTF-8 无 BOM）。

**文件一：`sheets-payload.json`**（建表 + 类型保真写入的载荷）

```json
{
  "sheets": [
    {
      "name": "台账",
      "header": true,
      "columns": ["工号", "姓名", "部门", "加班次数", "餐费合计（元）"],
      "dtypes": { "工号": "object", "加班次数": "int64", "餐费合计（元）": "int64" },
      "formats": { "工号": "@" },
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

**文件二：`total-row-cells.json`**（合计行载荷，1 行 × 5 格）

```json
[
  [
    { "value": "合计" },
    { },
    { },
    { "formula": "=SUM(D2:D7)" },
    { "formula": "=SUM(E2:E7)" }
  ]
]
```

载荷字段依据（均出自官方 `+table-put`/`+workbook-create --sheets` 的 JSON Schema 与指南，两命令协议完全同构）：

- `工号` 按什么格式写入（**要求①**）：**按文本写入**。三层保证：① JSON 里工号带引号以字符串字面量传入（`"00183"`）；② `dtypes["工号"]="object"`，CLI 端把 object 映射为内部 string 类型；③ `formats["工号"]="@"` 即单元格数字格式设为「文本」（string 列缺省本来就是 `@`，这里显式写出以自证）。官方指南明文规定：编号 / 前导零这类**标识符**必须走字符串 + 文本格式，否则 `001` 会被自动数值化成 `1`——这正是题目要求保留前导 0 的场景。
- `加班次数`、`餐费合计（元）` 按数值写入（**要求①**）：`dtypes` 声明 `int64`，data 里直接写 JSON 数字（`12`、`360`，不带引号、不带千分位），落表为真数值，可排序、可求和。
- `header: true` 且未传 `mode`（默认 `overwrite`）：从 A1 起写「表头 + 数据」块 → 第 1 行表头、第 2–7 行 6 条数据（这就是后面合计行落在第 8 行的依据）。
- 合计行里 `{}` 的语义是「该格不做任何修改、保留原状」，即 B8/C8 保持空白；`value`/`formula` 只写 A8、D8、E8。
- 为什么合计用公式而不是静态数字：官方编辑准则「可推导值写落格公式，不用静态值代替」。公式计算结果就是要求给出的正确数字：**D8 = 51，E8 = 1530**（验算见第 3 节）。若财务明确要静态数字，把两个 `{"formula": …}` 换成 `{"value": 51}` 和 `{"value": 1530}` 即可，其余不变。

---

## 2. 按序执行的命令清单

### 第 0 步（可选）自检认证

```bat
lark-cli whoami
```
理由：题目声明已安装并认证，此命令只读输出当前身份与 token 状态，执行前快速自检一下。

### 第 1 步：新建工作簿 + 一次写入表头与 6 行数据（要求①）

```bat
cd /d <你的执行目录>
lark-cli sheets +workbook-create --title "9 月加班餐费台账" --sheets @./sheets-payload.json
```
理由：`+workbook-create --sheets` 是官方「一步建表 + 类型保真写入」的首选路径（`+table-put` 只能写已存在的表，`--values` 会把数字落成文本，都不合适）。

- 执行成功后：云空间出现《9 月加班餐费台账》；新工作簿的默认子表被复用并改名为「台账」，**不会残留空 Sheet1**；A1:E1 表头、A2:E7 六行数据。
- **占位符采集**：把返回 JSON 中的电子表格 token 存下来（来源见第 0 节约定），下一步要用。

### 第 2 步：查子表结构，采集 `SHEET_ID`

```bat
set "SPREADSHEET_TOKEN=<第 1 步返回的电子表格 token>"
lark-cli sheets +workbook-info --spreadsheet-token %SPREADSHEET_TOKEN%
set "SHEET_ID=<本命令输出 sheets[] 中 title=="台账" 项的 sheet_id 字段>"
```
理由：官方规定任何 sheet 级操作前先 `+workbook-info` 确认真实子表与 `sheet_id`（禁止猜 Sheet1）；且 CSV 导出只认 `--sheet-id`、不接受 `--sheet-name`。
预期：`sheets[]` 里只有一张子表：`title` 为「台账」、`resource_type` 为 `sheet`、未隐藏。

### 第 3 步：回读校验数据落位（写后必做验证）

```bat
lark-cli sheets +csv-get --spreadsheet-token %SPREADSHEET_TOKEN% --sheet-name "台账" --range "A1:E8"
```
理由：官方准则「返回 ok 只表示请求成功」，写后必须回读首/中/末抽样核对；这一步同时确认两件事——A 列前导零仍在（如 `[row=2]` 显示 `00183` 而不是 `183`），以及**第 8 行确实全空**（合计行的落点，写前核清目标区域不含原始数据）。
预期：`[row=1]` 为表头；`[row=2]`–`[row=7]` 为 6 条记录；`[row=8]` 为空。

### 第 4 步：末尾追加「合计」行（要求②，不重写已有 6 行）

```bat
lark-cli sheets +cells-set --spreadsheet-token %SPREADSHEET_TOKEN% --sheet-name "台账" --range "A8:E8" --cells @./total-row-cells.json --allow-overwrite=false
```
理由：在数据末行 A8:E8 一次写入「合计」+ 两个 `=SUM` 公式；`--allow-overwrite=false` 时写入区内**任一格非空即整体报错拒写**，从机制上保证绝不会重写已有 6 行（若此步报错，说明第 8 行并非空——先回读排查，不要改回默认的覆盖模式硬写）。
说明：A8 写文本「合计」；D8=`=SUM(D2:D7)`、E8=`=SUM(E2:E7)`（引用第 2–7 行数据区，不含表头、不含自身，无循环引用风险）；B8/C8 用 `{}` 占位保持空白。本命令为 write 级别，无需 `--yes`。

### 第 5 步：公式诊断（写公式后的必做验证）

```bat
lark-cli sheets +formula-verify --spreadsheet-token %SPREADSHEET_TOKEN% --sheet-name "台账" --range "D8:E8" --exit-on-error
```
理由：官方硬性要求：只要写入了公式，就必须对目标范围跑 `+formula-verify --exit-on-error`——后端可能对语法/运行错误返回「成功」，错误会静默变成 `#VALUE!` 等；`status=success` 且退出码为 0 才算通过。

### 第 6 步：回读合计值（要求②给出正确数字）

```bat
lark-cli sheets +csv-get --spreadsheet-token %SPREADSHEET_TOKEN% --sheet-name "台账" --range "A8:E8"
```
理由：核对落表计算结果与预期一致：A8=`合计`、D8=`51`、E8=`1530`。

### 第 7 步（可选）：冻结表头行

```bat
lark-cli sheets +dim-freeze --spreadsheet-token %SPREADSHEET_TOKEN% --sheet-name "台账" --rows 1
```
理由：官方 sheets 指南约定「加汇总行」这类改变表长的任务收尾把表头行冻住，方便财务滚动查看；不传 `--cols` 即不冻结任何列。题目未要求，故标为可选。

### 第 8 步：导出 CSV 到 `./sep-meal.csv`（要求③）

```bat
lark-cli sheets +workbook-export --spreadsheet-token %SPREADSHEET_TOKEN% --file-extension csv --sheet-id %SHEET_ID% --output-path ./sep-meal.csv
```
理由：题目要求单子表 CSV 交付；`+workbook-export` 的 csv 模式**必须**传 `--sheet-id`（这是该命令的专有 flag，不接受公共四件套的 `--sheet-name`），命令内置异步导出 + 轮询，返回即含下载结果。

**`--output-path` 的本地路径规则**（官方帮助原文归纳，三条互斥语义）：

| 传法 | 行为 |
|---|---|
| 省略 | 只触发并轮询导出任务，**不下载**（返回 `file_token`/`status`，供稍后续传下载） |
| 具体路径（如 `./sep-meal.csv`，相对当前目录） | 下载并保存为该路径指定的文件 ← **本清单采用** |
| 目录（如 `.`） | 下载到该目录，文件名保留服务端生成的名字 |

所以必须传具体路径 `./sep-meal.csv`，才能精确得到这个文件名；文件落在第 1 步 `cd` 的工作目录。

---

## 3. 合计行数字（口径与验算）

| 项目 | 计算 | 结果 |
|---|---|---|
| 加班次数总和 | 12 + 7 + 15 + 3 + 9 + 5 | **51** |
| 餐费合计总和 | 360 + 210 + 450 + 90 + 270 + 150 | **1530** |

交叉校验：每行餐费恰为次数 × 30 元（如 12×30=360），故总和 51×30=1530，两列口径自洽。落表用 `=SUM(D2:D7)` / `=SUM(E2:E7)` 公式得出，第 6 步回读应看到 51 / 1530。

---

## 4. 执行后验收清单

- [ ] 第 1 步返回成功，云空间根目录出现《9 月加班餐费台账》。
- [ ] 第 3 步回读：第 1 行 = 表头 5 列；第 2–7 行 = 6 条记录；**A2=00183、A5=00410、A7=00638 等前导零完好**；A8:E8 全空。
- [ ] 第 5 步 `status=success`、退出码 0（无公式错误）。
- [ ] 第 6 步回读：A8=`合计`、D8=`51`、E8=`1530`。
- [ ] （若执行第 7 步）表头行已冻结。
- [ ] 第 8 步后 `./sep-meal.csv` 存在、可打开，内容为 8 行且与线上一致。

---

## 5. 本清单的核实依据（本次会话实际执行的核实动作）

- `lark-cli --help`：确认域划分，电子表格操作在 `sheets` 域（非 `base` 多维表格域）。
- `lark-cli sheets --help`：确认 `+workbook-create` / `+workbook-info` / `+csv-get` / `+cells-set` / `+formula-verify` / `+dim-freeze` / `+workbook-export` 七个 shortcut 均真实存在及其风险级别。
- 逐条 `--help` 核实（全部实际执行）：`+workbook-create`（`--title` 必填、`--sheets` typed 协议、与 `--values` 互斥）、`+cells-set`（`--range`+`--cells`、`--allow-overwrite` 默认 true/设 false 遇非空报错）、`+workbook-export`（csv 模式必填 `--sheet-id`、`--output-path` 三种路径语义）、`+table-put`（`--sheets` 字段 schema：`name/header/mode/columns/data/dtypes/formats`）、`+workbook-info`、`+csv-get`（`[row=N]` 行前缀）、`+formula-verify`（`--exit-on-error`、`--range`）、`+dim-freeze`（`--rows`）。
- 官方指南 `lark-cli skills read lark-sheets` 及其 `references/lark-sheets-write-cells.md`、`references/lark-sheets-workbook.md`：前导零/数值列的 dtypes+formats 规则、`{}` 占位语义、计算值写公式准则、@file 与 cmd.exe 适配规则、`+workbook-info` 输出契约、新建工作簿复用默认子表的说明。
- **未执行**的部分：上述 0–8 步的实际写表/导出操作未运行——本任务交付物是命令清单（返回值以占位符交付），飞书云端未产生任何新表；所有「预期返回」描述均来自上列官方文档的输出契约，非本机实测返回值。
