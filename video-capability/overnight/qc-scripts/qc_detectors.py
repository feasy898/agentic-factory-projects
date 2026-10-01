#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qc_detectors.py — J6 专用检测器管线（边界测试方案.md §2.3）

CPU-only 管线：强制 CUDA_VISIBLE_DEVICES=""（铁律2：不占卡0/卡1，避免与生产 vLLM 冲突）。

用法:
  python3 qc_detectors.py --clip /data/night/clips/x.mp4 --frames /data/night/frames/x \
      --out /data/night/results/x.qc.json [--max-frames 8]

行为:
  - 帧目录优先；若目录无图且给了 clip，用 ffmpeg 均匀抽 --max-frames 帧到该目录。
  - 每个检测维度独立 try/except；失败写进 errors{维度: 原因}，其余维度继续（降级表原则）。

输出统一 JSON（顶层键为冻结契约）:
{
  "ocr_texts": [...],                     # 所有帧 PaddleOCR 文本拼合
  "face_consistency": [f|null, ...],      # 相邻帧 ArcFace(normed_embedding) 余弦；无脸帧对=null
  "clip_sim": [s, ...],                   # 相邻帧 CLIP ViT-B-32 余弦
  "frame_diff": [{"pair":[i,i+1],"score":s}, ...],   # 帧差突变(>mean+3σ)列表
  "scene_cuts": [sec, ...],               # PySceneDetect ContentDetector 切割点(秒)
  "hand_hints": {...}|null,               # 可选维度：MediaPipe 未装则 null
  "clip_meta": {...},                     # ffprobe 元数据
  "frames": [...], "errors": {...}, "meta": {...}
}
"""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""                      # 本管线纯 CPU，硬禁 GPU
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # HF 权重走镜像（方案铁律4）
os.environ.setdefault("TMPDIR", "/data/night/tmp")

import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def log(msg):
    print(f"[qc {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 帧准备
def collect_frames(frames_dir: Path, max_frames: int):
    if not frames_dir.is_dir():
        return []
    files = sorted(p for p in frames_dir.iterdir() if p.suffix.lower() in IMG_EXTS)
    if len(files) > max_frames > 0:  # 均匀降采样到 max_frames
        idx = sorted({round(i * (len(files) - 1) / (max_frames - 1)) for i in range(max_frames)})
        files = [files[i] for i in idx]
    return [str(p) for p in files]


def extract_frames_ffmpeg(clip: str, out_dir: Path, n: int):
    import shutil
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH")
    out_dir.mkdir(parents=True, exist_ok=True)
    dur = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", clip], stderr=subprocess.DEVNULL).decode().strip() or 0)
    if dur <= 0:
        raise RuntimeError(f"ffprobe duration<=0 for {clip}")
    outs = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        o = out_dir / f"f{i+1:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}",
                        "-i", clip, "-frames:v", "1", "-q:v", "2", str(o)],
                       check=True, stderr=subprocess.DEVNULL)
        outs.append(str(o))
    return outs


def ffprobe_meta(clip: str):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", clip], stderr=subprocess.DEVNULL)
    raw = json.loads(out.decode())
    v = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration_sec": float(raw.get("format", {}).get("duration", 0) or 0),
        "size_bytes": int(raw.get("format", {}).get("size", 0) or 0),
        "codec": v.get("codec_name"),
        "width": v.get("width"), "height": v.get("height"),
        "avg_fps": v.get("avg_frame_rate"), "nb_frames": v.get("nb_frames"),
    }


# ---------------------------------------------------------------- 1. OCR (PaddleOCR, CPU)
def run_ocr(frame_paths, errors):
    from paddleocr import PaddleOCR
    # enable_mkldnn=False: paddle 3.3.1 onednn/PIR 执行器 bug（冒烟实测，见 smoke_qc.json）
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_textline_orientation=False, lang="ch", enable_mkldnn=False)
    texts = []
    for f in frame_paths:
        try:
            res = ocr.predict(f)                       # PaddleOCR 3.x
            for r in res:
                texts.extend(list(r["rec_texts"]))
        except AttributeError:
            res = ocr.ocr(f, cls=False)                # PaddleOCR 2.x 回退
            for page in res or []:
                for line in page or []:
                    texts.append(line[1][0])
    return texts


# ---------------------------------------------------------------- 2. 人脸一致性 (InsightFace ArcFace, onnxruntime-CPU)
def run_face(frame_paths, errors):
    import cv2
    import numpy as np
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))        # ctx_id=-1 → CPU
    embs, det = [], []
    for f in frame_paths:
        img = cv2.imread(f)
        if img is None:
            embs.append(None); det.append(0); continue
        faces = app.get(img)
        det.append(len(faces))
        if not faces:
            embs.append(None)
        else:  # 取最大脸（bbox 面积）
            face = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
            embs.append(face.normed_embedding)         # 已 L2 归一化 → 点积=余弦
    cos = [None if (a is None or b is None) else float(np.dot(a, b))
           for a, b in zip(embs, embs[1:])]
    return cos, {"faces_per_frame": det}


# ---------------------------------------------------------------- 3. CLIP 帧间相似度 (open_clip ViT-B-32, CPU)
_CLIP_MODEL = None


def _get_clip_model(cache_dir: str):
    global _CLIP_MODEL
    if _CLIP_MODEL is None:
        import open_clip, torch
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k", cache_dir=cache_dir)
        model = model.eval().cpu()                     # CPU-only
        _CLIP_MODEL = (model, preprocess, torch)
    return _CLIP_MODEL


def run_clip_sim(frame_paths, errors, cache_dir):
    from PIL import Image
    model, preprocess, torch = _get_clip_model(cache_dir)
    imgs = torch.stack([preprocess(Image.open(f).convert("RGB")) for f in frame_paths]).cpu()
    with torch.no_grad():
        feats = model.encode_image(imgs)
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return [float(x) for x in (feats[:-1] @ feats[1:].T).diagonal()]


# ---------------------------------------------------------------- 4. 帧差突变 (OpenCV)
def run_frame_diff(frame_paths, errors, size=(256, 256)):
    import cv2
    import numpy as np
    gs = []
    for f in frame_paths:
        img = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise RuntimeError(f"cv2.imread failed: {f}")
        gs.append(cv2.resize(img, size).astype(np.float32))
    scores = [float(np.abs(a - b).mean()) for a, b in zip(gs, gs[1:])]
    arr = np.array(scores, dtype=np.float32)
    if arr.size == 0:
        return [], []
    mu, sd = float(arr.mean()), float(arr.std())
    thr = mu + 3.0 * sd
    flagged = [{"pair": [i, i + 1], "score": round(s, 3)}
               for i, s in enumerate(scores) if s > thr]
    return flagged, [round(s, 3) for s in scores]


# ---------------------------------------------------------------- 5. 场景切割 (PySceneDetect)
def run_scene_cuts(clip, errors):
    from scenedetect import ContentDetector, SceneManager, open_video
    video = open_video(clip)
    sm = SceneManager()
    sm.add_detector(ContentDetector(threshold=27.0))
    sm.detect_scenes(video)
    scenes = sm.get_scene_list()
    # 切割点 = 每个后续场景的起点（秒）
    return [round(s[0].get_seconds(), 3) for s in scenes[1:]]


# ---------------------------------------------------------------- 6. 手部提示（可选维度，MediaPipe）
def run_hands(frame_paths, errors):
    try:
        import mediapipe as mp  # noqa: F401
    except ImportError:
        errors["hand_hints"] = "mediapipe 未安装（可选维度，本轮跳过；装法: pip install mediapipe）"
        return None
    try:
        import cv2
        import mediapipe as mp
        hands = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=4)
        per_frame = []
        for f in frame_paths:
            img = cv2.imread(f)
            res = hands.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            per_frame.append(len(res.multi_hand_landmarks or []))
        return {"hands_per_frame": per_frame}
    except Exception as e:  # noqa: BLE001
        errors["hand_hints"] = f"{type(e).__name__}: {e}"
        return None


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="J6 专用检测器管线 (CPU-only)")
    ap.add_argument("--clip", help="clip 视频路径")
    ap.add_argument("--frames", help="帧目录（优先使用；为空且给了 clip 则 ffmpeg 抽帧）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径")
    ap.add_argument("--max-frames", type=int, default=8)
    ap.add_argument("--clip-cache", default="/data/night/models/open_clip")
    args = ap.parse_args()

    t0 = time.time()
    result = {
        "clip": os.path.abspath(args.clip) if args.clip else None,
        "frames_dir": os.path.abspath(args.frames) if args.frames else None,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "device": "cpu (CUDA_VISIBLE_DEVICES forced empty)",
        "ocr_texts": [], "face_consistency": [], "clip_sim": [],
        "frame_diff": [], "scene_cuts": [], "hand_hints": None,
        "clip_meta": None, "frames": [], "errors": {}, "meta": {},
    }
    errors = result["errors"]

    frames = collect_frames(Path(args.frames), args.max_frames) if args.frames else []
    if not frames and args.clip:
        log("帧目录为空 → ffmpeg 均匀抽帧")
        try:
            frames = extract_frames_ffmpeg(args.clip, Path(args.frames), args.max_frames)
        except Exception as e:  # noqa: BLE001
            errors["frame_extraction"] = f"{type(e).__name__}: {e}"
    result["frames"] = frames
    if not frames:
        errors["pipeline"] = "无可用帧（帧目录为空且无 clip/抽帧失败），检测全部跳过"

    if args.clip and os.path.exists(args.clip):
        try:
            result["clip_meta"] = ffprobe_meta(args.clip)
        except Exception as e:  # noqa: BLE001
            errors["ffprobe"] = f"{type(e).__name__}: {e}"

    if frames:
        for name, fn in [
            ("ocr", lambda: run_ocr(frames, errors)),
            ("face_consistency", lambda: run_face(frames, errors)),
            ("clip_sim", lambda: run_clip_sim(frames, errors, args.clip_cache)),
            ("frame_diff", lambda: run_frame_diff(frames, errors)),
            ("scene_cuts", lambda: run_scene_cuts(args.clip, errors) if args.clip else (_ for _ in ()).throw(RuntimeError("no --clip"))),
            ("hand_hints", lambda: run_hands(frames, errors)),
        ]:
            t = time.time()
            try:
                log(f"run {name} ...")
                v = fn()
                if name == "ocr":
                    result["ocr_texts"] = v          # 契约键: ocr_texts
                elif name == "face_consistency":
                    cos, aux = v
                    result[name] = cos
                    result["meta"]["faces_per_frame"] = aux["faces_per_frame"]
                elif name == "frame_diff":
                    flagged, all_scores = v
                    result[name] = flagged
                    result["meta"]["frame_diff_scores"] = all_scores
                else:
                    result[name] = v
                result["meta"][f"{name}_sec"] = round(time.time() - t, 2)
                log(f"{name} OK ({result['meta'][f'{name}_sec']}s)")
            except Exception as e:  # noqa: BLE001
                errors[name] = f"{type(e).__name__}: {e}"
                result["meta"][f"{name}_sec"] = round(time.time() - t, 2)
                log(f"{name} FAILED → {errors[name]}")

    result["meta"]["total_sec"] = round(time.time() - t0, 2)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"WROTE {out}  (errors: {list(errors) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
