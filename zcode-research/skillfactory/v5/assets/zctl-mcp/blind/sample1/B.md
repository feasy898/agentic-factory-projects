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
