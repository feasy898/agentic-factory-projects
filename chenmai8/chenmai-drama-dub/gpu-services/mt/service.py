"""mt —— GPU 侧本地翻译主后端服务（FastAPI，:9004，M6；**T10 预置、T12 批部署冒烟**）。

与客户端 ``pipeline/mt_backends.LocalMtBackend`` 为同批接口契约（请求-响应口径见下）。
状态与回填纪律：本服务未冒烟前 ``configs/models.yaml`` 的 mt-core ``volta_status``
保持 ``pending``；T12 部署 + 冒烟后回填（同 asr_align :9001 的 T5 流程）。

接口口径：
  GET  /health
      → {"service":"mt","loaded":{"mt-core":bool},"cuda_available":bool,
         "device":str,"versions":{...},"error":null}
  POST /v1/translate
      请求 {"text":str, "tgt":"en|es|ar", "cast":str, "terms":{src:tgt},
            "prev":[str], "next":[str],
            "budget":{"orig_dur":f,"lo":f,"hi":f}|null, "n_candidates":int}
      响应 {"candidates":[{"text":str,"q":f},...], "timing":{"load_s":f,"total_s":f},
            "versions":{"mt-core":str,"transformers":str,"torch":str}}

结构化模板（术语干预 + 背景信息 + 前后文，与训练模板同构，plan/training-plan §1.4）：
``[背景信息]/[术语表（必须采用）]/[对话前文]/[原文]/[对话后文]`` → 译文。
时长预算以「目标音节窗」提示模型按预算伸缩（候选从紧凑到完整）。

推理约束（Volta sm_70，configs/models.yaml 部署矩阵）：fp16 + sdpa；**无 bf16**；
不依赖重型推理运行时；显存 ≈5GB（1.8B fp16），与 :9001 同驻 cuda:0（32GB 充裕）。
部署：gpu/setup_mt_service.sh（权重/环境）→ gpu-services/mt/run_gpu.sh start
（127.0.0.1:9004 常驻）→ 本机 ops/tunnel_gpu.sh（TUNNEL_LOCAL_PORT=9004）隧道访问。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

MODEL_DIR = os.environ.get("MT_CORE_DIR", "/data/xdng/models/mt-core")
DEVICE = os.environ.get("MT_DEVICE", "cuda:0")
MAX_CHARS = 2000  # 单句/单段上限（短剧台词量级远低于此，防御性兜底）

status: dict[str, Any] = {
    "service": "mt",
    "version": "1.0-draft",  # T12 冒烟后升 1.0
    "device": DEVICE,
    "loaded": {"mt-core": False},
    "error": None,
}
_M: dict[str, Any] = {}          # tokenizer/model 常驻
_INFER_LOCK = None               # 惰性建（threading.Lock 在事件循环外使用）


def _load_model() -> None:
    """装载 mt-core（fp16 + sdpa；Volta 无 bf16，禁 bf16 相关 flag）。"""
    global _INFER_LOCK
    if _INFER_LOCK is None:
        import threading

        _INFER_LOCK = threading.Lock()
    if not os.path.isdir(MODEL_DIR):
        status["error"] = f"权重目录不存在: {MODEL_DIR}（先跑 gpu/setup_mt_service.sh）"
        return
    t0 = time.perf_counter()
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=False)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR,
            torch_dtype=torch.float16,     # Volta：有 fp16、无 bf16
            attn_implementation="sdpa",    # 不依赖重型推理运行时
            trust_remote_code=False,
        )
        model.to(DEVICE).eval()
        _M["tok"] = tok
        _M["model"] = model
        status["loaded"]["mt-core"] = True
        status["versions"] = {
            "mt-core": os.environ.get("MT_CORE_VERSION", "TBD-T12"),
            "transformers": __import__("transformers").__version__,
            "torch": torch.__version__,
        }
        status["load_s"] = round(time.perf_counter() - t0, 3)
    except Exception as exc:  # 装载失败如实暴露在 /health，不静默
        status["error"] = f"{type(exc).__name__}: {exc}"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _load_model()
    yield


app = FastAPI(title="mt", version=status["version"], lifespan=_lifespan)


class BudgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orig_dur: float = Field(ge=0)
    lo: float = Field(ge=0)
    hi: float = Field(ge=0)


class TranslateIn(BaseModel):
    """与 LocalMtBackend.translate 的 payload 一一对应（extra=forbid 防口径漂移）。"""

    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_CHARS)
    tgt: str = Field(min_length=2, max_length=8)
    cast: str = ""
    terms: dict[str, str] = Field(default_factory=dict)
    prev: list[str] = Field(default_factory=list, max_length=2)
    next: list[str] = Field(default_factory=list, max_length=2)
    budget: Optional[BudgetIn] = None
    n_candidates: int = Field(default=4, ge=1, le=5)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        **status,
        "cuda_available": torch.cuda.is_available(),
    }


def _build_prompt(req: TranslateIn) -> str:
    """结构化模板：术语/背景/前后文/预算 → 生成提示（T12 可按模型卡模板微调）。"""
    parts: list[str] = []
    if req.cast:
        parts.append(f"[背景信息]\n{req.cast}")
    if req.terms:
        parts.append("[术语表（必须采用）]\n" + "；".join(f"{s}→{t}" for s, t in req.terms.items()))
    if req.prev:
        parts.append("[对话前文]\n" + "\n".join(req.prev))
    parts.append(f"[原文]\n{req.text}")
    if req.next:
        parts.append("[对话后文]\n" + "\n".join(req.next))
    if req.budget:
        parts.append(
            f"[时长预算] {req.budget.lo:.2f}–{req.budget.hi:.2f} 秒"
            f"（原文 {req.budget.orig_dur:.2f} 秒；候选从紧凑到完整）"
        )
    parts.append(f"[译文({req.tgt})]")
    return "\n\n".join(parts)


def _generate(prompt: str, n: int) -> list[str]:
    """贪心 + 采样多路 → ≤n 个去重候选（顺序即质量序：贪心在首位）。"""
    tok = _M["tok"]
    model = _M["model"]
    inputs = tok(prompt, return_tensors="pt").to(DEVICE)
    max_new = max(64, min(512, inputs["input_ids"].shape[1] * 2))
    outs: list[str] = []
    with torch.inference_mode():
        greedy = model.generate(
            **inputs, do_sample=False, max_new_tokens=max_new,
            pad_token_id=tok.pad_token_id or tok.eos_token_id,
        )
        outs.append(greedy)
        for _ in range(max(0, n - 1)):
            sampled = model.generate(
                **inputs, do_sample=True, temperature=0.9, top_p=0.95,
                max_new_tokens=max_new,
                pad_token_id=tok.pad_token_id or tok.eos_token_id,
            )
            outs.append(sampled)
    texts: list[str] = []
    for seq in outs:
        new_tokens = seq[0][inputs["input_ids"].shape[1]:]
        text = tok.decode(new_tokens, skip_special_tokens=True).strip()
        if text and text not in texts:
            texts.append(text)
    return texts


@app.post("/v1/translate")
def v1_translate(req: TranslateIn) -> dict[str, Any]:
    if not status["loaded"]["mt-core"]:
        raise HTTPException(status_code=503, detail=f"mt-core 未装载: {status['error']}")
    assert _INFER_LOCK is not None
    t0 = time.perf_counter()
    prompt = _build_prompt(req)
    with _INFER_LOCK:  # 单进程单卡份额，推理串行化
        texts = _generate(prompt, req.n_candidates)
    if not texts:
        raise HTTPException(status_code=500, detail="生成为空")
    # q：贪心首位 0.85，采样按序衰减（本服务不做质量模型打分，q 为启发式序）
    candidates = [
        {"text": t, "q": round(max(0.5, 0.85 - 0.05 * i), 3)}
        for i, t in enumerate(texts[: req.n_candidates])
    ]
    return {
        "candidates": candidates,
        "timing": {"total_s": round(time.perf_counter() - t0, 3)},
        "versions": status.get("versions") or {},
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="service.py", description="mt 服务（:9004）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("MT_PORT", "9004")))
    ap.add_argument("--host", default="127.0.0.1")  # 只监听本机回环；外部一律走 ssh 隧道
    args = ap.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
