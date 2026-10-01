# playwright — 浏览器自动化 MCP（微软官方）

> 目录实录：A4.4 任务域 server·浏览器/文档/电商 · https://github.com/microsoft/playwright-mcp · `skillfactory/v2/CATALOG.md:215`
> 形态注记：MCP server；stdio；npm 包 `@playwright/mcp`（0.0.83，实测在架，`npx @playwright/mcp@latest` 即用）。目录注记：microsoft 官方组织，37.7k★，经结构化可访问性快照让 LLM 操作网页（"bypassing the need for screenshots"），浏览器自动化赛道事实标准官方参考实现。

## 安装前提

- Node.js ≥ 18（本机实测 v22.23.2），`npx -y` 自动拉包。
- 浏览器：首次驱动浏览器时 Playwright 可能提示下载内核（`npx playwright install`）；本机已有 Chrome/Edge 时可用 `--browser msedge`/`chrome` 免下载。
- 无需密钥。

## 配置步骤

1. 使用本包 `mcp.office.json` 的 `playwright` 条目，等价手工配置：

```json
{
  "mcpServers": {
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
```

2. Claude Code `/mcp` 确认连接；`--browser msedge`、`--headless`、`--caps=core` 等开关加在 args。
3. 生产固定版本：`@playwright/mcp@0.0.83`（去掉 `@latest` 浮动）。

## 常用调用

- `browser_navigate` / `browser_snapshot`：打开页面并取可访问性快照（快照是主要观察手段，非截图）。
- `browser_click` / `browser_type` / `browser_select_option`：按快照里的元素引用操作（填表单、登录门户、导出报表）。
- `browser_tabs` / `browser_wait_for`：多页签与等待。
- `browser_take_screenshot`：需要视觉留档时用。

## 注意事项

- README 明示"非安全边界"（目录实录红队自述）：它能访问登录态内的一切页面，不要在不受控目录/profile 下跑。
- 企业内网系统优先 `--browser msedge` 复用本机凭据；不要把密码写进 agent 对话，让 agent 停在需要人工输入的步骤。
- 快照驱动≠零视觉：强视觉校验场景补 `browser_take_screenshot`。
