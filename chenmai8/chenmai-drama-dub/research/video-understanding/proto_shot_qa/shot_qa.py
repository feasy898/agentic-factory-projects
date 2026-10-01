#!/usr/bin/env python3
"""shot_qa —— 短剧镜头 QA 原型：纯代码关键帧时间轴 → 契约兼容校验 → 与在役
m5 scdet 镜头表交叉对比 →（可选）VLM 读总览图出镜头语义标注。

最小可行点（本轮）：前处理 + 契约兼容 + 离线对比全部真实跑通；
VLM 腿凭证到位前走 BLOCKED（exit 3），不伪造调用结果。

用法：
  python shot_qa.py <video> -o <outdir> [--ep <id>] [--baseline <jobs/xx/02_shots/shots.json>]
                    [--tol 0.6] [--vlm]
退出码：0 成功；2 参数/运行错误；3 VLM 凭证缺失（BLOCKED 语义，非失败伪装）；
4 源视频损坏（解码覆盖率 <50%，BLOCKED 语义）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import kfextract
import vlm_client

# __file__ 是文件路径：parents[0]=proto_shot_qa, [1]=video-understanding, [2]=research, [3]=repo
REPO_ROOT = Path(__file__).resolve().parents[3]


def load_contracts():
    """独立加载 pipeline/contracts.py（绕过包 __init__，避免 torch 重依赖）。

    该文件开了 `from __future__ import annotations`（PEP 563），pydantic 解析
    前向引用要查 sys.modules[模块名]，故 exec 前必须先注册（importlib 标准配方）。
    """
    p = REPO_ROOT / "pipeline" / "contracts.py"
    spec = importlib.util.spec_from_file_location("drama_contracts", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def build_candidate_shots(keyframe_times: list[float], duration: float, min_gap: float = 0.04):
    """关键帧时间轴 → 候选镜头切分 [0, t1, t2, ..., dur]。"""
    bounds = [0.0]
    for t in keyframe_times:
        if 0.0 < t < duration and t - bounds[-1] >= min_gap:
            bounds.append(float(t))
    if duration - bounds[-1] >= min_gap:
        bounds.append(float(duration))
    elif len(bounds) > 1:
        bounds[-1] = float(duration)
    return bounds


def contract_shotsheet(contracts, ep: str, fps: float, dur: float, bounds: list[float]):
    """候选切分 → 契约 C1 ShotSheet（用其只读约束验证兼容性；faces 未知留 0）。"""
    shots = []
    for k in range(len(bounds) - 1):
        shots.append(contracts.Shot(shot_id=f"p{k:04d}", start=bounds[k],
                                    end=bounds[k + 1], cut="hard" if k > 0 else "hard",
                                    faces=0))
    return contracts.ShotSheet(ep=ep, fps=max(1, round(fps)), dur=round(float(dur), 3),
                               shots=shots)


def compare_with_baseline(my_bounds: list[float], baseline: dict, tol: float) -> dict:
    """我的变化点 vs m5 scdet 切点（±tol 秒邻域匹配）→ 覆盖率报告。

    口径声明：关键帧=画面变化呈现点（含字幕弹出等镜头内变化，且稳定帧略滞后于切点），
    不是转场检测器；本对比度量的是"变化点时间轴对真实切点的覆盖度"。
    """
    m5_cuts = [float(s["start"]) for s in baseline.get("shots", [])][1:]
    my_cuts = my_bounds[1:-1]  # 去掉 0 与片尾
    matched_mine = 0
    mine_detail = []
    for c in my_cuts:
        near = [m for m in m5_cuts if abs(m - c) <= tol]
        ok = bool(near)
        matched_mine += ok
        mine_detail.append({"t": round(c, 3), "matches_m5": ok})
    matched_m5 = sum(1 for m in m5_cuts if any(abs(m - c) <= tol for c in my_cuts))
    prec = matched_mine / len(my_cuts) if my_cuts else None
    rec = matched_m5 / len(m5_cuts) if m5_cuts else None
    f1 = (2 * prec * rec / (prec + rec)) if (prec is not None and rec is not None
                                             and prec + rec > 0) else None
    return {
        "tolerance_s": tol,
        "m5_cut_count": len(m5_cuts),
        "my_changepoint_count": len(my_cuts),
        "matched_of_mine": matched_mine,
        "matched_of_m5": matched_m5,
        "precision_of_mine": round(prec, 4) if prec is not None else None,
        "recall_of_m5": round(rec, 4) if rec is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "my_changepoints": mine_detail,
        "m5_cuts": [round(c, 3) for c in m5_cuts],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="短剧镜头 QA 原型（worker-B）")
    ap.add_argument("video")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--ep", default=None)
    ap.add_argument("--baseline", default=None, help="m5 产物 shots.json（可选）")
    ap.add_argument("--tol", type=float, default=0.6)
    ap.add_argument("--vlm", action="store_true", help="VLM 读总览图（凭证缺失 exit 3）")
    a = ap.parse_args()

    video = Path(a.video)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ep = a.ep or video.stem

    try:
        meta = kfextract.extract(video, out)
    except kfextract.DecodeCoverageError as e:
        # 源文件损坏：写 BLOCKED 报告（不产 keyframes.json），exit 4 —— 不静默吞坏源
        report = {
            "video": str(video),
            "ep": ep,
            "status": "BLOCKED-corrupt-source",
            "reason": str(e),
        }
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 4
    kf_times = [k["time"] for k in meta["keyframes"]]

    contracts = load_contracts()
    bounds = build_candidate_shots(kf_times, meta["duration"])
    sheet = contract_shotsheet(contracts, ep, meta["fps"], meta["duration"], bounds)
    # 契约校验通过即证明纯代码时间轴可无损落 C1 形态
    sheet.model_validate(sheet.model_dump())

    report = {
        "video": str(video),
        "ep": ep,
        "duration_s": round(meta["duration"], 3),
        "fps": meta["fps"],
        "resolution": f'{meta["width"]}x{meta["height"]}',
        "threshold_auto": meta["threshold"],
        "noise_median": meta["noise_median"],
        "keyframe_count": meta["keyframe_count"],
        "overview_count": meta["overview_count"],
        "overviews": meta["overviews"],
        "candidate_bounds": [round(b, 3) for b in bounds],
        "contract_c1_shotshot_valid": True,
        "contract_shot_count": len(sheet.shots),
    }

    if a.baseline:
        baseline = json.loads(Path(a.baseline).read_text(encoding="utf-8"))
        report["baseline_compare"] = compare_with_baseline(bounds, baseline, a.tol)

    if a.vlm:
        try:
            notes = vlm_client.describe_all(meta["overviews"])
            (out / "vlm_notes.json").write_text(
                json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
            report["vlm"] = {"status": "ok", "sheets_read": len(notes)}
        except vlm_client.CredsBlocked as e:
            report["vlm"] = {"status": "BLOCKED", "reason": str(e)}
            (out / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps(report["vlm"], ensure_ascii=False))
            return 3

    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "video", "duration_s", "keyframe_count", "overview_count",
        "contract_shot_count")}, ensure_ascii=False))
    if a.baseline:
        bc = report["baseline_compare"]
        print(json.dumps({k: bc[k] for k in (
            "m5_cut_count", "my_changepoint_count", "matched_of_m5",
            "recall_of_m5", "precision_of_mine")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
