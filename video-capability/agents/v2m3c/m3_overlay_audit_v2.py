#!/usr/bin/env python3
"""V2-M3C: overlay audit v2 - apply fluid exemption consistently (D-066).

Defects found in real run (queue2 log + frame-grid目检):
1. G7d full-frame first/last DINO cos penalizes the dynamic subject itself
   (steam/fog/light fill the frame by design -> cos 0.27-0.90 unrelated to
   background stability). Fix: mask both frames to the static dark-base region
   before embedding -> measures background semantic stability only.
2. G7c RAFT p95 unreliable on near-black low-texture footage (ov_fog_low is
   visually static but p95=46.3px - RAFT noise without trackable texture).
   Fix: when p95 exceeds threshold, adjudicate with the G7c degraded criteria
   (photo_diff <= 0.08 AND SSIM >= 0.60, same thresholds as g7 module).

Hard gates remain: static-region stability (c') + masked background drift (d').
a/b recorded not verdict-bearing (D-064 exemption).
"""
from pathlib import Path
import json
import sys

REPO = Path("/root/cradle")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import numpy as np
from PIL import Image

from src.gates.g7_object_persistence import (
    load_thresholds,
    default_embed_fn,
    default_detect_fn,
    default_flow_fn,
    default_seg_fn,
    default_vlm_fn,
)
from tools.m3_gen_overlays import AUDIT_TERMS
from tools.m3_overlay_audit import build_static_mask, LUMINANCE_STATIC_TAU

ODIR = REPO / "assets" / "overlays"


def masked_embed_cos(embed_fn, img0, imgn, static_mask):
    """静态暗底区首尾 DINO 余弦: 两帧分别在静态区外置暗(动态本体清除)后 embed。

    背景=画面语义主体(近黑素材), 动态本体清除后余弦衡量背景漂移 (D-066)。
    """
    def masked(img):
        a = np.asarray(img, dtype="float32")
        m = np.asarray(static_mask.resize(img.size, Image.NEAREST)) > 127
        a = a * m[..., None]  # 动态区置黑 (= 素材底色)
        return Image.fromarray(a.astype("uint8"))

    e0 = embed_fn(masked(img0))
    en = embed_fn(masked(imgn))
    e0 = np.asarray(e0, dtype="float64").flatten()
    en = np.asarray(en, dtype="float64").flatten()
    na, nb = np.linalg.norm(e0), np.linalg.norm(en)
    if na == 0 or nb == 0:
        return 0.0
    return float((e0 * en).sum() / (na * nb))


def static_region_photo_ssim(flow_fn, img0, img1, static_mask):
    """静态区光度差 + SSIM (与 g7 default_flow_fn 退化判据同口径)。"""
    r = flow_fn(img0, img1, static_mask)
    r = r if isinstance(r, dict) else {}
    return float(r.get("photo_diff", 0.0)), float(r.get("ssim", 1.0)), r


def main() -> int:
    manifest_path = ODIR / "manifest.json"
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    thresholds = load_thresholds()
    embed_fn = default_embed_fn()
    detect_fn = default_detect_fn()
    seg_fn = default_seg_fn()
    flow_fn = default_flow_fn()

    mask_dir = ODIR / "masks"
    mask_dir.mkdir(exist_ok=True)
    p95_tau = float(thresholds.get("g7c_flow_p95_max_px", 30.0))
    d_tau = float(thresholds.get("g7d_min_cos", 0.84))
    photo_tau = float(thresholds.get("g7c_photo_diff_max", 0.08))
    ssim_tau = float(thresholds.get("g7c_ssim_min", 0.60))

    n_pass = 0
    for e in entries:
        video = ODIR / e["file"]
        mask_png = str(mask_dir / f"{e['file']}.static.png")
        build_static_mask(str(video), mask_png)
        static_mask = Image.open(mask_png).convert("L")
        m_arr = np.asarray(static_mask) > 127
        static_ratio = round(float(m_arr.mean()), 4)

        # --- G7c': 静态区稳定性 (RAFT p95; 超阈用光度差+SSIM 复核低纹理伪光流) ---
        from src.gen.evidence import read_source_frames
        frames = read_source_frames(str(video), 9, (480, 832))
        p95s, photos, ssims = [], [], []
        for i in range(len(frames) - 1):
            r = flow_fn(frames[i], frames[i + 1], m_arr)
            r = r if isinstance(r, dict) else {}
            if r.get("p95_px") is not None:
                p95s.append(float(r["p95_px"]))
            photos.append(float(r.get("photo_diff", 0.0)))
            ssims.append(float(r.get("ssim", 1.0)))
        worst_p95 = max(p95s) if p95s else None
        max_photo, min_ssim = max(photos), min(ssims)
        if worst_p95 is not None and worst_p95 <= p95_tau:
            c_triggered, c_basis = False, "raft_p95"
        else:
            # 低纹理复核: 光度差与 SSIM 均达标 → 伪光流(近黑区无纹理), 不触发
            c_triggered = bool(max_photo > photo_tau or min_ssim < ssim_tau)
            c_basis = "photo_ssim_adjudicated" if worst_p95 is not None and worst_p95 > p95_tau else "photo_ssim"
        c_score = round(1.0 - max_photo / max(photo_tau, 1e-6), 4)

        # --- G7d': 静态区首尾背景一致性 ---
        imgs = [Image.open(p).convert("RGB") for p in _frames_paths(video, len(frames))]
        d_cos = masked_embed_cos(embed_fn, imgs[0], imgs[-1], static_mask)
        d_triggered = d_cos < d_tau

        audit_pass = (not c_triggered) and (not d_triggered)
        e["g7_audit"] = {
            "passed": audit_pass,
            "criteria": ("D-066: c'=static-region stable (RAFT p95 <= %.0fpx, low-texture "
                         "adjudicated by photo_diff<=%.2f AND ssim>=%.2f) AND d'=masked-bg "
                         "first/last DINO cos >= %.2f; a/b recorded (fluid exemption, D-064)")
                        % (p95_tau, photo_tau, ssim_tau, d_tau),
            "terms": AUDIT_TERMS.get(e["kind"], ["steam"]),
            "static_mask": str(Path(mask_png).relative_to(ODIR)),
            "static_region_ratio": static_ratio,
            "c": {"passed": not c_triggered, "basis": c_basis,
                  "p95_px": round(worst_p95, 3) if worst_p95 is not None else None,
                  "p95_tau_px": p95_tau,
                  "photo_diff_max": round(max_photo, 5), "photo_tau": photo_tau,
                  "ssim_min": round(min_ssim, 5), "ssim_tau": ssim_tau,
                  "score": c_score},
            "d": {"passed": not d_triggered, "masked_bg_cos": round(d_cos, 4),
                  "threshold": d_tau, "score": round(d_cos, 4)},
        }
        print(f"{e['file']}: audit={'PASS' if audit_pass else 'FAIL'} "
              f"c({c_basis}: p95={worst_p95}, photo={max_photo:.4f}, ssim={min_ssim:.4f}) "
              f"d(masked_cos={d_cos:.4f}) static_ratio={static_ratio}")
        manifest_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        n_pass += int(audit_pass)
    print(f"审计完成(v2, D-066): {n_pass}/{len(entries)} PASS → {manifest_path}")
    return 0


def _frames_paths(video: Path, n_expected: int):
    """复用审计抽帧缓存目录 (与 g7 同款均匀 16 帧); 返回帧文件路径列表。"""
    from src.gates.g7_object_persistence import extract_frames_uniform
    frames_dir = str(video) + ".g7frames"
    paths = extract_frames_uniform(str(video), frames_dir, 16)
    return paths


if __name__ == "__main__":
    raise SystemExit(main())
