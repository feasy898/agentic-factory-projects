"""SQLite 持久层测试: 迁移只新增 / 状态机矩阵 / 候选 / 用量 / 并发。"""

from __future__ import annotations

import json
import threading

import pytest

from src.db import DB, STATUSES, TRANSITIONS, IllegalTransition


def test_migrate_only_adds(db):
    assert db.schema_version() == 1
    assert db.migrate() == 0  # 幂等, 不重复应用


def test_ingest_and_upsert(db, valid_card):
    tid = db.ingest_task("S03", "evidence_product", "first_frame_i2v", valid_card, template="t1")
    assert tid >= 1
    # 幂等重 ingest: pending 时更新
    db.ingest_task("S03", "evidence_product", "t2v", valid_card, template="t1")
    t = db.get_task("S03")
    assert t["lane"] == "t2v" and t["status"] == "pending" and t["template"] == "t1"
    # 非 pending 时不覆盖状态(也不覆盖卡面)
    db.set_status("S03", "generating")
    db.ingest_task("S03", "evidence_product", "ken_burns", valid_card, template="t1")
    t2 = db.get_task("S03")
    assert t2["status"] == "generating" and t2["lane"] == "t2v"  # 卡面未覆盖, 保持原值


def test_transition_matrix(db, valid_card):
    db.ingest_task("S03", "evidence_product", "first_frame_i2v", valid_card)
    legal = {(o, n) for o, outs in TRANSITIONS.items() for n in outs}
    illegal = {(o, n) for o in STATUSES for n in STATUSES} - legal

    # 用一个辅助函数把任务摆到任意状态(绕过状态机, 模拟外部置位)
    def force(status):
        db.force_status("S03", status, "test setup")

    for old, new in sorted(legal):
        force(old)
        db.set_status("S03", new)  # 不应抛
        assert db.get_task("S03")["status"] == new

    for old, new in sorted(illegal):
        force(old)
        with pytest.raises(IllegalTransition):
            db.set_status("S03", new)


def test_set_status_unknown_task(db):
    with pytest.raises(KeyError):
        db.set_status("NOPE", "generating")


def test_candidates_lifecycle(db, valid_card):
    db.ingest_task("S03", "evidence_product", "first_frame_i2v", valid_card)
    cid = db.add_candidate("S03", "workdir/candidates/a.mp4", verdict="pending")
    db.update_candidate(cid, gate_json={"G1": {"passed": True}}, overall_score=0.8, verdict="pass")
    cands = db.get_candidates("S03")
    assert len(cands) == 1 and cands[0]["verdict"] == "pass"
    assert cands[0]["gate_json"]["G1"]["passed"] is True

    db.update_candidate(cid, selected=True)
    sel = db.selected_candidate("S03")
    assert sel and sel["id"] == cid and sel["selected"] is True

    db.clear_candidates("S03")
    assert db.get_candidates("S03") == []


def test_api_usage_and_events(db):
    db.log_api_usage("vlm", "api", True)
    db.log_api_usage("vlm", "api", False)
    db.log_api_usage("vlm", "local", True)
    assert db.api_usage_count("vlm", route="api") == 2
    assert db.api_usage_count("vlm") == 3
    s = db.api_usage_summary()["vlm"]
    assert s == {"api_ok": 1, "api_fail": 1, "local_ok": 1, "local_fail": 0}

    db.log_event("warn", "hello 中文事件")
    evs = db.recent_events(1)
    assert evs[0]["msg"] == "hello 中文事件" and evs[0]["level"] == "warn"


def test_update_task_whitelist(db, valid_card):
    db.ingest_task("S03", "evidence_product", "first_frame_i2v", valid_card)
    db.update_task("S03", attempts=2, seed=42, hint_json={"round": 1})
    t = db.get_task("S03")
    assert t["attempts"] == 2 and t["seed"] == 42
    assert json.loads(t["hint_json"]) == {"round": 1}
    with pytest.raises(ValueError):
        db.update_task("S03", status="composed")  # 状态必须走状态机


def test_concurrent_writers(tmp_path, valid_card):
    """两个连接并发写: WAL + busy_timeout 下不丢数据。"""
    path = tmp_path / "conc.sqlite3"
    db1 = DB(path)
    db1.migrate()
    db2 = DB(path)
    db1.ingest_task("S03", "evidence_product", "first_frame_i2v", valid_card)

    def worker(dbx, tag, n):
        for i in range(n):
            dbx.log_event("info", f"{tag}-{i}")

    threads = [threading.Thread(target=worker, args=(db1, "a", 30)),
               threading.Thread(target=worker, args=(db2, "b", 30)),
               threading.Thread(target=worker, args=(db2, "c", 30))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(db1.recent_events(limit=1000)) == 90
    db1.close()
    db2.close()
