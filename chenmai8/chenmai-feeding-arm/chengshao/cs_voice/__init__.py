"""cs_voice：离线语音交互链路（ASR → 意图解析 → TTS）。

组件：
- :class:`AsrEngine` —— CPU 离线语音识别（非流式，短句 ≤30s），主后端 funasr，
  不可用时按开发指令 §9 回退表切换 ONNX 运行时路径（见 :mod:`cs_voice.asr`）。
- :class:`IntentParser` —— 关键词规则解析，产出契约 ``VoiceIntent``。
- :class:`Speaker` —— 本地 TTS（Windows SAPI，经 pyttsx3），离线播报确认语。
- :class:`VoiceLink` —— 冻结交互接口（start/poll/say），另提供注入接口供
  无麦克风环境与端到端 mock 使用（契约只增不改名）。

指令集（冻结）：下一口 / 继续 / 等一下 / 吃饱了 / 我想吃X（X ∈ 注册菜名表）。
公开内容不含任何上游参考项目名（命名纪律见开发指令 §2）。
"""

from __future__ import annotations

from .asr import AsrEngine
from .intent import IntentParser
from .link import VoiceLink
from .tts import Speaker
from .vad import EnergyVad

__all__ = ["AsrEngine", "EnergyVad", "IntentParser", "Speaker", "VoiceLink"]
