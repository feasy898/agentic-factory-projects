# excel — Excel 读写 MCP（haris-musa 版）

> 目录实录：A4.3 任务域 server·办公协同 · https://github.com/haris-musa/excel-mcp-server · `skillfactory/v2/CATALOG.md:198`
> 形态注记：MCP server；stdio；PyPI 包 `excel-mcp-server`（1.1.1，实测在架，uvx 分发）。目录注记：4.2k★，changelog 2026-09-28；安全设计（危险公式拦截+目录沙箱+只读模式）是 MCP 工具安全教学样本。

## 安装前提

- Python ≥ 3.10 与 `uv`/`uvx`（本机实测 uvx 0.12.15 可用），`uvx` 首次运行自动建环境拉包。
- 无需 Microsoft Excel（openpyxl 系，纯文件操作）。
- 无需密钥。

## 配置步骤

1. 建立工作簿专用目录并设 `OFFICE_EXCEL_DIR`（server 的目录沙箱，所有读写限制在该目录内）：
   `set OFFICE_EXCEL_DIR=D:\workspace\office-docs\excel`
2. 使用本包 `mcp.office.json` 的 `excel` 条目，等价手工配置：

```json
{
  "mcpServers": {
    "excel": {
      "type": "stdio",
      "command": "uvx",
      "args": ["excel-mcp-server", "stdio"],
      "env": { "EXCEL_FILES_PATH": "D:\\workspace\\office-docs\\excel" }
    }
  }
}
```

3. Claude Code `/mcp` 确认连接。

## 常用调用

- 读数据：读单元格/行/区域，大表分页读取；读公式与格式信息。
- 写数据：写值、写公式、建表、追加行。
- 结构操作：创建/复制/重命名工作表，区域样式、条件格式、图表。
- `.xlsm` 支持只读。

## 注意事项

- 目录沙箱：`EXCEL_FILES_PATH` 之外的路径一律拒绝——把敏感表放在沙箱外是正确姿势。
- 危险公式拦截：外部工作簿引用等危险公式会被拦（目录实录"公式白名单"），生产可再开只读模式（启动参数 `--transport`/只读开关见仓库 README）。
- 与同目录另一条目 negokaz 版（Go+npm，读重于写、带截图）互为互补，按"读为主还是写为主"选型。
