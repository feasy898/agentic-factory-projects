"""M2 规则层验收（T1.2）：全类别召回 + 白名单误报 + 难负例 + 归一化等价 + 延迟。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m2_recognizers

exit 0 = 通过。测评为 ``data/cases/rule_cases.jsonl``（T1.1 生成器产出，372 例：
每结构化类别 ≥20 正例含扰动变体 + 白名单负例 ≥40 + 密级样例 ≥20 + 难负例 ≥26）。

通过线（开发指令 §6 M2 / evals.thresholds）：
1. 规模基线：用例 ≥300、白名单负例 ≥40、含密级词用例 ≥20（生成器已保证，此处复核）；
2. 召回：ID_CARD/USCC/BANK_CARD = 100%（RECALL_STRUCTURAL，规则层内部满分要求）；
   PHONE/EMAIL/IP/PLATE/SECRET_KEY ≥99%（RECALL_PATTERN）；座机/出生日期与
   词面类（SENSITIVE_ATTR/CLASSIFICATION_MARK）同按 RECALL_PATTERN 内控；
   结构化号码整体（micro）≥99.5%（任务口径线）；
3. 白名单误报率 ≤1%（WHITELIST_FPR_MAX；whitelisted 正确标记不算误报；
   白名单负例「可命中但必须 whitelisted=true，未标记即误报」——生成器计分口径）；
4. 难负例（reject）：探测值（坏校验位/非法形状）**不得**被任何 confidence=1.0
   判定覆盖（校验位必须真实门控置信度；格式命中输出 0.5 属安全优先设计）；
5. 归一化等价（§5.3.2→§5.3.1）：每条召回匹配除 span/类型外还要求
   normalized 与期望归一化值全等（全角/分组/分隔符变体 → 同一规范值）；
6. 延迟：2000 字规则层单遍 10 次均值 < 100ms（RULE_LATENCY_MS_2000CH）。

召回分母与生成器计分口径一致：``graded 且 rule_detectable 且非 whitelisted`` 的
expected finding（人名/住址 rule_detectable=false，归 NER 层计分，不计入规则层）。
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals import thresholds as th  # noqa: E402
from recognizers.models import SENSITIVE_ATTR_SUBTYPES  # noqa: E402
from recognizers.rule.detect import (  # noqa: E402
    detect,
    get_classification_terms,
    get_sensitive_terms,
)
from recognizers.rule.whitelist import get_whitelist  # noqa: E402

RESULTS: list[tuple[bool, str]] = []
CASES_PATH = REPO_ROOT / "data" / "cases" / "rule_cases.jsonl"

#: 结构化号码类别（micro 召回与 ≥99.5% 线的口径；与 M8 生成器 STRUCTURAL_CLASSES 一致）
STRUCTURAL_CLASSES = (
    "ID_CARD", "USCC", "BANK_CARD", "PHONE_MOBILE", "PHONE_LANDLINE",
    "PLATE", "EMAIL", "IP", "SECRET_KEY", "DATE_BIRTH",
)

#: 每类别召回线（§6 M2；座机/出生日期/词面类按 RECALL_PATTERN 内控）
RECALL_LINES: dict[str, float] = {
    "ID_CARD": th.RECALL_STRUCTURAL,
    "USCC": th.RECALL_STRUCTURAL,
    "BANK_CARD": th.RECALL_STRUCTURAL,
    "PHONE_MOBILE": th.RECALL_PATTERN,
    "PHONE_LANDLINE": th.RECALL_PATTERN,
    "PLATE": th.RECALL_PATTERN,
    "EMAIL": th.RECALL_PATTERN,
    "IP": th.RECALL_PATTERN,
    "SECRET_KEY": th.RECALL_PATTERN,
    "DATE_BIRTH": th.RECALL_PATTERN,
    "SENSITIVE_ATTR": th.RECALL_PATTERN,
    "CLASSIFICATION_MARK": th.RECALL_PATTERN,
}

#: 词面类：召回匹配只要求 span 重叠（密级槽位「内部资料 注意保密」按词逐条产出）
WORD_TYPES = frozenset({"CLASSIFICATION_MARK"})


def _record(name: str, fn):
    try:
        detail = fn()
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _load_cases() -> list[dict]:
    assert CASES_PATH.exists(), f"missing: {CASES_PATH.relative_to(REPO_ROOT)}"
    cases = [json.loads(line) for line in
             CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len({c["id"] for c in cases}) == len(cases), "duplicate case ids"
    return cases


def _is_recalled(exp: dict, dets: list) -> bool:
    """expected finding 是否被召回：类型一致 + span 重叠（词面类）+ 归一化等价（值类）。"""
    for d in dets:
        if d.type.value != exp["type"]:
            continue
        if not (d.start < exp["end"] and exp["start"] < d.end):
            continue
        if exp["type"] in WORD_TYPES or d.normalized == exp["normalized"]:
            return True
    return False


# ── 1. 规模基线 ─────────────────────────────────────────────────────


def check_scale(cases: list[dict]) -> str:
    assert len(cases) >= th.RULE_CASES_MIN, f"cases {len(cases)} < {th.RULE_CASES_MIN}"
    grading = Counter(c["grading"] for c in cases)
    assert grading.get("whitelist", 0) >= th.WHITELIST_NEGATIVES_MIN, grading
    n_class = sum(1 for c in cases
                  if any(f["type"] == "CLASSIFICATION_MARK" for f in c["expected"]))
    assert n_class >= th.CLASSIFICATION_SAMPLES_MIN, n_class
    per_class = Counter(f["type"] for c in cases for f in c["expected"]
                        if f["graded"] and f["rule_detectable"] and not f["whitelisted"])
    for etype in RECALL_LINES:
        assert per_class.get(etype, 0) >= th.RULE_CASES_PER_CLASS_MIN, \
            f"{etype}: {per_class.get(etype, 0)} < {th.RULE_CASES_PER_CLASS_MIN}"
    return (f"{len(cases)} cases (detect={grading['detect']}, whitelist={grading['whitelist']}, "
            f"reject={grading['reject']}); classification cases={n_class}; "
            f"per-class graded ≥{th.RULE_CASES_PER_CLASS_MIN} ok")


# ── 2. 召回（逐类 + micro）+ 归一化等价 + span 保真 ──────────────────


def check_recall(cases: list[dict]) -> str:
    per_total: Counter[str] = Counter()
    per_hit: Counter[str] = Counter()
    struct_total = struct_hit = 0
    bad_span: list[tuple[str, str]] = []
    norm_equiv_fail: list[tuple[str, str, str, str]] = []
    ner_layer = 0
    for case in cases:
        text = case["text"]
        dets = detect(text)
        for d in dets:
            # span 保真 + fid 约定：任何一条检测违规即失败
            if text[d.start:d.end] != d.raw:
                bad_span.append((case["id"], f"{d.type.value}@{d.start}"))
            if d.fid != "":
                bad_span.append((case["id"], f"{d.type.value}:fid={d.fid!r}"))
        for exp in case["expected"]:
            if exp["graded"] and exp["rule_detectable"] is False:
                ner_layer += 1
            if not (exp["graded"] and exp["rule_detectable"]) or exp["whitelisted"]:
                continue
            per_total[exp["type"]] += 1
            if exp["type"] in STRUCTURAL_CLASSES:
                struct_total += 1
            if _is_recalled(exp, dets):
                per_hit[exp["type"]] += 1
                if exp["type"] in STRUCTURAL_CLASSES:
                    struct_hit += 1
            elif exp["type"] not in WORD_TYPES:
                # 归一化等价专项：span/类型命中但 normalized 不等 → 记录差异
                for d in dets:
                    if d.type.value == exp["type"] and d.start < exp["end"] and exp["start"] < d.end:
                        norm_equiv_fail.append(
                            (case["id"], exp["type"], exp["normalized"], d.normalized))
                        break

    lines = [f"{'class':<20}{'recall':>8}{'graded':>8}{'line':>7}"]
    for etype in sorted(RECALL_LINES):
        total, hit = per_total[etype], per_hit[etype]
        recall = (hit / total) if total else 1.0
        lines.append(f"{etype:<20}{recall:>8.4f}{total:>8}{RECALL_LINES[etype]:>7.2f}")
        assert total > 0, f"{etype}: no graded cases"
        assert recall >= RECALL_LINES[etype], (
            f"{etype} recall {recall:.4f} < {RECALL_LINES[etype]} ({hit}/{total})")
    struct_micro = struct_hit / struct_total if struct_total else 1.0
    assert struct_micro >= 0.995, f"structural micro recall {struct_micro:.4f} < 0.995"
    assert not bad_span, f"span/fid violations: {bad_span[:5]}"
    assert not norm_equiv_fail, f"normalization equivalence fails: {norm_equiv_fail[:5]}"
    print("── 召回明细（graded & rule_detectable & 非白名单分母）────────────")
    for line in lines:
        print(f"  {line}")
    print(f"  {'MICRO(结构化号码)':<20}{struct_micro:>8.4f}{struct_total:>8}")
    return (f"all class lines met; structural micro={struct_micro:.4f} "
            f"({struct_hit}/{struct_total}); spans ok; normalized equivalence ok; "
            f"NER-layer sample={ner_layer} (不计规则层分母)")


# ── 3. 白名单误报 ───────────────────────────────────────────────────


def check_whitelist(cases: list[dict]) -> str:
    wl_cases = [c for c in cases if c["grading"] == "whitelist"]
    total_dets = fp = 0
    wl_slots = wl_hits = 0
    fp_samples: list[tuple[str, str, str]] = []
    for case in wl_cases:
        dets = detect(case["text"])
        total_dets += len(dets)
        for d in dets:
            if not d.whitelisted:
                fp += 1
                fp_samples.append((case["id"], d.type.value, case["text"][d.start:d.end]))
        for exp in case["expected"]:
            if exp["whitelisted"]:
                wl_slots += 1
                wl_hits += sum(
                    1 for d in dets if d.type.value == exp["type"]
                    and d.whitelisted and d.start < exp["end"] and exp["start"] < d.end)
    fpr = fp / total_dets if total_dets else 0.0
    assert fpr <= th.WHITELIST_FPR_MAX, (
        f"whitelist FPR {fpr:.4f} > {th.WHITELIST_FPR_MAX}: {fp_samples[:5]}")
    # 白名单实体本身应被识别并正确标记（信息性下限：≥80%，杜绝「检测器干脆全瞎」假阳性通过）
    assert wl_slots == 0 or wl_hits / wl_slots >= 0.8, (
        f"whitelisted slot detection {wl_hits}/{wl_slots} too low")
    return (f"FPR={fp}/{total_dets}={fpr:.4f} ≤{th.WHITELIST_FPR_MAX}; "
            f"whitelisted slots detected {wl_hits}/{wl_slots}")


# ── 4. 难负例（reject）──────────────────────────────────────────────


def check_reject(cases: list[dict]) -> str:
    probes = [(c, c["reject_probe"]) for c in cases if "reject_probe" in c]
    assert len(probes) >= th.GENERATOR_REJECT_NEGATIVES_MIN, len(probes)
    confident: list[tuple[str, str, str]] = []
    zero_hit = 0
    for case, probe in probes:
        text = case["text"]
        # 探测值 span：文本中定位（生成器保证探测值原样在文中）
        pos = text.find(probe["raw"])
        assert pos != -1, f"{case['id']}: probe value not found in text"
        end = pos + len(probe["raw"])
        dets = [d for d in detect(text)
                if d.start < end and pos < d.end]
        if not dets:
            zero_hit += 1
        for d in dets:
            if d.confidence >= 1.0:
                confident.append((case["id"], d.type.value, d.raw))
                break
    assert not confident, (
        f"reject probes got confidence=1.0 detections: {confident[:5]}")
    return (f"{len(probes)} probes: none covered by a confidence=1.0 finding; "
            f"{zero_hit} probes produced no finding at all")


# ── 5. 延迟（2000 字 × 10 次均值）──────────────────────────────────


def _latency_text(cases: list[dict]) -> str:
    parts: list[str] = []
    size = 0
    for case in cases:
        if case["grading"] != "detect":
            continue
        parts.append(case["text"])
        size += len(case["text"]) + 1
        if size >= 2000:
            break
    return "\n".join(parts)[:2000]


def check_latency(cases: list[dict]) -> str:
    text = _latency_text(cases)
    assert len(text) == 2000, f"latency text {len(text)} != 2000 chars"
    detect(text)  # 预热（首次含词表加载）
    samples = []
    for _ in range(10):
        t0 = time.perf_counter()
        out = detect(text)
        samples.append((time.perf_counter() - t0) * 1000)
        assert out is not None
    mean_ms = sum(samples) / len(samples)
    assert mean_ms < th.RULE_LATENCY_MS_2000CH, (
        f"latency mean {mean_ms:.2f}ms >= {th.RULE_LATENCY_MS_2000CH}ms")
    return (f"2000ch detect ×10 mean {mean_ms:.2f}ms "
            f"(max {max(samples):.2f}ms) < {th.RULE_LATENCY_MS_2000CH}ms")


# ── 6. 白名单配置与词表加载自检（配置面在位）──────────────────────────


def check_config_surface() -> str:
    terms = get_sensitive_terms()
    subtypes = {s for s, _ in terms}
    assert subtypes <= set(SENSITIVE_ATTR_SUBTYPES), \
        f"subtypes out of contract range: {subtypes - set(SENSITIVE_ATTR_SUBTYPES)}"
    assert len(terms) >= 15, f"sensitive terms {len(terms)} < 15"
    wl = get_whitelist()
    assert "12345" in wl.hotline and "110" in wl.hotline, "hotline whitelist incomplete"
    assert wl.unit_prefixes, "unit landline prefixes empty"
    assert wl.public_titles, "public titles empty"
    assert get_classification_terms(), "classification terms empty"
    return (f"sensitive terms={len(terms)} ({len(subtypes)} subtypes); hotline="
            f"{len(wl.hotline)}; unit prefixes={len(wl.unit_prefixes)}; "
            f"public titles={len(wl.public_titles)}")


def main() -> int:
    cases = _load_cases()
    _record("config-surface(词表/白名单配置在位)", check_config_surface)
    _record("case-scale(≥300/白名单≥40/密级≥20/类别≥20)", lambda: check_scale(cases))
    _record("recall(逐类线+micro≥99.5%+span保真+归一化等价)", lambda: check_recall(cases))
    _record("whitelist(误报率≤1%+白名单实体标记率)", lambda: check_whitelist(cases))
    _record("reject(难负例零满置信度误判)", lambda: check_reject(cases))
    _record("latency(2000字×10均值<100ms)", lambda: check_latency(cases))

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M2 RECOGNIZERS: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
