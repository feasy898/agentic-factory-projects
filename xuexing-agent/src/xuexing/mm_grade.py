"""mm_grade —— VLM 辅助判分（BACKLOG P3「mm_grade VLM 辅助判分」）的确定性内核。

行为契约（specs/drafts/mm_grade.spec.md，本文件为参考实现）：

- 场景：主观解答题（solve）的手写作答照片。管线：注入的 VLM 客户端
  （mm_client.MMClient 满足其表面）恰好一次转写学生解答步骤（schema 冻结）->
  确定性分步给分规则（参考解切分、双向包含匹配、贪心配对，规则全部冻结）->
  产出 GradeSuggestion（分步给分建议 + 复核原因）。
- 人机协同复核闭环：干净建议（reasons 为空）走 suggest_response 产出 Response；
  需复核建议（低置信/缺答案/步骤不齐/自相矛盾）走 confirm_review 由人给出终审，
  两条路互斥——每条建议恰好一条路可走，Response 可追溯。
- 判分诚实性：VLM prompt 只含题面（stem）与转写指令，绝不含 answer/solution——
  防止 VLM 把参考答案抄进学生步骤；给分完全在本地按冻结规则计算，VLM 不判分。
- 宁可交人，不猜：低置信步骤不计分只标记；步骤不齐 partial_match；缺最终答案
  final_answer_missing；步骤全对但答案错 contradiction——任一命中即 needs_review。
- 模块间零 import：client 与 answer_grader（grading.grade 满足表面）都是注入的
  鸭子参数，一致性由契约测试在测试内 import 对方模块跨模块锁定。

全模块纯函数：无 IO、无随机、无时钟、不读环境，同输入同输出（出网只发生在注入的
client.vision 恰好一次调用上）。
"""
# 注意：不用 `from __future__ import annotations`——重生成注入装载（XX_IMPL_DIR）
# 按文件位置 exec 模块，字符串化注解曾崩 dataclasses KW_ONLY 探测（见 tts_reader/
# mm_ingest/asr_answer 同款注释）。
import json
import math
import re
from dataclasses import dataclass
from typing import Optional

from xuexing.types import Response

__all__ = [
    "GradeError",
    "GRADE_VERSION",
    "MIN_CONFIDENCE",
    "IMAGE_FORMATS",
    "REASON_LOW_CONFIDENCE",
    "REASON_FINAL_ANSWER_MISSING",
    "REASON_PARTIAL_MATCH",
    "REASON_CONTRADICTION",
    "REVIEW_REASONS",
    "StepScore",
    "GradeSuggestion",
    "solution_steps",
    "match_key",
    "steps_match",
    "build_grade_prompt",
    "parse_transcription",
    "grade_solution",
    "suggest_response",
    "confirm_review",
]


class GradeError(ValueError):
    """mm_grade 模块所有校验失败的异常类型（ValueError 直接子类）。"""


# ---- 冻结常量（specs/drafts/mm_grade.spec.md §3）----

GRADE_VERSION = "1"

MIN_CONFIDENCE = 0.9  # 步骤级置信度门；confidence < 门限的步骤不计分只标记进复核

# 与 mm_client.IMAGE_MIME 键集相等（跨模块锁定）；大小写敏感
IMAGE_FORMATS = ("png", "jpg", "jpeg", "webp", "gif")

REASON_LOW_CONFIDENCE = "low_confidence"              # 有步骤置信度低于门限
REASON_FINAL_ANSWER_MISSING = "final_answer_missing"  # 转写未发现最终答案
REASON_PARTIAL_MATCH = "partial_match"                # 建议得分 < 满分（步骤不齐）
REASON_CONTRADICTION = "contradiction"                # 步骤全对但最终答案判错

# 复核原因词表（值与顺序冻结；suggestion.reasons 严格按此顺序、无重复）
REVIEW_REASONS = (
    REASON_LOW_CONFIDENCE,
    REASON_FINAL_ANSWER_MISSING,
    REASON_PARTIAL_MATCH,
    REASON_CONTRADICTION,
)

# 合法题型：本模块只管主观解答题（choice/fill 由 grading 确定性直判，不进 VLM）
_SOLVE_ONLY = "solve"

# 参考解步骤切分的行首序号标记（冻结）：可选全/半角开括号 + 1..3 位（ASCII 数字或
# 中文数字）+ 恰一个分隔符（、.．:：)））+ 紧随空白。已知边界（冻结接受）：行首
# 以「12.5」这类小数开头的正文会被误剥——按非目标处理，参考解不应这样书写。
_STEP_MARKER_RE = re.compile(r"^[（(]?[0-9一二三四五六七八九十]{1,3}[、.．:：)）]\s*")
_WHITESPACE_RE = re.compile(r"\s+")

_REQUIRED_STEP_KEYS = ("text", "confidence")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------- 参考解切分（规则冻结） ----------

def solution_steps(solution) -> list:
    """参考解文本 -> 步骤列表（本地确定性切分，判分侧唯一步骤来源）。

    冻结规则：按行切分（splitlines，容忍 \\r\\n）-> 逐行 strip -> 剥一个行首序号
    标记（_STEP_MARKER_RE，如 "(1) "/"2. "/"（一）"）-> 再 strip -> 丢空行。
    非 str -> GradeError；无步骤（空/全空白）-> []（由调用方守卫拒绝）。
    """
    if not isinstance(solution, str):
        raise GradeError(f"solution must be str, got {type(solution).__name__}")
    steps = []
    for line in solution.splitlines():
        line = _STEP_MARKER_RE.sub("", line.strip()).strip()
        if line:
            steps.append(line)
    return steps


# ---------- 匹配积木（规则冻结） ----------

def match_key(text) -> str:
    """匹配键：全角折叠（grading N1 同闭式）-> 删除全部空白 -> 小写化。

    手写转写的空白是纯噪声（「修 x 米」与「修x米」同一内容），步骤比较删空白；
    与 grading N2 不同（数值答案的空白有语义，那里折叠为单空格）。不做尾部标点
    剥离（双向包含已吸收标点差异）。
    """
    if not isinstance(text, str):
        raise GradeError(f"match_key expects str, got {type(text).__name__}")
    folded = []
    for ch in text:
        cp = ord(ch)
        if 0xFF01 <= cp <= 0xFF5E:
            folded.append(chr(cp - 0xFEE0))
        elif cp == 0x3000:
            folded.append(" ")
        else:
            folded.append(ch)
    return _WHITESPACE_RE.sub("", "".join(folded)).strip().lower()


def steps_match(ref_text, student_text) -> bool:
    """步骤匹配（冻结）：双向包含——键相等、或参考键 ⊆ 学生键、或学生键 ⊆ 参考键。

    任一侧键为空（空白步骤）-> False（空白步骤永不匹配）。非 str -> GradeError。
    """
    key_ref = match_key(ref_text)
    key_student = match_key(student_text)
    if not key_ref or not key_student:
        return False
    return key_ref == key_student or key_ref in key_student or key_student in key_ref


# ---------- 题目表面守卫（V6） ----------

def _require_item_surface(item):
    """solve 专用题目表面校验 -> (item_id, stem, answer, 参考步骤列表)。

    校验顺序冻结：id 非空 str -> item_type == "solve"（本模块只管主观题）->
    stem 非空 str -> answer 非空 str -> solution 为 str 且切出 >=1 步。
    任一失败抛 GradeError（在零出网守卫段内被调用）。
    """
    iid = getattr(item, "id", None)
    if not isinstance(iid, str) or not iid.strip():
        raise GradeError("item.id must be a non-blank str")
    item_type = getattr(item, "item_type", None)
    if item_type != _SOLVE_ONLY:
        raise GradeError(
            f"item {iid!r}: mm_grade only grades solve items, got {item_type!r}")
    stem = getattr(item, "stem", None)
    if not isinstance(stem, str) or not stem.strip():
        raise GradeError(f"item {iid!r} stem must be a non-blank str")
    answer = getattr(item, "answer", None)
    if not isinstance(answer, str) or not answer.strip():
        raise GradeError(f"item {iid!r} answer must be a non-blank str")
    solution = getattr(item, "solution", None)
    if not isinstance(solution, str):
        raise GradeError(
            f"item {iid!r} solution must be str, got {type(solution).__name__}")
    steps = solution_steps(solution)
    if not steps:
        raise GradeError(f"item {iid!r} solution yields no steps to score")
    return iid, stem, answer, steps


# ---------- prompt（冻结文本，判分侧卫生：绝不含 answer/solution） ----------

def _render_grade_prompt(stem: str) -> str:
    lines = [
        "你是阅卷助手。下面是一道主观解答题的题面，请从学生手写作答照片中逐行转写学生的解答过程。",
        "只输出一个 JSON 对象，不要输出任何其他文字。",
        '输出 JSON schema（冻结）：{"steps": [{"text": 学生某一步书写内容的原样转写, "confidence": 0 到 1 的数字}], "final_answer": 学生最终答案字符串或 null}',
        "规则：",
        "1. 只转写学生实际书写的内容，按书写顺序逐行转写；不补全、不改写、不自己计算。",
        "2. text 是该步原样转写；confidence 是你对该步转写的置信度，取 0 到 1。",
        "3. 学生写了最终答案则原样转写为 final_answer；没有写输出 null。",
        "题面：",
        stem,
    ]
    return "\n".join(lines)


def build_grade_prompt(item) -> str:
    """solve 题 -> 确定性 VLM 转写提示词（只含题面，绝不含 answer/solution）。

    先跑与 grade_solution 相同的题目表面守卫（V6），非法题目 -> GradeError。
    """
    _iid, stem, _answer, _steps = _require_item_surface(item)
    return _render_grade_prompt(stem)


# ---------- 转写解析（schema 冻结） ----------

def parse_transcription(text) -> dict:
    """VLM 回复文本 -> {"steps": [{"text": str, "confidence": float}…],
    "final_answer": str|None}。

    文本先 strip；取首个 "{" 到最后一个 "}" 的切片做 JSON 解析（前后闲话容忍，
    与 mm_ingest.parse_transcript 同策略）；顶层必须 dict 且含 `steps` list。
    每条步骤必须 dict 且 `text`（str）/`confidence`（[0,1] 有限数字拒 bool，
    int 规整 float）两键必填，未知键忽略；空白 text 合法（评分侧永不匹配）。
    `final_answer` 可选：缺席/null/空白 -> None；非 str 非 null -> GradeError。
    任何违例 -> GradeError。
    """
    if not isinstance(text, str):
        raise GradeError(f"transcription text must be str, got {type(text).__name__}")
    stripped = text.strip()
    if not stripped:
        raise GradeError("transcription is empty")
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise GradeError("transcription contains no json object")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise GradeError(f"transcription is not valid json: {e}") from e
    if not isinstance(parsed, dict):
        raise GradeError("transcription json must be an object")
    steps_raw = parsed.get("steps")
    if not isinstance(steps_raw, list):
        raise GradeError("transcription 'steps' must be a list")
    steps = []
    for i, entry in enumerate(steps_raw):
        if not isinstance(entry, dict):
            raise GradeError(f"transcription step {i} must be an object")
        for key in _REQUIRED_STEP_KEYS:
            if key not in entry:
                raise GradeError(f"transcription step {i} missing key {key!r}")
        step_text = entry["text"]
        if not isinstance(step_text, str):
            raise GradeError(
                f"transcription step {i} text must be str, got {type(step_text).__name__}")
        confidence = entry["confidence"]
        if not _is_number(confidence) or not math.isfinite(confidence) \
                or not 0.0 <= confidence <= 1.0:
            raise GradeError(
                f"transcription step {i} confidence must be a number in [0, 1], "
                f"got {confidence!r}")
        steps.append({"text": step_text, "confidence": float(confidence)})
    final = parsed.get("final_answer")  # 缺席 -> None（schema 可选键）
    if final is not None:
        if not isinstance(final, str):
            raise GradeError(
                f"transcription 'final_answer' must be str or null, "
                f"got {type(final).__name__}")
        if not final.strip():
            final = None
    return {"steps": steps, "final_answer": final}


# ---------- 数据形状 ----------

@dataclass
class StepScore:
    """一道参考步骤的给分建议。"""

    index: int                    # 参考步骤下标（0 起，参考解切分序）
    ref_text: str                 # 参考步骤原文（切分后）
    student_text: Optional[str]   # 配对到的学生步骤原文；未配对 None
    awarded: int                  # 1=配对计 1 分；0=未配对不计分

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "ref_text": self.ref_text,
            "student_text": self.student_text,
            "awarded": self.awarded,
        }


@dataclass
class GradeSuggestion:
    """一题的分步给分建议 + 复核路由（人机协同闭环的队列条目）。"""

    item_id: str
    steps: list                   # list[StepScore]，参考步骤序
    max_points: int               # 满分 = 参考步骤数
    suggested_points: int         # 建议得分（配对数）
    final_answer: Optional[str]   # 转写的最终答案（空白已规整为 None）
    final_answer_correct: bool    # answer_grader(item, final_answer) 的判定
    flagged_steps: list           # list[str]：低于置信度门的学生步骤原文（转写序）
    reasons: list                 # list[str]：REVIEW_REASONS 词表序、无重复
    needs_review: bool            # == bool(reasons)

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "steps": [s.to_dict() for s in self.steps],
            "max_points": self.max_points,
            "suggested_points": self.suggested_points,
            "final_answer": self.final_answer,
            "final_answer_correct": self.final_answer_correct,
            "flagged_steps": list(self.flagged_steps),
            "reasons": list(self.reasons),
            "needs_review": self.needs_review,
        }


# ---------- 管线入口 ----------

def grade_solution(item, image, client, answer_grader, *,
                   image_format="png", min_confidence=MIN_CONFIDENCE) -> GradeSuggestion:
    """VLM 辅助判分管线：手写照片 -> 步骤转写 -> 冻结规则分步给分 -> 建议。

    守卫顺序冻结（任一失败抛 GradeError，且零次 client 调用）：
    V1 client 有 callable `vision`；V2 answer_grader callable；V3 image 非空 bytes；
    V4 image_format ∈ IMAGE_FORMATS；V5 min_confidence 为 [0,1] 有限数字（拒 bool）；
    V6 题目表面（见 _require_item_surface）。

    通过后恰好一次 `client.vision(prompt, [image], image_format=image_format)`
    （prompt == build_grade_prompt(item)）；parse_transcription 解析（任何解析失败
    -> GradeError 且 answer_grader 不被调用）；随后恰好一次
    `answer_grader(item, final_answer)`，返回值必须为 bool（否则 GradeError）。

    分步给分（规则冻结）：低于 min_confidence 的学生步骤不参与匹配、原文进
    flagged_steps；其余步骤按参考步骤序贪心配对——每个参考步骤取转写序中第一个
    未被占用且 steps_match 的学生步骤，配对计 1 分，每个学生步骤至多用一次；
    多余学生步骤不扣分也不标记。

    复核路由（按 REVIEW_REASONS 词表序累积）：有 flagged_steps -> low_confidence；
    final_answer 为 None -> final_answer_missing；建议分 < 满分 -> partial_match；
    建议分 == 满分且判定错 -> contradiction。reasons 非空即 needs_review。
    client / answer_grader 抛出的异常原样传播（不包装、不吞）。
    """
    # V1 client 表面
    vision_fn = getattr(client, "vision", None)
    if not callable(vision_fn):
        raise GradeError("client must provide a callable vision()")
    # V2 answer_grader 表面
    if not callable(answer_grader):
        raise GradeError("answer_grader must be callable")
    # V3 image
    if not isinstance(image, bytes) or not image:
        raise GradeError(f"image must be non-empty bytes, got {type(image).__name__}")
    # V4 image_format
    if image_format not in IMAGE_FORMATS:
        raise GradeError(f"image format not allowed: {image_format!r}")
    # V5 min_confidence
    if not _is_number(min_confidence) or not math.isfinite(min_confidence) \
            or not 0.0 <= min_confidence <= 1.0:
        raise GradeError(
            f"min_confidence must be a number in [0, 1], got {min_confidence!r}")
    # V6 题目表面（含参考解非空门）
    iid, stem, _answer, ref_steps = _require_item_surface(item)

    # 恰好一次出网（唯一注入口）
    raw = vision_fn(_render_grade_prompt(stem), [image], image_format=image_format)
    transcription = parse_transcription(raw)
    final_answer = transcription["final_answer"]

    # 恰好一次答案判定（判分完整性由注入的 answer_grader 承担）
    verdict = answer_grader(item, final_answer)
    if not isinstance(verdict, bool):
        raise GradeError(
            f"answer_grader must return bool, got {type(verdict).__name__}")

    # 分步给分：低置信步骤只标记不参与；贪心配对、每学生步骤至多用一次
    trusted, flagged = [], []
    for s in transcription["steps"]:
        if s["confidence"] < min_confidence:
            flagged.append(s["text"])
        else:
            trusted.append(s["text"])
    used = [False] * len(trusted)
    step_scores = []
    for idx, ref in enumerate(ref_steps):
        hit = None
        for j, student_text in enumerate(trusted):
            if used[j]:
                continue
            if steps_match(ref, student_text):
                hit = j
                break  # 转写序最前的未占用匹配者胜（冻结平局规则）
        if hit is not None:
            used[hit] = True
            step_scores.append(
                StepScore(index=idx, ref_text=ref, student_text=trusted[hit], awarded=1))
        else:
            step_scores.append(
                StepScore(index=idx, ref_text=ref, student_text=None, awarded=0))
    suggested = sum(s.awarded for s in step_scores)
    max_points = len(ref_steps)

    # 复核路由（词表序；partial 与 contradiction 互斥：建议分不可能既等于又小于满分）
    reasons = []
    if flagged:
        reasons.append(REASON_LOW_CONFIDENCE)
    if final_answer is None:
        reasons.append(REASON_FINAL_ANSWER_MISSING)
    if suggested < max_points:
        reasons.append(REASON_PARTIAL_MATCH)
    if suggested == max_points and verdict is False:
        reasons.append(REASON_CONTRADICTION)

    return GradeSuggestion(
        item_id=iid, steps=step_scores, max_points=max_points,
        suggested_points=suggested, final_answer=final_answer,
        final_answer_correct=verdict, flagged_steps=flagged,
        reasons=reasons, needs_review=bool(reasons))


# ---------- 人机协同闭环（两路互斥） ----------

def _suggestion_item_id(suggestion) -> str:
    iid = getattr(suggestion, "item_id", None)
    if not isinstance(iid, str) or not iid:
        raise GradeError("suggestion.item_id must be a non-blank str")
    return iid


def _suggestion_needs_review(suggestion) -> bool:
    needs = getattr(suggestion, "needs_review", None)
    if not isinstance(needs, bool):
        raise GradeError("suggestion must expose a bool needs_review")
    return needs


def suggest_response(suggestion, response_ms=None):
    """干净建议（needs_review=False）-> Response：判对、learner_answer=转写答案。

    干净建议按构造必是「步骤全配对 + 最终答案在场且判对」，故 correct 恒 True。
    needs_review=True 的建议 -> GradeError（必须走人审 confirm_review）。
    """
    if _suggestion_needs_review(suggestion):
        raise GradeError("suggestion needs human review; use confirm_review()")
    return Response(item_id=_suggestion_item_id(suggestion), correct=True,
                    learner_answer=getattr(suggestion, "final_answer", None),
                    response_ms=response_ms)


def confirm_review(suggestion, correct, learner_answer=None, response_ms=None):
    """需复核建议（needs_review=True）-> 人终审 Response。

    correct 必须为 bool；learner_answer 缺省（None）记录转写的 final_answer，
    传入非 None 值则按人审改写记录。needs_review=False 的干净建议 -> GradeError
    （走 suggest_response，防止人审路径静默绕过自动结论）。
    """
    if not _suggestion_needs_review(suggestion):
        raise GradeError("suggestion does not need review; use suggest_response()")
    if not isinstance(correct, bool):
        raise GradeError(f"correct must be bool, got {type(correct).__name__}")
    iid = _suggestion_item_id(suggestion)
    if learner_answer is None:
        learner_answer = getattr(suggestion, "final_answer", None)
    return Response(item_id=iid, correct=correct,
                    learner_answer=learner_answer, response_ms=response_ms)
