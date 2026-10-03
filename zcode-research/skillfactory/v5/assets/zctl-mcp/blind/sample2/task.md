# 盲评任务 sample2（zctl-mcp）

任务：为 zctl（ZCode 闲时任务/额度重置 CLI）设计一个 MCP server 的工具暴露方案。要求输出一份工具清单 JSON：每个工具含 name、description（须说明只读/变更属性与守卫方式）、inputSchema。设计须回答「哪些 zctl 能力适合暴露为 MCP 工具、哪些不适合、为什么」。

评判标准（交给评委时不再提供额外信息）：哪份交付更能胜任「让一个 MCP 客户端安全接入 zctl」这个目标。

## A 臂交付

```json
{
  "serverInfo": { "name": "zctl-mcp", "version": "0.1.0" },
  "tools": [
    { "name": "zctl_reset_status", "description": "查询可重置额度。", "inputSchema": { "type": "object", "properties": {}, "required": [] } },
    { "name": "zctl_offpeak_availability", "description": "查询闲时任务资格。", "inputSchema": { "type": "object", "properties": {}, "required": [] } },
    { "name": "zctl_reset_use", "description": "重置额度。默认 dry-run，加 confirm=true 才真正执行。", "inputSchema": { "type": "object", "properties": { "type": { "type": "string", "enum": ["FIVE_HOUR", "WEEK"] }, "confirm": { "type": "boolean" } }, "required": ["type"] } },
    { "name": "zctl_offpeak_take", "description": "领取闲时任务。加 confirm=true 执行。", "inputSchema": { "type": "object", "properties": { "task_id": { "type": "string" }, "confirm": { "type": "boolean" } } } }
  ],
  "design_notes": "把 zctl 的查询与变更能力都封装成工具，变更工具用 confirm 参数做守卫，方便一键完成额度重置和取号。"
}
```
## B 臂交付

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

