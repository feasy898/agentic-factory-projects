# gmail-official — Google 官方远程 Gmail MCP

> 目录实录：A4.3 任务域 server·办公协同 · https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server · `skillfactory/v2/CATALOG.md:203`
> 形态注记：MCP server；远程 streamable-http，端点 `https://gmailmcp.googleapis.com/mcp/v1`（官方文档页实抓），OAuth 2.0 由客户端承载；本机 2026-09-30 对 initialize 实测返回 HTTP 200。目录注记：Developer Preview，需 Google Workspace Developer Preview Program，9 工具只读取向（无发送）；官方文档警示邮件=不可信输入、间接提示注入，建议 Model Armor。

## 安装前提

- **Google Workspace Developer Preview Program 会员资格**（Developer Preview 门槛，目录实录原文；无资格则用 `google-workspace` 社区条目替代）。
- Google Cloud 项目启用两个 API（官方文档原文）：

```bash
gcloud services enable gmail.googleapis.com --project=PROJECT_ID
gcloud services enable gmailmcp.googleapis.com --project=PROJECT_ID
```

- OAuth consent screen 配置 scopes：`gmail.readonly`、`gmail.compose`。
- 建 OAuth 2.0 Web 客户端，redirect URI 按客户端填（Claude.ai/Desktop 为 `https://claude.ai/api/mcp/auth_callback`）。

## 配置步骤

1. 使用本包 `mcp.office.json` 的 `gmail-official` 条目，等价手工配置：

```json
{
  "mcpServers": {
    "gmail-official": {
      "type": "http",
      "url": "https://gmailmcp.googleapis.com/mcp/v1"
    }
  }
}
```

2. 在客户端里登记 OAuth Client ID/Secret（Claude.ai/Desktop：Settings → Connectors → Add custom connector，Advanced settings 填凭据；Claude Code 走 `/mcp` 的 OAuth 授权流）。
3. `/mcp` 触发授权后确认工具列表出现（9 个只读取向工具）。

## 常用调用

- 搜索邮件、读取线程/单封、读附件元数据。
- 读草稿、列标签（无发送工具——官方刻意只读取向）。
- 起草回复（gmail.compose scope 内）。

## 注意事项

- **提示注入**：邮件正文是不可信输入，可能携带诱导指令（官方文档原话），高风险动作务必人工确认。
- Preview 期端点/行为可能变更，商业化前重新核文档页。
- 无资格进入 Preview 计划时：本包 `google-workspace`（社区版，含发送）是替代路径。
