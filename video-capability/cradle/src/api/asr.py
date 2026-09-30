"""ASR 能力: API(OpenAI 兼容 /audio/transcriptions)优先, 本地 whisper small 兜底。

均不可用时调用方(g6)跳过对应子判据并记录 (SPECS §2)。
"""

from __future__ import annotations

from .adapters import Adapter, BudgetGuard, Endpoint, http_post_multipart


def api_transcribe(endpoint: Endpoint, audio_path: str, language: str = "zh", http=http_post_multipart) -> dict:
    data = http(
        f"{endpoint.base}/audio/transcriptions",
        endpoint.key,
        fields={"model": endpoint.model, "language": language, "response_format": "json"},
        file_field="file",
        file_path=audio_path,
    )
    if "text" not in data:
        raise ValueError(f"ASR API 返回缺 text 字段: {str(data)[:160]}")
    return {"text": data["text"], "model": endpoint.model}


def local_whisper(audio_path: str, model_size: str = "small", language: str | None = None, model=None) -> dict:
    """openai-whisper small。model 可注入(测试 stub); 缺省 lazy 加载。"""
    if model is None:
        try:
            import whisper
        except Exception as e:  # pragma: no cover
            from .adapters import LocalUnavailable

            raise LocalUnavailable(f"whisper 本地依赖不可用: {e}") from e
        model = whisper.load_model(model_size)
    result = model.transcribe(audio_path, language=language, temperature=0)
    return {"text": str(result.get("text", "")).strip(), "model": f"whisper-{model_size}"}


def make_asr_adapter(endpoint: Endpoint, budget: BudgetGuard, local_fn=None, log=None) -> Adapter:
    return Adapter(
        "asr",
        endpoint,
        budget,
        api_fn=lambda audio_path, **kw: api_transcribe(endpoint, audio_path, **kw),
        local_fn=local_fn or local_whisper,
        log=log,
    )
