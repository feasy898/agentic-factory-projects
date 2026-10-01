"""VAD：能量门限 + 滞回的轻量语音活动检测（麦克风常驻采集用）。

无 webrtcvad 依赖，纯 numpy：按帧算 RMS 分贝，超门限即视为语音，
语音结束后保持 hangover 时长再判停，并保留 pre-roll 预卷缓冲，
保证句首不被截掉。门限可在线自适应（噪声底跟踪 ±漂移）。
"""

from __future__ import annotations

import collections
import math

import numpy as np


class EnergyVad:
    """逐帧喂入，返回整段是否处于语音中；分段结果从 :meth:`take_utterance` 取。"""

    def __init__(self, samplerate: int = 16000, frame_ms: int = 30,
                 thresh_dbfs: float = -38.0, hangover_ms: int = 400,
                 preroll_ms: int = 300, min_utterance_ms: int = 250,
                 adapt: bool = True) -> None:
        self.sr = samplerate
        self.frame_len = int(samplerate * frame_ms / 1000)
        self.thresh_dbfs = thresh_dbfs
        self.hangover_frames = max(1, int(hangover_ms / frame_ms))
        self.min_frames = max(1, int(min_utterance_ms / frame_ms))
        self.adapt = adapt
        self._preroll: collections.deque[np.ndarray] = collections.deque(
            maxlen=max(1, int(preroll_ms / frame_ms)))
        self._buf: list[np.ndarray] = []
        self._quiet = 0
        self._speech_frames = 0
        self._last_speech_frames = 0  # 最近一次收口时的有效语音帧数
        self._noise_floor_db: float | None = None

    # -- 公开接口 ----------------------------------------------------------

    def feed(self, chunk: np.ndarray) -> bool:
        """喂一小段样本（任意长度），返回当前是否判定为语音。"""
        for i in range(0, len(chunk), self.frame_len):
            self._feed_frame(chunk[i:i + self.frame_len])
        return self._speech_frames > 0

    @property
    def speaking(self) -> bool:
        return self._speech_frames > 0

    def take_utterance(self) -> np.ndarray | None:
        """语音段结束后取整句（含预卷）；有效语音不足最短时长返回 None。"""
        if self.speaking:
            return None  # 还在说话中，未收口
        seg = self._buf
        self._buf = []
        n_speech = self._last_speech_frames
        self._last_speech_frames = 0
        if n_speech < self.min_frames:
            return None
        return np.concatenate(seg)

    # -- 内部 --------------------------------------------------------------

    def _feed_frame(self, frame: np.ndarray) -> None:
        if len(frame) == 0:
            return
        rms = float(np.sqrt(np.mean(np.square(frame.astype(np.float64)))) or 0.0)
        db = 20.0 * math.log10(max(rms, 1e-10))
        thresh = self.thresh_dbfs
        if self.adapt and self._noise_floor_db is not None:
            thresh = max(self.thresh_dbfs, self._noise_floor_db + 8.0)
        is_speech = db > thresh
        if not is_speech:
            # 跟踪噪声底（慢速下漂，只取安静帧）
            self._noise_floor_db = (db if self._noise_floor_db is None
                                    else 0.995 * self._noise_floor_db + 0.005 * db)
        if is_speech:
            if self._speech_frames == 0:
                self._buf.extend(self._preroll)
            self._buf.append(frame.copy())
            self._speech_frames += 1
            self._quiet = 0
        elif self._speech_frames > 0:
            self._buf.append(frame.copy())
            self._quiet += 1
            if self._quiet >= self.hangover_frames:
                # 收口：记录有效语音帧数（预卷/滞回不计入时长）
                self._last_speech_frames = self._speech_frames
                self._speech_frames = 0
                self._quiet = 0
        else:
            self._preroll.append(frame.copy())
