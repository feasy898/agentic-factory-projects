"""rule_cases 评测集装配（M8 · T1.1）：模板 × 扰动 × 期望 findings → JSONL 行。

计分口径（与包 docstring 一致）：
- 召回分母 = graded 且 rule_detectable 且非 whitelisted 的 expected finding；
- 白名单负例：可命中但必须 whitelisted=true（未标记即误报）；
- 难负例（reject）：expected 恒空，探测值记入 ``reject_probe``。

产出计划固定（勿改动配额顺序，否则 seed 对齐失效）：14 类政务文书 300 条 +
白名单负例 46 条 + 难负例 26 条 = 372 条。
"""
from __future__ import annotations

import random
from typing import Any

from benchmark.generator import perturb as pert
from benchmark.generator import templates as tpl
from benchmark.generator.personas import Personas
from masking.normalize import normalize_value
from recognizers.models import EntityClass

#: 14 类政务文书模板 × 配额（合计 300）
DOC_TEMPLATE_PLAN: tuple[tuple[str, int], ...] = (
    ("low_income_publicity", 26),
    ("petition_transfer", 24),
    ("administrative_penalty", 24),
    ("medical_reimburse", 22),
    ("disability_subsidy", 22),
    ("community_correction", 20),
    ("cadre_assessment", 22),
    ("talent_publicity", 20),
    ("business_registration", 20),
    ("security_incident_report", 20),
    ("meeting_minutes", 20),
    ("procurement_notice", 20),
    ("hotline_workorder", 24),
    ("key_personnel_visit", 16),
)

#: 白名单负例小模板 × 配额（合计 46）
WHITELIST_PLAN: tuple[tuple[str, int], ...] = (
    ("wl_hotline", 10),
    ("wl_emergency", 10),
    ("wl_doc_number", 12),
    ("wl_unit_landline", 10),
    ("wl_title_only", 4),
)

#: 难负例小模板 × 配额（合计 26）
REJECT_PLAN: tuple[tuple[str, int], ...] = (
    ("r_bad_id", 8),
    ("r_bad_bank", 6),
    ("r_bad_uscc", 4),
    ("r_bad_phone_len", 4),
    ("r_bad_ip", 4),
)

#: 良性扰动候选（按类别；空 = 保持干净写法）
_BENIGN_BY_TYPE: dict[str, tuple[str, ...]] = {
    "ID_CARD": ("fullwidth", "digit_spacing"),
    "USCC": ("fullwidth", "digit_spacing"),
    "BANK_CARD": ("fullwidth", "digit_spacing", "separator"),
    "PHONE_MOBILE": ("fullwidth", "digit_spacing", "separator"),
    "PHONE_LANDLINE": ("fullwidth", "digit_spacing", "separator"),
    "PLATE": ("fullwidth", "separator"),
    "IP": ("fullwidth",),
    "DATE_BIRTH": ("fullwidth",),
    "EMAIL": (),
    "SECRET_KEY": (),
}

#: 允许破坏性扰动（部分打码/OCR 数字形近）的类别
_DESTRUCTIBLE = frozenset({
    "ID_CARD", "USCC", "BANK_CARD", "PHONE_MOBILE", "PHONE_LANDLINE", "EMAIL",
})

_CONF_1 = frozenset({"ID_CARD", "USCC", "BANK_CARD"})

# ── §5.3.2 完整口径的规范化（生成器侧目标值）────────────────────────
# masking.normalize 为 v0（仅全角数字，字母映射待 M3 补全），USCC/PLATE/EMAIL
# 的全角字母会残留；本数据集的 normalized 记**归一化目标值**，故在此实现完整规则。
# evals.m8_generator 侧按同规则独立实现并逐条复核（双实现交叉验证）。
_FW_FULL = {0xFF01 + i: chr(0x21 + i) for i in range(94)}
_FW_FULL[0x3000] = " "
_SEPARATORS = " \t\r\n-‐‑‒–—―－.．·"
_DIGIT_CLASSES = frozenset({"USCC", "BANK_CARD", "PHONE_LANDLINE"})


def _canonical(etype: str, value: str) -> str:
    hw = value.translate(_FW_FULL)
    if etype == "ID_CARD":
        d = "".join(ch for ch in hw if ch not in _SEPARATORS)
        return d[:-1] + "X" if d.endswith(("x", "X")) else d
    if etype == "PHONE_MOBILE":
        d = "".join(ch for ch in hw if ch not in _SEPARATORS)
        body = d[1:] if d.startswith("+") else d
        if len(body) == 13 and body.startswith("86") and body[2] == "1" and body[3] in "3456789":
            return body[2:]
        return d
    if etype == "PLATE":
        return "".join(ch for ch in hw if ch not in _SEPARATORS).upper()
    if etype in _DIGIT_CLASSES:
        return "".join(ch for ch in hw if ch not in _SEPARATORS)
    return hw.strip()  # PERSON/ADDRESS/EMAIL/IP/SECRET_KEY/词面类：不做串级归一化


def _digit_groupable(text: str) -> bool:
    return len(text) >= 11 and not any(ch in "-.@/ \n　" for ch in text)


def _perturb_slot(slot: tpl.Slot, rng: random.Random) -> tuple[str, list[str]]:
    """对单槽位施加扰动，返回 (扰动后文本, 扰动种类)。"""
    text, kinds = slot.value, []
    benign = _BENIGN_BY_TYPE.get(slot.etype, ())
    roll = rng.random()
    if roll < 0.32 and benign:
        kind = rng.choice(benign)
        if kind == "fullwidth":
            text, kinds = pert.to_fullwidth(text), ["fullwidth"]
        elif kind == "digit_spacing" and _digit_groupable(text):
            spaced = pert.insert_digit_groups(text, rng, slot.etype)
            if spaced != text:
                text, kinds = spaced, ["digit_spacing"]
        elif kind == "separator":
            variant = pert.apply_separator_variant(text, rng, slot.etype)
            if variant != text:
                text, kinds = variant, ["separator_variant"]
    elif roll < 0.42 and slot.etype in _DESTRUCTIBLE:
        if rng.random() < 0.5:
            text = pert.partial_mask(text, rng)
            kinds = ["partial_mask"]
        else:
            text = pert.ocr_digits_mangle(text, rng)
            kinds = ["ocr_digits"]
    return text, kinds


def _assemble(case_id: str, template: str, chunks: list[tpl.Chunk], rng: random.Random,
              *, grading: str, reject_probe: dict[str, str] | None = None) -> dict[str, Any]:
    """施加扰动 → 拼接 → 精确 span → 期望 findings。"""
    pert_kinds: list[str] = []
    worked: list[tuple[str, tpl.Slot | None, list[str]]] = []
    for text, slot in chunks:
        if slot is None:
            worked.append((text, None, []))
            continue
        ptext, kinds = _perturb_slot(slot, rng)
        pert_kinds += kinds
        worked.append((ptext, slot, kinds))

    # 全局扰动：空行加倍 + 上下文 OCR 形近字（仅常量块）
    newline_at = [i for i, (t, s, _) in enumerate(worked) if s is None and t == "\n"]
    if newline_at and rng.random() < 0.35:
        worked[rng.choice(newline_at)] = ("\n\n", None, [])
        pert_kinds.append("newline_blank")
    ctx_at = [i for i, (t, s, _) in enumerate(worked)
              if s is None and len(t) >= 8 and "\n" not in t]
    if ctx_at and rng.random() < 0.6:
        i = rng.choice(ctx_at)
        worked[i] = (pert.ocr_context_mangle(worked[i][0], rng), None, [])
        pert_kinds.append("ocr_context")

    findings: list[dict[str, Any]] = []
    parts: list[str] = []
    offset, fid = 0, 0
    for text, slot, kinds in worked:
        parts.append(text)
        if slot is not None:
            fid += 1
            graded = not ({"partial_mask", "ocr_digits"} & set(kinds))
            etype = EntityClass(slot.etype)
            # normalized 语义（§5.1/§5.3.2）：graded finding 记**归一化目标值**——
            # 良性扰动（全角/分组/分隔符）按契约必须归一回干净规范值；DATE_BIRTH 恒为
            # ISO。破坏性扰动（打码/OCR 错字）的 normalized 仅为 masking v0 的诚实
            # 归一输出，该 finding 不参与召回/不变式计分。
            normalized = (slot.iso if slot.etype == "DATE_BIRTH"
                          else (_canonical(slot.etype, slot.value) if graded
                                else normalize_value(etype, text)))
            findings.append({
                "fid": f"f_{fid:04d}",
                "type": slot.etype,
                "subtype": slot.subtype,
                "start": offset,
                "end": offset + len(text),
                "raw": text,
                "normalized": normalized,
                "confidence": 1.0 if slot.etype in _CONF_1 else 0.9,
                "whitelisted": slot.whitelisted,
                "action_hint": slot.action_hint,
                "graded": graded,
                "rule_detectable": slot.rule_detectable,
            })
        offset += len(text)

    case: dict[str, Any] = {
        "id": case_id,
        "template": template,
        "grading": grading,
        "text": "".join(parts),
        "perturbations": sorted(set(pert_kinds)),
        "expected": findings,
    }
    if reject_probe is not None:
        case["reject_probe"] = reject_probe
    return case


def build_cases(seed: int, config_path: str | None = None) -> list[dict[str, Any]]:
    """按固定计划产出全部评测行（同 seed → 逐字节可复现）。"""
    rng = random.Random(seed)
    kit = tpl.GenKit(rng, Personas(seed, config_path))
    cases: list[dict[str, Any]] = []
    seq = 0
    for name, count in DOC_TEMPLATE_PLAN:
        builder = tpl.DOC_TEMPLATES[name]
        for _ in range(count):
            seq += 1
            cases.append(_assemble(f"rc_{seq:04d}", name, builder(kit), rng,
                                   grading="detect"))
    for name, count in WHITELIST_PLAN:
        builder = tpl.WHITELIST_TEMPLATES[name]
        for _ in range(count):
            seq += 1
            cases.append(_assemble(f"rc_{seq:04d}", name, builder(kit), rng,
                                   grading="whitelist"))
    for name, count in REJECT_PLAN:
        builder = tpl.REJECT_TEMPLATES[name]
        for _ in range(count):
            seq += 1
            chunks, probe = builder(kit)
            cases.append(_assemble(f"rc_{seq:04d}", name, chunks, rng,
                                   grading="reject", reject_probe=probe))
    return cases


def summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """规模与分布统计（manifest 与 eval 打印共用）。"""
    grading: dict[str, int] = {}
    templates: dict[str, int] = {}
    perturbs: dict[str, int] = {}
    by_class: dict[str, int] = {}
    graded_by_class: dict[str, int] = {}
    sensitive_by_subtype: dict[str, int] = {}
    classification_cases = 0
    for case in cases:
        grading[case["grading"]] = grading.get(case["grading"], 0) + 1
        templates[case["template"]] = templates.get(case["template"], 0) + 1
        for kind in case["perturbations"]:
            perturbs[kind] = perturbs.get(kind, 0) + 1
        has_classification = False
        for f in case["expected"]:
            etype = f["type"]
            by_class[etype] = by_class.get(etype, 0) + 1
            if f["graded"] and f["rule_detectable"] and not f["whitelisted"]:
                graded_by_class[etype] = graded_by_class.get(etype, 0) + 1
            if etype == "CLASSIFICATION_MARK":
                has_classification = True
            if etype == "SENSITIVE_ATTR" and f["subtype"]:
                sensitive_by_subtype[f["subtype"]] = (
                    sensitive_by_subtype.get(f["subtype"], 0) + 1)
        classification_cases += int(has_classification)
    return {
        "cases_total": len(cases),
        "cases_by_grading": dict(sorted(grading.items())),
        "templates": dict(sorted(templates.items())),
        "perturbations": dict(sorted(perturbs.items())),
        "findings_by_class": dict(sorted(by_class.items())),
        "graded_detect_by_class": dict(sorted(graded_by_class.items())),
        "sensitive_attr_by_subtype": dict(sorted(sensitive_by_subtype.items())),
        "whitelist_cases": grading.get("whitelist", 0),
        "reject_cases": grading.get("reject", 0),
        "classification_cases": classification_cases,
    }
