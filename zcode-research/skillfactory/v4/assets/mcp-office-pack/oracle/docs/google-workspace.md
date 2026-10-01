# google-workspace — Google 全家桶一体化 MCP（社区版 workspace-mcp）

> 目录实录：A4.3 任务域 server·办公协同 · https://github.com/taylorwilsdon/google_workspace_mcp · `skillfactory/v2/CATALOG.md:202`
> 形态注记：MCP server；stdio / streamable-http 双传输；PyPI 包 `workspace-mcp`（1.30.0，实测在架，uvx 分发）。目录注记：~3.3k★ 更新至 2026-09-29，MIT；OAuth 2.1 PKCE 多用户部署设计可进治理章节。

## 安装前提

- Python ≥ 3.10 与 `uvx`（本机实测 uvx 0.12.15）。
- **Google Cloud OAuth 凭据**（密钥，绝不写进配置文件）：
  1. Google Cloud Console 建项目 → 启用 Gmail API / Google Drive API / Google Calendar API / Sheets API 等。
  2. 建 OAuth 2.0 客户端（Desktop 类型），拿 Client ID 与 Client Secret。
  3. 配置 OAuth consent screen，把测试账号加为 test user。

## 配置步骤

1. 把凭据放进环境变量（官方 README 实抓核实变量名）：

```powershell
setx GOOGLE_OAUTH_CLIENT_ID "你的client_id"
setx GOOGLE_OAUTH_CLIENT_SECRET "你的client_secret"
```

2. 使用本包 `mcp.office.json` 的 `google-workspace` 条目——env 中只有 `${GOOGLE_OAUTH_CLIENT_ID}` / `${GOOGLE_OAUTH_CLIENT_SECRET}` 占位符，运行时由环境变量注入真值。等价手工配置：

```json
{
  "mcpServers": {
    "google-workspace": {
      "type": "stdio",
      "command": "uvx",
      "args": ["workspace-mcp", "--tool-tier", "core"],
      "env": {
        "GOOGLE_OAUTH_CLIENT_ID": "由环境变量注入",
        "GOOGLE_OAUTH_CLIENT_SECRET": "由环境变量注入"
      }
    }
  }
}
```

3. 首次调用工具时浏览器弹出 Google 授权页，同意后 token 缓存到本地。
4. 多用户/SaaS 部署：改 `--transport streamable-http`（`WORKSPACE_MCP_PORT=8000`）+ `MCP_ENABLE_OAUTH21=true`（README 实抓）。

## 常用调用

- Gmail：搜索/读邮件/起草（15+ 工具）；`--tools gmail drive` 可精选服务。
- Docs 19 工具 / Sheets 14 工具 / Slides 7 工具：在线文档的读写与导出。
- Calendar / Drive：日程与文件管理（按 tier 与 --tools 裁剪）。

## 注意事项

- 密钥纪律：Client Secret 只走环境变量/凭据库（本机规范见 `D:\AGENTS.md` 红线节），配置模板永远保持 `${...}` 占位符，本包 validate.py 会拦截真值。
- OAuth token 缓存文件等同于凭据，勿提交 git。
- scopes 一次授权要一次授权到位，反复加服务要重复同意；生产用 `--read-only` 起步。
