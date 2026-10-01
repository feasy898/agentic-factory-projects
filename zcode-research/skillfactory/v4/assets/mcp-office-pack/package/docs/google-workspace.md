# google-workspace — taylorwilsdon google_workspace_mcp（一体化协同）

> **目录实录**：https://github.com/taylorwilsdon/google_workspace_mcp
> （`skillfactory/v2/CATALOG.md:202` · A4.3 任务域 server·办公协同）
> 本包实测（2026-09-30，Windows x64）：`google_workspace 4.0.10`，协议 2025-03-26，**120 工具**。

## 安装前提

- Python 3.10+ 与 `uvx`；PyPI 包名 `workspace-mcp`。
- **OAuth 2.0 凭据**：到 Google Cloud Console 建 OAuth 客户端（Desktop 类型），拿到
  Client ID / Client Secret。本包配置只写占位符
  `${GOOGLE_OAUTH_CLIENT_ID}` / `${GOOGLE_OAUTH_CLIENT_SECRET}`，真值只在启用方环境变量。
- **冷拉包要给足超时**：本包实测首跑 282s 才完成握手（含依赖解析）；自动实跑建议 ≥600s。

## 配置步骤

1. 并入本包 `google-workspace` 条目（`uvx workspace-mcp`）到 `.mcp.json`。
2. 注入两个环境变量真值（PowerShell）：
   `$env:GOOGLE_OAUTH_CLIENT_ID="xxxx.apps.googleusercontent.com"`、
   `$env:GOOGLE_OAUTH_CLIENT_SECRET="GOCSPX-..."`（示例即占位形态，勿把真值写进任何文件）。
3. 首次调用授权类工具时走浏览器 OAuth 授权流程（OAuth 2.1 PKCE，多用户部署模式）。
4. 会话内确认 `mcp__google-workspace__*` 工具挂载。

## 常用调用

- Gmail 组（15+）：搜索邮件、读信、建草稿、加标签；
- Docs 组（19）：建文档、追加/替换内容、插入表格；
- Sheets 组（14）：建表、读写行列、追加数据；
- Slides 组（7）+ Drive 组：演示文稿与云端硬盘文件管理。

## 注意事项

- **协议握手不需要真密钥**：本包实测用哑值占位符即可完成 initialize + tools/list
  （120 工具）；真凭据在**工具调用层**才需要——这是"密钥零真值入包、用时注入"策略的样板条目。
- OAuth 客户端须把回发地址配进 Google Cloud Console 白名单，否则授权回调 400。
- 120 个工具全量挂载对上下文开销大，生产建议裁剪（见 `SKILL.md` 裁剪方法）或用
  `enabled: false` 先收藏。
- Google API 配额与用户协议约束照常适用；企业场景优先官方 Gmail 远程端点（见
  `docs/gmail-official.md`）做对照。
