#!/usr/bin/env node
/*! zctl-mcp server — 把 zctl（ZCode 闲时任务/额度重置 CLI）封装为 MCP (stdio) server。
 *  只暴露只读工具；变更类操作一律不在此 server 暴露（安全默认：dry-run 红线在 zctl 侧，MCP 侧直接不开放）。
 *  零依赖，Node >=18。协议：换行分隔 JSON-RPC 2.0（MCP 2024-11-05）。
 *  确定性：tools/list 输出与 oracle/expected_tools.json 冻结一致；无时间戳、无随机数。
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
// zctl.mjs 定位：包内副本优先，其次研究线原脚本（install 文档允许二选一）
const ZCTL_CANDIDATES = [
  join(HERE, "zctl.mjs"),
  join(HERE, "..", "..", "..", "..", "zctl", "zctl.mjs"),
];
const ZCTL = ZCTL_CANDIDATES.find((p) => existsSync(p));

const TOOLS = [
  {
    name: "zctl_reset_status",
    description:
      "查询 ZCode 额度重置券状态（只读）。对应 zctl reset status。返回可用 5 小时/周重置券数量与过期时间。凭据取自本机 ~/.zcode/v2/credentials.json，token 不回显。",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "zctl_offpeak_availability",
    description:
      "查询闲时任务取号资格（只读）。对应 zctl offpeak availability。不取号、不结算。",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
  {
    name: "zctl_offpeak_status",
    description:
      "轮询闲时任务票状态（只读）。对应 zctl offpeak status --ids <ticket_id>。",
    inputSchema: {
      type: "object",
      properties: { ticket_id: { type: "string", description: "闲时任务票 id" } },
      required: ["ticket_id"],
    },
  },
  {
    name: "zctl_help",
    description:
      "返回 zctl 用法摘要（只读）。列出全部子命令与安全机制（变更类默认 dry-run、须 --yes）。MCP 侧不暴露任何变更类工具。",
    inputSchema: { type: "object", properties: {}, required: [] },
  },
];

function zctlArgs(toolName, args) {
  switch (toolName) {
    case "zctl_reset_status":
      return ["reset", "status"];
    case "zctl_offpeak_availability":
      return ["offpeak", "availability"];
    case "zctl_offpeak_status":
      return ["offpeak", "status", "--ids", String(args.ticket_id)];
    case "zctl_help":
      return ["--help"];
    default:
      return null;
  }
}

function callZctl(toolName, args) {
  if (ZCTL === undefined) {
    return { ok: false, text: "zctl.mjs 未找到（安装见 package/INSTALL.md）" };
  }
  const zargs = zctlArgs(toolName, args ?? {});
  if (zargs === null) {
    return { ok: false, text: `未知工具：${toolName}` };
  }
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [ZCTL, ...zargs], { cwd: HERE });
    let out = "";
    let err = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve({ ok: false, text: "zctl 调用超时（30s）" });
    }, 30000);
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, text: (out + (err ? `\n[stderr] ${err}` : "")).trim() });
    });
  });
}

function send(ws, obj) {
  ws.stdout.write(JSON.stringify(obj) + "\n");
}

// ---- stdio 主循环：换行分隔 JSON-RPC ----
let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", async (chunk) => {
  buf += chunk;
  let idx;
  while ((idx = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (!line) continue;
    let req;
    try {
      req = JSON.parse(line);
    } catch {
      send(process, { jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
      continue;
    }
    await handle(req);
  }
});

async function handle(req) {
  const { id, method, params } = req;
  switch (method) {
    case "initialize":
      send(process, {
        jsonrpc: "2.0",
        id,
        result: {
          protocolVersion: "2024-11-05",
          capabilities: { tools: {} },
          serverInfo: { name: "zctl-mcp", version: "1.0.0" },
        },
      });
      return;
    case "notifications/initialized":
      return; // 通知无需应答
    case "tools/list":
      send(process, { jsonrpc: "2.0", id, result: { tools: TOOLS } });
      return;
    case "tools/call": {
      const name = params?.name;
      if (!TOOLS.some((t) => t.name === name)) {
        send(process, {
          jsonrpc: "2.0",
          id,
          error: { code: -32602, message: `未知工具：${name}` },
        });
        return;
      }
      const r = await callZctl(name, params?.arguments);
      send(process, {
        jsonrpc: "2.0",
        id,
        result: {
          content: [{ type: "text", text: r.text }],
          isError: !r.ok,
        },
      });
      return;
    }
    case "ping":
      send(process, { jsonrpc: "2.0", id, result: {} });
      return;
    default:
      if (id !== undefined) {
        send(process, { jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } });
      }
  }
}
