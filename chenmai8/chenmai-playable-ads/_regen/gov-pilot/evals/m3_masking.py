"""M3 masking 验收：占位符稳定性/归一化等价/流式 fuzz/工具调用还原/碰撞/性能。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m3_masking

exit 0 = 通过。检查项（开发指令 §6 M3 eval 口径，阈值取 evals/thresholds.py M3 节）：
1. 稳定性：1000 值 × 同 session 重复请求占位符全等（含跨请求实例重建——纯 HMAC 确定性）；
   跨 session 占位符不同（session_id 参与摘要，设计如此）；
2. 归一化等价：全角/空格/分隔符/前缀变体 → 同 normalized → 同占位符（§5.3.2）；
3. 流式 fuzz：500 条随机 1–7 字符切块用例，``feed()*k + flush()`` 与整段还原全等；
4. 工具调用还原（T2.3 补：流式 hold-to-finish）：
   - 含中文参数 JSON 的 delta 序列（arguments 被切成任意碎片、占位符跨 chunk）：
     finish 前零发出、finish 时**单个 delta** 整体还原，JSON 可解析、原值在位、
     占位符零残留、中文逐字保真；
   - 显式跨块切分全扫描（占位符在每个位置被切开）+ 随机切块 fuzz；
   - 多工具并行（多 index 交错增量、id/name 仅首见）、无 index 归槽；
   - 流式 finalize 结果 == 非流式直接整体还原（restore_arguments）逐字相等；
   - 缓冲安全阀：超上限响亮失败（不静默截断）；
5. 碰撞：10 万值插入零最终碰撞（全部占位符唯一）；8 位 hex 抽样的重复对全部被
   插入期升位化解（升位数 == 重复值数）；插入期检测逻辑单测（8→10→12→拒绝）；
6. 性能：含 50 个占位符的 2000 字整段还原 < 20ms。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.thresholds import (  # noqa: E402
    MASK_CHUNK_MAX_BYTES,
    MASK_CHUNK_MIN_BYTES,
    MASK_COLLISION_PROBE_VALUES,
    MASK_RESTORE_MS_50PH_2000CH,
    MASK_STABILITY_VALUES,
    MASK_STREAM_FUZZ_CASES,
)
from masking.mapper import RESTORE_PATTERN, SessionMapper  # noqa: E402
from masking.normalize import normalize_value  # noqa: E402
from masking.remap import MAX_PLACEHOLDER_LEN, StreamRestorer  # noqa: E402
from masking.toolbuf import (  # noqa: E402
    MAX_ARGUMENTS_CHARS,
    ToolArgumentsOverflowError,
    ToolCallBuffer,
    restore_arguments,
)
from recognizers.models import EntityClass  # noqa: E402

RESULTS: list[tuple[bool, str]] = []

MASK_KEY = "cd" * 32
SESSION = "sess_m3_main"

ID_OK = "11010519491231002X"
PHONE_OK = "13800138000"
PERSON_OK = "张三"
ADDRESS_OK = "澄迈县老城镇示范街1号"


def _record(name: str, fn) -> None:
    try:
        detail = fn()
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _split_chars(text: str, rnd: random.Random,
                 lo: int = MASK_CHUNK_MIN_BYTES, hi: int = MASK_CHUNK_MAX_BYTES) -> list[str]:
    """把文本按 lo–hi 字符随机切块（模拟上游 SSE 增量；保证非空片段）。"""
    pieces: list[str] = []
    i = 0
    while i < len(text):
        n = rnd.randint(lo, hi)
        pieces.append(text[i : i + n])
        i += n
    return pieces


def _stable_values(count: int) -> list[tuple[EntityClass, str]]:
    """count 个确定性多类别值（占位符算法只关心 (类别, normalized) 对）。"""
    out: list[tuple[EntityClass, str]] = []
    makers = (
        (EntityClass.ID_CARD, lambda i: f"110105{1949 + i % 50:04d}{1 + i % 12:02d}{1 + i % 28:02d}{i % 10000:04d}"),
        (EntityClass.PHONE_MOBILE, lambda i: f"138{i:08d}"),
        (EntityClass.BANK_CARD, lambda i: f"62220212{i:010d}"),
        (EntityClass.EMAIL, lambda i: f"user{i}@chengmai.gov.cn"),
        (EntityClass.PERSON, lambda i: f"王小{i}"),
    )
    for i in range(count):
        etype, make = makers[i % len(makers)]
        out.append((etype, make(i)))
    return out


# ── 1. 稳定性（§6 M3：1000 值同 session 全等 / 跨 session 不同）────────
def step_stability() -> str:
    mapper = SessionMapper(SESSION, MASK_KEY.encode())
    # 跨请求实例重建：SessionMapper 无状态派生（纯 HMAC），同 session+key 必然同占位符
    mapper_replay = SessionMapper(SESSION, MASK_KEY.encode())
    cross_sessions = [SessionMapper(f"sess_m3_cross_{k}", MASK_KEY.encode()) for k in range(3)]
    for i, (etype, value) in enumerate(_stable_values(MASK_STABILITY_VALUES)):
        ph1, entry1 = mapper.placeholder_for(etype, value)
        ph2, entry2 = mapper.placeholder_for(etype, value)  # 同 session 重复请求
        if ph1 != ph2 or entry1.normalized != entry2.normalized or entry1 is not entry2:
            raise AssertionError(f"value#{i} repeat mismatch: {ph1!r} vs {ph2!r}")
        ph3, _ = mapper_replay.placeholder_for(etype, value)
        if ph3 != ph1:
            raise AssertionError(f"value#{i} replay-instance mismatch: {ph1!r} vs {ph3!r}")
        ph_cross, _ = cross_sessions[i % 3].placeholder_for(etype, value)
        if ph_cross == ph1:
            raise AssertionError(f"value#{i} cross-session collision: {ph1!r}")
        if mapper.lookup(ph1) != value or mapper.restore(f"前{ph1}后") != f"前{value}后":
            raise AssertionError(f"value#{i} restore mismatch")
    distinct = len({mapper.placeholder_for(e, v)[0] for e, v in _stable_values(MASK_STABILITY_VALUES)})
    if distinct != MASK_STABILITY_VALUES:
        raise AssertionError(f"distinct placeholders {distinct} != {MASK_STABILITY_VALUES}")
    return (f"{MASK_STABILITY_VALUES} values × repeat/replay identical; 3 cross-sessions all differ; "
            f"restore round-trip exact")


# ── 2. 归一化等价（§5.3.2：变体写法 → 同 normalized → 同占位符）────────
_EQUIV_CASES = [
    (EntityClass.PHONE_MOBILE, ["138 0013 8000", "１３８００１３８０００", "+86 138-0013-8000", "138．0013．8000"], PHONE_OK),
    (EntityClass.ID_CARD, ["11010519491231002x", "110105 19491231 002X", "１１０１０５１９４９１２３１００２Ｘ"], ID_OK),
    (EntityClass.BANK_CARD, ["6222 0212 3456 7890", "６２２２．０２１２．３４５６．７８９０"], "6222021234567890"),
    (EntityClass.PLATE, ["琼A·12345", "琼a-12345", "琼Ａ１２３４５"], "琼A12345"),
    (EntityClass.DATE_BIRTH, ["1990年3月7日", "1990/3/7", "1990.03.07", "１９９０年０３月０７日"], "1990-03-07"),
    (EntityClass.EMAIL, ["Ｕｓｅｒ＠ChengMai.gov.cn", "User@ChengMai.gov.cn"], "User@ChengMai.gov.cn"),
]


def step_normalize_equivalence() -> str:
    mapper = SessionMapper("sess_m3_equiv", MASK_KEY.encode())
    checked = 0
    for etype, variants, expected in _EQUIV_CASES:
        placeholders = []
        for raw in variants:
            normalized = normalize_value(etype, raw)
            if normalized != expected:
                raise AssertionError(f"{etype.value} normalize({raw!r})={normalized!r} != {expected!r}")
            ph, entry = mapper.placeholder_for(etype, normalized)
            placeholders.append(ph)
            if entry.normalized != expected:
                raise AssertionError(f"entry.normalized {entry.normalized!r} != {expected!r}")
        if len(set(placeholders)) != 1:
            raise AssertionError(f"{etype.value} variants → {len(set(placeholders))} placeholders")
        if mapper.restore(placeholders[0]) != expected:
            raise AssertionError(f"restore {placeholders[0]!r} != {expected!r}")
        checked += len(variants)
    return f"{len(_EQUIV_CASES)} classes / {checked} variants → one placeholder each; restore = normalized"


# ── 3. 流式 fuzz（§6 M3：500 条随机切块还原全等）────────────────────
_FUZZ_TEMPLATES = [
    # (模板, [(类别, 原值)]) —— {n} 为槽位；覆盖占位符相邻/交错/起止边界/未知形状混排
    ("证件{x}与证件{y}，联系{p}或{q}；住址{a}。",
     [(EntityClass.ID_CARD, ID_OK), (EntityClass.ID_CARD, "110105194912311019"),
      (EntityClass.PHONE_MOBILE, PHONE_OK), (EntityClass.PHONE_MOBILE, "13900139000"),
      (EntityClass.ADDRESS, ADDRESS_OK)]),
    ("本段没有任何需要脱敏的内容，仅有普通公文用语。", []),
    ("{x}开头即占位符，末尾悬{y}。", [(EntityClass.PERSON, PERSON_OK), (EntityClass.PERSON, "李四")]),
    ("〔未知·deadbeef〕与{x}之间。〔未知·cafebabe〕结尾。",
     [(EntityClass.PHONE_MOBILE, PHONE_OK)]),
]


def _build_fuzz_pairs(mapper: SessionMapper) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for tpl, values in _FUZZ_TEMPLATES:
        filled_parts: list[str] = []
        spans: list[tuple[int, int, EntityClass, str]] = []
        cursor = 0
        for etype, value in values:
            open_at = tpl.index("{", cursor)
            close_at = tpl.index("}", open_at)
            filled_parts.append(tpl[cursor:open_at])
            start = sum(len(p) for p in filled_parts)
            filled_parts.append(value)
            spans.append((start, start + len(value), etype, value))
            cursor = close_at + 1
        filled_parts.append(tpl[cursor:])
        filled = "".join(filled_parts)
        masked, _entries = mapper.mask(filled, spans)
        if mapper.restore(masked) != filled:
            raise AssertionError(f"whole-restore sanity failed: {mapper.restore(masked)!r}")
        pairs.append((masked, filled))
    return pairs


def step_stream_fuzz() -> str:
    mapper = SessionMapper("sess_m3_fuzz", MASK_KEY.encode())
    pairs = _build_fuzz_pairs(mapper)
    for seed in range(MASK_STREAM_FUZZ_CASES):
        rnd = random.Random(seed)
        masked, filled = pairs[seed % len(pairs)]
        restorer = StreamRestorer(mapper.lookup)
        out = "".join(restorer.feed(p) for p in _split_chars(masked, rnd))
        out += restorer.flush()
        if out != filled:
            raise AssertionError(f"seed={seed} mismatch:\n out={out!r}\n exp={filled!r}")
        if restorer.pending_len > MAX_PLACEHOLDER_LEN:
            raise AssertionError(f"seed={seed} buffer exceeded cap: {restorer.pending_len}")
    return (f"{MASK_STREAM_FUZZ_CASES} chunked cases (1–{MASK_CHUNK_MAX_BYTES} chars) == whole-restore; "
            f"{len(_FUZZ_TEMPLATES)} templates incl. boundary/unknown-shape; buffer stayed ≤{MAX_PLACEHOLDER_LEN}")


# ── 4. 工具调用还原（T2.3：流式 hold-to-finish + 跨 chunk 切分）────────
TOOL_NAME = "query_lowincome_record"
TOOL_ARGS_OBJ = {
    "query": f"{PERSON_OK}的低保年审，身份证{ID_OK}，手机{PHONE_OK}，户籍地{ADDRESS_OK}",
    "options": {"year": 2026, "channel": "窗口"},
}
TOOL_ARGS_RAW = json.dumps(TOOL_ARGS_OBJ, ensure_ascii=False)


def _masked_tool_args(mapper: SessionMapper) -> str:
    """上游视角的 arguments：请求侧登记过的 PII 以占位符形状出现在参数里。"""
    masked = TOOL_ARGS_RAW
    for etype, value in ((EntityClass.PERSON, PERSON_OK), (EntityClass.ID_CARD, ID_OK),
                         (EntityClass.PHONE_MOBILE, PHONE_OK), (EntityClass.ADDRESS, ADDRESS_OK)):
        ph, _ = mapper.placeholder_for(etype, value)
        masked = masked.replace(value, ph)
    if not RESTORE_PATTERN.search(masked):
        raise AssertionError("fixture broken: no placeholder in masked arguments")
    return masked


def _expected_tool_args(mapper: SessionMapper, masked: str) -> str:
    expected = restore_arguments(mapper, masked)  # 非流式直接整体还原（§6 M3）
    if json.loads(expected) != TOOL_ARGS_OBJ:
        raise AssertionError(f"restored args not JSON-identical: {expected!r}")
    if RESTORE_PATTERN.search(expected):
        raise AssertionError(f"placeholder leaked in restored args: {expected!r}")
    return expected


def _feed_fragments(buf: ToolCallBuffer, index: int, fragments: list[str], *,
                    call_id: str = "call_m3_1", first_only_meta: bool = True) -> None:
    for j, frag in enumerate(fragments):
        call: dict[str, Any] = {"index": index}
        if first_only_meta and j == 0:
            call["id"] = call_id
            call["type"] = "function"
        fn: dict[str, Any] = {"arguments": frag}
        if first_only_meta and j == 0:
            fn["name"] = TOOL_NAME
        call["function"] = fn
        before = buf.held_events
        out = buf.feed([call])
        if out is not None:
            raise AssertionError("feed must produce no output (hold-to-finish)")
        if buf.held_events != before + 1:
            raise AssertionError(f"fragment#{j} not held")
    if buf.held_arguments(index) != "".join(fragments):
        raise AssertionError("held concatenation != fragment order join")


def _assert_single_restored_delta(deltas: list[dict], index: int, call_id: str,
                                  expected_args: str) -> None:
    if len(deltas) != 1:
        raise AssertionError(f"expected single delta for index={index}, got {len(deltas)}")
    call = deltas[0]
    if call["index"] != index or call.get("type") != "function" or call.get("id") != call_id:
        raise AssertionError(f"delta envelope mismatch: {call!r}")
    if call["function"]["name"] != TOOL_NAME:
        raise AssertionError(f"function name mismatch: {call['function']!r}")
    if call["function"]["arguments"] != expected_args:
        raise AssertionError(f"arguments mismatch:\n got={call['function']['arguments']!r}\n exp={expected_args!r}")


def step_tool_core() -> str:
    """含中文参数 JSON 的 delta 序列：hold-to-finish、单个 delta 整体还原。"""
    mapper = SessionMapper("sess_m3_tool", MASK_KEY.encode())
    masked = _masked_tool_args(mapper)
    expected = _expected_tool_args(mapper, masked)

    buf = ToolCallBuffer()
    fragments = _split_chars(masked, random.Random(0))
    _feed_fragments(buf, 0, fragments, call_id="call_m3_core")
    if not buf:
        raise AssertionError("buffer should be non-empty while holding")
    fragment_count = buf.held_events
    deltas = buf.finalize(mapper)
    _assert_single_restored_delta(deltas, 0, "call_m3_core", expected)
    # finalize 幂等清空：重复收尾返回空表
    if buf or buf.finalize(mapper) != []:
        raise AssertionError("buffer not cleared after finalize")
    # 流式整体还原 == 非流式直接整体还原（逐字相等）
    if deltas[0]["function"]["arguments"] != mapper.restore(masked):
        raise AssertionError("streamed finalize != whole-restore")
    return (f"args {len(masked)} chars in {fragment_count} fragments → single delta; "
            "JSON exact, Chinese intact, zero placeholder; hold-to-finish; finalize idempotent")


def step_tool_cross_chunk() -> str:
    """显式跨块切分全扫描（占位符在每个位置被切开）+ 随机切块 fuzz + 多工具并行。"""
    mapper = SessionMapper("sess_m3_tool2", MASK_KEY.encode())
    masked = _masked_tool_args(mapper)
    expected = _expected_tool_args(mapper, masked)

    # 1) 两块切分全扫描：切点扫过全部位置（含占位符内部/JSON 结构字符处）
    for cut in range(1, len(masked)):
        buf = ToolCallBuffer()
        buf.feed([{"index": 0, "id": "call_x", "type": "function",
                   "function": {"name": TOOL_NAME, "arguments": masked[:cut]}}])
        buf.feed([{"index": 0, "function": {"arguments": masked[cut:]}}])
        deltas = buf.finalize(mapper)
        if deltas[0]["function"]["arguments"] != expected:
            raise AssertionError(f"cut={cut} restore mismatch: {deltas[0]['function']['arguments']!r}")

    # 2) 随机切块 fuzz：任意 1–7 字符碎片逐 delta 喂入
    for seed in range(200):
        rnd = random.Random(1000 + seed)
        buf = ToolCallBuffer()
        _feed_fragments(buf, 0, _split_chars(masked, rnd))
        deltas = buf.finalize(mapper)
        if deltas[0]["function"]["arguments"] != expected:
            raise AssertionError(f"fuzz seed={seed} mismatch")

    # 3) 多工具并行：两个 index 的增量交错到达，id/name 只在各自首块声明
    #    （两调用参数同形——会话映射共享，占位符相同；缓冲/还原按槽位独立）
    frags_a = _split_chars(masked, random.Random(7))
    frags_b = _split_chars(masked, random.Random(8))
    buf = ToolCallBuffer()
    for k in range(max(len(frags_a), len(frags_b))):
        if k < len(frags_a):
            call: dict[str, Any] = {"index": 0, "function": {"arguments": frags_a[k]}}
            if k == 0:
                call.update({"id": "call_a", "type": "function"})
                call["function"]["name"] = TOOL_NAME
            buf.feed([call])
        if k < len(frags_b):
            call_b: dict[str, Any] = {"index": 1, "function": {"arguments": frags_b[k]}}
            if k == 0:
                call_b.update({"id": "call_b", "type": "function"})
                call_b["function"]["name"] = TOOL_NAME
            buf.feed([call_b])
    deltas = buf.finalize(mapper)
    if [d["index"] for d in deltas] != [0, 1]:
        raise AssertionError(f"deltas not sorted/complete: {[d['index'] for d in deltas]}")
    _assert_single_restored_delta([deltas[0]], 0, "call_a", expected)
    _assert_single_restored_delta([deltas[1]], 1, "call_b", expected)

    # 4) 无 index 增量归槽 0；非 dict 元素跳过不炸
    buf = ToolCallBuffer()
    buf.feed(["garbage", {"id": "call_n", "function": {"name": TOOL_NAME, "arguments": masked}}])
    deltas = buf.finalize(mapper)
    if len(deltas) != 1 or deltas[0]["index"] != 0:
        raise AssertionError(f"no-index slotting broken: {deltas!r}")
    if deltas[0]["function"]["arguments"] != expected:
        raise AssertionError("no-index restore mismatch")
    return (f"exhaustive 2-way splits ({len(masked) - 1} cuts) + 200 fuzz seeds + "
            "2-tool interleave (multi-index, meta-first-fragment) + no-index slotting all exact")


def step_tool_edges() -> str:
    """缓冲安全阀（超限响亮失败不静默截断）与 restore_arguments 边界。"""
    mapper = SessionMapper("sess_m3_tool3", MASK_KEY.encode())
    masked = _masked_tool_args(mapper)
    if MAX_ARGUMENTS_CHARS < MASK_STABILITY_VALUES:
        raise AssertionError("safety valve implausibly small")
    buf = ToolCallBuffer(max_arguments_chars=16)
    buf.feed([{"index": 0, "function": {"arguments": masked[:10]}}])
    try:
        buf.feed([{"index": 0, "function": {"arguments": masked[10:]}}])
    except ToolArgumentsOverflowError:
        pass
    else:
        raise AssertionError("overflow valve did not fire")
    # 阀为绊线：追加后检查、抛错时缓冲状态原样保留（含触发块）供上层诊断，
    # 网关管线不捕获该异常即中断响应流；缓冲不被静默截断、也不半途清空
    if buf.held_arguments(0) != masked:
        raise AssertionError("overflow altered held state (expected intact tripwire)")
    if buf.finalize(mapper)[0]["function"]["arguments"] != _expected_tool_args(mapper, masked):
        raise AssertionError("post-overflow finalize not deterministic whole-restore")

    # 非流式直接整体还原：纯文本参数（非 JSON）原样替换；无占位符时原样返回
    plain = f"请核对{PERSON_OK}的材料。〔未知·deadbeef〕"
    if restore_arguments(mapper, plain) != f"请核对{PERSON_OK}的材料。〔未知·deadbeef〕":
        raise AssertionError("unknown placeholder must stay untouched")
    if restore_arguments(mapper, "无占位符原文") != "无占位符原文":
        raise AssertionError("no-placeholder passthrough broken")
    if restore_arguments(mapper, masked) != mapper.restore(masked):
        raise AssertionError("restore_arguments deviates from mapper.restore")
    return ("overflow valve raises loudly at cap (held prefix intact); "
            "restore_arguments: non-JSON/plain passthrough + unknown shape untouched")


# ── 5. 碰撞（§6 M3：10 万值插入零碰撞 + 插入期检测逻辑单测）────────────
def _digest8(session_id: str, type_value: str, normalized: str, key: bytes) -> str:
    msg = f"{session_id}\x1f{type_value}\x1f{normalized}"
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()[:8]


class _ForcedDigestMapper(SessionMapper):
    """白盒：强制指定若干值的摘要，确定性复现升位路径。"""

    def __init__(self, session_id: str, key: bytes, forced: dict[str, str]) -> None:
        super().__init__(session_id, key)
        self._forced = forced

    def _digest(self, type_value: str, normalized: str) -> str:  # noqa: ARG002 — 契约同形
        forced = self._forced.get(normalized)
        return forced if forced is not None else super()._digest(type_value, normalized)


def _placeholder_width(placeholder: str, label: str) -> int:
    body = placeholder.removeprefix("〔").removesuffix("〕")
    hexpart = body.removeprefix(label + "·")
    if len(hexpart) not in (8, 10, 12) or any(c not in "0123456789abcdef" for c in hexpart):
        raise AssertionError(f"malformed placeholder: {placeholder!r}")
    return len(hexpart)


def step_collision() -> str:
    label = EntityClass.PERSON.label
    key = MASK_KEY.encode()
    mapper = SessionMapper("sess_m3_collide", key)
    seen: set[str] = set()
    escalated = 0
    for i in range(MASK_COLLISION_PROBE_VALUES):
        ph, _ = mapper.placeholder_for(EntityClass.PERSON, f"人员{i:06d}")
        if ph in seen:
            raise AssertionError(f"final placeholder collision at value#{i}: {ph!r}")
        seen.add(ph)
        if _placeholder_width(ph, label) > 8:
            escalated += 1
    distinct8 = len({_digest8("sess_m3_collide", EntityClass.PERSON.value, f"人员{i:06d}", key)
                     for i in range(MASK_COLLISION_PROBE_VALUES)})
    expected_escalations = MASK_COLLISION_PROBE_VALUES - distinct8
    if escalated != expected_escalations:
        raise AssertionError(f"escalated={escalated} != digest8 duplicates={expected_escalations}")
    # 重复请求命中复用：二次插入不新增条目
    if len(mapper.entries()) != MASK_COLLISION_PROBE_VALUES:
        raise AssertionError(f"entry count {len(mapper.entries())} != {MASK_COLLISION_PROBE_VALUES}")

    # 插入期检测逻辑单测（确定性复现升位路径；同值复用走快路径，异值同摘要才升位）：
    m2 = _ForcedDigestMapper("sess_m3_force", key, {
        "甲": "aaaaaaaa" + "0" * 56,
        "乙": "aaaaaaaa" + "1" + "0" * 55,   # 与甲同 8 位（第 9 位异）→ 升 10
        "丙": "aaaaaaaa" + "2" + "0" * 55,   # 与甲同 8 位（另一 10 位前缀）→ 升 10
        "丁": "bbbbbbbb" + "0" * 56,
        "己": "bbbbbbbb" + "22" + "9" + "0" * 53,   # 与丁同 8 位 → 升 10（占住 …22）
        "戊": "bbbbbbbb" + "22" + "8" + "0" * 53,   # 8/10 位全被异值占 → 升 12
    })
    ph_jia, _ = m2.placeholder_for(EntityClass.PERSON, "甲")
    ph_yi, _ = m2.placeholder_for(EntityClass.PERSON, "乙")
    ph_yi_again, _ = m2.placeholder_for(EntityClass.PERSON, "乙")   # 同值再次到达 → 复用
    ph_bing, _ = m2.placeholder_for(EntityClass.PERSON, "丙")
    ph_ding, _ = m2.placeholder_for(EntityClass.PERSON, "丁")
    ph_ji, _ = m2.placeholder_for(EntityClass.PERSON, "己")
    ph_wu, _ = m2.placeholder_for(EntityClass.PERSON, "戊")
    if _placeholder_width(ph_jia, label) != 8:
        raise AssertionError("甲 should stay at width 8")
    if _placeholder_width(ph_yi, label) != 10 or ph_yi == ph_jia:
        raise AssertionError("乙 should escalate to width 10")
    if ph_yi_again != ph_yi:
        raise AssertionError("乙 (same value re-request) should reuse its placeholder")
    if _placeholder_width(ph_bing, label) != 10 or len({ph_jia, ph_yi, ph_bing}) != 3:
        raise AssertionError("丙 should escalate to width 10, distinct from 甲/乙")
    if _placeholder_width(ph_ding, label) != 8:
        raise AssertionError("丁 should stay at width 8")
    if _placeholder_width(ph_ji, label) != 10:
        raise AssertionError("己 should escalate to width 10")
    if _placeholder_width(ph_wu, label) != 12 or len({ph_ding, ph_ji, ph_wu}) != 3:
        raise AssertionError("戊 should escalate to width 12, distinct from 丁/己")
    # 8→10→12 全撞（逐级被异值占住）→ 拒绝：庚辛共用摘要前缀，三档宽度均已名花有主
    m3 = _ForcedDigestMapper("sess_m3_force3", key, {
        "a": "dddddddd" + "0" * 56,                      # 落 8 位
        "b": "dddddddd" + "ee" + "0" * 54,               # 8 撞 → 落 10 位
        "c": "dddddddd" + "ee" + "ff" + "0" * 52,        # 8/10 撞 → 落 12 位
        "辛": "dddddddd" + "ee" + "ff" + "9" + "0" * 51,  # 8/10/12 全撞 → 拒绝
    })
    m3.placeholder_for(EntityClass.PERSON, "a")
    m3.placeholder_for(EntityClass.PERSON, "b")
    m3.placeholder_for(EntityClass.PERSON, "c")
    try:
        m3.placeholder_for(EntityClass.PERSON, "辛")
    except RuntimeError:
        pass
    else:
        raise AssertionError("unresolved 12-width collision must raise")
    return (f"{MASK_COLLISION_PROBE_VALUES} inserts → 0 final collisions "
            f"(digest8 duplicate values {expected_escalations} = escalated {escalated}); "
            "8→10 escalate / same-value reuse / 8+10→12 escalate / unresolved→RuntimeError all verified")


# ── 6. 性能（§6 M3：含 50 占位符的 2000 字还原 < 20ms）───────────────
def step_performance() -> str:
    mapper = SessionMapper("sess_m3_perf", MASK_KEY.encode())
    filler = "低保对象名单公示，请联系镇民政办核实信息后再办。"
    original_parts: list[str] = []
    spans: list[tuple[int, int, EntityClass, str]] = []
    cursor = 0
    for k in range(50):
        piece = f"对象{k}联系人电话"
        original_parts.append(piece)
        start = cursor + len(piece)
        phone = f"139{k:08d}"
        original_parts.append(phone)
        spans.append((start, start + len(phone), EntityClass.PHONE_MOBILE, phone))
        cursor = start + len(phone)
    original = "".join(original_parts)
    while len(original) + sum(3 for _ in spans) < 2000:  # 占位符比原值多 3 字/个
        original += filler
    masked, _ = mapper.mask(original, spans)
    hits = RESTORE_PATTERN.findall(masked)
    if len(hits) != 50:
        raise AssertionError(f"fixture placeholders {len(hits)} != 50")
    if len(masked) < 2000:
        raise AssertionError(f"fixture too short: {len(masked)}")
    if mapper.restore(masked) != original:
        raise AssertionError("restore sanity failed")

    runs = 50
    started = time.perf_counter()
    for _ in range(runs):
        mapper.restore(masked)
    elapsed_ms = (time.perf_counter() - started) / runs * 1000
    if elapsed_ms >= MASK_RESTORE_MS_50PH_2000CH:
        raise AssertionError(f"restore {elapsed_ms:.2f}ms >= {MASK_RESTORE_MS_50PH_2000CH}ms")
    return (f"{len(masked)} chars / 50 placeholders restore mean {elapsed_ms:.3f}ms "
            f"< {MASK_RESTORE_MS_50PH_2000CH}ms ({runs} runs)")


STEPS = (
    ("mask:stability-1000", step_stability),
    ("mask:normalization-equivalence", step_normalize_equivalence),
    ("remap:stream-fuzz-500", step_stream_fuzz),
    ("tool:hold-to-finish-core", step_tool_core),
    ("tool:cross-chunk-sweep-fuzz-multi", step_tool_cross_chunk),
    ("tool:overflow-valve-nonstream", step_tool_edges),
    ("collide:100k-insert-escalation", step_collision),
    ("perf:restore-50ph-2000ch", step_performance),
)


def main() -> int:
    for name, fn in STEPS:
        _record(name, fn)
    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M3 MASKING: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
