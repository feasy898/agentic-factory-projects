"""webui.selftest —— M10 端到端自验收（httpx，真实走完整流水线）。

流程（对应规划 §6-M10 EVAL）：
  1. 选空闲端口，子进程拉起 ``python -m webui.app --host 127.0.0.1 --port N``
     （与本 selftest 同解释器，需装 fastapi/uvicorn/httpx——见 python/requirements.txt）；
  2. /api/health → 200 且 status=ok；
  3. GET / → 200 且页面零外链（无任何 http(s) 外部引用）；
  4. 模式 A：httpx multipart 上传 specs-eval/demo-zh.json → 200 → 轮询至 done →
     产物链接（预览/汇总页/质检报告/二维码/渠道包）逐个 GET 200，质检 0 fail；
  5. 模式 B：表单（match3 + zh 文案 + 上传 demo PNG）→ done → 链接 GET 200；
  6. 负向：坏 JSON spec → 400；未知模板 → 400；
  7. 收尾杀掉服务子进程。全部断言过 → 打印 SELFTEST PASS，exit 0。

用法：python -m webui.selftest [--timeout-sec 480]（工作目录任意；仓库根自定位）
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SPEC = REPO_ROOT / "specs-eval" / "demo-zh.json"
DEMO_PNG = REPO_ROOT / "specs-eval" / "assets" / "demo-zh" / "piece-0.png"
SERVER_LOG = REPO_ROOT / "artifacts" / "webui" / "_selftest-server.log"
HEALTH_WAIT_SEC = 60.0

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        FAILURES.append(f"{name}: {detail}")
    return ok


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def spawn_server(port: int) -> subprocess.Popen:
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(SERVER_LOG, "ab")
    return subprocess.Popen(
        [sys.executable, "-m", "webui.app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO_ROOT), stdout=log, stderr=subprocess.STDOUT,
    )


def wait_health(client: httpx.Client, deadline: float) -> bool:
    while time.monotonic() < deadline:
        try:
            r = client.get("/api/health", timeout=3)
            if r.status_code == 200 and r.json().get("status") == "ok":
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def await_job(client: httpx.Client, job_id: str, timeout_sec: float) -> dict:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/{job_id}", timeout=10)
        if r.status_code == 200:
            job = r.json()
            if job.get("status") in ("done", "failed"):
                return job
        time.sleep(2)
    return {"status": "poll-timeout"}


def run_build(client: httpx.Client, label: str, timeout_sec: float,
              expect_project: str, **kwargs) -> dict:
    """提交一个构建任务并等它落定；done 时断言产物链接全 200、质检 0 fail。"""
    print(f"[step] 构建（{label}）：POST /api/build")
    r = client.post("/api/build", timeout=60, **kwargs)
    if not check(f"{label}: POST /api/build → 200", r.status_code == 200,
                 f"exit {r.status_code} body={r.text[:300]}"):
        return {}
    job_id = r.json().get("id", "")
    job = await_job(client, job_id, timeout_sec)
    if not check(f"{label}: 任务 done（id={job_id}）", job.get("status") == "done",
                 f"status={job.get('status')} error={job.get('error')}"):
        print("  ---- make 日志尾 ----")
        print("\n".join(("      " + ln) for ln in (job.get("logTail") or "").splitlines()[-12:]))
        return job
    check(f"{label}: projectId={expect_project}", job.get("projectId") == expect_project,
          str(job.get("projectId")))
    qa = job.get("qa") or {}
    check(f"{label}: 质检 0 fail（pass={qa.get('pass')} skip={qa.get('skip')}）",
          qa.get("fail") == 0, str(qa))
    check(f"{label}: 自动试玩到结束页（pf:end win）", qa.get("endWin") is True, str(qa.get("endWin")))
    links = job.get("links") or {}
    for name in ("preview", "summary", "report", "pipeline"):
        url = links.get(name, "")
        resp = client.get(url, timeout=30) if url else None
        check(f"{label}: 链接 {name} → 200", resp is not None and resp.status_code == 200,
              f"{url} exit {getattr(resp, 'status_code', None)}")
    qr = client.get(f"/api/jobs/{job_id}/qr.png", timeout=30)
    check(f"{label}: 二维码 /api/jobs/…/qr.png → 200 PNG",
          qr.status_code == 200 and qr.content[:8] == b"\x89PNG\r\n\x1a\n",
          f"exit {qr.status_code} bytes={len(qr.content)}")
    pkgs = job.get("packages") or []
    check(f"{label}: 渠道包 ≥3", len(pkgs) >= 3, f"{len(pkgs)} 包")
    bad_href = None
    for p in pkgs:
        resp = client.get(p["href"], timeout=60)
        if resp.status_code != 200:
            bad_href = f"{p['channel']}/{p['locale']} → {resp.status_code}"
            break
    check(f"{label}: 渠道包产物逐个 GET 200", bad_href is None, bad_href or f"{len(pkgs)} 包全 200")
    return job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webui.selftest", description="webui 端到端自验收")
    parser.add_argument("--timeout-sec", type=float, default=480.0,
                        help="单个构建任务的轮询上限秒数（默认 480）")
    args = parser.parse_args(argv)

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    print(f"[step] 启动服务：python -m webui.app --host 127.0.0.1 --port {port}（日志 {SERVER_LOG.name}）")
    proc = spawn_server(port)
    t0 = time.monotonic()
    try:
        with httpx.Client(base_url=base) as client:
            ok = wait_health(client, time.monotonic() + HEALTH_WAIT_SEC)
            check("服务 /api/health → status=ok", ok,
                  "" if ok else f"{HEALTH_WAIT_SEC}s 内未就绪（见 {SERVER_LOG}）")
            if not ok:
                return finish(proc, t0)

            r = client.get("/")
            page = r.text
            check("GET / → 200", r.status_code == 200, f"exit {r.status_code}")
            import re as re_mod
            external = re_mod.findall(r'(?:src|href)\s*=\s*["\']https?://[^"\']+', page)
            check("单页零外链（无 http(s) 引用）", not external, "; ".join(external[:3]))

            r = client.get("/api/meta")
            meta = r.json() if r.status_code == 200 else {}
            check("GET /api/meta → 200 且模板 ≥3",
                  r.status_code == 200 and len(meta.get("templates", [])) >= 3,
                  str(r.status_code))

            # ---- 模式 A：上传 demo spec（demo-zh.json，中文三消） ------------
            spec_bytes = DEMO_SPEC.read_bytes()
            run_build(client, "A·上传spec", args.timeout_sec, "demo-zh",
                      files={"spec": ("demo-zh.json", spec_bytes, "application/json")})

            # ---- 模式 B：表单（match3 + zh 文案 + 上传 PNG） -----------------
            png_bytes = DEMO_PNG.read_bytes() if DEMO_PNG.is_file() else b""
            files = {"assets": ("piece-0.png", png_bytes, "image/png")} if png_bytes else None
            run_build(client, "B·表单组装", args.timeout_sec, "webui-match3",
                      data={"template": "match3", "locale": "zh",
                            "title": "宝石试玩（webui）", "cta": "马上玩",
                            "tutorial": "拖动宝石连成一线！", "win": "赢啦！",
                            "lose": "再挑战！", "score": "分数", "near_win": "true"},
                      files=files)

            # ---- 负向：坏 spec / 未知模板必须 400 ----------------------------
            r = client.post("/api/build", files={"spec": ("bad.json", b"{ not json", "application/json")})
            check("负向·坏 JSON spec → 400", r.status_code == 400, f"exit {r.status_code}")
            r = client.post("/api/build", data={"template": "not-a-template"})
            check("负向·未知模板 → 400", r.status_code == 400, f"exit {r.status_code}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    return finish(None, t0)


def finish(proc: subprocess.Popen | None, t0: float) -> int:
    elapsed = time.monotonic() - t0
    if FAILURES:
        print(f"SELFTEST FAIL（{len(FAILURES)} 项断言未过，耗时 {elapsed:.1f}s）：")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"SELFTEST PASS（全部断言通过，耗时 {elapsed:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
