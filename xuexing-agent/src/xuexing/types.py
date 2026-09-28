"""学情诊断内核 — 共享数据类型（冻结契约的 schema 部分）。

所有类型 JSON 可序列化：字段只能是 dict/list/str/float/int/bool/None。
重生成实现只允许 import 本模块 + 标准库。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class KnowledgePoint:
    """知识点。prereqs 列出必须先掌握的知识点 id。standard_ref 指向课标条目描述。"""

    id: str
    name: str
    subject: str
    grade: int
    cluster: str
    description: str = ""
    standard_ref: str = ""
    prereqs: list[str] = field(default_factory=list)


@dataclass
class Item:
    """题目。kps[0] 是主知识点（诊断与选题以它为准），其余为次要知识点。"""

    id: str
    item_type: str  # "choice" | "fill" | "solve"
    stem: str
    answer: str
    kps: list[str]
    difficulty: float  # [0,1]，0 最易
    solution: str = ""
    options: list[str] = field(default_factory=list)  # choice 必填，长度>=2
    discrimination: float = 0.6  # [0,1]
    guess: Optional[float] = None  # None 则由 item_type 默认值决定
    misconceptions: list[str] = field(default_factory=list)

    def effective_guess(self) -> float:
        if self.guess is not None:
            return self.guess
        return {"choice": 0.25, "fill": 0.10, "solve": 0.02}.get(self.item_type, 0.1)


@dataclass
class Response:
    """一次作答。correct 是判分结果（客观题由系统判，主观题由教师/批改端给）。"""

    item_id: str
    correct: bool
    learner_answer: Optional[str] = None
    response_ms: Optional[int] = None


@dataclass
class Profile:
    """学情画像：每个知识点一个 [0,1] 掌握度 + 证据数 + 置信度。"""

    learner_id: str
    mastery: dict[str, float]
    evidence: dict[str, int]
    updated_at: str = ""

    def confidence(self, kp_id: str) -> float:
        n = self.evidence.get(kp_id, 0)
        return n / (n + 3.0)


@dataclass
class Strategy:
    """教学策略（含证据出处与适用条件，条件字段全部可选）。"""

    id: str
    name: str
    description: str
    priority: int = 0
    evidence: str = ""
    effect_size: Optional[float] = None
    mastery_lt: Optional[float] = None
    mastery_gte: Optional[float] = None
    grade_max: Optional[int] = None
    grade_min: Optional[int] = None


@dataclass
class PlanStep:
    kp_id: str
    strategy_id: str
    rationale: str = ""
    target_mastery: float = 0.85


@dataclass
class ReviewEntry:
    kp_id: str
    due: str  # ISO 日期
    interval_days: int
    ease: float


@dataclass
class LearningPlan:
    learner_id: str
    steps: list[PlanStep]
    reviews: list[ReviewEntry]
    created_at: str = ""


@dataclass
class Paper:
    paper_id: str
    title: str
    blueprint: dict[str, int]
    item_ids: list[str]
    sections: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Misconception:
    """常见错误模式。signature 是该误解下的典型错误答案（用于归因匹配）。"""

    id: str
    kp_id: str
    description: str
    hint: str
    signature: list[str] = field(default_factory=list)


# ---------- 序列化 helpers（重生成实现可直接复用） ----------

def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
