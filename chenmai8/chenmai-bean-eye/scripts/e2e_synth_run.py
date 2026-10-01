"""W4c 端到端：合成盘全链一条命令（classic 分割 + 规则分类 → 三语护照）。

运行（仓库根）::

    python scripts/e2e_synth_run.py --trays 3

链路（plan/开发指令.md §2 数据流；识别腿 = 产品缺省 classic/rules）::

    M12 compose_tray（程序化素材合成整盘对，无外部数据集路径）
      → M3 标定 calibrate_pair + warp_to_tray
      → M4 ClassicSeg（逐面真跑）
      → M5 RulesV0（逐粒真跑）
      → M6 匈牙利上下配对
      → M8 计量 → M9 标准引擎定级
      → M11 TemplateAgent 溯因 → M10 三语质量护照（二维码）

与 scripts/smoke_synth_chain.py 的分工：冒烟脚本在 M4/M5 缺位期用合成真值
直出观测验证「标定→…→护照」六段；本脚本走 **beaneye.app.pipeline.
run_pipeline 与 API 完全同一条装配路径**（build_components 探测
beaneye.segment / beaneye.classify 工厂真实接线 ClassicSeg + RulesV0），
图像 IO、证据裁剪、降级检测、护照校验和全部真跑——识别链任何一环造假
都会在断言处现形。

自验收硬断言（每盘，任一失败 → 非零退出）：
  1. 装配非降级：segment/classify 均为工厂真实接入（degraded_stages 为空）；
  2. 标定：px_per_mm 相对合成真值相对误差 ≤2%、重投影误差 ≤1.5px；
  3. 配对：配对粒数 ≥ 真值 50%（classic 粘连切分为已知短板，§9 风险表；
     实测值如实写入报告，不作更高硬线）；
  4. 计量/定级：bean_count == 配对粒数；standard_id 与 YAML sha 格式合法；
  5. 护照：三语 HTML 各 >20KB；页面内嵌二维码经 zxing-cpp 解码回读，
     report_id / sha256 与 BatchResult 一致。

逐盘**如实记录**（不作硬断言，供报告与后续评测基线）：
  classic 粒数恢复率、真值↔检出 匈牙利质心匹配（6mm 门限）后的逐粒
  分类标签一致率（top/bottom/双面裁决）、grading.defect_counts 与真值
  直方对照。合成盘上 RulesV0 的已知精度（tests/test_classify acc≈0.77）
  决定该一致率有限——按「AI 初检 + 人工复核」定位如实呈现。

产物：out/e2e_synth/ 下逐盘双面整盘图 + 首盘 write_batch 四件套抽样
（labels JSON + manifest.yaml）+ 逐盘 crops 证据 + 三语护照 + summary.json。
全程离线 CPU，不依赖网络与权重。
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import zxingcpp  # noqa: E402

from beaneye.acquisition.base import imwrite_bgr, write_json  # noqa: E402
from beaneye.app import PipelineRequest, build_components, run_pipeline  # noqa: E402
from beaneye.app.pipeline import STAGE_ORDER  # noqa: E402
from beaneye.calibration import load_tray_config  # noqa: E402
from beaneye.report import canonical_sha256, parse_qr_payload  # noqa: E402
from beaneye.schemas import TrayScan  # noqa: E402
from beaneye.synth import ComposeConfig, compose_tray, sample_library, write_batch  # noqa: E402
from beaneye.taxonomy import load_taxonomy  # noqa: E402

# 真值↔检出质心匹配门限（mm）：配对门限 12mm 的一半，只认近邻——
# 弦切豆翻面质心横移实测 ≤4.2mm（冒烟脚本结论），6mm 门限不误吸远邻
MATCH_GATE_MM = 6.0

_QR_RE = re.compile(r'class="qr" src="data:image/png;base64,([A-Za-z0-9+/=]+)"')


def build_config(args: argparse.Namespace) -> ComposeConfig:
    """合成配置：程序化默认（与 configs/synth.yaml 同 schema，程序内直构）。

    缺省**零接触/零重叠**（contact 0-0）= M4 spec 的「稀疏盘」适用场景
    （§9 风险表回退口径：演示用稀疏盘）；--contacts 可开粘连做压力档。
    """
    return ComposeConfig(
        version=1,
        width_px=args.canvas,
        height_px=args.canvas,
        margin_mm=20.0,
        n_beans_min=args.min_beans,
        n_beans_max=args.max_beans,
        defect_rate=args.defect_rate,
        class_weights={
            "black": 3.0, "mold": 2.0, "sour": 2.0, "insect": 2.0, "dried": 2.0,
            "broken": 3.0, "brocade": 2.0, "shell": 1.0, "elephant": 1.0,
            "peaberry": 1.0, "immature": 1.0, "faded": 1.0,
        },
        contact_min=args.contacts_min,
        contact_max=args.contacts_max,
        overlap_depth=0.8,
        free_factor=1.06,
        scale_jitter=0.10,
        angle_jitter=180.0,
        pair_jitter_mm=0.6,
        mirror_bottom=True,
        per_class=20,
        library_seed=20260929,
    )


# ---------------------------------------------------------------------------
# 真值↔检出 对照（报告口径，非链路组件）
# ---------------------------------------------------------------------------


def _gate_match(truth_xy: np.ndarray, obs_xy: np.ndarray, gate_mm: float):
    """质心匈牙利匹配（门限外不成对）。返回 [(truth_i, obs_j, dist), ...]。"""
    if len(truth_xy) == 0 or len(obs_xy) == 0:
        return []
    big = gate_mm * 1000.0
    cost = np.linalg.norm(truth_xy[:, None, :] - obs_xy[None, :, :], axis=2)
    cost[cost > gate_mm] = big
    rows, cols = linear_sum_assignment(cost)
    return [
        (int(r), int(c), float(cost[r, c]))
        for r, c in zip(rows, cols)
        if cost[r, c] < big
    ]


def _poly_centroid(poly) -> tuple[float, float]:
    """多边形质心（cv2.moments，与合成器标注同口径）。"""
    m = cv2.moments(np.asarray(poly, dtype=np.float32))
    if m["m00"] <= 0:
        pts = np.asarray(poly, dtype=np.float64)
        return float(pts[:, 0].mean()), float(pts[:, 1].mean())
    return float(m["m10"] / m["m00"]), float(m["m01"] / m["m00"])


def agreement_stats(tray, beans) -> dict:
    """逐粒对照：配对产物 obs ↔ 合成真值（同一布局坐标，匈牙利质心匹配）。

    - 掩码级：每面检出质心 ↔ 该面真值多边形质心（弦切豆翻面质心横移
      实测 ≤4.2mm，6mm 门限内）匈牙利匹配（6mm 门限）→ 匹配数；
    - 标签级：匹配对上 分类标签 vs 真值类别（top/bottom 各算；双面裁决
      final_defect 以 top 面匹配为锚——M12 成对语义上下同类）。
    """
    truth_cls = [b.cls for b in tray.beans]
    truth_xy = {
        "top": np.asarray([_poly_centroid(b.poly_mm_top) for b in tray.beans]),
        "bottom": np.asarray([_poly_centroid(b.poly_mm_bottom) for b in tray.beans]),
    }

    out: dict = {}
    top_anchor: dict[int, object] = {}
    for side in ("top", "bottom"):
        entries = [(pb, (pb.top if side == "top" else pb.bottom)) for pb in beans
                   if (pb.top if side == "top" else pb.bottom) is not None]
        obs_xy = np.asarray([o.mask.centroid_mm for _, o in entries], dtype=np.float64)
        pairs = _gate_match(truth_xy[side], obs_xy, MATCH_GATE_MM)
        agree = sum(1 for ti, oj, _ in pairs if entries[oj][1].defect == truth_cls[ti])
        out[f"matched_{side}"] = len(pairs)
        out[f"label_agree_{side}"] = agree
        out[f"n_obs_{side}"] = len(entries)
        if side == "top":
            top_anchor = {ti: entries[oj][0] for ti, oj, _ in pairs}

    out["matched_final"] = len(top_anchor)
    out["final_agree"] = sum(
        1 for ti, pb in top_anchor.items() if pb.final_defect == truth_cls[ti]
    )
    return out


# ---------------------------------------------------------------------------
# 单盘全链
# ---------------------------------------------------------------------------


def run_tray(idx: int, seed: int, cfg: ComposeConfig, library, args, data_root: Path) -> dict:
    t_tray = time.perf_counter()
    tray = compose_tray(seed=seed, config=cfg, library=library)
    n_truth = len(tray.beans)
    truth_hist = Counter(b.cls for b in tray.beans if b.cls != "normal")

    # 双面整盘图落盘（中文路径安全封装 imencode/imdecode），管线从盘读回
    img_dir = data_root / "trays" / tray.scan_id
    top_path = imwrite_bgr(img_dir / "top.png", tray.top_bgr)
    bottom_path = imwrite_bgr(img_dir / "bottom.png", tray.bottom_bgr)

    scan = TrayScan(
        scan_id=tray.scan_id,
        sample_id=f"e2e_synth_{idx:04d}",
        tray_id="tray_synth_01",
        top_image=str(top_path.relative_to(data_root)).replace("\\", "/"),
        bottom_image=str(bottom_path.relative_to(data_root)).replace("\\", "/"),
        calibration=None,
        captured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        source="synth",
    )

    # 装配（缺省探测工厂 → ClassicSeg + RulesV0；接不上即显式失败）
    components = build_components()
    degraded = components.degraded_stages()
    assert not degraded, f"盘 {idx}: 识别组件降级 {degraded}（{components.degraded_reasons()}）——e2e 要求产品链真实接线"

    outcome = run_pipeline(
        PipelineRequest(
            scan=scan,
            top_path=top_path,
            bottom_path=bottom_path,
            standard_id=args.standard,
            langs=list(args.langs),
            data_root=data_root,
        ),
        components,
    )
    result = outcome.result

    # ---- 硬断言（任一失败即本脚本失败） ---------------------------------
    assert outcome.degraded_stages == [], f"盘 {idx}: 管线降级 {outcome.degraded_stages}"
    calib = outcome.scan.calibration
    assert calib is not None, f"盘 {idx}: 标定缺失"
    ppm_err = abs(calib.px_per_mm - tray.px_per_mm) / tray.px_per_mm
    assert ppm_err <= 0.02, f"盘 {idx}: px_per_mm 相对误差 {ppm_err:.3%} > 2%"
    assert calib.reproj_err_px <= 1.5, f"盘 {idx}: 重投影误差 {calib.reproj_err_px:.2f}px > 1.5px"
    assert sorted(calib.marker_ids) == [0, 1, 2, 3], f"盘 {idx}: 角码 id {calib.marker_ids}"

    beans = result.beans
    floor = max(1, int(np.ceil(0.5 * n_truth)))
    assert len(beans) >= floor, (
        f"盘 {idx}: 配对粒数 {len(beans)} < 真值 50%（{n_truth}）——classic 检出异常"
    )
    assert result.measurements.bean_count == len(beans)
    assert set(STAGE_ORDER[:8]) <= set(result.timings_s), (
        f"盘 {idx}: 阶段耗时缺失 {result.timings_s}"
    )
    grading = result.grading
    assert grading.standard_id == args.standard, f"盘 {idx}: standard_id {grading.standard_id}"
    assert re.fullmatch(r"[0-9a-f]{64}", grading.standard_yaml_sha), "标准 YAML sha 格式非法"

    # 护照：三语存在 + 体积 + 页内二维码解码回读校验和
    assert outcome.passport is not None, f"盘 {idx}: 护照缺失"
    passport = outcome.passport
    assert sorted(passport.langs) == sorted(args.langs), f"盘 {idx}: 护照语种 {passport.langs}"
    for lang in args.langs:
        html_path = Path(passport.html_paths[lang])
        assert html_path.is_file() and html_path.stat().st_size > 20_000, (
            f"盘 {idx}: {lang} 护照缺失或过小"
        )
        m = _QR_RE.search(html_path.read_text(encoding="utf-8"))
        assert m is not None, f"盘 {idx}: {lang} 护照页未找到二维码图"
        png = base64.b64decode(m.group(1))
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        assert img is not None, f"盘 {idx}: {lang} 二维码 PNG 解码失败"
        found = zxingcpp.read_barcodes(img)
        assert found, f"盘 {idx}: {lang} 二维码解码失败"
        rid, sha = parse_qr_payload(found[0].text)
        assert rid == result.result_id and sha == canonical_sha256(result), (
            f"盘 {idx}: {lang} 二维码回读与 BatchResult 校验和不一致"
        )
        assert found[0].text == passport.qr_payload

    # ---- 如实记录（不作硬线） --------------------------------------------
    ag = agreement_stats(tray, beans)
    row = {
        "index": idx,
        "seed": seed,
        "scan_id": tray.scan_id,
        "result_id": result.result_id,
        "n_truth_beans": n_truth,
        "n_truth_defects": int(sum(truth_hist.values())),
        "paired": outcome.pairing_summary["paired"],
        "top_only": outcome.pairing_summary["top_only"],
        "bottom_only": outcome.pairing_summary["bottom_only"],
        "count_recovery": round(len(beans) / n_truth, 4) if n_truth else None,
        "ppm_err_pct": round(ppm_err * 100, 4),
        "reproj_err_px": round(calib.reproj_err_px, 4),
        "grade": grading.grade,
        "passed": grading.passed,
        "primary_count": grading.primary_count,
        "secondary_count": grading.secondary_count,
        "grading_defect_counts": {k: v for k, v in grading.defect_counts.items() if v > 0},
        "truth_defect_hist": dict(sorted(truth_hist.items())),
        "agreement": ag,
        "label_agree_rate": {
            side: round(ag[f"label_agree_{side}"] / ag[f"matched_{side}"], 4)
            if ag[f"matched_{side}"] else None
            for side in ("top", "bottom")
        },
        "final_agree_rate": round(ag["final_agree"] / ag["matched_final"], 4)
        if ag["matched_final"] else None,
        "degraded": outcome.degraded_stages,
        "timings_s": dict(result.timings_s),
        "passport_runtime_s": round(outcome.passport_runtime_s, 4),
        "tray_total_s": round(time.perf_counter() - t_tray, 3),
        "pipeline_versions": dict(result.pipeline_versions),
    }
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trays", type=int, default=3)
    ap.add_argument("--canvas", type=int, default=2048)
    ap.add_argument("--min-beans", type=int, default=60)
    ap.add_argument("--max-beans", type=int, default=100)
    ap.add_argument("--defect-rate", type=float, default=0.06)
    ap.add_argument("--contacts-min", type=int, default=0, help="接触/重叠目标豆数下限（缺省 0=稀疏盘）")
    ap.add_argument("--contacts-max", type=int, default=0)
    ap.add_argument("--standard", default="cqi_fine_robusta")
    ap.add_argument("--langs", default="zh,en,vi")
    ap.add_argument("--seed0", type=int, default=410001)
    ap.add_argument("--out", default="out/e2e_synth")
    args = ap.parse_args()
    args.langs = [s.strip() for s in args.langs.split(",") if s.strip()]

    t_all = time.perf_counter()
    cfg = build_config(args)
    library = sample_library(cfg.library_seed, cfg.per_class)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for k in range(args.trays):
        seed = args.seed0 + k
        row = run_tray(k + 1, seed, cfg, library, args, out)
        rows.append(row)
        if k == 0:
            # 首盘产物抽样：双面图 + labels JSON（含 RLE 真值）+ manifest.yaml
            tray = compose_tray(seed=seed, config=cfg, library=library)
            paths = write_batch(tray, out / "batch_sample", index=1, with_rle=True)
            row["batch_files"] = sorted(p.name for p in paths.values())
        ag = row["agreement"]
        print(
            f"[{k + 1}/{args.trays}] {row['scan_id']} truth={row['n_truth_beans']} "
            f"paired={row['paired']} recovery={row['count_recovery']} "
            f"agree(top/bot/final)={row['label_agree_rate']['top']}/"
            f"{row['label_agree_rate']['bottom']}/{row['final_agree_rate']} "
            f"grade={row['grade']} ppm_err={row['ppm_err_pct']}% "
            f"t={row['tray_total_s']}s",
            flush=True,
        )

    total_s = time.perf_counter() - t_all
    matched_top = sum(r["agreement"]["matched_top"] for r in rows)
    agree_top = sum(r["agreement"]["label_agree_top"] for r in rows)
    matched_bot = sum(r["agreement"]["matched_bottom"] for r in rows)
    agree_bot = sum(r["agreement"]["label_agree_bottom"] for r in rows)
    matched_fin = sum(r["agreement"]["matched_final"] for r in rows)
    agree_fin = sum(r["agreement"]["final_agree"] for r in rows)
    summary = {
        "e2e": "synth full chain (compose→calibration→classic segment→rules classify→"
               "pairing→metrology→grading→agent→passport x3 langs)",
        "trays": args.trays,
        "standard": args.standard,
        "langs": args.langs,
        "canvas_px": args.canvas,
        "contacts": [args.contacts_min, args.contacts_max],
        "total_s": round(total_s, 1),
        "mean_s_per_tray": round(total_s / args.trays, 2),
        "stage_mean_s": {
            s: round(sum(r["timings_s"][s] for r in rows) / len(rows), 3)
            for s in rows[0]["timings_s"]
        },
        "passport_mean_s": round(sum(r["passport_runtime_s"] for r in rows) / len(rows), 3),
        "beans_truth_total": sum(r["n_truth_beans"] for r in rows),
        "paired_total": sum(r["paired"] for r in rows),
        "count_recovery_mean": round(
            sum(r["count_recovery"] for r in rows) / len(rows), 4
        ),
        "label_agree_rate_total": {
            "top": round(agree_top / matched_top, 4) if matched_top else None,
            "bottom": round(agree_bot / matched_bot, 4) if matched_bot else None,
            "final": round(agree_fin / matched_fin, 4) if matched_fin else None,
        },
        "grades": dict(Counter(r["grade"] for r in rows)),
        "defects_truth_total": sum(r["n_truth_defects"] for r in rows),
        "pipeline_versions": rows[0]["pipeline_versions"],
        "out_root": str(out),
        "rows": rows,
    }
    write_json(out / "summary.json", summary)
    print(
        f"\nE2E PASS: {args.trays} 盘全链（合成→标定→classic分割→规则分类→配对→"
        f"计量→定级→三语护照）硬断言全通过；"
        f"总时长 {total_s:.0f}s（{summary['mean_s_per_tray']}s/盘）；"
        f"粒数恢复率均值 {summary['count_recovery_mean']}；"
        f"标签一致率 {summary['label_agree_rate_total']}（记录值，不作验收线）；"
        f"报告 {out / 'summary.json'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
