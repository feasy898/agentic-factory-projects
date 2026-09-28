"""VoiceLink：语音交互门面（冻结接口 start/poll/say，开发指令 §3.2）。

运行形态：
- 麦克风模式（``mic=True``）：后台采集线程 → EnergyVad 分段 → ASR → 意图
  解析 → 意图队列。采集打开失败（无输入设备）时自动退回注入模式，只打
  日志不抛错——无硬件环境主链路照常可用。
- 注入模式：:meth:`inject_intent` / :meth:`inject_text` /
  :meth:`inject_audio` 直接送入意图或音频（端到端 mock 按 §7 用队列注入，
  不经麦克风）。

``poll()`` 非阻塞，语义为"取最近意图"：清空队列只留最新一条。
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

import numpy as np

from .asr import AsrEngine
from .intent import IntentParser
from .tts import Speaker
from .vad import EnergyVad

logger = logging.getLogger(__name__)


class VoiceLink:
    """语音链路门面。构造参数全部可选（缺省即离线中文场景）。"""

    def __init__(self, asr: AsrEngine | None = None,
                 parser: IntentParser | None = None,
                 speaker: Speaker | None = None,
                 samplerate: int = 16000,
                 mic: bool = False, device: int | None = None) -> None:
        self._asr = asr or AsrEngine()
        self._parser = parser or IntentParser()
        self._speaker = speaker or Speaker()
        self._sr = samplerate
        self._device = device
        self._intents: "queue.Queue[object]" = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None
        self.mic_active = False

    # -- 冻结接口（§3.2） --------------------------------------------------

    def start(self) -> None:
        """启动后台线程。麦克风不可用时自动降级为注入模式。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._mic_loop, daemon=True, name="cs-voice-mic")
        self._thread.start()

    def poll(self) -> "object | None":
        """非阻塞取最近意图（清空积压，只返回最新一条）。"""
        latest = None
        while True:
            try:
                latest = self._intents.get_nowait()
            except queue.Empty:
                break
        return latest

    def say(self, text: str) -> None:
        """TTS 播报确认语（异步）。"""
        self._speaker.say(text)

    # -- 注入接口（契约外只增，mock/e2e 用） -------------------------------

    def inject_intent(self, intent) -> None:
        """直接注入一条 ``VoiceIntent``（行为树按脚本触发时用）。"""
        self._intents.put(intent)

    def inject_text(self, text: str, ts_ns: int | None = None):
        """注入一句已识别文本（跳过 ASR，走意图解析），返回该意图。"""
        vi = self._parser.parse(text, ts_ns=ts_ns)
        self._intents.put(vi)
        return vi

    def inject_audio(self, path: str | Path):
        """注入一个音频文件：同步跑 ASR+解析并入队，返回该意图。"""
        import soundfile as sf

        wave, sr = sf.read(str(path), dtype="float32", always_2d=True)
        vi = self._recognize(wave.mean(axis=1), sr)
        self._intents.put(vi)
        return vi

    @property
    def speaker(self) -> Speaker:
        return self._speaker

    def shutdown(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._speaker.shutdown()

    # -- 内部 --------------------------------------------------------------

    def _recognize(self, wave: np.ndarray, sr: int):
        text = self._asr.transcribe(wave, sr)
        vi = self._parser.parse(text)
        logger.debug("voice: %r -> %s", text, vi.intent)
        return vi

    def _mic_loop(self) -> None:
        try:
            import sounddevice as sd
        except Exception as err:  # noqa: BLE001 —— 缺依赖/缺驱动
            logger.warning("麦克风模式不可用（%s），降级为注入模式", err)
            return
        try:
            with sd.InputStream(samplerate=self._sr, channels=1, dtype="float32",
                                device=self._device,
                                blocksize=int(self._sr * 0.03)) as stream:
                self.mic_active = True
                vad = EnergyVad(samplerate=self._sr)
                while self._running:
                    data, _ = stream.read(int(self._sr * 0.06))
                    if vad.feed(data[:, 0]):
                        continue
                    seg = vad.take_utterance()
                    if seg is not None:
                        try:
                            self._recognize(seg, self._sr)
                        except Exception:  # noqa: BLE001
                            logger.exception("单句识别失败，跳过")
        except Exception as err:  # noqa: BLE001
            logger.warning("麦克风采集失败（%s），降级为注入模式", err)
        finally:
            self.mic_active = False
