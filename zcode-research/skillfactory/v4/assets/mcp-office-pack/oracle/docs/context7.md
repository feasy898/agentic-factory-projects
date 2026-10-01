# context7 — 最新文档检索 MCP

> 目录实录：A4.4 任务域 server·浏览器/文档/电商 · https://github.com/upstash/context7 · `skillfactory/v2/CATALOG.md:209`
> 形态注记：MCP server；远程 http 端点 `https://mcp.context7.com/mcp`（本机 2026-09-30 对 initialize 实测 200）+ 本地 stdio（npm `@upstash/context7-mcp`，4.1.1 实测在架）+ CLI + Skills 多形态。目录注记：62.5k★，编码类课程标配基建，"防 API 幻觉第一推荐"，"同一能力多形态封装"最佳活案例。

## 安装前提

- **远程形态**：无需安装（本配置采用）；高用量可注册 upstash 拿 API key 提限额。
- **本地形态**：Node.js ≥ 18。

## 配置步骤

1. 远程形态（本包默认）：使用 `mcp.office.json` 的 `context7` 条目，等价手工配置：

```json
{
  "mcpServers": {
    "context7": {
      "type": "http",
      "url": "https://mcp.context7.com/mcp"
    }
  }
}
```

2. 本地形态（替代）：

```json
{ "type": "stdio", "command": "npx", "args": ["-y", "@upstash/context7-mcp"] }
```

3. Claude Code `/mcp` 确认连接。

## 常用调用

- `resolve-library-id`：把库名解析为 Context7 文档库 ID（如 React → /facebook/react）。
- `query-docs`（get-library-docs）：拉取该库最新文档与代码示例注入提示词——写 Excel 公式批处理脚本、playwright 脚本前先查一遍，防旧版 API 幻觉。

## 注意事项

- 两步工作流：先 resolve 再查文档，直接猜库 ID 会失败。
- 文档覆盖依赖社区登记，冷门国产库可能缺收；缺收时回退到官方文档 URL 直读。
- 免费端点有限速，团队批量评测建议配 API key（`--api-key` 或 header，见仓库 README）。
