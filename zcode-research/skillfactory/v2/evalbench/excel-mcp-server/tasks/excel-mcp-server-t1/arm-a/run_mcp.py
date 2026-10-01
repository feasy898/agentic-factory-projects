# -*- coding: utf-8 -*-
"""MCP stdio driver: drive the real excel-mcp-server through the exact
tool-call sequence required by task T1, and verify read-back behavior."""
import json
import os
import queue
import subprocess
import sys
import threading

WORKDIR = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(WORKDIR, "sales-2026-09.xlsx")

if os.path.exists(XLSX):
    os.remove(XLSX)

proc = subprocess.Popen(
    ["uvx", "excel-mcp-server", "stdio", "--allow-dir", WORKDIR],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8",
)

q = queue.Queue()


def reader():
    for line in proc.stdout:
        q.put(line)


threading.Thread(target=reader, daemon=True).start()

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
    proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    if notify:
        return None
    while True:
        resp = json.loads(q.get(timeout=180))
        if resp.get("id") == rid:
            return resp


def tool(name, arguments):
    r = rpc("tools/call", {"name": name, "arguments": arguments})
    print("### tools/call:", name)
    print("    args:", json.dumps(arguments, ensure_ascii=False))
    body = r.get("result", r.get("error"))
    print("    resp:", json.dumps(body, ensure_ascii=False))
    return body


log = open(os.path.join(WORKDIR, "mcp-transcript.jsonl"), "w", encoding="utf-8")


def tool_logged(name, arguments):
    r = rpc("tools/call", {"name": name, "arguments": arguments})
    log.write(json.dumps({"call": name, "arguments": arguments,
                          "response": r.get("result", r.get("error"))},
                         ensure_ascii=False) + "\n")
    log.flush()
    return r.get("result", r.get("error"))


init = rpc("initialize", {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "t1-probe", "version": "1.0"},
})
print("### initialize ->", json.dumps(init.get("result", {}).get("serverInfo"), ensure_ascii=False))
rpc("notifications/initialized", notify=True)

HEADERS = [["日期", "品名", "数量", "单价", "金额"]]
ROWS = [
    ["2026-09-01", "笔记本", 3, 45, 135],
    ["2026-09-01", "签字笔", 20, 2.5, 50],
    ["2026-09-02", "A4纸", 10, 18, 180],
    ["2026-09-03", "订书机", 2, 25, 50],
    ["2026-09-05", "笔记本", 5, 45, 225],
    ["2026-09-08", "便利贴", 8, 6, 48],
    ["2026-09-10", "签字笔", 15, 2.5, 37.5],
    ["2026-09-12", "文件夹", 12, 9, 108],
    ["2026-09-15", "A4纸", 6, 18, 108],
    ["2026-09-18", "白板笔", 9, 5, 45],
    ["2026-09-22", "订书钉", 4, 8, 32],
    ["2026-09-26", "便利贴", 10, 6, 60],
]

P = {"path": XLSX}
S = "流水"

tool_logged("create_workbook", dict(P, sheets=[S]))
tool_logged("write_range", dict(P, sheet=S, start_cell="A1", rows=HEADERS))
tool_logged("write_range", dict(P, sheet=S, start_cell="A2", rows=ROWS))
tool_logged("write_range", dict(P, sheet=S, start_cell="E14", rows=[["=SUM(E2:E13)"]]))

print("\n### read back full sheet (values mode, default)")
full = tool_logged("read_range", dict(P, sheet=S))
print(json.dumps(full, ensure_ascii=False, indent=1))

print("\n### read E14 values mode")
e14v = tool_logged("read_range", dict(P, sheet=S, range="E14:E14", mode="values"))
print(json.dumps(e14v, ensure_ascii=False))

print("\n### read E14 formulas mode")
e14f = tool_logged("read_range", dict(P, sheet=S, range="E14:E14", mode="formulas"))
print(json.dumps(e14f, ensure_ascii=False))

proc.stdin.close()
proc.wait(timeout=30)
log.close()
print("\nDONE, exit:", proc.returncode)
