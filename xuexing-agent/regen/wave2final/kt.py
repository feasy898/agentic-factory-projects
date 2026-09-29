"""kt —— 同一学习者跨会话的掌握度轨迹追踪（KT 时序追踪）。

冻结契约：specs/frozen/kt.spec.md（本文自包含，公式与常量在本模块内自足定义，
不 import 任何其他 xuexing 引擎）。依赖仅标准库 + xuexing.types（绝对导入）。
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import re

from xuexing.types import Profile

__all__ = [
    "KTEvent",
    "KTSnapshot",
    "trace",
    "to_profile",
    "xes3g5m_row",
    "load_xes3g5m_csv",
]


@dataclass
class KTEvent:
    item_id: str
    correct: bool
    day: float  # 相对轨迹起点的天数；非负；沿列表非降（校验在 trace 内）


@dataclass
class KTSnapshot:
    day: float  # 本事件 day 的 float 化值（透传）
    item_id: str
    correct: bool
    mastery: dict[str, float]  # 全部图内知识点，round 到 6 位
    evidence: dict[str, int]  # 全部图内知识点的直接证据计数


# 序列单元格 token：空白（含空格/制表/换行）或逗号以外字符的极大连续段
_TOKEN_RE = re.compile(r"[^\s,]+")
_MS_PER_DAY = 86400000.0
# 证据更新的数值下限（odds / lr_eff 的饱和护栏）
_FLOOR = 1e-4


def _tokens(value) -> list[str]:
    """单元格 token 化；None -> 空序列，其余经 str() 规范化后扫描。"""
    if value is None:
        return []
    return _TOKEN_RE.findall(str(value))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def trace(events: list[KTEvent], bank, graph,
          prior: float = 0.5, half_life_days: float = 7.0) -> list[KTSnapshot]:
    """把带时间戳的作答事件流按序折叠成逐事件掌握度轨迹（先遗忘、后证据）。"""
    # ---- A. 校验先于任何折叠（空 events 也执行）----
    # 链式比较求值语义，无类型预检：不可比较类型 -> TypeError（全规格唯一例外）；
    # bool 按数值参与（True/False 均落入区间拒绝支）。
    if not (0.0 < prior < 1.0):
        raise ValueError(f"prior 必须在开区间 (0,1) 内: {prior!r}")
    if not _is_number(half_life_days) or not (half_life_days > 0):
        raise ValueError(f"half_life_days 必须为正数: {half_life_days!r}")
    days: list[float] = []
    for ev in events:
        d = ev.day
        if not _is_number(d) or not (d >= 0.0):  # NaN 经链式比较落入拒绝支
            raise ValueError(f"event.day 必须为非负数字: {d!r}")
        fd = float(d)
        if days and fd < days[-1]:
            raise ValueError(f"event.day 必须沿列表非降: {fd!r}")
        days.append(fd)

    prior = float(prior)
    kp_ids = [kp.id for kp in graph.kps()]
    mastery = {kid: prior for kid in kp_ids}
    evidence = {kid: 0 for kid in kp_ids}

    snaps: list[KTSnapshot] = []
    prev_day: float | None = None  # 上一个有效事件的 day；None = 尚无有效事件
    for ev, day in zip(events, days):
        item = bank.get(ev.item_id)
        if item is None:
            # ghost 事件：无快照、不推进衰减时钟（因此 bank 查找先于衰减）
            continue

        # ---- B1 遗忘：对所有有直接证据的知识点施加指数半衰期衰减 ----
        # 首个有效事件不衰减（起步 day 再大也不衰减）；衰减不消耗证据计数。
        if prev_day is not None:
            factor = 0.5 ** ((day - prev_day) / half_life_days)
            for kid in kp_ids:
                if evidence[kid] > 0:
                    mastery[kid] *= factor

        # ---- B2 证据：猜测感知 odds 贝叶斯更新 ----
        # 单题似然比（每事件一次，与当前掌握度无关）
        p_nm = max(item.effective_guess(), 0.02)
        p_m = 1.0 - _clamp01(0.05 + 0.20 * item.difficulty)
        if p_m <= p_nm:  # 高猜度护栏
            p_m = min(p_m + 0.05, 0.99)
        if ev.correct:
            lr = p_m / p_nm
        else:
            lr = (1.0 - p_m) / max(1.0 - p_nm, _FLOOR)
        # 按声明顺序逐个处理；重复 id 不去重；图外仅跳过该知识点、位次不重排
        for idx, kid in enumerate(item.kps):
            if not graph.has(kid):
                continue
            w = 1.0 if idx == 0 else 0.5
            lr_eff = lr ** w if lr >= 1 else max(lr ** w, _FLOOR)
            m = mastery[kid]
            odds = max(m, _FLOOR) / max(1.0 - m, _FLOOR)
            odds *= lr_eff
            mastery[kid] = _clamp01(odds / (1.0 + odds))
            evidence[kid] += 1

        # ---- B3 快照：输出值一次性 round(·,6)，内部状态全程不舍入 ----
        snaps.append(KTSnapshot(
            day=day,
            item_id=ev.item_id,
            correct=ev.correct,
            mastery={kid: round(mastery[kid], 6) for kid in kp_ids},
            evidence=dict(evidence),
        ))
        prev_day = day
    return snaps


def to_profile(snapshot: KTSnapshot, learner_id: str) -> Profile:
    """把轨迹末状态交给 route/scheduler 等模块；mastery/evidence 为拷贝。"""
    return Profile(
        learner_id=learner_id,
        mastery=dict(snapshot.mastery),
        evidence=dict(snapshot.evidence),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def xes3g5m_row(row: dict) -> tuple[str, list[KTEvent]]:
    """XES3G5M（pyKT-CSV）单行 -> (uid, 事件流)。

    绑定管线顺序：必需列检查 -> token 化 -> 长度校验（全列，先于掩码剔除）->
    掩码剔除（先于一切 token 级解析）-> 仅对保留位做 token 级解析。
    """
    for col in ("uid", "questions", "responses", "timestamps"):
        if col not in row:
            raise ValueError(f"缺少必需列: {col}")
    uid = str(row["uid"])
    q_tokens = _tokens(row["questions"])
    r_tokens = _tokens(row["responses"])
    t_tokens = _tokens(row["timestamps"])
    n = len(q_tokens)
    if len(r_tokens) != n or len(t_tokens) != n:
        raise ValueError("responses/timestamps 与 questions 长度不齐")

    raw_mask = row.get("selectmasks")
    if raw_mask is None or str(raw_mask).strip() == "":
        keep = list(range(n))  # 无掩码：全部位有效
    else:
        mask_tokens = _tokens(raw_mask)
        if len(mask_tokens) != n:
            raise ValueError("selectmasks 与 questions 长度不齐")
        keep = [i for i, tok in enumerate(mask_tokens) if tok != "-1"]
    if not keep:
        return (uid, [])

    # 仅对保留位解析（填充位的 timestamps/responses 一律不校验）
    t_vals = [float(t_tokens[i]) for i in keep]  # 非数字 -> ValueError
    t0 = t_vals[0]  # day 0 基准 = 掩码保留位首个时间戳，不是列首 token
    events: list[KTEvent] = []
    for j, i in enumerate(keep):
        resp = r_tokens[i]
        if resp == "1":
            correct = True
        elif resp == "0":
            correct = False
        else:
            raise ValueError(f"非法 response token: {resp!r}")
        events.append(KTEvent(q_tokens[i], correct, (t_vals[j] - t0) / _MS_PER_DAY))
    return (uid, events)  # 不重排时间戳；非降校验交给 trace


def load_xes3g5m_csv(path: str) -> list[tuple[str, list[KTEvent]]]:
    """逐行读取 pyKT 风格 CSV 序列 -> (uid, 事件流) 列表；只读、按文件顺序。"""
    loaded: list[tuple[str, list[KTEvent]]] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            loaded.append(xes3g5m_row(row))
    return loaded
