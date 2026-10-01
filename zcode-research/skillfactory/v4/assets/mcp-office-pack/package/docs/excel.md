# excel — haris-musa 版 Excel MCP（openpyxl 系）

> **目录实录**：https://github.com/haris-musa/excel-mcp-server
> （`skillfactory/v2/CATALOG.md:198` · A4.3 任务域 server·办公协同）
> 本包实测（2026-09-30，Windows x64）：`excel-mcp-server 1.1.1`，协议 2025-03-26，**26 工具**。

## 安装前提

- Python 3.10+ 与 `uvx`（本机实测 uv 0.12.15）；PyPI 包名 `excel-mcp-server`，uvx 首跑自动拉取。
- 无需密钥。
- 准备一个工作簿沙箱目录（占位符 `${OFFICEPACK_EXCEL_DIR}`，如 `D:\office-docs\excel`），
  经 `EXCEL_FILES_PATH` 环境变量或 `--allow-dir` 参数传入；目录不存在时行为不可预期，务必先建目录。

## 配置步骤

1. 建沙箱目录并设环境变量：`set OFFICEPACK_EXCEL_DIR=D:\office-docs\excel`。
2. 并入本包 `excel` 条目（`uvx excel-mcp-server stdio`）到 `.mcp.json`。
3. **必须带 `stdio` 子命令**：1.x 起传输方式改为位置参数（`stdio` / `streamable-http`），
   裸跑 `excel-mcp-server` 会直接打印 usage 退出——这是本包实测踩到的第一个坑。
4. 会话内确认 `mcp__excel__*` 工具挂载。

## 常用调用

- `create_workbook` / `create_sheet` / `describe_workbook`：建簿建表与结构自查；
- `read_range` / `write_range`：区域读写（写公式亦经此通道，公式经白名单校验）；
- `find_cells` / `copy_range` / `merge_cells`：查找与区域操作；
- `format_range` / `add_conditional_format` / `add_data_validation`：样式、条件格式、数据校验；
- `create_chart` / `create_table` / `create_summary_table`：图表与结构化表格；
- `import_workbook` / `export_workbook` / `read_vba`：导入导出与 VBA 读取。

## 注意事项

- **安全设计是选型理由**：危险公式拦截 + 目录沙箱 + 只读模式，适合直接讲 MCP 工具安全；
  沙箱内路径用相对路径（如 `reports/q1.xlsx`），server 会以 `EXCEL_FILES_PATH` 为根解析。
- `.xlsm` 仅支持只读；写操作面向 `.xlsx`。
- 多目录用 `;`（Windows）/ `:`（macOS/Linux）分隔 `EXCEL_FILES_PATH`。
- 与本包 `excel-npm`（negokaz 版）为同一 catalog 行下的"两维护者版本并行收录"先例：
  本条强在写（公式/格式/图表），读重场景用 excel-npm 分页更省上下文。
