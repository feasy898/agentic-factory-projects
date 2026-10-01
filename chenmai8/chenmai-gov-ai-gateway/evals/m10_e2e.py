"""M10 端到端验收入口（D0 收工线）：驱动 ops/e2e_smoke.py 全链路八用例 U1–U8，
并在 e2e 全绿后做 T5.3 收尾——三部门演示数据注入 + 库内三部门数据可查断言。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m10_e2e

exit 0 = 通过（= ops/e2e_smoke.py 的 ACTIVE 用例全 PASS、零 FAIL，且收尾的
三部门演示数据注入与可查断言通过）。

断言面（开发指令 §2 D0 行 + §9）：拉起 mock 上游 ×2（:8901/:8902 子进程）与网关
（:9000），断言——上游收到全占位符（bytes 级零原值）、客户端拿到还原答案、
密级样例被 403 拦截、审计入库且零明文。用例明细与拓扑见 ops/e2e_smoke.py 模块文档
（U1–U5 当天生效；U6 文件通道 D3 起生效；U7 注入拦截 T4.3 起生效——检索网页
埋注材料 403 INJECTION + 审计 flag=injection + 干净版负例对照；
U8 真实大模型全链 T6.2 起生效——config/app.yaml 真实上游 profiles 双腿
（INTERNET/GOVCLOUD）经 GPU 本地大模型服务真实推理，回复非空+还原+AI 标识+
上游 ring buffer 全文=脱敏版，上游离线（GPU 服务/隧道=环境依赖）时如实
DEFERRED 不计失败；其余未上线用例 DEFERRED 不计失败）。

T5.3 收尾（``_seed_demo_step``，跑后追加，不动 e2e 用例本身）：

1. e2e 退出后网关/审计写队列已随 lifespan 收尾，审计库文件即 §9 U5 口径的
   ``config/app.yaml audit_db``（data/audit.db；e2e 每轮开跑前重建，行内存的
   是本次 mock 链七用例 U1–U7 事件；U8 真实链路走独立临时审计库不入此库）；
2. 经 :func:`ops.seed_demo.seed_demo` 以**固定 base-ts** 注入三部门演示数据
   （18 事件 = 3 部门 × 6 请求，覆盖三路由），写路径即真实审计写队列
   （零明文硬闸），写后全库 bytes 级零明文复扫；
3. 重开库直读（:func:`audit.writer.read_events`）断言**库内三部门数据可查**：
   每部门演示事件数 == 6、部门集合 == config/dept_keys.yaml 三部门、
   路由混合 == INTERNET/GOVCLOUD/BLOCK 各 6、BLOCK 事件 blocked 位为真；
4. 再以进程内 ASGI 应用（临时 SQLite 审计库 + 内存会话注册表）冒烟看板
   「演示态一键切换」的服务面：``GET /webui/dashboard`` 200 且面板探针在位；
   ``POST /admin/api/demo/seed`` 无 Key → 401、带演示 Key → 三部门注入；
   ``GET /admin/api/demo/state`` 摘要一致；``POST /admin/api/demo/clear``
   只清演示事件（真实流量事件零误删）。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.e2e_smoke import main as smoke_main  # noqa: E402

# ── T5.3 收尾常量 ──────────────────────────────────────────────────
DEMO_PER_DEPT = 6                 # 每部门请求数（场景表一轮：2 INTERNET + 2 GOVCLOUD + 2 BLOCK）
DEMO_BASE_TS = "2026-09-29T09:30:00.000000Z"   # 固定 base-ts → 整库字节级可复现
DEMO_KEY = "dk_5e6f7a8b"          # 演示明文 key（民政局；config/dept_keys.yaml 只存其 sha256）


def _seed_demo_step() -> int:
    """T5.3 收尾：三部门演示数据注入 + 库内可查 + 看板演示态服务面冒烟。

    返回进程退出码（0 = 通过）；任何失败先打印原因再返回 1（gate 抓得到）。
    """
    from audit.writer import SqliteAuditWriter, read_events  # noqa: E402
    from common.config import (  # noqa: E402
        load_app_config,
        load_dept_keys,
        load_env_file,
        resolve_secret,
    )
    from gateway.app import create_app, resolve_db_path  # noqa: E402
    from masking.mapper import SessionRegistry  # noqa: E402
    from ops.seed_demo import demo_state_from_events, seed_demo  # noqa: E402

    def _fail(msg: str) -> int:
        print(f"[seed_demo] FAIL — {msg}", flush=True)
        return 1

    load_env_file()
    cfg = load_app_config()
    mask_key = resolve_secret(cfg.mask_key_env)   # 缺失即抛明确错误
    depts = list(load_dept_keys())
    db_path = resolve_db_path(cfg.audit_db)

    # ── ① 三部门演示数据注入（固定 base-ts；写路径 = 真实 SQLite 写队列）──
    writer = SqliteAuditWriter(db_path)
    try:
        summary = seed_demo(sink=writer, mask_key=mask_key, cfg=cfg, depts=depts,
                            per_dept=DEMO_PER_DEPT, base_ts=datetime.fromisoformat(
                                DEMO_BASE_TS.replace("Z", "+00:00")))
    finally:
        writer.close()

    inserted = summary["inserted"]
    routes = summary["routes"]
    per_dept = summary["per_dept_detail"]
    print(f"[seed_demo] 三部门演示数据注入: {len(depts)} 部门 × {DEMO_PER_DEPT} 请求 = "
          f"{inserted} 事件落库 {db_path}（"
          + " / ".join(f"{d}×{info['inserted']}" for d, info in per_dept.items())
          + f"）；路由 INTERNET {routes.get('INTERNET', 0)} / "
          f"GOVCLOUD {routes.get('GOVCLOUD', 0)} / BLOCK {routes.get('BLOCK', 0)}",
          flush=True)
    print(f"[seed_demo] 库文件 bytes 级零明文复扫: {summary['db_scan_bytes']} 字节，"
          f"0 命中（本次种子值 + 密级词 + 注入语句全在扫描清单）", flush=True)

    # ── ② 库内三部门数据可查（重开库直读，不经写队列实例）────────────────
    rows = read_events(db_path)
    demo_events = [e for _, e in rows if e.session_id.startswith("sess_demo_")]
    if len(demo_events) != inserted:
        return _fail(f"库内演示事件 {len(demo_events)} != 注入 {inserted}")
    seen_depts = {e.dept for e in demo_events}
    if seen_depts != set(depts):
        return _fail(f"库内演示部门集合 {sorted(seen_depts)} != 配置部门 {sorted(depts)}")
    for dept in depts:
        n = sum(1 for e in demo_events if e.dept == dept)
        if n != DEMO_PER_DEPT:
            return _fail(f"部门 {dept} 演示事件 {n} != {DEMO_PER_DEPT}")
    if routes.get("INTERNET") != DEMO_PER_DEPT or routes.get("GOVCLOUD") != DEMO_PER_DEPT \
            or routes.get("BLOCK") != DEMO_PER_DEPT:
        return _fail(f"路由混合不符: {routes}")
    if not all((e.route == "BLOCK") == e.blocked for e in demo_events):
        return _fail("演示事件 blocked 位与 route 不一致")
    state = demo_state_from_events([e for _, e in rows])
    if state["demo"] != inserted or not state["demo_seeded"]:
        return _fail(f"demo_state 摘要不符: demo={state['demo']} seeded={state['demo_seeded']}")
    print(f"[seed_demo] 库内三部门数据可查: {len(demo_events)} 条演示事件，部门 "
          + " / ".join(f"{d['dept']}×{d['demo']}" for d in state["by_dept"])
          + f"；总事件 {state['total']}（含 e2e mock 链用例）", flush=True)

    # ── ③ 看板演示态服务面冒烟（进程内 ASGI；临时库，不碰真实审计库）──────
    tmp_dir = REPO_ROOT / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    tmp_db = tmp_dir / "seed_demo_step_audit.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(tmp_db) + suffix).unlink(missing_ok=True)
    probe_writer = SqliteAuditWriter(tmp_db)
    try:
        app = create_app(cfg=cfg, mask_key=mask_key,
                         dept_key_digests=load_dept_keys(),
                         audit_store=probe_writer,
                         session_registry=SessionRegistry(mask_key.encode("utf-8")))
        problems = _probe_demo_api(app)
    finally:
        probe_writer.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(tmp_db) + suffix).unlink(missing_ok=True)
    if problems:
        return _fail(problems)
    print("[seed_demo] 演示态一键切换冒烟: 看板页 200+面板探针；seed 无 Key 401 / "
          "带 Key 三部门注入；state 摘要一致；clear 只清演示事件", flush=True)

    print(f"m10_e2e(+T5.3 演示数据): e2e 八用例全 PASS + seed_demo {inserted} 事件"
          f"三部门可查（{'/'.join(depts)}）", flush=True)
    return 0


def _probe_demo_api(app: Any) -> str:
    """进程内 ASGI 冒烟看板演示态服务面；返回失败原因（空串 = 通过）。"""
    import asyncio  # noqa: PLC0415 — 与 m9_webui 同一 asyncio.run 口径

    import httpx  # noqa: PLC0415

    async def _run() -> list[str]:
        problems: list[str] = []
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://anongw.test") as client:
            page = await client.get("/webui/dashboard")
            if page.status_code != 200:
                problems.append(f"看板页 status={page.status_code}")
            for probe in ("演示态一键切换", "demo-seed-btn", "demo-clear-btn",
                          "/admin/api/demo/", "sess_demo_"):
                if probe not in page.text:
                    problems.append(f"看板页探针缺失: {probe}")

            auth = {"Authorization": f"Bearer {DEMO_KEY}"}
            unauth = await client.post("/admin/api/demo/seed")
            if unauth.status_code != 401:
                problems.append(f"seed 无 Key 应 401: {unauth.status_code}")
            seeded = await client.post("/admin/api/demo/seed", headers=auth)
            if seeded.status_code != 200:
                problems.append(f"seed 带 Key status={seeded.status_code} "
                                f"{seeded.text[:200]!r}")
                return problems
            payload = seeded.json()
            depts = payload.get("depts") or []
            if len(depts) != 3 or payload.get("inserted") != 3 * DEMO_PER_DEPT:
                problems.append(f"seed 摘要异常: {payload.get('inserted')} depts={depts}")
            if payload.get("routes", {}).get("BLOCK") != DEMO_PER_DEPT:
                problems.append(f"seed 路由混合异常: {payload.get('routes')}")

            state = await client.get("/admin/api/demo/state", headers=auth)
            if state.status_code != 200:
                problems.append(f"state status={state.status_code}")
            else:
                st = state.json()
                if st.get("demo") != 3 * DEMO_PER_DEPT or not st.get("demo_seeded"):
                    problems.append(f"state 摘要异常: demo={st.get('demo')}")
                if len(st.get("by_dept") or []) != 3:
                    problems.append(f"state 按部门条目异常: {st.get('by_dept')}")

            # 幂等：重复 seed（replace 语义）不叠加
            again = await client.post("/admin/api/demo/seed", headers=auth)
            if again.status_code != 200 or again.json().get("inserted") != 3 * DEMO_PER_DEPT:
                problems.append(f"重复 seed 非幂等: {again.status_code}")

            cleared = await client.post("/admin/api/demo/clear", headers=auth)
            if cleared.status_code != 200 or cleared.json().get("removed") != 3 * DEMO_PER_DEPT:
                problems.append(f"clear 异常: {cleared.status_code} {cleared.text[:200]!r}")
            after = await client.get("/admin/api/demo/state", headers=auth)
            if after.status_code != 200 or after.json().get("demo_seeded"):
                problems.append("clear 后仍有演示态数据")
        return problems

    problems = asyncio.run(_run())
    return "；".join(problems)


def main() -> int:
    print("== evals.m10_e2e → ops/e2e_smoke（§9 八用例：U1–U7 + U8 真实大模型全链）==",
          flush=True)
    rc = smoke_main()
    if rc != 0:
        return rc
    print("=" * 64, flush=True)
    return _seed_demo_step()


if __name__ == "__main__":
    sys.exit(main())
