"""确定性 REST API：出卷 / 提交作答 / 查画像 / 查计划 / 复习打卡。

薄胶水层：所有逻辑都在内核模块里，这里只做 HTTP 编解码与会话存储。
"""
from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent_shell import MockLLM, attribute_error
from .diagnosis import aggregate_to_clusters, diagnose
from .itembank import ItemBank
from .kpgraph import KPGraph
from .paper import generate_paper, select_next_item
from .pedagogy import StrategyLibrary
from .route import build_plan
from .scheduler import ReviewLog, schedule
from .types import Misconception, Response, to_dict


class BlueprintIn(BaseModel):
    blueprint: dict[str, int]
    seed: int = 42
    title: str = "诊断卷"
    difficulty_target: float = 0.5


class ResponseIn(BaseModel):
    item_id: str
    correct: bool
    learner_answer: str | None = None


class SubmitIn(BaseModel):
    responses: list[ResponseIn]


class ReviewIn(BaseModel):
    rating: int
    days_since_last: int = 0


def create_app(
    bank: ItemBank,
    graph: KPGraph,
    strategies: StrategyLibrary,
    misconceptions: list[Misconception] | None = None,
) -> FastAPI:
    app = FastAPI(title="xuexing-agent")
    store: dict[str, dict] = {}
    misconceptions = misconceptions or []
    attempt_counts: dict[str, dict[str, int]] = {}

    @app.post("/papers/diagnostic")
    def make_paper(body: BlueprintIn):
        try:
            paper = generate_paper(
                bank, graph, body.blueprint, body.seed, body.title, body.difficulty_target
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        return to_dict(paper)

    @app.post("/learners/{learner_id}/responses")
    def submit(learner_id: str, body: SubmitIn):
        responses = [
            Response(item_id=r.item_id, correct=r.correct, learner_answer=r.learner_answer)
            for r in body.responses
        ]
        profile = diagnose(responses, bank, graph, learner_id=learner_id)
        entry = store.setdefault(learner_id, {"responses": [], "history": []})
        entry["responses"].extend(body.responses)
        entry["profile"] = profile
        clusters = aggregate_to_clusters(profile, graph)
        return {"learner_id": learner_id, "mastery": profile.mastery, "clusters": clusters}

    @app.get("/learners/{learner_id}/profile")
    def get_profile(learner_id: str):
        entry = store.get(learner_id)
        if not entry or "profile" not in entry:
            raise HTTPException(404, "learner not found")
        p = entry["profile"]
        return {
            "learner_id": learner_id,
            "mastery": p.mastery,
            "evidence": p.evidence,
            "updated_at": p.updated_at,
            "confidence": {k: round(p.confidence(k), 4) for k in p.mastery},
        }

    @app.get("/learners/{learner_id}/plan")
    def get_plan(learner_id: str):
        entry = store.get(learner_id)
        if not entry or "profile" not in entry:
            raise HTTPException(404, "learner not found")
        plan = build_plan(entry["profile"], bank, graph, strategies, date.today())
        return to_dict(plan)

    @app.get("/learners/{learner_id}/next_item")
    def next_item(learner_id: str, scope: str = "", per_kp_cap: int = 3):
        entry = store.get(learner_id)
        if not entry or "profile" not in entry:
            raise HTTPException(404, "learner not found")
        scope_set = set(scope.split(",")) if scope else {kp.id for kp in graph.kps()}
        counts = attempt_counts.setdefault(learner_id, {})
        administered = set(entry.setdefault("administered", []))
        item_id = select_next_item(bank, entry["profile"], administered, scope_set, counts, per_kp_cap)
        if item_id is None:
            return {"item_id": None, "reason": "exhausted"}
        entry["administered"].append(item_id)
        primary = bank.get(item_id).kps[0]
        counts[primary] = counts.get(primary, 0) + 1
        return {"item_id": item_id}

    @app.post("/learners/{learner_id}/reviews")
    def review(learner_id: str, body: ReviewIn):
        if body.rating not in (0, 1, 2, 3):
            raise HTTPException(400, "rating must be 0-3")
        entry = store.setdefault(learner_id, {"responses": [], "history": []})
        entry["history"].append(body.rating)
        e = schedule(learner_id, [ReviewLog(rating=body.rating, days_since_last=body.days_since_last)], date.today())
        return to_dict(e)

    @app.post("/attribute")
    def attribute(item_id: str, learner_answer: str):
        item = bank.get(item_id)
        if item is None:
            raise HTTPException(404, "item not found")
        mc = attribute_error(item, learner_answer, misconceptions, MockLLM())
        return {"misconception_id": mc}

    return app
