#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zctl-mcp 确定性评测器（G0-1 绿 / G0-2 红 / exit 2 用法错）。

用法：
  python eval/runner.py <被测产物根> <oracle根>
  python eval/runner.py                     # 自评：被测=本资产根，oracle=本资产 oracle/

被测产物根解析：<root>/package/mcp-server.mjs（或 <root>/mcp-server.mjs）。
评测流程（全离线、零凭据、零网络）：
  1) spawn `node mcp-server.mjs`，发送 initialize 握手 + tools/list；
  2) 与 oracle/expected_tools.json 冻结期望比对：
     a. serverInfo.name/version、protocolVersion；
     b. 工具名集合恰等（不多不少）；
     c. 每工具 description 含期望关键词、inputSchema.required 恰等；
     d. 禁止出现的变更类工具名（forbidden_tool_names）一个都不许在列。
  3) 全过 → stdout 打 JSON（无时间戳）exit 0；任一失败 → exit 1。
用法错（参数数为 0 且不在资产根、或参数个数=1）→ exit 2。

红路 fail-closed：对空目录（无 server 文件）→ exit 1；永不修成 exit 0。
确定性：不读时钟、无随机；同输入同输出。
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET_ROOT = os.path.normpath(os.path.join(HERE, ".."))
DEFAULT_ORACLE = os.path.join(ASSET_ROOT, "oracle")

INIT_TIMEOUT = 30.0


def fail(checks, name, detail):
    checks.append({"name": name, "passed": False, "detail": detail})


def passk(checks, name, detail):
    checks.append({"name": name, "passed": True, "detail": detail})


def resolve_candidate(root):
    for rel in (os.path.join("package", "mcp-server.mjs"), "mcp-server.mjs"):
        p = os.path.join(root, rel)
        if os.path.isfile(p):
            return p
    return None


def rpc(session, obj, expect_id):
    """写一行 JSON-RPC，读到 id 匹配的响应（跳过通知）。超时/进程死 → None。"""
    import threading

    session["stdin"].write(json.dumps(obj) + "\n")
    session["stdin"].flush()
    ev = threading.Event()
    result = {}

    def pump():
        for line in session["pump_lines"]:
            pass

    # 简化：pump 线程已把行放进 queue；这里带超时等匹配 id
    import queue as _q
    q = session["lines"]
    deadline = INIT_TIMEOUT
    import time
    end = time.time() + deadline
    while time.time() < end:
        try:
            line = q.get(timeout=max(0.05, end - time.time()))
        except _q.Empty:
            break
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("id") == expect_id:
            result["msg"] = msg
            return result
    return None


def talk_to_server(server_path):
    """启动 server，完成 initialize + tools/list。返回 (init_result, tools, stderr_text) 或抛 RuntimeError。"""
    import threading
    import queue as _q

    proc = subprocess.Popen(
        ["node", server_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=os.path.dirname(server_path),
    )
    q = _q.Queue()

    def pump():
        for line in proc.stdout:
            q.put(line)
        q.put(None)

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    session = {"stdin": proc.stdin, "lines": q, "pump_lines": []}

    init = rpc(session, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05",
                   "capabilities": {},
                   "clientInfo": {"name": "zctl-mcp-eval", "version": "1.0.0"}},
    }, 1)
    if init is None:
        proc.kill()
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError("initialize 无响应或超时；stderr=%s" % err[-400:])
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    proc.stdin.flush()

    tl = rpc(session, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, 2)
    proc.kill()
    if tl is None:
        raise RuntimeError("tools/list 无响应或超时")
    return init["msg"]["result"], tl["msg"]["result"], ""


def evaluate(candidate_root, oracle_root):
    checks = []
    expected_path = os.path.join(oracle_root, "expected_tools.json")
    if not os.path.isfile(expected_path):
        fail(checks, "oracle_present", "oracle/expected_tools.json 不存在: %s" % expected_path)
        return False, checks, None
    with open(expected_path, "rb") as f:
        expected = json.loads(f.read().decode("utf-8-sig"))

    server = resolve_candidate(candidate_root)
    if server is None:
        fail(checks, "server_present",
             "被测产物根未解析出 mcp-server.mjs（已尝试 <root>/package/mcp-server.mjs 与 <root>/mcp-server.mjs）: %s" % candidate_root)
        return False, checks, None

    try:
        init_result, tl_result, _ = talk_to_server(server)
    except Exception as exc:  # noqa: BLE001 — 评测器要把一切失败收敛为 exit 1
        fail(checks, "mcp_handshake", "握手/列举失败：%s" % exc)
        return False, checks, None

    info = init_result.get("serverInfo", {})
    if info.get("name") != expected["serverInfo"]["name"] or info.get("version") != expected["serverInfo"]["version"]:
        fail(checks, "server_info", "serverInfo 不符：实测 %r 期望 %r" % (info, expected["serverInfo"]))
    else:
        passk(checks, "server_info", "serverInfo 一致：%s@%s" % (info.get("name"), info.get("version")))

    tools = {t.get("name"): t for t in tl_result.get("tools", [])}
    exp_tools = {t["name"]: t for t in expected["tools"]}
    if set(tools) != set(exp_tools):
        fail(checks, "tool_set_exact",
             "工具名集合不恰等：多 %r 缺 %r" % (sorted(set(tools) - set(exp_tools)), sorted(set(exp_tools) - set(tools))))
    else:
        passk(checks, "tool_set_exact", "4 工具恰等：%s" % sorted(tools))

    for name, exp in sorted(exp_tools.items()):
        got = tools.get(name)
        if got is None:
            continue
        desc = got.get("description", "")
        miss_kw = [kw for kw in exp["description_contains"] if kw not in desc]
        req = sorted((got.get("inputSchema") or {}).get("required") or [])
        exp_req = sorted(exp["inputSchema_required"])
        if miss_kw or req != exp_req:
            fail(checks, "tool_contract:%s" % name,
                 "description 缺关键词 %r；required 实测 %r 期望 %r" % (miss_kw, req, exp_req))
        else:
            passk(checks, "tool_contract:%s" % name, "关键词齐备；required=%r" % req)

    forbidden = [n for n in expected.get("forbidden_tool_names", []) if n in tools]
    if forbidden:
        fail(checks, "mutating_tools_absent", "出现被禁止的变更类工具：%r" % forbidden)
    else:
        passk(checks, "mutating_tools_absent", "变更类工具零暴露（reset use/offpeak take/settle 均不在列）")

    ok = all(c["passed"] for c in checks)
    return ok, checks, {"tools": sorted(tools)}


def main(argv):
    if len(argv) == 0:
        candidate, oracle = ASSET_ROOT, DEFAULT_ORACLE
    elif len(argv) == 2:
        candidate, oracle = argv
    else:
        print("用法：python eval/runner.py [<被测产物根> <oracle根>]；零参数=自评", file=sys.stderr)
        return 2

    ok, checks, extra = evaluate(candidate, oracle)
    summary = {
        "total": len(checks),
        "pass": sum(1 for c in checks if c["passed"]),
        "fail": sum(1 for c in checks if not c["passed"]),
        "tested_root": os.path.abspath(candidate),
        "reference_root": os.path.abspath(oracle),
    }
    print(json.dumps({"ok": ok, "summary": summary, "checks": checks,
                      "tools_seen": extra}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
