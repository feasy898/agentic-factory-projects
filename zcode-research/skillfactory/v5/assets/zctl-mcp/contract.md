# contract.md — zctl-mcp 接口契约（冻结 v1.0.0，2026-10-02）

## 1. 资产定位

把研究线 zctl CLI（ZCode 闲时任务/额度重置协议级工具）封装为 MCP stdio server 资产。
**安全默认：只暴露只读工具；变更类操作（reset use / opportunity / offpeak take / settle）不在此 server 暴露**——MCP 侧的守卫比 zctl 侧的 dry-run 更严一层。

## 2. 产物根布局

```
package/mcp-server.mjs   # MCP server（零依赖 Node>=18，stdio JSON-RPC 2024-11-05）
package/INSTALL.md       # 安装与 ZCode MCP 配置说明
oracle/expected_tools.json  # 冻结期望（serverInfo + 4 工具契约 + forbidden 名单）
eval/runner.py           # 确定性评测器（本契约的机械化判分）
```

## 3. 冻结项（eval 逐条判定）

| # | 冻结项 | 判定 |
|---|---|---|
| F1 | serverInfo = zctl-mcp@1.0.0，protocolVersion 2024-11-05 | initialize 响应比对 |
| F2 | 工具名集合恰为 {zctl_reset_status, zctl_offpeak_availability, zctl_offpeak_status, zctl_help} | tools/list 恰等比对 |
| F3 | 每工具 description 含 oracle 关键词；inputSchema.required 恰等 | 逐工具比对 |
| F4 | forbidden_tool_names 零暴露（zctl_reset_use / zctl_offpeak_take / zctl_offpeak_settle） | tools/list 反向比对 |

## 4. 红路（fail-closed）

- 空目录 / 缺 server 文件 → exit 1；
- 工具集多/少/改名 → exit 1；
- 出现任何变更类工具 → exit 1；
- 红路永远不许修成 exit 0。

## 5. 用法错

- 参数个数 ∉ {0, 2} → exit 2（零参数=自评）。

## 6. 变更条款

契约变更须同步：spec.md、oracle/expected_tools.json、eval/runner.py 三处一致，且红路矩阵复跑全绿后方可升版本号。
