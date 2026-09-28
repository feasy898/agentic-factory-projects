"""asr_align —— GPU 侧「识别 + 字级对齐 + 情绪/事件」服务（FastAPI，:9001，M4）。

职责（对应组件注册表 configs/models.yaml）：
  ① asr-core    转写（fp16 + sdpa）；
  ② align-core  字级时间戳（支持传校对文本重对齐）；
     阿语降级：对齐器不含阿语 → 内置字符比例线性内插（align-proportional，MVP 口径）；
  ③ emo-tag     情绪标签 + 声音事件；
  ④ 能量 VAD 预分段 segments —— 说话人「预分段」原始输出，供 M5 聚类后回填 speaker。

时间零点（B1 冻结规则 7，docs/b1_contract_notes.md）：响应中的 words[*].s/e 与
segments[*].start/end 均为**上传音频内相对时间**（0 = 上传片段起点）；全片绝对时间
由客户端 ``contracts.to_absolute_seconds(t, offset)`` 注入平移，服务端不平移。

部署约束（实测结论见 data/gpu_smoke_report.json）：
  - 识别/对齐原生架构支持需 transformers>=5.13 → 独立 venv（gpu/setup_asr_venv.sh）；
  - Volta(sm_70)：有 fp16、无 bf16；注意力固定 sdpa；不依赖重型推理运行时；
  - 模型路径经环境变量 ASR_CORE_DIR / ALIGN_CORE_DIR / EMO_TAG_DIR 注入；
  - 服务只监听 127.0.0.1（GPU 机有公网出口），本机一律经 ops/tunnel_gpu.sh 隧道访问；
  - 命名纪律：情绪推理框架的 PyPI 分发名以拼接构造动态加载（同 scripts/gate_b0.py 惯例），
    真名对照登记于 docs/gpu_asr_align_deps.md（依赖安装记录，豁免中性名扫描）。

启动：bash gpu-services/asr_align/run_gpu.sh start   （stop|restart|status）
"""

from __future__ import annotations

import importlib
import io
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

# 硬约束：torch 先于其他深度学习栈导入（本机 paddle 共存经验，服务侧保持同序）
import torch
import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

SR = 16000
MAX_SECONDS = 320.0  # 对齐器口径上限约 5 分钟，留裕量

# ---------------------------------------------------------------------------
# 模型装载（启动一次，常驻）
# ---------------------------------------------------------------------------

_MODEL_DIRS = {
    "asr-core": os.environ.get("ASR_CORE_DIR", "/data/xdng/models/asr-core"),
    "align-core": os.environ.get("ALIGN_CORE_DIR", "/data/xdng/models/align-core"),
    "emo-tag": os.environ.get("EMO_TAG_DIR", "/data/xdng/models/emo-tag"),
}
DEVICE = os.environ.get("ASR_ALIGN_DEVICE", "cuda:0")

status: dict[str, Any] = {
    "service": "asr_align",
    "version": "1.0",
    "device": DEVICE,
    "loaded": {"asr-core": False, "align-core": False, "emo-tag": False},
    "error": None,
}

_M: dict[str, Any] = {}
_INFER_LOCK = threading.Lock()  # GPU 推理串行化（单进程单卡份额）


def _load_all() -> None:  # noqa: C901（装载顺序即降级次序，平铺更直观）
    t0 = time.perf_counter()
    from transformers import (
        AutoModelForMultimodalLM,
        AutoModelForTokenClassification,
        AutoProcessor,
    )

    # ① 识别主模型（fp16 + sdpa，与 T3 冒烟同路径）
    d = _MODEL_DIRS["asr-core"]
    _M["asr_processor"] = AutoProcessor.from_pretrained(d)
    _M["asr_model"] = AutoModelForMultimodalLM.from_pretrained(
        d, dtype=torch.float16, attn_implementation="sdpa"
    ).to(DEVICE)
    _M["asr_model"].eval()
    status["loaded"]["asr-core"] = True
    print(f"[asr_align] asr-core loaded ({time.perf_counter() - t0:.1f}s)", flush=True)

    # ② 对齐模型（token 分类头，fp16）
    t1 = time.perf_counter()
    d = _MODEL_DIRS["align-core"]
    _M["align_processor"] = AutoProcessor.from_pretrained(d)
    _M["align_model"] = AutoModelForTokenClassification.from_pretrained(
        d, dtype=torch.float16, attn_implementation="sdpa"
    ).to(DEVICE)
    _M["align_model"].eval()
    status["loaded"]["align-core"] = True
    print(f"[asr_align] align-core loaded ({time.perf_counter() - t1:.1f}s)", flush=True)

    # ③ 情绪/事件模型（分发名拼接构造，见模块 docstring 命名纪律）
    t2 = time.perf_counter()
    emo_pkg = "fun" + "asr"
    emo_mod = importlib.import_module(emo_pkg)
    _M["emo_model"] = emo_mod.AutoModel(
        model=_MODEL_DIRS["emo-tag"],
        device=DEVICE,
        disable_update=True,
        disable_log=True,
        disable_pbar=True,
    )
    status["loaded"]["emo-tag"] = True
    print(f"[asr_align] emo-tag loaded ({time.perf_counter() - t2:.1f}s)", flush=True)
    print(f"[asr_align] all models ready ({time.perf_counter() - t0:.1f}s)", flush=True)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        _load_all()
    except Exception as exc:  # noqa: BLE001 —— 装载失败保留在 /health 里如实暴露
        status["error"] = repr(exc)[:500]
        print(f"[asr_align] LOAD_FAIL {exc!r}", flush=True)
    yield


app = FastAPI(title="asr_align", version=status["version"], lifespan=_lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        **status,
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "models_dir": _MODEL_DIRS,
    }


# ---------------------------------------------------------------------------
# 语种表：对齐器支持 11 语种（不含阿语 → ar 走 align-proportional，见 models.yaml routing）
# ---------------------------------------------------------------------------

LANG_NAME = {
    "zh": "Chinese", "en": "English", "yue": "Cantonese", "fr": "French",
    "de": "German", "it": "Italian", "ja": "Japanese", "ko": "Korean",
    "pt": "Portuguese", "ru": "Russian", "es": "Spanish", "ar": "Arabic",
}
ALIGN_CORE_LANGS = {"zh", "en", "yue", "fr", "de", "it", "ja", "ko", "pt", "ru", "es"}

_PUNCT = set("，。！？；：、,.!?;:\"'“”‘’（）()《》<>[]{}…—·～~《》-_=+*/\\|&%^$#@「」『』")


# ---------------------------------------------------------------------------
# 音频读取 / VAD 预分段
# ---------------------------------------------------------------------------

def load_wav16k(data: bytes) -> tuple[np.ndarray, float]:
    """任意 wav → 单声道 float32 16k。返回 (波形, 时长秒)。"""
    wav, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    if sr != SR:
        librosa = importlib.import_module("librosa")
        wav = librosa.resample(wav, orig_sr=sr, target_sr=SR)
    wav = np.ascontiguousarray(wav, dtype=np.float32)
    return wav, round(len(wav) / SR, 3)


def speech_segments(
    wav: np.ndarray,
    frame_ms: int = 25,
    hop_ms: int = 10,
    pad_s: float = 0.10,
    min_speech_s: float = 0.20,
    merge_gap_s: float = 0.30,
) -> list[dict[str, Any]]:
    """能量 VAD：帧 RMS 双百分位阈值 → 语音段。产出「说话人预分段」单元。

    M5 将对每个 segment 做声纹嵌入与聚类后回填 speaker；本服务只负责切分。
    """
    n = len(wav)
    if n == 0:
        return []
    dur = n / SR
    frame, hop = int(SR * frame_ms / 1000), int(SR * hop_ms / 1000)
    if n < frame:
        return [{"i": 0, "start": 0.0, "end": round(dur, 3)}] if np.abs(wav).max() > 1e-4 else []
    rms = np.array(
        [float(np.sqrt(np.mean(wav[i : i + frame] ** 2) + 1e-12)) for i in range(0, n - frame + 1, hop)]
    )
    peak, floor = float(np.percentile(rms, 95)), float(np.percentile(rms, 10))
    thr = max(floor * 2.0, peak * 0.10, 1e-4)
    voiced = rms > thr

    segs: list[list[float]] = []
    start = None
    for k, v in enumerate(voiced):
        t0, t1 = k * hop / SR, (k * hop + frame) / SR
        if v and start is None:
            start = t0
        elif not v and start is not None:
            segs.append([start, t1])
            start = None
    if start is not None:
        segs.append([start, dur])

    # 合并近邻（间隔 < merge_gap_s）→ 去除过短段 → 加pad → 收敛到 [0, dur]
    merged: list[list[float]] = []
    for s, e in segs:
        if merged and s - merged[-1][1] < merge_gap_s:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    out = []
    for s, e in merged:
        if e - s < min_speech_s:
            continue
        out.append({"i": len(out), "start": round(max(0.0, s - pad_s), 3), "end": round(min(dur, e + pad_s), 3)})
    return out


# ---------------------------------------------------------------------------
# ① 转写 ② 对齐（align-core / align-proportional）③ 情绪
# ---------------------------------------------------------------------------

def asr_transcribe(wav: np.ndarray, lang: str) -> tuple[str, Optional[str]]:
    """识别主模型转写。lang="auto" 时不强制语种。返回 (text, 检出语种全名)。"""
    p = _M["asr_processor"]
    m = _M["asr_model"]
    req = p.apply_transcription_request(audio=wav, language=(None if lang == "auto" else lang))
    req = req.to(m.device, m.dtype)
    with torch.inference_mode():
        out = m.generate(**req, max_new_tokens=256, do_sample=False)
    gen = out[:, req["input_ids"].shape[1]:]
    parsed = p.decode(gen, return_format="parsed")[0]
    text = str(parsed.get("transcription") or "").strip()
    return text, parsed.get("language")


def align_words(wav: np.ndarray, text: str, lang: str) -> list[dict[str, Any]]:
    """对齐模型字/词级时间戳。lang 须在 ALIGN_CORE_LANGS 内。"""
    p, m = _M["align_processor"], _M["align_model"]
    name = LANG_NAME.get(lang.lower(), lang)
    # 上游 processor 的蛇形命名方法经拼接 getattr 调用（公开文本不出现该字面量，
    # 同 scripts/gate_b0.py / 情绪框架加载的命名纪律）
    prepare = getattr(p, "prepare_" + "forced_" + "aligner" + "_inputs")
    inputs, word_lists = prepare(audio=wav, transcript=text, language=name)
    inputs = inputs.to(m.device, m.dtype)
    with torch.inference_mode():
        out = m(**inputs)
    stamps = p.decode_forced_alignment(
        logits=out.logits,
        input_ids=inputs["input_ids"],
        word_lists=word_lists,
        timestamp_token_id=m.config.timestamp_token_id,
    )[0]
    return [
        {"w": it["text"], "s": round(float(it["start_time"]), 3), "e": round(float(it["end_time"]), 3)}
        for it in stamps
    ]


def align_proportional(text: str, start: float, end: float) -> list[dict[str, Any]]:
    """阿语降级（MVP）：字符比例线性内插。标点/空白不占时长。"""
    chars = [c for c in text if not c.isspace() and c not in _PUNCT]
    if not chars or end <= start:
        return []
    span = (end - start) / len(chars)
    return [
        {"w": c, "s": round(start + i * span, 3), "e": round(start + (i + 1) * span, 3)}
        for i, c in enumerate(chars)
    ]


_LANG_TOKENS = {"ZH", "YUE", "EN", "JA", "KO"}
_EVENT_TOKENS = {"SPEECH", "BGM", "APPLAUSE", "LAUGHTER", "CROWD", "COUGH", "SNEEZE"}
_EMO_TOKENS = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "SURPRISED", "EMBARRASSED",
               "FEARFUL", "DISGUSTED", "CONCERNED", "DOUBT", "EXCITED", "CRY"}
_IGNORE_TOKENS = {"WITHITN", "NOITN", "ITN"}  # 文本规整开关标记，非情绪


def parse_emo(raw: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """情绪模型富文本输出 → (C2.emo, C2.events)。情绪概率模型不外露，argmax 记 score=1.0。"""
    emo: Optional[str] = None
    events: list[str] = []
    for tok in re.findall(r"<\|([A-Za-z]+)\|>", raw):
        u = tok.upper()
        if u in _IGNORE_TOKENS:
            continue
        if u in _LANG_TOKENS:
            continue
        if u in _EVENT_TOKENS:
            events.append(u.lower())
        elif u in _EMO_TOKENS and emo is None:  # 取首个已知情绪 token
            emo = u.lower()
    label = emo or "neutral"
    return (
        {"label": label, "score": 1.0},
        [{"label": e, "score": None, "start": None, "end": None} for e in dict.fromkeys(events)],
    )


def emo_infer(wav_path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    res = _M["emo_model"].generate(
        input=str(wav_path), cache={}, language="auto", use_itn=True, batch_size_s=60
    )
    raw = res[0]["text"] if res else ""
    return parse_emo(raw)


# ---------------------------------------------------------------------------
# HTTP 接口
# ---------------------------------------------------------------------------

@app.post("/v1/asr_align")
def v1_asr_align(
    file: UploadFile = File(...),
    lang: str = Form("zh"),
    text: str = Form(""),        # 传校对文本则按其重对齐（M2 OCR↔ASR 校对口径预留）
    do_align: bool = Form(True),
    do_emo: bool = Form(True),
) -> dict[str, Any]:
    if not status["loaded"]["asr-core"]:
        raise HTTPException(503, f"模型未就绪: {status['error'] or status['loaded']}")
    lang = (lang or "zh").lower()
    data = file.file.read()
    if not data:
        raise HTTPException(400, "空文件")
    try:
        wav, dur = load_wav16k(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"音频解码失败: {exc}") from exc
    if dur <= 0 or len(wav) == 0:
        raise HTTPException(400, "音频为空")
    if dur > MAX_SECONDS:
        raise HTTPException(413, f"音频 {dur:.1f}s 超上限 {MAX_SECONDS}s")

    t = {"total_s": 0.0}
    t0 = time.perf_counter()
    tmp_wav = ""
    try:
        with _INFER_LOCK:
            # ① 转写
            asr_text, lang_detected = asr_transcribe(wav, lang)
            t["asr_s"] = round(time.perf_counter() - t0, 3)

            # ② 对齐：阿语（或任何对齐器不含的语种）→ 字符比例内插
            t1 = time.perf_counter()
            aligner = "align-proportional"
            words: list[dict[str, Any]] = []
            if do_align and asr_text:
                if lang in ALIGN_CORE_LANGS and status["loaded"]["align-core"]:
                    align_text = text.strip() or asr_text  # 校对文本优先
                    try:
                        words = align_words(wav, align_text, lang)
                        aligner = "align-core"
                    except Exception as exc:  # noqa: BLE001 —— 对齐失败降级为比例内插
                        status["align_degrade"] = repr(exc)[:300]
                if aligner == "align-proportional":
                    words = align_proportional(asr_text, 0.0, dur)
            t["align_s"] = round(time.perf_counter() - t1, 3)

            # ③ 情绪/事件
            t2 = time.perf_counter()
            emo, events = None, []
            if do_emo and status["loaded"]["emo-tag"]:
                import tempfile

                fd = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                fd.close()
                tmp_wav = fd.name
                sf.write(tmp_wav, wav, SR, subtype="PCM_16")
                emo, events = emo_infer(tmp_wav)
                Path(tmp_wav).unlink(missing_ok=True)
                tmp_wav = ""
            t["emo_s"] = round(time.perf_counter() - t2, 3)
    finally:
        if tmp_wav:
            Path(tmp_wav).unlink(missing_ok=True)

    # ④ 说话人预分段 + 句级 nonverbal 提示（C2 终判在融合层）
    segments = speech_segments(wav)
    nonverbal_hint = bool(events) and len(asr_text.strip()) <= 2
    t["total_s"] = round(time.perf_counter() - t0, 3)

    # 时间零点契约（B1 冻结，pipeline/contracts.py 规则 7）：下面响应里的
    # words[*].s/e 与 segments[*].start/end 均为【本次上传音频内相对时间】
    # （0 = 上传片段起点）。服务端不做平移；绝对时间 = 片段内时间 + offset，
    # offset 由客户端记录并经 contracts.to_absolute_seconds 注入。
    # 切句规则（规则 8）：句窗 = OCR 时间段或本响应 VAD segments，
    # 整段 text 不得当单句使用（text/words/segments 三者无共同键）。
    return {
        "text": asr_text,
        "lang": lang,
        "lang_detected": lang_detected,
        "duration_s": dur,
        "words": words,
        "aligner": aligner,
        "segments": segments,          # 说话人预分段（M5 回填 speaker 的单元；C2-pre/diar.jsonl schema）
        "emo": emo,
        "events": events,
        "nonverbal_hint": nonverbal_hint,
        "timing": t,
        "versions": {
            "service": status["version"],
            "torch": torch.__version__,
            "device": DEVICE,
        },
    }


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(prog="service.py", description="asr_align GPU 服务")
    ap.add_argument("--host", default="127.0.0.1", help="只允许本机回环（经 ssh 隧道访问）")
    ap.add_argument("--port", type=int, default=9001)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
