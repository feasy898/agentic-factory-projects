"""mm_ingest —— 拍照录入管线（BACKLOG P3「mm_ingest 拍照录入管线」）的确定性内核。

行为契约（specs/drafts/mm_ingest.spec.md，本文件为参考实现）：

- 管线：一张学生作答照片 -> VLM 结构化转写（题号→学生答案 JSON，schema 冻结）->
  确定性校验（题号∈卷面、答案形态、置信度门）-> 注入的 grader（与
  grading.grade_to_response 同签名）产出 Response；不可信条目（未知题号/重复题号/
  低置信/形态不符/卷面缺号）不猜测、不静默判分，进人机协同复核队列。
- 卷面题号 1..N 与 omr_sheet/paper_layout 同一编号语义（sections 顺序展开、空
  sections 回退 paper.item_ids）；选项标签解析与 omr_sheet.parse_option 同闭式。
- 学生面卫生：VLM prompt 只含题号/题型/choice 标签，绝不含 stem/answer/solution/
  选项正文。
- 模块间零 import：client（mm_client.MMClient 满足其表面）与 grader
  （grading.grade_to_response 满足）都是注入的鸭子类型参数，一致性由契约测试
  在测试内 import 对方模块跨模块锁定。

全模块纯函数：无 IO、无随机、无时钟、不读环境，同输入同输出。
"""
import json
import math
import re
from dataclasses import dataclass
from typing import Optional

from xuexing.types import Response, to_dict

__all__ = [
    "IngestError",
    "INGEST_VERSION",
    "MIN_CONFIDENCE",
    "IMAGE_FORMATS",
    "REASON_UNKNOWN_NUMBER",
    "REASON_DUPLICATE_NUMBER",
    "REASON_MISSING_NUMBER",
    "REASON_LOW_CONFIDENCE",
    "REASON_ANSWER_FORM",
    "REVIEW_REASONS",
    "ReviewItem",
    "IngestResult",
    "build_transcribe_prompt",
    "parse_transcript",
    "option_labels",
    "ingest_photo",
]


class IngestError(ValueError):
    """mm_ingest 模块所有校验失败的异常类型（ValueError 直接子类）。"""


# ---- 冻结常量（specs/drafts/mm_ingest.spec.md §3）----

INGEST_VERSION = "1"

MIN_CONFIDENCE = 0.9  # ingest_photo 的缺省置信度门；confidence < 门限进复核

# 与 mm_client.IMAGE_MIME 键集相等（跨模块锁定）；大小写敏感
IMAGE_FORMATS = ("png", "jpg", "jpeg", "webp", "gif")

REASON_UNKNOWN_NUMBER = "unknown_number"    # 转写题号不在卷面 1..N
REASON_DUPLICATE_NUMBER = "duplicate_number"  # 同一题号被转写多次
REASON_MISSING_NUMBER = "missing_number"    # 卷面题号在转写中完全缺席
REASON_LOW_CONFIDENCE = "low_confidence"    # confidence < min_confidence
REASON_ANSWER_FORM = "answer_form"          # 答案形态与题型不符（不可信不猜）

REVIEW_REASONS = (
    REASON_UNKNOWN_NUMBER,
    REASON_DUPLICATE_NUMBER,
    REASON_MISSING_NUMBER,
    REASON_LOW_CONFIDENCE,
    REASON_ANSWER_FORM,
)

# 合法题型（与 types.Item.item_type 值域一致）
_ITEM_TYPES = ("choice", "fill", "solve")

# 显式选项标签：单个 ASCII 字母 + 分隔符（. ． 、 ) ）），后接选项正文
# （与 omr_sheet.parse_option / paper_layout.parse_option 同款正则，跨模块锁定）
_OPT_RE = re.compile(r"([A-Za-z])[.．、)）][ \t]*(.*)\Z", re.S)
_FALLBACK_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MAX_BUBBLES = 26

# 转写条目必填键（冻结 schema；entry/顶层未知键忽略）
_REQUIRED_ENTRY_KEYS = ("number", "answer", "confidence")


@dataclass
class ReviewItem:
    """人机协同复核队列的一个条目（恰好一个 reason，词表见 REVIEW_REASONS）。"""

    number: int                  # 转写题号；missing_number 时为卷面缺号
    item_id: Optional[str]       # 卷内号给 item_id；unknown_number 恒 None
    answer: Optional[str]        # 转写原文；missing_number 恒 None
    confidence: Optional[float]  # 转写置信度；missing_number 恒 None
    reason: str
    detail: str

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "item_id": self.item_id,
            "answer": self.answer,
            "confidence": self.confidence,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class IngestResult:
    """一次拍照录入的结果：判分 Response（卷面题号升序）+ 复核队列。"""

    responses: list  # list[Response]
    review: list     # list[ReviewItem]

    def to_dict(self) -> dict:
        return {
            "responses": [to_dict(r) for r in self.responses],
            "review": [item.to_dict() for item in self.review],
        }


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------- 卷面表面（题号 1..N -> 题目，omr_sheet 同编号语义） ----------

def _require_str_attr(obj, attr, what):
    value = getattr(obj, attr, None)
    if not isinstance(value, str):
        raise IngestError(f"{what} must be str, got {type(value).__name__}")
    return value


def _bank_index(bank):
    items_fn = getattr(bank, "items", None)
    if not callable(items_fn):
        raise IngestError("bank must expose items()")
    try:
        seq = items_fn()
        iterator = iter(seq)
    except TypeError:
        raise IngestError("bank.items() must return an iterable") from None
    index = {}
    for it in iterator:
        iid = getattr(it, "id", None)
        if not isinstance(iid, str) or not iid.strip():
            raise IngestError("bank item id must be a non-empty str")
        if iid in index:
            raise IngestError(f"duplicate item id in bank: {iid}")
        index[iid] = it
    return index


def _section_lists(paper):
    """paper.sections 规整化为 item_ids 列表的列表（空 -> paper.item_ids 单一隐式节）。"""
    raw_sections = getattr(paper, "sections", None)
    if not isinstance(raw_sections, (list, tuple)):
        raise IngestError("paper.sections must be a list")
    sec_list = list(raw_sections)
    if not sec_list:
        fallback_ids = getattr(paper, "item_ids", None)
        if not isinstance(fallback_ids, (list, tuple)):
            raise IngestError("paper.item_ids must be a list when sections is empty")
        sec_list = [{"item_ids": list(fallback_ids)}]
    out = []
    for sec in sec_list:
        if not isinstance(sec, dict):
            raise IngestError("paper.sections entries must be dicts")
        ids = sec.get("item_ids")
        if not isinstance(ids, (list, tuple)):
            raise IngestError(f"section {sec.get('kp_id', '')!r} item_ids must be a list")
        for iid in ids:
            if not isinstance(iid, str) or not iid.strip():
                raise IngestError(f"section item id must be non-empty str, got {iid!r}")
        out.append([str(iid) for iid in ids])
    return out


def option_labels(item) -> list:
    """choice 题的选项标签列（与 omr_sheet.parse_option 同闭式，跨模块锁定）。

    options 非 list/tuple、长度 <2 或 >26、含非 str/空白串、标签重复 -> IngestError。
    """
    iid = getattr(item, "id", None)
    raw_options = getattr(item, "options", None)
    if not isinstance(raw_options, (list, tuple)) or len(raw_options) < 2:
        raise IngestError(f"item {iid} choice needs >=2 options")
    if len(raw_options) > _MAX_BUBBLES:
        raise IngestError(
            f"item {iid} has {len(raw_options)} options, max is {_MAX_BUBBLES}")
    labels = []
    for pos, raw in enumerate(raw_options):
        if not isinstance(raw, str) or not raw.strip():
            raise IngestError(f"item {iid} option text must be a non-blank str")
        m = _OPT_RE.match(raw.strip())
        labels.append(m.group(1).upper() if m else _FALLBACK_LABELS[pos])
    if len(set(labels)) != len(labels):
        raise IngestError(f"item {iid} duplicate option labels: {labels}")
    return labels


def _paper_questions(paper, bank) -> list:
    """卷面表面校验 + 题号 1..N -> 题目记录列表（校验顺序 V6->V7->V8->空卷门）。"""
    _require_str_attr(paper, "paper_id", "paper.paper_id")
    _require_str_attr(paper, "title", "paper.title")
    index = _bank_index(bank)
    questions = []
    for sec_ids in _section_lists(paper):
        for iid in sec_ids:
            item = index.get(iid)
            if item is None:
                raise IngestError(f"unknown item id in paper: {iid}")
            item_type = getattr(item, "item_type", None)
            if item_type not in _ITEM_TYPES:
                raise IngestError(f"unknown item_type for {iid}: {item_type!r}")
            record = {
                "number": len(questions) + 1,
                "item_id": iid,
                "item": item,
                "item_type": item_type,
                "labels": [],
                "options": [],
            }
            if item_type == "choice":
                raw_options = list(getattr(item, "options"))
                labels = option_labels(item)
                answer = getattr(item, "answer", None)
                if not isinstance(answer, str):
                    raise IngestError(
                        f"item {iid} answer must be str, got {type(answer).__name__}")
                target = answer.strip().upper()
                if target not in labels and not any(
                        isinstance(o, str) and o.strip().upper() == target
                        for o in raw_options):
                    raise IngestError(f"item {iid}: answer not among options")
                record["labels"] = labels
                record["options"] = raw_options
            questions.append(record)
    if not questions:
        raise IngestError("empty paper: no questions to ingest")
    return questions


# ---------- prompt（冻结文本，学生面卫生） ----------

def _render_prompt(questions: list) -> str:
    n = len(questions)
    lines = [
        "你是阅卷录入助手。下面是一张学生作答照片对应的卷面题目清单，请逐题转写学生答案。",
        "只输出一个 JSON 对象，不要输出任何其他文字。",
        '输出 JSON schema（冻结）：{"answers": [{"number": 题号整数, "answer": 学生答案字符串或 null, "confidence": 0 到 1 的数字}]}',
        "规则：",
        f"1. 卷面共 {n} 道题，题号 1..{n}，每个题号在 answers 中恰好出现一次。",
        "2. choice 题：answer 只输出被选选项的标签字母（A-Z 之一）；未作答输出 null。",
        "3. fill/solve 题：answer 按照片原样转写学生书写内容；未作答输出 null。",
        "4. confidence 是你对该条转写的置信度，取 0 到 1。",
        "卷面题目清单：",
    ]
    for q in questions:
        line = f"{q['number']}. {q['item_type']}"
        if q["item_type"] == "choice":
            line += " 选项 " + "/".join(q["labels"])
        lines.append(line)
    return "\n".join(lines)


def build_transcribe_prompt(paper, bank) -> str:
    """卷面 -> 确定性 VLM 转写提示词（只含题号/题型/choice 标签，I4 卫生）。"""
    return _render_prompt(_paper_questions(paper, bank))


# ---------- 转写解析（schema 冻结） ----------

def parse_transcript(text) -> list:
    """VLM 回复文本 -> [{"number": int, "answer": str|None, "confidence": float}…]。

    首个 "{" 到最后一个 "}" 切片 JSON 解析（前后闲话容忍）；顶层 dict 且含 answers
    list；entry 三键必填（number ≥1 int 拒 bool / answer str|None / confidence
    [0,1] 有限数字拒 bool）；未知键忽略；任何违例 -> IngestError。
    """
    if not isinstance(text, str):
        raise IngestError(f"transcript text must be str, got {type(text).__name__}")
    stripped = text.strip()
    if not stripped:
        raise IngestError("transcript is empty")
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise IngestError("transcript contains no json object")
    try:
        parsed = json.loads(stripped[start:end + 1])
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise IngestError(f"transcript is not valid json: {e}") from e
    if not isinstance(parsed, dict):
        raise IngestError("transcript json must be an object")
    answers = parsed.get("answers")
    if not isinstance(answers, list):
        raise IngestError("transcript 'answers' must be a list")
    entries = []
    for i, entry in enumerate(answers):
        if not isinstance(entry, dict):
            raise IngestError(f"transcript entry {i} must be an object")
        for key in _REQUIRED_ENTRY_KEYS:
            if key not in entry:
                raise IngestError(f"transcript entry {i} missing key {key!r}")
        number = entry["number"]
        if not _is_int(number) or number < 1:
            raise IngestError(f"transcript entry {i} number must be int >= 1, got {number!r}")
        answer = entry["answer"]
        if answer is not None and not isinstance(answer, str):
            raise IngestError(
                f"transcript entry {i} answer must be str or null, got {type(answer).__name__}")
        confidence = entry["confidence"]
        if not _is_number(confidence) or not math.isfinite(confidence) \
                or not 0.0 <= confidence <= 1.0:
            raise IngestError(
                f"transcript entry {i} confidence must be a number in [0, 1], got {confidence!r}")
        entries.append({
            "number": number,
            "answer": answer,
            "confidence": float(confidence),
        })
    return entries


# ---------- 管线入口 ----------

def ingest_photo(image, paper, bank, client, grader, *,
                 image_format="png", min_confidence=MIN_CONFIDENCE) -> IngestResult:
    """拍照录入管线：image -> VLM 转写 -> 确定性校验路由 -> grader 判分 + 复核队列。

    校验顺序 V1..V8 冻结（client/grader/image/image_format/min_confidence/卷面），
    任一失败抛 IngestError 且零次 client 调用；随后恰好一次
    client.vision(prompt, [image], image_format=image_format)，grader/client 异常
    原样传播。responses 按卷面题号升序；review = 条目级（转写序）+ 缺号（升序）。
    """
    # V1 client 表面
    vision_fn = getattr(client, "vision", None)
    if not callable(vision_fn):
        raise IngestError("client must provide a callable vision()")
    # V2 grader 表面
    if not callable(grader):
        raise IngestError("grader must be callable")
    # V3 image
    if not isinstance(image, bytes) or not image:
        raise IngestError("image must be non-empty bytes")
    # V4 image_format
    if image_format not in IMAGE_FORMATS:
        raise IngestError(f"image format not allowed: {image_format!r}")
    # V5 min_confidence
    if not _is_number(min_confidence) or not math.isfinite(min_confidence) \
            or not 0.0 <= min_confidence <= 1.0:
        raise IngestError(
            f"min_confidence must be a number in [0, 1], got {min_confidence!r}")
    # V6-V8 卷面表面 + 空卷门
    questions = _paper_questions(paper, bank)
    by_number = {q["number"]: q for q in questions}

    # 恰好一次出网（唯一注入口）
    prompt = _render_prompt(questions)
    raw = vision_fn(prompt, [image], image_format=image_format)
    entries = parse_transcript(raw)

    counts = {}
    for e in entries:
        counts[e["number"]] = counts.get(e["number"], 0) + 1

    responses = []  # (卷面题号, Response)
    review = []
    for e in entries:  # 优先级冻结：unknown > duplicate > low_confidence > form
        number = e["number"]
        answer = e["answer"]
        confidence = e["confidence"]
        q = by_number.get(number)
        if q is None:
            review.append(ReviewItem(
                number=number, item_id=None, answer=answer, confidence=confidence,
                reason=REASON_UNKNOWN_NUMBER,
                detail=f"number {number} is not on paper (1..{len(questions)})"))
            continue
        if counts[number] > 1:
            review.append(ReviewItem(
                number=number, item_id=q["item_id"], answer=answer,
                confidence=confidence, reason=REASON_DUPLICATE_NUMBER,
                detail=f"number {number} transcribed {counts[number]} times"))
            continue
        if confidence < min_confidence:
            review.append(ReviewItem(
                number=number, item_id=q["item_id"], answer=answer,
                confidence=confidence, reason=REASON_LOW_CONFIDENCE,
                detail=f"confidence {confidence} < min_confidence {min_confidence}"))
            continue
        if answer is None or not answer.strip():
            # 空白（VLM 显式 null/空白串）：无作答证据，交 grader 恒判错但不伪造内容
            responses.append((number, grader(q["item"], None)))
            continue
        if q["item_type"] == "choice":
            token = answer.strip().upper()
            if len(token) == 1 and token in q["labels"]:
                idx = q["labels"].index(token)
                responses.append((number, grader(q["item"], q["options"][idx])))
            else:
                review.append(ReviewItem(
                    number=number, item_id=q["item_id"], answer=answer,
                    confidence=confidence, reason=REASON_ANSWER_FORM,
                    detail=f"choice answer must be a single bubble label in "
                           f"{q['labels']}, got {answer!r}"))
            continue
        responses.append((number, grader(q["item"], answer)))  # fill/solve 原文透传

    # 缺号：转写里完全没出现的卷面题号（升序排在条目级 review 之后）
    for q in questions:
        if q["number"] not in counts:
            review.append(ReviewItem(
                number=q["number"], item_id=q["item_id"], answer=None,
                confidence=None, reason=REASON_MISSING_NUMBER,
                detail=f"number {q['number']} missing from transcript"))

    responses.sort(key=lambda pair: pair[0])
    return IngestResult(responses=[r for _, r in responses], review=review)
