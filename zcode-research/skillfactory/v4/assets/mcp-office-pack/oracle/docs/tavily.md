# tavily — 实时搜索 MCP

> 目录实录：A4.4 任务域 server·浏览器/文档/电商 · https://github.com/tavily-ai/tavily-mcp · `skillfactory/v2/CATALOG.md:214`
> 形态注记：MCP server（tavily-ai 官方 production-ready）；stdio；npm 包 `tavily-mcp`（0.2.22，实测在架）+ 商业 SaaS API（tavily.com 按量计费）。目录注记：2,415★/MIT，搜索/抽取/站点映射/爬取四类工具；server 开源但搜索服务按量计费，"引入需预算评估"（目录原文）。

## 安装前提

- Node.js ≥ 18，`npx -y` 自动拉包。
- **Tavily API key（密钥）**：tavily.com 注册获取（免费档有额度）。

## 配置步骤

1. 把 key 写入用户级环境变量（不要写进任何仓库文件）：

```powershell
setx TAVILY_API_KEY "tvly-你的key"
```

2. 使用本包 `mcp.office.json` 的 `tavily` 条目——env 中是 `${TAVILY_API_KEY}` 占位符，运行时由环境变量注入。等价手工配置：

```json
{
  "mcpServers": {
    "tavily": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "tavily-mcp"],
      "env": { "TAVILY_API_KEY": "由环境变量注入" }
    }
  }
}
```

3. Claude Code `/mcp` 确认连接。

## 常用调用

- `tavily-search`：实时 web 搜索（调研类课程内容生产的基础工具，目录原文）。
- `tavily-extract`：抽取指定 URL 正文。
- `tavily-map`：站点结构映射；`tavily-crawl`：受控爬取。

## 注意事项

- 密钥纪律：key 形如 `tvly-...`，本包 validate.py 用正则拦截真值进入配置；泄漏后立即在 tavily.com 后台吊销。
- 计费按调用/credits 走，批量评测前先用免费档估量（目录实录：预算评估）。
- 与 Firecrawl/crawl4AI（爬取为主，目录已有）不重复：搜索需求用 Tavily，整站抓取用后者。
