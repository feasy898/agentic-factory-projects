# 9 月加班餐费台账 —— lark-cli 可按序执行命令清单

> 交付物：把下表录入**飞书电子表格**（spreadsheet，非多维表格），追加合计行，并导出 CSV 给财务。
> 依据：本机 `lark-cli`（`lark-cli --version` → **1.0.97**）实测 `--help` / `--print-schema` / `lark-cli skills read lark-sheets`（SKILL.md v3.5.2 及 `references/lark-sheets-workbook.md`、`references/lark-sheets-write-cells.md`）核实全部命令与 flag，未编造任何用法。占位符统一用 `<大写>`，来源随条注明。

## 0. 环境核实（已在本机实际执行）

| 检查 | 命令 | 结果 |
|---|---|---|
| 版本 | `lark-cli --version` | `lark-cli version 1.0.97` ✅ |
| 认证 | `lark-cli auth status` | 本机返回 `{"ok":false,"error":{"type":"config","subtype":"not_configured"}}` ⚠️ |

⚠️ 本沙箱未完成 OAuth 配置；任务前提是"用户环境已认证"，故以下命令在其认证环境中执行即可。若执行前想再确认，先跑 **步骤 0**（只读、无副作用）。本次所有命令的 flag 与载荷均经 `--help` / `--print-schema` / 内嵌 skill 文档核实、JSON 载荷经 Python 解析校验，但**未做端到端真实写入**（本机无认证，如实注明）。

## 0.5 正确数字（步骤 3 直接写入）

- 加班次数总和：12+7+15+3+9+5 = **51**
- 餐费总和：360+210+450+90+270+150 = **1530**

（已用 Python 对 6 行原始数据求和交叉验证，与手算一致。）

---

## 命令清单（按序执行，bash 引号风格，同官方示例）

### 步骤 0（可选，只读）：确认登录态

```bash
lark-cli auth status
```

- **理由**：写操作前确认已认证、scope 可用，避免写到一半报 `authorization`。
- **返回**：`ok:true` 即可继续（来源：`lark-cli auth --help`，`auth check`/`auth status` 为只读命令）。

### 步骤 1：新建电子表格《9 月加班餐费台账》并一步写入表头 + 6 行数据（typed，类型保真）

```bash
lark-cli sheets +workbook-create --as user --title "9 月加班餐费台账" --sheets '{"sheets":[{"name":"9月台账","columns":["工号","姓名","部门","加班次数","餐费合计（元）"],"dtypes":{"工号":"string","姓名":"string","部门":"string","加班次数":"int64","餐费合计（元）":"int64"},"data":[["00183","阿岚","研发",12,360],["00241","阿荔","设计",7,210],["00377","阿松","研发",15,450],["00410","阿玫","市场",3,90],["00526","阿柏","研发",9,270],["00638","阿棠","财务",5,150]]}]}'
```

- **理由**：`+workbook-create --sheets` 是官方推荐的「建表 + typed 类型保真写入」一条龙（内嵌 workbook.md 原文："string 列保前导零（如订单号 00123）"、"number 不丢精度"），比建空表再写少一次往返。
- **写入格式说明（任务①核心）**：
  - **工号列（含前导零）**：按 **字符串（文本）** 写入——JSON 里写 `"00183"`（带引号），并把 `dtypes["工号"]` 显式声明为 `string`。`--print-schema` 原文：`object`/`string` 列落为 "string + 文本格式 `@`（数字样字符串如「00123」不会塌缩成数字）"；skill 速查同口径："日期标签、编号、前导零、身份证/单据号写文本"。这样单元格里就是文本 `00183`，导出 CSV 保留 `00183`。
  - **加班次数、餐费合计（元）**：按 **数值** 写入——JSON 里写裸数字 `12`、`360`（不带引号），`dtypes` 声明 `int64`（schema：`int*` → number，精度保留），可排序/求和。
  - `columns` 即表头行（schema：`header` 默认 true，列名落 A1:E1）；`--title` 是云空间里的工作簿名《9 月加班餐费台账》，`name:"9月台账"` 是子表名，两者独立。
- **返回占位符**：`<SPREADSHEET_TOKEN>` —— 来源：本步成功返回（信封 `ok:true`）的 `data` 中新表 token/URL 字段（同响应也会给 `url`，后续步骤亦可改用 `--url <SPREADSHEET_URL>` 等价定位；具体字段名以实际返回为准）。

### 步骤 2（只读）：列子表结构，取 CSV 导出必需的 `sheet_id`

```bash
lark-cli sheets +workbook-info --as user --spreadsheet-token <SPREADSHEET_TOKEN>
```

- **理由**：`+workbook-export` 的 csv 模式**只认专用 flag `--sheet-id`**（help 原文："Required only in csv mode… unrelated to the common four-tuple sheet locator"），而 sheet_id 只能从 `+workbook-info` 精确获取（workbook.md："不要手动拼写或从 URL 中猜测"）；同时顺带确认步骤 1 落表成功（应见 1 张可见 `sheet` 子表、约 7 行）。
- **返回占位符**：`<SHEET_ID>` —— 来源：本步返回 `sheets[]` 中 `title == "9月台账"` 条目的 `sheet_id` 字段（workbook.md 输出契约：`sheets[]` 每项含 `sheet_id`/`title`/`index`/`resource_type` 等；旧 payload 用 `sheet_name`，优先取 `title`）。

### 步骤 3：末尾**追加**合计行（不重写已有 6 行）

```bash
lark-cli sheets +table-put --as user --spreadsheet-token <SPREADSHEET_TOKEN> --sheets '{"sheets":[{"name":"9月台账","mode":"append","allow_overwrite":false,"columns":["工号","姓名","部门","加班次数","餐费合计（元）"],"dtypes":{"加班次数":"int64","餐费合计（元）":"int64"},"data":[["合计",null,null,51,1530]]}]}'
```

- **理由**：skill write-cells.md 明确"普通表尾追加直接用 `+table-put` 的 `mode:\"append\"`，它会**自动定位末行**"，故落到第 8 行（表头 1 行 + 数据 6 行之后），**完全不改写第 1–7 行**；`allow_overwrite:false` 加一道保险——若写入会落在非空单元格则直接拒写（schema 原文），从机制上排除覆盖；`header` 省略（append 模式默认 false，不重复表头）；`null` 即空单元格（B、C 列留空）；51、1530 按数值写入（`int64`）。
- **返回**：`ok:true` + 更新计数（来源：`+table-put --help`，输出契约同 §JSON 信封）。注意成功判定看 `ok == true`（或退出码 0），**不要**看 `code == 0`（ASSET-DOC §5.2）。

### 步骤 4（只读）：回读校验（前导零 + 合计行）

```bash
lark-cli sheets +csv-get --as user --spreadsheet-token <SPREADSHEET_TOKEN> --sheet-name "9月台账" --range A1:E8 --include-row-prefix false
```

- **理由**：skill 准则要求"写后用 `+csv-get`/`+cells-get` 验首、中、末"——"返回 ok 只表示请求成功"；重点核对首行 `00183` 未塌缩成 `183`、末行合计 `51`/`1530`。
- **预期回读**（8 行）：

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

### 步骤 5：导出 CSV 到本地 `./sep-meal.csv`

```bash
lark-cli sheets +workbook-export --as user --spreadsheet-token <SPREADSHEET_TOKEN> --file-extension csv --sheet-id <SHEET_ID> --output-path ./sep-meal.csv
```

- **理由**：`+workbook-export` 是官方导出捷径，csv 模式一次导一张子表（官方示例 #4 原样：`--file-extension csv --sheet-id "$SID" --output-path ./sheet.csv`）；命令内置"创建导出任务 + 轮询 + 下载"，带 `--output-path` 即落盘（省略则只建任务不下载）。
- **本地路径规则（任务③提示点）**：`--output-path` **只接受当前工作目录（cwd）下的相对路径**——`./sep-meal.csv` 合规；绝对路径（如 `D:\...\sep-meal.csv`）会被判 `unsafe file path` 拒绝（lark-shared 安全规则："--file、--output、--output-dir、@file 等仅接受 cwd 下相对路径"）。执行前请 `cd` 到目标目录。
- **返回**：`ok:true` + 导出任务状态/file_token；完成后本地 `./sep-meal.csv` 内容应与步骤 4 预期一致（工号列保持 `00183` 等文本）。

---

## 备注

1. **`--as user`**：全程显式指定，以登录用户身份操作（台账是用户云空间资产；skill 提醒 bot 身份访问用户资源可能"返回空成功而非报错"，故必须 user）。
2. **引号/转义**：以上为 bash 单引号风格（与官方示例一致）。PowerShell/cmd 下需改双引号并转义内部双引号；载荷大或嫌转义麻烦时，可把 JSON 存为 cwd 下文件走 `--sheets @./payload.json`（`@file` 同样只收相对路径），或 stdin（`--sheets -`）。
3. **合计行样式**（加粗/底色等）：skill 对"汇总行"有样式规范，但任务未要求美化，按"最小改动"准则不做，仅写值。
4. **成功判定**：所有步骤看 `ok == true` / 退出码；若遇退出码 10（`type:confirmation`）属高风险确认门禁，按契约向用户确认后把 `hint` 指出的确认 flag 追加到原命令末尾重试，不得静默绕过。
5. **失败排查**：`authorization` → 读错误信封 `missing_scopes` 补授权；`network` → 可安全重试；字段级契约见 `errs/ERROR_CONTRACT.md`（ASSET-DOC §7）。

## 口径冲突说明（按任务要求注明）

- ASSET-DOC / 内嵌 skill 的「公式优先」准则（write-cells.md："计算结果默认写公式，不写静态值"）与任务②"合计……（给出正确数字）"存在张力：`+table-put` **不支持公式字段**（write-cells.md 第 79 行明示），写公式需改 `+cells-set` 手工定位第 8 行并追加 `+formula-verify` 验证链。**以任务为准**：合计行按任务要求直接写入正确数字 51 / 1530（静态值），一次性餐费台账+导 CSV 场景下确定、可核对、导出即所得。
- 其余事项（命令、flag、前导零文本格式、数值类型、相对路径规则）均与 ASSET-DOC 及内嵌 skill 一致，无冲突。
