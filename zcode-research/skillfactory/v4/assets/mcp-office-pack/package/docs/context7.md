# context7 — Upstash Context7 远程 MCP（库文档实时检索）

> **目录实录**：https://github.com/upstash/context7
> （`skillfactory/v2/CATALOG.md:209` · A4.4 任务域 server·浏览器/文档/电商）
> 本包实测（2026-09-30，Windows x64）：POST initialize → HTTP 200，`Context7 4.1.1`，
> 协议 2025-03-26，端点 `https://mcp.context7.com/mcp`，**免装免密钥匿名可达**。

## 安装前提

- 无需本地安装：官方远程托管（Streamable HTTP）。
- 无需密钥：匿名 initialize 即可达（实测 1.2s）；高用量才需要 Upstash API key，本包按匿名收录。
- 宿主需支持 http 型 MCP 条目（`.mcp.json` 的 `"type": "http"`）。

## 配置步骤

1. 把本包 `context7` 条目（`"type": "http"` + `url`）并入 `.mcp.json`。
2. 会话内确认远程工具挂载（`resolve-library-id` / `query-docs` 等）。
3. 无本地依赖、无启动过程——http 型条目天然没有"冷拉包"问题（对比 `google-workspace` 的
   数分钟首跑，本条 1.2s 内可验证连通）。

## 常用调用

- `resolve-library-id`：把库名解析成 Context7 的库 ID（如 Office 自动化相关的库）；
- `get-library-docs` / `query-docs`：按主题拉取该库**最新**文档与代码示例注入提示词。

## 注意事项

- **定位是"防 API 幻觉"**：写 Office.js 加载项、VBA、openpyxl/python-docx 脚本时，先查再写，
  避免 LLM 用过时 API 编造参数；CATALOG 评为"编码类课程标配基建"。
- 文档质量取决于上游库在 Context7 的收录度；小众库先 `resolve-library-id` 探一下，解析不到
  就回退到本地文档。
- 远程端点行为可能随服务方调整（版本号实测 4.1.1，2026-09-30）；端点不可达时检查宿主出网代理。
- 与本包其余条目互补：它不占六格场景槽位，属"文档检索"补充条目，可独立裁剪（见 `SKILL.md`）。
