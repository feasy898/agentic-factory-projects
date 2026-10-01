"""omr_sheet —— OMR 答题卡对接规范（BACKLOG P2「OMR 答题卡对接规范」）的确定性内核。

行为契约（specs/drafts/omr_sheet.spec.md，本文件为参考实现）：

- build_answer_sheet：Paper -> answer-sheet.json（题号-选项映射）——卷面题号
  （1..N 贯穿全卷，与 paper_layout 同一编号语义）-> 题目 id -> OMR 列名（q<题号>）
  -> 气泡值表（选项标签 A–Z）-> 选项内容；fill/solve 题不出涂点，标记为 manual
  模式交手工/OCR 录入。附 OMRChecker template.json 内容侧信息：outputColumns
  （自然排序）+ fieldBlocks 的 fieldLabels 字段串（q1..10 含端点区间）/bubbleValues/
  direction；像素几何（origin/间距）不在本模块范围。学生面文档不含答案/解析/题干。
- parse_omr_results：OMRChecker Results CSV 文本 -> 行 dict 列表（表头
  file_id, input_path, output_path, score, <列…>；题目单元格 = 该题被涂气泡值的
  拼接串，未涂 = 空串，多涂按气泡序拼接如 "AC"）。
- to_responses：一张卡（行 dict）按 answer-sheet 映射还原为 Response 列表——
  未涂 -> learner_answer=None, correct=False；单涂 -> learner_answer=该选项在 bank
  options 中的原文全串（与 grading.grade_choice 对显式标签题/位置回退标签题都
  同判，契约测试跨模块锁定）；多涂 -> learner_answer=涂点拼接串且一律
  correct=False（不猜）；manual 题不产 Response。sheet/bank 任一漂移（未知题/
  题型变/气泡表不一致/缺列/未知涂点）一律 OMRError 硬失败，不静默错位判分。

OMRChecker 对接事实（2026-09-29 实读 Udayraj123/OMRChecker master 源码核对）：
Results CSV 表头 = file_id, input_path, output_path, score, <template.output_columns>
（src/utils/file.py），结果行同序追加（src/entry.py）；题目单元格为该 field_label
被涂气泡值的拼接、无涂点记 field_block.empty_val（模板默认 ""）（src/core.py）；
字段串 "q1..10" 解析为 q1..q10 含端点（src/utils/parsing.py parse_field_string），
输出列自然排序键 = (前缀, 数字)（同文件 custom_sort_output_columns）；
QTYPE_MCQ4 气泡值 ["A","B","C","D"]、direction horizontal（src/constants/common.py）。

全模块纯函数：无 IO、无随机、无时钟、不读环境，同输入同输出。
鸭子类型参数表面（规格 §2，禁止 import 其所在模块）：
- paper: paper_id: str / title: str / sections: list[dict]（含 item_ids: list[str]、
  可选 kp_name: str；sections 为空时回退 paper.item_ids: list[str] 单一隐式节）
- bank: items() -> 题目列表；题目对象只用 id / item_type / answer / options
（注入装载约束：不用 from __future__ import annotations，注解直接写真实对象。）
"""

import csv
import io
import re

from xuexing.types import Response

__all__ = [
    "OMRError",
    "OMR_VERSION",
    "FIELD_PREFIX",
    "MODE_OMR",
    "MODE_MANUAL",
    "BLOCK_DIRECTION",
    "MAX_BUBBLES",
    "RESULTS_FILE_ID_COLUMN",
    "parse_option",
    "field_label",
    "parse_field_ranges",
    "natural_sort_key",
    "build_answer_sheet",
    "parse_omr_results",
    "to_responses",
]


class OMRError(ValueError):
    """omr_sheet 模块所有校验失败的异常类型（ValueError 直接子类）。"""


# ---- 冻结常量（specs/drafts/omr_sheet.spec.md §3.1）----

OMR_VERSION = "1"  # answer-sheet.json 的 schema 版本

FIELD_PREFIX = "q"  # OMR 列名前缀：列名 = "q" + str(卷面题号)

MODE_OMR = "omr"      # choice 题：机读涂卡
MODE_MANUAL = "manual"  # fill/solve 题：手工/OCR 录入，无涂点

BLOCK_DIRECTION = "horizontal"  # OMRChecker QTYPE_MCQ* 同款：一题一行气泡横排

MAX_BUBBLES = 26  # 气泡值 = 单个大写 ASCII 字母，A–Z 上限

RESULTS_FILE_ID_COLUMN = "file_id"  # OMRChecker Results CSV 的文件标识列名

# 合法题型（与 types.Item.item_type 值域一致；未知题型在排版/映射期即报错）
_ITEM_TYPES = ("choice", "fill", "solve")

# 显式选项标签：单个 ASCII 字母 + 分隔符（. ． 、 ) ）），后接选项正文
_OPT_RE = re.compile(r"([A-Za-z])[.．、)）][ \t]*(.*)\Z", re.S)
_FALLBACK_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# OMRChecker 自然排序键：([^\d]+)(\d*) 取首组（custom_sort_output_columns 同款）
_NATURAL_RE = re.compile(r"([^\d]+)(\d*)")


def parse_option(option_text, position):
    """选项字符串 -> (标签, 选项正文)（规格 §3.2，与 paper_layout.parse_option 同闭式）。

    先 strip；匹配「单 ASCII 字母 + 分隔符（. ． 、 ) ））+ 正文」按显式标签解析
    （标签归一为大写，正文 strip，可为空串）；否则按位置回退标签 A–Z、整串作正文。
    option_text 非 str / strip 后空 / position 非 int（含 bool）/
    position 不在 [0, 25] -> OMRError。
    """
    if not isinstance(option_text, str):
        raise OMRError(f"option text must be str, got {type(option_text).__name__}")
    if isinstance(position, bool) or not isinstance(position, int):
        raise OMRError(f"option position must be int, got {position!r}")
    if not 0 <= position <= 25:
        raise OMRError(f"option position out of label range A-Z: {position}")
    text = option_text.strip()
    if not text:
        raise OMRError("option text is blank")
    m = _OPT_RE.match(text)
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return _FALLBACK_LABELS[position], text


def field_label(number):
    """卷面题号 -> OMR 列名（"q" + str(题号)，规格 §3.3）。

    number 非 int（含 bool）或 < 1 -> OMRError。
    """
    if isinstance(number, bool) or not isinstance(number, int):
        raise OMRError(f"question number must be int, got {number!r}")
    if number < 1:
        raise OMRError(f"question number must be >= 1, got {number}")
    return FIELD_PREFIX + str(number)


def parse_field_ranges(numbers):
    """题号集合 -> 最短 OMRChecker fieldLabels 字段串列表（规格 §3.4，闭式）。

    输入去重升序后，连续段 a..b（a<b）输出 "qa..b"（含端点，同 OMRChecker
    "q1..10" -> q1..q10），孤立号输出 "qa"。numbers 非 list/tuple、元素非 int
    （含 bool）或 < 1 -> OMRError；空列表 -> []。
    """
    if not isinstance(numbers, (list, tuple)):
        raise OMRError(
            f"numbers must be a list, got {type(numbers).__name__}")
    nums = set()
    for n in numbers:
        if isinstance(n, bool) or not isinstance(n, int):
            raise OMRError(f"question number must be int, got {n!r}")
        if n < 1:
            raise OMRError(f"question number must be >= 1, got {n}")
        nums.add(n)
    ordered = sorted(nums)
    out = []
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1] == ordered[j] + 1:
            j += 1
        if j == i:
            out.append(FIELD_PREFIX + str(ordered[i]))
        else:
            out.append(f"{FIELD_PREFIX}{ordered[i]}..{ordered[j]}")
        i = j + 1
    return out


def natural_sort_key(label):
    """列名 -> 自然排序键 [前缀 str, 数字 int]（规格 §3.5，OMRChecker 同款）。

    label 非非空 str -> OMRError；无数字尾缀时数字位为 0。
    """
    if not isinstance(label, str) or not label:
        raise OMRError(f"column label must be a non-empty str, got {label!r}")
    groups = _NATURAL_RE.findall(label)
    prefix, suffix = groups[0] if groups else ("", "")
    return [prefix, int(suffix) if suffix else 0]


def _require_str_attr(obj, attr, what):
    value = getattr(obj, attr, None)
    if not isinstance(value, str):
        raise OMRError(f"{what} must be str, got {type(value).__name__}")
    return value


def _option_pairs(item, item_id):
    """choice 题的 options -> [(标签, 正文)…]（≥2 项、标签唯一、≤MAX_BUBBLES）。"""
    raw_options = getattr(item, "options", None)
    if not isinstance(raw_options, (list, tuple)) or len(raw_options) < 2:
        raise OMRError(f"item {item_id} choice needs >=2 options")
    pairs = [parse_option(o, i) for i, o in enumerate(raw_options)]
    labels = [label for label, _ in pairs]
    if len(set(labels)) != len(labels):
        raise OMRError(f"item {item_id} duplicate option labels: {labels}")
    if len(pairs) > MAX_BUBBLES:
        raise OMRError(
            f"item {item_id} has {len(pairs)} options, max is {MAX_BUBBLES}")
    return pairs


def build_answer_sheet(paper, bank):
    """Paper + bank -> answer-sheet.json dict（规格 §3.6，全部规则闭式）。

    校验顺序冻结：paper 表面 -> bank 索引 -> sections 规整化（空则回退
    paper.item_ids）-> 逐节逐题（卷面顺序，首个坏题报错）-> 空卷门。
    学生面文档：不含 answer/solution/stem/misconceptions 等作答依据；
    fill/solve 题不出涂点（manual 模式）。纯函数：输出全部为新构造容器。
    """
    # V1：paper 表面
    paper_id = _require_str_attr(paper, "paper_id", "paper.paper_id")
    title = _require_str_attr(paper, "title", "paper.title")
    raw_sections = getattr(paper, "sections", None)
    if not isinstance(raw_sections, (list, tuple)):
        raise OMRError("paper.sections must be a list")
    sec_list = list(raw_sections)

    # V2：bank 索引
    items_fn = getattr(bank, "items", None)
    if not callable(items_fn):
        raise OMRError("bank must expose items()")
    seq = items_fn()
    try:
        iterator = iter(seq)
    except TypeError:
        raise OMRError("bank.items() must return an iterable") from None
    index = {}
    for it in iterator:
        iid = getattr(it, "id", None)
        if not isinstance(iid, str) or not iid.strip():
            raise OMRError("bank item id must be a non-empty str")
        if iid in index:
            raise OMRError(f"duplicate item id in bank: {iid}")
        index[iid] = it

    # V3：sections 规整化（空 -> paper.item_ids 单一隐式节）
    if not sec_list:
        fallback_ids = getattr(paper, "item_ids", None)
        if not isinstance(fallback_ids, (list, tuple)):
            raise OMRError("paper.item_ids must be a list when sections is empty")
        sec_list = [{"kp_name": "", "item_ids": list(fallback_ids)}]
    normalized = []
    for sec in sec_list:
        if not isinstance(sec, dict):
            raise OMRError("paper.sections entries must be dicts")
        ids = sec.get("item_ids")
        if not isinstance(ids, (list, tuple)):
            raise OMRError(f"section {sec.get('kp_id', '')!r} item_ids must be a list")
        for iid in ids:
            if not isinstance(iid, str) or not iid.strip():
                raise OMRError(f"section item id must be non-empty str, got {iid!r}")
        name = ""
        if "kp_name" in sec:
            v = sec["kp_name"]
            if not isinstance(v, str):
                raise OMRError("section kp_name must be str")
            name = v
        normalized.append({"item_ids": list(ids)})

    # V4：逐节逐题构建（题号 1..N 贯穿全卷；首个坏题即报错）
    questions = []
    section_index_of = []  # 题目 -> 所属节下标（fieldBlocks 分段用）
    for sec_idx, sec in enumerate(normalized):
        for iid in sec["item_ids"]:
            item = index.get(iid)
            if item is None:
                raise OMRError(f"unknown item id in paper: {iid}")
            item_type = getattr(item, "item_type", None)
            if item_type not in _ITEM_TYPES:
                raise OMRError(f"unknown item_type for {iid}: {item_type!r}")
            number = len(questions) + 1
            if item_type == "choice":
                pairs = _option_pairs(item, iid)
                questions.append({
                    "number": number,
                    "item_id": iid,
                    "mode": MODE_OMR,
                    "field_label": field_label(number),
                    "bubble_values": [label for label, _ in pairs],
                    "options": [{"label": label, "text": text}
                                for label, text in pairs],
                })
            else:  # fill/solve：无涂点，手工/OCR 录入（options 字段即使有值也忽略）
                questions.append({
                    "number": number,
                    "item_id": iid,
                    "mode": MODE_MANUAL,
                    "field_label": None,
                    "bubble_values": [],
                    "options": [],
                })
            section_index_of.append(sec_idx)

    # V5：空卷门
    if not questions:
        raise OMRError("empty paper: no questions to map")

    # V6：outputColumns（自然排序）+ fieldBlocks 分段
    omr_questions = [q for q in questions if q["mode"] == MODE_OMR]
    output_columns = sorted(
        (q["field_label"] for q in omr_questions), key=natural_sort_key)
    blocks = []

    def _close_run(run):
        if run:
            blocks.append({
                "name": f"block{len(blocks) + 1}",
                "field_labels": parse_field_ranges([q["number"] for q in run]),
                "bubble_values": list(run[0]["bubble_values"]),
                "direction": BLOCK_DIRECTION,
            })

    run = []
    prev_bubbles = None
    prev_sec_idx = None
    for q, sec_idx in zip(questions, section_index_of):
        if q["mode"] != MODE_OMR:
            _close_run(run)
            run = []
            prev_bubbles = None
            prev_sec_idx = None
            continue
        bubbles = tuple(q["bubble_values"])
        if run and (bubbles != prev_bubbles or sec_idx != prev_sec_idx):
            _close_run(run)
            run = []
        run.append(q)
        prev_bubbles = bubbles
        prev_sec_idx = sec_idx
    _close_run(run)

    omr_count = len(omr_questions)
    return {
        "format_version": OMR_VERSION,
        "paper_id": paper_id,
        "title": title,
        "question_count": len(questions),
        "omr_count": omr_count,
        "manual_count": len(questions) - omr_count,
        "questions": questions,
        "output_columns": output_columns,
        "field_blocks": blocks,
    }


def parse_omr_results(csv_text):
    """OMRChecker Results CSV 文本 -> 行 dict 列表（规格 §3.7）。

    行 = {"file_id": 原文, "values": {除 file_id 外全部列: 单元格原文}}。
    首字符 BOM 剥除；空行跳过；首个非空行为表头（非空 str、互不重复、必含
    file_id 列）；数据行长/短于表头、file_id strip 后为空 -> OMRError。
    表头之后无数据行 -> []。score 列照录字符串（判分不靠它）。
    """
    if not isinstance(csv_text, str):
        raise OMRError(f"csv_text must be str, got {type(csv_text).__name__}")
    if csv_text.startswith(chr(0xFEFF)):  # BOM U+FEFF（避免源码里放不可见字面量）
        csv_text = csv_text[1:]
    rows = [r for r in csv.reader(io.StringIO(csv_text)) if r]
    if not rows:
        raise OMRError("no header row in results csv")
    header = rows[0]
    for cell in header:
        if not isinstance(cell, str) or not cell:
            raise OMRError("results csv header cells must be non-empty str")
    if len(set(header)) != len(header):
        raise OMRError(f"duplicate columns in results csv header: {header}")
    if RESULTS_FILE_ID_COLUMN not in header:
        raise OMRError(
            f"results csv header must contain {RESULTS_FILE_ID_COLUMN!r}: {header}")
    file_id_idx = header.index(RESULTS_FILE_ID_COLUMN)
    out = []
    for row in rows[1:]:
        if len(row) != len(header):
            raise OMRError(
                f"ragged row in results csv: {len(row)} cells, "
                f"header has {len(header)}")
        file_id = row[file_id_idx]
        if not file_id.strip():
            raise OMRError("results csv row has blank file_id")
        values = {col: cell for col, cell in zip(header, row)
                  if col != RESULTS_FILE_ID_COLUMN}
        out.append({"file_id": file_id, "values": values})
    return out


def _resolve_answer_index(item, item_id, pairs):
    """题目标答 -> 选项下标：标签优先（strip+大写），其后正文（strip+大写）。

    两路都无命中 -> OMRError（题目本身坏，不允许静默全错）。
    """
    answer = getattr(item, "answer", None)
    if not isinstance(answer, str):
        raise OMRError(f"item {item_id} answer must be str, "
                       f"got {type(answer).__name__}")
    target = answer.strip().upper()
    for idx, (label, _) in enumerate(pairs):
        if label == target:
            return idx
    for idx, (_, text) in enumerate(pairs):
        if text.strip().upper() == target:
            return idx
    raise OMRError(f"item {item_id}: answer not among options")


def to_responses(row, sheet, bank):
    """一张卡的 OMR 涂点 -> Response 列表（规格 §3.8，卷面 omr 题序）。

    校验顺序冻结：sheet 表面 -> row 表面 -> bank 索引 -> 逐题还原（对位门 ->
    涂点归一 -> 未涂/单涂/多涂三路）。manual 题跳过不产 Response；
    response_ms 恒 None；单涂的 learner_answer = 该选项在 bank options 中的
    原文全串（与 grading.grade_choice 的标签/全文两路解析都同判）。
    未知涂点字符 / sheet-bank 漂移 / answer 无法解析 -> OMRError，绝不静默错位判分。
    """
    # V1：sheet 表面
    if not isinstance(sheet, dict):
        raise OMRError(f"sheet must be dict, got {type(sheet).__name__}")
    if sheet.get("format_version") != OMR_VERSION:
        raise OMRError(
            f"sheet format_version must be {OMR_VERSION!r}, "
            f"got {sheet.get('format_version')!r}")
    questions = sheet.get("questions")
    if not isinstance(questions, (list, tuple)):
        raise OMRError("sheet.questions must be a list")

    # V2：row 表面
    if not isinstance(row, dict):
        raise OMRError(f"row must be dict, got {type(row).__name__}")
    values = row.get("values")
    if not isinstance(values, dict):
        raise OMRError("row must carry a 'values' dict")
    for key, cell in values.items():
        if not isinstance(key, str) or not isinstance(cell, str):
            raise OMRError("row values must map str columns to str cells")

    # V3：bank 索引
    items_fn = getattr(bank, "items", None)
    if not callable(items_fn):
        raise OMRError("bank must expose items()")
    index = {}
    for it in items_fn():
        iid = getattr(it, "id", None)
        if not isinstance(iid, str) or not iid.strip():
            raise OMRError("bank item id must be a non-empty str")
        if iid in index:
            raise OMRError(f"duplicate item id in bank: {iid}")
        index[iid] = it

    # V4：逐题还原
    seen_numbers = set()
    seen_labels = set()
    results = []
    for question in questions:
        if not isinstance(question, dict):
            raise OMRError("sheet.questions entries must be dicts")
        number = question.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise OMRError(f"sheet question number must be int >= 1, got {number!r}")
        if number in seen_numbers:
            raise OMRError(f"duplicate question number in sheet: {number}")
        seen_numbers.add(number)
        item_id = question.get("item_id")
        if not isinstance(item_id, str) or not item_id.strip():
            raise OMRError(
                f"sheet question {number} item_id must be non-empty str")
        mode = question.get("mode")
        if mode == MODE_MANUAL:
            continue  # 主观题走 grading 模块与人工/OCR 渠道，适配层不越界
        if mode != MODE_OMR:
            raise OMRError(f"sheet question {number} unknown mode: {mode!r}")
        column = question.get("field_label")
        if not isinstance(column, str) or not column:
            raise OMRError(
                f"omr question {number} field_label must be non-empty str")
        if column in seen_labels:
            raise OMRError(f"duplicate OMR column in sheet: {column}")
        seen_labels.add(column)

        item = index.get(item_id)
        if item is None:
            raise OMRError(f"unknown item id in sheet: {item_id}")
        if getattr(item, "item_type", None) != "choice":
            raise OMRError(
                f"item {item_id} is not choice in bank but sheet marks it omr")
        pairs = _option_pairs(item, item_id)
        labels = [label for label, _ in pairs]
        raw_options = list(item.options)
        bubble_values = question.get("bubble_values")
        if not isinstance(bubble_values, (list, tuple)) or \
                list(bubble_values) != labels:
            raise OMRError(
                f"item {item_id} bubble_values {bubble_values!r} do not match "
                f"bank option labels {labels}")

        marked = values.get(column)
        if marked is None:
            raise OMRError(f"missing OMR column in results row: {column}")
        if not isinstance(marked, str):
            raise OMRError(f"OMR cell {column} must be str, "
                           f"got {type(marked).__name__}")
        text = marked.strip()
        if not text:
            # 未涂：无作答证据，判错但不伪造作答内容
            results.append(Response(item_id=item_id, correct=False,
                                    learner_answer=None, response_ms=None))
            continue
        normalized = text.upper()
        for ch in normalized:
            if ch not in labels:
                raise OMRError(
                    f"unknown mark {ch!r} in OMR cell {column} "
                    f"(bubble values: {labels})")
        if len(normalized) == 1:
            answer_idx = _resolve_answer_index(item, item_id, pairs)
            mark_idx = labels.index(normalized)
            results.append(Response(item_id=item_id,
                                    correct=(mark_idx == answer_idx),
                                    learner_answer=raw_options[mark_idx],
                                    response_ms=None))
        else:
            # 多涂：单选题多涂不判对，不猜；learner_answer 保留拼接串作证据
            results.append(Response(item_id=item_id, correct=False,
                                    learner_answer=normalized, response_ms=None))
    return results
