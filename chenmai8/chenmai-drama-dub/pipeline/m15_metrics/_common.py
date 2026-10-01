"""M15 共享助手：调用账本 / 文本与序列度量 / wav IO / 原子写。

本文件只放六项指标共用的无业务逻辑原语；指标口径本身归各指标子模块。
"""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np

#: 无空格连写语种（WER 按字计）；其余按空白分词
_NO_SPACE_LANGS = {"zh", "yue", "ja"}
#: 标点/符号正则（NFKC 归一后剔除；保留字母数字与 CJK）
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)


# ---------------------------------------------------------------------------
# 调用账本（成本指标的记账来源）
# ---------------------------------------------------------------------------

class CallLedger:
    """单次指标运行的墙钟/外部调用记账（M15 成本指标的数据源）。

    - :meth:`stage` 上下文管理器记阶段墙钟（每个指标一个阶段）；
    - :meth:`call` 记每次外部服务调用（服务名/操作/耗时/成败）；
    - M14 ``metrics.db`` 尚未部署（编排批次未落），本账本即当前唯一记账来源，
      缺失口径在 metrics.json 里如实注明（不伪造历史成本）。
    """

    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.stages: dict[str, float] = {}
        self.calls: list[dict[str, Any]] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        t = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = round(time.perf_counter() - t, 3)

    def call(self, service: str, op: str, seconds: float, *, ok: bool = True,
             note: str = "") -> None:
        self.calls.append({
            "service": service, "op": op, "seconds": round(float(seconds), 3),
            "ok": bool(ok), "note": note,
        })

    @property
    def wall_total(self) -> float:
        return round(time.perf_counter() - self.t0, 3)

    def calls_summary(self) -> dict[str, dict[str, float]]:
        """按服务汇总：调用次数 / 累计秒（ok 与失败分开计）。"""
        out: dict[str, dict[str, float]] = {}
        for c in self.calls:
            agg = out.setdefault(c["service"], {"n": 0, "seconds": 0.0, "n_fail": 0})
            agg["n"] += 1
            agg["seconds"] = round(agg["seconds"] + c["seconds"], 3)
            if not c["ok"]:
                agg["n_fail"] += 1
        return out


# ---------------------------------------------------------------------------
# 文本归一与 WER/CER
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """NFKC → casefold → 剔除标点 → 压空白（WER/CER 参考与假设同口径）。"""
    import unicodedata

    t = unicodedata.normalize("NFKC", text or "")
    t = t.casefold()
    t = _PUNCT_RE.sub(" ", t)
    return " ".join(t.split())


def tokenize(text: str, lang: str) -> list[str]:
    """分语种 token 化：无空格连写语种按字，其余按空白词。"""
    t = normalize_text(text)
    if not t:
        return []
    if (lang or "").lower() in _NO_SPACE_LANGS:
        return [ch for ch in t if not ch.isspace()]
    return t.split()


def edit_distance(a: list[str], b: list[str]) -> int:
    """Levenshtein 距离（token 序列；两行滚动数组）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def wer_rate(ref_tokens: list[str], hyp_tokens: list[str]) -> float:
    """WER/CER = 编辑距离 / 参考长度；参考空时：假设也空 → 0.0，否则 1.0。"""
    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0
    return round(edit_distance(ref_tokens, hyp_tokens) / len(ref_tokens), 4)


def metric_result(key: str, title: str, value: Optional[float], *, status: str,
                  threshold: Optional[float], method: str,
                  detail: Optional[dict[str, Any]] = None,
                  reason: str = "") -> dict[str, Any]:
    """单指标结果的标准外壳（metrics.json ``metrics[*]`` 的统一形态）。"""
    return {
        "key": key,
        "title": title,
        "value": (round(float(value), 4) if value is not None else None),
        "status": status,          # ok | unavailable
        "threshold": threshold,    # None = 基线 v0（无历史基准，如实记录首测值）
        "method": method,
        "reason": reason,
        "detail": detail or {},
    }


# ---------------------------------------------------------------------------
# 序列度量
# ---------------------------------------------------------------------------

def pearson(x: np.ndarray | list[float], y: np.ndarray | list[float]) -> float:
    """Pearson 相关系数；任一序零方差（或长度<2）→ 0.0（退化如实记 0）。"""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.shape != y.shape or x.size < 2:
        return 0.0
    sx, sy = x.std(), y.std()
    if sx <= 0.0 or sy <= 0.0:
        return 0.0
    return float(round(np.corrcoef(x, y)[0, 1], 4))


def rms_envelope(x: np.ndarray, sr: int, hop_s: float) -> tuple[np.ndarray, np.ndarray]:
    """波形 → (每 hop 的 RMS, hop 中心时刻秒)。末尾不足一 hop 的余量丢弃。"""
    x = np.asarray(x, dtype=np.float64)
    hop = max(1, int(round(hop_s * sr)))
    n_hop = x.shape[0] // hop
    if n_hop == 0:
        return np.zeros(0), np.zeros(0)
    frames = x[: n_hop * hop].reshape(n_hop, hop)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    times = (np.arange(n_hop) + 0.5) * hop_s
    return rms, times


# ---------------------------------------------------------------------------
# wav IO
# ---------------------------------------------------------------------------

def wav_duration(path: str | Path) -> float:
    """wav 实测时长（秒，3 位小数；soundfile 帧数/采样率）。"""
    import soundfile as sf

    info = sf.info(str(path))
    return round(info.frames / float(info.samplerate), 3)


def read_mono(path: str | Path) -> tuple[np.ndarray, int]:
    """wav → (float64 单声道, 原采样率)（多声道取均值）。"""
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return data.mean(axis=1), int(sr)


def slice_wav(src: str | Path, t0: float, t1: float, out: str | Path) -> Path:
    """按时间窗切片落盘（保留源采样率/单声道；供 :9001 上传，服务端重采样兜底）。"""
    import soundfile as sf

    data, sr = sf.read(str(src), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    i0 = max(0, int(round(t0 * sr)))
    i1 = min(mono.shape[0], max(i0 + 1, int(round(t1 * sr))))
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), mono[i0:i1], sr, subtype="PCM_16")
    return out_path


def to_mono16k(src: str | Path, out: str | Path) -> Path:
    """整轨转 16k 单声道 wav（ffmpeg 重采样，:9001 建议输入口径）。"""
    import subprocess
    import tempfile

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), "-ar", "16000", "-ac", "1", str(out_path)]
    subprocess.run(cmd, check=True, timeout=300, capture_output=True, text=True)
    return out_path


# ---------------------------------------------------------------------------
# 写盘
# ---------------------------------------------------------------------------

def write_json_atomic(path: str | Path, payload: Any) -> Path:
    """单文档 JSON 原子写（与 m8/m6 同口径：同目录 tmp + os.replace）。"""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n",
    )
    os.replace(tmp, path)
    return path
