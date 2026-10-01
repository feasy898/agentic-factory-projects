#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_samples.py — mcp-office-pack 样例实跑器

对 mcp.office.json 的每一条 server 做一次真实 MCP 协议握手：
  - stdio 条目：启动进程，发送 initialize → notifications/initialized → tools/list，
    记录协议版本、serverInfo 与工具数。
  - http 条目：POST initialize 到远端端点，解析 JSON/SSE 响应。
占位符（${VAR}）在实跑时以哑值注入（仅用于让进程启动，绝不使用真实密钥）。
结果写 out/samples.json，逐条含 status: pass|fail 与证据（serverInfo/工具数/HTTP 状态码）。

用法：python run_samples.py [--config mcp.office.json] [--out out/samples.json] [--timeout 240]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent

INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "mcp-office-pack-oracle", "version": "1.0.0"},
    },
}
INITIALIZED_NOTICE = {"jsonrpc": "2.0", "method": "notifications/initialized"}
TOOLS_REQUEST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def expand(value: str, scratch_dir: str) -> str:
    """占位符替换为哑值（仅协议握手用，不含真实密钥）。

    路径型占位符（*_DIR/*_PATH/*_ROOT）替换为真实存在的临时目录，
    否则 filesystem 类 server 会因目录不可访问拒绝启动。
    """
    def repl(match: "re.Match[str]") -> str:
        var = match.group(1)
        if var.endswith(("_DIR", "_PATH", "_ROOT")):
            return scratch_dir
        return "oracle-probe-dummy"
    return re.sub(r"\$\{([A-Z0-9_]+)\}", repl, value)


def resolve_cmd(command: str) -> str:
    """Windows 下 npx/npm 等是 .cmd shim，create_subprocess_exec 需要 which 解析。"""
    found = shutil.which(command)
    if found:
        return found
    found = shutil.which(command + ".cmd") or shutil.which(command + ".exe")
    if found:
        return found
    return command


async def probe_stdio(entry: dict, timeout: float) -> dict:
    scratch_dir = str((BASE / "out" / "probe-scratch").resolve())
    Path(scratch_dir).mkdir(parents=True, exist_ok=True)
    cmd = [resolve_cmd(entry["command"])] + [expand(a, scratch_dir) for a in entry.get("args", [])]
    env = {k: expand(v, scratch_dir) for k, v in entry.get("env", {}).items()}
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "error": f"进程启动失败: {exc}", "cmd": cmd}

    async def read_messages():
        while True:
            line = await proc.stdout.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            # 兼容 LSP 式 Content-Length 帧：MCP stdio 默认按行 JSON
            if text.startswith("{"):
                try:
                    yield json.loads(text)
                except json.JSONDecodeError:
                    continue

    init_result = None
    tools_result = None
    stderr_tail = ""

    async def handshake() -> None:
        nonlocal init_result, tools_result
        # 1) 先发 initialize，再等 id==1 响应
        proc.stdin.write((json.dumps(INIT_REQUEST) + "\n").encode())
        await proc.stdin.drain()
        async for msg in read_messages():
            if msg.get("id") == 1:
                init_result = msg
                break
        # 2) initialized 通知 + tools/list
        proc.stdin.write((json.dumps(INITIALIZED_NOTICE) + "\n").encode())
        proc.stdin.write((json.dumps(TOOLS_REQUEST) + "\n").encode())
        await proc.stdin.drain()
        async for msg in read_messages():
            if msg.get("id") == 2:
                tools_result = msg
                break

    try:
        await asyncio.wait_for(handshake(), timeout=timeout)
    except asyncio.TimeoutError:
        stderr_tail = f"握手超时（> {timeout:.0f}s，含首次拉包时间）"
    except Exception as exc:  # noqa: BLE001
        stderr_tail = exc.__class__.__name__ + ": " + str(exc)
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except Exception:  # noqa: BLE001
            pass
        try:
            err = await asyncio.wait_for(proc.stderr.read(), timeout=5)
            stderr_tail = (err.decode("utf-8", errors="replace") if err else "")[-400:] or stderr_tail
        except Exception:  # noqa: BLE001
            pass

    if init_result is None:
        return {
            "status": "fail",
            "error": stderr_tail or "stdio 无 initialize 响应",
            "elapsed_s": round(time.monotonic() - t0, 1),
        }
    result = init_result.get("result", {})
    tools = (tools_result or {}).get("result", {}).get("tools")
    return {
        "status": "pass",
        "server_info": result.get("serverInfo"),
        "protocol_version": result.get("protocolVersion"),
        "tools_count": len(tools) if isinstance(tools, list) else None,
        "tools_list": sorted(t.get("name", "?") for t in tools)[:12] if isinstance(tools, list) else None,
        "elapsed_s": round(time.monotonic() - t0, 1),
    }


async def probe_http(entry: dict, timeout: float) -> dict:
    import urllib.request

    url = entry["url"]
    t0 = time.monotonic()
    body = json.dumps(INIT_REQUEST).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    def do_post():
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read().decode("utf-8", errors="replace")

    try:
        status, hdrs, text = await asyncio.wait_for(asyncio.to_thread(do_post), timeout=timeout + 10)
    except Exception as exc:  # noqa: BLE001
        return {"status": "fail", "error": f"{exc.__class__.__name__}: {exc}"}

    snippet = text[:300].replace("\n", " ")
    # 解析 JSON 或 SSE data: 行中的 jsonrpc 消息（按行解析，SSE 的 data 行是完整 JSON）
    payload = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                candidate = line[len("data:"):].strip()
                try:
                    payload = json.loads(candidate)
                    break
                except json.JSONDecodeError:
                    continue
    auth_required = status in (401, 403) or (
        isinstance(payload, dict) and payload.get("error", {}).get("code") in (-32001, -32002)
    ) or "oauth" in text.lower()[:800]
    evidence = {
        "http_status": status,
        "content_type": hdrs.get("Content-Type") or hdrs.get("content-type"),
        "mcp_rpc": payload if isinstance(payload, dict) else None,
        "body_snippet": snippet,
    }
    if isinstance(payload, dict) and "result" in payload:
        result = payload["result"]
        evidence.update({
            "server_info": result.get("serverInfo"),
            "protocol_version": result.get("protocolVersion"),
        })
        evidence["verdict"] = "initialize 成功（匿名可达）"
        evidence["status"] = "pass"
    elif auth_required:
        evidence["verdict"] = "端点为 MCP 服务且要求授权（OAuth），匿名握手被拒——端点活性已证实"
        evidence["status"] = "pass_auth_required"
    else:
        evidence["verdict"] = "HTTP 可达但未见合法 MCP 响应"
        evidence["status"] = "fail"
    evidence["elapsed_s"] = round(time.monotonic() - t0, 1)
    return evidence


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="mcp-office-pack 样例实跑器")
    parser.add_argument("--config", default=str(BASE / "mcp.office.json"))
    parser.add_argument("--out", default=str(BASE / "out" / "samples.json"))
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    servers = config["mcpServers"]
    samples = []
    for name, entry in servers.items():
        etype = entry.get("type")
        print(f"[run] {name} ({etype}) …", flush=True)
        try:
            if etype == "stdio":
                res = await probe_stdio(entry, args.timeout)
            elif etype == "http":
                res = await probe_http(entry, args.timeout)
            else:
                res = {"status": "fail", "error": f"未知 type: {etype}"}
        except Exception as exc:  # noqa: BLE001
            res = {"status": "fail", "error": f"{exc.__class__.__name__}: {exc}"}
        res["type"] = etype
        samples.append({"name": name, **res})
        print(f"[{res['status'].upper()}] {name}: "
              f"{res.get('server_info') or res.get('verdict') or res.get('error')}", flush=True)

    passed = sum(1 for s in samples if str(s.get("status")).startswith("pass"))
    report = {
        "oracle": "mcp-office-pack",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config": str(Path(args.config).resolve()),
        "method": "stdio: JSON-RPC initialize + tools/list 握手；http: POST initialize",
        "samples": samples,
        "summary": {
            "total": len(samples),
            "passed": passed,
            "failed": len(samples) - passed,
            "note": "pass=协议握手成功；pass_auth_required=远程端点活性证实但要求 OAuth",
        },
    }
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"summary: {report['summary']}  -> {out_path}")
    return 0 if passed == len(samples) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
