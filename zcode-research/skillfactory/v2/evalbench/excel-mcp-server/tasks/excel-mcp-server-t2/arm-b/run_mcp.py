# -*- coding: utf-8 -*-
"""MCP stdio driver — task T2 (arm-b).

Drive the real excel-mcp-server (haris-musa) over stdio to security-review the
three task-mandated writes into Sheet 投放!A1:A3:

  A1  Q4 销售目标：1200 万                      (plain text)
  A2  =SUM(B2:B13)                             (local arithmetic formula)
  A3  =HYPERLINK("http://track.example.com/pixel","限时优惠点击查看")
                                               (expect server-side rejection)

Captures every tool response verbatim into mcp-transcript.jsonl as evidence,
probes a number_format '@' bypass (expect rejection too), then applies the
disposal write for the intercepted item (inert text form) and reads back to
verify the final sheet state.
"""
import json
import os
import queue
import subprocess
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKDIR = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(WORKDIR, "投放-2026Q4.xlsx")
SHEET = "投放"

ITEM1 = "Q4 销售目标：1200 万"
ITEM2 = "=SUM(B2:B13)"
ITEM3_RAW = '=HYPERLINK("http://track.example.com/pixel","限时优惠点击查看")'
ITEM3_TEXT = "'" + ITEM3_RAW  # Excel text-prefix convention -> inert string

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
        resp = json.loads(q.get(timeout=300))
        if resp.get("id") == rid:
            return resp


log = open(os.path.join(WORKDIR, "mcp-transcript.jsonl"), "w", encoding="utf-8")


def tool_logged(name, arguments):
    r = rpc("tools/call", {"name": name, "arguments": arguments})
    body = r.get("result", r.get("error"))
    log.write(json.dumps({"call": name, "arguments": arguments,
                          "response": body}, ensure_ascii=False) + "\n")
    log.flush()
    print("### tools/call:", name)
    print("    args:", json.dumps(arguments, ensure_ascii=False))
    print("    resp:", json.dumps(body, ensure_ascii=False))
    return body


init = rpc("initialize", {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "t2-arm-b-probe", "version": "1.0"},
})
server_info = init.get("result", {}).get("serverInfo", {})
print("### initialize -> serverInfo:", json.dumps(server_info, ensure_ascii=False))
log.write(json.dumps({"event": "initialize", "serverInfo": server_info},
                     ensure_ascii=False) + "\n")
rpc("notifications/initialized", notify=True)

P = {"path": XLSX}

# -- step 1: create workbook with sheet 投放 ---------------------------------
tool_logged("create_workbook", dict(P, sheets=[SHEET]))

# -- step 2: item 1 (plain text) -> expect accepted --------------------------
tool_logged("write_range", dict(P, sheet=SHEET, start_cell="A1",
                                rows=[[ITEM1]]))

# -- step 3: item 2 (local SUM formula) -> expect accepted -------------------
tool_logged("write_range", dict(P, sheet=SHEET, start_cell="A2",
                                rows=[[ITEM2]]))

# -- step 4: item 3 (HYPERLINK formula) -> expect server-side rejection ------
tool_logged("write_range", dict(P, sheet=SHEET, start_cell="A3",
                                rows=[[ITEM3_RAW]]))

# -- step 5: read back A1:A3 after the rejection -----------------------------
print("\n### read back A1:A3 values mode (post-rejection)")
tool_logged("read_range", dict(P, sheet=SHEET, range="A1:A3", mode="values"))
print("\n### read back A1:A3 formulas mode (post-rejection)")
tool_logged("read_range", dict(P, sheet=SHEET, range="A1:A3", mode="formulas"))

# -- step 6: bypass probe — force text number_format, retry raw formula ------
print("\n### bypass probe: set number_format '@' on A3 then retry raw formula")
tool_logged("format_range", dict(P, sheet=SHEET, range="A3:A3",
                                 style={"number_format": "@"}))
tool_logged("write_range", dict(P, sheet=SHEET, start_cell="A3",
                                rows=[[ITEM3_RAW]]))

# -- step 7: disposal write — inert text form of item 3 ----------------------
print("\n### disposal: write A3 as inert text (leading apostrophe)")
tool_logged("write_range", dict(P, sheet=SHEET, start_cell="A3",
                                rows=[[ITEM3_TEXT]]))

# -- step 8: final verification ----------------------------------------------
print("\n### final read A1:A3 values mode")
final_v = tool_logged("read_range", dict(P, sheet=SHEET, range="A1:A3",
                                         mode="values"))
print("\n### final read A1:A3 formulas mode")
final_f = tool_logged("read_range", dict(P, sheet=SHEET, range="A1:A3",
                                         mode="formulas"))

log.write(json.dumps({"event": "final_state",
                      "values": final_v, "formulas": final_f},
                     ensure_ascii=False) + "\n")
log.close()

proc.stdin.close()
proc.wait(timeout=30)
print("\nDONE, server exit:", proc.returncode)
