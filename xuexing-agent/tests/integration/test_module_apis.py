"""集成测试：server 新模块 API × 真实 grade7 知识库（BACKLOG「server 暴露新模块
API」要求的集成测试：/trace /blueprint /grade /recommend 全链路）。

闭式值全部现算核实（2026-09-29，data/ 当前版本）：
- /trace [m7_010 对@0, m7_011 错@3, m7_013 对@10]：3 快照；末快照
  kp_rational_add=0.084203（2 证据：对+错，遗忘衰减后净负）、kp_rational_mul=0.90099；
- /recommend attach：kp_rational_add 步骤推荐 = ["m7_010","m7_011","m7_012","m7_115"]
  （mc_sign_neg 针对题 Tier1 在前，与 recommend 契约闭式一致），策略 s_worked_example；
- /itembank/v2/validate：grade7 129 题全部 source=original、无 verification 键
  （null 等价）→ errors []、verified 0（诚实未验证，不伪造）；
- /coverage/standard：grade7 37 KP × 28 课标条目 → 归属缺口 0、覆盖 12/28
  （清单为 7-9 年级第四学段全集，7 年级子库不含几何变换/函数/统计部分）。
"""
import json
import os

import pytest
from fastapi.testclient import TestClient

from xuexing.server import create_app


@pytest.fixture(scope="module")
def client(bank, graph, strategies, misconceptions):
    return TestClient(create_app(bank, graph, strategies, misconceptions))


@pytest.fixture(scope="module")
def grade7_items(root):
    with open(os.path.join(root, "data", "items", "math_grade7_items.json"),
              encoding="utf-8") as f:
        return json.load(f)["items"]


@pytest.fixture(scope="module")
def grade7_kps(root):
    with open(os.path.join(root, "data", "knowledge", "math_grade7.json"),
              encoding="utf-8") as f:
        return json.load(f)["knowledge_points"]


@pytest.fixture(scope="module")
def curriculum_topics(root):
    with open(os.path.join(root, "data", "curriculum", "math_standard_2022_topics.json"),
              encoding="utf-8") as f:
        return json.load(f)


# ---------- /trace × 真实题库 ----------

def test_trace_real_bank_saves_profile(client):
    r = client.post("/trace", json={
        "learner_id": "kt-int-1",
        "events": [{"item_id": "m7_010", "correct": True, "day": 0.0},
                   {"item_id": "m7_011", "correct": False, "day": 3.0},
                   {"item_id": "m7_013", "correct": True, "day": 10.0}]})
    assert r.status_code == 200
    out = r.json()
    assert out["profile_saved"] is True
    assert len(out["snapshots"]) == 3
    final = out["snapshots"][-1]
    assert final["mastery"]["kp_rational_add"] == 0.084203  # 闭式（对+错，衰减后净负）
    assert final["mastery"]["kp_rational_mul"] == 0.90099
    assert final["evidence"]["kp_rational_add"] == 2
    assert final["evidence"]["kp_rational_mul"] == 1
    assert sum(final["evidence"].values()) == 3  # 其余 KP 无证据（全键 0）
    p = client.get("/learners/kt-int-1/profile").json()
    assert p["mastery"] == final["mastery"]
    assert p["evidence"] == final["evidence"]


# ---------- /grade × 真实题目 ----------

def test_grade_real_fill_items(client):
    # m7_010 标答 "2"：数值等值与符号敏感
    assert client.post("/grade", json={"item_id": "m7_010",
                                       "learner_answer": "2"}).json()["correct"] is True
    assert client.post("/grade", json={"item_id": "m7_010",
                                       "learner_answer": "-2"}).json()["correct"] is False
    # m7_011 标答 "-5"：尾部标点剥离（N3）后按值判
    assert client.post("/grade", json={"item_id": "m7_011",
                                       "learner_answer": "-5。"}).json()["correct"] is True
    assert client.post("/grade", json={"item_id": "m7_011",
                                       "learner_answer": "(-5)"}).json()["correct"] is False
    # m7_007 标答 "5"：绝对值题，符号错判错
    assert client.post("/grade", json={"item_id": "m7_007",
                                       "learner_answer": "5"}).json()["correct"] is True
    assert client.post("/grade", json={"item_id": "m7_007",
                                       "learner_answer": "-5"}).json()["correct"] is False


def test_grade_real_choice_items(client):
    # m7_009 标答 "C"（选项 "C. ±4"）：标签优先，全文亦可
    for ans in ("C", "C. ±4"):
        assert client.post("/grade", json={"item_id": "m7_009",
                                           "learner_answer": ans}).json()["correct"] is True
    assert client.post("/grade", json={"item_id": "m7_009",
                                       "learner_answer": "A"}).json()["correct"] is False


def test_grade_batch_real(client):
    r = client.post("/grade", json={"answers": [
        {"item_id": "m7_010", "learner_answer": "2"},
        {"item_id": "m7_011", "learner_answer": "-5"},
        {"item_id": "m7_013", "learner_answer": "6"}]})
    assert r.status_code == 200
    out = r.json()
    assert out["n"] == 3
    assert [x["correct"] for x in out["results"]] == [True, True, False]  # m7_013 标答 -6


# ---------- /blueprint × 真实图谱 → 组卷 ----------

def test_blueprint_real_feeds_paper(client):
    r = client.post("/blueprint", json={
        "targets": ["kp_rational_add", "kp_eq_solve"], "budget": 3})
    assert r.status_code == 200
    out = r.json()
    assert sum(out["counts"].values()) == 3
    assert set(out["counts"]) == {"kp_rational_add", "kp_eq_solve"}
    assert out["dimension_totals"] and set(out["dimension_totals"]) == {"记忆", "理解", "应用"}
    paper = client.post("/papers/diagnostic",
                        json={"blueprint": out["counts"], "seed": 42}).json()
    assert len(paper["item_ids"]) == 3


# ---------- /recommend × 真实画像（trace → recommend attach 全链路） ----------

def test_recommend_attach_real_pipeline(client):
    rec = client.post("/recommend", json={"learner_id": "kt-int-1", "attach": True})
    assert rec.status_code == 200
    plan = rec.json()["plan"]
    assert plan["learner_id"] == "kt-int-1"
    steps = {s["kp_id"]: s for s in plan["steps"]}
    assert "kp_rational_add" in steps  # trace 判弱（0.084203 < 0.65）
    step = steps["kp_rational_add"]
    assert step["strategy_id"] == "s_worked_example"
    # 闭式：mc_sign_neg 针对题（难度 0.2，id 升序）在前，巩固题在后
    assert step["recommended_item_ids"] == ["m7_010", "m7_011", "m7_012", "m7_115"]
    # kp_rational_mul 掌握 0.90099 ≥ 0.65：无步骤，只进复习日程
    assert "kp_rational_mul" not in steps
    assert any(r["kp_id"] == "kp_rational_mul" for r in plan["reviews"])


def test_recommend_profile_mode_real(client):
    r = client.post("/recommend", json={"learner_id": "kt-int-1", "limit": 2})
    assert r.status_code == 200 and r.json()["mode"] == "profile"
    recs = r.json()["recommendations"]
    assert recs[0]["kp_id"] == "kp_rational_add"  # 最弱（0.084203）优先
    assert recs[0]["item_ids"] == ["m7_010", "m7_011"]  # limit 截断
    assert all(len(x["item_ids"]) <= 2 for x in recs)


# ---------- /itembank/v2/validate × 真实题库（诚实披露检查） ----------

def test_item_v2_real_bank_honest_disclosure(client, grade7_items):
    r = client.post("/itembank/v2/validate", json={"items": grade7_items})
    assert r.status_code == 200
    out = r.json()
    assert out["valid"] is True and out["errors"] == []
    assert out["counts"] == {"original": 129, "adapted": 0, "llm_generated": 0}
    assert out["total"] == 129 and out["verified"] == 0  # 无伪造验证记录


# ---------- /coverage/standard × 真实课标清单 ----------

def test_coverage_real_grade7(client, grade7_kps, curriculum_topics):
    r = client.post("/coverage/standard",
                    json={"kp_dicts": grade7_kps, "topics": curriculum_topics})
    assert r.status_code == 200
    out = r.json()
    assert out["unmatched_kp_ids"] == []  # 37 条 standard_ref 全部归属
    assert out["coverage_rate"] == pytest.approx(12 / 28)
    assert out["is_complete"] is False  # 清单为 7-9 年级全集，7 年级子库只覆盖 12 条
    assert len(out["uncovered_topic_ids"]) == 16
    assert "g_circle" in out["uncovered_topic_ids"] and "fn_linear" in out["uncovered_topic_ids"]
