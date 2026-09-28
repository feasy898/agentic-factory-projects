"""规则层识别器（M2 全类别）：正则 + 校验位 + 词表 + 白名单（开发指令 §6 M2）。

类别面（§5.1.1 规则层可产出）：

- 结构化号码：ID_CARD（GB11643 校验位）/ USCC（GB32174）/ BANK_CARD（Luhn）/
  PHONE_MOBILE（1[3-9] 号段，容 +86 前缀与空格/连字符分隔）/ PHONE_LANDLINE
  （0 区号 + 本地 7-8 位）/ PLATE（含新能源 6 位）/ EMAIL / IPv4（逐段 0-255）/
  SECRET_KEY（sk- 前缀、AKIA 访问键、PEM 块、长熵 hex 串）/
  DATE_BIRTH（数字版式 + 「出生/生于」上下文门控，避免把公文日期误判为生日）；
- 词面类：SENSITIVE_ATTR（政务敏感身份词表，携带 subtype，ROUTE_FLAG）/
  WORK_SECRET（词表可选层，ROUTE_FLAG）/ CLASSIFICATION_MARK（密级词表，
  命中即 BLOCK_FLAG → 路由拦截）；
- 白名单（labels.md §7）：公开文号 → DOC_NUMBER 且 whitelisted=true、热线/应急
  短号回查、单位座机号段（config/whitelist.yaml）、公开职务姓名称谓钩子
  （:mod:`recognizers.rule.whitelist`，NER 层 PERSON 接入后生效）。

工程口径：

- **影子扫描**：先对全文做全角→半角（1:1 字符映射，span 与原文严格对齐），
  全部正则在影子上匹配，raw/词面匹配与审计表面形式仍取原文；
- 归一化统一走 :func:`masking.normalize.normalize_value`（§5.3.2）；
- 校验位通过 → confidence=1.0；仅格式命中（校验位不符）仍输出（confidence=0.5，
  宁可多脱敏不可漏脱敏，T0.4 口径延续）；难负例（坏校验位）因此永不拿到
  满置信度判定；
- 单遍扫描 + span 占用表防重叠（长熵串 > 证件/卡号/电话 > 日期；词面类不重叠
  数字 span，不受占用表约束）；
- ``detect(text) -> list[Finding]``：fid 恒空串由调用方按请求编号（T0.4 起不变）；
- 性能：2000 字单遍 < 100ms（evals.m2_recognizers 断言，10 次均值）。

归一化等价口径说明：结构化号码串允许内部空格/连字符/全角写法（生成器扰动
``digit_spacing``/``separator_variant``/``fullwidth``），检测端先把 token 压缩
后再做形状/校验位分类，保证「同号异写 → 同 normalized → 同占位符」（§5.3.1）。
"""
from __future__ import annotations

import re
from pathlib import Path

from common.config import REPO_ROOT
from masking.normalize import normalize_value, to_halfwidth
from recognizers.models import EntityClass, Finding
from recognizers.rule.whitelist import Whitelist, get_whitelist

#: 词表默认路径（可配置词表，开发指令 §6 M2）
CLASSIFICATION_TERMS_PATH = REPO_ROOT / "config" / "classification_terms.txt"
SENSITIVE_TERMS_PATH = REPO_ROOT / "config" / "sensitive_terms.txt"
WORK_SECRET_TERMS_PATH = REPO_ROOT / "config" / "work_secret_terms.txt"

#: 词表文件缺失时的兜底词（与 config/classification_terms.txt v0 内容一致）
DEFAULT_CLASSIFICATION_TERMS: tuple[str, ...] = (
    "机密★", "秘密★", "绝密", "内部资料", "注意保密", "不得外传",
)

#: 敏感属性词表兜底（与 config/sensitive_terms.txt 一致：(subtype, term)）
DEFAULT_SENSITIVE_TERMS: tuple[tuple[str, str], ...] = (
    ("低保特困", "低保对象"), ("低保特困", "低保户"), ("低保特困", "特困供养人员"),
    ("信访人", "信访人"),
    ("犯罪记录", "犯罪记录"),
    ("病症", "尿毒症"), ("病症", "恶性肿瘤"), ("病症", "严重糖尿病"),
    ("金融账户", "银行账户"),
    ("残障", "肢体残疾人"), ("残障", "听力残疾人"), ("残障", "视力残疾人"),
    ("社区矫正", "社区矫正对象"),
    ("特定身份", "涉军优抚对象"), ("特定身份", "退役军人"),
    ("行踪轨迹", "活动轨迹"),
)

#: 工作秘密词表兜底（词表可选层；与 config/work_secret_terms.txt 一致）
DEFAULT_WORK_SECRET_TERMS: tuple[str, ...] = (
    "未公开人事任免", "未公开的干部考察情况", "内部议题",
)

#: 机构名后缀抑制：词命中紧跟这些后缀时视为机构指称而非个人敏感属性
#: （如「退役军人事务局」是单位，不是个人「特定身份」；「银行账户」不受影响）
_INSTITUTION_SUFFIXES: tuple[str, ...] = ("事务局", "服务中心")

# ── 编译期常量：校验位 ─────────────────────────────────────────────

#: GB11643 校验：位权与校验码表
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CODES = "10X98765432"

#: GB32174：字符集（31 进制，无 I/O/S/V/Z）与位权
_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_INDEX = {ch: i for i, ch in enumerate(_USCC_CHARS)}
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)

_HEX_SET = frozenset("0123456789abcdefABCDEF")

# ── 编译期常量：正则（均在半角影子上匹配；span 1:1 对应原文）─────────

#: PEM 私钥块（跨行；span 含换行）
_PEM_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*KEY-----.*?-----END [A-Z0-9 ]*KEY-----",
                     re.DOTALL)

#: 通用「数字/字母串」token：允许内部空格/制表/连字符（分组与分隔写法），
#: 压缩后按长度/字符域分类（证件/卡号/电话/熵串）。raw 长度下限 10。
_TOKEN_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z \t-]{9,}")

#: 车牌：省份简称 + 发牌机关字母 + 5 位（普通）/ 6 位（新能源 D/F 开头），
#: 容许间隔点「·」（I/O 不入牌）
_PLATE_RE = re.compile(
    r"(?<![0-9A-Za-z])"
    r"[京津沪渝冀晋蒙辽吉黑苏浙皖闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新]"
    r"[A-HJ-NP-Z][ ·]?[A-HJ-NP-Z0-9]{5,6}"
    r"(?![0-9A-Za-z])"
)

#: 邮箱（local@domain.tld；domain 至少一个点）
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"
    r"(?![A-Za-z0-9-])"
)

#: IPv4：逐段 0-255，前后不贴数字/点（杜绝 5 段链与段内截取）
_IPV4_OCT = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4_RE = re.compile(rf"(?<![0-9.]){_IPV4_OCT}(?:\.{_IPV4_OCT}){{3}}(?![0-9.])")

#: 出生日期（数字版式）：年 18/19/20 开头，容 - /. 分隔；中文版式单独一条
_DIGIT_DATE_RE = re.compile(r"(?<!\d)(?:18|19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)")
_CN_DATE_RE = re.compile(r"(?<!\d)(?:18|19|20)\d{2}年\d{1,2}月\d{1,2}日(?!\d)")

#: 出生日期上下文门控：命中日期紧邻（±窗口）出现「出生/生于/生日」才判 DATE_BIRTH，
#: 公文里大量「发布日期/办理时限」类日期因此零误报
_BIRTH_AFTER = ("出生", "生于", "生日")
_BIRTH_BEFORE = ("生于", "出生于", "生日")
_BIRTH_CTX_WINDOW = 8

#: 公开文号：机关代字 + 〔20XX〕N号（labels.md §7 → DOC_NUMBER 默认 whitelisted）
_DOC_NUMBER_RE = re.compile(r"[\u4e00-\u9fff]{2,12}[〔\[]20\d{2}[〕\]]\d{1,6}号")

#: token 内部压缩时剔除的分隔符
_TOKEN_SEPARATORS = " \t-"

_TERMS_CACHE: tuple[str, ...] | None = None
_SENSITIVE_CACHE: tuple[tuple[str, str], ...] | None = None
_WORK_SECRET_CACHE: tuple[str, ...] | None = None


# ── 校验位（独立实现，供 eval 交叉复核）─────────────────────────────


def id_card_checksum_ok(number: str) -> bool:
    """GB11643 校验位验证（输入为 18 位归一化身份证号）。"""
    if len(number) != 18 or not all("0" <= ch <= "9" for ch in number[:17]):
        return False
    tail = 10 if number[17] in ("X", "x") else (
        int(number[17]) if number[17].isdigit() else -1)
    if tail < 0:
        return False
    total = sum(int(ch) * w for ch, w in zip(number[:17], _ID_WEIGHTS, strict=True))
    return (total + tail) % 11 == 1


def uscc_checksum_ok(code: str) -> bool:
    """GB32174 校验位验证（18 位；全体加权和 ≡ 0 mod 31）。"""
    if len(code) != 18 or any(ch not in _USCC_INDEX for ch in code):
        return False
    total = sum(_USCC_INDEX[ch] * w for ch, w in
                zip(code[:17], _USCC_WEIGHTS, strict=True)) + _USCC_INDEX[code[17]]
    return total % 31 == 0


def luhn_ok(number: str) -> bool:
    """Luhn 校验（银行卡；12-19 位数字）。"""
    if len(number) < 12 or len(number) > 19 or not number.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ── 词表加载（密级 / 敏感属性 / 工作秘密，同一模式）───────────────────


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


def load_sensitive_terms(path: str | Path | None = None) -> tuple[tuple[str, str], ...]:
    """加载敏感属性词表：行格式 ``子类型|词``、# 注释；缺失/为空回退内置。

    子类型不在 SENSITIVE_ATTR_SUBTYPES 值域内的行忽略（契约校验前置）。
    """
    from recognizers.models import SENSITIVE_ATTR_SUBTYPES

    p = Path(path) if path else SENSITIVE_TERMS_PATH
    terms: list[tuple[str, str]] = []
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            subtype, _, term = line.partition("|")
            subtype, term = subtype.strip(), term.strip()
            if subtype in SENSITIVE_ATTR_SUBTYPES and term:
                terms.append((subtype, term))
    if not terms:
        terms = list(DEFAULT_SENSITIVE_TERMS)
    return tuple(terms)


def get_sensitive_terms() -> tuple[tuple[str, str], ...]:
    """进程级缓存的敏感属性词表。"""
    global _SENSITIVE_CACHE
    if _SENSITIVE_CACHE is None:
        _SENSITIVE_CACHE = load_sensitive_terms()
    return _SENSITIVE_CACHE


def set_sensitive_terms(terms: tuple[tuple[str, str], ...]) -> None:
    """测试/运维显式注入敏感属性词表（绕过文件）。"""
    global _SENSITIVE_CACHE
    _SENSITIVE_CACHE = tuple(terms) or DEFAULT_SENSITIVE_TERMS


def load_work_secret_terms(path: str | Path | None = None) -> tuple[str, ...]:
    """加载工作秘密词表：一行一词、# 注释；缺失/为空回退内置。"""
    p = Path(path) if path else WORK_SECRET_TERMS_PATH
    terms: list[str] = []
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                terms.append(line)
    if not terms:
        terms = list(DEFAULT_WORK_SECRET_TERMS)
    return tuple(terms)


def get_work_secret_terms() -> tuple[str, ...]:
    """进程级缓存的工作秘密词表。"""
    global _WORK_SECRET_CACHE
    if _WORK_SECRET_CACHE is None:
        _WORK_SECRET_CACHE = load_work_secret_terms()
    return _WORK_SECRET_CACHE


def set_work_secret_terms(terms: tuple[str, ...]) -> None:
    """测试/运维显式注入工作秘密词表（绕过文件）。"""
    global _WORK_SECRET_CACHE
    _WORK_SECRET_CACHE = tuple(terms) or DEFAULT_WORK_SECRET_TERMS


# ── 内部：span 占用与 Finding 组装 ──────────────────────────────────


def _overlaps(start: int, end: int, taken: list[tuple[int, int]]) -> bool:
    return any(start < t_end and t_start < end for t_start, t_end in taken)


def _finding(text: str, etype: EntityClass, start: int, end: int, *,
             confidence: float, whitelisted: bool = False,
             subtype: str | None = None) -> Finding:
    raw = text[start:end]
    return Finding(
        fid="", type=etype, layer="rule", start=start, end=end, raw=raw,
        normalized=normalize_value(etype, raw), confidence=confidence,
        whitelisted=whitelisted,
        action_hint="BLOCK_FLAG" if etype is EntityClass.CLASSIFICATION_MARK
        else "ROUTE_FLAG" if etype in (EntityClass.SENSITIVE_ATTR, EntityClass.WORK_SECRET)
        else "MASK",
        subtype=subtype,
    )


# ── 内部：token 压缩分类（证件/卡号/电话/熵串共面）───────────────────


def _is_hex(s: str) -> bool:
    return all(ch in _HEX_SET for ch in s)


def _classify_token(compact: str) -> tuple[EntityClass | None, float]:
    """压缩串 → (类别, confidence)。顺序：熵串 > 证件 > 卡号 > 电话。

    口径（难负例友好）：形状命中但校验位不符 → (类别, 0.5) 仍返回，
    由调用方输出低置信度 finding（宁可多脱敏）；完全不成形状 → (None, 0)。
    """
    n = len(compact)
    # 熵串三态：sk- 前缀 / AKIA 访问键 / 40 位长熵 hex
    if compact.startswith("sk") and n >= 30 and _is_hex(compact[2:]):
        return EntityClass.SECRET_KEY, 1.0
    if compact.startswith("AKIA") and 16 <= n - 4 <= 20 \
            and all(ch.isalnum() and ch.isupper() or ch.isdigit() for ch in compact[4:]):
        return EntityClass.SECRET_KEY, 1.0
    if n == 40 and _is_hex(compact):
        return EntityClass.SECRET_KEY, 1.0
    # 18 位全数字形（+尾位 X）：按身份证形解释（18 位全数字串极少为信用代码）
    if n == 18 and all("0" <= ch <= "9" for ch in compact[:17]) and compact[17] in "0123456789Xx":
        return EntityClass.ID_CARD, (1.0 if id_card_checksum_ok(compact) else 0.5)
    # 18 位信用代码：字符域合规且前 17 位非全数字（全数字形已按身份证解释，
    # 同时防止坏证件号串联回信用代码满置信度判定）
    if n == 18 and not compact[:17].isdigit() \
            and all(ch in _USCC_INDEX for ch in compact):
        return EntityClass.USCC, (1.0 if uscc_checksum_ok(compact) else 0.5)
    # 银行卡：12-19 位数字、BIN 首位 2-6、Luhn
    if 12 <= n <= 19 and compact.isdigit() and compact[0] in "23456":
        return EntityClass.BANK_CARD, (1.0 if luhn_ok(compact) else 0.5)
    # 手机号：1[3-9] + 9 位；或 86 + 11 位（+86 前缀写法，span 由调用方回扩）
    if n == 11 and compact[0] == "1" and compact[1] in "3456789":
        return EntityClass.PHONE_MOBILE, 1.0
    if n == 13 and compact.startswith("86") and compact[2] == "1" and compact[3] in "3456789":
        return EntityClass.PHONE_MOBILE, 1.0
    # 座机：0 + 区号 3-4 位 + 本地 7-8 位（压缩 11-12 位）
    if n in (11, 12) and compact[0] == "0" and compact[1] in "123456789":
        return EntityClass.PHONE_LANDLINE, 1.0
    return None, 0.0


def _scan_tokens(shadow: str, text: str, findings: list[Finding],
                 taken: list[tuple[int, int]], wl: Whitelist) -> None:
    """通用数字/字母 token 扫描：熵串/证件/卡号/手机/座机（含白名单回查）。"""
    for m in _TOKEN_RE.finditer(shadow):
        end = m.end()
        # token 尾部悬挂分隔符不算值的一部分（「号码 138 1234 5678 （工作日…）」）
        while end > m.start() and shadow[end - 1] in _TOKEN_SEPARATORS:
            end -= 1
        start = m.start()
        if start == end or _overlaps(start, end, taken):
            continue
        compact = "".join(ch for ch in shadow[start:end] if ch not in _TOKEN_SEPARATORS)
        etype, confidence = _classify_token(compact)
        if etype is None:
            continue
        if etype is EntityClass.PHONE_MOBILE and compact.startswith("86") \
                and start > 0 and shadow[start - 1] == "+":
            start -= 1  # span 回扩覆盖 +86 的「+」（原文写法完整进 raw）
        whitelisted = (
            etype is EntityClass.PHONE_LANDLINE and wl.is_unit_landline(compact)
            or etype is EntityClass.PHONE_MOBILE and wl.is_hotline(compact)
            or etype is EntityClass.PHONE_LANDLINE and wl.is_hotline(compact)
        )
        findings.append(_finding(text, etype, start, end,
                                 confidence=confidence, whitelisted=whitelisted))
        taken.append((start, end))


# ── 主入口 ─────────────────────────────────────────────────────────


def detect(text: str, *, terms: tuple[str, ...] | None = None,
           whitelist: Whitelist | None = None) -> list[Finding]:
    """规则层全类别检测：返回按 start 升序的 Finding 列表（fid 空串，调用方编号）。

    ``terms``：显式覆盖密级词表（T0.4 形参，保留兼容）；``whitelist``：显式覆盖
    白名单（缺省用进程缓存 config/whitelist.yaml）。
    """
    if not text:
        return []
    wl = whitelist or get_whitelist()
    shadow = to_halfwidth(text)
    findings: list[Finding] = []
    taken: list[tuple[int, int]] = []

    # 1) PEM 私钥块（跨行熵材料，最先占位）
    for m in _PEM_RE.finditer(shadow):
        if _overlaps(m.start(), m.end(), taken):
            continue
        findings.append(_finding(text, EntityClass.SECRET_KEY, m.start(), m.end(),
                                 confidence=1.0))
        taken.append((m.start(), m.end()))

    # 2) 通用数字/字母 token：熵串/身份证/信用代码/银行卡/手机/座机
    _scan_tokens(shadow, text, findings, taken, wl)

    # 3) 车牌（省份简称不在 token 字符域内，独立正则）
    for m in _PLATE_RE.finditer(shadow):
        if _overlaps(m.start(), m.end(), taken):
            continue
        findings.append(_finding(text, EntityClass.PLATE, m.start(), m.end(),
                                 confidence=1.0))
        taken.append((m.start(), m.end()))

    # 4) 邮箱
    for m in _EMAIL_RE.finditer(shadow):
        if _overlaps(m.start(), m.end(), taken):
            continue
        findings.append(_finding(text, EntityClass.EMAIL, m.start(), m.end(),
                                 confidence=1.0))
        taken.append((m.start(), m.end()))

    # 5) IPv4
    for m in _IPV4_RE.finditer(shadow):
        if _overlaps(m.start(), m.end(), taken):
            continue
        findings.append(_finding(text, EntityClass.IP, m.start(), m.end(),
                                 confidence=1.0))
        taken.append((m.start(), m.end()))

    # 6) 出生日期（数字/中文版式 + 「出生/生于」上下文门控，跳过已占用 span）
    for m in _DIGIT_DATE_RE.finditer(shadow):
        if _overlaps(m.start(), m.end(), taken):
            continue
        if not (any(w in shadow[m.end():m.end() + _BIRTH_CTX_WINDOW] for w in _BIRTH_AFTER)
                or any(w in shadow[max(0, m.start() - _BIRTH_CTX_WINDOW):m.start()]
                       for w in _BIRTH_BEFORE)):
            continue
        findings.append(_finding(text, EntityClass.DATE_BIRTH, m.start(), m.end(),
                                 confidence=0.9))
        taken.append((m.start(), m.end()))
    for m in _CN_DATE_RE.finditer(shadow):
        if _overlaps(m.start(), m.end(), taken):
            continue
        if not (any(w in shadow[m.end():m.end() + _BIRTH_CTX_WINDOW] for w in _BIRTH_AFTER)
                or any(w in shadow[max(0, m.start() - _BIRTH_CTX_WINDOW):m.start()]
                       for w in _BIRTH_BEFORE)):
            continue
        findings.append(_finding(text, EntityClass.DATE_BIRTH, m.start(), m.end(),
                                 confidence=0.9))
        taken.append((m.start(), m.end()))

    # 7) 公开文号 → DOC_NUMBER（默认 whitelisted，labels.md §7）
    for m in _DOC_NUMBER_RE.finditer(text):
        if _overlaps(m.start(), m.end(), taken):
            continue
        findings.append(_finding(text, EntityClass.DOC_NUMBER, m.start(), m.end(),
                                 confidence=0.9, whitelisted=True))
        taken.append((m.start(), m.end()))

    # 8) 敏感属性词表（subtype + ROUTE_FLAG；机构名后缀抑制）
    for subtype, term in get_sensitive_terms():
        pos = 0
        while (hit := text.find(term, pos)) != -1:
            hit_end = hit + len(term)
            if not any(text[hit_end:].startswith(suf) for suf in _INSTITUTION_SUFFIXES):
                findings.append(_finding(text, EntityClass.SENSITIVE_ATTR,
                                         hit, hit_end, confidence=1.0, subtype=subtype))
            pos = hit_end

    # 9) 工作秘密词表（词表可选层，ROUTE_FLAG）
    for term in get_work_secret_terms():
        pos = 0
        while (hit := text.find(term, pos)) != -1:
            findings.append(_finding(text, EntityClass.WORK_SECRET,
                                     hit, hit + len(term), confidence=1.0))
            pos = hit + len(term)

    # 10) 密级词表（命中即 BLOCK_FLAG；terms 形参可显式覆盖）
    for term in (terms if terms is not None else get_classification_terms()):
        if not term:
            continue
        pos = 0
        while (hit := text.find(term, pos)) != -1:
            findings.append(_finding(text, EntityClass.CLASSIFICATION_MARK,
                                     hit, hit + len(term), confidence=1.0))
            pos = hit + len(term)

    findings.sort(key=lambda f: (f.start, f.end, f.type.value))
    return findings
