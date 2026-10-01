"""itembank_v2 —— 题库 schema v2（source / verification）完整性校验器。

冻结契约：specs/frozen/itembank_v2.spec.md（2026-09-29 定稿）。
纯函数内核：无 IO、无随机、无时钟、不读环境。
validate_item_v2 对任意输入不抛异常（I7）；validate_bank_v2 / source_counts /
verification_stats 对不可迭代入参 TypeError 原样传播（I11），对可迭代入参不抛异常。
仅依赖内建类型，不 import 任何模块（规格 §2：本模块不需要 xuexing.types）。
"""

SCHEMA_VERSION = 2
SOURCE_VALUES = ("original", "adapted", "llm_generated")


def _prefix(item):
    """I8：id 键存在按其值字面渲染（f-string，无 repr 引号，falsy/非 str 照渲染）；
    键缺失 → "<no-id>: "。"""
    if "id" in item:
        return f"{item['id']}: "
    return "<no-id>: "


def _source_stage_errors(item, p):
    """V1（source 完整性，原始值口径）→ V2（adapted 溯源强制），固定顺序累积。

    V1a：键缺失，或值为 str 且 strip 后为空（strip 仅用于空判）；
    V1b：值非 str（含 None）；
    V1c：非空 str 但原始字面值不在 SOURCE_VALUES（不 strip、不归一化大小写）；
    V2：source 原始值恰为 "adapted"（== 恰等，不 strip）才检查 source_ref。
    """
    errors = []
    source = item.get("source")
    if "source" not in item or (isinstance(source, str) and not source.strip()):
        errors.append(f"{p}missing source")  # V1a
    elif not isinstance(source, str):
        errors.append(f"{p}bad source {source!r}")  # V1b
    elif source not in SOURCE_VALUES:
        errors.append(f"{p}bad source {source!r}")  # V1c：原始字面值判定
    if source == "adapted":  # V2：原始值恰等才触发；其他情形 source_ref 不检查
        ref = item.get("source_ref")
        if not isinstance(ref, str) or not ref.strip():
            errors.append(f"{p}adapted requires non-empty source_ref")
    return errors


def _record_errors(record, p):
    """verification 记录目录：C1 → C2 → C3 → C4。

    门控：C2/C3 仅在 C1 未触发（agents 为 list 且 len(agents) >= 2）时评估，
    绝不对非 list 入参迭代求值；C4 三条恒独立评估、与门控无关。
    C2：逐元素（列表序）非 str / 带首尾空白 / strip 后空，各报一条；
    C3：agents 全部 str 元素按原始字面值判重（不 strip、含 C2 坏元素），至多一条，
        恒在全部 C2 消息之后；
    C4a/C4b/C4c：answers_agree 缺失 / 非 bool / 恰为 False 各有专属消息。
    """
    errors = []
    agents = record.get("agents")
    gated = not isinstance(agents, list) or len(agents) < 2
    if gated:  # C1
        errors.append(f"{p}verification needs >=2 agents")
    else:
        for el in agents:  # C2：列表序逐元素
            if not isinstance(el, str) or el != el.strip() or not el.strip():
                errors.append(f"{p}bad verification agent {el!r}")
        seen = set()
        duplicated = False
        for el in agents:  # C3：全部 str 元素的原始字面值判重
            if isinstance(el, str):
                if el in seen:
                    duplicated = True
                seen.add(el)
        if duplicated:
            errors.append(f"{p}duplicate verification agents")
    if "answers_agree" not in record:  # C4a（恒评估）
        errors.append(f"{p}verification missing answers_agree")
    else:
        agree = record["answers_agree"]
        if not isinstance(agree, bool):  # C4b
            errors.append(f"{p}bad answers_agree {agree!r}")
        elif agree is False:  # C4c
            errors.append(f"{p}verification not passed")
    return errors


def _verification_stage_errors(item, p):
    """V3：llm_generated 入库门 → 记录形状 → 记录目录。

    V3a：verification 缺失或 None（二者等价）且 source 原始值恰为 "llm_generated"；
    V3b：非 None 且非 dict；
    V3c：为 dict 时逐条记录检查（_record_errors）。
    """
    errors = []
    verification = item.get("verification")
    if verification is None:
        if item.get("source") == "llm_generated":  # V3a
            errors.append(f"{p}llm_generated requires verification")
        return errors
    if not isinstance(verification, dict):  # V3b
        errors.append(f"{p}bad verification {verification!r}")
        return errors
    errors.extend(_record_errors(verification, p))  # V3c
    return errors


def validate_item_v2(item):
    """单题 v2 完整性校验：对任意输入不抛异常，返回 0..n 条 str 消息。

    非 dict 输入只返回 ["item is not a dict"]；规则按 V1→V2→V3 固定顺序累积、
    不短路、各规则独立评估实际值（I6）。
    """
    if not isinstance(item, dict):
        return ["item is not a dict"]
    p = _prefix(item)
    errors = _source_stage_errors(item, p)
    errors.extend(_verification_stage_errors(item, p))
    return errors


def validate_bank_v2(items):
    """逐题 validate_item_v2 并按输入原序拼接；不去重、不排序（I9）。

    入参不可迭代时 TypeError 原样传播（I11，不捕获不转消息）；
    可迭代时对任意元素不抛异常。
    """
    errors = []
    for item in items:
        errors.extend(validate_item_v2(item))
    return errors


def source_counts(items):
    """按 source 值计数：键恒为 SOURCE_VALUES 全集（canonical 顺序，含 0，I10）。

    只认原始 str 值恰等于 SOURCE_VALUES 成员的 source（与 V1c 同口径）；非 dict、
    键缺失、非 str/非法值不入桶。每次返回新 dict；不可迭代入参 TypeError 原样传播。
    """
    counts = {value: 0 for value in SOURCE_VALUES}
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        if isinstance(source, str) and source in SOURCE_VALUES:
            counts[source] += 1
    return counts


def verification_stats(items):
    """返回 (total, verified) 二元组：total = 元素总数（非 dict 也计入）；
    verified = verification 为 dict 且记录目录 C1..C4 零消息（与 source 无关）。
    不可迭代入参 TypeError 原样传播（I11）。
    """
    total = 0
    verified = 0
    for item in items:
        total += 1
        if not isinstance(item, dict):
            continue
        record = item.get("verification")
        if isinstance(record, dict) and not _record_errors(record, ""):
            verified += 1
    return (total, verified)
