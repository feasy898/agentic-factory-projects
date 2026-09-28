"""cs_dashboard eval（开发指令 §5.7 / §10.2）。

按 spec 原样验收：
- 起真实 uvicorn 于随机端口（非 TestClient 内联传输）；
- POST 30 口 + 校验 GET /api/session/current 聚合一致（30/30 无丢失）；
- SSE /api/stream 实时送达；
- 手工验收项的自动化部分：启动后 httpx 拉取页面 200、静态资源全本地可解析、
  第一方资源零外链（离线可开）；
- 非法与冲突输入负例（422/409）；
- 克数聚合（有称重路径）与会话轮转。

运行（eval 命令，cwd=仓库根）：
    .venv/Scripts/python.exe -m pytest tests/test_dashboard.py -q
结束由 tests/conftest.py 把 {module,date,cmd,metrics,thresholds,pass} 写入
chengshao/reports/dashboard_eval.json（本模块 DASH_METRICS 提供业务指标）。
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from chengshao.cs_dashboard.app import create_app

# 业务指标（conftest 终局汇总时读取；默认值保证未跑的用例不会伪装通过）
DASH_METRICS: dict = {
    "page_http_status": None,
    "static_assets_all_200": None,
    "first_party_external_refs": None,
    "bites_posted": 0,
    "bites_recorded": None,
    "aggregation_match": None,
    "outcomes": None,
    "sse_snapshot_ok": None,
    "sse_bite_delivered": None,
    "invalid_rejected_422": None,
    "conflicts_409": None,
    "grams_total_check": None,
}

OUTCOME_PLAN = {5: "retry", 17: "retry", 23: "rejected", 28: "aborted"}  # 其余 success


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server:
    """在随机端口起真实 uvicorn（独立线程、独立事件循环）。"""

    def __init__(self, db_path: Path) -> None:
        self.port = _free_port()
        self.app = create_app(db_path=db_path)
        config = uvicorn.Config(
            self.app, host="127.0.0.1", port=self.port,
            log_level="warning", access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "_Server":
        self.thread.start()
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base}/api/health", timeout=1.0).status_code == 200:
                    return self
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("uvicorn 20s 内未就绪")

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10.0)


@pytest.fixture()
def server(tmp_path: Path):
    with _Server(tmp_path / "care.db") as s:
        yield s


def _bite(i: int, base_ns: int, outcome: str | None = None,
          grams: tuple[float, float] | None = None) -> dict:
    ts_start = base_ns + i * 20_000_000_000
    return {
        "bite_id": i,
        "ts_start_ns": ts_start,
        "ts_end_ns": ts_start + 18_000_000_000,
        "outcome": outcome or OUTCOME_PLAN.get(i, "success"),
        "grams_before": None if grams is None else grams[0],
        "grams_after": None if grams is None else grams[1],
    }


# ---------------------------------------------------------------------------
# 1) 页面与静态资源：启动后 httpx 拉取 200；资源本地化（零外链 → 离线可开）
# ---------------------------------------------------------------------------

def test_page_served_200_and_offline_capable(server: _Server) -> None:
    r = httpx.get(f"{server.base}/", timeout=5.0)
    DASH_METRICS["page_http_status"] = r.status_code
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "澄勺" in r.text and "护理看板" in r.text

    # HTML 引用的全部本地静态资源必须可达
    refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', r.text)
    assert refs, "页面应引用本地静态资源"
    ok = True
    for ref in refs:
        ar = httpx.get(f"{server.base}{ref}", timeout=5.0)
        ok = ok and ar.status_code == 200 and len(ar.content) > 0
    DASH_METRICS["static_assets_all_200"] = ok
    assert ok, f"静态资源存在缺失: {refs}"

    # 第一方资源（页面/脚本/样式）零外链：任何 http(s) 引用都判失败（离线可开）
    first_party = ["/static/style.css", "/static/app.js"]
    external = 0
    for path in first_party:
        text = httpx.get(f"{server.base}{path}", timeout=5.0).text
        external += len(re.findall(r"https?://", text))
    DASH_METRICS["first_party_external_refs"] = external
    assert external == 0, "第一方静态资源不得引用外部网络（离线可开）"


# ---------------------------------------------------------------------------
# 2) 冻结契约主用例：30 口 POST + GET 聚合一致（§5.7）
# ---------------------------------------------------------------------------

def test_contract_30_bites_and_aggregation(server: _Server) -> None:
    # 30 口合成时间戳铺在真实时刻之前的 10 分钟窗内（每口 20s），
    # 保证结束会话的 ended_ns（真实当前时间）晚于最后一口 ts_end。
    base_ns = time.time_ns() - 600_000_000_000

    # 契约形状：POST /api/session/start {user_id} → {session_id}
    r = httpx.post(f"{server.base}/api/session/start",
                   json={"user_id": "elder-01"}, timeout=5.0)
    assert r.status_code == 200, r.text
    assert set(r.json().keys()) == {"session_id"}
    session_id = r.json()["session_id"]

    # 会话中：POST 30 口 → 全部 204
    for i in range(30):
        br = httpx.post(f"{server.base}/api/bite", json=_bite(i, base_ns), timeout=5.0)
        assert br.status_code == 204, (i, br.status_code, br.text)
    DASH_METRICS["bites_posted"] = 30

    # GET /api/session/current → MealSession 聚合一致
    cur = httpx.get(f"{server.base}/api/session/current", timeout=5.0)
    assert cur.status_code == 200
    session = cur.json()
    assert set(session.keys()) == {
        "session_id", "user_id", "started_ns", "ended_ns", "bites", "total_grams",
    }
    assert session["session_id"] == session_id
    assert session["user_id"] == "elder-01"
    assert session["ended_ns"] is None
    bites = session["bites"]
    DASH_METRICS["bites_recorded"] = len(bites)
    assert len(bites) == 30, f"30 口应全部落库，实际 {len(bites)}"
    assert [b["bite_id"] for b in bites] == list(range(30)), "bite_id 0..29 无丢失且保序"
    for i, b in enumerate(bites):
        expect = _bite(i, base_ns)
        assert b["ts_start_ns"] == expect["ts_start_ns"]
        assert b["ts_end_ns"] == expect["ts_end_ns"]
        assert b["outcome"] == expect["outcome"]
        assert b["grams_before"] is None and b["grams_after"] is None

    outcomes = {k: 0 for k in ("success", "retry", "rejected", "aborted")}
    for b in bites:
        outcomes[b["outcome"]] += 1
    expect_outcomes = {
        "success": 26, "retry": 2, "rejected": 1, "aborted": 1,
    }
    DASH_METRICS["outcomes"] = outcomes
    DASH_METRICS["aggregation_match"] = (
        outcomes == expect_outcomes and session["total_grams"] is None
    )
    assert outcomes == expect_outcomes
    assert session["total_grams"] is None, "无称重硬件时 total_grams 必须为 null"

    # GET /api/summary 聚合一致（追加端点）
    s = httpx.get(f"{server.base}/api/summary", timeout=5.0).json()
    assert s["session_id"] == session_id
    assert s["bite_count"] == 30
    assert s["outcomes"] == expect_outcomes
    assert s["total_grams"] is None
    assert s["duration_s"] >= 0

    # 结束会话：ended_ns 落定，时长口径 = 结束-开始
    er = httpx.post(f"{server.base}/api/session/end", timeout=5.0)
    assert er.status_code == 200
    ended = er.json()["session"]
    assert ended["ended_ns"] >= max(b["ts_end_ns"] for b in bites)
    s2 = httpx.get(f"{server.base}/api/summary", timeout=5.0).json()
    expect_dur = (ended["ended_ns"] - ended["started_ns"]) / 1e9
    assert abs(s2["duration_s"] - expect_dur) < 0.05

    # 会话轮转 + 克数聚合（有称重路径：Σ max(0, before-after)）
    r2 = httpx.post(f"{server.base}/api/session/start",
                    json={"user_id": "elder-02"}, timeout=5.0)
    assert r2.status_code == 200
    sid2 = r2.json()["session_id"]
    assert sid2 != session_id
    g_base = time.time_ns()
    grams_plan = [(250.0, 242.0), (242.0, 236.5)]  # 8.0g + 5.5g = 13.5g
    for i, g in enumerate(grams_plan):
        br = httpx.post(f"{server.base}/api/bite",
                        json=_bite(i, g_base, grams=g), timeout=5.0)
        assert br.status_code == 204
    cur2 = httpx.get(f"{server.base}/api/session/current", timeout=5.0).json()
    assert cur2["session_id"] == sid2, "current 应指向最近一餐"
    assert len(cur2["bites"]) == 2
    s3 = httpx.get(f"{server.base}/api/summary", timeout=5.0).json()
    DASH_METRICS["grams_total_check"] = abs(s3["total_grams"] - 13.5) < 1e-6
    assert DASH_METRICS["grams_total_check"]
    assert s3["bite_count"] == 2


# ---------------------------------------------------------------------------
# 3) SSE 实时流：连接即快照；另一线程 POST 单口，流内送达同一 bite
# ---------------------------------------------------------------------------

def _read_sse_event(lines) -> tuple[str, dict] | None:
    """从行迭代器解析下一个 SSE 事件，返回 (event, data)；流结束返回 None。"""
    event, data_lines = None, []
    for line in lines:
        if line == "":
            if event is not None:
                return event, json.loads("".join(data_lines) or "{}")
            continue
        if line.startswith(":"):
            continue  # 心跳注释
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    return None


def test_sse_stream_realtime(server: _Server) -> None:
    httpx.post(f"{server.base}/api/session/start",
               json={"user_id": "elder-sse"}, timeout=5.0)
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    with httpx.Client(timeout=timeout) as client:
        with client.stream("GET", f"{server.base}/api/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")

            lines = resp.iter_lines()  # 同一响应流只建一次迭代器（重用会 StreamConsumed）
            first = _read_sse_event(lines)
            assert first is not None and first[0] == "snapshot", "连接即推 snapshot"
            snap = first[1]
            DASH_METRICS["sse_snapshot_ok"] = (
                "summary" in snap and snap["summary"]["bite_count"] == 0
            )
            assert DASH_METRICS["sse_snapshot_ok"]

            # 流保持打开的同时，从另一线程写入单口（时间戳放过去，避免时序越界）
            base_ns = time.time_ns() - 60_000_000_000
            result: dict = {}

            def _post() -> None:
                rr = httpx.post(f"{server.base}/api/bite",
                                json=_bite(0, base_ns), timeout=5.0)
                result["status"] = rr.status_code

            poster = threading.Thread(target=_post)
            poster.start()
            deadline = time.monotonic() + 15.0
            delivered = None
            while delivered is None and time.monotonic() < deadline:
                evt = _read_sse_event(lines)
                if evt is not None and evt[0] == "bite":
                    delivered = evt[1]
            poster.join(timeout=5.0)
            assert result.get("status") == 204
            assert delivered is not None, "15s 内未在 SSE 流中收到 bite 事件"
            DASH_METRICS["sse_bite_delivered"] = (
                delivered["bite"]["bite_id"] == 0
                and delivered["summary"]["bite_count"] == 1
            )
            assert DASH_METRICS["sse_bite_delivered"]

    cur = httpx.get(f"{server.base}/api/session/current", timeout=5.0).json()
    assert len(cur["bites"]) == 1


# ---------------------------------------------------------------------------
# 4) 负例：契约校验 422；冲突 409（无会话 / 重复开餐 / 重复 bite_id / 重复收尾）
# ---------------------------------------------------------------------------

def test_validation_and_conflicts(server: _Server) -> None:
    base = server.base
    base_ns = time.time_ns() - 120_000_000_000  # 合成时间放过去，避免越界到未来

    # 无会话写入口 → 409
    r = httpx.post(f"{base}/api/bite", json=_bite(0, base_ns), timeout=5.0)
    assert r.status_code == 409

    # user_id 为空 → 契约校验 422
    assert httpx.post(f"{base}/api/session/start", json={"user_id": ""},
                      timeout=5.0).status_code == 422

    assert httpx.post(f"{base}/api/session/start", json={"user_id": "u1"},
                      timeout=5.0).status_code == 200

    # 进行中重复开餐 → 409
    assert httpx.post(f"{base}/api/session/start", json={"user_id": "u2"},
                      timeout=5.0).status_code == 409

    # 非法 outcome / 负 bite_id / 缺字段 → 422（契约 BiteRecord 校验）
    bad = _bite(0, base_ns)
    bad["outcome"] = "slurp"
    assert httpx.post(f"{base}/api/bite", json=bad, timeout=5.0).status_code == 422
    bad = _bite(-1, base_ns)
    assert httpx.post(f"{base}/api/bite", json=bad, timeout=5.0).status_code == 422
    bad = _bite(1, base_ns)
    del bad["ts_end_ns"]
    assert httpx.post(f"{base}/api/bite", json=bad, timeout=5.0).status_code == 422
    # ts_end < ts_start → 422
    bad = _bite(1, base_ns)
    bad["ts_end_ns"] = bad["ts_start_ns"] - 1
    assert httpx.post(f"{base}/api/bite", json=bad, timeout=5.0).status_code == 422

    # 合法写入后重复 bite_id → 409（防双计）
    good = _bite(0, base_ns)
    assert httpx.post(f"{base}/api/bite", json=good, timeout=5.0).status_code == 204
    assert httpx.post(f"{base}/api/bite", json=good, timeout=5.0).status_code == 409

    cur = httpx.get(f"{base}/api/session/current", timeout=5.0).json()
    assert len(cur["bites"]) == 1, "重复口不得落库两次"

    # 结束后：再写口 → 409；重复收尾 → 409
    assert httpx.post(f"{base}/api/session/end", timeout=5.0).status_code == 200
    assert httpx.post(f"{base}/api/bite", json=_bite(9, base_ns),
                      timeout=5.0).status_code == 409
    assert httpx.post(f"{base}/api/session/end", timeout=5.0).status_code == 409

    DASH_METRICS["invalid_rejected_422"] = True
    DASH_METRICS["conflicts_409"] = True


# ---------------------------------------------------------------------------
# 5) 进程内 Store 直查：事件流镜像可回放
# ---------------------------------------------------------------------------

def test_event_mirror_replay(server: _Server) -> None:
    base_ns = time.time_ns() - 60_000_000_000
    httpx.post(f"{server.base}/api/session/start", json={"user_id": "u"},
               timeout=5.0)
    httpx.post(f"{server.base}/api/bite", json=_bite(0, base_ns), timeout=5.0)
    httpx.post(f"{server.base}/api/session/end", timeout=5.0)
    events = httpx.get(f"{server.base}/api/events?limit=10", timeout=5.0).json()
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "session_ended", "事件镜像应为倒序（最新在前）"
    assert set(kinds) == {"session_started", "bite", "session_ended"}
    bite_evt = next(e for e in events if e["kind"] == "bite")
    assert bite_evt["payload"]["bite"]["bite_id"] == 0
