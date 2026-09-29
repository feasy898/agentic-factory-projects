"""paper_layout —— 静态卷打印友好排版（BACKLOG P2「静态卷 PDF 输出」）的确定性内核。

行为契约（specs/drafts/paper_layout.spec.md，本文件为参考实现）：

- render_paper_layout：Paper -> 打印友好排版 JSON——页眉（机构注记 · 卷名 · 卷号）、
  按节分组的顺序题号（1..N 贯穿全卷）、选择题选项的标签解析（"A. x" -> 标签 A +
  正文 x，无标签按位置回退 A–Z）、按题型冻结的留白规则（choice 题内括号 /
  fill 一条下划线 / solve 六行解答留白）、固定每页题数的分页与
  「第 p 页 / 共 P 页」页脚；节标题块恒出现在其首题之前（编号不计块数）。
- parse_option：选项字符串 -> (标签, 选项正文)；显式标签优先并归一为大写。
- section_ordinal：节序号 -> 中文序号（一…九十九；≥100 回退阿拉伯数字）。

面向机构分发/离线打印的学生卷：输出**不含**题目答案、解析、误解标签等作答依据
（ integrity 门：未知题、缺合法选项、重复标签在排版期即报错，不静默出残卷）。

全模块纯函数：无 IO、无随机、无时钟、不读环境，同输入同输出。
鸭子类型参数表面（规格 §2，禁止 import 其所在模块）：
- paper: paper_id: str / title: str / sections: list[dict]（含 item_ids: list[str]、
  可选 kp_name: str；sections 为空时回退 paper.item_ids: list[str] 单一隐式节）
- bank: items() -> 题目列表；题目对象只用 id / item_type / stem / options
（注入装载约束：不用 from __future__ import annotations，注解直接写真实对象。）
"""

import re

__all__ = [
    "LayoutError",
    "FORMAT_VERSION",
    "HEADER_SEPARATOR",
    "DEFAULT_QUESTIONS_PER_PAGE",
    "ANSWER_SPACE_RULES",
    "parse_option",
    "section_ordinal",
    "render_paper_layout",
]


class LayoutError(ValueError):
    """paper_layout 模块所有校验失败的异常类型（ValueError 直接子类）。"""


FORMAT_VERSION = "1"  # 排版 JSON 的 schema 版本（冻结）

# 页眉文本段连接符（冻结）：note/title/paper_id 中的非空段以此相连
HEADER_SEPARATOR = " · "

DEFAULT_QUESTIONS_PER_PAGE = 10  # 每页题数缺省值（冻结）

# 留白规则表（冻结）：style = 答案落点样式，lines = 题后留白行数
ANSWER_SPACE_RULES = {
    "choice": {"style": "bracket", "lines": 0},  # 答案写在题干括号内
    "fill": {"style": "underline", "lines": 1},  # 一条作答下划线
    "solve": {"style": "ruled", "lines": 6},     # 六行解答留白
}

# 显式选项标签：单个 ASCII 字母 + 分隔符（. ． 、 ) ）），后接选项正文
_OPT_RE = re.compile(r"([A-Za-z])[.．、)）][ \t]*(.*)\Z", re.S)
_CN_DIGITS = "零一二三四五六七八九"
_FALLBACK_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def parse_option(option_text, position):
    """选项字符串 -> (标签, 选项正文)（规格 §3.2）。

    先 strip；匹配「单 ASCII 字母 + 分隔符（. ． 、 ) ））+ 正文」按显式标签解析
    （标签归一为大写，正文 strip，可为空串）；否则按位置回退标签 A–Z、整串作正文。
    option_text 非 str / strip 后空 / position 非 int（含 bool）/
    position 不在 [0, 25] -> LayoutError。
    """
    if not isinstance(option_text, str):
        raise LayoutError(f"option text must be str, got {type(option_text).__name__}")
    if isinstance(position, bool) or not isinstance(position, int):
        raise LayoutError(f"option position must be int, got {position!r}")
    if not 0 <= position <= 25:
        raise LayoutError(f"option position out of label range A-Z: {position}")
    text = option_text.strip()
    if not text:
        raise LayoutError("option text is blank")
    m = _OPT_RE.match(text)
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return _FALLBACK_LABELS[position], text


def section_ordinal(n):
    """节序号 -> 中文序号文本（规格 §3.3，闭式）。

    1-9 -> 一…九；10 -> 十，11-19 -> 十一…十九；整十 -> 二十/三十/…/九十；
    其余两位数 -> 二十一…九十九；n >= 100 -> str(n)。
    n 非 int（含 bool）或 < 1 -> LayoutError。
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise LayoutError(f"section ordinal must be int, got {n!r}")
    if n < 1:
        raise LayoutError(f"section ordinal must be >= 1, got {n}")
    if n >= 100:
        return str(n)
    tens, units = divmod(n, 10)
    if tens == 0:
        return _CN_DIGITS[units]
    if tens == 1:
        return "十" + (_CN_DIGITS[units] if units else "")
    return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[units] if units else "")


def _require_str_attr(obj, attr, what):
    value = getattr(obj, attr, None)
    if not isinstance(value, str):
        raise LayoutError(f"{what} must be str, got {type(value).__name__}")
    return value


def _build_question(item, item_id, number):
    """单题排版块（规格 §3.4）。只读题目的 item_type / stem / options。"""
    item_type = getattr(item, "item_type", None)
    if item_type not in ANSWER_SPACE_RULES:
        raise LayoutError(f"unknown item_type for {item_id}: {item_type!r}")
    stem = getattr(item, "stem", None)
    if not isinstance(stem, str) or not stem.strip():
        raise LayoutError(f"item {item_id} stem must be a non-empty str")
    if item_type == "choice":
        raw_options = getattr(item, "options", None)
        if not isinstance(raw_options, (list, tuple)) or len(raw_options) < 2:
            raise LayoutError(f"item {item_id} choice needs >=2 options")
        pairs = [parse_option(o, i) for i, o in enumerate(raw_options)]
        labels = [label for label, _ in pairs]
        if len(set(labels)) != len(labels):
            raise LayoutError(f"item {item_id} duplicate option labels: {labels}")
        options = [{"label": label, "text": text} for label, text in pairs]
    else:
        options = []  # 非 choice 题不排选项（options 字段即使有值也忽略）
    rule = ANSWER_SPACE_RULES[item_type]
    return {
        "kind": "question",
        "number": number,
        "item_id": item_id,
        "item_type": item_type,
        "stem": stem,
        "options": options,
        "answer_space": {"style": rule["style"], "lines": rule["lines"]},
    }


def render_paper_layout(paper, bank, questions_per_page=DEFAULT_QUESTIONS_PER_PAGE,
                        header_note=""):
    """Paper -> 打印友好排版 JSON（规格 §3.5，全部规则闭式）。

    校验顺序冻结：questions_per_page -> header_note -> paper 表面 -> bank 索引 ->
    sections -> 逐题构建（按卷面顺序首个坏题报错）-> 空卷门 -> 分页。

    分页闭式：第 p 页（1 起）承载全卷第 (p-1)*qpp+1 .. min(p*qpp, N) 题；
    节标题块只在其**首题**所在页、且紧邻该题之前出现，不占题数位；
    命名但无题的节不渲染、不占节序号。

    纯函数：不改 paper/bank；输出全部为新构造容器，JSON 可序列化，
    不含 answer/solution 等作答依据。
    """
    # V1：每页题数
    if isinstance(questions_per_page, bool) or not isinstance(questions_per_page, int):
        raise LayoutError(
            f"questions_per_page must be int, got {questions_per_page!r}")
    if questions_per_page < 1:
        raise LayoutError(f"questions_per_page must be >= 1, got {questions_per_page}")
    # V2：页眉注记
    if not isinstance(header_note, str):
        raise LayoutError(f"header_note must be str, got {type(header_note).__name__}")

    # V3：paper 表面
    paper_id = _require_str_attr(paper, "paper_id", "paper.paper_id")
    title = _require_str_attr(paper, "title", "paper.title")
    raw_sections = getattr(paper, "sections", None)
    if not isinstance(raw_sections, (list, tuple)):
        raise LayoutError("paper.sections must be a list")
    sec_list = list(raw_sections)

    # V4：bank 索引（只建 id -> 题对象映射，题目内容在排版到该题时才校验）
    items_fn = getattr(bank, "items", None)
    if not callable(items_fn):
        raise LayoutError("bank must expose items()")
    seq = items_fn()
    try:
        iterator = iter(seq)
    except TypeError:
        raise LayoutError("bank.items() must return an iterable") from None
    index = {}
    for it in iterator:
        iid = getattr(it, "id", None)
        if not isinstance(iid, str) or not iid.strip():
            raise LayoutError("bank item id must be a non-empty str")
        if iid in index:
            raise LayoutError(f"duplicate item id in bank: {iid}")
        index[iid] = it

    # V5a：sections 为空 -> 整卷回退为单一匿名隐式节（用 paper.item_ids）
    if not sec_list:
        fallback_ids = getattr(paper, "item_ids", None)
        if not isinstance(fallback_ids, (list, tuple)):
            raise LayoutError("paper.item_ids must be a list when sections is empty")
        sec_list = [{"kp_name": "", "item_ids": list(fallback_ids)}]

    # V5b：节规整化（item_ids 必须是 list/tuple 且元素为非空 str；kp_name 可选 str）
    normalized = []
    for sec in sec_list:
        if not isinstance(sec, dict):
            raise LayoutError("paper.sections entries must be dicts")
        ids = sec.get("item_ids")
        if not isinstance(ids, (list, tuple)):
            raise LayoutError(
                f"section {sec.get('kp_id', '')!r} item_ids must be a list")
        for iid in ids:
            if not isinstance(iid, str) or not iid.strip():
                raise LayoutError(f"section item id must be non-empty str, got {iid!r}")
        name = ""
        if "kp_name" in sec:
            v = sec["kp_name"]
            if not isinstance(v, str):
                raise LayoutError("section kp_name must be str")
            name = v
        normalized.append({"name": name.strip(), "item_ids": list(ids)})

    # V6：逐节逐题构建（卷面顺序；首个坏题即报错）；节序号只发给「有名且有题」的节
    flat = []  # (节条目, 题块)，按卷面顺序
    entries = []
    ordinal_counter = 0
    position = 0
    for sec in normalized:
        entry = {"name": sec["name"], "first_pos": None, "ordinal": None}
        if sec["name"] and sec["item_ids"]:
            ordinal_counter += 1
            entry["ordinal"] = ordinal_counter
            entry["first_pos"] = position
        for iid in sec["item_ids"]:
            item = index.get(iid)
            if item is None:
                raise LayoutError(f"unknown item id in paper: {iid}")
            position += 1
            flat.append((entry, _build_question(item, iid, position)))
        entries.append(entry)

    # V7：空卷门
    if position == 0:
        raise LayoutError("empty paper: no questions to lay out")

    # V8：分页 + 页眉/页脚（闭式）
    page_count = -(-position // questions_per_page)
    header_segments = [s for s in (header_note.strip(), title.strip(), paper_id.strip()) if s]
    header_text = HEADER_SEPARATOR.join(header_segments)
    pages = []
    for p in range(1, page_count + 1):
        lo = (p - 1) * questions_per_page
        hi = min(p * questions_per_page, position)
        blocks = []
        for pos in range(lo, hi):
            entry, question = flat[pos]
            if entry["ordinal"] is not None and pos == entry["first_pos"]:
                blocks.append({
                    "kind": "section",
                    "text": f"{section_ordinal(entry['ordinal'])}、{entry['name']}",
                })
            blocks.append(question)
        pages.append({
            "page_number": p,
            "page_count": page_count,
            "header": {
                "title": title,
                "paper_id": paper_id,
                "note": header_note.strip(),
                "text": header_text,
            },
            "footer": {"text": f"第 {p} 页 / 共 {page_count} 页"},
            "blocks": blocks,
        })

    by_type = {}
    for _, question in flat:
        by_type[question["item_type"]] = by_type.get(question["item_type"], 0) + 1

    return {
        "format_version": FORMAT_VERSION,
        "paper_id": paper_id,
        "title": title,
        "question_count": position,
        "page_count": page_count,
        "by_item_type": {k: by_type[k] for k in sorted(by_type)},
        "pages": pages,
    }
