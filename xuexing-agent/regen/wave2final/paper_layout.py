"""paper_layout —— 静态卷打印友好排版（冻结契约：specs/frozen/paper_layout.spec.md 定稿 v1）。

纯函数内核：Paper + bank -> 打印友好 JSON（页眉/顺序题号/选项标签/留白/分页/页脚）。
无 IO、无随机、无时钟，同输入同输出；学生卷不读取、不输出任何作答依据。
鸭子表面上约定要读的属性/键「缺失」时，以哨兵捕获后把缺失值送入对应类型校验抛
LayoutError，绝不漏出 AttributeError/KeyError；唯一域外 = 属性读取本身抛出
非 AttributeError 异常（原样传播，见规格 §6）。
"""
import re

FORMAT_VERSION = "1"
HEADER_SEPARATOR = " · "  # 空格 + U+00B7 + 空格
DEFAULT_QUESTIONS_PER_PAGE = 10
ANSWER_SPACE_RULES = {
    "choice": {"style": "bracket", "lines": 0},
    "fill": {"style": "underline", "lines": 1},
    "solve": {"style": "ruled", "lines": 6},
}

_CN_DIGITS = "零一二三四五六七八九"
_FALLBACK_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# 显式标签锚定 strip 后串首（match，不做串内搜索）：单 ASCII 字母 + 分隔符 + 可为零的空白 + 正文（可跨换行）
_OPTION_RE = re.compile(r"([A-Za-z])[.．、)）][ \t]*(.*)\Z", re.DOTALL)
_MISSING = object()  # 「属性/键缺失」哨兵：缺失 ≠ 空容器


class LayoutError(ValueError):
    """本模块唯一校验异常类型。"""


def _fail(msg):
    raise LayoutError(msg)


def _is_int(value):
    # bool 是 int 子类，规格一律按非 int 拒绝
    return isinstance(value, int) and not isinstance(value, bool)


def parse_option(option_text, position) -> tuple[str, str]:
    """选项字符串 -> (标签, 选项正文)。无显式标签时按位回退，正文保留 strip 后整串。"""
    if not (isinstance(option_text, str) and option_text.strip() != ""):
        _fail("parse_option: option_text must be a non-blank str, got %r" % (option_text,))
    if not (_is_int(position) and 0 <= position <= 25):
        _fail("parse_option: position must be an int in [0, 25], got %r" % (position,))
    text = option_text.strip()
    m = _OPTION_RE.match(text)
    if m is None:
        return _FALLBACK_LABELS[position], text
    return m.group(1).upper(), m.group(2).strip()


def section_ordinal(n) -> str:
    """节序号 -> 中文序号闭式（1-99）；n >= 100 回退阿拉伯数字。"""
    if not (_is_int(n) and n >= 1):
        _fail("section_ordinal: n must be a positive int, got %r" % (n,))
    if n >= 100:
        return str(n)
    tens, ones = divmod(n, 10)
    if tens == 0:
        return _CN_DIGITS[ones]
    text = _CN_DIGITS[tens] + "十" if tens > 1 else "十"
    if ones:
        text += _CN_DIGITS[ones]
    return text


def render_paper_layout(paper, bank, questions_per_page=DEFAULT_QUESTIONS_PER_PAGE,
                        header_note="") -> dict:
    """Paper + bank -> 打印友好排版 JSON。校验顺序 V1→V8 冻结，任一步失败抛 LayoutError。"""
    # ---- V1 questions_per_page：int（拒 bool）且 >= 1 ----
    if not (_is_int(questions_per_page) and questions_per_page >= 1):
        _fail("questions_per_page must be an int >= 1, got %r" % (questions_per_page,))
    # ---- V2 header_note：必须为 str ----
    if not isinstance(header_note, str):
        _fail("header_note must be a str, got %r" % (header_note,))

    # ---- V3 paper 表面（属性缺失送类型校验；sections 缺失不触发回退） ----
    paper_id = getattr(paper, "paper_id", _MISSING)
    if not isinstance(paper_id, str):
        _fail("paper.paper_id must be a str, got %r" % (paper_id,))
    title = getattr(paper, "title", _MISSING)
    if not isinstance(title, str):
        _fail("paper.title must be a str, got %r" % (title,))
    sections = getattr(paper, "sections", _MISSING)
    if not isinstance(sections, (list, tuple)):
        _fail("paper.sections must be a list, got %r" % (sections,))

    # ---- V4 bank 索引：只建 id -> 题对象映射，题目内容延迟到该题被排版（V6）时校验 ----
    items_getter = getattr(bank, "items", _MISSING)
    if not callable(items_getter):
        _fail("bank.items must be a callable, got %r" % (items_getter,))
    raw_items = items_getter()
    try:
        items_iter = iter(raw_items)
    except TypeError:
        _fail("bank.items() must return an iterable, got %r" % (raw_items,))
    id_to_item = {}
    for it in items_iter:
        iid = getattr(it, "id", _MISSING)
        if not (isinstance(iid, str) and iid.strip() != ""):
            _fail("bank item id must be a non-blank str, got %r" % (iid,))
        if iid in id_to_item:
            _fail("duplicate bank item id: %r" % (iid,))
        id_to_item[iid] = it

    # ---- V5 节规整化：空 sections 才回退到单一匿名隐式节 ----
    norm_sections = []  # (strip 后节名, item_ids 拷贝)
    if len(sections) == 0:
        fallback_ids = getattr(paper, "item_ids", _MISSING)
        if not isinstance(fallback_ids, (list, tuple)):
            _fail("paper.item_ids must be a list when sections is empty, got %r" % (fallback_ids,))
        _check_section_elements(fallback_ids)
        norm_sections.append(("", list(fallback_ids)))
    else:
        for sec in sections:
            if not isinstance(sec, dict):
                _fail("section must be a dict, got %r" % (sec,))
            ids = sec.get("item_ids", _MISSING)
            if not isinstance(ids, (list, tuple)):
                _fail("section %r: item_ids must be a list, got %r" % (sec.get("kp_name", ""), ids))
            _check_section_elements(ids)
            raw_name = sec.get("kp_name", _MISSING)
            if raw_name is _MISSING:
                name = ""
            else:
                if not isinstance(raw_name, str):
                    _fail("section kp_name must be a str, got %r" % (raw_name,))
                name = raw_name.strip()  # 全空白等价未命名
            norm_sections.append((name, list(ids)))

    # ---- V6 逐节逐题构建：卷面顺序 = 节序 × 节内 item_ids 序，首个坏题即抛 ----
    flat_blocks = []
    type_counts = {}
    ordinal = 0  # 节序号计数器：只发给「kp_name 非空且有题」的节
    number = 0
    for name, ids in norm_sections:
        if name != "" and ids:
            ordinal += 1
            flat_blocks.append(
                {"kind": "section", "text": "%s、%s" % (section_ordinal(ordinal), name)})
        for iid in ids:
            if iid not in id_to_item:
                _fail("unknown item id in paper: %r" % (iid,))
            it = id_to_item[iid]
            item_type = getattr(it, "item_type", _MISSING)
            if item_type not in ANSWER_SPACE_RULES:
                _fail("item %r: item_type must be one of %s, got %r"
                      % (iid, sorted(ANSWER_SPACE_RULES), item_type))
            stem = getattr(it, "stem", _MISSING)
            if not (isinstance(stem, str) and stem.strip() != ""):
                _fail("item %r: stem must be a non-blank str, got %r" % (iid, stem))
            options = []  # 非 choice 恒 []，options 字段即使有值也忽略
            if item_type == "choice":
                raw_options = getattr(it, "options", _MISSING)
                if not (isinstance(raw_options, (list, tuple)) and len(raw_options) >= 2):
                    _fail("item %r: choice needs a list/tuple of >= 2 options, got %r"
                          % (iid, raw_options))
                labels = set()  # 显式标签与回退标签同样参与判重
                for pos, opt in enumerate(raw_options):
                    label, body = parse_option(opt, pos)
                    if label in labels:
                        _fail("item %r: duplicate option label %r" % (iid, label))
                    labels.add(label)
                    options.append({"label": label, "text": body})
            number += 1
            type_counts[item_type] = type_counts.get(item_type, 0) + 1
            flat_blocks.append({
                "kind": "question",
                "number": number,
                "item_id": iid,
                "item_type": item_type,
                "stem": stem,
                "options": options,
                "answer_space": dict(ANSWER_SPACE_RULES[item_type]),  # 每次新 dict，不别名常量表
            })

    # ---- V7 空卷门 ----
    if number == 0:
        _fail("empty paper: no questions to lay out")
    total = number

    # ---- V8 分页 + 页眉页脚：节标题块紧邻节首题、不占题数位，跨页不重复 ----
    page_count = (total + questions_per_page - 1) // questions_per_page
    note = header_note.strip()
    header_text = HEADER_SEPARATOR.join(
        seg for seg in (note, title.strip(), paper_id.strip()) if seg != "")
    pages = []
    pending_sections = []  # 已就绪未落页的节标题块，随其节首题落页
    current = None
    in_page = 0
    for block in flat_blocks:
        if block["kind"] == "section":
            pending_sections.append(block)
            continue
        if current is None or in_page == questions_per_page:
            page_number = len(pages) + 1
            current = {
                "page_number": page_number,
                "page_count": page_count,
                "header": {
                    "title": title,      # 原样透传，不 strip
                    "paper_id": paper_id,  # 原样透传，不 strip
                    "note": note,
                    "text": header_text,
                },
                "footer": {"text": "第 %d 页 / 共 %d 页" % (page_number, page_count)},
                "blocks": [],
            }
            pages.append(current)
            in_page = 0
        current["blocks"].extend(pending_sections)
        pending_sections = []
        current["blocks"].append(block)
        in_page += 1

    return {
        "format_version": FORMAT_VERSION,
        "paper_id": paper_id,  # 顶层原样透传
        "title": title,
        "question_count": total,
        "page_count": page_count,
        "by_item_type": dict(sorted(type_counts.items())),  # 仅出现的题型，键码点升序
        "pages": pages,
    }


def _check_section_elements(ids):
    """节内 item_ids 元素必须为 strip 后非空的 str。"""
    for x in ids:
        if not (isinstance(x, str) and x.strip() != ""):
            _fail("section item_ids elements must be non-blank str, got %r" % (x,))
