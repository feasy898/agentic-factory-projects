"""契约：mm_grade —— VLM 辅助判分（步骤转写 → 冻结规则分步给分 → 人机协同闭环）。

夹具自封闭、**全 mock 零网络**：client 用脚本化 vision mock（记录调用），
MMClient 走 MockTransport；answer_grader 用记录型 mock（跨模块锁定用例另注入
grading.grade）。全部数值/字节条款为手算可复核的闭式值（实测于 CPython 3.12
x64：480-30=450、450/3=150、1/2+1/3=5/6、10/12≡5/6）。跨模块锁定
（mm_client.IMAGE_MIME 键集 / grading.grade 闭式 / MMClient+MockTransport 线上
prompt 逐字节）在测试内 import 对方模块断言，被测模块间零 import。
"""
import copy
import json

import pytest

from xuexing.mm_grade import (
    GRADE_VERSION,
    IMAGE_FORMATS,
    MIN_CONFIDENCE,
    REASON_CONTRADICTION,
    REASON_FINAL_ANSWER_MISSING,
    REASON_LOW_CONFIDENCE,
    REASON_PARTIAL_MATCH,
    REVIEW_REASONS,
    GradeError,
    build_grade_prompt,
    confirm_review,
    grade_solution,
    match_key,
    parse_transcription,
    solution_steps,
    steps_match,
    suggest_response,
)
from xuexing.types import Response


# 哨兵环境：非机密占位值，仅供 MMClient 的 mock 传输层读取，不对应任何真实凭据
_SENTINEL_ENV = {"XX_LLM_API_KEY": "sentinel-token-1"}


# ---------- 自封闭小夹具 ----------

class _DuckItem:
    def __init__(self, item_id, item_type, stem, answer, solution):
        self.id = item_id
        self.item_type = item_type
        self.stem = stem
        self.answer = answer
        self.solution = solution
        self.options = []
        self.kps = ["kp-x"]
        self.difficulty = 0.5


# 题面验算：乙队修 3 天后还剩 30 米 -> 3x + 30 = 480 -> x = 150（手算可复核）
SOLVE = _DuckItem(
    "s1", "solve",
    "甲乙两队合修一条 480 米的路，乙队修了 3 天后还剩 30 米没修完，乙队平均每天修多少米？",
    "x=150",
    "解：设乙队每天修 x 米。\n(1) 列方程：3x + 30 = 480。\n"
    "2. 解方程得 x = 150。\n答：乙队每天修 150 米。",
)
REF_STEPS = solution_steps(SOLVE.solution)
assert REF_STEPS == [
    "解：设乙队每天修 x 米。",
    "列方程：3x + 30 = 480。",
    "解方程得 x = 150。",
    "答：乙队每天修 150 米。",
], REF_STEPS

# 数值等值题：1/2 + 1/3 = 5/6；学生答案 10/12 与标答 5/6 数值等值（现算核实）
SOLVE_FRAC = _DuckItem("s3", "solve", "计算：1/2 + 1/3 = ?",
                       "5/6", "1/2 + 1/3\n= 3/6 + 2/6\n= 5/6")

CHOICE = _DuckItem("c1", "choice", "1+1=?", "B", "")

FULL_STEPS = ["解：设乙队每天修x米。", "列方程：3x+30=480。",
              "解方程得x=150。", "答：乙队每天修150米。"]
IMAGE = b"\x89PNG\r\n\x1a\n fake-handwriting-payload"


def _transcript(steps, final="x=150"):
    """steps: list[(text, confidence)] -> 冻结 schema 的 VLM 回复 JSON 文本。"""
    payload = {"steps": [{"text": t, "confidence": c} for t, c in steps]}
    if final is not ...:
        payload["final_answer"] = final
    return json.dumps(payload, ensure_ascii=False)


def _full_transcript(conf=1.0):
    return _transcript([(t, conf) for t in FULL_STEPS])


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


def _recording_grader(fn=None):
    """答案判定 mock：默认 correct = (answer == "x=150")；calls 记录 (item_id, answer)。"""
    calls = []

    def grader(item, answer):
        calls.append((item.id, answer))
        if fn is not None:
            return fn(item, answer)
        return answer == "x=150"

    grader.calls = calls
    return grader


def _grade(transcript, *, item=SOLVE, image_format="png",
           min_confidence=MIN_CONFIDENCE, client=None, grader=None):
    cl = client if client is not None else _ScriptClient(transcript)
    gd = grader if grader is not None else _recording_grader()
    suggestion = grade_solution(item, IMAGE, cl, gd,
                                image_format=image_format,
                                min_confidence=min_confidence)
    return suggestion, cl, gd


# ---------- I1 常量冻结 ----------

def test_frozen_constants():
    assert GRADE_VERSION == "1"
    assert MIN_CONFIDENCE == 0.9
    assert IMAGE_FORMATS == ("png", "jpg", "jpeg", "webp", "gif")
    assert REVIEW_REASONS == (
        "low_confidence", "final_answer_missing", "partial_match", "contradiction")
    assert (REASON_LOW_CONFIDENCE, REASON_FINAL_ANSWER_MISSING,
            REASON_PARTIAL_MATCH, REASON_CONTRADICTION) == REVIEW_REASONS
    assert issubclass(GradeError, ValueError)


def test_image_formats_match_mm_client_mime_keys():
    from xuexing.mm_client import IMAGE_MIME

    assert tuple(sorted(IMAGE_FORMATS)) == tuple(sorted(IMAGE_MIME.keys()))


# ---------- solution_steps（I4 参考解切分） ----------

def test_solution_steps_closed_forms():
    assert solution_steps(SOLVE.solution) == REF_STEPS
    assert solution_steps("（一）验证。") == ["验证。"]
    assert solution_steps("十、总结") == ["总结"]
    assert solution_steps("第一行\r\n2.第二行\r\n") == ["第一行", "第二行"]  # \r\n 容忍
    assert solution_steps("   \n  ") == []
    assert solution_steps("") == []
    with pytest.raises(GradeError):
        solution_steps(42)


# ---------- match_key / steps_match（I4 匹配规则） ----------

def test_match_key_closed_forms():
    assert match_key("Ｘ＝１５０") == "x=150"      # 全角折叠 + 小写
    assert match_key("a  b　c") == "abc"            # 删除全部空白（含 U+3000）
    assert match_key("解：设乙队每天修 X 米。") == "解:设乙队每天修x米。"
    assert match_key("") == ""
    with pytest.raises(GradeError):
        match_key(7)


def test_steps_match_closed_forms():
    assert steps_match("x = 150。", "x=150。") is True        # 折叠后相等
    assert steps_match("x = 150。", "所以x=150。") is True    # 参考 ⊆ 学生
    assert steps_match("解：设乙队每天修 x 米。", "设乙队每天修x米") is True  # 学生 ⊆ 参考
    assert steps_match("Ｘ＝１５０", "x=150") is True         # 全角折叠
    assert steps_match("x = 150。", "x=45") is False
    assert steps_match("x = 150。", "  ") is False            # 空白永不匹配
    assert steps_match("", "x=150") is False
    with pytest.raises(GradeError):
        steps_match(5, "x=150")


# ---------- build_grade_prompt（I2 冻结文本 + 判分侧卫生） ----------

def test_prompt_closed_form():
    expected = "\n".join([
        "你是阅卷助手。下面是一道主观解答题的题面，请从学生手写作答照片中逐行转写学生的解答过程。",
        "只输出一个 JSON 对象，不要输出任何其他文字。",
        '输出 JSON schema（冻结）：{"steps": [{"text": 学生某一步书写内容的原样转写, "confidence": 0 到 1 的数字}], "final_answer": 学生最终答案字符串或 null}',
        "规则：",
        "1. 只转写学生实际书写的内容，按书写顺序逐行转写；不补全、不改写、不自己计算。",
        "2. text 是该步原样转写；confidence 是你对该步转写的置信度，取 0 到 1。",
        "3. 学生写了最终答案则原样转写为 final_answer；没有写输出 null。",
        "题面：",
        SOLVE.stem,
    ])
    assert build_grade_prompt(SOLVE) == expected
    assert build_grade_prompt(SOLVE) == expected  # 同输入同字节


def test_prompt_hygiene_no_reference_material():
    prompt = build_grade_prompt(SOLVE)
    assert SOLVE.stem in prompt                      # 只含题面
    for leak in (SOLVE.answer, "x=150",              # 标答（含子串形态）
                 "解：设乙队", "3x + 30 = 480", "解方程得", "列方程",  # 参考解/步骤
                 "答：乙队每天修"):
        assert leak not in prompt
    with pytest.raises(GradeError):
        build_grade_prompt(CHOICE)                   # 非 solve 同样被 V6 拒


# ---------- parse_transcription（I3 schema 冻结） ----------

def test_parse_transcription_closed_forms():
    out = parse_transcription('{"steps": [{"text": "x=150", "confidence": 1}]}')
    assert out == {"steps": [{"text": "x=150", "confidence": 1.0}],
                   "final_answer": None}
    assert isinstance(out["steps"][0]["confidence"], float)   # int 规整 float
    assert set(out["steps"][0]) == {"text", "confidence"}      # 未知键忽略
    out = parse_transcription(
        '{"steps": [{"text": "解", "confidence": 0.9, "extra": 1}],'
        ' "final_answer": "x=150", "junk": true}')
    assert out == {"steps": [{"text": "解", "confidence": 0.9}],
                   "final_answer": "x=150"}
    fenced = "```json\n" \
             '{"steps": [], "final_answer": "  "}\n' \
             "``` 前后闲话"
    assert parse_transcription(fenced) == {"steps": [], "final_answer": None}
    assert parse_transcription('{"steps": []}') == {"steps": [], "final_answer": None}


def test_parse_transcription_guards():
    bad_wholes = [
        "", "   ", "no braces", "{", "}", "[1]", "{}",          # 无对象/缺 steps
        '{"steps": {}}',                                        # steps 非 list
        '{"steps": [5]}',                                       # 步骤非 dict
        '{"steps": [{"text": "x"}]}',                           # 缺 confidence
        '{"steps": [{"confidence": 0.9}]}',                     # 缺 text
        '{"steps": [{"text": 42, "confidence": 0.9}]}',         # text 非 str
        "not json {bad} tail",                                  # JSON 解析失败
        '{"steps": [], "final_answer": 42}',                    # final_answer 非 str/null
    ]
    for text in bad_wholes:
        with pytest.raises(GradeError):
            parse_transcription(text)
    with pytest.raises(GradeError):
        parse_transcription(None)                                # 非 str
    for confidence in (-0.1, 1.1, "0.9", True, None, float("inf"), float("nan")):
        entry = '{"text": "x", "confidence": %s}' % json.dumps(confidence)
        with pytest.raises(GradeError):
            parse_transcription('{"steps": [%s]}' % entry)


# ---------- grade_solution 主路由（I4/I5/I6） ----------

def test_grade_solution_full_match_clean_auto():
    s, client, grader = _grade(_full_transcript())
    assert s.item_id == "s1"
    assert s.max_points == 4 and s.suggested_points == 4
    assert [step.student_text for step in s.steps] == FULL_STEPS
    assert [step.awarded for step in s.steps] == [1, 1, 1, 1]
    assert [step.index for step in s.steps] == [0, 1, 2, 3]
    assert s.final_answer == "x=150" and s.final_answer_correct is True
    assert s.flagged_steps == [] and s.reasons == [] and s.needs_review is False
    assert len(client.calls) == 1                     # I6：恰好一次出网
    assert grader.calls == [("s1", "x=150")]          # I6：恰好一次答案判定
    # 干净建议走自动路：correct 恒 True、learner_answer=转写答案
    assert suggest_response(s) == Response("s1", True, "x=150", None)


def test_grade_solution_partial_match_flags_review():
    partial = [FULL_STEPS[0], FULL_STEPS[2], FULL_STEPS[3]]   # 漏「列方程」步
    s, _, grader = _grade(_transcript([(t, 1.0) for t in partial]))
    assert s.suggested_points == 3 and s.max_points == 4
    assert s.steps[1].awarded == 0 and s.steps[1].student_text is None
    assert s.steps[1].ref_text == "列方程：3x + 30 = 480。"
    assert s.reasons == [REASON_PARTIAL_MATCH] and s.needs_review is True
    assert s.final_answer_correct is True                       # 答案对但步骤不齐 -> 人审
    # 需复核建议不可走自动路
    with pytest.raises(GradeError):
        suggest_response(s)
    assert grader.calls == [("s1", "x=150")]


def test_grade_solution_low_confidence_excluded_and_flagged():
    steps = [(FULL_STEPS[0], 0.95), (FULL_STEPS[1], 0.5),   # 第 2 步低置信
             (FULL_STEPS[2], 0.95), (FULL_STEPS[3], 0.95)]
    s, _, _ = _grade(_transcript(steps))
    assert s.flagged_steps == ["列方程：3x+30=480。"]          # 低置信原文入队
    assert s.steps[1].awarded == 0 and s.steps[1].student_text is None  # 不计分
    assert s.suggested_points == 3
    assert s.reasons == [REASON_LOW_CONFIDENCE, REASON_PARTIAL_MATCH]   # 词表序
    assert s.needs_review is True


def test_grade_solution_confidence_boundary_is_inclusive():
    s, _, _ = _grade(_full_transcript(conf=0.9))   # 恰好等于门限：参与匹配
    assert s.flagged_steps == [] and s.suggested_points == 4
    assert s.needs_review is False
    below = _grade(_transcript([(t, 0.8999999999) for t in FULL_STEPS]))[0]
    assert len(below.flagged_steps) == 4 and below.suggested_points == 0


def test_grade_solution_final_answer_missing():
    s, _, grader = _grade(_transcript([(t, 1.0) for t in FULL_STEPS], final=None))
    assert s.final_answer is None and s.final_answer_correct is False
    # 步骤全配对（含「答：…」行）却没提取到最终答案：转写自相矛盾 -> 双原因
    assert s.reasons == [REASON_FINAL_ANSWER_MISSING, REASON_CONTRADICTION]
    assert grader.calls == [("s1", None)]            # None 也恰好判定一次（诚实无证据）
    # 空白 final_answer 同语义
    s2, _, grader2 = _grade(_transcript([(t, 1.0) for t in FULL_STEPS], final="   "))
    assert s2.final_answer is None and grader2.calls == [("s1", None)]


def test_grade_solution_contradiction_when_full_but_wrong():
    s, _, grader = _grade(_full_transcript(), grader=_recording_grader(
        lambda item, answer: answer == "x=45"))
    assert s.suggested_points == 4 and s.final_answer_correct is False
    assert s.reasons == [REASON_CONTRADICTION] and s.needs_review is True
    assert grader.calls == [("s1", "x=150")]
    # 步骤不齐 + 答案错：partial 与 contradiction 互斥，只报 partial
    s2, _, _ = _grade(_transcript([(FULL_STEPS[0], 1.0)]),
                      grader=_recording_grader(lambda item, answer: False))
    assert s2.reasons == [REASON_PARTIAL_MATCH]


def test_grade_solution_reason_order_and_completeness():
    # 低置信步骤（覆盖不到全部参考步骤）+ 缺最终答案 -> 词表序三原因
    s, _, grader = _grade(_transcript([(FULL_STEPS[0], 0.3)], final=None))
    assert s.reasons == [REASON_LOW_CONFIDENCE, REASON_FINAL_ANSWER_MISSING,
                         REASON_PARTIAL_MATCH]
    assert s.needs_review is True and len(s.flagged_steps) == 1
    assert grader.calls == [("s1", None)]


def test_grade_solution_greedy_uses_each_student_step_once():
    # 三个参考步骤全部被包含在同一条学生步骤里：只有第一条配对成功
    mega = "设总路程为x千米。则x-5=12。所以x=17。"
    item = _DuckItem("s2", "solve", "小明有一些糖，吃掉 5 颗后还剩 12 颗，原来有多少颗？",
                     "x=17", "设总路程为 x 千米。\n则 x - 5 = 12。\n所以 x = 17。")
    s, _, _ = _grade(_transcript([(mega, 1.0)], final="x=17"), item=item)
    assert s.max_points == 3 and s.suggested_points == 1
    assert [step.student_text for step in s.steps] == [mega, None, None]
    assert s.reasons == [REASON_PARTIAL_MATCH]
    # 左most 未占用者胜：乱序转写各自配到各自的参考步骤
    s2, _, _ = _grade(_transcript([("所以x=17。", 1.0), ("设总路程为x千米。", 1.0)],
                                  final="x=17"), item=item)
    assert [step.student_text for step in s2.steps] == [
        "设总路程为x千米。", None, "所以x=17。"]
    assert s2.suggested_points == 2


def test_grade_solution_extra_student_steps_not_penalized():
    steps = FULL_STEPS + ["草稿：3×150=450 验算"]     # 多余步骤
    s, _, _ = _grade(_transcript([(t, 1.0) for t in steps]))
    assert s.suggested_points == 4 and s.reasons == []
    assert s.needs_review is False and s.flagged_steps == []


def test_grade_solution_answer_only_still_review():
    # 学生只写了答案（跳步）：答案对也进人审（步骤证据缺失）
    s, _, grader = _grade(_transcript([], final="x=150"))
    assert s.suggested_points == 0 and s.final_answer_correct is True
    assert s.reasons == [REASON_PARTIAL_MATCH]
    assert grader.calls == [("s1", "x=150")]


# ---------- I6 出网形状与失败纪律 ----------

def test_grade_solution_single_vision_call_passthrough():
    transcript = _full_transcript()
    client = _ScriptClient(transcript)
    _grade(transcript, client=client)
    assert client.calls == [{"prompt": build_grade_prompt(SOLVE),
                             "images": [IMAGE], "image_format": "png"}]
    client2 = _ScriptClient(transcript)
    _grade(transcript, client=client2, image_format="jpeg")
    assert client2.calls[0]["image_format"] == "jpeg"


def test_grade_solution_parse_failure_one_call_no_grader():
    client = _ScriptClient("not json at all")
    grader = _recording_grader()
    with pytest.raises(GradeError, match="not valid json|no json"):
        grade_solution(SOLVE, IMAGE, client, grader)
    assert len(client.calls) == 1                    # 出网已发生
    assert grader.calls == []                        # 判定器未被调用


def test_grade_solution_answer_grader_must_return_bool():
    grader = _recording_grader(lambda item, answer: "yes")
    with pytest.raises(GradeError, match="bool"):
        _grade(_full_transcript(), grader=grader)


def test_grade_solution_exceptions_propagate_unwrapped():
    class _BoomClient:
        def vision(self, prompt, images, image_format="png"):
            raise RuntimeError("llm down")

    with pytest.raises(RuntimeError, match="llm down"):
        grade_solution(SOLVE, IMAGE, _BoomClient(), _recording_grader())

    def boom_grader(item, answer):
        raise ValueError("grading boom")

    with pytest.raises(ValueError, match="grading boom"):
        _grade(_full_transcript(), grader=boom_grader)


def test_grade_solution_guards_fail_before_any_network_call():
    client = _ScriptClient(_full_transcript())
    bad_calls = [
        lambda: grade_solution(SOLVE, IMAGE, _NoVision(), _recording_grader()),
        lambda: grade_solution(SOLVE, IMAGE, client, None),            # V2
        lambda: grade_solution(SOLVE, IMAGE, client, "grader"),
        lambda: grade_solution(SOLVE, b"", client, _recording_grader()),   # V3
        lambda: grade_solution(SOLVE, None, client, _recording_grader()),
        lambda: grade_solution(SOLVE, "img", client, _recording_grader()),
        lambda: grade_solution(SOLVE, IMAGE, client, _recording_grader(),
                               image_format="bmp"),                    # V4
        lambda: grade_solution(SOLVE, IMAGE, client, _recording_grader(),
                               image_format="PNG"),                    # 大小写敏感
        lambda: grade_solution(SOLVE, IMAGE, client, _recording_grader(),
                               min_confidence=-0.1),                   # V5
        lambda: grade_solution(SOLVE, IMAGE, client, _recording_grader(),
                               min_confidence=1.5),
        lambda: grade_solution(SOLVE, IMAGE, client, _recording_grader(),
                               min_confidence=True),
        lambda: grade_solution(SOLVE, IMAGE, client, _recording_grader(),
                               min_confidence="0.9"),
        lambda: grade_solution(SOLVE, IMAGE, client, _recording_grader(),
                               min_confidence=float("nan")),
        lambda: grade_solution(CHOICE, IMAGE, client, _recording_grader()),  # V6 非 solve
        lambda: grade_solution(_DuckItem(None, "solve", "题", "x=1", "x=1"),
                               IMAGE, client, _recording_grader()),    # id 缺失
        lambda: grade_solution(_DuckItem("s", "solve", "  ", "x=1", "x=1"),
                               IMAGE, client, _recording_grader()),    # stem 空白
        lambda: grade_solution(_DuckItem("s", "solve", "题", "  ", "x=1"),
                               IMAGE, client, _recording_grader()),    # answer 空白
        lambda: grade_solution(_DuckItem("s", "solve", "题", "x=1", ""),
                               IMAGE, client, _recording_grader()),    # solution 空步骤
        lambda: grade_solution(_DuckItem("s", "solve", "题", "x=1", " \n "),
                               IMAGE, client, _recording_grader()),
        lambda: grade_solution(_DuckItem("s", "solve", "题", "x=1", 42),
                               IMAGE, client, _recording_grader()),    # solution 非 str
    ]
    for bad in bad_calls:
        with pytest.raises(GradeError):
            bad()
    assert client.calls == []  # 全部守卫失败零出网


# ---------- I7 闭环互斥 ----------

def test_confirm_review_human_path_and_gate():
    s, _, _ = _grade(_transcript([(t, 1.0) for t in FULL_STEPS[:2]]))  # 部分配对
    assert s.needs_review is True
    assert confirm_review(s, True) == Response("s1", True, "x=150", None)
    assert confirm_review(s, False) == Response("s1", False, "x=150", None)
    assert confirm_review(s, True, learner_answer="x=150（抄错行）") == \
        Response("s1", True, "x=150（抄错行）", None)
    assert confirm_review(s, True, response_ms=1234) == \
        Response("s1", True, "x=150", 1234)
    with pytest.raises(GradeError):                  # 非 bool correct
        confirm_review(s, 1)
    clean, _, _ = _grade(_full_transcript())
    with pytest.raises(GradeError):                  # 干净建议不许走人审路
        confirm_review(clean, True)


def test_suggest_response_gate_on_needs_review():
    s, _, _ = _grade(_transcript([(t, 1.0) for t in FULL_STEPS[:1]]))
    with pytest.raises(GradeError, match="review"):
        suggest_response(s)
    with pytest.raises(GradeError):                  # needs_review 非 bool 的鸭子对象
        suggest_response(object())


# ---------- I8 确定性 ----------

def test_grade_solution_determinism_same_input_same_output():
    a, _, _ = _grade(_full_transcript())
    b, _, _ = _grade(_full_transcript())
    assert a.to_dict() == b.to_dict()
    assert a == b
    c, _, _ = _grade(_transcript([(FULL_STEPS[0], 0.3)], final=None))
    d, _, _ = _grade(_transcript([(FULL_STEPS[0], 0.3)], final=None))
    assert c.to_dict() == d.to_dict()


def test_grade_solution_inputs_not_mutated():
    solution_snapshot = SOLVE.solution
    image_snapshot = bytes(IMAGE)
    _grade(_full_transcript())
    assert SOLVE.solution == solution_snapshot
    assert IMAGE == image_snapshot
    assert REF_STEPS == solution_steps(SOLVE.solution)


# ---------- I9 跨模块锁定（测试内 import 对方模块） ----------

def test_cross_module_grading_grade_as_answer_grader():
    from xuexing.grading import grade

    # 闭式一：方程解字面判对/判错
    s, _, _ = _grade(_full_transcript(), grader=grade)
    assert s.needs_review is False
    s, _, _ = _grade(_full_transcript(), grader=grade,
                     client=_ScriptClient(_transcript(
                         [(t, 1.0) for t in FULL_STEPS], final="x=45")))
    assert s.final_answer_correct is False
    assert s.reasons == [REASON_CONTRADICTION]
    # 闭式二：数值等值（1/2+1/3=5/6；10/12 ≡ 5/6，parse_numeric 现算核实）
    frac_transcript = _transcript([("1/2+1/3", 1.0), ("=3/6+2/6", 1.0),
                                   ("=5/6", 1.0)], final="10/12")
    s, _, _ = _grade(frac_transcript, item=SOLVE_FRAC, grader=grade)
    assert s.needs_review is False and s.final_answer_correct is True
    assert suggest_response(s) == Response("s3", True, "10/12", None)
    # 闭式三：空白 final_answer 交 grading.grade(item, None) 判 False（不伪造）；
    # 步骤全配对却缺答案 -> 转写自相矛盾 -> final_answer_missing + contradiction
    s, _, _ = _grade(_transcript([(t, 1.0) for t in FULL_STEPS], final=None),
                     grader=grade)
    assert s.final_answer_correct is False
    assert s.reasons == [REASON_FINAL_ANSWER_MISSING, REASON_CONTRADICTION]


def test_end_to_end_mm_client_mock_transport_wire_prompt():
    """端到端（I9）：MMClient+MockTransport 全 mock 跑通，线上 prompt 逐字节等于
    build_grade_prompt，转写 JSON 被结构化解析并进入冻结规则给分。"""
    from xuexing.mm_client import ENDPOINTS, MMClient, MockTransport

    reply = json.dumps(
        {"choices": [{"message": {"content": _full_transcript()}}]},
        ensure_ascii=False).encode("utf-8")
    mt = MockTransport(replies={"chat": (200, reply)})
    client = MMClient(mt, env=dict(_SENTINEL_ENV),
                      resolve=lambda host: ["93.184.216.34"])
    s = grade_solution(SOLVE, IMAGE, client, _recording_grader())
    assert len(mt.calls) == 1
    call = mt.calls[0]
    assert call["url"] == ENDPOINTS["chat"]
    payload = json.loads(call["body"])
    assert payload["messages"][0]["content"][0] == {
        "type": "text", "text": build_grade_prompt(SOLVE)}
    assert s.suggested_points == 4 and s.needs_review is False
    assert suggest_response(s) == Response("s1", True, "x=150", None)


# ---------- 数据形状 ----------

def test_step_score_and_suggestion_to_dict_shapes():
    from xuexing.mm_grade import GradeSuggestion, StepScore

    step = StepScore(index=1, ref_text="列方程：3x + 30 = 480。",
                     student_text="列方程：3x+30=480。", awarded=1)
    assert step.to_dict() == {"index": 1, "ref_text": "列方程：3x + 30 = 480。",
                              "student_text": "列方程：3x+30=480。", "awarded": 1}
    s, _, _ = _grade(_transcript([(FULL_STEPS[0], 0.5)], final=None))
    data = s.to_dict()
    assert set(data) == {"item_id", "steps", "max_points", "suggested_points",
                         "final_answer", "final_answer_correct", "flagged_steps",
                         "reasons", "needs_review"}
    assert data["item_id"] == "s1" and data["max_points"] == 4
    assert data["suggested_points"] == 0
    assert data["final_answer"] is None and data["final_answer_correct"] is False
    assert data["flagged_steps"] == [FULL_STEPS[0]]
    assert data["reasons"] == [REASON_LOW_CONFIDENCE, REASON_FINAL_ANSWER_MISSING,
                               REASON_PARTIAL_MATCH]
    assert data["needs_review"] is True
    assert len(data["steps"]) == 4 and data["steps"][0]["awarded"] == 0
    assert json.dumps(data, ensure_ascii=False)      # JSON 可序列化
