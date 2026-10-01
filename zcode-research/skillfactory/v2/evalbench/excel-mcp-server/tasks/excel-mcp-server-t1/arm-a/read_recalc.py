# -*- coding: utf-8 -*-
"""Read E14 back via the real MCP server after LibreOffice recalculation."""
import json, os, queue, subprocess, threading

WORKDIR = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(WORKDIR, "recalc", "sales-2026-09.xlsx")

proc = subprocess.Popen(
    ["uvx", "excel-mcp-server", "stdio", "--allow-dir", WORKDIR],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8")
q = queue.Queue()
threading.Thread(target=lambda: [q.put(l) for l in proc.stdout], daemon=True).start()
_id = 0


def rpc(method, params=None, notify=False):
    global _id
    msg = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    rid = None
    if not notify:
        _id += 1
        rid = _id
        msg["id"] = rid
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    if notify:
        return None
    while True:
        r = json.loads(q.get(timeout=120))
        if r.get("id") == rid:
            return r


rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "t1-probe", "version": "1.0"}})
rpc("notifications/initialized", notify=True)
r = rpc("tools/call", {"name": "read_range", "arguments": {
    "path": XLSX, "sheet": "流水", "range": "E14:E14", "mode": "values"}})
print("E14 values mode after recalc:", json.dumps(r["result"]["structuredContent"], ensure_ascii=False))
r2 = rpc("tools/call", {"name": "read_range", "arguments": {
    "path": XLSX, "sheet": "流水", "range": "E14:E14", "mode": "formulas"}})
print("E14 formulas mode after recalc:", json.dumps(r2["result"]["structuredContent"], ensure_ascii=False))
proc.stdin.close()
proc.wait(timeout=30)
