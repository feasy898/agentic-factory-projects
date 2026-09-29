"""itembank_v2 —— 题库 schema v2：来源（source）与双代理验证（verification）字段校验器。

行为契约（specs/drafts/itembank_v2.spec.md，本文件为参考实现）。BACKLOG
「题库 schema v2」的确定性内核：

- source：题目来源枚举——original（原创）/ adapted（真题改编，必须附非空
  source_ref 注明出处）/ llm_generated（LLM 生成+验证，必须附通过的双代理
  独立解题一致性记录）；
- verification：双代理独立解题一致性记录——两个互不相同的独立解题者标识
  （agents，≥2 个无首尾空白的非空字符串、互不重复）+ 标答一致判定
  （answers_agree，必须恰为 True：记录为不一致的题不得留在库内）；
- 完整性语义：original/adapted 允许无 verification（null = 尚未做双代理验证，
  诚实缺口而非伪造记录）；llm_generated 必须带通过的记录（对应 README 的
  LLM 确定性入库门：未验证的生成内容不得入库）。

校验器是返回错误字符串列表的**全函数**：对任意输入对象不抛异常（域内只返回
0..n 条消息）；纯函数（无 IO、无随机、无时钟、不读环境），同输入同输出。
数据侧闭环由 tests/data/test_itembank_v2_data.py 与 tools/validate_knowledge.py
（--impl 范围外）承担；冻结模块 itembank.py 的 validate_item（R1..R9c 目录）
按其冻结规格保持不变，v2 完整性由本模块独立承担。

注入装载约束（同 misconception_coverage 规格 §2）：不用 from __future__ import
annotations——注解直接写真实对象；只依赖标准库。
"""

__all__ = [
    "SCHEMA_VERSION",
    "SOURCE_VALUES",
    "validate_item_v2",
    "validate_bank_v2",
    "source_counts",
    "verification_stats",
]

#: 题 schema 当前版本号。
SCHEMA_VERSION = 2

#: source 的合法取值（canonical 顺序，即统计与文档的固定顺序）。
SOURCE_VALUES = ("original", "adapted", "llm_generated")

#: id 键缺失时错误消息前缀使用的字面占位。
_NO_ID = "<no-id>"


def _prefix(item: dict) -> str:
    """错误消息前缀：f"{id}: "。id 键缺失 → "<no-id>: "；存在则按其值字面渲染
    （falsy/非 str 均照渲染，与冻结 itembank R1 探针的前缀风格一致）。"""
    if "id" in item:
        return f"{item['id']}: "
    return f"{_NO_ID}: "


def _record_errors(p: str, record: dict) -> list:
    """verification 记录（dict）的完整性检查；按固定顺序累积消息。"""
    errs: list = []
    agents = record.get("agents")
    if not isinstance(agents, list) or len(agents) < 2:
        errs.append(f"{p}verification needs >=2 agents")
    else:
        for el in agents:
            if not isinstance(el, str) or el != el.strip() or el.strip() == "":
                errs.append(f"{p}bad verification agent {el!r}")
        str_values = [el for el in agents if isinstance(el, str)]
        if len(set(str_values)) != len(str_values):
            errs.append(f"{p}duplicate verification agents")
    if "answers_agree" not in record:
        errs.append(f"{p}verification missing answers_agree")
    else:
        agree = record["answers_agree"]
        if not isinstance(agree, bool):
            errs.append(f"{p}bad answers_agree {agree!r}")
        elif agree is False:
            errs.append(f"{p}verification not passed")
    return errs


def validate_item_v2(item) -> list:
    """单题 schema v2 完整性校验。对任意输入不抛异常，返回 0..n 条错误消息。

    消息按固定规则目录 V1(source) → V2(source_ref) → V3(verification) 累积、
    不短路；非 dict 输入只返回一条无前缀消息 "item is not a dict"。
    """
    if not isinstance(item, dict):
        return ["item is not a dict"]
    p = _prefix(item)
    errs: list = []

    # V1 source：缺失/空白 → missing；非 str 或未知值 → bad source（repr）。
    if "source" not in item:
        errs.append(f"{p}missing source")
    else:
        source = item["source"]
        if not isinstance(source, str):
            errs.append(f"{p}bad source {source!r}")
        elif source.strip() == "":
            errs.append(f"{p}missing source")
        elif source not in SOURCE_VALUES:
            errs.append(f"{p}bad source {source!r}")

    # V2 source_ref：仅当 source 恰为 "adapted" 时要求非空 str（唯一消息）。
    if item.get("source") == "adapted":
        ref = item.get("source_ref")
        if not isinstance(ref, str) or ref.strip() == "":
            errs.append(f"{p}adapted requires non-empty source_ref")

    # V3 verification：null 等价于键缺失（= 尚未双代理验证）。
    verification = item.get("verification")
    if verification is None:
        if item.get("source") == "llm_generated":
            errs.append(f"{p}llm_generated requires verification")
    elif isinstance(verification, dict):
        errs.extend(_record_errors(p, verification))
    else:
        errs.append(f"{p}bad verification {verification!r}")
    return errs


def validate_bank_v2(items) -> list:
    """逐题累积校验：消息按输入原序拼接、不去重不排序（纯函数）。"""
    errs: list = []
    for item in items:
        errs.extend(validate_item_v2(item))
    return errs


def source_counts(items) -> dict:
    """按 source 统计条数。键恒为 SOURCE_VALUES 全集（canonical 顺序，含 0）；
    非 dict 元素与非法/缺失 source 不计入任何桶（完整性由校验器负责）。
    每次返回新 dict，修改返回值不影响后续调用。"""
    counts = {s: 0 for s in SOURCE_VALUES}
    for item in items:
        if isinstance(item, dict):
            source = item.get("source")
            if isinstance(source, str) and source in counts:
                counts[source] += 1
    return counts


def verification_stats(items) -> tuple:
    """(total, verified) 二元组：total = 元素总数；verified = 带完整且通过的
    双代理验证记录的条数（verification 为 dict 且记录检查零消息）。"""
    total = 0
    verified = 0
    for item in items:
        total += 1
        if isinstance(item, dict):
            verification = item.get("verification")
            if isinstance(verification, dict) and not _record_errors("", verification):
                verified += 1
    return (total, verified)
