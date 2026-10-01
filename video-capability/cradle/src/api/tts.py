"""TTS 能力: API(OpenAI 兼容 /audio/speech)优先, 本地 edge-tts 兜底。

本地实现: edge-tts 异步封装成同步, 语速 -10% (SPECS §5.6), 输出 mp3 + ffprobe 时长。
"""

from __future__ import annotations

from .adapters import Adapter, BudgetGuard, Endpoint, http_post_bytes

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_RATE = "-10%"


def api_tts(endpoint: Endpoint, text: str, out_path: str, voice: str = "alloy", http=http_post_bytes) -> dict:
    payload = {"model": endpoint.model, "input": text, "voice": voice, "response_format": "mp3"}
    audio = http(f"{endpoint.base}/audio/speech", endpoint.key, payload)
    if not audio or bytes(audio[:1]) == b"{":  # JSON 错误体而非音频
        raise ValueError(f"TTS API 返回非音频内容: {bytes(audio[:120])!r}")
    with open(out_path, "wb") as f:
        f.write(audio)
    return {"path": out_path, "model": endpoint.model}


def _ffprobe_duration(path: str) -> float:
    """延迟导入避免循环依赖 (gates.g1_tech 只依赖标准库)。"""
    from ..gates.g1_tech import probe_duration

    return probe_duration(path)


def local_edge_tts(
    text: str,
    out_path: str,
    rate: str = DEFAULT_RATE,
    voice: str = DEFAULT_VOICE,
    communicate_factory=None,
) -> dict:
    """edge-tts 同步封装。communicate_factory 可注入(单测 stub, 直接写一个假 mp3)。"""
    import asyncio

    if communicate_factory is None:
        try:
            import edge_tts
        except Exception as e:  # pragma: no cover
            from .adapters import LocalUnavailable

            raise LocalUnavailable(f"edge-tts 本地依赖不可用: {e}") from e

        def factory(t: str, v: str, r: str):
            return edge_tts.Communicate(t, voice=v, rate=r)

        communicate_factory = factory

    async def _run():
        com = communicate_factory(text, voice, rate)
        await com.save(out_path)

    asyncio.run(_run())
    duration = None
    try:
        duration = _ffprobe_duration(out_path)
    except Exception:
        duration = None
    return {"path": out_path, "model": f"edge-tts:{voice}", "rate": rate, "duration_s": duration}


def make_tts_adapter(endpoint: Endpoint, budget: BudgetGuard, local_fn=None, log=None) -> Adapter:
    return Adapter(
        "tts",
        endpoint,
        budget,
        api_fn=lambda text, out_path, **kw: api_tts(endpoint, text, out_path, **kw),
        local_fn=local_fn or local_edge_tts,
        log=log,
    )
