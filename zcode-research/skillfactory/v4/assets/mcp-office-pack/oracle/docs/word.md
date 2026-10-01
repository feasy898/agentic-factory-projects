# word — Word 文档 MCP（GongRzhe 版）

> 目录实录：A4.3 任务域 server·办公协同 · https://github.com/GongRzhe/Office-Word-MCP-Server · `skillfactory/v2/CATALOG.md:200`
> 形态注记：MCP server；stdio；PyPI 包 `office-word-mcp-server`（1.1.11，实测在架，uvx 分发）。目录注记：~2.1k★，仓库 2026-03-03 已归档只读（实测），uvx 仍可装；目录原文"功能面最全 Word MCP（合同/公文改稿案例），已归档=讲工具选型看维护状态的活教材"。

## 安装前提

- Python ≥ 3.10 与 `uvx`；依赖 python-docx + FastMCP，由 uvx 自动解析。
- 转 PDF 功能需本机有 Word/LibreOffice 之一（仅改稿不需要）。
- 无需密钥。

## 配置步骤

1. 使用本包 `mcp.office.json` 的 `word` 条目，等价手工配置：

```json
{
  "mcpServers": {
    "word": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "office-word-mcp-server", "word_mcp_server"]
    }
  }
}
```

2. Claude Code `/mcp` 确认连接。
3. 建议固定包版本（去掉浮动态）：`args` 改为 `["--from", "office-word-mcp-server==1.1.11", "word_mcp_server"]`。

## 常用调用

- 建文档与结构：新建 docx、加标题/段落/表格/图片（周报、公文骨架）。
- 改稿：查找替换（全库批量替换口径/日期）、格式化文本。
- 合并多文档、转 PDF。
- 批注提取、密码保护/解除（合同审阅流）。

## 注意事项

- **仓库已归档（2026-03-03，目录实测）**：无上游修复，选型时把"归档"计入风险；功能仍可用，本包经 PyPI 包实锚。
- 高风险操作（覆盖保存、解除密码）前先让 agent 复制副本。
- 仅处理 `.docx`，旧 `.doc` 先转换。
