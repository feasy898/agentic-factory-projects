# powerpoint — PPT 生成 MCP（GongRzhe 版）

> 目录实录：A4.3 任务域 server·办公协同 · https://github.com/GongRzhe/Office-PowerPoint-MCP-Server · `skillfactory/v2/CATALOG.md:201`
> 形态注记：MCP server；stdio；PyPI 包 `office-powerpoint-mcp-server`（2.0.7，实测在架，uvx 分发）。目录注记：~1.9k★，32+ 工具；与 Word-MCP 同作者同日归档（2026-03-03，实测），Smithery/uvx 仍可装，做社区 MCP 演进对照。

## 安装前提

- Python ≥ 3.10 与 `uvx`；依赖 python-pptx，uvx 自动解析。
- 无需 Microsoft PowerPoint，无需密钥。

## 配置步骤

1. 使用本包 `mcp.office.json` 的 `powerpoint` 条目，等价手工配置：

```json
{
  "mcpServers": {
    "powerpoint": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "office-powerpoint-mcp-server", "--with", "mcp<2", "ppt_mcp_server"]
    }
  }
}
```

> 注（本包实测踩中的两个坑）：
> ① PyPI 包 2.0.x（Consolidated Edition）的可执行名为 `ppt_mcp_server`，不是 `powerpoint_mcp_server`（uvx 报错列出可用执行文件时确认）。
> ② 该包未钉死 `mcp` 依赖，2026-09-30 实测拉到 `mcp` 2.x 后启动即崩（`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`，FastMCP 在 2.x 更名 MCPServer）——必须如上 `--with "mcp<2"` 钉回 1.x。归档仓库 + 松散依赖钉版，是它作为"选型风险教材"的又一实证。

2. Claude Code `/mcp` 确认连接。

## 常用调用

- 从零生成：建演示文稿、增删幻灯片、按版式添加文本/图片/表格/图表（周报汇报一键成 PPT，目录原文）。
- 模板化：4 配色方案 25+ 模板、主题切换、母版管理。
- 提取：从既有 PPT 提取全部文本（评审/汇总场景）。

## 注意事项

- **仓库已归档（2026-03-03，与 Word-MCP 同日）**：同作者两仓一起归档是社区 MCP 演进的典型样本，选型风险同 `word.md`。
- 复杂版式（SmartArt、动画）不在工具面内，模板请先在 PowerPoint 里做好母版再交给 agent 填内容。
- 生成后务必人工打开核一遍版式溢出（agent 只保证内容结构，不保证视觉）。
