"""kt — 学习者跨会话的掌握度轨迹追踪（KT 时序追踪）。

冻结契约：specs/frozen/kt.spec.md（定稿 v1）。把带时间戳的作答事件流按顺序折叠成
逐事件的掌握度轨迹：每走到一个新事件，先对所有有直接证据的知识点施加指数半衰期
遗忘（0.5^(Δ/H)），再按猜测感知 odds 贝叶斯更新写入新证据。行为契约：轨迹可重放
（前缀逐位复现）、可解释（闭式数值手算可复核）、同输入同输出。另提供 XES3G5M
（pyKT-CSV）序列行到事件流的确定性适配器。

装载约束（§2）：禁止相对导入；禁止 ``from __future__ import annotations``（注入
装载下 dataclass 字符串注解会在 dataclasses._process_class 处抛 AttributeError）——
全部注解写真实对象。
"""
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

# ---- §3.3 冻结常量 ----
_SLIP_BASE = 0.05        # slip = _SLIP_BASE + _SLIP_SLOPE * difficulty
_SLIP_SLOPE = 0.20
_GUESS_FLOOR = 0.02      # p_nm：猜测率下限
_GUARD_BONUS = 0.05      # 高猜度护栏：p_m 抬升量
_GUARD_CAP = 0.99        # 高猜度护栏：p_m 封顶
_ODDS_FLOOR = 1e-4       # odds 分子/分母下限与 lr_eff 下限

# ---- §3.5 冻结常量 ----
_TOKEN_RE = re.compile(r"[^\s,]+")  # token =「空白或逗号以外字符」的极大连续段
_MS_PER_DAY = 86400000.0


def _clamp01(x):
    return max(0.0, min(1.0, x))


def _cells_tokens(value):
    """§3.5 单元格 token 化：None → 空；否则 str() 规范化后取极大非分隔段。"""
    if value is None:
        return []
    return _TOKEN_RE.findall(str(value))


@dataclass
class KTEvent:
    item_id: str
    correct: bool
    day: float     # 相对轨迹起点的天数；非负；沿列表非降


@dataclass
class KTSnapshot:
    day: float                    # 本事件 day 的 float 化值（透传）
    item_id: str                  # 触发本快照的事件题 id
    correct: bool
    mastery: dict[str, float]     # 图内知识点 -> round(m, 6)
    evidence: dict[str, int]      # 图内知识点 -> 直接证据计数


def trace(events: list, bank, graph,
          prior: float = 0.5, half_life_days: float = 7.0) -> list:
    """把事件流折叠为逐事件掌握度轨迹（§3.3；步骤顺序为绑定条款）。"""
    # ---- A. 校验先于任何其他工作（空 events 也执行）----
    # A1 prior：链式比较求值语义（无类型预检）；不可比较类型自然抛 TypeError
    #    （全规格唯一非 ValueError 异常）；bool 按数值参与（True≡1/False≡0 → 拒）。
    if not (0.0 < prior < 1.0):
        raise ValueError(f"prior must lie in the open interval (0, 1), got {prior!r}")
    # A2 half_life_days：数字（int/float，bool 除外）且 > 0；NaN 落入拒绝支。
    if isinstance(half_life_days, bool) or not isinstance(half_life_days, (int, float)):
        raise ValueError(f"half_life_days must be a number, got {half_life_days!r}")
    if not half_life_days > 0:
        raise ValueError(f"half_life_days must be > 0, got {half_life_days!r}")
    # A3 逐事件校验 day：数字（bool 除外）否则 ValueError；
    #    not (day >= 0.0)（含 NaN）→ ValueError；沿列表非降（严格下降抛）。
    prev_day = None
    for ev in events:
        day = ev.day
        if isinstance(day, bool) or not isinstance(day, (int, float)):
            raise ValueError(f"event.day must be a number, got {day!r}")
        if not day >= 0.0:
            raise ValueError(f"event.day must be >= 0, got {day!r}")
        if prev_day is not None and day < prev_day:
            raise ValueError(f"event.day must be non-decreasing, got {day!r} after {prev_day!r}")
        prev_day = day

    kp_ids = [kp.id for kp in graph.kps()]      # 键集与键序基准
    mastery = {kp: float(prior) for kp in kp_ids}   # 内部状态全程不舍入
    evidence = {kp: 0 for kp in kp_ids}

    snapshots: list = []
    last_day = None   # 上一个「有效」事件的 day；ghost 不推时钟
    for ev in events:
        item = bank.get(ev.item_id)
        if item is None:
            continue    # B2：整条事件跳过——不产生快照、不推进衰减时钟
        # ---- B1 遗忘：Δ = 本事件 day − 上一个有效事件 day；首个有效事件不衰减 ----
        if last_day is not None:
            factor = 0.5 ** ((ev.day - last_day) / half_life_days)
            if factor != 1.0:   # Δ=0 → 因子恰为 1，乘法为精确空操作
                for kp in kp_ids:
                    if evidence[kp] > 0:
                        mastery[kp] = mastery[kp] * factor
        # ---- B2 证据：单题似然比（每事件一次，与当前掌握度无关）----
        p_nm = max(item.effective_guess(), _GUESS_FLOOR)
        slip = _clamp01(_SLIP_BASE + _SLIP_SLOPE * item.difficulty)
        p_m = _clamp01(1.0 - slip)
        if p_m <= p_nm:                     # 高猜度护栏
            p_m = min(p_m + _GUARD_BONUS, _GUARD_CAP)
        lr_c = p_m / p_nm
        lr_w = (1.0 - p_m) / max(1.0 - p_nm, _ODDS_FLOOR)
        lr = lr_c if ev.correct else lr_w
        for idx, kp_id in enumerate(item.kps):   # 按声明顺序；重复不去重
            if not graph.has(kp_id):
                continue                        # 仅跳过该知识点；位次不重排
            w = 1.0 if idx == 0 else 0.5
            lr_eff = lr ** w if lr >= 1 else max(lr ** w, _ODDS_FLOOR)
            odds = max(mastery[kp_id], _ODDS_FLOOR) / max(1.0 - mastery[kp_id], _ODDS_FLOOR)
            odds *= lr_eff
            mastery[kp_id] = _clamp01(odds / (1.0 + odds))
            evidence[kp_id] += 1
        last_day = ev.day
        # ---- B3 快照：输出值一次性 round(·, 6)，独立新拷贝，键序随 graph.kps() ----
        snapshots.append(KTSnapshot(
            day=float(ev.day),
            item_id=ev.item_id,
            correct=ev.correct,
            mastery={kp: round(mastery[kp], 6) for kp in kp_ids},
            evidence=dict(evidence),
        ))
    return snapshots


def to_profile(snapshot: KTSnapshot, learner_id: str) -> Profile:
    """轨迹末状态 → 画像（§3.4）。mastery/evidence 为拷贝；updated_at 是唯一时间戳豁免。"""
    return Profile(
        learner_id=learner_id,
        mastery=dict(snapshot.mastery),
        evidence=dict(snapshot.evidence),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def xes3g5m_row(row: dict) -> tuple:
    """XES3G5M（pyKT-CSV）序列行 → (uid, 事件流)（§3.5；管线编号顺序为绑定条款）。"""
    # 1. 必需列检查（dict 无该键 → ValueError）
    for col in ("uid", "questions", "responses", "timestamps"):
        if col not in row:
            raise ValueError(f"missing required column: {col}")
    # 2. uid 规范化透传
    uid = str(row["uid"])
    # 3. 三格 token 化；n = questions token 数
    q_tokens = _cells_tokens(row["questions"])
    r_tokens = _cells_tokens(row["responses"])
    t_tokens = _cells_tokens(row["timestamps"])
    n = len(q_tokens)
    # 4. 长度校验（作用于全列，先于掩码剔除）
    if len(r_tokens) != n or len(t_tokens) != n:
        raise ValueError(
            f"column length mismatch: questions={n}, responses={len(r_tokens)}, "
            f"timestamps={len(t_tokens)}")
    # 5. selectmasks 读取：键缺失 / None / 去空白空串 → 无掩码；否则 token 化并校验长度
    raw_mask = row.get("selectmasks")
    if raw_mask is None or str(raw_mask).strip() == "":
        keep = list(range(n))                 # 无掩码：全部位有效
    else:
        mask_tokens = _cells_tokens(raw_mask)
        if len(mask_tokens) != n:
            raise ValueError(f"selectmasks length mismatch: mask={len(mask_tokens)}, n={n}")
        # 6. 掩码剔除先于一切 token 级解析；非 "-1" 的 token 一律视为有效
        keep = [i for i, tok in enumerate(mask_tokens) if tok != "-1"]
    if not keep:
        return uid, []
    # 7. 仅对保留位次解析 timestamps：float() 非数字 → ValueError；t0 = 保留位首个
    ts = [float(t_tokens[i]) for i in keep]
    t0 = ts[0]
    # 8. 按 keep 列序构造事件：response 仅保留位校验（"1"/"0"，其余 ValueError）
    events: list = []
    for pos, i in enumerate(keep):
        resp = r_tokens[i]
        if resp == "1":
            correct = True
        elif resp == "0":
            correct = False
        else:
            raise ValueError(f"invalid response token: {resp!r}")
        # day = (t_i − t0) / 86400000（IEEE 除法唯一结果；时间戳不重排，可为负）
        events.append(KTEvent(item_id=q_tokens[i], correct=correct,
                              day=(ts[pos] - t0) / _MS_PER_DAY))
    # 9. 其余列一律忽略；事件按列顺序排列，非降校验交给 trace
    return uid, events


def load_xes3g5m_csv(path: str) -> list:
    """逐行读取 pyKT-CSV 序列文件 → [(uid, 事件流), ...]；只读、按文件顺序、无隐式变换。"""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return [xes3g5m_row(row) for row in csv.DictReader(f)]
