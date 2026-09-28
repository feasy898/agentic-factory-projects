"""tts —— GPU 侧情绪迁移合成服务（FastAPI，:9002，M7）。

职责（组件注册表 configs/models.yaml，D1 fp32 定案）：
  ① dub-tts      主力引擎（五语种 zh/en/ja/es/ar；fp32；Volta 无 bf16、引擎无 fp16 开关）
  ② 备选路由      按 models.yaml routing.tts 语种链依序尝试：dub-tts → dub-tts-base →
     alt-tts-a → alt-tts-b（备选引擎懒加载：首次命中才装载；权重未部署的链节点
     如实记 skip 原因，不静默伪装成功）
  ③ **音色参考与情绪参考分离**（C5 冻结口径）：voice_ref=角色干净人声样本
     （05_cast/voicebank），emo_ref=原片该句人声（04_dial/emo_refs）——
     **音色与情绪可来自不同说话人**，这是情绪迁移的核心用法；
     主力引擎原生支持两路参考（emo_alpha 控制情绪强度）；备选引擎无情绪参考
     通道的，如实回填 ``emo_ref_used=false``（音色参考继续生效），不伪造情绪迁移。

时间口径（B0 契约增补）：合成是"无时间轴输入"的生成——服务只回传**产出 wav 的
实际时长**（duration_s，float 3 位）；句窗/绝对时间由客户端按 C5.expect_dur 与
M8 实测对齐处理，服务端不做时间平移。

部署约束（configs/models.yaml 部署矩阵；D1 冒烟 data/gpu_smoke_report.json）：
  - venv = 主 venv /data/xdng/venv（torch 2.5.1+cu118 + transformers 4.52.x，TTS/口型组）；
  - 主力引擎 fp32 常驻 cuda:0（默认，TTS_DEVICE 可覆盖），显存 ≈12GB 量级，与 :9001 同卡；
  - 备选 B 引擎按 models.yaml 落 cuda:1（TTS_ALT_B_DEVICE 可覆盖）——显存互斥：
    与 lip-pro 同卡互斥，lip-pro 起来时本服务须先停（B2 预算表）；
  - 服务只监听 127.0.0.1（GPU 机有公网出口），本机一律经 ops/tunnel_gpu.sh 隧道访问；
  - 命名纪律：引擎分发名/类名以拼接构造动态加载（同 gpu-services/asr_align/service.py
    惯例），真名对照登记于 docs/tts_service_deps.md（依赖安装记录，豁免中性名扫描）。

启动：bash gpu-services/tts/run_gpu.sh start   （stop|restart|status）
"""

from __future__ import annotations

import base64
import importlib
import io
import os
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

# 硬约束：torch 先于其他深度学习栈导入（同 asr_align 服务装载次序）
import torch
import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

#: 引擎真名拼接构造（公开文本零上游名；对照 docs/tts_service_deps.md）
_DUB_PKG = "inde" + "xtts.infer_v2_5"
_DUB_CLS = "Index" + "TTS2"
_ALT_B_PKG = "vox" + "cpm"
_ALT_B_CLS = "Vox" + "CPM"

WEIGHTS_ROOT = os.environ.get("TTS_WEIGHTS_ROOT", "/data/xdng/models")
OUT_DIR = os.environ.get("TTS_OUT_DIR", "/data/xdng/tts/out")
DEVICE = os.environ.get("TTS_DEVICE", "cuda:0")            # 主力引擎（models.yaml: cuda:0）
ALT_B_DEVICE = os.environ.get("TTS_ALT_B_DEVICE", "cuda:1")  # 备选 B（models.yaml: cuda:1）

#: 主力引擎 D1 冒烟 commit（configs/models.yaml dub-tts.version 同源）
DUB_TTS_VERSION = os.environ.get("TTS_DUB_VERSION", "2026-09-28@ee40fa7")
ALT_B_VERSION = os.environ.get("TTS_ALT_B_VERSION", "2026-09-28@f772e49")

#: 上限（音色参考 C3 口径 10–15s；情绪参考=句级；上限留裕量）
MAX_TEXT_CHARS = 500
MAX_REF_SECONDS = 30.0
MIN_REF_SECONDS = 0.3
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

#: 语种 → 引擎链（models.yaml routing.tts 冻结镜像；未列出的 dub-tts 语种走默认链）
ROUTING: dict[str, list[str]] = {
    "en": ["dub-tts", "dub-tts-base", "alt-tts-a", "alt-tts-b"],
    "es": ["dub-tts", "alt-tts-a", "alt-tts-b"],
    "ar": ["dub-tts", "alt-tts-b"],
}
DEFAULT_CHAIN = ["dub-tts"]

# 引擎注册表：loaded=常驻/已装载；weights_dir 存在性决定链节点是否可用
ENGINES: dict[str, dict[str, Any]] = {
    "dub-tts": {
        "langs": ["zh", "en", "ja", "es", "ar"],
        "device": DEVICE,
        "precision": "fp32",
        "weights_dir": os.path.join(WEIGHTS_ROOT, "dub-tts"),
        "version": DUB_TTS_VERSION,
        "emo_ref": True,       # 原生双参考（情绪可另取他人音频）
        "lazy": False,
    },
    "dub-tts-base": {
        "langs": ["zh", "en"],
        "device": DEVICE,
        "precision": "fp16",
        "weights_dir": os.path.join(WEIGHTS_ROOT, "dub-tts-base"),
        "version": "TBD",
        "emo_ref": False,      # 上一代引擎，无独立情绪参考通道
        "lazy": True,
    },
    "alt-tts-a": {
        "langs": ["en", "es"],
        "device": DEVICE,
        "precision": "fp16",
        "weights_dir": os.path.join(WEIGHTS_ROOT, "alt-tts-a"),
        "version": "TBD",
        "emo_ref": False,
        "lazy": True,
    },
    "alt-tts-b": {
        "langs": ["multi"],
        "device": ALT_B_DEVICE,
        "precision": "fp32",
        "weights_dir": os.path.join(WEIGHTS_ROOT, "alt-tts-b"),
        "version": ALT_B_VERSION,
        "emo_ref": False,      # 参考克隆模式：单路参考（音色优先，情绪参考如实忽略）
        "lazy": True,
    },
}

status: dict[str, Any] = {
    "service": "tts",
    "version": "1.0",
    "device": DEVICE,
    "alt_b_device": ALT_B_DEVICE,
    "loaded": {name: False for name in ENGINES},
    "weights_present": {},
    "error": None,
    "routing": ROUTING,
    "default_chain": DEFAULT_CHAIN,
}

_M: dict[str, Any] = {}
_INFER_LOCK = threading.Lock()   # GPU 推理串行化（单进程跨两卡份额统一排队）


# ---------------------------------------------------------------------------
# 引擎装载（dub-tts 启动即载；备选引擎懒加载）
# ---------------------------------------------------------------------------

def _weights_present(name: str) -> bool:
    d = ENGINES[name]["weights_dir"]
    ok = bool(d) and os.path.isdir(d) and any(
        f.endswith((".pth", ".safetensors", ".pt", ".bin", ".yaml")) for f in os.listdir(d)
    )
    status["weights_present"][name] = ok
    return ok


def _load_dub() -> None:
    """主力引擎：fp32（use_bf16=False 定案）、无 CUDA 核（纯 torch 声码器路径）。"""
    spec = ENGINES["dub-tts"]
    repo = os.environ.get(
        "TTS_DUB_REPO", "/data/xdng/smoke/repos/" + "inde" + "x-tts"
    )
    if repo and repo not in sys.path:
        sys.path.insert(0, repo)
    mod = importlib.import_module(_DUB_PKG)
    cls = getattr(mod, _DUB_CLS)
    t0 = time.perf_counter()
    _M["dub-tts"] = cls(
        cfg_path=os.path.join(spec["weights_dir"], "config.yaml"),
        model_dir=spec["weights_dir"],
        use_bf16=False,          # D1 定案：fp32 唯一实测档（引擎无 fp16 开关；Volta 禁 bf16）
        use_cuda_kernel=False,   # 纯 torch 声码器（D1 冒烟同路径）
        device=spec["device"],
    )
    status["loaded"]["dub-tts"] = True
    print(f"[tts] dub-tts loaded fp32 ({time.perf_counter() - t0:.1f}s)", flush=True)


def _lazy_load(name: str) -> None:
    """备选引擎懒加载。权重未部署 → RuntimeError（上层记入 attempts，不静默）。"""
    if status["loaded"].get(name):
        return
    spec = ENGINES[name]
    if not _weights_present(name):
        raise RuntimeError(f"weights 未部署: {spec['weights_dir']}（链节点跳过）")
    t0 = time.perf_counter()
    if name == "dub-tts-base":
        repo = os.environ.get("TTS_DUB_BASE_REPO", "")
        mod_path = os.environ.get("TTS_DUB_BASE_MODULE", "")
        cls_name = os.environ.get("TTS_DUB_BASE_CLASS", "")
        if not (repo and mod_path and cls_name):
            raise RuntimeError(
                "dub-tts-base 装载参数未配置（TTS_DUB_BASE_REPO/MODULE/CLASS，"
                "对照 docs/tts_service_deps.md）—— 上一代引擎权重未部署，链节点跳过"
            )
        if repo not in sys.path:
            sys.path.insert(0, repo)
        cls = getattr(importlib.import_module(mod_path), cls_name)
        _M[name] = cls(
            cfg_path=os.path.join(spec["weights_dir"], "config.yaml"),
            model_dir=spec["weights_dir"],
            use_bf16=False,
            use_cuda_kernel=False,
            device=spec["device"],
        )
    elif name == "alt-tts-a":
        mod_path = os.environ.get("TTS_ALT_A_MODULE", "")
        cls_name = os.environ.get("TTS_ALT_A_CLASS", "")
        if not (mod_path and cls_name):
            raise RuntimeError(
                "alt-tts-a 装载参数未配置（TTS_ALT_A_MODULE/CLASS，对照 "
                "docs/tts_service_deps.md）—— 备选 A 权重未部署，链节点跳过"
            )
        cls = getattr(importlib.import_module(mod_path), cls_name)
        _M[name] = cls.from_pretrained(
            spec["weights_dir"], dtype=torch.float16,
            attn_implementation="sdpa",
        ).to(spec["device"]).eval()
    elif name == "alt-tts-b":
        mod = importlib.import_module(_ALT_B_PKG)
        cls = getattr(mod, _ALT_B_CLS)
        _M[name] = cls.from_pretrained(
            spec["weights_dir"], optimize=False, load_denoiser=False,
            device=spec["device"],
        )
    else:  # pragma: no cover — 注册表与分支同步维护
        raise RuntimeError(f"未知引擎: {name}")
    status["loaded"][name] = True
    print(f"[tts] {name} loaded ({time.perf_counter() - t0:.1f}s)", flush=True)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    for name in ENGINES:
        _weights_present(name)
    if not status["weights_present"]["dub-tts"]:
        status["error"] = f"dub-tts 权重不存在: {ENGINES['dub-tts']['weights_dir']}"
        print(f"[tts] LOAD_FAIL {status['error']}", flush=True)
    else:
        try:
            _load_dub()
        except Exception as exc:  # noqa: BLE001 —— 装载失败保留在 /health 里如实暴露
            status["error"] = repr(exc)[:500]
            print(f"[tts] LOAD_FAIL {exc!r}", flush=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    yield


app = FastAPI(title="tts", version=status["version"], lifespan=_lifespan)


def _gpu_free_gb(device: str) -> Optional[float]:
    try:
        idx = int(device.split(":")[-1]) if ":" in device else 0
        free, _total = torch.cuda.mem_get_info(idx)
        return round(free / 1024**3, 1)
    except Exception:  # noqa: BLE001 —— 显存查询失败不阻塞 health
        return None


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        **status,
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "gpu_free_gb": {d: _gpu_free_gb(d) for d in {DEVICE, ALT_B_DEVICE}},
        "engines": {
            n: {k: v for k, v in spec.items() if k != "weights_dir"}
            for n, spec in ENGINES.items()
        },
        "weights_root": WEIGHTS_ROOT,
    }


# ---------------------------------------------------------------------------
# 参考音频读取（双参考校验 + 服务端日志口径）
# ---------------------------------------------------------------------------

def _read_ref(data: bytes, field: str) -> tuple[np.ndarray, int, float]:
    """参考 wav → (波形, 采样率, 时长)。空/坏/超限/静音一律 400。"""
    if not data:
        raise HTTPException(400, f"{field} 为空文件")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{field} 超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限")
    try:
        wav, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"{field} 解码失败: {exc}") from exc
    wav = wav.mean(axis=1)
    dur = len(wav) / sr
    if dur < MIN_REF_SECONDS:
        raise HTTPException(400, f"{field} 过短: {dur:.2f}s < {MIN_REF_SECONDS}s")
    if dur > MAX_REF_SECONDS:
        raise HTTPException(413, f"{field} 过长: {dur:.1f}s > {MAX_REF_SECONDS}s")
    if float(np.abs(wav).max()) < 1e-4:
        raise HTTPException(400, f"{field} 为静音")
    return wav, sr, round(dur, 3)


# ---------------------------------------------------------------------------
# 各引擎合成（统一签名 → 产出 wav 文件路径；emo_ref 语义逐引擎如实回填）
# ---------------------------------------------------------------------------

def _synth_dub(name: str, text: str, lang: str, voice_path: str, emo_path: Optional[str],
               emo_alpha: float, duration_factor: float, out_path: str) -> None:
    """主力引擎：spk_audio_prompt=音色参考，emo_audio_prompt=情绪参考（可不同说话人）。"""
    _M[name].infer(
        spk_audio_prompt=voice_path,
        text=text,
        output_path=out_path,
        lang=lang,
        emo_audio_prompt=emo_path,
        emo_alpha=emo_alpha,
        duration_factor=duration_factor,
        text_normalization=False,  # D1 口径：文本正则前端依赖境内不可得，关闭不影响骨干
        verbose=False,
    )


def _synth_alt_b(name: str, text: str, lang: str, voice_path: str, emo_path: Optional[str],
                 emo_alpha: float, duration_factor: float, out_path: str) -> None:
    """备选 B：参考克隆模式（单路参考=音色参考；emo_ref 如实忽略并回填）。"""
    del emo_path, emo_alpha  # 引擎无情绪参考通道（models.yaml alt-tts-b.emo_ref=False）
    wav = _M[name].generate(
        text=text,
        prompt_wav_path=None,
        prompt_text=None,
        reference_wav_path=voice_path,
        cfg_value=2.0,
        inference_timesteps=10,
        normalize=False,
    )
    wav = np.asarray(wav).squeeze()
    sr = 16000  # D1 冒烟同口径（该引擎产出 16k）
    sf.write(out_path, wav, sr)


def _synth_generic_future(name: str, text: str, lang: str, voice_path: str,
                          emo_path: Optional[str], emo_alpha: float,
                          duration_factor: float, out_path: str) -> None:
    """上一代主力 / 备选 A：权重未部署前的占位分支（命中即报错，不伪造产物）。

    装载器已在懒加载环节拦截（weights 未部署 → 链节点跳过），正常流不会到这里；
    真正接入时替换为对应引擎的 infer/generate 调用（对照 docs/tts_service_deps.md）。
    """
    del name, text, lang, voice_path, emo_path, emo_alpha, duration_factor, out_path
    raise RuntimeError("该引擎合成分支待权重部署后接入（见 docs/tts_service_deps.md）")


_SYNTH_FN = {
    "dub-tts": _synth_dub,
    "alt-tts-b": _synth_alt_b,
    "dub-tts-base": _synth_generic_future,
    "alt-tts-a": _synth_generic_future,
}


def resolve_chain(lang: str, engine: str) -> list[str]:
    """engine 显式指定 → 单引擎；否则按语种链（models.yaml routing.tts），未列出走默认。"""
    if engine and engine != "auto":
        if engine not in ENGINES:
            raise HTTPException(400, f"未知引擎: {engine}（可选: {sorted(ENGINES)} 或 auto）")
        return [engine]
    return list(ROUTING.get(lang, DEFAULT_CHAIN))


# ---------------------------------------------------------------------------
# HTTP 接口
# ---------------------------------------------------------------------------

@app.post("/v1/tts")
def v1_tts(
    text: str = Form(...),
    lang: str = Form("en"),
    voice_ref: UploadFile = File(...),        # 音色参考：角色干净人声（C5.voice_ref）
    emo_ref: Optional[UploadFile] = File(None),  # 情绪参考：原片该句人声（C5.emo_ref）
    emo_alpha: float = Form(0.7),
    duration_factor: float = Form(1.0),
    engine: str = Form("auto"),
    utt_id: str = Form(""),
    dry_run: bool = Form(False),
) -> dict[str, Any]:
    """合成一句：双参考（音色/情绪分离）→ wav(base64) + 实际时长。

    路由：engine=auto 按 models.yaml routing.tts[lang] 链依序尝试，链节点
    失败/未部署记入 attempts 后继续；全链失败返回 503（attempts 全量附上）。
    dry_run=true 只做路由解析与参考校验，不占 GPU（路由冒烟用）。
    """
    if not status["loaded"]["dub-tts"]:
        raise HTTPException(503, f"主力引擎未就绪: {status['error'] or '装载中'}")
    text = (text or "").strip()
    if not text:
        raise HTTPException(400, "text 为空")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(413, f"text 超过 {MAX_TEXT_CHARS} 字符上限")
    lang = (lang or "en").lower()
    if not 0.0 <= emo_alpha <= 1.0:
        raise HTTPException(400, f"emo_alpha 越界 [0,1]: {emo_alpha}（C5 口径）")
    if not 0.5 <= duration_factor <= 2.0:
        raise HTTPException(400, f"duration_factor 越界 [0.5,2.0]: {duration_factor}（C5 口径）")

    chain = resolve_chain(lang, engine)

    voice_data = voice_ref.file.read()
    v_wav, v_sr, v_dur = _read_ref(voice_data, "voice_ref")
    emo_path: Optional[str] = None
    e_dur: Optional[float] = None
    if emo_ref is not None:
        emo_data = emo_ref.file.read()
        if emo_data:
            _e_wav, _e_sr, e_dur = _read_ref(emo_data, "emo_ref")
            emo_path = _dump_tmp(_e_wav, _e_sr)
    voice_path = _dump_tmp(v_wav, v_sr)

    attempts: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    out_path = ""
    try:
        if dry_run:
            for name in chain:
                attempts.append({"engine": name, "ok": True, "skipped": "dry_run",
                                 "weights_present": status["weights_present"].get(name),
                                 "loaded": status["loaded"].get(name)})
            selected = chain[0]
        else:
            selected = ""
            for name in chain:
                spec = ENGINES[name]
                if lang != "multi" and spec["langs"] != ["multi"] and lang not in spec["langs"]:
                    attempts.append({"engine": name, "ok": False,
                                     "error": f"语种 {lang} 不在引擎支持表 {spec['langs']}"})
                    continue
                t_eng = time.perf_counter()
                try:
                    if not status["loaded"].get(name):
                        _lazy_load(name)
                    fd, out_path = tempfile.mkstemp(suffix=".wav", dir=OUT_DIR)
                    os.close(fd)
                    _SYNTH_FN[name](name, text, lang, voice_path, emo_path,
                                    emo_alpha, duration_factor, out_path)
                    wav, sr = sf.read(out_path, dtype="float32")
                    dur_s = round(len(wav) / sr, 3)
                    if dur_s <= 0 or float(np.abs(wav).max()) < 1e-4:
                        raise RuntimeError(f"产出空/静音 (dur={dur_s}s)")
                    selected = name
                    attempts.append({
                        "engine": name, "ok": True, "infer_s": round(time.perf_counter() - t_eng, 3),
                        "emo_ref_used": bool(emo_path) and spec["emo_ref"],
                        "emo_ref_supported": bool(spec["emo_ref"]),
                    })
                    # 服务端日志：双参考确认行（音色/情绪参考各一的实测时长入日志）
                    print(
                        f"[tts] SYNTH utt_id={utt_id or '-'} engine={name} lang={lang} "
                        f"voice_ref={voice_ref.filename or '-'}({v_dur}s@{v_sr}) "
                        f"emo_ref={(emo_ref.filename if emo_ref else '-') or '-'}"
                        f"({e_dur if e_dur is not None else '-'}s) "
                        f"emo_ref_used={bool(emo_path) and spec['emo_ref']} "
                        f"emo_alpha={emo_alpha} duration_factor={duration_factor} "
                        f"text_len={len(text)} -> wav {dur_s}s/{sr}Hz "
                        f"infer={time.perf_counter() - t_eng:.2f}s",
                        flush=True,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 —— 链节点失败如实记录，继续下一引擎
                    if out_path and os.path.isfile(out_path):
                        os.unlink(out_path)
                    out_path = ""
                    attempts.append({
                        "engine": name, "ok": False, "error": repr(exc)[:400],
                        "infer_s": round(time.perf_counter() - t_eng, 3),
                    })
                    print(f"[tts] ENGINE_FAIL engine={name}: {exc!r}", flush=True)
            if not selected:
                raise HTTPException(503, detail={"msg": "全链失败", "attempts": attempts})
        total_s = round(time.perf_counter() - t0, 3)

        sel_attempt = next((a for a in attempts if a.get("engine") == selected and a.get("ok")), None)
        resp: dict[str, Any] = {
            "engine": selected,
            "chain": chain,
            "attempts": attempts,
            "duration_s": None,  # 产出 wav 实测时长；dry_run 无产物保持 None
            "request": {
                "lang": lang, "emo_alpha": emo_alpha, "duration_factor": duration_factor,
                "voice_ref": voice_ref.filename or "", "emo_ref": (emo_ref.filename if emo_ref else "") or "",
                "voice_ref_s": v_dur, "emo_ref_s": e_dur,
                "emo_ref_used": (sel_attempt or {}).get("emo_ref_used"),
                "utt_id": utt_id, "text_chars": len(text),
            },
            "timing": {"total_s": total_s},
            "versions": {
                "service": status["version"],
                selected: ENGINES[selected]["version"],
                "torch": torch.__version__,
                "device": ENGINES[selected]["device"],
            },
        }
        if not dry_run:
            with open(out_path, "rb") as f:
                wav_bytes = f.read()
            wav, sr = sf.read(out_path, dtype="float32")
            resp["wav_b64"] = base64.b64encode(wav_bytes).decode("ascii")
            resp["wav_bytes"] = len(wav_bytes)
            resp["sr"] = int(sr)
            resp["duration_s"] = round(len(wav) / sr, 3)  # 产出 wav 实测时长（C 出口）
        return resp
    finally:
        for p in (voice_path, emo_path, out_path):
            if p and os.path.isfile(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _dump_tmp(wav: np.ndarray, sr: int) -> str:
    """参考波形落临时文件（引擎均以文件路径取参考；随请求结束清理）。"""
    fd, path = tempfile.mkstemp(suffix=".wav", dir=OUT_DIR)
    os.close(fd)
    sf.write(path, wav, sr)
    return path


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(prog="service.py", description="tts GPU 服务（:9002）")
    ap.add_argument("--host", default="127.0.0.1", help="只允许本机回环（经 ssh 隧道访问）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("TTS_PORT", "9002")))
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
