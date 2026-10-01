# tavily — Tavily 官方 MCP（实时搜索/抽取/爬取）

> **目录实录**：https://github.com/tavily-ai/tavily-mcp
> （`skillfactory/v2/CATALOG.md:214` · A4.4 任务域 server·浏览器/文档/电商）
> 本包实测（2026-09-30，Windows x64）：`tavily-mcp 0.2.22`，协议 2025-03-26，**5 工具**。

## 安装前提

- Node.js ≥ 18 与 `npx`；npm 包名 `tavily-mcp`。
- **API key（唯一密钥条目之一）**：在 tavily.com 注册取 key。包内配置只写占位符
  `${TAVILY_API_KEY}`，真值只在启用方环境变量——密钥永不入包、不入 git、不入对话明文。
- 无 key 也能启动：本包实测用哑值占位即完成 initialize + tools/list（5 工具）；
  真值在**工具调用层**才需要。

## 配置步骤

1. 并入本包 `tavily` 条目到 `.mcp.json`（args `-y tavily-mcp@latest`）。
2. 注入真值：`set TAVILY_API_KEY=tvly-xxxx`（示例即占位形态；真值走环境变量，勿写进任何文件）。
3. 会话内确认 `mcp__tavily__*` 工具挂载，用一次 `tavily_search` 小查询验证计费链路。

## 常用调用

- `tavily_search`：实时 web 搜索（时间范围/域名过滤/深度档位）；
- `tavily_extract`：抽指定 URL 正文（配合搜索结果二次精读）；
- `tavily_map`：站点结构映射（摸清一个站有哪些页）；
- `tavily_crawl`：定向爬取（限深限页）；
- `tavily_research`：研究型检索（实测 tools/list 第 5 个工具；具体语义以 server 内工具描述为准）。

## 注意事项

- **按量计费**：server 开源 MIT，但搜索服务本体按 key 计费；批处理/评测脚本先小流量试跑，
  设好月度预算告警再放量（CATALOG 选型注记原话："引入需预算评估"）。
- 搜索是办公场景"调研素材获取"槽位：写周报/招投标调研时由 agent 代查，素材链接记得回填人工复核。
- `@latest` 漂移风险：包大版本升级可能改工具面，固定版本可在 args 写 `tavily-mcp@0.2.22`。
- 若与浏览器条目（playwright）同开，注意两者都是"出网"工具：涉密内网环境同时关掉这两条。
