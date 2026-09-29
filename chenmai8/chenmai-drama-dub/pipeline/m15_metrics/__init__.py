"""M15 指标体系（规划 §4 M15；任务 T21 定案口径，【本机+GPU】）。

六个指标子模块（每个指标一个文件，函数式纯计算 + 可注入客户端）：

  ============================  ===========================================  ==================
  指标                          测法（T21 定案）                              通过线（MVP）
  ============================  ===========================================  ==================
  speaker_similarity            声纹嵌入（voxdia 组件）余弦：合成句 wav vs    ≥0.70（规划线）
                                C5 voice_ref 角色参考
  emotion_similarity            情绪标签一致率：C2 源句标签 vs 配音轨句窗      ≥0.70（规划线）
                                切片经 :9001 回判标签
  listen_wer                    配音回听 WER：:9001 转写 08_mix/dubbed 轨     ≤0.08（规划线）
                                vs C4 chosen 译文（分语种词/字口径）
  duration_alignment_rate       M8 产出入窗比：C5 实测时长（soundfile）       ≥0.70（规划线）
                                落 C4 预算窗 lo/hi 占比
  lip_score                     口型区帧差活性 vs 人声能量相关性              基线 v0（无历史基准，
                               （Pearson r；口型区=C2 face.bbox 下半，        如实记录首测值）
                                与 M10 嘴区口径同源）
  cost_per_minute               每分钟处理成本：墙钟/模型调用记账             报告值（基线 v0）
                                （本次运行的 ledger + M14 metrics.db 透传）
  ============================  ===========================================  ==================

出口：``12_out/metrics.json``（工作纸、非冻结契约；schema_version 自描述）。
CLI（规划 §4 M15 冻结形态）::

    python -m pipeline.m15_metrics --ep ep01 --lang en
    python -m pipeline.m15_metrics --ep ep01 --lang en [--jobs-dir <dir>]
        [--asr-url http://127.0.0.1:9001] [--allow-degraded]

退出码：0 = metrics.json 落盘且六项全部出数（数值如实，不做阈值门禁——
数值进演示页，判定归人）；1 = 有指标未能出数（未加 --allow-degraded 时）
或输入缺失；2 = 用法错误。
"""

from __future__ import annotations

from pipeline.m15_metrics._common import (
    CallLedger,
    edit_distance,
    metric_result,
    normalize_text,
    pearson,
    read_mono,
    tokenize,
    wav_duration,
    wer_rate,
    write_json_atomic,
)
from pipeline.m15_metrics import (
    cost,
    dur_align,
    lip_score,
    speaker_sim,
    wer,
)
from pipeline.m15_metrics.emotion_sim import compute as emotion_similarity

__all__ = [
    "CallLedger",
    "edit_distance",
    "metric_result",
    "normalize_text",
    "pearson",
    "read_mono",
    "tokenize",
    "wav_duration",
    "wer_rate",
    "write_json_atomic",
    "speaker_sim",
    "emotion_similarity",
    "wer",
    "dur_align",
    "lip_score",
    "cost",
]

#: 指标键（metrics.json ``metrics`` 对象的固定六键，顺序即运行序）
METRIC_KEYS = (
    "speaker_similarity",
    "emotion_similarity",
    "listen_wer",
    "duration_alignment_rate",
    "lip_score",
    "cost_per_minute",
)
