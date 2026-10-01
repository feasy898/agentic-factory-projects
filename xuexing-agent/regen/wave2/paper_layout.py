"""paper_layout —— 静态卷打印友好排版（冻结契约 specs/frozen/paper_layout.spec.md 的重生成实例）。

把 paper 产出的 Paper 渲染为可直接交付排版/PDF 管线的打印友好 JSON：页眉
（机构注记 · 卷名 · 卷号）、按节分组的顺序题号（1..N 贯穿全卷）、选择题选项标签解析、
按题型冻结的留白规则、固定每页题数的分页与「第 p 页 / 共 P 页」页脚。产出学生卷：
对题目对象只读 id/item_type/stem（choice 另读 options），不读、不输出
answer/solution/misconceptions 等作答依据（I9）。

全内核纯函数：无 IO、无随机、无时钟、不读环境，同输入同输出（无 seed/时间戳豁免）。
入参为鸭子类型表面（paper/bank/题目对象）；「缺失 ≠ 空容器」：约定要读的属性/键
缺失时按缺失值送对应类型校验并抛 LayoutError，不漏 AttributeError/KeyError（§2.2）。
仅依赖 Python 标准库；不 import 任何其他 xuexing 模块。
"""

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


# ---------- 冻结常量（§3.1 / I1） ----------

FORMAT_VERSION = "1"
HEADER_SEPARATOR = " · "  # 空格 + U+00B7 + 空格
DEFAULT_QUESTIONS_PER_PAGE = 10
ANSWER_SPACE_RULES = {
    "choice": {"style": "bracket", "lines": 0},  # 答案写在题干括号内
    "fill": {"style": "underline", "lines": 1},  # 一条作答下划线
    "solve": {"style": "ruled", "lines": 6},     # 六行解答留白
}

_ORDINAL_DIGITS = "一二三四五六七八九"
_LABEL_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LABEL_SEPARATORS = ".．、)）"

# 「缺失」哨兵：区分「属性/键缺失」与「值为 None/空容器」（§2.2）
_MISSING = object()


class LayoutError(ValueError):
    """排版期校验失败（本模块唯一校验异常类型，ValueError 直接子类）。"""


# ---------- 内部工具 ----------

def _read_attr(obj, name):
    """读对象属性；属性缺失（§2.2）转 LayoutError，不漏 AttributeError。

    域外输入：属性读取本身抛非 AttributeError 异常时原样传播（§6）。
    """
    value = getattr(obj, name, _MISSING)
    if value is _MISSING:
        raise LayoutError(
            "missing attribute %r on %s" % (name, type(obj).__name__))
    return value


def _check_item_ids(raw_ids, where):
    """节内 item_ids 元素校验：必须为 strip 后非空的 str；返回原样元素列表。"""
    ids = []
    for position, item_id in enumerate(raw_ids):
        if not isinstance(item_id, str) or not item_id.strip():
            raise LayoutError(
                "%s[%d] must be a non-blank str, got %r" % (where, position, item_id))
        ids.append(item_id)
    return ids


# ---------- 公开 API：parse_option（§3.2 / I3） ----------

def parse_option(option_text, position) -> tuple:
    """选项字符串 -> (标签, 选项正文)。

    显式标签匹配锚定 strip 后串首：单 ASCII 字母 + 分隔符（. ． 、 ) ）之一）
    + 空白（空格/制表，可为零个）+ 正文；标签归一大写；正文为分隔符后直至串尾的
    全部剩余字符（可含换行）strip 后，可为空串。不做串内搜索。
    不匹配 -> 按位回退：标签 = 字母表[position]，正文 = strip 后整串。
    """
    if not isinstance(option_text, str) or not option_text.strip():
        raise LayoutError(
            "option_text must be a non-blank str, got %r" % (option_text,))
    if (isinstance(position, bool) or not isinstance(position, int)
            or position < 0 or position > 25):
        raise LayoutError(
            "position must be an int in [0, 25], got %r" % (position,))
    text = option_text.strip()
    if (len(text) >= 2 and text[0].isascii() and text[0].isalpha()
            and text[1] in _LABEL_SEPARATORS):
        return text[0].upper(), text[2:].strip()
    return _LABEL_ALPHABET[position], text


# ---------- 公开 API：section_ordinal（§3.3 / I6） ----------

def section_ordinal(n) -> str:
    """节序号 -> 中文序号闭式：1-9 一…九；10 十；11-19 十一…十九；
    整十 二十/三十/…/九十；其余两位 几十几；n >= 100 -> str(n)。"""
    if isinstance(n, bool) or not isinstance(n, int):
        raise LayoutError("section ordinal must be an int, got %r" % (n,))
    if n < 1:
        raise LayoutError("section ordinal must be >= 1, got %r" % (n,))
    if n >= 100:
        return str(n)
    if n < 10:
        return _ORDINAL_DIGITS[n - 1]
    tens, ones = divmod(n, 10)
    text = "" if tens == 1 else _ORDINAL_DIGITS[tens - 1]
    text += "十"
    if ones:
        text += _ORDINAL_DIGITS[ones - 1]
    return text


# ---------- V4：bank 索引 ----------

def _index_bank(bank):
    """id -> 题对象映射；只读 items()/id，题目内容延迟到该题被排版时才校验。"""
    items_method = getattr(bank, "items", _MISSING)
    if items_method is _MISSING or not callable(items_method):
        raise LayoutError(
            "bank.items must be a callable, got %r" % (items_method,))
    items_seq = items_method()
    try:
        items_iter = iter(items_seq)
    except TypeError:
        raise LayoutError(
            "bank.items() must return an iterable, got %r" % (items_seq,)) from None
    by_id = {}
    for item in items_iter:
        item_id = getattr(item, "id", _MISSING)
        if item_id is _MISSING or not isinstance(item_id, str) or not item_id.strip():
            raise LayoutError(
                "bank item.id must be a non-blank str, got %r" % (item_id,))
        if item_id in by_id:
            raise LayoutError("duplicate item id in bank: %r" % (item_id,))
        by_id[item_id] = item
    return by_id


# ---------- V5：节规整化 ----------

def _normalize_sections(paper, sections):
    """规整化为 [{kp_name(已 strip), item_ids(原样 str 列表)}]。

    仅当 sections 为空 list/tuple 时回退 paper.item_ids 构造单一匿名隐式节；
    sections 属性缺失已在调用方按 §2.2 报错，缺失不触发回退。
    """
    normalized = []
    if len(sections) == 0:
        raw_ids = getattr(paper, "item_ids", _MISSING)
        if raw_ids is _MISSING or not isinstance(raw_ids, (list, tuple)):
            raise LayoutError(
                "paper.item_ids must be a list or tuple when sections is empty, got %r"
                % (raw_ids,))
        normalized.append(
            {"kp_name": "", "item_ids": _check_item_ids(raw_ids, "paper.item_ids")})
        return normalized
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise LayoutError(
                "section #%d must be a dict, got %r" % (index, section))
        if "item_ids" not in section:
            raise LayoutError(
                "section #%d is missing required key 'item_ids'" % (index,))
        raw_ids = section["item_ids"]
        if not isinstance(raw_ids, (list, tuple)):
            raise LayoutError(
                "section #%d item_ids must be a list or tuple, got %r"
                % (index, raw_ids))
        ids = _check_item_ids(raw_ids, "section #%d item_ids" % (index,))
        kp_name = section.get("kp_name", "")
        if not isinstance(kp_name, str):
            raise LayoutError(
                "section #%d kp_name must be a str, got %r" % (index, kp_name))
        normalized.append({"kp_name": kp_name.strip(), "item_ids": ids})
    return normalized


# ---------- V6：单题校验 + 题块构建（§3.4） ----------

def _build_question(number, item_id, item):
    """对单道被排版的题执行 §3.4 校验并新构造题块（不引用入参内部对象）。"""
    item_type = getattr(item, "item_type", _MISSING)
    if item_type is _MISSING or item_type not in ANSWER_SPACE_RULES:
        raise LayoutError(
            "item %r has unknown item_type %r" % (item_id, item_type))
    stem = getattr(item, "stem", _MISSING)
    if not isinstance(stem, str) or not stem.strip():
        raise LayoutError(
            "item %r stem must be a non-blank str, got %r" % (item_id, stem))
    options = []
    if item_type == "choice":
        raw_options = getattr(item, "options", _MISSING)
        if (raw_options is _MISSING or not isinstance(raw_options, (list, tuple))
                or len(raw_options) < 2):
            raise LayoutError(
                "choice item %r needs a list/tuple of >= 2 options, got %r"
                % (item_id, raw_options))
        seen_labels = set()
        for option_position, option_text in enumerate(raw_options):
            label, text = parse_option(option_text, option_position)
            if label in seen_labels:  # 显式标签与回退标签同样参与判重
                raise LayoutError(
                    "item %r has duplicate option label %r" % (item_id, label))
            seen_labels.add(label)
            options.append({"label": label, "text": text})
    rule = ANSWER_SPACE_RULES[item_type]
    return {
        "kind": "question",
        "number": number,
        "item_id": item_id,
        "item_type": item_type,
        "stem": stem,  # 原样透传不 strip
        "options": options,  # 非 choice 恒 []
        "answer_space": {"style": rule["style"], "lines": rule["lines"]},  # 每次新 dict
    }


# ---------- 公开 API：render_paper_layout（§3.5 / V1→V8） ----------

def render_paper_layout(paper, bank,
                        questions_per_page: int = DEFAULT_QUESTIONS_PER_PAGE,
                        header_note: str = "") -> dict:
    """Paper + bank -> 打印友好排版 JSON。校验顺序 V1→V8 冻结，任何一步失败抛 LayoutError。"""
    # V1 questions_per_page：int（bool 拒）且 >= 1
    if (isinstance(questions_per_page, bool) or not isinstance(questions_per_page, int)
            or questions_per_page < 1):
        raise LayoutError(
            "questions_per_page must be an int >= 1, got %r" % (questions_per_page,))
    # V2 header_note：str（空串合法）
    if not isinstance(header_note, str):
        raise LayoutError("header_note must be a str, got %r" % (header_note,))
    # V3 paper 表面：paper_id/title 为 str（可空串）；sections 为 list/tuple
    paper_id = _read_attr(paper, "paper_id")
    title = _read_attr(paper, "title")
    sections = _read_attr(paper, "sections")
    if not isinstance(paper_id, str):
        raise LayoutError("paper.paper_id must be a str, got %r" % (paper_id,))
    if not isinstance(title, str):
        raise LayoutError("paper.title must be a str, got %r" % (title,))
    if not isinstance(sections, (list, tuple)):
        raise LayoutError(
            "paper.sections must be a list or tuple, got %r" % (sections,))
    # V4 bank 索引（items 缺失/不可调用、返回不可迭代、id 缺失/非 str、id 重复在此报错；
    # 题目内容延迟到该题被排版时才校验）
    by_id = _index_bank(bank)
    # V5 节规整化（节非 dict、item_ids 键缺失/非列表、元素非 str、kp_name 非 str 在此报错）
    normalized = _normalize_sections(paper, sections)
    # V6 逐节逐题构建：卷面顺序 = 节序 × 节内 item_ids 序
    question_blocks = []
    section_titles = {}  # 题块下标 -> 节标题文本（恒出现在节首题之前，不占每页题数位）
    ordinal_counter = 0
    type_counts = {}
    for section in normalized:
        ids = section["item_ids"]
        section_name = section["kp_name"]
        section_number = None
        # 节序号仅发给「命名且有题」的节；未命名节与空节不消耗号段
        if section_name and ids:
            ordinal_counter += 1
            section_number = ordinal_counter
        for position_in_section, item_id in enumerate(ids):
            item = by_id.get(item_id)
            if item is None:
                raise LayoutError("unknown item id in paper: %r" % (item_id,))
            block = _build_question(len(question_blocks) + 1, item_id, item)
            question_blocks.append(block)
            block_type = block["item_type"]
            type_counts[block_type] = type_counts.get(block_type, 0) + 1
            if position_in_section == 0 and section_number is not None:
                section_titles[len(question_blocks) - 1] = (
                    section_ordinal(section_number) + "、" + section_name)
    # V7 空卷门
    question_count = len(question_blocks)
    if question_count == 0:
        raise LayoutError("paper has no questions to lay out")
    # V8 分页 + 页眉页脚：第 p 页承载全卷第 (p-1)*qpp+1 .. min(p*qpp, N) 题
    page_count = (question_count + questions_per_page - 1) // questions_per_page
    note = header_note.strip()
    header_text = HEADER_SEPARATOR.join(
        segment for segment in (note, title.strip(), paper_id.strip()) if segment)
    pages = []
    for page_number in range(1, page_count + 1):
        start = (page_number - 1) * questions_per_page
        end = min(page_number * questions_per_page, question_count)
        blocks = []
        for index in range(start, end):
            if index in section_titles:
                blocks.append({"kind": "section", "text": section_titles[index]})
            blocks.append(question_blocks[index])
        pages.append({
            "page_number": page_number,
            "page_count": page_count,
            "header": {
                "title": title,  # 原样透传，不 strip
                "paper_id": paper_id,  # 原样透传，不 strip
                "note": note,
                "text": header_text,
            },
            "footer": {"text": "第 %d 页 / 共 %d 页" % (page_number, page_count)},
            "blocks": blocks,
        })
    return {
        "format_version": FORMAT_VERSION,
        "paper_id": paper_id,  # 原样透传，不 strip
        "title": title,        # 原样透传，不 strip
        "question_count": question_count,
        "page_count": page_count,
        "by_item_type": {t: type_counts[t] for t in sorted(type_counts)},
        "pages": pages,
    }
