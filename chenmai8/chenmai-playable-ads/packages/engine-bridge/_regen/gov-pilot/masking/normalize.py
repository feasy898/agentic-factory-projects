"""M3 号码归一化（masking-normalize spec §5.3.2，冻结规则）。

原则：同一实体的不同写法 → 同 normalized → 同占位符。规则逐条对照
specs/masking-normalize.md（重生成实现，未读原实现源码）：

1. ``to_halfwidth``：0xFF01–0xFF5E ↔ 0x21–0x7E 全角 ASCII 可打印区 + 全角空格
   0x3000 → 半角空格；``str.translate`` 一次映射，1:1 长度不变。
2. ``normalize_digits``：全角→半角后删除全部分隔符（半角/全角空格、\\t\\r\\n、
   ``-``、Unicode 连字符类 ‐‑‒–—―、全角减号 －、``.``、全角点 ．、中文间隔点 ·）。
3. ``normalize_value`` 逐类别：
   - PHONE_MOBILE：公共归一后去 +86/86 前缀（仅当去掉后剩 11 位且第 3 位为 1、
     第 4 位 ∈ 3-9，防误删普通数字；``+`` 号随前缀一并剥离）；
   - ID_CARD：公共归一后末位 x→X；
   - PLATE：公共归一后大写（间隔点 · 已被公共归一删除）；
   - DATE_BIRTH：仅半角化（不做分隔符删除）后匹配数字版式
     ``YYYY<年/./-/、>M<月/./-/、>D[日]`` → ``YYYY-MM-DD`` 补零；无法解析原样返回；
   - PHONE_LANDLINE / BANK_CARD / USCC：公共归一；
   - EMAIL / IP / SECRET_KEY 及其余词面类：仅全角→半角 + 首尾去空白；
   - PERSON / ADDRESS：不做串级归一化（原样，仅精确匹配去重取向）。

spec 缺口备注：日期分隔式样 spec 列举 ``年/./-/、``，冻结测试另含 ``1990/3/7``，
故数字版式分隔集含 ``/``（本文件如此实现）。
"""
from __future__ import annotations

import re

from recognizers.models import EntityClass

_PLACEHOLDER_OPEN = "\u3014"   # 〔
_PLACEHOLDER_CLOSE = "\u3015"  # 〕
_MIDDLE_DOT = "\u00b7"         # ·（占位符分隔与中文间隔点同字）

# 全角 ASCII 可打印区（0xFF01–0xFF5E）→ 半角（0x21–0x7E），外加全角空格 → 半角空格
_HALFWIDTH_TABLE = {
    code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)
}
_HALFWIDTH_TABLE[0x3000] = 0x20  # 全角空格

# 数字串类内部分隔符（masking-normalize §2，冻结字符集）
_SEPARATORS = (
    " "        # 半角空格
    "\u3000"   # 全角空格
    "\t\r\n"   # 制表/回车/换行
    "-"        # 连字符
    "\u2010\u2011\u2012\u2013\u2014\u2015"  # ‐ ‑ ‒ – — ―
    "\uff0d"   # － 全角减号
    "."        # 半角点
    "\uff0e"   # ．全角点
    + _MIDDLE_DOT  # · 中文间隔点
)
_SEPARATOR_TABLE = {ord(ch): None for ch in _SEPARATORS}

# DATE_BIRTH 数字版式：YYYY<年/./-/、>M<月/./-/、>D[日]（fullmatch；spec 缺 /，测试钉死）
_DATE_PARTS_RE = re.compile(r"(\d{4})[年./\-、](\d{1,2})[月./\-、](\d{1,2})日?")


def to_halfwidth(text: str) -> str:
    """全角 → 半角（1:1 长度不变，识别层影子扫描依赖此性质）。"""
    return text.translate(_HALFWIDTH_TABLE)


def normalize_digits(text: str) -> str:
    """数字串类公共归一：全角→半角 + 删除全部分隔符。"""
    return to_halfwidth(text).translate(_SEPARATOR_TABLE)


def _strip_mobile_country_prefix(normalized: str) -> str:
    """去 +86/86 前缀：仅当去掉后剩 11 位且第 3 位为 1、第 4 位 ∈ 3-9（含 + 剥离）。"""
    body = normalized[1:] if normalized.startswith("+") else normalized
    if len(body) == 13 and body[:2] == "86" and body[2] == "1" and body[3] in "3456789":
        return body[2:]
    return normalized


def normalize_value(etype: EntityClass | str, raw: str) -> str:
    """按类别把写法变体归一为 canonical 值（规则冻结，改动须回归 m3/m2/m8）。"""
    cls = etype if isinstance(etype, EntityClass) else EntityClass(str(etype))

    if cls in (EntityClass.PERSON, EntityClass.ADDRESS):
        return raw  # 不做串级归一化（原样），仅精确匹配去重

    if cls is EntityClass.PHONE_MOBILE:
        return _strip_mobile_country_prefix(normalize_digits(raw))

    if cls is EntityClass.ID_CARD:
        digits = normalize_digits(raw)
        return digits[:-1] + digits[-1].upper() if digits else digits  # 末位 x→X

    if cls is EntityClass.PLATE:
        return normalize_digits(raw).upper()  # · 已被公共归一删除

    if cls is EntityClass.DATE_BIRTH:
        half = to_halfwidth(raw)
        matched = _DATE_PARTS_RE.fullmatch(half)
        if matched is None:
            return half  # 无法解析原样返回（半角化后）
        year, month, day = matched.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    if cls in (EntityClass.PHONE_LANDLINE, EntityClass.BANK_CARD, EntityClass.USCC):
        return normalize_digits(raw)

    # EMAIL / IP / SECRET_KEY 及词面类：仅全角→半角 + 首尾去空白（保守安全）
    return to_halfwidth(raw).strip()


__all__ = [
    "normalize_digits",
    "normalize_value",
    "to_halfwidth",
]
