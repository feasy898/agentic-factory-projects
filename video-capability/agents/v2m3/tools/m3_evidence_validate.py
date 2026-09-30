"""V2-M3: evidence_transfer 合成源结构保持度验证 (SPECS_V2 §5.4 必做, M3 核心佐证)。

流程:
1. make_synthetic_source ×2 (虾滑/毛肚主图 + 程序 zoompan + 确定性粒子, 运动GT已知)
   → assets/evidence/synthetic_demo_source_0{1,2}.mp4 (+首帧 PNG);
2. evidence.generate 低强度重绘 (denoise 扫描, 缺省 0.30);
3. structural_persistence: 源/输出 RAFT 光流场相关性 + 深度图相关性;
4. 对照组: 正控=源的重编码副本 (应≈高相关, 锚定刻度); 负控=不同资产的 kenburns
   (不同运动, 应低相关) → 量化"结构保持度"有上界与下界参照。
产出: workdir/logs/v2m3_evidence_validation.json (报告引用)。

用法 (GPU): python tools/m3_evidence_validate.py [--sweep 0.30] [--skip-gen]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SOURCES = [
    {"id": "01", "base": "assets/products/shrimp_01.png", "shot": "S18",
     "prompt": "close-up of fresh hand-made shrimp paste on a ceramic dish, warm amber lighting, professional food photography"},
    {"id": "02", "base": "assets/products/maodu_01.png", "shot": "S19",
     "prompt": "close-up of fresh beef tripe on a dark plate, warm amber lighting, professional food photography"},
]


def first_frame_png(src_mp4: Path, out_png: Path) -> None:
    from src.gen.evidence import read_source_frames

    Image_first = read_source_frames(str(src_mp4), 1, (480, 832))[0]
    Image_first.save(out_png)


def reencode_copy(src: Path, dst: Path) -> Path:
    cp = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src),
         "-c:v", "libx264", "-preset", "fast", "-crf", "28", "-pix_fmt", "yuv420p", str(dst)],
        capture_output=True, text=True, timeout=300)
    if cp.returncode != 0:
        raise RuntimeError(f"重编码失败: {cp.stderr[-300:]}")
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", default="0.30", help="逗号分隔 denoise 扫描, 如 0.20,0.30,0.35")
    ap.add_argument("--skip-sources", action="store_true", help="源已生成, 跳过第 1 步")
    ap.add_argument("--out", default=str(REPO / "workdir" / "logs" / "v2m3_evidence_validation.json"))
    args = ap.parse_args()
    sweep = [float(x) for x in str(args.sweep).split(",")]
    for d in sweep:
        if not (0.2 <= d <= 0.35):
            raise ValueError(f"denoise {d} 超出 SPECS_V2 §5.4 范围 0.2-0.35")

    ev_dir = REPO / "assets" / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    cand_dir = REPO / "workdir" / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "README.md").write_text(
        "# assets/evidence — 证据转移车道源视频\n\n"
        "用户放入实拍视频 (如手机竖拍 30 秒沸腾锅), 并在镜头卡 `evidence_asset` 字段指向该文件, "
        "即激活 evidence_transfer 车道 (SPECS_V2 §5.4)。\n\n"
        "- 本轮成片中的证据镜头使用 `synthetic_demo_source_*.mp4` 合成测试源演示\n"
        "  (程序 zoompan+确定性粒子合成, 运动 ground truth 已知), 报告标注**演示源, 非真实实拍**。\n"
        "- 源视频建议: 竖版 480×832 比例、时长 3-5s、画面运动平缓。\n",
        encoding="utf-8")

    report: dict = {"sweep": sweep, "sources": [], "runs": [], "controls": {}}

    # 1. 合成源
    if not args.skip_sources:
        from src.gen.evidence import make_synthetic_source

        for s in SOURCES:
            t0 = time.monotonic()
            out = ev_dir / f"synthetic_demo_source_{s['id']}.mp4"
            meta = make_synthetic_source(str(REPO / s["base"]), str(out),
                                         n_frames=49, fps=16, size=(480, 832))
            first_frame_png(out, ev_dir / f"synthetic_demo_source_{s['id']}_first.png")
            meta["gen_seconds"] = round(time.monotonic() - t0, 1)
            meta["id"] = s["id"]
            meta["base"] = s["base"]
            report["sources"].append(meta)
            print(f"合成源 {s['id']}: {out.name} ({meta['gen_seconds']}s)")

    # 2+3. 重绘 + 结构保持度
    from src.gen.evidence import (
        generate as ev_generate,
        load_raft_flow_fn,
        structural_persistence,
    )
    from src.gen.wan import load_wan_pipeline

    pipe = load_wan_pipeline(device="cuda")
    flow_fn = load_raft_flow_fn(device="cuda")

    for s in SOURCES:
        src = ev_dir / f"synthetic_demo_source_{s['id']}.mp4"
        card = {
            "shot_id": s["shot"], "duration_sec": 3, "resolution": [480, 832], "fps": 16,
            "prompt_en": s["prompt"],
            "negative": ["human face", "hands", "fingers", "text", "watermark", "logo",
                         "deformed", "extra limbs", "melting", "liquid"],
            "evidence_asset": str(src),
        }
        for d in sweep:
            out = cand_dir / f"v2m3_ev_{s['id']}_d{int(d * 100):03d}.mp4"
            t0 = time.monotonic()
            meta = ev_generate(card, seed=99, out_path=str(out), pipeline=pipe, denoise=d)
            pers = structural_persistence(str(src), str(out), flow_fn=flow_fn, n_pairs=6,
                                          size=(480, 832), with_depth=True)
            run = {"source": src.name, "denoise": d, "out": out.name,
                   "gen_seconds": meta.get("gen_seconds"), "persistence": pers}
            report["runs"].append(run)
            print(f"重绘 {src.name} d={d}: flow_cos={pers['flow_cos']} "
                  f"pearson={pers['flow_pearson']} epe={pers['epe_px']}px "
                  f"depth0={pers.get('depth_corr_first')} depthN={pers.get('depth_corr_last')} "
                  f"({meta.get('gen_seconds')}s)")
            # GPU 串行纪律: 每轮清缓存
            try:
                import torch

                torch.cuda.empty_cache()
            except Exception:
                pass

    # 4. 对照组 (源 01)
    src = ev_dir / "synthetic_demo_source_01.mp4"
    pos = cand_dir / "v2m3_ctl_pos_reencode.mp4"
    reencode_copy(src, pos)
    neg_base = REPO / "assets" / "products" / "soup_01.png"
    neg = cand_dir / "v2m3_ctl_neg_kenburns.mp4"
    from src.gen.kenburns import run_kenburns

    run_kenburns(str(neg_base), str(neg), "pan_left", 3.0625, 16, 480, 832)
    report["controls"] = {
        "positive_reencode": structural_persistence(str(src), str(pos), flow_fn=flow_fn,
                                                    n_pairs=6, size=(480, 832), with_depth=False),
        "negative_unrelated_motion": structural_persistence(str(src), str(neg), flow_fn=flow_fn,
                                                            n_pairs=6, size=(480, 832), with_depth=False),
    }
    print(f"正控(重编码副本): flow_cos={report['controls']['positive_reencode']['flow_cos']}")
    print(f"负控(不同运动 kenburns): flow_cos={report['controls']['negative_unrelated_motion']['flow_cos']}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
