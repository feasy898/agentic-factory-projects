```json
{
  "serverInfo": { "name": "zctl-mcp", "version": "1.0.0" },
  "tools": [
    { "name": "zctl_reset_status", "description": "查询额度重置券状态（只读）。对应 zctl reset status。凭据取自本机 credentials.json，token 不回显。", "inputSchema": { "type": "object", "properties": {}, "required": [] } },
    { "name": "zctl_offpeak_availability", "description": "查询闲时任务取号资格（只读）。对应 zctl offpeak availability。不取号不结算。", "inputSchema": { "type": "object", "properties": {}, "required": [] } },
    { "name": "zctl_offpeak_status", "description": "轮询闲时任务票状态（只读）。对应 zctl offpeak status --ids <ticket_id>。", "inputSchema": { "type": "object", "properties": { "ticket_id": { "type": "string" } }, "required": ["ticket_id"] } },
    { "name": "zctl_help", "description": "返回 zctl 用法摘要（只读）。列明变更类命令默认 dry-run 须 --yes；MCP 侧不暴露任何变更类工具。", "inputSchema": { "type": "object", "properties": {}, "required": [] } }
  ],
  "design_notes": "变更类操作（reset use / opportunity / offpeak take / settle）一律不暴露为 MCP 工具：MCP 客户端是自动执行环境，无人确认环节；zctl 的 dry-run+--yes 守卫依赖人在环上，暴露即绕过。只读四工具已覆盖『看额度、看资格、看票、看用法』全部查询需求。"
}
```
