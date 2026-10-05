"""train/ 评测度量（私有模块：实例匹配 / AP50 / F1 / 粒数 MAE / 双面配对）。

**仅真实模式导入**（顶部直接依赖 numpy/cv2/scipy；``--dry-run`` 路径不得
import 本模块）。指标口径：

- 掩码 AP50：自实现全点插值 AP（VOC2010/COCO 风格），单 IoU 阈值 0.5、
  类内贪心匹配（预测按分数降序，一对一占用 GT）——与 pycocotools 的
  多 IoU 平均 mAP **不是同一口径**，报告时以「mask AP50（自实现口径）」
  表述，验收阈值（训练计划 T1：≥0.90）只对该口径负责；
- 粒数 MAE：逐盘 |预测粒数 − 真值粒数|，按真值粒数分桶（≤300 / >300），
  对应训练计划 T1 的 ≤3 / ≤8 粒门槛；
- 双面配对：匈牙利算法（scipy.optimize.linear_sum_assignment），代价 =
  1 − IoU，配对可行性 = IoU ≥ 阈值 或 质心距 ≤ 上限（翻面质心横移容差）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment


# ---------------------------------------------------------------------------
# 实例容器
# ---------------------------------------------------------------------------


@dataclass
class Instance:
    """单个实例（GT 或预测）：类别 + 局部掩码 + 全图偏移 + 分数 + 附加元数据。"""

    category_id: int
    score: float
    crop: np.ndarray  # bool (h, w)，外接框局部
    offset: tuple[int, int]  # 全图坐标 (x0, y0)
    meta: dict = field(default_factory=dict)  # GT: bean_id/side/class_top/class_bottom

    @property
    def area(self) -> int:
        return int(self.crop.sum())

    def centroid(self) -> tuple[float, float]:
        """局部质心的全图坐标 (x, y)；空掩码返回 offset。"""
        ys, xs = np.nonzero(self.crop)
        if xs.size == 0:
            return (float(self.offset[0]), float(self.offset[1]))
        return (
            float(xs.mean()) + float(self.offset[0]),
            float(ys.mean()) + float(self.offset[1]),
        )


# ---------------------------------------------------------------------------
# COCO segmentation → Instance
# ---------------------------------------------------------------------------


def decode_segmentation(seg: object, w: int, h: int) -> tuple[np.ndarray, tuple[int, int]]:
    """COCO segmentation（多边形列表或未压缩 RLE dict）→ (bool crop, (x0,y0))。

    RLE 解码复用 :func:`beaneye.synth.rle_decode`（列主序，与
    :func:`beaneye.synth.rle_encode` 互逆）；多边形在外接框局部 fillPoly。
    """
    if isinstance(seg, dict):  # 未压缩 RLE
        from beaneye.synth import rle_decode  # 复用合成引擎解码（真实分支已装 cv2/numpy）

        mask = rle_decode(seg).astype(bool)
        if mask.shape != (h, w):
            raise ValueError(f"RLE size {mask.shape} != 图像 ({h}, {w})")
        return _crop_mask(mask)
    polys = seg or []
    pts_all: list[list[float]] = []
    for poly in polys:
        flat = [float(v) for v in poly]
        if len(flat) < 6:
            continue
        pts_all.extend((flat[i], flat[i + 1]) for i in range(0, len(flat), 2))
    if not pts_all:
        return np.zeros((0, 0), dtype=bool), (0, 0)
    arr = np.asarray(pts_all, dtype=np.float64)
    x0, y0 = arr.min(axis=0)
    x1, y1 = arr.max(axis=0)
    ix0, iy0 = max(0, int(np.floor(x0))), max(0, int(np.floor(y0)))
    ix1, iy1 = min(int(w) - 1, int(np.ceil(x1))), min(int(h) - 1, int(np.ceil(y1)))
    if ix1 < ix0 or iy1 < iy0:
        return np.zeros((0, 0), dtype=bool), (0, 0)
    crop = np.zeros((iy1 - iy0 + 1, ix1 - ix0 + 1), dtype=np.uint8)
    for poly in polys:
        flat = [float(v) for v in poly]
        if len(flat) < 6:
            continue
        pts = np.asarray(flat, dtype=np.float32).reshape(-1, 2)
        pts[:, 0] -= ix0
        pts[:, 1] -= iy0
        cv2.fillPoly(crop, [np.round(pts).astype(np.int32)], 255)
    return crop.astype(bool), (ix0, iy0)


def _crop_mask(mask: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return np.zeros((0, 0), dtype=bool), (0, 0)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return mask[y0 : y1 + 1, x0 : x1 + 1].copy(), (x0, y0)


def ann_to_instance(ann: dict, width: int, height: int) -> Instance:
    """COCO 标注 → :class:`Instance`（meta 带 bean_id/side/class_* 扩展字段）。"""
    crop, offset = decode_segmentation(ann.get("segmentation"), width, height)
    return Instance(
        category_id=int(ann["category_id"]),
        score=1.0,
        crop=crop,
        offset=offset,
        meta={
            k: ann.get(k)
            for k in ("bean_id", "side", "class_top", "class_bottom")
            if k in ann
        },
    )


def detections_to_instances(class_id, score, masks) -> list[Instance]:
    """框架预测（class_id/score/掩码数组 N×H×W）→ Instance 列表（空掩码丢弃）。"""
    out: list[Instance] = []
    for i in range(len(score)):
        m = np.asarray(masks[i], dtype=bool)
        if m.size == 0 or not m.any():
            continue
        crop, offset = _crop_mask(m)
        out.append(
            Instance(
                category_id=int(class_id[i]),
                score=float(score[i]),
                crop=crop,
                offset=offset,
            )
        )
    return out


# ---------------------------------------------------------------------------
# IoU 与匹配
# ---------------------------------------------------------------------------


def _aligned(a: Instance, b: Instance) -> tuple[np.ndarray, np.ndarray]:
    """两实例掩码对齐到公共外接框窗口（并集范围）。"""
    ax0, ay0 = a.offset
    bx0, by0 = b.offset
    ax1, ay1 = ax0 + a.crop.shape[1], ay0 + a.crop.shape[0]
    bx1, by1 = bx0 + b.crop.shape[1], by0 + b.crop.shape[0]
    ux0, uy0 = min(ax0, bx0), min(ay0, by0)
    ux1, uy1 = max(ax1, bx1), max(ay1, by1)
    ua = np.zeros((uy1 - uy0, ux1 - ux0), dtype=bool)
    ub = np.zeros_like(ua)
    ua[ay0 - uy0 : ay1 - uy0, ax0 - ux0 : ax1 - ux0] = a.crop
    ub[by0 - uy0 : by1 - uy0, bx0 - ux0 : bx1 - ux0] = b.crop
    return ua, ub


def iou_matrix(a: list[Instance], b: list[Instance]) -> np.ndarray:
    """成组 IoU 矩阵（局部窗口对齐，避免整幅 2048² × N² 全图开销）。"""
    m = np.zeros((len(a), len(b)), dtype=np.float32)
    for i, ia in enumerate(a):
        for j, ib in enumerate(b):
            if ia.crop.size == 0 or ib.crop.size == 0:
                continue
            ua, ub = _aligned(ia, ib)
            inter = float(np.logical_and(ua, ub).sum())
            union = float(ia.area + ib.area - inter)
            m[i, j] = inter / union if union > 0 else 0.0
    return m


def greedy_match(
    gts: list[Instance],
    preds: list[Instance],
    iou_thr: float = 0.5,
    *,
    require_same_class: bool = False,
) -> list[int]:
    """贪心匹配： preds 须已按分数降序；返回每 pred 的 GT 下标（未匹配 = -1）。

    ``require_same_class=True`` 时跨类别对（category_id 不同）一律不可匹配——
    实测跨类同掩码 IoU=1.0 若不隔离会被计成 TP，虚高总体 P/R/F1（复核项）；
    AP 口径（:func:`evaluate_ap50`）本就类内分桶，不受此开关影响。
    """
    ious = iou_matrix(gts, preds)
    if require_same_class:
        for j, g in enumerate(gts):
            for k, p in enumerate(preds):
                if g.category_id != p.category_id:
                    ious[j, k] = -1.0
    matched_gt: set[int] = set()
    out: list[int] = []
    for k in range(len(preds)):
        best_j, best_iou = -1, iou_thr
        for j in range(len(gts)):
            if j in matched_gt:
                continue
            if ious[j, k] >= best_iou:
                best_j, best_iou = j, float(ious[j, k])
        out.append(best_j)
        if best_j >= 0:
            matched_gt.add(best_j)
    return out


# ---------------------------------------------------------------------------
# AP50 / F1（自实现口径，见模块 docstring）
# ---------------------------------------------------------------------------


def ap_from_scores(scores: list[float], tps: list[int], n_gt: int) -> float:
    """全点插值 AP（单阈值；scores/tps 已配对，内部重新按分数降序）。"""
    if n_gt <= 0:
        return 0.0
    order = np.argsort(-np.asarray(scores, dtype=np.float64), kind="stable")
    tp = np.asarray(tps, dtype=np.float64)[order]
    ctp = np.cumsum(tp)
    cfp = np.cumsum(1.0 - tp)
    recall = ctp / float(n_gt)
    precision = ctp / np.maximum(ctp + cfp, 1e-12)
    mrec = np.concatenate([[0.0], recall, [1.0]])
    mpre = np.concatenate([[0.0], precision, [0.0]])
    for i in range(mpre.size - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.flatnonzero(mrec[1:] != mrec[:-1])
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def evaluate_ap50(
    gts_by_img: list[list[Instance]],
    preds_by_img: list[list[Instance]],
    *,
    iou_thr: float = 0.5,
    class_id_offset: int = 0,
) -> dict:
    """全类掩码 AP50（自实现口径）。

    ``class_id_offset``：预测 class_id + offset = COCO category_id（训练框架
    可能把 1..13 的类别 id 压成 0..12，见 eval 脚本同名参数说明）。
    返回 {per_class: {cat_id: {ap, n_gt, n_pred}}, macro_ap50, ...}。
    """
    per_img: list[dict[int, dict[str, list]]] = []
    all_cats: set[int] = set()
    for gts, preds in zip(gts_by_img, preds_by_img):
        for g in gts:
            all_cats.add(g.category_id)
        for p in preds:
            all_cats.add(p.category_id + class_id_offset)
        buckets: dict[int, dict[str, list]] = {}
        for g in gts:
            buckets.setdefault(g.category_id, {"gt": [], "pred": []})["gt"].append(g)
        for p in preds:
            cid = p.category_id + class_id_offset
            buckets.setdefault(cid, {"gt": [], "pred": []})["pred"].append(p)
        per_img.append(buckets)

    n_gt_by_cat: dict[int, int] = {c: 0 for c in sorted(all_cats)}
    scores_by_cat: dict[int, list[float]] = {c: [] for c in sorted(all_cats)}
    tps_by_cat: dict[int, list[int]] = {c: [] for c in sorted(all_cats)}
    for buckets in per_img:
        for cid, node in buckets.items():
            n_gt_by_cat[cid] += len(node["gt"])
            if not node["pred"]:
                continue
            order = sorted(
                range(len(node["pred"])), key=lambda k: -node["pred"][k].score
            )
            preds_sorted = [node["pred"][k] for k in order]
            matches = greedy_match(node["gt"], preds_sorted, iou_thr)
            for k, j in enumerate(matches):
                scores_by_cat[cid].append(preds_sorted[k].score)
                tps_by_cat[cid].append(1 if j >= 0 else 0)

    per_class: dict[str, dict] = {}
    aps: list[float] = []
    for cid in sorted(all_cats):
        ap = ap_from_scores(scores_by_cat[cid], tps_by_cat[cid], n_gt_by_cat[cid])
        per_class[str(cid)] = {
            "ap50": round(ap, 6),
            "n_gt": n_gt_by_cat[cid],
            "n_pred": len(scores_by_cat[cid]),
        }
        if n_gt_by_cat[cid] > 0:
            aps.append(ap)
    return {
        "ap50_iou_thr": iou_thr,
        "class_id_offset": class_id_offset,
        "per_class": per_class,
        "macro_ap50": round(sum(aps) / len(aps), 6) if aps else None,
        "n_classes_with_gt": len(aps),
    }


def prf_from_matches(
    gts: list[Instance],
    preds: list[Instance],
    *,
    iou_thr: float = 0.5,
    class_id_offset: int = 0,
) -> dict:
    """实例级 P/R/F1（含 per-class 表；preds 不需预排序，内部按分数降序贪心）。

    总体 tp/fp/fn 用**类别一致**的贪心匹配（跨类重叠不算 TP，见
    :func:`greedy_match` 的 require_same_class）；per-class 表本就类内匹配。
    """
    order = sorted(range(len(preds)), key=lambda k: -preds[k].score)
    preds_sorted = [preds[k] for k in order]
    matches = greedy_match(gts, preds_sorted, iou_thr, require_same_class=True)
    n_gt = len(gts)
    tp = sum(1 for j in matches if j >= 0)
    fp = len(preds_sorted) - tp
    fn = n_gt - tp

    cats: set[int] = {g.category_id for g in gts} | {
        p.category_id + class_id_offset for p in preds
    }
    per_class: dict[str, dict] = {}
    f1s: list[float] = []
    for cid in sorted(cats):
        g_c = [g for g in gts if g.category_id == cid]
        p_c = [p for k, p in enumerate(preds_sorted)
               if p.category_id + class_id_offset == cid]
        m_c = greedy_match(g_c, p_c, iou_thr)
        tp_c = sum(1 for j in m_c if j >= 0)
        fp_c = len(p_c) - tp_c
        fn_c = len(g_c) - tp_c
        precision = tp_c / (tp_c + fp_c) if (tp_c + fp_c) else None
        recall = tp_c / (tp_c + fn_c) if (tp_c + fn_c) else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and (precision + recall) > 0
            else 0.0
        )
        per_class[str(cid)] = {
            "n_gt": len(g_c), "n_pred": len(p_c), "tp": tp_c,
            "precision": None if precision is None else round(precision, 6),
            "recall": None if recall is None else round(recall, 6),
            "f1": round(f1, 6),
        }
        if g_c:
            f1s.append(f1)
    macro = round(sum(f1s) / len(f1s), 6) if f1s else None
    p_all = tp / (tp + fp) if (tp + fp) else None
    r_all = tp / (tp + fn) if (tp + fn) else None
    f1_all = (
        2 * p_all * r_all / (p_all + r_all)
        if p_all is not None and r_all is not None and (p_all + r_all) > 0
        else 0.0
    )
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": None if p_all is None else round(p_all, 6),
        "recall": None if r_all is None else round(r_all, 6),
        "f1": round(f1_all, 6),
        "macro_f1": macro,
        "per_class": per_class,
    }


# ---------------------------------------------------------------------------
# 粒数 MAE（训练计划 T1：≤300 粒盘 ≤3、>300 粒盘 ≤8）
# ---------------------------------------------------------------------------


def counting_mae(
    gts_by_img: list[list[Instance]],
    preds_by_img: list[list[Instance]],
    bucket_split: int = 300,
) -> dict:
    """逐盘粒数误差分桶统计（桶按**真值**粒数划分）。

    另产出**逐盘相对误差**（|误差| / 该盘真值粒数，再对盘取均值/最大）——
    真实档 ≤10% 门槛的量纲是「每盘相对误差」，不能拿总体 MAE 除以标注总数
    （复核项实测那样会被低估 N_images 倍、门槛恒过）。
    """
    buckets = {"le": {"n": 0, "sum_err": 0, "max_err": 0},
               "gt": {"n": 0, "sum_err": 0, "max_err": 0}}
    rel_errs: list[float] = []
    for gts, preds in zip(gts_by_img, preds_by_img):
        key = "le" if len(gts) <= bucket_split else "gt"
        err = abs(len(preds) - len(gts))
        node = buckets[key]
        node["n"] += 1
        node["sum_err"] += err
        node["max_err"] = max(node["max_err"], err)
        if gts:
            rel_errs.append(err / len(gts))
    out = {"bucket_split": bucket_split}
    for key, node in buckets.items():
        out[key] = {
            "n_images": node["n"],
            "mae": round(node["sum_err"] / node["n"], 4) if node["n"] else None,
            "max_abs_err": node["max_err"],
        }
    n_all = sum(b["n"] for b in buckets.values())
    out["mae_overall"] = round(
        (buckets["le"]["sum_err"] + buckets["gt"]["sum_err"]) / max(n_all, 1), 4
    )
    out["rel_err_mean"] = round(sum(rel_errs) / len(rel_errs), 6) if rel_errs else None
    out["rel_err_max"] = round(max(rel_errs), 6) if rel_errs else None
    return out


# ---------------------------------------------------------------------------
# 双面配对（T2 配置 C；匈牙利 + 门限）
# ---------------------------------------------------------------------------


def pair_top_bottom(
    top: list[Instance],
    bottom: list[Instance],
    *,
    iou_thr: float = 0.3,
    max_dist_px: float = 80.0,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """top/bottom 预测实例匈牙利配对。

    可行性 = IoU ≥ ``iou_thr`` 或 质心距 ≤ ``max_dist_px``（翻面质心横移容差，
    与 beaneye.pairing 的 12mm 门限同思想，此处单位为像素）；返回
    (配对对 [(i, j)], 未配对 top 下标, 未配对 bottom 下标)。
    """
    if not top or not bottom:
        return [], list(range(len(top))), list(range(len(bottom)))
    ious = iou_matrix(top, bottom)
    cost = np.full((len(top), len(bottom)), 1e6, dtype=np.float64)
    for i in range(len(top)):
        ci = np.asarray(top[i].centroid())
        for j in range(len(bottom)):
            dist = float(np.hypot(*(ci - np.asarray(bottom[j].centroid()))))
            if ious[i, j] >= iou_thr or dist <= max_dist_px:
                cost[i, j] = 1.0 - float(ious[i, j])
    rows, cols = linear_sum_assignment(cost)
    paired: list[tuple[int, int]] = []
    used_t: set[int] = set()
    used_b: set[int] = set()
    for i, j in zip(rows, cols):
        if cost[i, j] < 1e5:
            paired.append((int(i), int(j)))
            used_t.add(int(i))
            used_b.add(int(j))
    unpaired_t = [i for i in range(len(top)) if i not in used_t]
    unpaired_b = [j for j in range(len(bottom)) if j not in used_b]
    return paired, unpaired_t, unpaired_b
