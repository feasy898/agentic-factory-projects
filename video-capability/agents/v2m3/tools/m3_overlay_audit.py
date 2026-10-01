"""V2-M3: overlay 素材 G7 审计 (SPECS_V2 §5.3: 素材入库前单独过 G7 审计)。

豁免条款口径 (D-064): overlay 素材的"动态本体"就是蒸汽/雾/光斑——按 G7e 豁免条款
它们本属流体/气体元素, 其自身运动不算缺陷。因此审计对象是"静态背景必须稳定":
- G7c (硬性): 静态区 = 首帧亮度 < 60 的暗底区域 (程序确定性蒙版, 白=静态),
  RAFT P95 ≤ 30px (校准阈值) → 背景无漂移;
- G7d (硬性): 首尾全帧 DINO 余弦 ≥ 0.84 → 无整体画面漂移;
- G7a/G7b (记录): 流体主体一致性/计数按豁免条款仅记录不判死 (蒸汽无稳定计数
  与稳定形体属物理本性)。
审计通过 → manifest.g7_audit.passed=true, 才能被 compositing_2d5 挑选。

用法 (GPU): python tools/m3_overlay_audit.py [--overlays assets/overlays]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

LUMINANCE_STATIC_TAU = 60  # 首帧亮度 < 60 → 静态暗底 (动态本体=亮蒸汽/光斑)


def build_static_mask(video_path: str, out_png: str, tau: int = LUMINANCE_STATIC_TAU) -> str:
    """首帧亮度蒙版: 白=静态(暗底), 黑=动态本体(亮蒸汽)。确定性, 无 SAM 依赖。"""
    from src.gen.evidence import read_source_frames

    first = read_source_frames(video_path, 1, (480, 832))[0]
    arr = np.asarray(first.convert("L"), dtype="float32")
    static = arr < tau
    Image.fromarray((static * 255).astype("uint8"), mode="L").save(out_png)
    return out_png


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlays", default=str(REPO / "assets" / "overlays"))
    args = ap.parse_args()
    odir = Path(args.overlays)
    manifest_path = odir / "manifest.json"
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))

    from src.gates.g7_object_persistence import (
        g7_object_persistence,
        load_thresholds,
    )
    from tools.m3_gen_overlays import AUDIT_TERMS

    thresholds = load_thresholds()
    mask_dir = odir / "masks"
    mask_dir.mkdir(exist_ok=True)

    for e in entries:
        if e.get("g7_audit", {}).get("passed"):
            print(f"skip (已过审): {e['file']}")
            continue
        video = odir / e["file"]
        mask_png = str(mask_dir / f"{e['file']}.static.png")
        build_static_mask(str(video), mask_png)
        terms = AUDIT_TERMS.get(e["kind"], ["steam"])
        result = g7_object_persistence(
            str(video), terms, thresholds,
            expected_static_mask=mask_png,
            frames_dir=str(video) + ".g7frames",
        )
        subs = result.get("detail", {})
        gate_passed = bool(result.get("passed"))

        # D-064 判据: c/d 硬性 (背景稳定 + 无整体漂移); a/b 记录不判死 (豁免条款)
        c_ok = bool(subs.get("c", {}).get("skipped", True)) or not subs.get("c", {}).get("triggered", False)
        d_ok = bool(subs.get("d", {}).get("skipped", True)) or not subs.get("d", {}).get("triggered", False)
        audit_pass = c_ok and d_ok
        e["g7_audit"] = {
            "passed": audit_pass,
            "criteria": "D-064: g7c static-bg stable AND g7d no global drift; a/b recorded (fluid exemption)",
            "gate_passed_all_subs": gate_passed,
            "g7_score": result.get("score"),
            "terms": terms,
            "static_mask": str(Path(mask_png).relative_to(odir)),
            "c": {"passed": c_ok, "score": subs.get("c", {}).get("score"),
                  "p95_px": subs.get("c", {}).get("p95_px"),
                  "mask_source": subs.get("c", {}).get("mask_source")},
            "d": {"passed": d_ok, "score": subs.get("d", {}).get("score"),
                  "cos": subs.get("d", {}).get("score")},
            "a": {"passed": not subs.get("a", {}).get("triggered", False),
                  "score": subs.get("a", {}).get("score")},
            "b": {"passed": not subs.get("b", {}).get("triggered", False),
                  "score": subs.get("b", {}).get("score"),
                  "churn": subs.get("b", {}).get("churn"),
                  "counts": subs.get("b", {}).get("counts")},
        }
        print(f"{e['file']}: audit={'PASS' if audit_pass else 'FAIL'} "
              f"c(p95={e['g7_audit']['c']['p95_px']}) d(cos={e['g7_audit']['d']['cos']}) "
              f"a={e['g7_audit']['a']['score']} b(churn={e['g7_audit']['b']['churn']})")
        manifest_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    n_pass = sum(1 for e in entries if e.get("g7_audit", {}).get("passed"))
    print(f"审计完成: {n_pass}/{len(entries)} PASS → {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
