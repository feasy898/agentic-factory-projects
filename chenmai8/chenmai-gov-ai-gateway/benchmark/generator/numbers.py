"""自研号码生成器：带正确校验位的政务场景结构化号码（M8 · T1.1）。

全部函数为纯函数：随机来源只经调用方传入的 :class:`random.Random`。
校验位算法独立于生成器实现，供 evals 侧复核（属性：全体位加权和 ≡ 0 模基）。

- 身份证：GB 11643 校验位（权重 7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2；模 11 映射 10X98765432）；
- 统一社会信用代码：GB 32174 校验位（字符集 31 进制、权重 1,3,9,27,19,26,16,17,20,29,25,13,8,24,10,30,28）；
- 银行卡：Luhn 校验位；
- 手机/座机/车牌/邮箱/IPv4/密钥串/出生日期：格式合规即可（无校验位）。
"""
from __future__ import annotations

import random
import string
from datetime import date

from benchmark.generator.geo import CHENGMAI_CODE, HAINAN_COUNTIES

# ── 身份证（GB 11643）──────────────────────────────────────────────

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_MAP = "10X98765432"


def id_card_check_digit(first17: str) -> str:
    """GB 11643 校验位：Σ(位×权重) mod 11 → 映射表。"""
    total = sum(int(ch) * w for ch, w in zip(first17, _ID_WEIGHTS, strict=True))
    return _ID_CHECK_MAP[total % 11]


def gen_id_card(rng: random.Random, region: str, birth: date, seq: int | None = None) -> str:
    """按区划码 + 出生日期生成 18 位身份证（顺序码奇男偶女不做强约束）。"""
    if seq is None:
        seq = rng.randrange(1, 999)
    body = f"{region}{birth:%Y%m%d}{seq:03d}"
    return body + id_card_check_digit(body)


def id_card_is_valid(idnum: str) -> bool:
    """GB 11643 校验（含末位；X 记 10）：全体 18 位加权和 ≡ 1（mod 11）。"""
    if len(idnum) != 18:
        return False
    if not all("0" <= c <= "9" for c in idnum[:17]):
        return False
    tail = idnum[17]
    value = 10 if tail in ("X", "x") else (int(tail) if tail.isdigit() else -1)
    if value < 0:
        return False
    total = sum(d * w for d, w in zip((int(c) for c in idnum[:17]), _ID_WEIGHTS, strict=True))
    return (total + value) % 11 == 1


def pick_region(rng: random.Random, chengmai_ratio: float = 0.45) -> tuple[str, str]:
    """抽县级区划：约四成落在澄迈县，其余散布海南省其他市县。返回 (代码, 名称)。"""
    if rng.random() < chengmai_ratio:
        return CHENGMAI_CODE, "澄迈县"
    return rng.choice(HAINAN_COUNTIES)


# ── 统一社会信用代码（GB 32174）───────────────────────────────────

_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"  # 无 I/O/S/V/Z
_USCC_INDEX = {ch: i for i, ch in enumerate(_USCC_CHARS)}
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)

#: 登记管理部门 + 机构类别常用前缀（第 1-2 位）
USCC_KIND_PREFIXES: tuple[str, ...] = (
    "91",  # 工商 · 企业
    "92",  # 工商 · 个体工商户
    "93",  # 工商 · 农民专业合作社
    "52",  # 民政 · 民办非企业单位
    "51",  # 民政 · 社会团体
    "11",  # 机构编制 · 机关
    "12",  # 机构编制 · 事业单位
)


def uscc_check_char(first17: str) -> str:
    """GB 32174 校验位（第 18 位）：基 31，C=(31-Σ mod 31) mod 31。"""
    total = sum(_USCC_INDEX[ch] * w for ch, w in zip(first17, _USCC_WEIGHTS, strict=True))
    return _USCC_CHARS[(31 - total % 31) % 31]


def gen_uscc(rng: random.Random, region: str) -> str:
    """生成 18 位统一社会信用代码：部门类别 + 区划 + 9 位主体标识码 + 校验位。"""
    prefix = rng.choice(USCC_KIND_PREFIXES)
    body = "".join(rng.choice(_USCC_CHARS) for _ in range(9))
    first17 = prefix + region + body
    return first17 + uscc_check_char(first17)


def uscc_is_valid(code: str) -> bool:
    """全体 18 位（第 18 位权重 1）加权和 ≡ 0（mod 31）。"""
    if len(code) != 18 or any(ch not in _USCC_INDEX for ch in code):
        return False
    total = sum(_USCC_INDEX[ch] * w for ch, w in
                zip(code[:17], _USCC_WEIGHTS, strict=True)) + _USCC_INDEX[code[17]]
    return total % 31 == 0


# ── 银行卡（Luhn）─────────────────────────────────────────────────

#: 常见发卡行 BIN（6-8 位，合成用）
BANK_BINS: tuple[tuple[str, str], ...] = (
    ("622202", "工商银行"), ("621700", "建设银行"), ("622848", "农业银行"),
    ("621661", "邮政储蓄银行"), ("622588", "招商银行"), ("622260", "交通银行"),
    ("621785", "中国银行"), ("625908", "建设银行信用卡"),
)


def luhn_check_digit(digits: str) -> str:
    """Luhn 校验位：右起隔位加倍、超 9 减 9，补位使总和 ≡ 0（mod 10）。"""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:  # digits 的末位是校验位左邻，属加倍位
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def gen_bank_card(rng: random.Random) -> tuple[str, str]:
    """生成过 Luhn 的卡号，返回 (卡号, 发卡行名)。长度 16 或 19。"""
    prefix, bank = rng.choice(BANK_BINS)
    length = rng.choice((16, 16, 19))
    body = prefix + "".join(rng.choice(string.digits) for _ in range(length - len(prefix) - 1))
    return body + luhn_check_digit(body), bank


def bank_card_is_valid(num: str) -> bool:
    """Luhn 全卡号校验（含末位）。"""
    if not num.isdigit() or len(num) < 12:
        return False
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ── 电话 / 车牌 / 邮箱 / IP / 密钥 / 日期 ─────────────────────────

_MOBILE_PREFIXES = (
    "133", "135", "136", "137", "138", "139", "147", "150", "151", "152",
    "155", "157", "158", "159", "166", "170", "176", "177", "178",
    "180", "181", "182", "185", "186", "187", "188", "189", "191", "193", "195", "198", "199",
)

_PLATE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_PLATE_CITY = ("A", "B", "C", "D", "E", "F")  # 琼A（海口/澄迈属地）… 琼F

_EMAIL_DOMAINS = ("163.com", "126.com", "qq.com", "sina.com", "188.com", "gov.cn.local")

_SECRET_SHAPES = ("sk_hex", "akia", "pem", "long_token")


def gen_mobile(rng: random.Random) -> str:
    return rng.choice(_MOBILE_PREFIXES) + "".join(rng.choice(string.digits) for _ in range(8))


def gen_landline(rng: random.Random, *, unit: bool = False, prefix: str = "0898") -> str:
    """座机：0898（全省并网）+ 8 位本地号；unit=True 时落单位总机演示号段。"""
    if unit:
        return prefix + "".join(rng.choice(string.digits) for _ in range(4))
    return prefix + rng.choice("2345678") + "".join(rng.choice(string.digits) for _ in range(7))


def gen_plate(rng: random.Random, *, nev_ratio: float = 0.25) -> str:
    """车牌：琼A-琼F；新能源 6 位（D/F 开头小/大型车电牌）。"""
    city = "A" if rng.random() < 0.6 else rng.choice(_PLATE_CITY)
    if rng.random() < nev_ratio:
        series = rng.choice("DF") + "".join(
            rng.choice(string.digits + _PLATE_LETTERS) for _ in range(5))
    else:
        series = (rng.choice(_PLATE_LETTERS)
                  + "".join(rng.choice(string.digits + _PLATE_LETTERS) for _ in range(4)))
    return f"琼{city}{series}"


def gen_email(rng: random.Random) -> str:
    local = "".join(rng.choice(string.ascii_lowercase + string.digits)
                    for _ in range(rng.randrange(6, 12)))
    return f"{local}@{rng.choice(_EMAIL_DOMAINS)}"


def gen_ipv4(rng: random.Random) -> str:
    kind = rng.random()
    if kind < 0.4:
        o1 = rng.choice((10, 172, 192))
        o2 = rng.randrange(16, 32) if o1 == 172 else (168 if o1 == 192 else rng.randrange(1, 255))
    else:
        o1 = rng.choice((36, 58, 113, 139, 183, 220))
        o2 = rng.randrange(1, 255)
    return f"{o1}.{o2}.{rng.randrange(1, 255)}.{rng.randrange(1, 255)}"


def gen_secret_key(rng: random.Random) -> str:
    """密钥串四种形态：sk- 前缀、AKIA 访问键、PEM 块、长熵令牌。"""
    shape = rng.choice(_SECRET_SHAPES)
    hexset = string.hexdigits.lower()
    if shape == "sk_hex":
        return "sk-" + "".join(rng.choice(hexset) for _ in range(48))
    if shape == "akia":
        return "AKIA" + "".join(rng.choice(string.ascii_uppercase + string.digits)
                                for _ in range(16))
    if shape == "pem":
        b64 = string.ascii_letters + string.digits + "+/="
        lines = ["".join(rng.choice(b64) for _ in range(64)) for _ in range(2)]
        return "-----BEGIN RSA PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END RSA PRIVATE KEY-----"
    return "".join(rng.choice(hexset) for _ in range(40))


def gen_birth(rng: random.Random, *, lo: int = 1955, hi: int = 2008) -> date:
    """出生日期：成人年龄段。"""
    return date(rng.randrange(lo, hi + 1), rng.randrange(1, 13), rng.randrange(1, 29))


def gen_amount(rng: random.Random, *, lo: int = 300, hi: int = 90000) -> str:
    """金额字符串（元，两位小数，千分位逗号）。"""
    return f"{rng.randrange(lo, hi):,}.00"
