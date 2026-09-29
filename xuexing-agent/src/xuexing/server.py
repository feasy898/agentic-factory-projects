"""确定性 REST API：出卷 / 提交作答 / 查画像 / 查计划 / 复习打卡，以及新模块
API（/trace /blueprint /grade /recommend /itembank/v2/validate
/coverage/standard）与机构多租户（X-Org-Id 头 + /orgs）。

薄胶水层：所有逻辑都在内核模块里，这里只做 HTTP 编解码与会话存储。
领域校验失败（内核 ValueError 族）映射 400，资源不存在映射 404，
请求体形态违规由 pydantic 映射 422；端点不实现任何领域算法。

机构多租户（specs/drafts/multitenant.spec.md §3.6-3.7）：全部有状态端点接受
可选请求头 X-Org-Id（缺省/空串/空白归并 DEFAULT_ORG_ID，见
xuexing.multitenant.resolve_org）；store 与 attempt 计数按 (org, learner)
分域——同一 learner_id 在不同机构下完全隔离；不带该头的请求行为与单租户
时代逐字节一致。无状态端点忽略该头。GET /orgs 只读枚举机构命名空间。

导入约定：绝对导入（from xuexing.xxx import ...）——与重生成注入装载约定一致
（见 specs/drafts/server.spec.md §2），本文件可被
run_contract.py --impl-dir <dir> --modules server 装载。
"""
from datetime import date
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from xuexing.agent_shell import MockLLM, attribute_error
from xuexing.blueprint import build_blueprint
from xuexing.diagnosis import aggregate_to_clusters, diagnose
from xuexing.grading import grade_to_response
from xuexing.itembank import ItemBank
from xuexing.itembank_v2 import source_counts, validate_bank_v2, verification_stats
from xuexing.kpgraph import KPGraph
from xuexing.kt import KTEvent, trace, to_profile
from xuexing.multitenant import AttemptCounter, OrgStore, resolve_org
from xuexing.paper import generate_paper, select_next_item
from xuexing.pedagogy import StrategyLibrary
from xuexing.recommend import (
    attach_recommendations,
    recommend_for_kp,
    recommend_for_profile,
)
from xuexing.route import build_plan
from xuexing.scheduler import ReviewLog, schedule
from xuexing.standard_coverage import check_coverage_dicts
from xuexing.types import Misconception, Response, to_dict


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


# ---- 新模块 API 请求体（specs/drafts/server.spec.md §3）----

class KTEventIn(BaseModel):
    item_id: str
    correct: bool
    day: float


class TraceIn(BaseModel):
    events: list[KTEventIn]
    learner_id: str = ""
    prior: float = 0.5
    half_life_days: float = 7.0


class BlueprintReq(BaseModel):
    targets: list[str]
    budget: int
    ratios: dict[str, float] | None = None


class GradeAnswerIn(BaseModel):
    item_id: str
    learner_answer: str | None = None


class GradeIn(BaseModel):
    item_id: str | None = None
    learner_answer: str | None = None
    answers: list[GradeAnswerIn] | None = None


class RecommendIn(BaseModel):
    learner_id: str = ""
    kp_id: str = ""
    mastery_threshold: float = 0.65
    limit: int | None = None
    attach: bool = False


class ItemsV2In(BaseModel):
    # 元素刻意为任意 JSON 值：itembank_v2 校验器是全函数，
    # "非 dict → item is not a dict" 的语义要能经 HTTP 观察。
    items: list[Any]


class CoverageIn(BaseModel):
    kp_dicts: list[dict]
    topics: dict


def create_app(
    bank: ItemBank,
    graph: KPGraph,
    strategies: StrategyLibrary,
    misconceptions: list[Misconception] | None = None,
) -> FastAPI:
    app = FastAPI(title="xuexing-agent")
    store = OrgStore()
    misconceptions = misconceptions or []
    attempt_counts = AttemptCounter()

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
    def submit(learner_id: str, body: SubmitIn,
               x_org_id: str | None = Header(default=None, alias="X-Org-Id")):
        org = resolve_org(x_org_id)
        responses = [
            Response(item_id=r.item_id, correct=r.correct, learner_answer=r.learner_answer)
            for r in body.responses
        ]
        profile = diagnose(responses, bank, graph, learner_id=learner_id)
        entry = store.entry(org, learner_id)
        entry["responses"].extend(body.responses)
        entry["profile"] = profile
        clusters = aggregate_to_clusters(profile, graph)
        return {"learner_id": learner_id, "mastery": profile.mastery, "clusters": clusters}

    @app.get("/learners/{learner_id}/profile")
    def get_profile(learner_id: str,
                    x_org_id: str | None = Header(default=None, alias="X-Org-Id")):
        org = resolve_org(x_org_id)
        entry = store.get(org, learner_id)
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
    def get_plan(learner_id: str,
                 x_org_id: str | None = Header(default=None, alias="X-Org-Id")):
        org = resolve_org(x_org_id)
        entry = store.get(org, learner_id)
        if not entry or "profile" not in entry:
            raise HTTPException(404, "learner not found")
        plan = build_plan(entry["profile"], bank, graph, strategies, date.today())
        return to_dict(plan)

    @app.get("/learners/{learner_id}/next_item")
    def next_item(learner_id: str, scope: str = "", per_kp_cap: int = 3,
                  x_org_id: str | None = Header(default=None, alias="X-Org-Id")):
        org = resolve_org(x_org_id)
        entry = store.get(org, learner_id)
        if not entry or "profile" not in entry:
            raise HTTPException(404, "learner not found")
        scope_set = set(scope.split(",")) if scope else {kp.id for kp in graph.kps()}
        counts = attempt_counts.counts(org, learner_id)
        administered = entry.setdefault("administered", [])
        item_id = select_next_item(bank, entry["profile"], administered, scope_set, counts, per_kp_cap)
        if item_id is None:
            return {"item_id": None, "reason": "exhausted"}
        entry["administered"].append(item_id)
        primary = bank.get(item_id).kps[0]
        attempt_counts.bump(org, learner_id, primary)
        return {"item_id": item_id}

    @app.post("/learners/{learner_id}/reviews")
    def review(learner_id: str, body: ReviewIn,
               x_org_id: str | None = Header(default=None, alias="X-Org-Id")):
        if body.rating not in (0, 1, 2, 3):
            raise HTTPException(400, "rating must be 0-3")
        org = resolve_org(x_org_id)
        entry = store.entry(org, learner_id)
        entry["history"].append(body.rating)
        e = schedule(learner_id, [ReviewLog(rating=body.rating, days_since_last=body.days_since_last)], date.today())
        return to_dict(e)

    @app.get("/orgs")
    def list_orgs():
        # 只读枚举（multitenant 规格 §3.7 / I9）：org 升序、learner 升序
        return {"orgs": [
            {"org_id": org, "learner_ids": store.learner_ids(org)}
            for org in store.org_ids()
        ]}

    @app.post("/attribute")
    def attribute(item_id: str, learner_answer: str):
        item = bank.get(item_id)
        if item is None:
            raise HTTPException(404, "item not found")
        mc = attribute_error(item, learner_answer, misconceptions, MockLLM())
        return {"misconception_id": mc}

    # ---- 新模块 API（specs/drafts/server.spec.md §3.1-§3.6）----

    @app.post("/trace")
    def kt_trace(body: TraceIn,
                 x_org_id: str | None = Header(default=None, alias="X-Org-Id")):
        events = [KTEvent(item_id=e.item_id, correct=e.correct, day=e.day)
                  for e in body.events]
        try:
            snapshots = trace(events, bank, graph,
                              prior=body.prior, half_life_days=body.half_life_days)
        except ValueError as e:
            raise HTTPException(400, str(e))
        saved = False
        if body.learner_id:
            if not snapshots:  # 无快照可存
                raise HTTPException(400, "cannot save profile: trace has no snapshots")
            store.set_profile(resolve_org(x_org_id), body.learner_id,
                              to_profile(snapshots[-1], body.learner_id))
            saved = True
        return {
            "learner_id": body.learner_id or None,
            "profile_saved": saved,
            "snapshots": [
                {"day": s.day, "item_id": s.item_id, "correct": s.correct,
                 "mastery": s.mastery, "evidence": s.evidence}
                for s in snapshots
            ],
        }

    @app.post("/blueprint")
    def make_blueprint(body: BlueprintReq):
        try:
            bp = build_blueprint(body.targets, body.budget, graph, body.ratios)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {
            "targets": bp.targets,
            "budget": bp.budget,
            "ratios": bp.ratios,
            "allocation": bp.allocation,
            "dimension_totals": bp.dimension_totals,
            "counts": bp.counts(),
            "per_dimension": [
                {"dimension": dim, "counts": sub, "difficulty_target": dt}
                for dim, sub, dt in bp.per_dimension()
            ],
        }

    @app.post("/grade")
    def grade_answers(body: GradeIn):
        if body.answers is not None:  # 批量优先（I5）；原子：先验存在性再判分（I4）
            items = []
            for a in body.answers:
                item = bank.get(a.item_id)
                if item is None:
                    raise HTTPException(404, f"item not found: {a.item_id}")
                items.append(item)
            results = []
            for item, a in zip(items, body.answers):
                try:
                    resp = grade_to_response(item, a.learner_answer)
                except ValueError as e:
                    raise HTTPException(400, str(e))
                results.append(to_dict(resp))
            return {"mode": "batch", "n": len(results), "results": results}
        if body.item_id is None:
            raise HTTPException(400, "provide item_id or answers")
        item = bank.get(body.item_id)
        if item is None:
            raise HTTPException(404, f"item not found: {body.item_id}")
        try:
            resp = grade_to_response(item, body.learner_answer)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return to_dict(resp)

    @app.post("/recommend")
    def recommend(body: RecommendIn,
                  x_org_id: str | None = Header(default=None, alias="X-Org-Id")):
        try:
            if body.kp_id:  # kp 模式优先（I5）
                ids = recommend_for_kp(body.kp_id, bank, misconceptions, body.limit)
                return {"mode": "kp", "kp_id": body.kp_id, "item_ids": ids}
            if body.learner_id:
                entry = store.get(resolve_org(x_org_id), body.learner_id)
                if not entry or "profile" not in entry:
                    raise HTTPException(404, "learner not found")
                profile = entry["profile"]
                if body.attach:
                    plan = build_plan(profile, bank, graph, strategies, date.today())
                    attached = attach_recommendations(plan, bank, misconceptions, body.limit)
                    return {"mode": "plan", "plan": to_dict(attached)}
                recs = recommend_for_profile(profile, bank, misconceptions,
                                             mastery_threshold=body.mastery_threshold,
                                             limit=body.limit)
                return {"mode": "profile", "recommendations": to_dict(recs)}
        except ValueError as e:
            raise HTTPException(400, str(e))
        raise HTTPException(400, "provide kp_id or learner_id")

    @app.post("/itembank/v2/validate")
    def item_v2_validate(body: ItemsV2In):
        # 校验器是全函数：任意输入不抛异常，恒 200（I2/I7 只读）
        errors = validate_bank_v2(body.items)
        total, verified = verification_stats(body.items)
        return {
            "valid": not errors,
            "errors": errors,
            "counts": source_counts(body.items),
            "total": total,
            "verified": verified,
        }

    @app.post("/coverage/standard")
    def coverage_standard(body: CoverageIn):
        try:
            report = check_coverage_dicts(body.kp_dicts, body.topics)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {
            "coverage_rate": report.coverage_rate,
            "is_complete": report.is_complete(),
            "uncovered_topic_ids": list(report.uncovered_topic_ids),
            "unmatched_kp_ids": list(report.unmatched_kp_ids),
            "matched_kp_ids": list(report.matched_kp_ids),
            "covered_topic_ids": list(report.covered_topic_ids),
            "matches": [
                {"kp_id": m.kp_id, "topic_ids": list(m.topic_ids)}
                for m in report.matches
            ],
        }

    return app
