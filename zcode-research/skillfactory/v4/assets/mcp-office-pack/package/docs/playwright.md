# playwright — 微软官方 Playwright MCP（浏览器自动化）

> **目录实录**：https://github.com/microsoft/playwright-mcp
> （`skillfactory/v2/CATALOG.md:215` · A4.4 任务域 server·浏览器/文档/电商）
> 本包实测（2026-09-30，Windows x64）：`Playwright 1.64.0-alpha`，协议 2025-03-26，**25 工具**。

## 安装前提

- Node.js ≥ 18 与 `npx`（npm 包 `@playwright/mcp`）；`npx -y` 首跑自动拉取。
- 浏览器内核：首次真实导航前需要 `npx playwright install chromium`（协议握手与 tools/list
  不需要浏览器，实测验证）；公司内网可配 `PLAYWRIGHT_DOWNLOAD_HOST` 走镜像。
- 无需密钥。

## 配置步骤

1. 并入本包 `playwright` 条目（`npx -y @playwright/mcp@latest`）到 `.mcp.json`。
2. 按需加启动参数（追加进 args）：`--headless`（无窗口）、`--isolated`（一次性画像）、
   `--browser firefox|webkit`、`--viewport-size=1280,720`。
3. 会话内确认 `mcp__playwright__*` 工具挂载后，`browser_navigate` 打开任取页面试拍快照。

## 常用调用

- `browser_navigate` / `browser_click` / `browser_type` / `browser_select_option` / `browser_fill_form`：页面操作五件套；
- `browser_snapshot`：**结构化无障碍快照**（本 server 的核心机制：让 LLM 读可访问性树而非截图，
  元素带 ref 引用，后续点击/填表按 ref 定位）；
- `browser_take_screenshot`：截图（视觉复核用）；
- `browser_tabs` / `browser_evaluate` / `browser_wait_for` / `browser_find`：多页签、页面内脚本、等待与定位；
- `browser_network_requests` / `browser_console_messages`：网络与控制台观测（排障利器）。

## 注意事项

- **选型注记**：CATALOG 曾录 Cloudflare fork（`cloudflare/playwright-mcp`，:208），经官方
  README 核实其仅 Workers 部署/远程形态、npm 包无 bin 无法本地实跑，本包按"fork≠本体"改录
  微软官方原版（官方条目即 npx 即用）。
- 快照机制避免视觉模型依赖，但页面强视觉校验场景仍需配 `browser_take_screenshot` 人工复核。
- 登录态默认落在用户画像目录；`--isolated` 模式下每次会话都是全新画像，不要用于需要登录态的流程。
- 对未测试站点自动化有风险（误点/误提交），支付、删除等不可逆操作保持人在环。
