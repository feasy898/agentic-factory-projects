"""指标 6 —— 每分钟处理成本（墙钟/模型调用记账）。

测法（任务 T21 定案，规划 §4 M15 表行 6）：主值 = 本次指标运行总墙钟
（CallLedger）÷ 产出的成片分钟数（``wall_clock_s_per_output_minute``）；
明细如实记账：

- 阶段墙钟（每个指标一个阶段）；
- 外部服务调用（服务/操作/次数/累计秒/失败数）——"模型调用记账"口径；
- 记账来源声明：M14 ``metrics.db`` 尚未部署（编排批次未落），本次运行
  的会话账本即当前唯一记账来源，历史/全链路成本（M1–M12 各步耗时）待
  M14 落库后透传，缺口径如实注明、不伪造；
- 金额换算（GPU 时×单价等）需要费率表，当前无费率输入 → 只记时间与
  调用次数，不对标市价折算（规划"报告值（对标市价 ~50 元/分）"的金额
  维度留给有费率输入的消费方）。

基线 v0：首测值即基线（metrics.json 顶层 ``baseline`` 同步标注）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pipeline.m15_metrics._common import CallLedger, metric_result, wav_duration

KEY = "cost_per_minute"
TITLE = "每分钟处理成本（墙钟/模型调用记账）"
THRESHOLD: Optional[float] = None  # 基线 v0：报告值，无通过线
METHOD = ("运行总墙钟 ÷ 成片分钟数；明细=阶段墙钟 + 外部服务调用记账"
          "（来源：本次会话账本；M14 metrics.db 未部署，缺历史口径如实注明）")


def compute(ws: Path, lang: str, ep: str, ledger: CallLedger,
            *, output_duration_s: Optional[float] = None) -> dict[str, Any]:
    if output_duration_s is None:
        output_duration_s = _output_duration(ws, ep, lang)
    minutes = (output_duration_s / 60.0) if output_duration_s else 0.0
    wall = ledger.wall_total
    value = (round(wall / minutes, 2) if minutes > 0 else None)

    detail: dict[str, Any] = {
        "wall_clock_s_total": wall,
        "stages_s": dict(sorted(ledger.stages.items())),
        "output_duration_s": output_duration_s,
        "output_minutes": round(minutes, 4) if minutes else None,
        "calls": list(ledger.calls),
        "calls_by_service": ledger.calls_summary(),
        "accounting_sources": {
            "session_ledger": "本次 m15 运行的墙钟与外部调用账本（已记）",
            "metrics_db": "M14 未部署（metrics.db 缺）——全链路逐步耗时待 M14 落库后透传",
            "price_table": "无费率输入（GPU 时×单价/API 费），金额维度不折算",
        },
        "baseline": "v0（首测值即基线）",
    }
    if value is None:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason="成片时长不可得（12_out 视频与配音轨均缺），"
                                    "无法归一到每分钟",
                             detail=detail)
    return metric_result(KEY, TITLE, value, status="ok", threshold=THRESHOLD,
                         method=METHOD, detail=detail)


def _output_duration(ws: Path, ep: str, lang: str) -> Optional[float]:
    """成片时长：12_out 视频ffprobe → 配音轨 wav 时长（兜底）。"""
    for rel in (f"12_out/{ep}.{lang}.mp4", f"09_lip/done/{ep}.{lang}.lip.mp4"):
        p = ws / rel
        if p.is_file():
            try:
                from pipeline.m1_ingest import ffprobe_json

                meta = ffprobe_json(p)
                dur = float(meta.get("format", {}).get("duration") or 0.0)
                if dur > 0:
                    return round(dur, 3)
            except Exception:
                continue
    for name in (f"dubbed.{lang}.wav", "dubbed.wav"):
        p = ws / "08_mix" / name
        if p.is_file():
            try:
                return wav_duration(p)
            except Exception:
                continue
    return None
