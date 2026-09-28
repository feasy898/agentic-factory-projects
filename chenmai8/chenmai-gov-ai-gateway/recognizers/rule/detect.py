"""规则层 v0：身份证 + 手机号 + 密级词（T0.4 链路最小集）。

范围说明：本文件是规则层的**骨架实现**，只覆盖非流式链路打通所需的三类；
全类别正则/校验位/白名单/性能优化由规则层任务（M2）在同一模块内扩展，
``detect(text) -> list[Finding]`` 接口形状不变。

v0 行为口径（有意取舍，规则层任务复核）：
- ID_CARD：GB11643 位权校验通过 → confidence=1.0；仅格式命中（校验位不符）
  仍输出 Finding（confidence=0.5，安全优先：宁可多脱敏不可漏脱敏）；
- PHONE_MOBILE：1[3-9] 号段 11 位，容许空格/连字符分隔与 +86/86 前缀；无校验位，
  格式命中即 confidence=1.0；与身份证 span 重叠时弃用（证件号优先）；
- CLASSIFICATION_MARK：词表逐词匹配（config/classification_terms.txt，可配置），
  action_hint=BLOCK_FLAG → 路由拦截。
"""
from __future__ import annotations

import re
from pathlib import Path

from common.config import REPO_ROOT
from masking.normalize import normalize_value
from recognizers.models import EntityClass, Finding

#: 词表默认路径（可配置词表，开发指令 §6 M2）
CLASSIFICATION_TERMS_PATH = REPO_ROOT / "config" / "classification_terms.txt"

#: 词表文件缺失时的兜底词（与 config/classification_terms.txt v0 内容一致）
DEFAULT_CLASSIFICATION_TERMS: tuple[str, ...] = (
    "机密★", "秘密★", "绝密", "内部资料", "注意保密", "不得外传",
)

#: 身份证：GB11643 18 位（世纪码 18/19/20，月/日合法域），前后不贴数字/X
_ID_CARD_RE = re.compile(
    r"(?<![0-9Xx])"
    r"[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]"
    r"(?![0-9Xx])"
)

#: 手机号：可选 +86/86 前缀 + 1[3-9] 起始 11 位，容许空格/连字符分隔
_PHONE_RE = re.compile(
    r"(?<![0-9])(?:\+?86[-\s]?)?1[3-9](?:[-\s]?\d){9}(?![0-9])"
)

#: GB11643 校验：位权与校验码表
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CODES = "10X98765432"

_TERMS_CACHE: tuple[str, ...] | None = None


def id_card_checksum_ok(number: str) -> bool:
    """GB11643 校验位验证（输入为 18 位归一化身份证号）。"""
    if len(number) != 18:
        return False
    total = sum(int(ch) * w for ch, w in zip(number[:17], _ID_WEIGHTS, strict=True))
    return _ID_CHECK_CODES[total % 11] == number[17].upper()


def load_classification_terms(path: str | Path | None = None) -> tuple[str, ...]:
    """加载密级词表：一行一词、# 注释；文件缺失/为空时回退内置词表。"""
    p = Path(path) if path else CLASSIFICATION_TERMS_PATH
    terms: list[str] = []
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                terms.append(line)
    if not terms:
        terms = list(DEFAULT_CLASSIFICATION_TERMS)
    return tuple(terms)


def get_classification_terms() -> tuple[str, ...]:
    """进程级缓存的词表（首次调用加载 config/classification_terms.txt）。"""
    global _TERMS_CACHE
    if _TERMS_CACHE is None:
        _TERMS_CACHE = load_classification_terms()
    return _TERMS_CACHE


def set_classification_terms(terms: tuple[str, ...]) -> None:
    """测试/运维显式注入词表（绕过文件）。"""
    global _TERMS_CACHE
    _TERMS_CACHE = tuple(terms) or DEFAULT_CLASSIFICATION_TERMS


def _overlaps(start: int, end: int, taken: list[tuple[int, int]]) -> bool:
    return any(start < t_end and t_start < end for t_start, t_end in taken)


def detect(text: str, *, terms: tuple[str, ...] | None = None) -> list[Finding]:
    """规则 v0 检测：返回按 start 升序的 Finding 列表（fid 为空串，由调用方按请求编号）。"""
    findings: list[Finding] = []
    taken: list[tuple[int, int]] = []

    for match in _ID_CARD_RE.finditer(text):
        raw = match.group(0)
        normalized = normalize_value(EntityClass.ID_CARD, raw)
        confidence = 1.0 if id_card_checksum_ok(normalized) else 0.5
        findings.append(Finding(
            fid="", type=EntityClass.ID_CARD, layer="rule",
            start=match.start(), end=match.end(), raw=raw, normalized=normalized,
            confidence=confidence, whitelisted=False, action_hint="MASK",
        ))
        taken.append((match.start(), match.end()))

    for match in _PHONE_RE.finditer(text):
        if _overlaps(match.start(), match.end(), taken):
            continue  # 与身份证 span 重叠：证件号优先
        raw = match.group(0)
        findings.append(Finding(
            fid="", type=EntityClass.PHONE_MOBILE, layer="rule",
            start=match.start(), end=match.end(), raw=raw,
            normalized=normalize_value(EntityClass.PHONE_MOBILE, raw),
            confidence=1.0, whitelisted=False, action_hint="MASK",
        ))

    for term in (terms if terms is not None else get_classification_terms()):
        if not term:
            continue
        pos = 0
        while (hit := text.find(term, pos)) != -1:
            findings.append(Finding(
                fid="", type=EntityClass.CLASSIFICATION_MARK, layer="rule",
                start=hit, end=hit + len(term), raw=term, normalized=term,
                confidence=1.0, whitelisted=False, action_hint="BLOCK_FLAG",
            ))
            pos = hit + len(term)

    findings.sort(key=lambda f: (f.start, f.end, f.type.value))
    return findings
