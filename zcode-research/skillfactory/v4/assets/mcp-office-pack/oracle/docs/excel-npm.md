# excel-npm — Excel 读取 MCP（negokaz 版，Go+npm 分发）

> 目录实录：A4.3 任务域 server·办公协同 · https://github.com/negokaz/excel-mcp-server · `skillfactory/v2/CATALOG.md:199`
> 形态注记：MCP server；stdio；npm scope 包 `@negokaz/excel-mcp-server`（0.12.0，实测在架，bin=excel-mcp-server，Go 单二进制+npm 分发）。目录注记：~1k★/176 commits，MIT；分页读（默认 4000 格）/写值公式/建表/区域样式；Windows 实时编辑+工作表截图；目录原文"读重于写互补选择，截图工具做『让 agent 看表格画面』演示"。

## 安装前提

- Node.js ≥ 18（本机实测 v22.23.2），`npx -y` 自动拉包（Go 二进制随 npm 包分发，无需 Go 环境）。
- 无需 Microsoft Excel，无需密钥。

## 配置步骤

1. 使用本包 `mcp.office.json` 的 `excel-npm` 条目，等价手工配置：

```json
{
  "mcpServers": {
    "excel-npm": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@negokaz/excel-mcp-server"]
    }
  }
}
```

2. Claude Code `/mcp` 确认连接。

### ⚠️ 包名陷阱（本包实测踩中）

npm 上**不带 scope** 的 `excel-mcp-server`（1.0.0，维护者 lichard）是另一个第三方包，Windows 启动器走 Python 且缺 pandas 依赖（本机实测报 `ModuleNotFoundError: No module named 'pandas'`）——**务必带 `@negokaz/` scope**，本包样例实跑时正是靠这个报错定位的。

## 常用调用

- 读表：分页读取（默认一次 4000 格，大表不爆上下文）——大报表盘点首选。
- 写：写值/公式、建表、区域样式。
- 截图：工作表截图，让 agent"看到"表格画面（演示利器，目录原文）。
- Windows Excel 实时编辑：与本机打开的会话联动。

## 注意事项

- **与本包 `excel`（haris-musa 版）的选型对照**（目录按两维护者版本并行收录）：
  - 读为主/要截图/要 npm 生态 → 本条目（negokaz）；
  - 写为主/要条件格式图表/要 PyPI 生态 → `excel`（haris-musa）。
- 无目录沙箱参数：文件路径由每次工具调用显式给出，敏感目录文件不要把绝对路径交给 agent。
- 旧版 .xls 支持有限，优先 .xlsx。
