# powerpoint — GongRzhe Office-PowerPoint-MCP-Server

> **目录实录**：https://github.com/GongRzhe/Office-PowerPoint-MCP-Server
> （`skillfactory/v2/CATALOG.md:201` · A4.3 任务域 server·办公协同）
> 本包实测（2026-09-30，Windows x64）：`ppt-mcp-server 1.30.0`，协议 2025-03-26，**37 工具**。

## 安装前提

- Python 3.10+ 与 `uvx`；PyPI 包名 `office-powerpoint-mcp-server`。
- 无需密钥。
- **双陷阱（spec §3.6 与本包实测一致）**：① 可执行名是 `ppt_mcp_server`，与包名不同，须
  `uvx --from` 指定；② 该包未钉死 `mcp` 依赖，裸跑会拉到 mcp 2.x 即崩
  （`ModuleNotFoundError: mcp.server.fastmcp`）——必须 `--with "mcp<2"` 钉版本。

## 配置步骤

1. 并入本包 `powerpoint` 条目到 `.mcp.json`。args 三要素缺一不可：
   `["--from", "office-powerpoint-mcp-server", "--with", "mcp<2", "ppt_mcp_server"]`。
2. 若曾裸跑失败留下损坏的 uv 缓存环境，重跑会自动重建（`--with` 会解析出独立环境）。
3. 首跑含拉包，实测 57s 内完成握手；确认 `mcp__powerpoint__*` 工具挂载。

## 常用调用

- `create_presentation` / `create_presentation_from_template` / `add_slide`：建稿、套模板、加页；
- `manage_text` / `add_bullet_points` / `populate_placeholder`：页内文字编排；
- `manage_image` / `apply_picture_effects` / `add_table` / `add_chart` / `update_chart_data`：元素与图表；
- `apply_professional_design` / `apply_slide_template` / `manage_slide_masters` / `manage_slide_transitions`：设计、模板与母版；
- `extract_presentation_text` / `extract_slide_text`：全文/单页文本提取（反向把 PPT 变大纲）；
- `auto_generate_presentation`：由主题自动生成整份演示。

## 注意事项

- 与 `word` 同作者同归档时点（上游 2026-03-03 归档），PyPI 仍可装可跑；选型注记同 catalog
  "社区 MCP 演进对照"定位。
- `--with "mcp<2"` 是**运行时依赖钉子**，升级包前先确认上游是否已兼容 mcp 2.x，再决定是否
  摘钉；摘钉后务必重做协议握手验证。
- 只处理 `.pptx`；`.ppt` 老格式需先转换。
- 图表工具依赖 python-pptx 原生图表能力，复杂图表建议先在 Excel 生成再贴图。
