#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_qc.py — 四项检测器冒烟（CPU-only，venv-qc）：
  1. PaddleOCR 识别含文字测试图
  2. InsightFace ArcFace：同人(messi vs 翻转messi)应高相似；不同人(messi vs solvay某脸)应低相似
  3. open_clip ViT-B-32：两帧相似度
  4. ffprobe 读 clip 元数据
各项独立 try/except，失败降级记录。
"""
import os
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TMPDIR", "/data/night/tmp")

import json
import subprocess
import time

RESULTS = {}


def smoke(name):
    def deco(fn):
        t = time.time()
        try:
            RESULTS[name] = {"status": "OK", "data": fn(),
                             "sec": round(time.time() - t, 2)}
        except Exception as e:  # noqa: BLE001
            RESULTS[name] = {"status": "FAIL",
                             "error": f"{type(e).__name__}: {e}",
                             "sec": round(time.time() - t, 2)}
        print(f"[smoke] {name}: {RESULTS[name]['status']} ({RESULTS[name]['sec']}s)", flush=True)
    return deco


@smoke("ocr")
def _():
    from paddleocr import PaddleOCR
    # enable_mkldnn=False: paddle 3.3.1 onednn/PIR 执行器 bug
    # (NotImplementedError ConvertPirAttribute2RuntimeAttribute pir::ArrayAttribute<pir::DoubleAttribute>)
    ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_textline_orientation=False, lang="ch", enable_mkldnn=False)
    res = ocr.predict("/data/night/frames/smoke_ocr/ocr_test.png")
    texts = []
    for r in res:
        texts.extend(list(r["rec_texts"]))
    assert texts, "OCR 未识别出任何文本"
    return {"texts": texts}


@smoke("insightface_arcface")
def _():
    import cv2
    import numpy as np
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))

    def embed(img_bgr):
        faces = app.get(img_bgr)
        if not faces:
            return None, 0
        f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
        return f.normed_embedding, len(faces)

    messi = cv2.imread("/data/night/frames/smoke_faces/messi5.jpg")
    e_messi, n1 = embed(messi)
    e_flip, _ = embed(cv2.flip(messi, 1))          # 同人水平翻转
    # 不同人对照：opencv 样例 solvay.jpg 与 deepface tests/dataset 均已不存在（404），
    # bcebos face_demo 主机不解析 → 本冒烟只做同人对照，跨人对照等真实素材
    assert e_messi is not None, "messi5.jpg 未检出人脸"
    sim_same = float(np.dot(e_messi, e_flip)) if e_flip is not None else None
    return {"sim_same_person_messi_vs_flip": sim_same,
            "faces_detected": {"messi": n1},
            "note": "期望同人翻转 sim>0.5；跨人对照暂缺第二身份素材"}


@smoke("openclip")
def _():
    import torch
    from PIL import Image
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k", cache_dir="/data/night/models/open_clip")
    model = model.eval().cpu()
    paths = ["/data/night/frames/smoke_clip/f01.jpg", "/data/night/frames/smoke_clip/f02.jpg"]
    imgs = torch.stack([preprocess(Image.open(p).convert("RGB")) for p in paths]).cpu()
    with torch.no_grad():
        feats = model.encode_image(imgs)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        sim = float((feats[0] @ feats[1]).cpu())
        # 文字对齐 sanity: "a diagram" vs "a dog"
        from open_clip import tokenize
        txt = tokenize(["a diagram", "a dog"]).cpu()
        with torch.no_grad():
            tfeats = model.encode_text(txt)
            tfeats = tfeats / tfeats.norm(dim=-1, keepdim=True)
        timg = (feats[0:1] @ tfeats.T).cpu().tolist()[0]
    return {"sim_frame01_vs_frame02": sim,
            "img_vs_text_a-diagram_a-dog": [round(x, 4) for x in timg]}


@smoke("ffprobe")
def _():
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         "/data/night/clips/smoke_clip.mp4"])
    raw = json.loads(out.decode())
    v = next(s for s in raw["streams"] if s["codec_type"] == "video")
    return {"duration_sec": raw["format"]["duration"], "codec": v["codec_name"],
            "width": v["width"], "height": v["height"], "avg_fps": v["avg_frame_rate"]}


print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
with open("/data/night/results/smoke_qc.json", "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, ensure_ascii=False, indent=2)
n_fail = sum(1 for v in RESULTS.values() if v["status"] != "OK")
print(f"[smoke] DONE ok={len(RESULTS)-n_fail} fail={n_fail}")
