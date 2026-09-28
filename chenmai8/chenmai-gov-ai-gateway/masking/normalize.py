"""归一化（开发指令 §5.3.2，冻结规则；v0 覆盖身份证/手机号，其余类别随规则层任务补全）。

原则：同一实体的不同写法（全角/空格/分隔符/前缀）归一到同一字符串，
从而在占位符算法中得到同一占位符（§5.3.1 归一化等价）。
"""
from __future__ import annotations

from recognizers.models import EntityClass

# 全角数字 ０-９ → 0-9；全角空格/常见全角符号在翻译表中一并处理
_FW_DIGITS = {0xFF10 + i: str(i) for i in range(10)}
_FW_SPACE = {0x3000: " ", 0xFF0D: "-", 0xFF0E: ".", 0xFF03: "#"}  # － ． ＃
_TRANSLATE = {**_FW_DIGITS, **_FW_SPACE}

#: 数字串类实体：删内部空格/连字符/点号/间隔点等分隔符
_DIGIT_TYPES = frozenset({
    EntityClass.ID_CARD,
    EntityClass.PHONE_MOBILE,
    EntityClass.PHONE_LANDLINE,
    EntityClass.BANK_CARD,
    EntityClass.USCC,
})

#: 间隔点/连字符/空格等分隔符字符集（半角+全角+中文间隔点）
_SEPARATORS = " \t\r\n-‐‑‒–—―－.．·"


def to_halfwidth(text: str) -> str:
    """全角数字/常见全角符号 → 半角（其余字符原样）。"""
    return text.translate(_TRANSLATE)


def normalize_digits(raw: str) -> str:
    """数字串归一：全角→半角、删除内部空格/连字符/点号/全角空格（§5.3.2 第 1 条）。"""
    return to_halfwidth(raw).translate(str.maketrans("", "", _SEPARATORS))


def normalize_value(entity_type: EntityClass, raw: str) -> str:
    """按类别归一化（§5.3.2；v0 实装：ID_CARD / PHONE_MOBILE / PLATE / 数字串类）。

    - PHONE_MOBILE：去 +86/86 前缀（仅当剩余部分为 11 位 1[3-9] 号段时才视为前缀）；
    - ID_CARD：末位 x→X；
    - PLATE：去间隔点 + 大写；
    - 其余数字串类：normalize_digits；其他类型：仅做全角→半角与首尾去空白，
      不做串级归一化（与 §5.3.2 对 PERSON/ADDRESS 的取向一致，保守安全）。
    """
    if entity_type is EntityClass.PHONE_MOBILE:
        digits = normalize_digits(raw)
        body = digits[1:] if digits.startswith("+") else digits
        # +86/86 前缀：仅当去掉后剩余 11 位且 1[3-9] 起始才视为前缀（避免误删普通数字）
        if (len(body) == 13 and body.startswith("86")
                and body[2] == "1" and body[3] in "3456789"):
            return body[2:]
        return digits
    if entity_type is EntityClass.ID_CARD:
        digits = normalize_digits(raw)
        return digits[:-1] + "X" if digits.endswith(("x", "X")) else digits
    if entity_type is EntityClass.PLATE:
        return normalize_digits(raw).upper()
    if entity_type in _DIGIT_TYPES:
        return normalize_digits(raw)
    return to_halfwidth(raw).strip()
