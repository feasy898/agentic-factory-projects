#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mcp-office-pack 样例实跑器（run_samples.py，可选件）。

行为规格：spec.md §7（R1–R4）。
  R1 stdio 条目：启动进程，发送 initialize（protocolVersion 2025-03-26）→
      notifications/initialized → tools/list；收到 id==1 合法 result 即协议握手成功
      （status=pass），记录 serverInfo / protocolVersion / 工具数。
  R2 http 条目：POST initialize 到远端端点；HTTP 200 + 合法 result → pass；
      HTTP 401/403、JSON-RPC error code −32001/−32002、或响应前 800 字符含 oauth →
      pass_auth_required（端点活性证实、要求 OAuth，计入通过）；其余 → fail。
  R3 占位符哑值注入：${VAR} 以哑值替换——以 _DIR/_PATH/_ROOT 结尾的变量替换为真实存在的
      临时目录（否则 filesystem 类 server 拒绝启动），其余替换为 oracle-probe-dummy；
      绝不使用真实密钥。
  R4 产物与退出码：写 out/samples.json（逐条 status + 证据 + elapsed_s）；exit 0 当且仅当
      全部条目 status 以 pass 开头。

命令行（contract §2）：python run_samples.py [--config <path>] [--out <path>] [--timeout <秒>]
  缺省 --config 本脚本同目录 mcp.office.json、--out 本脚本同目录 out/samples.json（相对 BASE，
  不依赖调用方 cwd）。不做工具调用实跑：止步于协议握手 + tools/list（spec §10 边界）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import queue
from pathlib import Path
from urllib import error as urlerr
from urllib import request as urlreq

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
PROTO = "2025-03-26"
DUMMY = "oracle-probe-dummy"           # spec §7 R3 固定哑值
DIR_SUFFIXES = ("_DIR", "_PATH", "_ROOT")
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": PROTO, "capabilities": {},
                   "clientInfo": {"name": "mcp-office-pack-samples", "version": "1.0.0"}}}
INITED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


# ---------------------------------------------------------------- 哑值注入（R3）

def dummy_sub(value: str, tmpdir: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        return tmpdir if m.group(1).endswith(DIR_SUFFIXES) else DUMMY
    return PLACEHOLDER_RE.sub(repl, value)


def dummy_args(entry: dict, tmpdir: str) -> list:
    return [dummy_sub(a, tmpdir) for a in entry.get("args", []) if isinstance(a, str)]


def dummy_env(entry: dict, tmpdir: str) -> dict:
    env = entry.get("env") or {}
    return {k: dummy_sub(v, tmpdir) for k, v in env.items()
            if isinstance(k, str) and isinstance(v, str)}


# ---------------------------------------------------------------- stdio（R1）

def tree_kill(proc: subprocess.Popen) -> None:
    """Windows 下 uvx/npx 会派生子进程持管道，须按进程树击杀。"""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def stdio_sample(name: str, entry: dict, tmpdir: str, timeout: int) -> dict:
    t0 = time.time()
    command = entry.get("command") or ""
    resolved = shutil.which(command) or command
    argv = [resolved] + dummy_args(entry, tmpdir)
    env = os.environ.copy()
    env.update(dummy_env(entry, tmpdir))
    sample = {"name": name, "type": "stdio", "status": "fail",
              "command": [command] + dummy_args(entry, tmpdir)}
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, text=True,
                                encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        sample["verdict"] = "spawn 失败: %r" % e
        sample["elapsed_s"] = round(time.time() - t0, 1)
        return sample

    q: "queue.Queue" = queue.Queue()
    threading.Thread(target=lambda: [q.put(ln) for ln in proc.stdout] or q.put(None),
                     daemon=True).start()
    qe: "queue.Queue" = queue.Queue()
    threading.Thread(target=lambda: [qe.put(ln) for ln in proc.stderr] or qe.put(None),
                     daemon=True).start()

    server_info = proto_ver = tools = None
    verdict = None
    deadline = time.time() + timeout
    try:
        proc.stdin.write(json.dumps(INIT) + "\n")
        proc.stdin.flush()
    except Exception as e:  # noqa: BLE001
        verdict = "stdin 写入失败: %r" % e
    if verdict is None:
        while time.time() < deadline:
            try:
                line = q.get(timeout=1.0)
            except queue.Empty:
                continue
            if line is None:
                verdict = "进程提前退出（stdout EOF）"
                break
            try:
                msg = json.loads(line.strip())
            except Exception:
                continue
            if msg.get("id") == 1:
                if "result" in msg:
                    res = msg["result"]
                    server_info = res.get("serverInfo")
                    proto_ver = res.get("protocolVersion")
                    try:
                        proc.stdin.write(json.dumps(INITED) + "\n")
                        proc.stdin.write(json.dumps(TOOLS_LIST) + "\n")
                        proc.stdin.flush()
                    except Exception:
                        pass  # 握手已成功，tools/list 尽力而为
                else:
                    verdict = "initialize 返回 error: %s" % json.dumps(msg.get("error"))[:200]
                break
        else:
            verdict = "握手超时（>%ds，含首跑拉包时间）" % timeout
        if verdict is None and server_info is not None:
            # 握手成功（R1：id==1 合法 result 即 pass），再等 tools/list 补工具数
            list_deadline = time.time() + min(60, max(5, deadline - time.time()))
            while time.time() < list_deadline:
                try:
                    line = q.get(timeout=1.0)
                except queue.Empty:
                    continue
                if line is None:
                    break
                try:
                    msg = json.loads(line.strip())
                except Exception:
                    continue
                if msg.get("id") == 2 and "result" in msg:
                    tools = len(msg["result"].get("tools", []))
                    break
                if msg.get("id") == 2 and "error" in msg:
                    break
    tree_kill(proc)

    etail = []
    while len(etail) < 4:
        try:
            ln = qe.get(timeout=0.5)
        except queue.Empty:
            break
        if ln is None:
            break
        etail.append(ln.rstrip()[:200])

    sample["server_info"] = server_info
    sample["protocol_version"] = proto_ver
    sample["tool_count"] = tools
    sample["elapsed_s"] = round(time.time() - t0, 1)
    if server_info is not None:
        sample["status"] = "pass"
        sample["verdict"] = "stdio 握手成功（initialize %s）" % PROTO
    else:
        sample["verdict"] = verdict or "未收到 id==1 合法 result"
        if etail:
            sample["stderr_tail"] = etail[-2:]
    return sample


# ---------------------------------------------------------------- http（R2）

def _parse_body(raw: str, ctype: str):
    """JSON 或 SSE（data: 行）→ JSON-RPC 消息或 None。"""
    if "text/event-stream" in ctype or raw.lstrip().startswith(("event:", "data:")):
        for ln in raw.splitlines():
            ln = ln.strip()
            if ln.startswith("data:"):
                try:
                    m = json.loads(ln[5:].strip())
                    if isinstance(m, dict) and m.get("id") == 1:
                        return m
                except Exception:
                    continue
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def http_sample(name: str, entry: dict, tmpdir: str, timeout: int) -> dict:
    t0 = time.time()
    url = dummy_sub(entry.get("url") or "", tmpdir)
    sample = {"name": name, "type": "http", "status": "fail", "url": url}
    body = json.dumps(INIT).encode("utf-8")
    req = urlreq.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "mcp-office-pack-samples/1.0.0",
    })
    try:
        with urlreq.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", errors="replace")
    except urlerr.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        head = raw[:800].lower()
        sample["http_status"] = e.code
        if e.code in (401, 403) or "oauth" in head or "-32001" in head or "-32002" in head:
            sample["status"] = "pass_auth_required"
            sample["verdict"] = "端点活性证实，要求 OAuth（HTTP %d）" % e.code
        else:
            sample["verdict"] = "HTTP %d（非 OAuth 证据）" % e.code
            sample["evidence"] = raw[:200]
        sample["elapsed_s"] = round(time.time() - t0, 1)
        return sample
    except Exception as e:  # noqa: BLE001
        sample["verdict"] = "请求失败: %r" % e
        sample["elapsed_s"] = round(time.time() - t0, 1)
        return sample

    sample["http_status"] = status
    sample["content_type"] = ctype
    head = raw[:800].lower()
    msg = _parse_body(raw, ctype)
    if isinstance(msg, dict) and msg.get("id") == 1 and "result" in msg:
        res = msg["result"]
        sample["status"] = "pass"
        sample["server_info"] = res.get("serverInfo")
        sample["protocol_version"] = res.get("protocolVersion")
        sample["verdict"] = "HTTP %d + 合法 initialize result（匿名可达）" % status
    elif "oauth" in head or "-32001" in head or "-32002" in head:
        sample["status"] = "pass_auth_required"
        sample["verdict"] = "端点活性证实，要求 OAuth（响应前 800 字符证据）"
    else:
        sample["verdict"] = "HTTP %d 但无合法 initialize result" % status
        sample["evidence"] = raw[:300]
    sample["elapsed_s"] = round(time.time() - t0, 1)
    return sample


# ---------------------------------------------------------------- 主流程（R4）

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mcp-office-pack 样例实跑器（spec §7）")
    ap.add_argument("--config", default=None, help="配置路径（缺省 mcp.office.json，相对脚本目录）")
    ap.add_argument("--out", default=None, help="报告路径（缺省 out/samples.json，相对脚本目录）")
    ap.add_argument("--timeout", type=int, default=600,
                    help="单条目超时秒数（缺省 600；workspace-mcp 冷拉包可达数分钟）")
    args = ap.parse_args(argv)

    cfg_path = Path(args.config) if args.config else BASE / "mcp.office.json"
    if not cfg_path.is_absolute():
        cfg_path = BASE / cfg_path
    out_path = Path(args.out) if args.out else BASE / "out" / "samples.json"
    if not out_path.is_absolute():
        out_path = BASE / out_path

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        print("mcpServers 缺失或为空，无法实跑")
        return 1

    tmpdir = tempfile.mkdtemp(prefix="officepack-samples-")  # R3：真实存在的哑目录
    samples = []
    for name, entry in servers.items():
        entry = entry if isinstance(entry, dict) else {}
        if entry.get("type") == "http":
            s = http_sample(name, entry, tmpdir, args.timeout)
        else:
            s = stdio_sample(name, entry, tmpdir, args.timeout)
        samples.append(s)
        print("[%-6s] %-18s %s  (%ss)"
              % (s["status"], name, s.get("verdict", ""), s.get("elapsed_s", "?")))
        try:
            sys.stdout.flush()
        except Exception:
            pass

    passed = sum(1 for s in samples if s["status"].startswith("pass"))
    report = {"samples": samples,
              "summary": {"total": len(samples), "passed": passed,
                          "failed": len(samples) - passed}}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print("summary: %d/%d passed → %s" % (passed, len(samples),
                                          out_path.relative_to(BASE) if out_path.is_relative_to(BASE) else out_path))
    return 0 if passed == len(samples) and samples else 1


if __name__ == "__main__":
    sys.exit(main())
