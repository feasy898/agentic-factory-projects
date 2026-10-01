"""TTS：本地离线播报（Windows SAPI，经 pyttsx3）。

- :meth:`Speaker.say`：运行时确认语播报（一次性线程实际播放，等结果回传，
  带 15s 上限；行为树侧如需 fire-and-forget 可自行包一层队列）；
- :meth:`Speaker.synth_to_wav`：把文本渲染成 wav 文件——无音频输出设备的
  服务器/CI 环境也能验证 TTS 通路，并用于生成内置样本音频。

工程约束（本机实测踩坑结论，实现据此设计）：
- pyttsx3.init() 返回**进程级缓存的单例引擎**（weakref），且其 runAndWait
  事件循环不可并发/复用：同一线程第 2 次调用或跨线程并发会互相挂起
  （"run loop already started"），真实播放后尤其如此；
- 直接用 SAPI COM（win32com ``SAPI.SpVoice``）做播放则稳定可重复，
  且完全不触碰 pyttsx3 的全局引擎缓存。

因此：
- 合成（:meth:`Speaker.synth_to_wav`）走**进程级单例工作线程**跑
  pyttsx3 ``save_to_file``（单线程顺序 runAndWait 实测可反复执行，
  已生成 20 条样本验证）；
- 播放（:meth:`Speaker.say`）走**一次性线程 + 原生 SAPI COM 异步播报**，
  轮询播放状态并带硬超时——无声卡/异常环境也不会挂起或污染合成线程；
- pyttsx3.init() 经全局锁串行，规避 comtypes 缓存竞态。

TTS 不可用（缺 SAPI/无中文语音/无声卡）时任务降级并记录
``available=False``，绝不阻塞主链路。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_ZH_VOICE_HINTS = ("huihui", "zh-cn", "zh_cn", "chinese")

# ---- 合成专用：进程级单例工作线程（save_to_file 任务串行） ----------------
_JOBS: "queue.Queue[Callable]" = queue.Queue()
_WORKER: threading.Thread | None = None
_INIT_LOCK = threading.Lock()  # pyttsx3.init()/comtypes 全局缓存保护


def _ensure_worker() -> None:
    global _WORKER
    with _INIT_LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return
        started = threading.Event()

        def run() -> None:  # 合成线程：只跑 save_to_file 类任务
            started.set()
            while True:
                job = _JOBS.get()
                if job is None:
                    return
                try:
                    with _INIT_LOCK:
                        engine = _init_engine()
                    job(engine)  # 线程内单次 runAndWait（见模块头注）
                except Exception:  # noqa: BLE001 —— 单条任务失败不拖垮线程
                    logger.exception("TTS 合成任务失败")

        _WORKER = threading.Thread(target=run, daemon=True, name="cs-voice-tts")
        _WORKER.start()
        started.wait(timeout=5)


def _init_engine():
    import pyttsx3

    return pyttsx3.init()


def _pick_voice(engine, voice_hint: str | None) -> str:
    voices = engine.getProperty("voices") or []
    keys = [voice_hint] if voice_hint else list(_ZH_VOICE_HINTS)
    for v in voices:
        vid = f"{v.id} {v.name} {' '.join(map(str, v.languages or []))}".lower()
        if any(h.lower() in vid for h in keys):
            return v.id
    return str(voices[0].id) if voices else ""


def _sapi_pick_voice(voice, voice_hint: str | None):
    """为原生 SAPI SpVoice 挑中文语音 token（缺省回退第一个）。"""
    try:
        tokens = voice.GetVoices()
        keys = [voice_hint.lower()] if voice_hint else [h.lower() for h in _ZH_VOICE_HINTS]
        for i in range(tokens.Count):
            token = tokens.Item(i)
            try:
                desc = str(token.GetAttribute("Name")).lower()
            except Exception:  # noqa: BLE001
                try:
                    desc = str(token.GetDescription(i)).lower()
                except Exception:  # noqa: BLE001
                    continue
            if any(h in desc for h in keys):
                return token
        return tokens.Item(0)
    except Exception:  # noqa: BLE001 —— 挑选失败就让 SAPI 用默认语音
        return voice.Voice


class Speaker:
    """离线 TTS 门面。不可用时静默降级（``available=False``）。

    多实例安全：合成经进程级单例线程，播放经一次性线程，互不影响。
    """

    def __init__(self, voice_hint: str | None = None, rate: int = 190) -> None:
        self._voice_hint = voice_hint
        self._rate = rate
        self.available = False
        self.voice_name = ""

    # -- 公开接口 ----------------------------------------------------------

    def say(self, text: str, timeout_s: float = 15.0) -> bool:
        """播报确认语，返回**播报线程的实际结果**（审查 D14）。

        用原生 SAPI COM 异步播报（SVSFlagsAsync），一次性线程内轮询
        播放状态，10s 硬超时兜底——任何异常环境只丢这条播报，
        不挂线程池、不影响合成通路。COM 线程先 ``CoInitialize``
        （SAPI 是 COM 组件，非主线程必须初始化 COM 公寓）；
        ``say()`` 最多阻塞 ``timeout_s`` 等线程落定后回传真实成败。
        """
        if not text:
            return False

        def play() -> bool:
            try:
                import pythoncom
                import win32com.client

                pythoncom.CoInitialize()  # 播放线程自己的 COM 公寓（审查 D14）
                try:
                    voice = win32com.client.Dispatch("SAPI.SpVoice")
                    voice.Voice = _sapi_pick_voice(voice, self._voice_hint)
                    voice.Rate = max(-10, min(10, (self._rate - 190) // 15))
                    voice.Speak(text, 1)  # 1 = SVSFlagsAsync
                    deadline = time.monotonic() + 10.0
                    while time.monotonic() < deadline:
                        if voice.Status.RunningState == 1:  # 1 = SRSLDone
                            self.available = True
                            return True
                        time.sleep(0.1)
                    logger.warning("TTS 播报超时未完成（10s），放弃本条")
                    return False
                finally:
                    pythoncom.CoUninitialize()
            except Exception:  # noqa: BLE001 —— 播放失败不阻塞主链路
                logger.exception("TTS 播报失败")
                return False

        result: dict = {"ok": False}
        done = threading.Event()

        def runner() -> None:
            result["ok"] = play()
            done.set()

        threading.Thread(target=runner, daemon=True,
                         name="cs-voice-tts-play").start()
        done.wait(timeout=timeout_s)
        return bool(result["ok"])

    def synth_to_wav(self, text: str, path: str | Path,
                     rate: int | None = None) -> bool:
        """渲染文本为 wav 文件（同步等待，无需音频输出设备）。成功返回 True。"""
        if not text:
            return False

        def job(engine) -> None:
            engine.setProperty("voice", _pick_voice(engine, self._voice_hint))
            engine.setProperty("rate", rate if rate is not None else self._rate)
            engine.save_to_file(text, str(path))
            engine.runAndWait()
            self.available = True
            self.voice_name = str(engine.getProperty("voice"))

        target = Path(path)
        ok = self._enqueue(job, done=threading.Event(), timeout=60.0)
        if not ok:
            return False
        if not (target.is_file() and target.stat().st_size > 44):
            time.sleep(0.3)  # SAPI 落盘抖动兜底
        return target.is_file() and target.stat().st_size > 44

    def shutdown(self) -> None:
        """兼容接口：工作/播放线程均为守护线程，随进程退出，无需单独停止。"""

    # -- 内部 --------------------------------------------------------------

    def _enqueue(self, job: Callable, done: threading.Event | None,
                 timeout: float) -> bool:
        _ensure_worker()

        def wrapped(engine) -> None:
            job(engine)
            if done is not None:
                done.set()

        wrapped.done = done  # type: ignore[attr-defined]
        _JOBS.put(wrapped)
        if done is None:
            return True
        return done.wait(timeout=timeout)
