"""归一化（gov2 盲实现，依据 docs/assets/specs/masking-normalize.md §1-§3）。

原则：同一实体的不同写法 → 同 normalized → 同占位符。
"""
from __future__ import annotations

import re

from recognizers.models import EntityClass

# 全角 ASCII 可打印区（0xFF01–0xFF5E ↔ 0x21–0x7E，94 字）+ 全角空格 0x3000 → 半角空格。
# translate 一次映射 1:1，长度不变。
_FW_ASCII = {0xFF01 + i: chr(0x21 + i) for i in range(94)}
_FW_SPACE = {0x3000: " "}
_TRANSLATE = {**_FW_ASCII, **_FW_SPACE}

#: 数字串类实体（spec §2：公共归一 = 半角化 + 删分隔符）
_DIGIT_TYPES = frozenset({
    EntityClass.ID_CARD,
    EntityClass.PHONE_MOBILE,
    EntityClass.PHONE_LANDLINE,
    EntityClass.BANK_CARD,
    EntityClass.USCC,
})

#: 分隔符字符集（spec §2 逐字面删除；不含 + —— 加号只在 PHONE_MOBILE 前缀剥离中处理）
_SEPARATORS = " \t\r\n-‐‑‒–—―－.．·"

#: DATE_BIRTH 数字版式：(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})日? 的 fullmatch
#: （spec §3：字符类四选一「年、.、/、-」；顿号不是候选分隔符）
_DATE_PARTS_RE = re.compile(r"(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})日?")


def to_halfwidth(text: str) -> str:
    """全角数字/常见全角符号 → 半角（其余字符原样）。"""
    return text.translate(_TRANSLATE)


def normalize_digits(raw: str) -> str:
    """数字串公共归一：全角→半角、删除内部空格/连字符/点号/间隔点等分隔符。"""
    return to_halfwidth(raw).translate(str.maketrans("", "", _SEPARATORS))


def normalize_value(entity_type: EntityClass, raw: str) -> str:
    """按类别归一化（spec masking-normalize §3 表）。

    - PHONE_MOBILE：公共归一后去 +86/86 前缀——先剥单个前导 +，仅当 body 13 位、
      以 86 开头、第 3 位为 1 且第 4 位 ∈3-9 才视为前缀返回 body[2:]；否则原样
      返回 digits（含可能残留的前导 +）；
    - ID_CARD：公共归一后末位 x→X；
    - PLATE：公共归一后大写；
    - DATE_BIRTH：半角化+去首尾空白后 fullmatch 数字版式 → YYYY-MM-DD（补零）；
      无法解析原样返回（半角化后）；
    - 其余数字串类：公共归一；其他类别：仅半角化+首尾去空白（大小写不归一）。
    """
    if entity_type is EntityClass.PHONE_MOBILE:
        digits = normalize_digits(raw)
        body = digits.removeprefix("+")
        if (len(body) == 13 and body.startswith("86")
                and body[2] == "1" and body[3] in "3456789"):
            return body[2:]
        return digits
    if entity_type is EntityClass.ID_CARD:
        digits = normalize_digits(raw)
        return digits[:-1] + "X" if digits.endswith(("x", "X")) else digits
    if entity_type is EntityClass.PLATE:
        return normalize_digits(raw).upper()
    if entity_type is EntityClass.DATE_BIRTH:
        hw = to_halfwidth(raw).strip()
        m = _DATE_PARTS_RE.fullmatch(hw)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return hw
    if entity_type in _DIGIT_TYPES:
        return normalize_digits(raw)
    return to_halfwidth(raw).strip()
