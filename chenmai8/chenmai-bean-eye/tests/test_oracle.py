"""M4 真值分割 OracleSeg eval（W4a · beaneye/segment/oracle.py）。

运行（仓库根）::

    pytest tests/test_oracle.py -q

覆盖（W4a 任务书自验收线）：

1. **真值透传**：OracleSeg 逐粒 BeanMask 与合成 manifest 完全一致——top 面
   多边形/bbox/质心/面积逐字段透传；bottom 面由真值多边形解析重算（M12
   成对语义：manifest 几何字段为 top 口径）；栅格口径上预测多边形栅格化
   == RLE 真值栅格**逐字节相等 → 逐豆 IoU = 1.0**（M4 spec 通过线
   「Oracle IoU=1.0」，双面全查）；
2. **与 classic 的 IoU 对照报告落盘**：同一合成盘走真实链路（calibrate_pair
   ArUco 标定 → warp_to_tray 正射网格 → M13 管线同口径 BGR→RGB 输入），
   OracleSeg（=真值上界）与 ClassicSeg 逐豆最大 IoU 匹配（匈牙利），对照
   报告落盘 ``out/eval/oracle_vs_classic_report.json``（oracle 侧 IoU、
   classic 侧逐豆 IoU/粒数误差/耗时）。classic 通过线本任务书未给，按
   观测值留保守护栏（粘连切分是 ClassicSeg 已知短板，§9 风险表），实测值
   以报告为准如实记录；
3. 索引与错误面：batch 目录扫描（write_batch 产物）/ 内存 SynthTray /
   labels dict 三种来源；未知 scan_id、重复注册、非法 side、非法 labels
   （版本/结构/多边形/坐标）、文件缺失、空目录 → 一律 OracleSegError；
4. 契约与工程线：SegResult JSON 无损往返、确定性（同输入逐字段一致）、
   mask_id→真值标注 O(1) 回查（smoke_synth_chain 的 truth_by_mask 同约定）、
   M13 装配器注入不降级、normalize_seg_result 兼容。

测试盘：2048 画布（classic 的 px/mm 口径）小豆数 + module 级共享，控制
套件时长。
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from scipy.optimize import linear_sum_assignment

from beaneye.acquisition.base import write_json
from beaneye.app.components import build_components, normalize_seg_result
from beaneye.calibration import calibrate_pair, warp_to_tray
from beaneye.schemas import SegResult, TrayScan
from beaneye.segment import ClassicSeg, OracleSeg, OracleSegError
from beaneye.segment.oracle import SUPPORTED_LABELS_VERSION
from beaneye.synth import (
    ComposeConfig,
    compose_tray,
    labels_to_json,
    sample_library,
    write_batch,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "out" / "eval" / "oracle_vs_classic_report.json"


# ---------------------------------------------------------------------------
# 共享夹具：2048 画布合成盘（豆数适中、含接触对，classic 有真实差距可对照）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def library():
    return sample_library(20260929, 20)


@pytest.fixture(scope="module")
def tray(library):
    cfg = ComposeConfig(
        version=1,
        width_px=2048,
        height_px=2048,
        margin_mm=20.0,
        n_beans_min=14,
        n_beans_max=18,
        defect_rate=0.35,
        class_weights={
            "black": 2.0, "mold": 2.0, "sour": 1.0, "insect": 2.0, "dried": 1.0,
            "broken": 2.0, "brocade": 1.0, "shell": 1.0, "elephant": 1.0,
            "peaberry": 1.0, "immature": 1.0, "faded": 1.0,
        },
        contact_min=2,
        contact_max=4,
        overlap_depth=0.75,
        free_factor=1.08,
        scale_jitter=0.08,
        angle_jitter=180.0,
        pair_jitter_mm=0.6,
        mirror_bottom=True,
        per_class=20,
        library_seed=20260929,
    )
    return compose_tray(seed=2026, config=cfg, library=library)


@pytest.fixture(scope="module")
def labels(tray) -> dict:
    return labels_to_json(tray, with_rle=True)


@pytest.fixture(scope="module")
def oracle(labels) -> OracleSeg:
    return OracleSeg(labels_by_scan={labels["scan_id"]: labels})


@pytest.fixture(scope="module")
def warped_rgb(tray):
    """M13 管线同口径：calibrate_pair → warp_to_tray → BGR→RGB（每面一张）。"""
    calib = calibrate_pair(tray.top_bgr, tray.bottom_bgr)
    grid = warp_to_tray(tray.top_bgr, np.asarray(calib.H_top, dtype=np.float64), None)
    return {
        "top": cv2.cvtColor(grid, cv2.COLOR_BGR2RGB),
        "bottom": cv2.cvtColor(
            warp_to_tray(tray.bottom_bgr, np.asarray(calib.H_bottom, dtype=np.float64), None),
            cv2.COLOR_BGR2RGB,
        ),
    }


def make_scan(scan_id: str) -> TrayScan:
    return TrayScan(
        scan_id=scan_id,
        sample_id="s-oracle",
        tray_id="t-oracle",
        top_image="img/top.png",
        bottom_image="img/bottom.png",
        calibration=None,
        captured_at="2026-09-29T10:00:00+00:00",
        source="synth",
    )


# ---------------------------------------------------------------------------
# 度量工具（与 tests/test_segment.py 同口径）
# ---------------------------------------------------------------------------


def rasterize_mm(masks, grid_px: int, tray_mm: float) -> list[np.ndarray]:
    """BeanMask.polygon（盘面 mm）→ 托盘 mm 网格布尔掩码（测试侧独立栅格化）。"""
    out = []
    for m in masks:
        poly = np.asarray(m.polygon, dtype=np.float64) * (grid_px / tray_mm)
        canvas = np.zeros((grid_px, grid_px), dtype=np.uint8)
        cv2.fillPoly(canvas, [np.round(poly).astype(np.int32)], 1)
        out.append(canvas.astype(bool))
    return out


def iou(a: np.ndarray, b: np.ndarray) -> float:
    union = int((a | b).sum())
    return float((a & b).sum()) / union if union else 0.0


def match_max_iou(gts, preds) -> tuple[list[float], list[int]]:
    """一对一最大 IoU 匹配；返回 (逐 GT IoU, 配到的 pred 下标，未配=-1)。"""
    if not preds:
        return [0.0] * len(gts), [-1] * len(gts)
    mat = np.zeros((len(gts), len(preds)), dtype=np.float64)
    for i, g in enumerate(gts):
        g = g > 0  # truth_rasters 为 uint8 {0,255}，统一布尔口径
        for j, p in enumerate(preds):
            mat[i, j] = iou(g, p)
    row, col = linear_sum_assignment(1.0 - mat)
    best = [0.0] * len(gts)
    which = [-1] * len(gts)
    for r, c in zip(row, col):
        if mat[r, c] > 0.05:
            best[r] = float(mat[r, c])
            which[r] = int(c)
    return best, which


# ---------------------------------------------------------------------------
# 1) 真值透传：BeanMask 逐字段 == manifest（top 透传 / bottom 解析重算）
# ---------------------------------------------------------------------------


def test_truth_passthrough_top_exact(labels, oracle):
    scan_id = labels["scan_id"]
    res = oracle.predict(None, make_scan(scan_id))  # img 不参与真值透传
    assert res.scan_id == scan_id and res.side == "top"
    assert len(res.masks) == len(labels["beans"])

    for i, (m, entry) in enumerate(zip(res.masks, labels["beans"])):
        assert m.mask_id == f"top_{i:04d}"
        assert m.side == "top" and m.source == "oracle" and m.conf == 1.0
        # 多边形逐点透传（JSON 往返后的 3 位小数真值）
        assert m.polygon == [[float(x), float(y)] for x, y in entry["poly_mm_top"]]
        # top 口径几何字段逐字段透传
        assert m.bbox_mm == tuple(float(v) for v in entry["bbox_mm"])
        assert m.area_mm2 == float(entry["area_mm2"])
        assert m.centroid_mm == tuple(float(v) for v in entry["centroid_mm"])
        x0, y0, x1, y1 = m.bbox_mm
        assert x0 <= x1 and y0 <= y1 and res.runtime_s >= 0.0


def test_truth_passthrough_bottom_recomputed(labels, oracle):
    scan_id = labels["scan_id"]
    masks = oracle.masks_for(scan_id, side="bottom")
    assert len(masks) == len(labels["beans"])

    def shoelace(poly):
        x, y = poly[:, 0], poly[:, 1]
        return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)

    for m, entry in zip(masks, labels["beans"]):
        poly = np.asarray(entry["poly_mm_bottom"], dtype=np.float64)
        assert m.side == "bottom" and m.source == "oracle" and m.conf == 1.0
        assert m.polygon == [[float(x), float(y)] for x, y in entry["poly_mm_bottom"]]
        # bottom 真值几何 = 真值多边形解析重算（与 compose 同公式、3 位小数）
        assert m.area_mm2 == pytest.approx(round(shoelace(poly), 3), abs=1e-9)
        assert m.bbox_mm == pytest.approx(
            (
                round(float(poly[:, 0].min()), 3),
                round(float(poly[:, 1].min()), 3),
                round(float(poly[:, 0].max()), 3),
                round(float(poly[:, 1].max()), 3),
            ),
            abs=1e-9,
        )
        # M12 成对语义：两面同一粒豆（同长轴/长宽比/弦切），面积应一致（变体
        # 波纹相位差异允许微小出入）
        assert abs(m.area_mm2 - entry["area_mm2"]) / entry["area_mm2"] <= 0.05, entry["bean_id"]


# ---------------------------------------------------------------------------
# 2) 栅格口径：Oracle IoU = 1.0（M4 spec 通过线，双面全查，逐字节相等）
# ---------------------------------------------------------------------------


def test_oracle_raster_iou_is_one_both_sides(labels, oracle):
    scan_id = labels["scan_id"]
    grid_px = labels["tray"]["rle_grid_px"]
    tray_mm = labels["tray"]["tray_mm"]
    for side in ("top", "bottom"):
        truth = oracle.truth_rasters(scan_id, side)
        pred = rasterize_mm(oracle.masks_for(scan_id, side=side), grid_px, tray_mm)
        assert len(truth) == len(pred) == len(labels["beans"])
        for t, p, entry in zip(truth, pred, labels["beans"]):
            # 逐字节相等强于 IoU=1.0：透传多边形栅格化 == 合成器 RLE 真值栅格
            assert np.array_equal(t > 0, p), f"{entry['bean_id']}.{side} 栅格不一致"
            assert iou(t > 0, p) == 1.0


# ---------------------------------------------------------------------------
# 3) W4a 落盘件：oracle（真值上界）vs classic 逐豆 IoU 对照报告
# ---------------------------------------------------------------------------


def test_oracle_vs_classic_iou_report_written(labels, oracle, tray, warped_rgb):
    scan_id = labels["scan_id"]
    grid_px = labels["tray"]["rle_grid_px"]
    tray_mm = labels["tray"]["tray_mm"]
    scan = make_scan(scan_id)
    tray_rows: list[dict] = []
    classic_overall: list[float] = []

    for side in ("top", "bottom"):
        seg = OracleSeg(labels_by_scan={scan_id: labels}, side=side)  # 按面各备实例（协议适配）
        res_o = seg.predict(warped_rgb[side], scan)  # 真值上界
        assert len(res_o.masks) == len(labels["beans"])
        truth = oracle.truth_rasters(scan_id, side)
        o_ras = rasterize_mm(res_o.masks, grid_px, tray_mm)
        o_ious = [iou(t > 0, p) for t, p in zip(truth, o_ras)]
        assert all(x == 1.0 for x in o_ious), f"{side}: oracle 自身 IoU 未达 1.0"

        res_c = ClassicSeg().predict(warped_rgb[side], scan)
        c_ras = rasterize_mm(res_c.masks, grid_px, tray_mm)
        c_ious, _ = match_max_iou(truth, c_ras)
        matched = sum(1 for x in c_ious if x > 0.05)
        classic_overall.extend(c_ious)

        tray_rows.append(
            {
                "side": side,
                "n_beans": len(truth),
                "oracle": {
                    "n_masks": len(res_o.masks),
                    "iou_vs_truth_mean": round(float(np.mean(o_ious)), 6),
                    "iou_vs_truth_min": round(float(np.min(o_ious)), 6),
                    "runtime_s": round(res_o.runtime_s, 4),
                },
                "classic": {
                    "n_masks": len(res_c.masks),
                    "count_error_pct": round(
                        abs(len(res_c.masks) - len(truth)) / len(truth) * 100.0, 2
                    ),
                    "matched": matched,
                    "iou_vs_oracle_mean": round(float(np.mean(c_ious)), 4),
                    "iou_vs_oracle_min": round(float(np.min(c_ious)), 4),
                    "per_bean_iou": [
                        {"bean_id": e["bean_id"], "iou": round(float(v), 4)}
                        for e, v in zip(labels["beans"], c_ious)
                    ],
                    "runtime_s": round(res_c.runtime_s, 4),
                },
            }
        )
        # classic 护栏（任务书未给线，按观测留保守界；真实值以报告为准）：
        # 稀疏为主的小盘上 classic 应配对到绝大多数豆且不塌方
        assert matched / len(truth) >= 0.60, f"{side}: classic 配对率 {matched}/{len(truth)} 过低"
        assert float(np.mean(c_ious)) >= 0.40, f"{side}: classic 平均 IoU 过低"

    report = {
        "report": "oracle_vs_classic_iou",
        "task": "W4a",
        "eval": "tests/test_oracle.py",
        "labels_version": SUPPORTED_LABELS_VERSION,
        "scan_id": scan_id,
        "seed": tray.seed,
        "grid_px": grid_px,
        "tray_mm": tray_mm,
        "semantics": "oracle=合成 manifest 真值透传（上限）；classic 与它的逐豆 IoU 差距即经典 CV 离真值的差距",
        "mean_iou_classic_vs_oracle": round(float(np.mean(classic_overall)), 4),
        "trays": tray_rows,
    }
    write_json(REPORT_PATH, report)

    # 落盘件回读校验：JSON 合法、结构齐全、数值自洽
    assert REPORT_PATH.is_file()
    back = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert back["report"] == "oracle_vs_classic_iou" and back["task"] == "W4a"
    assert len(back["trays"]) == 2 and {r["side"] for r in back["trays"]} == {"top", "bottom"}
    for row in back["trays"]:
        assert row["oracle"]["iou_vs_truth_mean"] == 1.0
        assert row["classic"]["matched"] <= row["n_beans"]
        assert abs(
            row["classic"]["iou_vs_oracle_mean"]
            - float(np.mean([b["iou"] for b in row["classic"]["per_bean_iou"]]))
        ) < 5e-4
    print(
        f"\n[oracle-vs-classic] report={REPORT_PATH} "
        f"mean_iou(classic vs oracle)={report['mean_iou_classic_vs_oracle']}"
        + "".join(
            f"\n  {r['side']}: classic n={r['classic']['n_masks']}/{r['n_beans']} "
            f"matched={r['classic']['matched']} mean_iou={r['classic']['iou_vs_oracle_mean']} "
            f"(oracle IoU={r['oracle']['iou_vs_truth_mean']})"
            for r in tray_rows
        )
    )


# ---------------------------------------------------------------------------
# 4) 索引来源与错误面
# ---------------------------------------------------------------------------


def test_sources_batch_dir_and_tray(tray, labels, tmp_path):
    paths = write_batch(tray, tmp_path / "batch", index=1, with_rle=True)
    seg = OracleSeg.from_batch_dir(tmp_path / "batch")
    assert seg.scan_ids() == [labels["scan_id"]]
    assert seg.bean_ids(labels["scan_id"]) == [e["bean_id"] for e in labels["beans"]]

    from_tray_seg = OracleSeg.from_tray(tray, side="bottom")
    res = from_tray_seg.predict(None, make_scan(tray.scan_id))
    assert res.side == "bottom" and len(res.masks) == len(tray.beans)
    assert paths["labels"].is_file()


def test_unknown_scan_id_duplicate_and_bad_side(labels, oracle):
    with pytest.raises(OracleSegError, match="未索引 scan_id"):
        oracle.predict(None, make_scan("synth_nope"))
    with pytest.raises(OracleSegError, match="重复注册"):
        oracle.register(labels)
    with pytest.raises(OracleSegError, match="side"):
        OracleSeg(side="left")
    seg = OracleSeg()
    with pytest.raises(OracleSegError, match="未索引"):
        seg.masks_for("synth_nope")
    with pytest.raises(OracleSegError, match="side"):
        seg.masks_for(labels["scan_id"], side="middle")


def test_invalid_labels_rejected(tmp_path, labels):
    with pytest.raises(OracleSegError, match="labels_version"):
        OracleSeg(labels_by_scan={"x": {**labels, "labels_version": 99}})
    with pytest.raises(OracleSegError, match="beans"):
        OracleSeg(labels_by_scan={"x": {"labels_version": 1, "scan_id": "x"}})
    bad_poly = {
        "labels_version": 1, "scan_id": "x",
        "beans": [{"bean_id": "b1", "poly_mm_top": [[0.0, 0.0], [1.0, 1.0]],
                   "poly_mm_bottom": [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]]}],
    }
    with pytest.raises(OracleSegError, match="poly_mm_top"):
        OracleSeg(labels_by_scan={"x": bad_poly})
    bad_coord = {
        "labels_version": 1, "scan_id": "x",
        "beans": [{"bean_id": "b1", "poly_mm_top": [[0.0, "x"], [1.0, 1.0], [2.0, 0.0]],
                   "poly_mm_bottom": [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]]}],
    }
    with pytest.raises(OracleSegError, match="数值"):
        OracleSeg(labels_by_scan={"x": bad_coord})
    with pytest.raises(OracleSegError, match="读取失败"):
        OracleSeg(labels_by_scan={"x": tmp_path / "no_such_labels.json"})
    with pytest.raises(OracleSegError, match="不存在"):
        OracleSeg.from_batch_dir(tmp_path / "no_such_dir")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(OracleSegError, match="labels_"):
        OracleSeg.from_batch_dir(empty)


def test_entry_maps_mask_id_to_truth_entry(labels, oracle):
    scan_id = labels["scan_id"]
    e = oracle.entry(scan_id, "top_0003")
    assert e["bean_id"] == labels["beans"][3]["bean_id"]
    assert oracle.entry(scan_id, "bottom_0000")["bean_id"] == labels["beans"][0]["bean_id"]
    with pytest.raises(OracleSegError, match="越界"):
        oracle.entry(scan_id, f"top_{len(labels['beans']):04d}")
    with pytest.raises(OracleSegError, match="约定"):
        oracle.entry(scan_id, "left_0000")


# ---------------------------------------------------------------------------
# 5) 契约与工程线：JSON 往返 / 确定性 / M13 装配器
# ---------------------------------------------------------------------------


def test_determinism_json_roundtrip_and_m13_wiring(labels, oracle, warped_rgb):
    scan = make_scan(labels["scan_id"])
    a = oracle.predict(warped_rgb["top"], scan)
    b = oracle.predict(warped_rgb["top"], scan)
    assert [m.to_json() for m in a.masks] == [m.to_json() for m in b.masks]

    revived = SegResult.from_json(a.to_json())
    assert revived == a  # 契约无损往返（含 source=oracle/conf=1.0 校验）

    # M13 装配器：注入不降级；side 已正确时 normalize 原样放行
    comps = build_components(segment=oracle, allow_probe=False)
    assert not comps.segment.degraded
    via_box = comps.segment.impl.predict(warped_rgb["top"], scan)
    assert via_box.side == "top" and len(via_box.masks) == len(labels["beans"])
    norm = normalize_seg_result(via_box, side="top", scan_id=scan.scan_id)
    assert norm is via_box or norm == via_box

    # 换面：side 属性翻转 → bottom 真值（M12 成对语义，多边形应与 top 不同）
    oracle.side = "bottom"
    try:
        res_b = oracle.predict(warped_rgb["bottom"], scan)
        assert res_b.side == "bottom"
        assert all(m.mask_id.startswith("bottom_") for m in res_b.masks)
        same = sum(
            1
            for mb, mt in zip(res_b.masks, a.masks)
            if mb.polygon == mt.polygon
        )
        assert same < len(a.masks), "mirror_bottom 下 bottom 真值多边形不应与 top 全同"
    finally:
        oracle.side = "top"
