# filesystem — 文件访问 MCP（办公文件场景底座）

> 目录实录：A4.1 参考实现与框架 · https://github.com/modelcontextprotocol/servers · `skillfactory/v2/CATALOG.md:187`
> 形态注记：MCP 官方参考 server 集（7 个，含 Filesystem）；stdio；npm 包 `@modelcontextprotocol/server-filesystem`（2026.8.31 实测在架）。目录注记：README 自述教学示例非生产，但 Filesystem 为社区事实标准。

## 安装前提

- Node.js ≥ 18 与 npm（本机实测 Node v22.23.2 / npm 10.9.8 可用），无需预装：`npx -y` 首次运行自动拉包。
- 无需任何密钥。

## 配置步骤

1. 选定授权根目录（agent 只能访问它），设为环境变量 `OFFICE_FS_ROOT`，如 `set OFFICE_FS_ROOT=D:\workspace\office-docs`。
2. 使用本包 `mcp.office.json` 中的 `filesystem` 条目，或手工写入项目 `.mcp.json`：

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:\\workspace\\office-docs"]
    }
  }
}
```

3. Claude Code 中执行 `/mcp` 确认 server 已连接（connect 状态）。

## 常用调用

- `read_file` / `read_multiple_files`：读取文本类办公文件（md/txt/csv/json）。
- `write_file` / `edit_file`：新建或按精确文本替换改文件（改合同/公文初稿常用）。
- `list_directory` / `directory_tree`：盘点资料目录。
- `search_files`：按名搜索；`get_file_info`：看大小/时间。
- `create_directory` / `move_file`：资料归档整理。

## 注意事项

- 沙箱边界 = 启动参数里的根目录，路径穿越会被拒绝；不要把盘根设为 `OFFICE_FS_ROOT`。
- 官方 README 自述"教学示例非生产"（目录实录原文），重要资产建议叠加仓库级版本管理。
- 二进制格式（docx/xlsx）不是它的强项，走本包 `word`/`excel` 条目。
