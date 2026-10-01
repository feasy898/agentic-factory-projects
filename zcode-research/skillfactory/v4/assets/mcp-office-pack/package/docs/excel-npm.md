# excel-npm — negokaz 版 Excel MCP（Go + npm 分发）

> **目录实录**：https://github.com/negokaz/excel-mcp-server
> （`skillfactory/v2/CATALOG.md:199` · A4.3 任务域 server·办公协同）
> 本包实测（2026-09-30，Windows x64）：`excel-mcp-server 0.12.0-SNAPSHOT`，协议 2025-03-26，**7 工具**。

## 安装前提

- Node.js ≥ 18 与 `npx`；npm 包名 **必须带 scope：`@negokaz/excel-mcp-server`**。
- 无需密钥、无需 Python。

## 配置步骤

1. 并入本包 `excel-npm` 条目（`npx -y @negokaz/excel-mcp-server`）到 `.mcp.json`。
2. 可选：设 `EXCEL_MCP_PAGING_CELLS_LIMIT` 调整单页读取格数（默认 4000）——经 README 核实
   这是该包唯一文档化配置项。
3. 会话内确认 `mcp__excel-npm__*` 工具挂载（首跑含拉包，实测 37s 内完成握手）。

## 常用调用

- `excel_read_sheet`：分页读取大表（默认单页 4000 格，防上下文爆炸）；
- `excel_write_to_sheet`：写值/写公式；
- `excel_create_table` / `excel_format_range` / `excel_copy_sheet`：建表、区域样式、复制表；
- `excel_describe_sheets`：工作表结构自查；
- `excel_screen_capture`：**工作表截图**，把表格渲染成图片"给 agent 看画面"（本条相对
  haris-musa 版的独有能力）。

## 注意事项

- **包名陷阱（spec §3.6 与实测一致）**：npm 上无 scope 的 `excel-mcp-server`（维护者 lichard）
  不是 negokaz 的包，其 Windows 启动器缺 pandas 会崩——装错包的典型症状是启动即退。
  认准 `@negokaz` scope。
- **无目录白名单参数**（与 haris-musa 版的关键差异，经 README 核实）：读哪个文件全由调用方
  给路径约束；安全上建议固定工作目录、传相对路径，并把敏感盘目录排除出会话可见范围。
- 定位是"读重型互补"：大表分页读与截图强；深度写（公式白名单/条件格式/图表）用本包 `excel`
  条目（haris-musa 版）。
- 7 个工具面小，与 `excel` 条目并存互不冲突，name 以 `excel` 前缀同占 Excel 槽位。
