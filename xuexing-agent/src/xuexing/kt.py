"""kt —— KT 时序追踪（同一学习者跨多次会话的掌握度轨迹）。

把带时间戳的作答事件流折叠成一条逐事件的掌握度轨迹：每走到一个新事件，
先对所有有直接证据的知识点施加遗忘曲线衰减（指数半衰期），再按 diagnosis
同族的猜感感知 odds 贝叶斯更新写入新证据。纯函数折叠：重放任意前缀得到
的最后一个快照，与全程轨迹对应位置的快照逐位相等（可重放）。
除 Profile.updated_at 外同输入同输出。

证据强度语义与 diagnosis 保持同族（slip 由难度滑出、猜测率感知、主知识点
全权重/次要知识点半权重、odds 下限护栏），但本模块不做先序平滑——那是
diagnosis 的职责；本模块也不 import 任何其他 xuexing 模块。

XES3G5M 对接：官方发行版（ai4ed/XES3G5M，NeurIPS 2023 D&B）为 pyKT 风格
CSV 序列，字段 uid / questions / responses("1"/"0") / timestamps(毫秒) /
selectmasks("-1" 为填充忽略)。xes3g5m_row / load_xes3g5m_csv 负责换成
KTEvent 流；知识点归属仍走本仓库 itembank 的题目-知识点映射（item_id）。
"""
# 注入装载约束（见 specs/drafts/kt.spec.md §2）：不用 from __future__ import annotations
# ——dataclass 字符串注解在 _regen_* 顶层模块名下会触发未受保护的 sys.modules 解析。
import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from xuexing.types import Profile

__all__ = [
    "KTEvent",
    "KTSnapshot",
    "trace",
    "to_profile",
    "xes3g5m_row",
    "load_xes3g5m_csv",
]

# ---- 与 diagnosis 同族的数值常量（specs/drafts/kt.spec.md §3 冻结）----
_ODDS_FLOOR = 1e-4      # odds 分子/分母、负证据似然比的统一下限
_GUESS_FLOOR = 0.02     # 猜测率下限
_GUARD_STEP = 0.05      # 高猜度护栏：p_m 抬升量
_GUARD_CAP = 0.99       # 高猜度护栏：p_m 封顶
_UPDATED_AT_FMT = "%Y-%m-%dT%H:%M:%SZ"

_MS_PER_DAY = 86400000.0   # XES3G5M timestamps 为毫秒级
_MASK_PAD = "-1"           # selectmasks 中唯一表示"剔除该位"的 token
_SEQ_SPLIT = re.compile(r"[^\s,]+")  # 序列单元格：空白或逗号分隔均可


# ---------- 数据类型 ----------

@dataclass
class KTEvent:
    """一次带时间的作答。day 是相对轨迹起点的天数（float，非负，非降序）。

    不绑定绝对时钟：调用方自选起点（XES3G5M 适配取首条有效时间戳为 day 0），
    这保证模块确定性——不读系统时钟。
    """

    item_id: str
    correct: bool
    day: float


@dataclass
class KTSnapshot:
    """轨迹上的一点：第 i 个有效事件处理完后的全量掌握度状态（round 到 6 位）。"""

    day: float
    item_id: str
    correct: bool
    mastery: dict[str, float]
    evidence: dict[str, int]


# ---------- 内部：与 diagnosis 同族的证据强度 ----------

def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _likelihood_ratio(item) -> tuple[float, float]:
    """单题似然比 (lr_c, lr_w)。P(错|会)=clamp01(0.05+0.20*难度)，猜感感知，
    高猜度护栏——全部与 diagnosis 逐条一致，使同一题在两个引擎里证据力相同。"""
    p_nm = max(item.effective_guess(), _GUESS_FLOOR)
    p_m = _clamp01(1.0 - (0.05 + 0.20 * item.difficulty))
    if p_m <= p_nm:  # 高猜度护栏
        p_m = min(p_m + _GUARD_STEP, _GUARD_CAP)
    lr_c = p_m / p_nm
    lr_w = (1.0 - p_m) / max(1.0 - p_nm, _ODDS_FLOOR)
    return lr_c, lr_w


def _as_day(value, what: str) -> float:
    """day 字段校验：数字（bool 除外）、非负；NaN 经链式比较拒绝。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number, got {type(value).__name__}")
    d = float(value)
    if not (d >= 0.0):  # NaN 的任何比较均为 False，落入此支被拒绝
        raise ValueError(f"{what} must be a finite number >= 0")
    return d


# ---------- 核心：轨迹折叠 ----------

def trace(
    events: list[KTEvent],
    bank,
    graph,
    prior: float = 0.5,
    half_life_days: float = 7.0,
) -> list[KTSnapshot]:
    """按事件顺序折叠出掌握度轨迹（每个有效事件一个快照）。

    步骤（顺序为绑定条款，见 specs/drafts/kt.spec.md §3.3）：
    A. 校验先于任何工作：prior ∈ (0,1)、half_life_days > 0（空 events 也校验）；
       再逐事件校验 day 为数字、非负、按列表顺序非降。
    B. 逐有效事件：先遗忘后证据——
       B1 遗忘：对所有 evidence>0 的知识点 m ← m · 0.5^(Δ/H)，
          Δ = 本事件 day − 上一个有效事件的 day（首事件 Δ=0）；无证据者保持 prior。
       B2 证据：题库查不到 item_id 则整条事件跳过（不产生快照、不推时钟）；
           否则对 item.kps 按声明顺序处理（主知识点权重 1.0，其余 0.5，
           图外知识点仅跳过该知识点）：odds 乘 lr^w，evidence +1。
    C. 快照：输出值一次性 round(·, 6)；内部状态全程不舍入（保证前缀重放
       与全程轨迹逐位一致）。
    """
    # ---- A：校验先于任何其他工作（空 events 也必须执行）----
    if not (0.0 < prior < 1.0):
        raise ValueError("prior must be in (0,1)")
    if not (isinstance(half_life_days, (int, float))
            and not isinstance(half_life_days, bool)) or not (half_life_days > 0.0):
        raise ValueError("half_life_days must be > 0")

    checked: list[tuple[KTEvent, float]] = []
    prev = 0.0
    for i, ev in enumerate(events):
        d = _as_day(ev.day, f"events[{i}].day")
        if checked and d < prev:
            raise ValueError("kt event days must be non-decreasing along the list")
        checked.append((ev, d))
        prev = d

    ids = [kp.id for kp in graph.kps()]
    mastery: dict[str, float] = {kp_id: prior for kp_id in ids}
    evidence: dict[str, int] = {kp_id: 0 for kp_id in ids}
    snapshots: list[KTSnapshot] = []
    prev_d = 0.0
    first = True

    for ev, d in checked:
        # ---- B1 遗忘：先衰减，后写证据（对负证据的掌握度同样衰减：保守方向）----
        if not first:
            factor = 0.5 ** ((d - prev_d) / half_life_days)
            for kp_id in ids:
                if evidence[kp_id] > 0:
                    mastery[kp_id] = mastery[kp_id] * factor
        first = False
        prev_d = d

        # ---- B2 证据更新 ----
        item = bank.get(ev.item_id)
        if item is None:  # 题库中不存在：整条事件跳过
            continue
        lr_c, lr_w = _likelihood_ratio(item)
        lr = lr_c if ev.correct else lr_w
        for idx, kp_id in enumerate(item.kps):
            if not graph.has(kp_id):  # 图外知识点：仅跳过该知识点
                continue
            w = 1.0 if idx == 0 else 0.5
            lr_eff = lr ** w if lr >= 1.0 else max(lr ** w, _ODDS_FLOOR)
            odds = (max(mastery[kp_id], _ODDS_FLOOR)
                    / max(1.0 - mastery[kp_id], _ODDS_FLOOR))
            odds *= lr_eff
            mastery[kp_id] = _clamp01(odds / (1.0 + odds))
            evidence[kp_id] += 1

        # ---- C：快照（输出值一次性 round；键序随 graph.kps()）----
        snapshots.append(KTSnapshot(
            day=d,
            item_id=ev.item_id,
            correct=ev.correct,
            mastery={kp_id: round(mastery[kp_id], 6) for kp_id in ids},
            evidence=dict(evidence),
        ))
    return snapshots


def to_profile(snapshot: KTSnapshot, learner_id: str) -> Profile:
    """把轨迹末快照折算成与其他模块对接的 Profile（mastery/evidence 逐字段一致；
    updated_at 是唯一时间戳字段，取当前 UTC）。快照的 dict 被复制，互不影响。"""
    return Profile(
        learner_id=learner_id,
        mastery=dict(snapshot.mastery),
        evidence=dict(snapshot.evidence),
        updated_at=datetime.now(timezone.utc).strftime(_UPDATED_AT_FMT),
    )


# ---------- XES3G5M 对接（pyKT 风格 CSV 序列行）----------

def _split_seq(value) -> list[str]:
    if value is None:
        return []
    return _SEQ_SPLIT.findall(str(value))


def xes3g5m_row(row: dict) -> tuple[str, list[KTEvent]]:
    """把 XES3G5M pyKT-CSV 的一行（dict，如 csv.DictReader 产出的行）换成事件流。

    字段映射（specs/drafts/kt.spec.md §3.5）：uid -> 学习者 id；
    questions -> item_id（token 原样，含负数填充 token，靠 selectmasks 剔除）；
    responses -> "1"=对 / "0"=错（其余 token 抛 ValueError）；
    timestamps -> 毫秒级时间戳，day = (t − 首个有效 t) / 86400000（day 0 起）；
    selectmasks -> 仅 token "-1" 视为剔除，其余视为有效；列缺失或空单元格则全选。
    is_repeat / concepts / fold 等其余列一律忽略。返回 (uid, events)，事件按
    列顺序排列（不重排时间戳；非降校验交给 trace）。
    """
    for col in ("uid", "questions", "responses", "timestamps"):
        if col not in row:
            raise ValueError(f"xes3g5m row missing column: {col}")
    uid = str(row["uid"])
    q_tokens = _split_seq(row["questions"])
    r_tokens = _split_seq(row["responses"])
    t_tokens = _split_seq(row["timestamps"])
    raw_mask = row.get("selectmasks")
    m_tokens = _split_seq(raw_mask) if raw_mask is not None and str(raw_mask).strip() != "" else None

    n = len(q_tokens)
    if len(r_tokens) != n or len(t_tokens) != n:
        raise ValueError(
            f"xes3g5m row length mismatch: questions={n}, responses={len(r_tokens)}, "
            f"timestamps={len(t_tokens)}")
    if m_tokens is not None and len(m_tokens) != n:
        raise ValueError(f"xes3g5m row selectmasks length {len(m_tokens)} != questions length {n}")

    keep = [i for i in range(n) if m_tokens is None or m_tokens[i] != _MASK_PAD]
    if not keep:
        return uid, []

    ts = []
    for i in keep:
        try:
            ts.append(float(t_tokens[i]))
        except (TypeError, ValueError):
            raise ValueError(f"xes3g5m timestamp token not a number: {t_tokens[i]!r}")
    t0 = ts[0]  # 首个有效时间戳为 day 0
    events: list[KTEvent] = []
    for j, i in enumerate(keep):
        r = r_tokens[i]
        if r == "1":
            correct = True
        elif r == "0":
            correct = False
        else:
            raise ValueError(f"xes3g5m response token must be '0' or '1', got {r!r}")
        events.append(KTEvent(item_id=q_tokens[i], correct=correct, day=(ts[j] - t0) / _MS_PER_DAY))
    return uid, events


def load_xes3g5m_csv(path: str) -> list[tuple[str, list[KTEvent]]]:
    """读取 XES3G5M pyKT-CSV 序列文件（每行一条学习者序列），返回按文件顺序的
    (uid, events) 列表。唯一的文件 IO 点，仅读不写；解析行为见 xes3g5m_row。"""
    out: list[tuple[str, list[KTEvent]]] = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out.append(xes3g5m_row(row))
    return out
