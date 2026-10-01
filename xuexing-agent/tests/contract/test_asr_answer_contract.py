"""契约：asr_answer —— 口述作答（语音 → ASR 转写 → 确定性抽取 → grading 衔接）。

夹具自封闭、**全 mock 零网络**：ASR 用脚本化 MockASR（记录调用、可注入异常/回写），
MMClient 走 MockTransport，判分优先用录制 grader、跨模块锁定时用真
grading.grade_to_response。全部抽取/判分条款为手算可复核的闭式值，数值等值用
grading.parse_numeric 独立复核。跨模块锁定（mm_client.DEFAULT_FILENAME 缺省/
MODEL_ASR/ENDPOINTS、grading 判分语义）在测试内 import 对方模块断言，被测模块间
零 import。
"""
import inspect
import json

import pytest

from xuexing.asr_answer import (
    ASRError,
    ASR_VERSION,
    DEFAULT_FILENAME,
    EDGE_CHARS,
    HEAD_FILLERS,
    SPOKEN_OPERATORS,
    asr_answer,
    clean_transcript,
    extract_answer,
    spoken_to_math,
)


# 哨兵环境：非机密占位值，仅供 MMClient 的 mock 传输层读取，不对应任何真实凭据
_SENTINEL_ENV = {"XX_LLM_API_KEY": "sentinel-token-1"}
_SENTINEL_RESOLVE = lambda host: ["93.184.216.34"]  # noqa: E731


# ---------- 自封闭小夹具 ----------

class _DuckItem:
    def __init__(self, item_id, item_type, stem, answer, options=None):
        self.id = item_id
        self.item_type = item_type
        self.stem = stem
        self.answer = answer
        self.options = list(options or [])


class MockASR:
    """脚本化 mock ASR：记录每次调用，回脚本化转写（或抛注入异常）。零网络。"""

    def __init__(self, transcript="模拟转写", error=None):
        self.transcript = transcript
        self.error = error
        self.calls = []

    def asr(self, audio, *, filename):
        self.calls.append({"audio": bytes(audio), "filename": filename})
        if self.error is not None:
            raise self.error
        return self.transcript


class _NoASR:
    pass


class RecGrader:
    """录制 grader：记录 (item, answer) 调用，返回固定哨兵（验证返回值原样透传）。"""

    def __init__(self, ret="GRADED"):
        self.ret = ret
        self.calls = []

    def __call__(self, item, answer):
        self.calls.append((item, answer))
        return self.ret


AUDIO = b"AUDIO-BYTES-01"
FILL_NEG2 = _DuckItem("f1", "fill", "比 -3 大的最小整数是多少", answer="-2")
FILL_UNIT = _DuckItem("f2", "fill", "水箱容积", answer="2.5升")
CHOICE_AB = _DuckItem("c1", "choice", "计算 1+1 等于多少？", answer="B",
                      options=["A. 2", "B. 3"])
SOLVE_X3 = _DuckItem("s1", "solve", "解方程：2x + 1 = 7", answer="x=3")


# ---------- I1 常量冻结 + 跨模块锁定 ----------

def test_frozen_constants():
    assert ASR_VERSION == "1"
    assert DEFAULT_FILENAME == "audio.wav"
    assert issubclass(ASRError, ValueError)
    # 上下缘字符集（fold 后形态）：引号/标点/语气词
    assert set(EDGE_CHARS) == set("\"'“”‘’。，、…·.,;:!?()"
                                  "嗯呃唉哦噢喔吧了呢啦咯嘛呀哈啊")
    # 句首引导语词表：值与长度非增序都冻结（序决定剥离优先级）
    assert HEAD_FILLERS == (
        "我认为答案是", "我觉得答案是", "我的答案是", "所以答案是",
        "我选的是", "答案等于", "答案是", "选的是",
        "答案", "选择", "所以", "我选", "等于", "就是",
        "答", "得", "选",
    )
    assert [len(f) for f in HEAD_FILLERS] == \
        sorted((len(f) for f in HEAD_FILLERS), reverse=True)
    # 口语算符表：值与序冻结（前缀最长优先）
    assert SPOKEN_OPERATORS == (
        ("等于", "="), ("乘以", "*"), ("除以", "/"),
        ("乘", "*"), ("加", "+"), ("减", "-"),
    )


def test_default_filename_matches_mm_client_signature():
    from xuexing.mm_client import MMClient

    default = inspect.signature(MMClient.asr).parameters["filename"].default
    assert DEFAULT_FILENAME == default == "audio.wav"


# ---------- clean_transcript（折叠 / 上下缘 / 句首引导语） ----------

def test_clean_transcript_fold_and_edges():
    assert clean_transcript("Ｂ。") == "B"                    # 全角字母+句号折叠
    assert clean_transcript("（Ａ）") == "A"                  # 全角括号折叠后剥离
    assert clean_transcript("３．５。") == "3.5"              # 全角数字/句点折叠
    assert clean_transcript("“负二”") == "负二"               # 弯引号两端剥离
    assert clean_transcript("五。。") == "五"                  # 连续尾部标点
    assert clean_transcript("嗯，答案是三。吧") == "三"        # 语气词+标点+引导语
    assert clean_transcript("  十二  ") == "十二"              # 首尾空白
    assert clean_transcript("　五　") == "五"                  # U+3000 折叠为空格再剥


def test_clean_transcript_head_fillers_table():
    rows = [
        ("我认为答案是八", "八"), ("我觉得答案是B", "B"),
        ("我的答案是负二", "负二"), ("所以答案是五", "五"),
        ("我选的是C", "C"), ("答案等于四十", "四十"),
        ("答案是三点五", "三点五"), ("选的是A", "A"),
        ("答案40", "40"), ("选择B", "B"), ("所以十", "十"),
        ("我选D", "D"), ("等于七", "七"), ("就是二分之一", "二分之一"),
        ("答：-2", "-2"), ("得六", "六"), ("选B了", "B"),
    ]
    for raw, want in rows:
        assert clean_transcript(raw) == want, raw


def test_clean_transcript_preserves_core_content():
    assert clean_transcript("x=3") == "x=3"          # 方程整串保留
    assert clean_transcript("x等于3") == "x等于3"     # 「等于」不在句首不动
    assert clean_transcript("-2") == "-2"            # 负号不在上下缘集合
    assert clean_transcript("0.5") == "0.5"
    assert clean_transcript("1 1/2") == "1 1/2"      # 内部空白不折叠


# ---------- spoken_to_math（口语数字文法，全部闭式手算复核） ----------

def test_spoken_to_math_integers():
    assert spoken_to_math("十二") == "12"
    assert spoken_to_math("二十三") == "23"
    assert spoken_to_math("一百零五") == "105"
    assert spoken_to_math("两千零三十") == "2030"
    assert spoken_to_math("十") == "10"              # 缺系数按 1
    assert spoken_to_math("零") == "0"
    assert spoken_to_math("两") == "2"
    assert spoken_to_math("一万零一十") == "10010"
    assert spoken_to_math("3分之2") == "2/3"          # ASCII 数字入文法
    assert spoken_to_math("103") == "103"            # ASCII 逐位累积


def test_spoken_to_math_decimals_and_fractions():
    assert spoken_to_math("三点一四") == "3.14"
    assert spoken_to_math("零点五") == "0.5"
    assert spoken_to_math("二点五") == "2.5"
    assert spoken_to_math("零点零五") == "0.05"
    assert spoken_to_math("三分之二") == "2/3"
    assert spoken_to_math("十分之一") == "1/10"
    assert spoken_to_math("二十分之十三") == "13/20"
    assert spoken_to_math("一又二分之一") == "1 1/2"
    assert spoken_to_math("二又三分之一") == "2 1/3"


def test_spoken_to_math_percent_negative():
    assert spoken_to_math("百分之五十") == "50%"
    assert spoken_to_math("百分之百") == "100%"
    assert spoken_to_math("百分之十二点五") == "12.5%"
    assert spoken_to_math("负二") == "-2"
    assert spoken_to_math("负零点五") == "-0.5"
    assert spoken_to_math("负三分之二") == "-2/3"
    assert spoken_to_math("负百分之五十") == "-50%"


def test_spoken_to_math_operators_and_passthrough():
    assert spoken_to_math("x等于3") == "x=3"          # 「等于」句中 -> =
    assert spoken_to_math("三加五") == "3+5"          # 不求值：转记号不猜得数
    assert spoken_to_math("10减4") == "10-4"
    assert spoken_to_math("二乘以三") == "2*3"
    assert spoken_to_math("2乘3") == "2*3"
    assert spoken_to_math("六除以二") == "6/2"
    assert spoken_to_math("B") == "B"
    assert spoken_to_math("5平方米") == "5平方米"      # 单位词透传（判分器单位门）
    assert spoken_to_math("负") == "负"               # 孤立记号透传
    assert spoken_to_math("点") == "点"
    assert spoken_to_math("万") == "万"               # 孤立大段单位透传
    assert spoken_to_math("负负二") == "负-2"          # 「负」恰修饰一次


# ---------- extract_answer（管线闭式 + 诚实性） ----------

def test_extract_answer_pipeline_closed_forms():
    rows = [
        ("答案是负二", "-2"), ("嗯，答案是三。吧", "3"),
        ("我认为答案是八", "8"), ("我的答案是负二", "-2"),
        ("所以答案是五", "5"), ("答案等于四十", "40"),
        ("答案是三点五", "3.5"), ("所以十", "10"), ("等于七", "7"),
        ("就是二分之一", "1/2"), ("得六", "6"), ("两点五升", "2.5升"),
        ("十二点五厘米", "12.5厘米"), ("我选的是B", "B"),
        ("x等于3", "x=3"), ("选B", "B"),
    ]
    for raw, want in rows:
        assert extract_answer(raw) == want, raw


def test_extract_answer_none_when_no_evidence():
    assert extract_answer("   ") is None
    assert extract_answer("") is None
    assert extract_answer("嗯吧呢") is None           # 纯语气词
    assert extract_answer("答案") is None             # 纯引导语
    # 部分可抽取：机械转换 + 字面比对交给判分器，不清洗句子结构、不猜测
    assert extract_answer("负三分之二的绝对值") == "-2/3的绝对值"


def test_extraction_is_item_independent():
    # I2 抽取只依赖转写文本，签名与行为均与 item 无关（不偷看标答）：
    # 同一转写无论最终判哪道题，抽取结果恒同。
    assert extract_answer("答案是负二") == extract_answer("答案是负二") == "-2"
    assert spoken_to_math(clean_transcript("答案是三点五")) == "3.5"


def test_non_str_inputs_raise_asr_error():
    for fn in (clean_transcript, spoken_to_math, extract_answer):
        for bad in (None, 42, b"audio-bytes", ["二"]):
            with pytest.raises(ASRError):
                fn(bad)


# ---------- asr_answer（I3 出网纪律 + I4 失败纪律） ----------

def test_asr_answer_happy_path_exact_call_shape():
    client = MockASR(transcript="答案是负二")
    grader = RecGrader()
    ret = asr_answer(AUDIO, FILL_NEG2, client, grader)
    assert ret == "GRADED"                             # grader 返回值原样透传
    assert len(client.calls) == 1                      # 恰好一次出网
    assert client.calls[0] == {"audio": AUDIO, "filename": "audio.wav"}
    assert grader.calls == [(FILL_NEG2, "-2")]         # 抽取结果交判分器


def test_asr_answer_filename_passthrough():
    client = MockASR(transcript="B")
    grader = RecGrader()
    asr_answer(AUDIO, CHOICE_AB, client, grader, filename="answer.mp3")
    assert client.calls[0]["filename"] == "answer.mp3"


def test_asr_answer_blank_transcript_hands_none():
    client = MockASR(transcript="   ")
    grader = RecGrader()
    asr_answer(AUDIO, FILL_NEG2, client, grader)
    assert grader.calls == [(FILL_NEG2, None)]         # 不伪造作答


def test_asr_answer_guards_zero_calls():
    client = MockASR()
    grader = RecGrader()
    bad_calls = [
        lambda: asr_answer(AUDIO, FILL_NEG2, _NoASR(), grader),
        lambda: asr_answer(AUDIO, FILL_NEG2, object(), grader),
        lambda: asr_answer(AUDIO, FILL_NEG2, client, None),
        lambda: asr_answer(AUDIO, FILL_NEG2, client, 5),
        lambda: asr_answer(AUDIO, FILL_NEG2, client, "grader"),
        lambda: asr_answer(None, FILL_NEG2, client, grader),
        lambda: asr_answer(b"", FILL_NEG2, client, grader),
        lambda: asr_answer(12, FILL_NEG2, client, grader),
        lambda: asr_answer("audio", FILL_NEG2, client, grader),
        lambda: asr_answer(AUDIO, FILL_NEG2, client, grader, filename=""),
        lambda: asr_answer(AUDIO, FILL_NEG2, client, grader, filename="   "),
        lambda: asr_answer(AUDIO, FILL_NEG2, client, grader, filename=5),
    ]
    for bad in bad_calls:
        with pytest.raises(ASRError):
            bad()
    assert client.calls == []                          # 全部守卫失败零出网
    assert grader.calls == []


def test_asr_answer_non_str_transcript():
    client = MockASR(transcript=42)
    grader = RecGrader()
    with pytest.raises(ASRError):
        asr_answer(AUDIO, FILL_NEG2, client, grader)
    assert len(client.calls) == 1                      # 已出网一次
    assert grader.calls == []                          # 但判分器未被调用


def test_asr_answer_client_exception_propagates():
    client = MockASR(error=RuntimeError("asr down"))
    grader = RecGrader()
    with pytest.raises(RuntimeError, match="asr down"):
        asr_answer(AUDIO, FILL_NEG2, client, grader)   # 原样传播不包装
    assert grader.calls == []


def test_asr_answer_deterministic_and_inputs_unmutated():
    audio_snapshot = bytes(AUDIO)
    results = []
    for _ in range(2):
        client = MockASR(transcript="答案是负二")
        grader = RecGrader()
        results.append((list(client.calls), list(grader.calls),
                        asr_answer(AUDIO, FILL_NEG2, client, grader)))
    assert results[0] == results[1]                    # 同输入同输出
    assert AUDIO == audio_snapshot                     # 入参不被修改


# ---------- I5 判分衔接（跨模块锁定 grading 语义） ----------

def test_numeric_equivalence_with_grading_parse_numeric():
    import math

    from xuexing.grading import parse_numeric

    rows = [
        ("负二", -2.0), ("三点五", 3.5), ("一又二分之一", 1.5),
        ("百分之五十", 0.5), ("三分之二", 2 / 3), ("零点零五", 0.05),
        ("一万零一十", 10010.0), ("二又三分之一", 2 + 1 / 3),
    ]
    for raw, want in rows:
        got = parse_numeric(extract_answer("答案是" + raw))
        assert got is not None and math.isclose(
            got, want, rel_tol=1e-9, abs_tol=1e-12), raw


def test_grade_fill_cross_module_closed_forms():
    from xuexing.grading import grade_fill

    true_rows = [
        (FILL_NEG2, "负二"), (FILL_NEG2, "嗯，答案是负二。吧"),
        (_DuckItem("u1", "fill", "s", answer="3.5"), "三点五"),
        (_DuckItem("u2", "fill", "s", answer="50%"), "百分之五十"),
        (FILL_UNIT, "两点五升"),
        (_DuckItem("u3", "fill", "s", answer="12.5厘米"), "十二点五厘米"),
    ]
    for item, raw in true_rows:
        assert grade_fill(item, extract_answer(raw)) is True, raw
    assert grade_fill(FILL_NEG2, extract_answer("二")) is False    # 2 ≠ -2
    assert grade_fill(FILL_NEG2, extract_answer("负三分之二的绝对值")) is False


def test_grade_choice_and_solve_cross_module():
    from xuexing.grading import grade, grade_choice

    assert grade_choice(CHOICE_AB, extract_answer("选B")) is True
    assert grade_choice(CHOICE_AB, extract_answer("我选的是A")) is False
    assert grade_choice(CHOICE_AB, extract_answer("选择Ｂ")) is True   # 全角折叠同判
    assert grade_choice(CHOICE_AB, extract_answer("答案是C")) is False
    assert grade(SOLVE_X3, extract_answer("x等于3")) is True           # x=3 字面直配
    # 冻结规则的可预期代价：「等于3」句首引导语剥离后只剩「3」，与字面标答 x=3
    # 不匹配判 False——诚实判错，不猜测方程结构
    assert grade(SOLVE_X3, extract_answer("等于3")) is False


def test_asr_answer_with_grading_grade_to_response():
    from xuexing.grading import grade_to_response

    resp = asr_answer(AUDIO, FILL_NEG2, MockASR("答案是负二"),
                      grade_to_response)
    assert (resp.item_id, resp.correct, resp.learner_answer) == ("f1", True, "-2")
    resp2 = asr_answer(AUDIO, CHOICE_AB, MockASR("选择Ｂ"), grade_to_response)
    assert (resp2.item_id, resp2.correct, resp2.learner_answer) == ("c1", True, "B")
    # 空白转写 ≡ grader(item, None)：与 grading 未作答语义逐字段一致
    resp3 = asr_answer(AUDIO, FILL_NEG2, MockASR("   "), grade_to_response)
    assert resp3.learner_answer is None and resp3.correct is False


# ---------- I7 端到端（MMClient + MockTransport 全 mock） ----------

def test_end_to_end_mm_client_mock_transport():
    from xuexing.mm_client import ENDPOINTS, MODEL_ASR, MMClient, MockTransport
    from xuexing.grading import grade_to_response

    reply = json.dumps({"text": "答案是负二"}, ensure_ascii=False).encode("utf-8")
    mt = MockTransport(replies={"asr": (200, reply)})
    client = MMClient(mt, env=dict(_SENTINEL_ENV), resolve=_SENTINEL_RESOLVE)
    resp = asr_answer(AUDIO, FILL_NEG2, client, grade_to_response)
    assert len(mt.calls) == 1                          # 恰好一次出网
    call = mt.calls[0]
    assert call["url"] == ENDPOINTS["asr"]
    assert call["headers"]["Authorization"] == "Bearer sentinel-token-1"
    assert call["content_type"].startswith("multipart/form-data; boundary=")
    body = call["body"]
    assert b'name="model"' in body and MODEL_ASR.encode("utf-8") in body
    assert b'filename="audio.wav"' in body             # 缺省文件名跨模块一致
    assert AUDIO in body                               # 音频字节原样入 multipart
    assert (resp.item_id, resp.correct, resp.learner_answer) == ("f1", True, "-2")
    # 同输入两次请求体逐字节相同（请求构造确定性）
    mt2 = MockTransport(replies={"asr": (200, reply)})
    client2 = MMClient(mt2, env=dict(_SENTINEL_ENV), resolve=_SENTINEL_RESOLVE)
    asr_answer(AUDIO, FILL_NEG2, client2, grade_to_response)
    assert mt2.calls[0]["body"] == body
