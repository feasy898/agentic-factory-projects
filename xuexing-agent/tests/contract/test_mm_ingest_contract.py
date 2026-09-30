"""契约：mm_ingest —— 拍照录入管线（VLM 结构化转写 → 确定性校验 → 判分/复核队列）。

夹具自封闭、**全 mock 零网络**：client 用脚本化 vision mock（记录调用），
MMClient 走 MockTransport；grader 用记录型 mock（跨模块锁定用例另注入
grading.grade_to_response）。全部数值/字节条款为手算可复核的闭式值
（实测于 CPython 3.12 x64）。跨模块锁定（mm_client.IMAGE_MIME 键集 /
omr_sheet.parse_option 标签列 / grading.grade_to_response / omr_sheet 未涂语义）
在测试内 import 对方模块断言，被测模块间零 import。
"""
import copy
import json

import pytest

from xuexing.mm_ingest import (
    IMAGE_FORMATS,
    INGEST_VERSION,
    MIN_CONFIDENCE,
    REASON_ANSWER_FORM,
    REASON_DUPLICATE_NUMBER,
    REASON_LOW_CONFIDENCE,
    REASON_MISSING_NUMBER,
    REASON_UNKNOWN_NUMBER,
    REVIEW_REASONS,
    IngestError,
    IngestResult,
    ReviewItem,
    build_transcribe_prompt,
    ingest_photo,
    option_labels,
    parse_transcript,
)
from xuexing.types import Paper, Response


# ---------- 自封闭小夹具 ----------

class _DuckItem:
    def __init__(self, item_id, item_type, answer, options=None, stem="题"):
        self.id = item_id
        self.item_type = item_type
        self.stem = stem
        self.answer = answer
        self.options = list(options or [])
        self.solution = f"SOL-{item_id}"
        self.misconceptions = ["mc-x"]


class _DuckBank:
    def __init__(self, items):
        self._items = list(items)

    def items(self):
        return list(self._items)


class _ScriptClient:
    """vision 脚本化 mock：恒回同一文本，记录每次调用（零网络）。"""

    def __init__(self, reply):
        self._reply = reply
        self.calls = []

    def vision(self, prompt, images, image_format="png"):
        self.calls.append({"prompt": prompt, "images": list(images),
                           "image_format": image_format})
        return self._reply


class _NoVision:
    pass


C1 = _DuckItem("c1", "choice", "B", ["A. 0", "B. -2/3", "C. +1.5", "D. 2026"])
F1 = _DuckItem("f1", "fill", "-300元")
S1 = _DuckItem("s1", "solve", "x=12")
C2 = _DuckItem("c2", "choice", "2", ["2", "3"])  # 无显式标签 -> 按位回退 A/B
BANK = _DuckBank([C1, F1, S1, C2])

SECTIONS = [
    {"kp_id": "a", "kp_name": "有理数", "item_ids": ["c1", "f1"]},
    {"kp_id": "b", "kp_name": "一元一次方程", "item_ids": ["s1", "c2"]},
]
# 卷面题号（omr_sheet/paper_layout 同语义）：1=c1(choice A-D) 2=f1(fill)
# 3=s1(solve) 4=c2(choice A/B)

IMAGE = b"\x89PNG\r\n\x1a\n fake-image-payload"


def _paper(sections=SECTIONS, item_ids=None, paper_id="paper-88", title="七年级诊断卷"):
    return Paper(
        paper_id=paper_id,
        title=title,
        blueprint={},
        item_ids=item_ids if item_ids is not None else
        [iid for s in sections for iid in s["item_ids"]],
        sections=[dict(s) for s in sections],
    )


def _recording_grader():
    """判分 mock：correct = 有无作答内容；calls 记录 (item_id, learner_answer)。"""
    calls = []

    def grader(item, learner_answer):
        calls.append((item.id, learner_answer))
        return Response(item_id=item.id, correct=(learner_answer is not None),
                        learner_answer=learner_answer, response_ms=None)

    grader.calls = calls
    return grader


def _ingest(transcript, *, sections=SECTIONS, image_format="png",
            min_confidence=MIN_CONFIDENCE, client=None, grader=None):
    cl = client if client is not None else _ScriptClient(transcript)
    gd = grader if grader is not None else _recording_grader()
    result = ingest_photo(IMAGE, _paper(sections=sections), BANK, cl, gd,
                          image_format=image_format, min_confidence=min_confidence)
    return result, cl, gd


# ---------- I1 常量冻结 ----------

def test_frozen_constants():
    assert INGEST_VERSION == "1"
    assert MIN_CONFIDENCE == 0.9
    assert IMAGE_FORMATS == ("png", "jpg", "jpeg", "webp", "gif")
    assert REVIEW_REASONS == (
        "unknown_number", "duplicate_number", "missing_number",
        "low_confidence", "answer_form")
    assert (REASON_UNKNOWN_NUMBER, REASON_DUPLICATE_NUMBER, REASON_MISSING_NUMBER,
            REASON_LOW_CONFIDENCE, REASON_ANSWER_FORM) == REVIEW_REASONS
    assert issubclass(IngestError, ValueError)


def test_image_formats_match_mm_client_mime_keys():
    from xuexing.mm_client import IMAGE_MIME

    assert tuple(sorted(IMAGE_FORMATS)) == tuple(sorted(IMAGE_MIME.keys()))


# ---------- option_labels（与 omr_sheet.parse_option 跨模块锁定） ----------

def test_option_labels_closed_forms():
    assert option_labels(C1) == ["A", "B", "C", "D"]
    assert option_labels(C2) == ["A", "B"]          # 无显式标签按位回退
    lower = _DuckItem("x", "choice", "a", ["b. 一", "c）二", "d．三", "e、四"])
    assert option_labels(lower) == ["B", "C", "D", "E"]  # 标签归一大写


def test_option_labels_guards():
    one = _DuckItem("x", "choice", "A", ["A. 1"])
    many = _DuckItem("x", "choice", "A", [f"{chr(65 + i)}. v{i}" for i in range(27)])
    dup = _DuckItem("x", "choice", "A", ["A. 1", "A. 2"])
    blank = _DuckItem("x", "choice", "A", ["A. 1", "   "])
    nonstr = _DuckItem("x", "choice", "A", ["A. 1", 5])
    none_opts = _DuckItem("x", "choice", "A")
    none_opts.options = None
    noattr = _DuckItem("x", "choice", "A")  # options=[] -> <2
    del noattr.options                       # 属性缺失 -> IngestError
    for item in (one, many, dup, blank, nonstr, none_opts, noattr):
        with pytest.raises(IngestError):
            option_labels(item)


def test_option_labels_matches_omr_sheet_parse_option():
    from xuexing.omr_sheet import parse_option

    for item in (C1, C2):
        assert option_labels(item) == [
            parse_option(o, i)[0] for i, o in enumerate(item.options)]


# ---------- build_transcribe_prompt（I4 冻结文本 + 学生面卫生） ----------

def test_prompt_closed_form_three_questions():
    paper3 = _paper(sections=[{"kp_id": "k", "kp_name": "有理数",
                               "item_ids": ["c1", "f1", "s1"]}])
    expected = "\n".join([
        "你是阅卷录入助手。下面是一张学生作答照片对应的卷面题目清单，请逐题转写学生答案。",
        "只输出一个 JSON 对象，不要输出任何其他文字。",
        '输出 JSON schema（冻结）：{"answers": [{"number": 题号整数, "answer": 学生答案字符串或 null, "confidence": 0 到 1 的数字}]}',
        "规则：",
        "1. 卷面共 3 道题，题号 1..3，每个题号在 answers 中恰好出现一次。",
        "2. choice 题：answer 只输出被选选项的标签字母（A-Z 之一）；未作答输出 null。",
        "3. fill/solve 题：answer 按照片原样转写学生书写内容；未作答输出 null。",
        "4. confidence 是你对该条转写的置信度，取 0 到 1。",
        "卷面题目清单：",
        "1. choice 选项 A/B/C/D",
        "2. fill",
        "3. solve",
    ])
    assert build_transcribe_prompt(paper3, BANK) == expected
    # 同输入同字节
    assert build_transcribe_prompt(paper3, BANK) == expected


def test_prompt_hygiene_no_answer_material():
    prompt = build_transcribe_prompt(_paper(), BANK)
    assert "A/B/C/D" in prompt and "A/B" in prompt  # 只含 choice 标签
    for leak in ("stem-c1", "stem-f1", "-300元", "x=12", "SOL-",   # 题干/答案/解析
                 "B. -2/3", "2026", "+1.5",                        # 选项正文
                 "有理数", "一元一次方程"):                          # 节名
        assert leak not in prompt
    assert prompt == build_transcribe_prompt(_paper(), BANK)       # 确定性


def test_prompt_exact_bytes_over_mm_client_mock_wire():
    """端到端（I10）：MMClient+MockTransport 全 mock 跑通，线上 prompt 逐字节等于
    build_transcribe_prompt，转写 JSON 被结构化解析并进入判分。"""
    from xuexing.mm_client import ENDPOINTS, MMClient, MockTransport

    transcript = '{"answers": [{"number": 1, "answer": "B", "confidence": 0.97}]}'
    reply = json.dumps({"choices": [{"message": {"content": transcript}}]},
                       ensure_ascii=False).encode("utf-8")
    mt = MockTransport(replies={"chat": (200, reply)})
    client = MMClient(mt, env={"XX_LLM_API_KEY": "sentinel-token-1"},
                      resolve=lambda host: ["93.184.216.34"])
    grader = _recording_grader()
    result = ingest_photo(IMAGE, _paper(), BANK, client, grader)
    assert len(mt.calls) == 1
    call = mt.calls[0]
    assert call["url"] == ENDPOINTS["chat"]
    payload = json.loads(call["body"])
    assert payload["messages"][0]["content"][0] == {
        "type": "text", "text": build_transcribe_prompt(_paper(), BANK)}
    assert result.responses == [Response("c1", True, "B. -2/3", None)]
    assert [r.reason for r in result.review] == ["missing_number"] * 3
    assert [r.number for r in result.review] == [2, 3, 4]


# ---------- parse_transcript（I3 schema 冻结） ----------

def test_parse_transcript_closed_forms():
    assert parse_transcript(
        '{"answers": [{"number": 1, "answer": "B", "confidence": 0.97}]}') == [
        {"number": 1, "answer": "B", "confidence": 0.97}]
    assert parse_transcript('{"answers": []} 尾部闲话') == []
    assert parse_transcript('前缀闲话 {"answers": []}') == []
    fenced = "```json\n" \
             '{"answers": [{"number": 2, "answer": null, "confidence": 1}]}\n' \
             "```"
    assert parse_transcript(fenced) == [
        {"number": 2, "answer": None, "confidence": 1.0}]
    out = parse_transcript(
        '{"answers": [{"number": 1, "answer": "B", "confidence": 1, "extra": "x"}]}')
    assert out == [{"number": 1, "answer": "B", "confidence": 1.0}]  # 未知键忽略
    assert isinstance(out[0]["confidence"], float)                    # int 规整 float
    assert set(out[0]) == {"number", "answer", "confidence"}


def test_parse_transcript_guards():
    good_entry = '{"number": 1, "answer": "B", "confidence": 0.9}'
    bad_wholes = [
        "", "   ", "no braces here", "{", "}", "[1, 2]",
        "{}",                                        # 缺 answers
        '{"answers": {}}',                           # answers 非 list
        '{"answers": [5]}',                          # entry 非 dict
        '{"answers": [{"number": 1, "answer": "B"}]}',            # 缺 confidence
        '{"answers": [{"number": 1, "confidence": 0.9}]}',        # 缺 answer
        '{"answers": [{"answer": "B", "confidence": 0.9}]}',      # 缺 number
        "not json {bad} tail",                       # JSON 解析失败
    ]
    for text in bad_wholes:
        with pytest.raises(IngestError):
            parse_transcript(text)
    with pytest.raises(IngestError):
        parse_transcript(42)  # 非 str
    for number in (0, -1, "1", True, 1.5, None):
        entry = '{"number": %s, "answer": "B", "confidence": 0.9}' % json.dumps(number)
        with pytest.raises(IngestError):
            parse_transcript('{"answers": [%s]}' % entry)
    for answer in (42, [], {}):
        entry = '{"number": 1, "answer": %s, "confidence": 0.9}' % json.dumps(answer)
        with pytest.raises(IngestError):
            parse_transcript('{"answers": [%s]}' % entry)
    for confidence in (-0.1, 1.1, "0.9", True, None, float("inf"), float("nan")):
        entry = '{"number": 1, "answer": "B", "confidence": %s}' % json.dumps(confidence)
        with pytest.raises(IngestError):
            parse_transcript('{"answers": [%s]}' % entry)


# ---------- ingest_photo 主路由（I2/I5/I6/I7） ----------

MAIN_TRANSCRIPT = (
    '{"answers": ['
    '{"number": 1, "answer": "B", "confidence": 0.97},'
    '{"number": 2, "answer": "-300元", "confidence": 0.95},'
    '{"number": 4, "answer": "x", "confidence": 0.8},'
    '{"number": 9, "answer": "42", "confidence": 0.99},'
    '{"number": 2, "answer": null, "confidence": 0.3}'
    ']}'
)


def test_ingest_routes_happy_duplicate_low_unknown_missing():
    result, client, grader = _ingest(MAIN_TRANSCRIPT)
    # responses：恰两类产出，卷面题号升序
    assert result.responses == [
        Response("c1", True, "B. -2/3", None),   # choice 交选项原文全串
    ]
    # review：条目级按转写序（duplicate 优先于 low_confidence）
    assert [(r.reason, r.number) for r in result.review] == [
        (REASON_DUPLICATE_NUMBER, 2),   # 2 出现 2 次：每条副本都进队
        (REASON_LOW_CONFIDENCE, 4),     # 0.8 < 0.9，先于形态门
        (REASON_UNKNOWN_NUMBER, 9),
        (REASON_DUPLICATE_NUMBER, 2),   # 低置信副本也是 duplicate 优先
        (REASON_MISSING_NUMBER, 3),     # 缺号排在最后
    ]
    assert [(r.item_id, r.answer, r.confidence) for r in result.review] == [
        ("f1", "-300元", 0.95),
        ("c2", "x", 0.8),
        (None, "42", 0.99),             # unknown_number 无 item_id
        ("f1", None, 0.3),
        ("s1", None, None),             # missing_number 无转写内容
    ]
    assert "not on paper" in result.review[2].detail
    assert "transcribed 2 times" in result.review[0].detail
    assert "min_confidence" in result.review[1].detail
    assert "missing from transcript" in result.review[4].detail
    # I5：恰好一次出网；每个 Response 恰好一次 grader；review 条目零 grader
    assert len(client.calls) == 1
    assert grader.calls == [("c1", "B. -2/3")]


def test_ingest_blank_answers_become_null_responses():
    transcript = ('{"answers": [{"number": 4, "answer": null, "confidence": 1}, '
                  '{"number": 1, "answer": "  ", "confidence": 1.0}]}')
    result, _, grader = _ingest(transcript)
    assert result.responses == [
        Response("c1", False, None, None), Response("c2", False, None, None)]
    assert grader.calls == [("c2", None), ("c1", None)]  # 判分按转写序、不伪造
    assert [(r.reason, r.number) for r in result.review] == [
        (REASON_MISSING_NUMBER, 2), (REASON_MISSING_NUMBER, 3)]


def test_ingest_choice_form_gate():
    def one(answer_text, number):
        text = ('{"answers": [{"number": %d, "answer": %s, "confidence": 1}]}'
                % (number, json.dumps(answer_text)))
        return _ingest(text)

    # 小写标签归一；grader 收到该选项原文全串
    result, _, grader = one("b", 4)
    assert result.responses == [Response("c2", True, "3", None)]  # c2 选项原文是 "3"
    assert grader.calls == [("c2", "3")]
    result, _, grader = one("b", 1)
    assert result.responses == [Response("c1", True, "B. -2/3", None)]
    # 不可信形态一律复核（宁可交人，不猜）；其余缺号条目仍进队
    for answer_text, number in (("E", 4), ("AB", 4), ("B. -2/3", 1), ("A.", 1), ("3", 4)):
        result, _, grader = one(answer_text, number)
        assert result.responses == []
        item = result.review[0]
        assert (item.reason, item.number, item.item_id) == (
            REASON_ANSWER_FORM, number, "c1" if number == 1 else "c2")
        assert item.answer == answer_text
        assert [r.reason for r in result.review[1:]] == [REASON_MISSING_NUMBER] * 3
        assert grader.calls == []


def test_ingest_min_confidence_boundary_and_custom():
    at_gate = ('{"answers": [{"number": 1, "answer": "B", "confidence": 0.9}]}')
    result, _, _ = _ingest(at_gate)  # 恰好等于门限：通过
    assert [r.item_id for r in result.responses] == ["c1"]
    zero = ('{"answers": [{"number": 4, "answer": "A", "confidence": 0.0}]}')
    result, _, _ = _ingest(zero, min_confidence=0.0)  # 0.0 < 0.0 不成立：通过
    assert [r.item_id for r in result.responses] == ["c2"]
    strict = ('{"answers": [{"number": 1, "answer": "B", "confidence": 0.99}]}')
    result, _, _ = _ingest(strict, min_confidence=1.0)  # 0.99 < 1：低置信
    assert result.responses == []
    assert [r.reason for r in result.review] == [
        REASON_LOW_CONFIDENCE] + [REASON_MISSING_NUMBER] * 3


def test_ingest_empty_transcript_all_missing_in_order():
    result, client, grader = _ingest('{"answers": []}')
    assert result.responses == []
    assert grader.calls == []
    assert [(r.reason, r.number, r.item_id, r.answer, r.confidence)
            for r in result.review] == [
        (REASON_MISSING_NUMBER, 1, "c1", None, None),
        (REASON_MISSING_NUMBER, 2, "f1", None, None),
        (REASON_MISSING_NUMBER, 3, "s1", None, None),
        (REASON_MISSING_NUMBER, 4, "c2", None, None),
    ]
    assert len(client.calls) == 1  # 仍恰好一次出网


def test_ingest_responses_sorted_by_paper_number():
    transcript = ('{"answers": [{"number": 4, "answer": "A", "confidence": 1}, '
                  '{"number": 1, "answer": "B", "confidence": 1}]}')
    result, _, grader = _ingest(transcript)
    assert [r.item_id for r in result.responses] == ["c1", "c2"]  # 题号升序，非转写序
    assert [r.learner_answer for r in result.responses] == ["B. -2/3", "2"]
    # 判分按转写序发生，产出在末尾统一按卷面题号排序
    assert grader.calls == [("c2", "2"), ("c1", "B. -2/3")]


def test_ingest_review_only_transcript_zero_grader_calls():
    result, _, grader = _ingest('{"answers": [{"number": 9, "answer": "7", "confidence": 1}]}')
    assert result.responses == []
    assert grader.calls == []
    assert [(r.reason, r.number) for r in result.review] == [
        (REASON_UNKNOWN_NUMBER, 9),
        (REASON_MISSING_NUMBER, 1), (REASON_MISSING_NUMBER, 2),
        (REASON_MISSING_NUMBER, 3), (REASON_MISSING_NUMBER, 4),
    ]


# ---------- I5 出网形状 ----------

def test_ingest_single_vision_call_image_and_format_passthrough():
    transcript = '{"answers": []}'
    client = _ScriptClient(transcript)
    _ingest(transcript, client=client)
    assert client.calls == [{"prompt": build_transcribe_prompt(_paper(), BANK),
                             "images": [IMAGE], "image_format": "png"}]
    client2 = _ScriptClient(transcript)
    _ingest(transcript, client=client2, image_format="jpeg")
    assert client2.calls[0]["image_format"] == "jpeg"


# ---------- I8 失败纪律 ----------

def test_ingest_client_and_grader_exceptions_propagate_unwrapped():
    class _BoomClient:
        def vision(self, prompt, images, image_format="png"):
            raise RuntimeError("llm down")

    with pytest.raises(RuntimeError, match="llm down"):
        ingest_photo(IMAGE, _paper(), BANK, _BoomClient(), _recording_grader())

    def boom_grader(item, learner_answer):
        raise ValueError("grading boom")

    transcript = '{"answers": [{"number": 1, "answer": "B", "confidence": 1}]}'
    with pytest.raises(ValueError, match="grading boom"):
        ingest_photo(IMAGE, _paper(), BANK, _ScriptClient(transcript), boom_grader)


def test_ingest_v_guards_fail_before_any_network_call():
    client = _ScriptClient('{"answers": []}')
    paper = _paper()
    bad_calls = [
        lambda: ingest_photo(IMAGE, paper, BANK, _NoVision(), _recording_grader()),
        lambda: ingest_photo(IMAGE, paper, BANK, client, None),          # grader 非 callable
        lambda: ingest_photo(IMAGE, paper, BANK, client, "grader"),
        lambda: ingest_photo(b"", paper, BANK, client, _recording_grader()),
        lambda: ingest_photo(None, paper, BANK, client, _recording_grader()),
        lambda: ingest_photo("not bytes", paper, BANK, client, _recording_grader()),
        lambda: ingest_photo(IMAGE, paper, BANK, client, _recording_grader(),
                             image_format="bmp"),
        lambda: ingest_photo(IMAGE, paper, BANK, client, _recording_grader(),
                             image_format="PNG"),                        # 大小写敏感
        lambda: ingest_photo(IMAGE, paper, BANK, client, _recording_grader(),
                             min_confidence=-0.1),
        lambda: ingest_photo(IMAGE, paper, BANK, client, _recording_grader(),
                             min_confidence=1.5),
        lambda: ingest_photo(IMAGE, paper, BANK, client, _recording_grader(),
                             min_confidence=True),
        lambda: ingest_photo(IMAGE, paper, BANK, client, _recording_grader(),
                             min_confidence="0.9"),
        lambda: ingest_photo(IMAGE, paper, BANK, client, _recording_grader(),
                             min_confidence=float("nan")),
    ]
    for bad in bad_calls:
        with pytest.raises(IngestError):
            bad()
    assert client.calls == []  # 全部守卫失败零出网


def test_ingest_paper_bank_surface_guards_zero_network():
    client = _ScriptClient('{"answers": []}')
    bad_calls = [
        lambda: ingest_photo(IMAGE, _NoVision(), BANK, client, _recording_grader()),
        lambda: ingest_photo(IMAGE, Paper(paper_id=None, title="t", blueprint={},
                                          item_ids=["c1"], sections=[]),
                             BANK, client, _recording_grader()),
        lambda: ingest_photo(IMAGE, Paper(paper_id="p", title=5, blueprint={},
                                          item_ids=["c1"], sections=[]),
                             BANK, client, _recording_grader()),
        lambda: ingest_photo(IMAGE, Paper(paper_id="p", title="t", blueprint={},
                                          item_ids=["c1"], sections="x"),
                             BANK, client, _recording_grader()),
        lambda: ingest_photo(IMAGE, Paper(paper_id="p", title="t", blueprint={},
                                          item_ids=None, sections=[]),
                             BANK, client, _recording_grader()),       # 空节回退 item_ids 非 list
        lambda: ingest_photo(IMAGE, Paper(paper_id="p", title="t", blueprint={},
                                          item_ids=[], sections=[42]),
                             BANK, client, _recording_grader()),       # 节非 dict
        lambda: ingest_photo(IMAGE, Paper(paper_id="p", title="t", blueprint={},
                                          item_ids=[], sections=[{"item_ids": "c1"}]),
                             BANK, client, _recording_grader()),       # item_ids 非 list
        lambda: ingest_photo(IMAGE, Paper(paper_id="p", title="t", blueprint={},
                                          item_ids=[], sections=[{"item_ids": [5]}]),
                             BANK, client, _recording_grader()),       # 题 id 非 str
        lambda: ingest_photo(IMAGE, Paper(paper_id="p", title="t", blueprint={},
                                          item_ids=[], sections=[{"item_ids": ["zz"]}]),
                             BANK, client, _recording_grader()),       # 未知题 id
        lambda: ingest_photo(IMAGE, _paper(), _NoVision(), client, _recording_grader()),
        lambda: ingest_photo(IMAGE, _paper(), _DuckBank([C1, C1]), client,
                             _recording_grader()),                     # bank 重复 id
        lambda: ingest_photo(IMAGE, _paper(
            sections=[{"item_ids": ["c1", "f1", "s1", "c2", "e1"]}]), BANK,
            client, _recording_grader()),                              # 未知题 e1
        lambda: ingest_photo(IMAGE, _paper(), _DuckBank(
            [_DuckItem("c1", "essay", "x"), F1]), client,
            _recording_grader()),                                      # 未知题型
        lambda: ingest_photo(IMAGE, _paper(), _DuckBank(
            [_DuckItem("c1", "choice", "A", ["A. 1"]), F1]), client,
            _recording_grader()),                                      # choice 单选项
        lambda: ingest_photo(IMAGE, _paper(), _DuckBank(
            [_DuckItem("c1", "choice", "A", ["A. 1", "A. 2"]), F1]), client,
            _recording_grader()),                                      # 标签重复
        lambda: ingest_photo(IMAGE, _paper(), _DuckBank(
            [_DuckItem("c1", "choice", "Z", ["A. 1", "B. 2"]), F1]), client,
            _recording_grader()),                                      # 标答不在选项
        lambda: ingest_photo(IMAGE, _paper(), _DuckBank(
            [_DuckItem("c1", "choice", None, ["A. 1", "B. 2"]), F1]), client,
            _recording_grader()),                                      # 标答非 str
    ]
    empty1 = Paper(paper_id="p", title="t", blueprint={}, item_ids=[],
                   sections=[{"item_ids": []}])
    empty2 = Paper(paper_id="p", title="t", blueprint={}, item_ids=[], sections=[])
    for paper in (empty1, empty2):
        bad_calls.append(lambda p=paper: ingest_photo(
            IMAGE, p, BANK, client, _recording_grader()))              # 空卷
    bad_calls.append(lambda: ingest_photo(
        IMAGE, _paper(), object(), client, _recording_grader()))       # bank 无 items()
    class _BadBank:
        def items(self):
            return 5
    bad_calls.append(lambda: ingest_photo(
        IMAGE, _paper(), _BadBank(), client, _recording_grader()))     # items() 不可迭代
    for bad in bad_calls:
        with pytest.raises(IngestError):
            bad()
    assert client.calls == []  # 卷面守卫失败零出网


# ---------- I9 确定性 ----------

def test_ingest_determinism_same_input_same_output():
    a, _, _ = _ingest(MAIN_TRANSCRIPT)
    b, _, _ = _ingest(MAIN_TRANSCRIPT)
    assert a.to_dict() == b.to_dict()
    assert a.responses == b.responses and a.review == b.review


def test_ingest_inputs_not_mutated():
    sections_snapshot = copy.deepcopy(SECTIONS)
    options_snapshot = [list(it.options) for it in (C1, F1, S1, C2)]
    answers_snapshot = [it.answer for it in (C1, F1, S1, C2)]
    image_snapshot = bytes(IMAGE)
    _ingest(MAIN_TRANSCRIPT)
    assert SECTIONS == sections_snapshot
    assert [it.options for it in (C1, F1, S1, C2)] == options_snapshot
    assert [it.answer for it in (C1, F1, S1, C2)] == answers_snapshot
    assert IMAGE == image_snapshot


# ---------- I10 跨模块锁定（测试内 import 对方模块） ----------

def test_cross_module_grading_grade_to_response_equality():
    from xuexing.grading import grade_to_response

    transcript = ('{"answers": [{"number": 1, "answer": "B", "confidence": 1}, '
                  '{"number": 2, "answer": "-300元", "confidence": 1}]}')
    result, _, _ = _ingest(transcript, grader=grade_to_response)
    assert result.responses == [
        grade_to_response(C1, "B. -2/3"),   # choice：判对
        grade_to_response(F1, "-300元"),    # fill：数值+单位判对
    ]
    assert result.responses == [
        Response("c1", True, "B. -2/3", None),
        Response("f1", True, "-300元", None),
    ]


def test_cross_module_omr_blank_mark_semantics():
    from xuexing.grading import grade_to_response
    from xuexing.omr_sheet import build_answer_sheet, to_responses

    transcript = '{"answers": [{"number": 4, "answer": null, "confidence": 1}]}'
    result, _, _ = _ingest(transcript, grader=grade_to_response)
    sheet = build_answer_sheet(_paper(), BANK)
    omr_rows = to_responses({"file_id": "x", "values": {"q1": "", "q4": ""}},
                            sheet, BANK)
    assert omr_rows[1] == Response("c2", False, None, None)  # omr 未涂
    assert result.responses[0] == omr_rows[1]                # 空白转写同语义
    assert omr_rows[0] == Response("c1", False, None, None)


# ---------- 数据形状 ----------

def test_review_item_and_ingest_result_to_dict_shapes():
    item = ReviewItem(number=1, item_id="c1", answer="B", confidence=0.9,
                      reason=REASON_LOW_CONFIDENCE, detail="d")
    assert item.to_dict() == {
        "number": 1, "item_id": "c1", "answer": "B", "confidence": 0.9,
        "reason": "low_confidence", "detail": "d"}
    result = IngestResult(responses=[Response("c1", True, "B. -2/3", None)],
                          review=[item])
    assert result.to_dict() == {
        "responses": [{"item_id": "c1", "correct": True,
                       "learner_answer": "B. -2/3", "response_ms": None}],
        "review": [item.to_dict()],
    }
