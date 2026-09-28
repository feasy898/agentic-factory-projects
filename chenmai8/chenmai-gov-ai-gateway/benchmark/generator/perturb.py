"""扰动器（M8 · T1.1）：模拟真实脏数据的七类扰动。

分级（cases 装配口径）：
- 良性扰动（保持可检测，归一化后回同一值）：``fullwidth`` / ``digit_spacing`` /
  ``separator_variant`` / ``newline_blank`` / ``ocr_context``（仅作用于上下文文字）；
- 破坏性扰动（值本身被破坏，finding 标 graded=false，不计入召回分母）：
  ``partial_mask`` / ``ocr_digits``。

全部函数纯函数，随机只经调用方传入的 :class:`random.Random`。
"""
from __future__ import annotations

import random
import string

# 全角映射：数字/字母/常见半角符号（X → Ｘ，@ → ＠，- → －，. → ．）
_FW_EXTRA = {"-": "－", ".": "．", "@": "＠", "/": "／", "(": "（", ")": "）", ":": "："}
_FULLWIDTH = str.maketrans(
    {**{c: chr(ord(c) + 0xFEE0) for c in string.digits + string.ascii_letters}, **_FW_EXTRA},
)

#: OCR 上下文形近字对（仅作用于非槽位文字；错字语义仍在公文常见范围内）
OCR_CONTEXT_PAIRS: tuple[tuple[str, str], ...] = (
    ("未", "末"), ("己", "已"), ("日", "曰"), ("人", "入"), ("土", "士"),
    ("千", "干"), ("治", "冶"), ("拨", "抜"), ("住", "往"), ("县", "県"),
    ("撤", "徹"), ("查", "杏"),
)

#: OCR 数字形近（值内破坏性扰动）
OCR_DIGIT_MAP: dict[str, str] = {
    "0": "O", "1": "l", "2": "Z", "3": "E", "4": "A",
    "5": "S", "6": "b", "7": "T", "8": "B", "9": "g",
}


def to_fullwidth(text: str) -> str:
    """数字/字母/常见符号 → 全角。"""
    return text.translate(_FULLWIDTH)


def insert_digit_groups(value: str, rng: random.Random, kind: str) -> str:
    """按号码类型插入空格分组（长度改变，调用方据实重算 span）。"""
    if kind in {"ID_CARD", "USCC"} and len(value) == 18:
        cuts = (6, 14) if rng.random() < 0.6 else (8,)
    elif kind == "PHONE_MOBILE":
        cuts = (3, 7) if rng.random() < 0.7 else (7,)
    elif kind == "BANK_CARD":
        step = 4
        cuts = tuple(range(step, len(value), step))
    elif kind == "PHONE_LANDLINE":
        cuts = (4,)
    else:
        cuts = ()
    return " ".join(value[i:j] for i, j in
                    zip((0, *cuts), (*cuts, len(value)), strict=True))


def apply_separator_variant(value: str, rng: random.Random, kind: str) -> str:
    """分隔符变体（良性）：手机 +86 前缀、座机空格、车牌间隔点、银行卡连字符。"""
    if kind == "PHONE_MOBILE":
        return "+86" + value
    if kind == "PHONE_LANDLINE":
        return value.replace("-", " ")
    if kind == "PLATE":
        return value[:2] + "·" + value[2:]
    if kind == "BANK_CARD":
        return "-".join(value[i:i + 4] for i in range(0, len(value), 4))
    return value


def partial_mask(value: str, rng: random.Random) -> str:
    """部分打码（破坏性）：保留首 2-4 与尾 2-4，中段换 `*`（至少 3 个）。"""
    head = rng.randrange(3, 5)
    tail = rng.randrange(2, 5)
    if len(value) <= head + tail + 3:
        head, tail = 2, 2
    middle = max(3, len(value) - head - tail)
    return value[:head] + "*" * middle + value[len(value) - tail:]


def ocr_digits_mangle(value: str, rng: random.Random) -> str:
    """OCR 数字形近（破坏性）：替换 1-2 个数字位。"""
    positions = [i for i, ch in enumerate(value) if ch in OCR_DIGIT_MAP]
    if not positions:
        return value
    out = list(value)
    for pos in rng.sample(positions, k=min(len(positions), rng.randrange(1, 3))):
        out[pos] = OCR_DIGIT_MAP[out[pos]]
    return "".join(out)


def ocr_context_mangle(text: str, rng: random.Random, *, max_swaps: int = 2) -> str:
    """上下文 OCR 形近字（良性，仅作用于非槽位文字）：0-2 处替换。"""
    swaps = rng.randrange(0, max_swaps + 1)
    out = text
    for _ in range(swaps):
        src, dst = rng.choice(OCR_CONTEXT_PAIRS)
        hits = [i for i in range(len(out)) if out.startswith(src, i)]
        if not hits:
            continue
        pos = rng.choice(hits)
        out = out[:pos] + dst + out[pos + 1:]
    return out


def blank_a_newline(text: str, rng: random.Random) -> str:
    """空行扰动：随机把某个换行加倍（整体 span 后移，行内内容不变）。"""
    positions = [i for i, ch in enumerate(text) if ch == "\n"]
    if not positions:
        return text
    pos = rng.choice(positions)
    return text[:pos] + "\n" + text[pos:]
