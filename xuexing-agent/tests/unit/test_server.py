import pytest
from fastapi.testclient import TestClient

from xuexing.server import create_app


@pytest.fixture(scope="module")
def client(bank, graph, strategies, misconceptions):
    app = create_app(bank, graph, strategies, misconceptions)
    return TestClient(app)


def test_make_paper_roundtrip(client):
    r = client.post("/papers/diagnostic", json={
        "blueprint": {"kp_rational_add": 2, "kp_eq_solve": 1}, "seed": 11})
    assert r.status_code == 200
    paper = r.json()
    assert len(paper["item_ids"]) == 3
    assert set(paper["blueprint"]) == {"kp_rational_add", "kp_eq_solve"}


def test_make_paper_bad_blueprint_400(client):
    r = client.post("/papers/diagnostic", json={"blueprint": {"kp_ghost": 1}})
    assert r.status_code == 400


def test_profile_404_before_any_response(client):
    assert client.get("/learners/nobody/profile").status_code == 404


def test_full_session_flow(client):
    lid = "stu-1"
    r = client.post(f"/learners/{lid}/responses", json={
        "responses": [
            {"item_id": "m7_010", "correct": False, "learner_answer": "8"},
            {"item_id": "m7_011", "correct": False, "learner_answer": "5"},
            {"item_id": "m7_013", "correct": True},
        ]})
    assert r.status_code == 200
    body = r.json()
    assert body["mastery"]["kp_rational_add"] < 0.5
    assert "一元一次方程" in body["clusters"]

    p = client.get(f"/learners/{lid}/profile").json()
    assert p["evidence"]["kp_rational_add"] == 2
    assert "confidence" in p

    plan = client.get(f"/learners/{lid}/plan").json()
    assert len(plan["steps"]) > 0 and "reviews" in plan

    nxt = client.get(f"/learners/{lid}/next_item", params={"scope": "kp_rational_add,kp_rational_mul"}).json()
    assert nxt["item_id"] is not None


def test_next_item_exhausts(client):
    lid = "stu-cap"
    client.post(f"/learners/{lid}/responses", json={"responses": [{"item_id": "m7_010", "correct": True}]})
    got = []
    for _ in range(10):
        r = client.get(f"/learners/{lid}/next_item", params={"scope": "kp_absvalue", "per_kp_cap": 2}).json()
        if r["item_id"] is None:
            break
        assert r["item_id"] not in got
        got.append(r["item_id"])
    assert len(got) <= 2


def test_attribute_endpoint(client):
    r = client.post("/attribute", params={"item_id": "m7_007", "learner_answer": "-5"})
    assert r.status_code == 200
    assert r.json()["misconception_id"] == "mc_abs_drop"


def test_review_rating_validation(client):
    assert client.post("/learners/stu-1/reviews", json={"rating": 9}).status_code == 400
    ok = client.post("/learners/stu-1/reviews", json={"rating": 2})
    assert ok.status_code == 200 and "due" in ok.json()
