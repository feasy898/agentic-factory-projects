"""G6 业务门禁: 字幕文本逐字等于模板数据(硬性); 可选 TTS→ASR 回转 CER≤5%。

编辑距离自实现, 不引 jiwer。
"""

from __future__ import annotations

from . import make_gate


def edit_distance(a: str, b: str) -> int:
    """Levenshtein 距离 (两行 DP)。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    """字符错误率 = 编辑距离 / len(ref); ref 为空时按 hyp 是否为空判 0 或 1。"""
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def check_subtitle_exact(expected: list[str], actual: list[str]) -> tuple[bool, dict]:
    """逐字比对(有序)。返回 (passed, detail)。"""
    diffs = []
    n = max(len(expected), len(actual))
    for i in range(n):
        e = expected[i] if i < len(expected) else None
        a = actual[i] if i < len(actual) else None
        if e != a:
            diffs.append({"index": i, "expected": e, "actual": a})
    return (not diffs), {"diffs": diffs, "expected_count": len(expected), "actual_count": len(actual)}


def g6_business(
    expected_subtitles: list[str],
    actual_subtitles: list[str],
    asr_fn=None,
    expected_narration: str | None = None,
    cer_max: float = 0.05,
) -> dict:
    """G6: 字幕逐字比对(必做, 硬性) + 可选 TTS→ASR 回转 CER。

    asr_fn()->str 可注入; 未提供或抛异常 → 跳过 CER 子判据并记录 (SPECS §2)。
    """
    sub_ok, sub_detail = check_subtitle_exact(expected_subtitles, actual_subtitles)

    cer_val = None
    asr_skipped = True
    asr_error = None
    hyp = None
    if asr_fn is not None and expected_narration is not None:
        try:
            hyp = asr_fn()
            cer_val = cer(expected_narration, hyp)
            asr_skipped = False
        except Exception as e:  # noqa: BLE001
            asr_error = str(e)

    cer_ok = True if cer_val is None else cer_val <= cer_max
    passed = sub_ok and cer_ok

    score = 1.0 if passed else 0.0
    if not passed and sub_ok and cer_val is not None:
        score = round(max(0.0, 1.0 - cer_val), 4)
    return make_gate(
        "G6", passed, score,
        subtitle_exact=sub_ok, subtitle_detail=sub_detail,
        cer=cer_val, cer_max=cer_max, asr_skipped=asr_skipped,
        asr_error=asr_error, asr_hyp=hyp,
        expected_narration=expected_narration,
    )
