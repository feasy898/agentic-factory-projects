"""M14 任务队列验收（任务 T20 自验收口径，全离线零 GPU/零真模型）。

覆盖：
- ep×lang 粒度作业与共享（ep 级）任务去重；enqueue 幂等；
- 四态机（待跑/进行/完成/失败）与步骤图静态校验（未知步/环/scope 单调）；
- **断点续跑核心**：杀掉执行到中间步骤的 resume 进程后重启 —— 完成步跳过、
  陈旧 running 收回、断点步重跑、后续步继续（规划 §4 M14 eval 线）；
- 依赖未满足拒绝执行（上游失败 → 下游不产生子进程、note 记原因）；
- 失败修复后 resume 收敛；产物被清 → 该步降级重跑；
- metrics.db 逐步记账 + :func:`pipeline.queue.ledger_from_metrics_db` 水合为
  真实 M15 ``CallLedger`` 并直连喂给 ``m15_metrics.cost.compute``（对接线）；
- CLI 三件套 enqueue/status/resume（真子进程，退出码即判定）+ run 等价性。

执行器全部走 ``--graph`` 微型桩图（python -c 脚本：计数器/产物/模式文件），
不触碰真管线模块 —— 真模块链路的执行正确性由各模块自身 eval 与 e2e 覆盖，
本文件只验收队列编排语义本身。
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pipeline.m15_metrics._common import CallLedger
from pipeline.queue import (
    SERVICE_DEPS,
    Queue,
    QueueError,
    QueueUsageError,
    default_graph,
    graph_from_file,
    ledger_from_metrics_db,
    service_deps,
    subgraph,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EP = "epq"

#: 桩步骤执行体：计数器自增 → 按模式文件动作（fail=exit 3 / sleep=停 8s）→ 写产物
_STUB = (
    "import sys, pathlib, time\n"
    "counter, artifact, modefile = sys.argv[1], sys.argv[2], sys.argv[3]\n"
    "cf = pathlib.Path(counter)\n"
    "n = (int(cf.read_text()) if cf.exists() else 0) + 1\n"
    "cf.write_text(str(n))\n"
    "mode = pathlib.Path(modefile).read_text(encoding='utf-8').strip()\n"
    "if mode == 'fail':\n"
    "    sys.exit(3)\n"
    "if mode == 'sleep':\n"
    "    time.sleep(8)\n"
    "ap = pathlib.Path(artifact)\n"
    "ap.parent.mkdir(parents=True, exist_ok=True)\n"
    "ap.write_text('ok %d' % n, encoding='utf-8')\n"
)


def _write_modes(tmp: Path, modes: dict[str, str]) -> None:
    for sid, mode in modes.items():
        (tmp / f"m_{sid}.mode").write_text(mode, encoding="utf-8")


def _chain_graph(tmp: Path, ep: str = EP, n: int = 5) -> Path:
    """5 步线性桩图：s1=ep 级共享，s2..s5 逐语种；模式经文件注入（可运行中翻转）。"""
    _write_modes(tmp, {f"s{i}": "ok" for i in range(1, n + 1)})
    steps = []
    ws = tmp / "jobs" / ep
    for i in range(1, n + 1):
        artifact = (str(ws / "art" / f"s{i}.txt") if i == 1
                    else str(ws / "art" / f"s{i}.") + "{lang}.txt")
        steps.append({
            "id": f"s{i}",
            "cmd": ["{python}", "-c", _STUB, str(tmp / f"c{i}.cnt"),
                    artifact, str(tmp / f"m_s{i}.mode")],
            "deps": [] if i == 1 else [f"s{i-1}"],
            "artifact": artifact,
            "services": ("stub@9999",) if i == 3 else (),
            "scope": "ep" if i == 1 else "lang",
        })
    path = tmp / "graph.json"
    path.write_text(json.dumps({"steps": steps}), encoding="utf-8")
    return path


def _queue(tmp: Path, graph: Path) -> Queue:
    return Queue(tmp / "jobs", db_path=tmp / "jobs.db",
                 metrics_db_path=tmp / "metrics.db",
                 graph=graph_from_file(graph))


def _counter(tmp: Path, i: int) -> int:
    p = tmp / f"c{i}.cnt"
    return int(p.read_text()) if p.exists() else 0


def _task_state(q: Queue, module: str, lang: str = "en") -> str:
    row = q._task(EP, "" if module == "s1" else lang, module)
    assert row is not None, f"任务行缺失: {module}"
    return row["state"]


def _cli(tmp: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.cli", *args],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300)
    if check:
        assert proc.returncode == 0, (
            f"CLI {' '.join(args[:2])}... exit={proc.returncode}\n"
            f"stdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}")
    return proc


# ---------------------------------------------------------------------------
# 步骤图与服务依赖声明（单一来源静态断言）
# ---------------------------------------------------------------------------

def test_default_graph_structure_and_service_deps():
    g = default_graph()
    assert set(g) == {"m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8",
                      "m9", "m10", "m11", "m15"}
    order = [s.id for s in subgraph(g, "m15")]
    assert order.index("m4") < order.index("m2") < order.index("m5") < \
        order.index("m6") < order.index("m8") < order.index("m7") < \
        order.index("m9") < order.index("m10") < order.index("m15")
    # 服务依赖声明：与各 StepSpec.services 同源一致（M13 复用的导入面）
    assert SERVICE_DEPS == {
        "m4": ("asr-align@9001",), "m6": ("mt@9004",),
        "m7": ("tts@9002",), "m10": ("lip@9003",),
    }
    assert service_deps(subgraph(g, "m15")) == SERVICE_DEPS
    for sid, spec in g.items():
        assert spec.services == SERVICE_DEPS.get(sid, ())
    # 共享步只依赖共享步；逐语种步产物模板含 {lang}
    assert all(g[d].scope == "ep" for d in g["m5"].deps)
    assert "{lang}" in g["m8"].artifact and "{ep}" in g["m9"].artifact
    assert g["m1"].scope == "ep" and g["m1"].params_required == ("input",)


def test_graph_validation_rejects_bad_graphs(tmp_path):
    ok = json.loads(_chain_graph(tmp_path, n=3).read_text(encoding="utf-8"))
    base = ok["steps"]
    # ① 未知依赖
    bad = json.loads(json.dumps(ok))
    bad["steps"][1]["deps"] = ["ghost"]
    p1 = tmp_path / "g1.json"
    p1.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(QueueUsageError):
        graph_from_file(p1)
    # ② 循环依赖
    bad = json.loads(json.dumps(ok))
    bad["steps"][0]["deps"] = ["s2"]
    p2 = tmp_path / "g2.json"
    p2.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(QueueUsageError):
        graph_from_file(p2)
    # ③ 共享步依赖逐语种步（scope 单调）
    bad = json.loads(json.dumps(ok))
    bad["steps"][0]["scope"] = "ep"
    bad["steps"][0]["deps"] = ["s2"]
    bad["steps"][1]["scope"] = "lang"
    p3 = tmp_path / "g3.json"
    p3.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(QueueUsageError):
        graph_from_file(p3)
    assert base  # 原图未动


def test_subgraph_closure_for_reuse(tmp_path):
    # M13 消费形态预演：单句重生成链（到 m9）与导出链（到 m11）的闭包
    g = default_graph()
    m9 = [s.id for s in subgraph(g, "m9")]
    assert "m10" not in m9 and "m15" not in m9
    assert {"m6", "m8", "m7", "m9", "m11"} <= set(m9)
    m11 = [s.id for s in subgraph(g, "m11")]
    assert "m9" not in m11 and "m8" not in m11 and "m6" in m11


# ---------------------------------------------------------------------------
# 入队 / 状态 / 四态
# ---------------------------------------------------------------------------

def test_enqueue_creates_jobs_and_shared_task_once(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    ids = q.enqueue(EP, ["en", "es"], "s5")
    assert len(ids) == 2 and ids[0] != ids[1]
    again = q.enqueue(EP, ["en", "es"], "s5")
    assert again == ids  # 幂等入队：复用既有作业行
    snap = q.status()
    jobs = {j["lang"]: j for j in snap["jobs"]}
    assert set(jobs) == {"en", "es"}
    assert all(j["state"] == "pending" for j in jobs.values())
    en_tasks = jobs["en"]["tasks"]
    shared = [t for t in en_tasks if t["lang"] == ""]
    assert [t["module"] for t in shared] == ["s1"]  # ep 级任务全局仅一行
    assert len([t for t in en_tasks if t["lang"] == "en"]) == 4
    # 依赖与产物已渲染（deps JSON、绝对产物路径含语种占位渲染）
    t3 = next(t for t in en_tasks if t["module"] == "s3")
    assert json.loads(t3["deps"]) == ["s2"]
    assert t3["artifact"].endswith("s3.en.txt")
    with pytest.raises(QueueUsageError):
        q.enqueue(EP, ["en"], "no-such-step")


def test_enqueue_requires_step_params(tmp_path):
    graph_path = _chain_graph(tmp_path, n=1)
    raw = json.loads(graph_path.read_text(encoding="utf-8"))
    raw["steps"][0]["params_required"] = ["input"]
    graph_path.write_text(json.dumps(raw), encoding="utf-8")
    q = _queue(tmp_path, graph_path)
    with pytest.raises(QueueUsageError):
        q.enqueue(EP, ["en"], "s1")
    assert q.status()["jobs"] == []  # 校验先行：未落任何作业
    ids = q.enqueue(EP, ["en"], "s1", params={"input": "clip.mp4"})
    assert len(ids) == 1


# ---------------------------------------------------------------------------
# 正常链路执行 + metrics 记账
# ---------------------------------------------------------------------------

def test_resume_runs_chain_and_records_metrics(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (jid,) = q.enqueue(EP, ["en"], "s5")
    out = q.resume(job_ids=[jid])
    assert out["ok"] is True and out["jobs"][0]["state"] == "done"
    assert all(_counter(tmp_path, i) == 1 for i in range(1, 6))
    assert all(_task_state(q, f"s{i}") == "done" for i in range(1, 6))
    job = q.status(job_id=jid)["jobs"][0]
    assert job["state"] == "done"
    # metrics.db：每步一次尝试一行，退出码/墙钟/声明服务齐全
    conn = sqlite3.connect(str(tmp_path / "metrics.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM step_metrics WHERE ep=? ORDER BY id", (EP,)).fetchall()
    conn.close()
    assert len(rows) == 5
    assert rows[0]["module"] == "s1" and rows[0]["lang"] == ""  # 共享步记账行
    assert all(r["lang"] == "en" for r in rows[1:])
    assert all(r["exit_code"] == 0 and r["wall_s"] > 0 for r in rows)
    assert json.loads(rows[2]["services"]) == ["stub@9999"]
    assert all(r["attempt"] == 1 for r in rows)


def test_completed_steps_skipped_on_second_resume(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (jid,) = q.enqueue(EP, ["en"], "s5")
    assert q.resume(job_ids=[jid])["ok"] is True
    out = q.resume(job_ids=[jid])
    assert out["ok"] is True
    assert all(_counter(tmp_path, i) == 1 for i in range(1, 6))  # 零重跑
    marks = [t for j in out["jobs"] for t in j["tasks"]]
    assert len(marks) == 5 and all(t.get("skipped") for t in marks)


def test_ep_scope_step_runs_once_across_langs(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    ids = q.enqueue(EP, ["en", "es"], "s5")
    out = q.resume(job_ids=ids)
    assert out["ok"] is True
    assert _counter(tmp_path, 1) == 1          # 共享步只跑一次
    assert all(_counter(tmp_path, i) == 2 for i in range(2, 6))  # 每语种一次
    ws = tmp_path / "jobs" / EP / "art"
    assert (ws / "s1.txt").is_file()
    assert (ws / "s2.en.txt").is_file() and (ws / "s2.es.txt").is_file()
    assert all(j["state"] == "done" for j in q.status()["jobs"])


# ---------------------------------------------------------------------------
# 断点续跑核心：杀中间步骤 → 重启从断点继续
# ---------------------------------------------------------------------------

def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=30)
    else:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


def test_kill_midstep_then_resume_from_breakpoint(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (jid,) = q.enqueue(EP, ["en"], "s5")
    (tmp_path / "m_s3.mode").write_text("sleep", encoding="utf-8")
    # 起 resume 子进程，跑到 s3（sleep 8s）中途整树杀掉
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-m", "pipeline.cli", "resume", "--job", str(jid),
         "--jobs-dir", str(tmp_path / "jobs"), "--db", str(tmp_path / "jobs.db"),
         "--metrics-db", str(tmp_path / "metrics.db"), "--graph", str(graph)],
        cwd=str(REPO_ROOT), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    deadline = time.time() + 30
    while time.time() < deadline and _counter(tmp_path, 3) == 0:
        assert proc.poll() is None, "resume 进程提前退出（未到 s3）"
        time.sleep(0.05)
    time.sleep(0.6)  # 确保 kill 落在 s3 执行窗口内
    _kill_tree(proc)
    proc.wait(timeout=30)
    assert _counter(tmp_path, 1) == 1 and _counter(tmp_path, 2) == 1
    mid = q.status(job_id=jid)["jobs"][0]
    assert mid["state"] in ("running", "failed")  # 中断态（未收口）
    # 重启：新进程/新 run_id → 陈旧 running 收回，从断点继续
    (tmp_path / "m_s3.mode").write_text("ok", encoding="utf-8")
    out = Queue(tmp_path / "jobs", db_path=tmp_path / "jobs.db",
                metrics_db_path=tmp_path / "metrics.db",
                graph=graph_from_file(graph)).resume(job_ids=[jid])
    assert out["ok"] is True, out
    assert out["reclaimed"] >= 1  # s3 的陈旧 running 被收回
    assert _counter(tmp_path, 1) == 1 and _counter(tmp_path, 2) == 1  # 完成步跳过
    assert _counter(tmp_path, 3) == 2  # 断点步重跑
    assert _counter(tmp_path, 4) == 1 and _counter(tmp_path, 5) == 1  # 后续继续
    assert _task_state(q, "s3") == "done"
    assert q.status(job_id=jid)["jobs"][0]["state"] == "done"
    # 记账：s3 两次尝试都在册 —— 被杀尝试 spawn 前已插行，回填缺失
    # → exit_code=-1 恒久在册（未完成尝试 ≠ 不存在，如实记账）
    conn = sqlite3.connect(str(tmp_path / "metrics.db"))
    codes = [r[0] for r in conn.execute(
        "SELECT exit_code FROM step_metrics WHERE ep=? AND module='s3' "
        "ORDER BY id", (EP,)).fetchall()]
    conn.close()
    assert codes == [-1, 0]


def test_stale_running_reclaimed_without_kill(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (jid,) = q.enqueue(EP, ["en"], "s5")
    assert q.resume(job_ids=[jid])["ok"] is True
    # 人为制造陈旧 running（模拟外部进程死亡遗留）
    conn = sqlite3.connect(str(tmp_path / "jobs.db"))
    conn.execute(
        "UPDATE tasks SET state='running', run_id='deadbeef' "
        "WHERE ep=? AND lang='en' AND module='s3'", (EP,))
    conn.commit()
    conn.close()
    os.remove(tmp_path / "jobs" / EP / "art" / "s3.en.txt")
    out = q.resume(job_ids=[jid])
    assert out["ok"] is True and out["reclaimed"] == 1
    assert _counter(tmp_path, 3) == 2 and _counter(tmp_path, 4) == 1


# ---------------------------------------------------------------------------
# 依赖未满足拒绝执行 / 失败修复后续跑 / 产物缺失重跑
# ---------------------------------------------------------------------------

def test_dep_failed_refuses_downstream(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (jid,) = q.enqueue(EP, ["en"], "s5")
    (tmp_path / "m_s3.mode").write_text("fail", encoding="utf-8")
    out = q.resume(job_ids=[jid])
    assert out["ok"] is False
    tasks = {t["module"]: t for t in out["jobs"][0]["tasks"]}
    assert tasks["s3"]["state"] == "failed" and tasks["s3"]["exit_code"] == 3
    assert tasks["s4"]["state"] == "failed" and tasks["s4"].get("refused")
    assert "s3(failed)" in tasks["s4"]["reason"]
    assert tasks["s5"]["state"] == "failed" and tasks["s5"].get("refused")
    assert _counter(tmp_path, 4) == 0 and _counter(tmp_path, 5) == 0  # 无子进程
    assert q.status(job_id=jid)["jobs"][0]["state"] == "failed"
    rc = _cli(tmp_path, "resume", "--job", str(jid),
              "--jobs-dir", str(tmp_path / "jobs"), "--db", str(tmp_path / "jobs.db"),
              "--metrics-db", str(tmp_path / "metrics.db"),
              "--graph", str(graph)).returncode
    assert rc == 1  # CLI 退出码即判定


def test_fixed_failure_converges_on_resume(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (jid,) = q.enqueue(EP, ["en"], "s5")
    (tmp_path / "m_s3.mode").write_text("fail", encoding="utf-8")
    assert q.resume(job_ids=[jid])["ok"] is False
    (tmp_path / "m_s3.mode").write_text("ok", encoding="utf-8")  # 修复
    out = q.resume(job_ids=[jid])
    assert out["ok"] is True
    assert [_counter(tmp_path, i) for i in range(1, 6)] == [1, 1, 2, 1, 1]
    assert q.status(job_id=jid)["jobs"][0]["state"] == "done"
    # s3 两次尝试记账：一败一成
    conn = sqlite3.connect(str(tmp_path / "metrics.db"))
    codes = [r[0] for r in conn.execute(
        "SELECT exit_code FROM step_metrics WHERE ep=? AND module='s3' "
        "ORDER BY id", (EP,)).fetchall()]
    conn.close()
    assert codes == [3, 0]


def test_missing_artifact_demotes_done_step_to_rerun(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (jid,) = q.enqueue(EP, ["en"], "s5")
    assert q.resume(job_ids=[jid])["ok"] is True
    os.remove(tmp_path / "jobs" / EP / "art" / "s2.en.txt")
    out = q.resume(job_ids=[jid])
    assert out["ok"] is True
    assert _counter(tmp_path, 2) == 2            # 产物被清 → 该步重跑
    assert _counter(tmp_path, 1) == 1            # 前序完成步不受影响
    assert _counter(tmp_path, 3) == 1            # 下游 done 且产物在位 → 跳过


# ---------------------------------------------------------------------------
# metrics.db → M15 CallLedger 对接
# ---------------------------------------------------------------------------

def test_ledger_hydration_feeds_m15_cost(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (jid,) = q.enqueue(EP, ["en"], "s5")
    assert q.resume(job_ids=[jid])["ok"] is True
    led = ledger_from_metrics_db(tmp_path / "metrics.db", ep=EP, lang="en")
    assert isinstance(led, CallLedger)
    assert "s1" in led.stages                     # ep 级共享步无语种后缀
    assert "s2[en]" in led.stages                 # 逐语种步带语种后缀
    assert led.wall_total == round(sum(led.stages.values()), 3)
    summary = led.calls_summary()["cpu"]          # s1/s2/s4/s5 无服务声明 → cpu
    assert summary["n"] == 4 and summary["n_fail"] == 0
    svc = led.calls_summary()["stub@9999"]        # s3 声明了外部服务
    assert svc["n"] == 1
    # 直连 M15 成本指标：水合账本即 ``cost.compute`` 可消费的真实入参
    from pipeline.m15_metrics import cost

    res = cost.compute(tmp_path, "en", EP, led, output_duration_s=60.0)
    assert res["status"] == "ok"
    # cost.compute 内部按 2 位小数取整（cost.py 口径），水合值同源
    assert res["value"] == round(led.wall_total, 2)  # 60s 成片 = 1 分钟
    assert res["detail"]["stages_s"] == dict(led.stages)
    assert res["detail"]["calls_by_service"]["cpu"]["n"] == 4


def test_ledger_filters_by_ep_and_counts_failures(tmp_path):
    graph = _chain_graph(tmp_path)
    q = _queue(tmp_path, graph)
    (a,) = q.enqueue("epa", ["en"], "s5")
    (b,) = q.enqueue("epb", ["en"], "s5")
    (tmp_path / "m_s2.mode").write_text("fail", encoding="utf-8")
    q.resume(job_ids=[a])                         # epa: s2 失败 → s3.. 拒绝
    (tmp_path / "m_s2.mode").write_text("ok", encoding="utf-8")
    q.resume(job_ids=[b])                         # epb: 全成
    led_a = ledger_from_metrics_db(tmp_path / "metrics.db", ep="epa", lang="en")
    led_b = ledger_from_metrics_db(tmp_path / "metrics.db", ep="epb", lang="en")
    assert set(led_a.stages) <= {"s1", "s2[en]", "s3[en]", "s4[en]", "s5[en]"}
    assert led_a.calls_summary()["cpu"]["n_fail"] >= 1
    assert led_b.calls_summary()["cpu"]["n"] == 4
    assert led_b.calls_summary()["cpu"]["n_fail"] == 0
    with pytest.raises(QueueError):
        ledger_from_metrics_db(tmp_path / "nope.db")


# ---------------------------------------------------------------------------
# CLI 三件套（真子进程，退出码即判定）
# ---------------------------------------------------------------------------

def test_cli_enqueue_status_resume_roundtrip(tmp_path):
    graph = _chain_graph(tmp_path)
    common = ["--jobs-dir", str(tmp_path / "jobs"), "--db",
              str(tmp_path / "jobs.db"), "--metrics-db",
              str(tmp_path / "metrics.db"), "--graph", str(graph)]
    p = _cli(tmp_path, "enqueue", EP, "--langs", "en,es", "--to", "s5", *common,
             check=True)
    jid = int(p.stdout.strip().split("#", 1)[1].split(",")[0].strip())
    st = json.loads(_cli(tmp_path, "status", "--json", *common,
                         check=True).stdout)
    assert [j["state"] for j in st["jobs"]] == ["pending", "pending"]
    _cli(tmp_path, "resume", "--job", str(jid), *common, check=True)
    st = json.loads(_cli(tmp_path, "status", "--json", "--job", str(jid),
                         *common, check=True).stdout)
    assert st["jobs"][0]["state"] == "done"
    assert all(t["state"] == "done" for t in st["jobs"][0]["tasks"])
    p = _cli(tmp_path, "resume", "--job", str(jid), *common, check=True)
    assert "skip" in p.stdout  # 二次 resume 全部跳过
    # 未知步骤：入队前拒绝（exit 2，不落库）
    rc = _cli(tmp_path, "enqueue", EP, "--langs", "en", "--to", "ghost",
              *common).returncode
    assert rc == 2
    rc = _cli(tmp_path, "resume").returncode  # 无过滤条件 → 用法错误
    assert rc == 2


def test_cli_run_is_enqueue_plus_resume(tmp_path):
    graph = _chain_graph(tmp_path)
    _cli(tmp_path, "run", EP, "--langs", "en", "--to", "s5",
         "--jobs-dir", str(tmp_path / "jobs"), "--db", str(tmp_path / "jobs.db"),
         "--metrics-db", str(tmp_path / "metrics.db"), "--graph", str(graph),
         check=True)
    st = json.loads(_cli(tmp_path, "status", "--json",
                         "--jobs-dir", str(tmp_path / "jobs"),
                         "--db", str(tmp_path / "jobs.db"),
                         "--metrics-db", str(tmp_path / "metrics.db"),
                         "--graph", str(graph), check=True).stdout)
    assert st["jobs"][0]["state"] == "done"
    assert _counter(tmp_path, 5) == 1
