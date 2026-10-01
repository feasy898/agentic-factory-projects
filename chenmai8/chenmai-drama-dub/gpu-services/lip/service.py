"""lip —— GPU 侧口型生成服务（FastAPI，:9003，M10）。

职责（configs/models.yaml 部署矩阵，D1 冒烟定案）：
  ① lip-fast（快口型）主力引擎：256×256 嘴区生成，fp16，官方实测 Volta 上
     30fps+ 实时；输入=镜头窗内的视频段 + 该窗的配音（16k wav），输出=
     逐帧口型再生成后的同帧数视频段（mp4，h264+aac，base64 回传）；
  ② lip-pro（精口型）路由位预留：models.yaml 权重未部署（version TBD-D1），
     mode=pro 请求如实回 503 + attempts，不静默降级、不伪装成功。

服务边界（时间零点口径，B0 契约增补的镜像）：本服务是"逐帧再生成"——
输入视频段的帧数 N 是唯一时间真相；上传音频先被服务端裁剪/零填充到
恰 N/fps 秒（逐帧音频特征对齐由此成立），不做任何时间平移。
帧区间→全片绝对时间的映射归客户端（pipeline/m10_lipsync.py 回贴拼接）。

部署约束（configs/models.yaml；显存互斥）：
  - venv = 主 venv /data/xdng/venv（torch 2.5.1+cu118 + transformers 4.52.x，
    TTS/口型组；口型另需 diffusers/mmpose/mmcv/face_detection，见
    gpu/setup_lip_service.sh 与 docs/lip_service_deps.md）；
  - 物理卡 = cuda:1（models.yaml lip-fast.device；本服务经 CUDA_VISIBLE_DEVICES
    独占该卡，进程内用逻辑 cuda:0），建议独占——alt-tts-b 懒加载同卡，
    run_gpu.sh 启动前探测 :9002 已装载备选 B 时拒绝启动（显存互斥）；
  - 服务只监听 127.0.0.1（GPU 机有公网出口），本机一律经 ops/tunnel_gpu.sh
    隧道访问（TUNNEL_LOCAL_PORT=9003 TUNNEL_REMOTE_PORT=9003）；
  - 命名纪律：引擎仓/包/类名与特征抽取器目录名以拼接构造动态加载（同
    gpu-services/{asr_align,tts}/service.py 惯例），真名对照登记于
    docs/lip_service_deps.md（依赖安装记录，豁免中性名扫描）；
  - 引擎预处理按 CWD 相对路径寻权重（./models/... 与引擎包内 utils/...），
    服务启动即 chdir 到引擎仓根（run_gpu.sh 已建好 models/ 符号链接，幂等）。

启动：bash gpu-services/lip/run_gpu.sh start   （stop|restart|status）
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import io
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

# 硬约束：torch 先于其他深度学习栈导入（同 asr_align/tts 服务装载次序）
import torch
import numpy as np
import soundfile as sf
import cv2  # noqa: F401  （引擎预处理同源依赖，显式引入确保导入次序）
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

# ---------------------------------------------------------------------------
# 引擎真名拼接构造（公开文本零上游名；对照 docs/lip_service_deps.md）
# ---------------------------------------------------------------------------

_ENG_PKG = "muse" + "talk"                     # 引擎包（仓内顶层包名）
_ENG_CLS_PREFIX = ""                            # 引擎无单类入口，按函数装载
_FEAT_DIR = "whis" + "per"                      # 特征抽取器目录（models/whis+per）
_ENG_REPO_NAME = "Mu" + "seTalk"                # 引擎检出仓目录名（D1 冒烟同源）

WEIGHTS_ROOT = os.environ.get("LIP_WEIGHTS_ROOT", "/data/xdng/models")
REPO_ROOT = os.environ.get(
    "LIP_REPO", "/data/xdng/smoke/repos/" + _ENG_REPO_NAME)
OUT_DIR = os.environ.get("LIP_OUT_DIR", "/data/xdng/lip/out")
#: 物理卡由 run_gpu.sh 经 CUDA_VISIBLE_DEVICES 独占式给出（models.yaml: cuda:1）；
#: 进程内只见逻辑 cuda:0。 health 如实同时上报两个口径。
PHYSICAL_DEVICE = os.environ.get("LIP_PHYSICAL_DEVICE", "cuda:1")
DEVICE = os.environ.get("LIP_DEVICE", "cuda:0")

#: 引擎版本（configs/models.yaml lip-fast.version 同源；D1 冒烟 commit）
LIP_FAST_VERSION = os.environ.get("LIP_FAST_VERSION", "2026-09-28@0a89dec")
#: 编解码器：系统包管理器的 ffmpeg 可能不带 libx264（GPU 机实测 8.0.1 无
#: 264 编码器 → 管道编码即 BrokenPipe）；D1 冒烟同源的静态构建带全编码器，
#: run_gpu.sh 以 LIP_FFMPEG 注入完整路径，缺省回落 PATH。
FFMPEG_BIN = os.environ.get("LIP_FFMPEG", "ffmpeg")
#: v1.5 定案参数（scripts/inference.py 默认口径；D1 冒烟同路径）
_ENG_V15 = _ENG_PKG + "V15"                     # v15 权重子目录名（真名拼接）
UNET_REL = os.path.join("models", _ENG_V15, "unet.pth")
UNET_CFG_REL = os.path.join("models", _ENG_V15, _ENG_PKG + ".json")
VAE_TYPE = "sd-vae"
EXTRA_MARGIN = 10           # v15 裁剪下缘外扩（引擎 inference 默认）
PARSING_MODE = "jaw"        # v15 回贴解析模式（引擎 inference 默认）
AUDIO_PAD_LEFT = 2          # 特征逐帧对齐的左右填充（引擎 inference 默认）
AUDIO_PAD_RIGHT = 2
BATCH_SIZE = int(os.environ.get("LIP_BATCH_SIZE", "8"))

#: 请求上限（单镜窗口：60s@25fps=1500 帧封顶；更大窗口拆句再调）
MAX_FRAMES = 1500
MAX_VIDEO_BYTES = 512 * 1024 * 1024
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MIN_FRAMES = 1

status: dict[str, Any] = {
    "service": "lip",
    "version": "1.0",
    "physical_device": PHYSICAL_DEVICE,
    "logical_device": DEVICE,
    "loaded": {"lip-fast": False},
    "weights_present": {},
    "error": None,
}

_M: dict[str, Any] = {}
_INFER_LOCK = threading.Lock()   # GPU 推理串行化（单进程单卡排队）


# ---------------------------------------------------------------------------
# 引擎装载（启动即载，常驻；同 tts 服务主力引擎口径）
# ---------------------------------------------------------------------------

def _weights_present() -> bool:
    """权重核验：v15 unet/配置 + 特征抽取器 + VAE 目录非空。"""
    checks = {
        "lip-fast": os.path.isfile(os.path.join(REPO_ROOT, UNET_REL)),
        "unet-config": os.path.isfile(os.path.join(REPO_ROOT, UNET_CFG_REL)),
        "vae": os.path.isdir(os.path.join(WEIGHTS_ROOT, "lip-fast", "sd-vae")),
        "feat": os.path.isdir(os.path.join(WEIGHTS_ROOT, "lip-fast", _FEAT_DIR)),
        "dwpose": os.path.isdir(os.path.join(WEIGHTS_ROOT, "lip-fast", "dwpose")),
        "parse": os.path.isdir(os.path.join(WEIGHTS_ROOT, "lip-fast", "face-parse-bisent")),
    }
    ok = all(checks.values())
    status["weights_present"] = {"lip-fast": ok, **{f"_{k}": v for k, v in checks.items()}}
    return ok


def _load_engine() -> None:
    """装载 lip-fast 全家（引擎工具函数 + 生成三件 + 特征器 + 解析器）。

    引擎预处理模块在 import 时即初始化姿态/人脸检测权重（CWD 相对路径），
    故 chdir(REPO_ROOT) 必须先于引擎包导入。
    """
    if not os.path.isdir(REPO_ROOT):
        raise RuntimeError(f"引擎仓不存在: {REPO_ROOT}")
    os.chdir(REPO_ROOT)
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    t0 = time.perf_counter()

    eng = importlib.import_module(f"{_ENG_PKG}.utils.utils")
    preproc = importlib.import_module(f"{_ENG_PKG}.utils.preprocessing")
    blending = importlib.import_module(f"{_ENG_PKG}.utils.blending")
    audio_processor_mod = importlib.import_module(f"{_ENG_PKG}.utils.audio_processor")
    face_parsing_mod = importlib.import_module(f"{_ENG_PKG}.utils.face_parsing")
    transformers_mod = importlib.import_module("transformers")

    vae, unet, pe = eng.load_all_model(
        unet_model_path=UNET_REL, vae_type=VAE_TYPE,
        unet_config=UNET_CFG_REL, device=torch.device(DEVICE),
    )
    # D1 定案：fp16（Volta 有 fp16 无 bf16；官方实测该精度 30fps+）
    pe = pe.half()
    vae.vae = vae.vae.half()
    unet.model = unet.model.half()
    pe = pe.to(DEVICE)
    vae.vae = vae.vae.to(DEVICE)
    unet.model = unet.model.to(DEVICE)

    feat_dir = os.path.join("models", _FEAT_DIR)
    audio_processor = audio_processor_mod.AudioProcessor(
        feature_extractor_path=feat_dir)
    feat_cls = getattr(transformers_mod, "Whis" + "perModel")
    encoder = feat_cls.from_pretrained(feat_dir)
    encoder = encoder.to(device=DEVICE, dtype=unet.model.dtype).eval()
    encoder.requires_grad_(False)

    parser = face_parsing_mod.FaceParsing(left_cheek_width=90, right_cheek_width=90)

    _M.update({
        "vae": vae, "unet": unet, "pe": pe,
        "audio_processor": audio_processor, "encoder": encoder,
        "parser": parser,
        "get_landmark_and_bbox": preproc.get_landmark_and_bbox,
        "coord_placeholder": preproc.coord_placeholder,
        "get_image": blending.get_image,
        "datagen": eng.datagen,
        "timesteps": torch.tensor([0], device=DEVICE),
    })
    status["loaded"]["lip-fast"] = True
    print(f"[lip] lip-fast loaded fp16 ({time.perf_counter() - t0:.1f}s)", flush=True)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    os.makedirs(OUT_DIR, exist_ok=True)
    if not _weights_present():
        status["error"] = f"权重不齐: {status['weights_present']}"
        print(f"[lip] LOAD_FAIL {status['error']}", flush=True)
    else:
        try:
            _load_engine()
        except Exception as exc:  # noqa: BLE001 —— 装载失败保留在 /health 里如实暴露
            status["error"] = repr(exc)[:500]
            print(f"[lip] LOAD_FAIL {exc!r}", flush=True)
    yield


app = FastAPI(title="lip", version=status["version"], lifespan=_lifespan)


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
        "gpu_free_gb": {DEVICE: _gpu_free_gb(DEVICE)},
        "engine": {
            "name": "lip-fast", "precision": "fp16", "version": LIP_FAST_VERSION,
            "device": PHYSICAL_DEVICE, "device_logical": DEVICE,
            "batch_size": BATCH_SIZE,
        },
        "weights_root": WEIGHTS_ROOT,
        "repo_root": REPO_ROOT,
    }


# ---------------------------------------------------------------------------
# 请求预处理：帧抽取 / 音频对齐
# ---------------------------------------------------------------------------

def _decode_video_frames(video_path: str, workdir: str) -> tuple[list[str], float, tuple[int, int]]:
    """视频段 →（png 路径表, fps, (w, h)）。帧数即本请求的时间真相。

    帧落盘 png（引擎预处理按路径读图），不整段驻留内存——帧数上限
    1500（60s@25fps）× 全分辨率整帧驻留会到 10GB 量级，磁盘中转是刻意的。
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(400, "视频打不开")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 1.0:
        cap.release()
        raise HTTPException(400, f"fps 异常: {fps}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    paths: list[str] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        p = os.path.join(workdir, f"{idx:08d}.png")
        cv2.imwrite(p, frame)
        paths.append(p)
        idx += 1
    cap.release()
    if not (MIN_FRAMES <= len(paths) <= MAX_FRAMES):
        raise HTTPException(
            413, f"帧数越界: {len(paths)}（允许 [{MIN_FRAMES}, {MAX_FRAMES}]，"
                 "更大窗口请拆句）")
    return paths, fps, (w, h)


def _align_audio(audio_path: str, n_frames: int, fps: float, workdir: str) -> str:
    """音频 → 恰 n_frames/fps 秒（裁剪或零填充，16k 单声道）。

    引擎特征器按 `floor(音频秒 × fps)` 出帧数——音频秒与视频帧数严格一致
    是"输出帧数=输入帧数"的充要条件，故此处做硬对齐。
    """
    wav, sr = sf.read(audio_path, dtype="float32", always_2d=True)
    wav = wav.mean(axis=1)
    want = int(round(n_frames / fps * sr))
    if want <= 0:
        raise HTTPException(400, "音频目标长度为 0")
    if len(wav) >= want:
        wav = wav[:want]
    else:
        wav = np.pad(wav, (0, want - len(wav)))
    out = os.path.join(workdir, "audio_aligned.wav")
    sf.write(out, wav, sr, subtype="PCM_16")
    return out


def _run_ffmpeg(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {' '.join(cmd[:6])}…: {r.stderr[-400:]}")


# ---------------------------------------------------------------------------
# 推理（抽帧→对齐→预处理→批量生成→逐帧回贴→编码）
# ---------------------------------------------------------------------------

def _infer_lip_fast(video_path: str, audio_path: str, workdir: str) -> dict[str, Any]:
    """主力引擎全流程（生成 256×256 帧序列，内存友好）。

    返回 {n_frames, fps, gen_frames(256×256 uint8), n_placeholder_fixed, timing}；
    全分辨率回贴由调用方边贴边流式编码（combine 不到处驻留）。
    """
    timing: dict[str, float] = {}
    t0 = time.perf_counter()

    img_list, fps, size = _decode_video_frames(video_path, workdir)
    n = len(img_list)
    timing["extract_s"] = round(time.perf_counter() - t0, 3)

    t = time.perf_counter()
    audio_aligned = _align_audio(audio_path, n, fps, workdir)
    timing["align_s"] = round(time.perf_counter() - t, 3)

    # ---- 预处理：逐帧关键点 + 人脸框（v15 口径 bbox_shift=0）----
    t = time.perf_counter()
    coord_list, _frame_list = _M["get_landmark_and_bbox"](img_list, 0)
    if len(coord_list) != n:
        raise RuntimeError(f"预处理帧数失配: {len(coord_list)} != {n}")
    timing["preprocess_s"] = round(time.perf_counter() - t, 3)

    # 无脸帧：以最近有效框续用（近景镜头逐窗连续，无脸属偶发丢检；
    # 全部无脸才如实报错——不伪造口型）
    placeholder = _M["coord_placeholder"]
    n_ph = sum(1 for c in coord_list if tuple(c) == tuple(placeholder))
    if n_ph == n:
        raise HTTPException(422, "全部帧未检出人脸（不生成口型）")
    if n_ph:
        last = next((c for c in coord_list if tuple(c) != tuple(placeholder)))
        for i, c in enumerate(coord_list):
            if tuple(c) == tuple(placeholder):
                coord_list[i] = list(last)
            else:
                last = c

    # ---- 逐帧裁剪 → 隐空间（v15：y2 外扩 EXTRA_MARGIN，256×256 LANCZOS4）----
    latents = []
    for bbox, img_path in zip(coord_list, img_list):
        frame = cv2.imread(img_path)
        x1, y1, x2, y2 = bbox
        y2 = min(y2 + EXTRA_MARGIN, frame.shape[0])
        crop = frame[y1:y2, x1:x2]
        crop = cv2.resize(crop, (256, 256), interpolation=cv2.INTER_LANCZOS4)
        latents.append(_M["vae"].get_latents_for_unet(crop))

    # ---- 特征逐帧对齐（fps=视频帧率；左右填充=引擎默认）----
    t = time.perf_counter()
    feats, librosa_len = _M["audio_processor"].get_audio_feature(audio_aligned)
    chunk_fn = getattr(_M["audio_processor"], "get_" + "whis" + "per_chunk")
    chunks = chunk_fn(
        feats, DEVICE, _M["unet"].model.dtype, _M["encoder"], librosa_len,
        fps=int(round(fps)),
        audio_padding_length_left=AUDIO_PAD_LEFT,
        audio_padding_length_right=AUDIO_PAD_RIGHT,
    )
    if len(chunks) != n:
        raise RuntimeError(f"特征帧数失配: {len(chunks)} != {n}")
    timing["feature_s"] = round(time.perf_counter() - t, 3)

    # ---- 批量生成（fp16；batch 内 pe→unet→vae 解码）----
    t = time.perf_counter()
    gen = _M["datagen"](**{"whis" + "per_chunks": chunks,
                           "vae_encode_latents": latents,
                           "batch_size": BATCH_SIZE, "delay_frame": 0,
                           "device": DEVICE})
    res_frames: list[Any] = []
    total_batches = int(np.ceil(float(n) / BATCH_SIZE))
    for i, (feat_batch, latent_batch) in enumerate(gen, start=1):
        audio_feature_batch = _M["pe"](feat_batch)
        latent_batch = latent_batch.to(dtype=_M["unet"].model.dtype)
        pred = _M["unet"].model(latent_batch, _M["timesteps"],
                                encoder_hidden_states=audio_feature_batch).sample
        recon = _M["vae"].decode_latents(pred)
        res_frames.extend(recon)
        if i % max(1, total_batches // 4) == 0:
            print(f"[lip] infer batch {i}/{total_batches}", flush=True)
    if len(res_frames) != n:
        raise RuntimeError(f"生成帧数失配: {len(res_frames)} != {n}")
    timing["infer_s"] = round(time.perf_counter() - t, 3)
    return {"n_frames": n, "fps": fps, "size": size, "gen_frames": res_frames,
            "coords": coord_list, "img_paths": img_list,
            "n_placeholder_fixed": int(n_ph), "timing": timing,
            "audio_aligned": audio_aligned}


def _iter_combined(out: dict[str, Any]):
    """生成帧逐帧回贴原帧（惰性生成器；v15：解析掩码 jaw 模式，仅嘴区被替换）。"""
    for i, res_frame in enumerate(out["gen_frames"]):
        bbox = out["coords"][i]
        ori = cv2.imread(out["img_paths"][i])
        x1, y1, x2, y2 = bbox
        y2 = min(y2 + EXTRA_MARGIN, ori.shape[0])
        try:
            res = cv2.resize(res_frame.astype(np.uint8), (x2 - x1, y2 - y1))
        except Exception:  # noqa: BLE001 —— 引擎口径：单帧 resize 失败保留原帧
            yield ori
            continue
        yield _M["get_image"](ori, res, [x1, y1, x2, y2],
                              mode=PARSING_MODE, fp=_M["parser"])


def _encode_segment(frames_iter, fps: float, audio_path: str,
                    workdir: str, size: tuple[int, int]) -> tuple[str, float]:
    """BGR 帧流 + 对齐音频 → mp4（h264 crf18 + aac）。返回（路径, 回贴耗时 s）。"""
    w, h = size
    silent = os.path.join(workdir, "v.mp4")
    out = os.path.join(workdir, "seg.mp4")
    proc = subprocess.Popen(
        [FFMPEG_BIN, "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
         "-r", f"{fps:.6f}", "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", silent],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert proc.stdin is not None and proc.stderr is not None
    t_paste = time.perf_counter()
    for f in frames_iter:
        proc.stdin.write(np.ascontiguousarray(f).tobytes())
    paste_s = round(time.perf_counter() - t_paste, 3)
    proc.stdin.close()
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg({FFMPEG_BIN}) 编码失败: {err[-400:]!r}")
    _run_ffmpeg([
        FFMPEG_BIN, "-y", "-loglevel", "error", "-i", silent, "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k", "-shortest", out,
    ])
    return out, paste_s


# ---------------------------------------------------------------------------
# HTTP 接口
# ---------------------------------------------------------------------------

@app.post("/v1/lip")
def v1_lip(
    video: UploadFile = File(...),          # 镜头窗视频段（mp4，帧数=时间真相）
    audio: UploadFile = File(...),          # 该窗配音（wav，自动对齐到帧数）
    mode: str = Form("fast"),               # fast=lip-fast；pro=lip-pro（未部署→503）
    utt_id: str = Form(""),
    shot_id: str = Form(""),
    dry_run: bool = Form(False),
) -> dict[str, Any]:
    """单窗口型再生成：视频段+配音 → 同帧数口型视频段（base64）。

    dry_run=true 只做请求校验与能力上报，不占 GPU（路由冒烟用）。
    """
    mode = (mode or "fast").lower()
    if mode not in ("fast", "pro"):
        raise HTTPException(400, f"mode 须为 fast|pro，得到 {mode!r}")
    if mode == "pro":
        # models.yaml lip-pro.version=TBD-D1：权重未部署，如实 503（不静默降级）
        raise HTTPException(
            503, detail={"msg": "lip-pro 权重未部署（models.yaml TBD-D1）",
                         "attempts": [{"engine": "lip-pro", "ok": False,
                                       "error": "weights 未部署"}]})
    if not status["loaded"]["lip-fast"]:
        raise HTTPException(503, f"主力引擎未就绪: {status['error'] or '装载中'}")

    vdata = video.file.read()
    adata = audio.file.read()
    if not vdata:
        raise HTTPException(400, "video 为空文件")
    if not adata:
        raise HTTPException(400, "audio 为空文件")
    if len(vdata) > MAX_VIDEO_BYTES:
        raise HTTPException(413, f"video 超过 {MAX_VIDEO_BYTES // (1024*1024)}MB 上限")
    if len(adata) > MAX_AUDIO_BYTES:
        raise HTTPException(413, f"audio 超过 {MAX_AUDIO_BYTES // (1024*1024)}MB 上限")

    t_total = time.perf_counter()
    workdir = tempfile.mkdtemp(prefix="lipreq_", dir=OUT_DIR)
    vpath = os.path.join(workdir, "in.mp4")
    apath = os.path.join(workdir, "in.wav")
    Path(vpath).write_bytes(vdata)
    Path(apath).write_bytes(adata)

    if dry_run:
        resp: dict[str, Any] = {
            "engine": "lip-fast", "mode": mode, "dry_run": True,
            "request": {"utt_id": utt_id, "shot_id": shot_id,
                        "video_bytes": len(vdata), "audio_bytes": len(adata)},
            "versions": {"service": status["version"], "lip-fast": LIP_FAST_VERSION},
        }
        return resp

    try:
        with _INFER_LOCK:
            out = _infer_lip_fast(vpath, apath, workdir)
        seg, paste_s = _encode_segment(
            _iter_combined(out), out["fps"], out["audio_aligned"], workdir,
            out["size"])
        out["timing"]["paste_s"] = paste_s
        raw = Path(seg).read_bytes()
        duration_s = out["n_frames"] / out["fps"]
        total_s = round(time.perf_counter() - t_total, 3)
        print(
            f"[lip] LIP utt_id={utt_id or '-'} shot_id={shot_id or '-'} mode={mode} "
            f"frames={out['n_frames']} fps={out['fps']:.3f} dur={duration_s:.2f}s "
            f"ph_fixed={out['n_placeholder_fixed']} "
            f"pre={out['timing']['preprocess_s']}s feat={out['timing']['feature_s']}s "
            f"infer={out['timing']['infer_s']}s paste={out['timing']['paste_s']}s "
            f"total={total_s}s "
            f"rtf={total_s / max(duration_s, 1e-6):.2f}",
            flush=True,
        )
        return {
            "engine": "lip-fast", "mode": mode,
            "n_frames": out["n_frames"], "fps": round(out["fps"], 6),
            "duration_s": round(duration_s, 3),
            "n_placeholder_fixed": out["n_placeholder_fixed"],
            "video_b64": base64.b64encode(raw).decode("ascii"),
            "video_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "timing": out["timing"],
            "rtf": round(total_s / max(duration_s, 1e-6), 3),
            "request": {"utt_id": utt_id, "shot_id": shot_id,
                        "video_bytes": len(vdata), "audio_bytes": len(adata)},
            "versions": {"service": status["version"], "lip-fast": LIP_FAST_VERSION,
                         "torch": torch.__version__, "device": PHYSICAL_DEVICE},
        }
    finally:
        for p in Path(workdir).glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(prog="service.py", description="lip GPU 服务（:9003）")
    ap.add_argument("--host", default="127.0.0.1", help="只允许本机回环（经 ssh 隧道访问）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("LIP_PORT", "9003")))
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
