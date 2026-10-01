# word — GongRzhe Office-Word-MCP-Server（python-docx 系）

> **目录实录**：https://github.com/GongRzhe/Office-Word-MCP-Server
> （`skillfactory/v2/CATALOG.md:200` · A4.3 任务域 server·办公协同）
> 本包实测（2026-09-30，Windows x64）：`Word Document Server 4.0.10`，协议 2025-03-26，**54 工具**。

## 安装前提

- Python 3.10+ 与 `uvx`；PyPI 包名 `office-word-mcp-server`。
- 无需密钥。
- **可执行名陷阱（本包实测踩坑）**：包名不等于可执行名，`uvx office-word-mcp-server` 会报
  "An executable named `office-word-mcp-server` is not provided by package"——真实可执行名是
  **`word_mcp_server`**，必须 `uvx --from office-word-mcp-server word_mcp_server` 启动
  （本包 `word` 条目 args 已按此写好）。

## 配置步骤

1. 并入本包 `word` 条目到 `.mcp.json`（args 已含 `--from` 与正确可执行名）。
2. 可选：用环境变量约定文档工作目录（本条无沙箱参数，建议以绝对路径约束读写范围）。
3. 首跑 uvx 拉包需数秒到数十秒；启动时 stderr 会打印 FastMCP ASCII 横幅，属正常现象，
   不影响 stdio 上的 JSON-RPC 通道（本包实测握手 34.2s 内完成，含拉包）。
4. 会话内确认 `mcp__word__*` 工具挂载。

## 常用调用

- `create_document` / `copy_document`：建文档（可带标题/作者元数据）与复制；
- `add_heading` / `add_paragraph` / `add_table` / `add_picture` / `add_page_break`：内容编排；
- `search_and_replace` / `find_text_in_document` / `get_document_outline`：查找替换与大纲提取（批量改稿主力）；
- `convert_to_pdf`（本机装 Word 时）：转 PDF；
- `get_all_comments` / `get_comments_by_author` / `get_comments_for_paragraph`：批注提取；
- `get_document_text`：纯文本导出。

## 注意事项

- **上游 2026-03-03 已归档（只读），PyPI 包仍可装可跑**——归档与否不是可用性判据，但意味着
  不会再有上游修复；本包按 CATALOG"讲工具选型看维护状态的活教材"定位收录。
- 只处理 `.docx`（Office Open XML）；老 `.doc` 需先另存为 `.docx`。
- 转 PDF 依赖本机 Microsoft Word COM，无 Office 的机器上该工具不可用，属预期行为。
- 54 个工具里脚注/尾注（footnote/endnote）族占 10 个、表格格式化族占 15 个（本包实测
  tools/list 计数），全量挂载会占上下文，裁剪方法见包根 `SKILL.md`。
