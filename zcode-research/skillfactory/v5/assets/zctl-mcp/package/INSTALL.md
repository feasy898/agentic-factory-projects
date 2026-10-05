# INSTALL — zctl-mcp 安装

## 前置

- Node >= 18（实测 v22.23.2 可用）；
- zctl.mjs：随仓提供于 `zcode-research/zctl/zctl.mjs`（server 按候选路径自动定位：包内副本优先，其次研究线原脚本）；
- 凭据：`~/.zcode/v2/credentials.json`（zctl 自行解密，token 不经 MCP 回显）。

## ZCode 客户端配置（mcpServers 片段）

```json
{
  "mcpServers": {
    "zctl": {
      "command": "node",
      "args": ["<仓库>/zcode-research/skillfactory/v5/assets/zctl-mcp/package/mcp-server.mjs"]
    }
  }
}
```

## 自检

```
python eval/runner.py            # 期望 exit 0（自评 7 项检查全过）
python eval/runner.py _empty oracle   # 期望 exit 1（红路 fail-closed）
```

## 安全说明

本 server 只暴露只读工具。额度重置（reset use）、取号（offpeak take）、结算（settle）等变更类操作**不提供 MCP 入口**；如需使用，回 zctl CLI 走 dry-run + --yes 人工确认。
