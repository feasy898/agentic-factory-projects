"""题库 schema v2 校验器 —— source / verification 溯源与质检完整性。

冻结契约：specs/frozen/itembank_v2.spec.md。四个纯函数，仅依赖内建类型：
- validate_item_v2：单题校验，任意输入不抛异常，返回 0..n 条 str 消息；
- validate_bank_v2 / source_counts / verification_stats：消费可迭代入参，
  不可迭代时 TypeError 原样传播（I11），对可迭代入参的任意元素不抛异常。

消息前缀 p = id 字面渲染（f-string，无 repr 引号；缺失 → "<no-id>: "）。
错误消息中嵌入的违规值一律经 repr 渲染。
"""

SCHEMA_VERSION = 2
SOURCE_VALUES = ("original", "adapted", "llm_generated")

_NOT_A_DICT = "item is not a dict"


def _prefix(item):
    # id 键存在按值字面渲染（含 falsy/非 str/dict）；键缺失 → "<no-id>: "
    if "id" in item:
        return f"{item['id']}: "
    return "<no-id>: "


def _record_errors(record):
    """verification 记录目录 C1..C4，返回不带前缀的消息尾段列表（按目录序累积）。

    门控：C1 恒评估；C2/C3 仅在 C1 未触发（agents 为 list 且 len >= 2）时评估；
    C4 三条恒独立评估、与 C1 门控无关。C3 判重比较域 = agents 全部 str 元素的
    原始字面值（不 strip、含违反 C2 的元素）。record.get 语义。
    """
    errors = []
    agents = record.get("agents")
    if not isinstance(agents, list) or len(agents) < 2:
        errors.append("verification needs >=2 agents")
    else:
        for el in agents:
            if not isinstance(el, str) or el != el.strip() or not el.strip():
                errors.append(f"bad verification agent {el!r}")
        seen = set()
        for el in agents:
            if isinstance(el, str):
                if el in seen:
                    errors.append("duplicate verification agents")
                    break
                seen.add(el)
    if "answers_agree" not in record:
        errors.append("verification missing answers_agree")
    else:
        agree = record["answers_agree"]
        if not isinstance(agree, bool):
            errors.append(f"bad answers_agree {agree!r}")
        elif agree is False:
            errors.append("verification not passed")
    return errors


def validate_item_v2(item) -> list:
    """单题 v2 完整性校验：V1→V2→V3 固定顺序累积、不短路；非 dict 只返回一条。"""
    if not isinstance(item, dict):
        return [_NOT_A_DICT]
    p = _prefix(item)
    errors = []
    source = item.get("source")

    # V1a/V1b/V1c 条件互斥（缺失或空串 / 非 str / 形状合法但枚举外），同消息合并 V1b/V1c
    if "source" not in item or (isinstance(source, str) and not source.strip()):
        errors.append(f"{p}missing source")
    elif not isinstance(source, str) or source not in SOURCE_VALUES:
        errors.append(f"{p}bad source {source!r}")

    # V2：原始值恰等 "adapted"（==，不 strip）才检查 source_ref；其他 source 不检查
    if source == "adapted":
        ref = item.get("source_ref")
        if not isinstance(ref, str) or not ref.strip():
            errors.append(f"{p}adapted requires non-empty source_ref")

    # V3a/V3b/V3c 互斥：缺失或 None（且 llm_generated）/ 非 None 非 dict / dict 记录目录
    verification = item.get("verification")
    if verification is None:
        if source == "llm_generated":
            errors.append(f"{p}llm_generated requires verification")
    elif not isinstance(verification, dict):
        errors.append(f"{p}bad verification {verification!r}")
    else:
        errors.extend(f"{p}{tail}" for tail in _record_errors(verification))
    return errors


def validate_bank_v2(items) -> list:
    """逐题 validate_item_v2，按输入原序拼接；不去重不排序；空输入 → []。"""
    errors = []
    for item in items:
        errors.extend(validate_item_v2(item))
    return errors


def source_counts(items) -> dict:
    """按 source 计数：键恒为 SOURCE_VALUES 全集（canonical 序，含 0），每次新 dict。

    只认原始 str 值恰等于 SOURCE_VALUES 成员的 source；非 dict/缺键/非法值不入桶。
    """
    counts = {value: 0 for value in SOURCE_VALUES}
    for item in items:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        if isinstance(source, str) and source in SOURCE_VALUES:
            counts[source] += 1
    return counts


def verification_stats(items) -> tuple:
    """返回 (total, verified)：total 含非 dict 元素；verified = verification 为 dict
    且记录目录 C1..C4 零消息的条数（判定与 source 无关）。"""
    total = 0
    verified = 0
    for item in items:
        total += 1
        if not isinstance(item, dict):
            continue
        verification = item.get("verification")
        if isinstance(verification, dict) and not _record_errors(verification):
            verified += 1
    return (total, verified)
