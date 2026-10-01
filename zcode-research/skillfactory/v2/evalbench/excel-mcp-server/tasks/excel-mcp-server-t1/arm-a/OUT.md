# Excel MCP 任务 T1 — 销售流水表（arm-a 交付）

> 资产：`excel-mcp-server`（haris-musa）v**1.1.1**，按 `..\..\..\ASSET-DOC.md` 的方法经 `uvx excel-mcp-server stdio` 调用。
> **本文所有工具调用与读回结果均为 2026-09-29 在本机实际执行所得**（非纸上推演），执行方式与证据见 §5。
> Sheet 名「流水」，第 1 行表头，第 2–13 行为 12 行数据，第 14 行汇总——与任务要求一致。

---

## 1. 完整工具调用序列

前置：MCP stdio 握手（`initialize` → `notifications/initialized`），服务器以
`uvx excel-mcp-server stdio --allow-dir <工作簿目录>` 启动；`path` 使用该目录下相对路径即可（ASSET-DOC §7 通用参数）。

### 第 1 步 · 建工作簿（工作表直接命名为「流水」）

```json
{ "name": "create_workbook", "arguments": { "path": "sales-2026-09.xlsx", "sheets": ["流水"] } }
```

> 用 `sheets: ["流水"]` 一步建出正确表名，避免先建 `Sheet1` 再 `rename_sheet`（ASSET-DOC §7.2：重命名不更新引用旧名的公式）。

### 第 2 步 · 第 1 行写入表头

```json
{ "name": "write_range", "arguments": {
    "path": "sales-2026-09.xlsx", "sheet": "流水", "start_cell": "A1",
    "rows": [["日期", "品名", "数量", "单价", "金额"]] } }
```

### 第 3 步 · A2 起写入 12 行数据

```json
{ "name": "write_range", "arguments": {
    "path": "sales-2026-09.xlsx", "sheet": "流水", "start_cell": "A2",
    "rows": [
      ["2026-09-01", "笔记本", 3, 45, 135],
      ["2026-09-01", "签字笔", 20, 2.5, 50],
      ["2026-09-02", "A4纸", 10, 18, 180],
      ["2026-09-03", "订书机", 2, 25, 50],
      ["2026-09-05", "笔记本", 5, 45, 225],
      ["2026-09-08", "便利贴", 8, 6, 48],
      ["2026-09-10", "签字笔", 15, 2.5, 37.5],
      ["2026-09-12", "文件夹", 12, 9, 108],
      ["2026-09-15", "A4纸", 6, 18, 108],
      ["2026-09-18", "白板笔", 9, 5, 45],
      ["2026-09-22", "订书钉", 4, 8, 32],
      ["2026-09-26", "便利贴", 10, 6, 60]
    ] } }
```

> 按数据原文照录：`"2026-09-01"` 形式字符串由服务器自动存为日期（ASSET-DOC §7.3 值规则，实测读回 ISO 8601 `2026-09-01T00:00:00`）；数量/单价/金额为数字原样写入；金额列为给定数值，不拆成 `=C*D` 公式。

### 第 4 步 · E14 写入汇总公式

```json
{ "name": "write_range", "arguments": {
    "path": "sales-2026-09.xlsx", "sheet": "流水", "start_cell": "E14",
    "rows": [["=SUM(E2:E13)"]] } }
```

**实测结果**：4 次调用全部成功（`isError: false`）。随后 `read_range`（values 模式）整表读回为 `A1:E13` 共 13 行，逐格与上表一致，12 行数据无缺无错。

---

## 2. E14 的公式原文

```excel
=SUM(E2:E13)
```

对第 2–13 行（12 笔流水）的金额列求和。

---

## 3. 手工验算：12 行金额合计

逐行累加（running total）：

| 行 | 品名 | 金额 | 累计 |
|---|---|---|---|
| 1 | 笔记本 | 135 | 135 |
| 2 | 签字笔 | 50 | 185 |
| 3 | A4纸 | 180 | 365 |
| 4 | 订书机 | 50 | 415 |
| 5 | 笔记本 | 225 | 640 |
| 6 | 便利贴 | 48 | 688 |
| 7 | 签字笔 | 37.5 | 725.5 |
| 8 | 文件夹 | 108 | 833.5 |
| 9 | A4纸 | 108 | 941.5 |
| 10 | 白板笔 | 45 | 986.5 |
| 11 | 订书钉 | 32 | 1018.5 |
| 12 | 便利贴 | 60 | **1078.5** |

**合计 = 1078.5 元。**

交叉验算（已实测运行）：12 行逐行 `数量 × 单价` 与给定金额全部相等（Python 校验输出 `per-row qty*price == 金额: True`），12 行金额求和输出 `1078.5`。

**实测印证**：工作簿经 LibreOffice 重算保存后，用本 MCP 工具以 values 模式读回 `E14` 得 **`1078.5`**，与手工验算一致。

---

## 4. 写入公式后立即用该 MCP 工具读回 E14，会读到什么？为什么？

**答案：用默认的 `read_range`（`mode: "values"`）读回是 `null`（空值）；改用 `mode: "formulas"` 则读到公式原文 `"=SUM(E2:E13)"`。**

两者均为本次实测输出：

```
read_range { sheet:"流水", range:"E14:E14", mode:"values"   }  →  {"values": [[null]]}
read_range { sheet:"流水", range:"E14:E14", mode:"formulas" }  →  {"values": [["=SUM(E2:E13)"]]}
```

**为什么**：excel-mcp-server 基于 openpyxl，只负责把公式**存储**进 `.xlsx`，没有计算引擎，写入时也不会为公式生成缓存结果值（ASSET-DOC §9「公式只存储不计算」）。而 `.xlsx` 里公式单元格的"值"本来就是 Excel 上次保存时缓存的计算结果——本服务器刚写入的公式还没有任何程序为它算过并保存，因此 values 模式读到 `null`。只有当文件被 Excel/LibreOffice 打开（重算）并保存后，缓存值才存在，values 模式才能读到 `1078.5`。

本任务的加分验证恰好证实了这一点：用 LibreOffice 无头模式重算另存后，再经本 MCP 工具读回——values 模式变为 `1078.5`，formulas 模式仍是 `"=SUM(E2:E13)"`。

附带一个实测细节：公式刚写入时整表 values 模式读回的已用区域是 `A1:E13` 而非 `A1:E14`——E14 只有公式没有值，不计入值视图的已用区域。

---

## 5. 实测记录

- 环境：Windows Server 2022 x64；`uvx 0.12.15`；`excel-mcp-server 1.1.1`（uvx 自动拉取，`initialize` 应答 `serverInfo.version = "1.1.1"`）。
- 执行命令：
  - `uvx excel-mcp-server stdio --allow-dir <本目录>`，以 MCP JSON-RPC（`tools/call`）依次执行 §1 的 4 步 + 3 次 `read_range` 验证——脚本 `run_mcp.py`，逐调用原始应答存于 `mcp-transcript.jsonl`。
  - 交叉验算：`python -c` 逐行 `数量×单价==金额` 校验与求和。
  - 重算验证：`"C:\Program Files\LibreOffice\program\soffice.com" --headless --convert-to xlsx --outdir recalc sales-2026-09.xlsx`，随后 `read_recalc.py` 经真实 MCP 服务器读回 `recalc/sales-2026-09.xlsx` 的 E14。
- 本目录产物清单：
  - `OUT.md`（本文，交付物）
  - `sales-2026-09.xlsx`（按 §1 序列生成的流水表，E14 为未重算公式）
  - `recalc/sales-2026-09.xlsx`（LibreOffice 重算版，E14 值为 1078.5）
  - `run_mcp.py` / `read_recalc.py` / `mcp-transcript.jsonl`（执行脚本与逐调用记录）

## 备注

- ASSET-DOC 所述工具名、参数与行为（`create_workbook`/`write_range`/`read_range`、日期自动转换、公式安全与"只存储不计算"限制）与 v1.1.1 实测一致，**未发现说明与任务冲突之处**。
- 会话内未直接挂载 Excel MCP 工具，故按 ASSET-DOC 的标准方式（uvx + stdio + MCP JSON-RPC）自行驱动真实服务器完成全部调用与读回验证；上文所有"读到什么"均为该真实调用链的输出，非推测。
