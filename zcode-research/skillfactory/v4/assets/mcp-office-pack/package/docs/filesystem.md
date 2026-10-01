# filesystem — MCP 官方参考 Filesystem server

> **目录实录**：https://github.com/modelcontextprotocol/servers
> （`skillfactory/v2/CATALOG.md:187` · A4.1 参考实现与框架）
> 本包实测（2026-09-30，Windows x64）：`secure-filesystem-server 0.2.0`，协议 2025-03-26，**14 工具**。

## 安装前提

- Node.js ≥ 18 与 `npx`（本机实测 Node v22.23.2 / npm 10.9.8）；npm 包为
  `@modelcontextprotocol/server-filesystem`，无需全局安装，`npx -y` 自动拉取。
- 无需任何密钥。
- 必须准备一个**真实存在**的授权目录（如 `D:\office-docs`）：server 启动时以目录为参数，
  目录不存在会拒绝启动。对应配置占位符 `${OFFICEPACK_FILES_ROOT}`。

## 配置步骤

1. 建好授权目录，例如 `mkdir D:\office-docs`。
2. 把本包 `mcp.office.json` 的 `filesystem` 条目并入 Claude Code 的 `.mcp.json` 的
   `mcpServers`（条目已含 `command/args/env/secret_env` 标准字段）。
3. 设置环境变量后启动会话：`set OFFICEPACK_FILES_ROOT=D:\office-docs`（PowerShell 用
   `$env:OFFICEPACK_FILES_ROOT="D:\office-docs"`）。
4. 会话内确认工具已挂载（`mcp__filesystem__*` 前缀）。

## 常用调用

- `read_text_file` / `read_media_file` / `read_multiple_files`：读文本、读媒体、批量读；
- `write_file` / `edit_file`：写入与按片段编辑；
- `create_directory` / `list_directory` / `directory_tree`：目录管理与结构浏览；
- `move_file` / `search_files` / `get_file_info`：移动、按名搜索、取元数据；
- `list_allowed_directories`：查看当前授权目录白名单（排障第一工具）。

## 注意事项

- **授权即边界**：参数目录之外的一切路径（含相对路径穿越）都会被拒绝；`list_allowed_directories`
  可随时核验。
- 目录占位符 `${OFFICEPACK_FILES_ROOT}` 属 `_ROOT` 结尾变量：自动化哑值注入时应替换为真实
  存在的临时目录，否则 server 拒绝启动。
- CATALOG 对官方参考实现的定位是"教学示例非生产"——敏感生产目录请勿直接挂载，先用空目录演练。
- Windows 下路径分隔符 `\` 在 JSON 里需转义为 `\\`，建议授权目录用盘符根下短路径。
