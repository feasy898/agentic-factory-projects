"""M5 分类 eval（W5）：beaneye/classify RulesV0（规则表驱动经典分类器）。

运行（仓库根）::

    pytest tests/test_classify.py -q

任务书自验收线：合成盘 12 类各 ≥30 粒（另加正常类盘）上逐粒分类——
总体准确率 ≥0.75、正常类召回 ≥0.95、混淆矩阵落盘 ``out/eval/classify_report.json``，
全程 exit 0。

口径（真值来自合成器已知标签，W12b 程序化合成）：

1. **评测盘**：每个种子基础生成 13 张盘——12 张缺陷盘（每张 34 粒、
   ``defect_rate=1.0``、类权重单键，保证每缺陷类 ≥30 粒配额）+ 1 张正常盘
   （40 粒、``defect_rate=0.0``）。两个种子基础共 26 盘（每缺陷类 68 粒、
   正常 80 粒）。渲染参数用生产缺省（2048 画布 / ±10% 尺寸抖动 / 光照
   扰动 / 阴影 / 暗角 / 颗粒），布局含少量接触/重叠豆。
2. **生产同路裁剪**：compose → ``calibrate_pair`` 真检四角 ArUco →
   ``warp_to_tray`` 正射网格 → 真值多边形构造 BeanMask(oracle) →
   M13 管线同款 ``extract_mask_crop_rgba`` 裁 RGBA——分类器吃到的 crop 与
   生产管线逐字节同构（含光照/阴影/叠豆像素）。
3. **规则阈值开发纪律**：configs/rules_v0.yaml 的阈值在 4 个开发种子基础
   （604100/711200/915300/412650，各 13 盘）上标定；本文件的两个验收种子
   基础不参与标定。
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from beaneye.app.components import build_components
from beaneye.app.pipeline import extract_mask_crop_rgba
from beaneye.calibration import calibrate_pair, load_tray_config, warp_to_tray
from beaneye.classify import (
    DEFAULT_RULES_CONFIG_PATH,
    RULES_OPS,
    RulesConfigError,
    RulesV0,
    build_default,
    load_rules_config,
)
from beaneye.classify.features import FEATURE_NAMES
from beaneye.schemas import BeanMask
from beaneye.synth import ComposeConfig, compose_tray
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
DEFECT_CLASSES = [k for k in TAX.keys() if k != "normal"]

# 验收种子基础（不参与规则阈值标定；每个基础 13 盘：12 缺陷类盘 + 1 正常盘）
ACCEPT_SEEDS = (267950, 531840)
DEFECT_BEANS = 34
NORMAL_BEANS = 40
REPORT_PATH = Path(__file__).resolve().parents[1] / "out" / "eval" / "classify_report.json"

ACC_MIN = 0.75
NORMAL_RECALL_MIN = 0.95
LATENCY_MS_MAX = 50.0


# ---------------------------------------------------------------------------
# 共享夹具：26 张验收盘逐粒分类（module 级跑一次）
# ---------------------------------------------------------------------------


def _tray_cfg(cls: str) -> ComposeConfig:
    n = NORMAL_BEANS if cls == "normal" else DEFECT_BEANS
    return ComposeConfig(
        version=1,
        width_px=2048,
        height_px=2048,
        margin_mm=20.0,
        n_beans_min=n,
        n_beans_max=n,
        defect_rate=0.0 if cls == "normal" else 1.0,
        class_weights={} if cls == "normal" else {cls: 1.0},
        contact_min=2,
        contact_max=4,
        overlap_depth=0.82,
        free_factor=1.06,
        scale_jitter=0.10,
        angle_jitter=180.0,
        pair_jitter_mm=0.6,
        mirror_bottom=True,
        per_class=24,
        library_seed=20260929,
    )


def _oracle_mask(bean, idx: int) -> BeanMask:
    """真值多边形 → 契约 BeanMask（oracle，conf=1.0；与 W12 冒烟同口径）。"""
    poly = [[round(float(x), 3) for x in p] for p in bean.poly_mm_top]
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return BeanMask(
        mask_id=f"top_{idx:04d}",
        side="top",
        polygon=poly,
        bbox_mm=(min(xs), min(ys), max(xs), max(ys)),
        area_mm2=bean.area_mm2,
        centroid_mm=bean.centroid_mm,
        source="oracle",
        conf=1.0,
    )


@pytest.fixture(scope="module")
def eval_run() -> dict:
    """逐盘合成 → 标定 → 裁剪 → RulesV0 分类，汇总记录 + 落盘评测报告。"""
    model = build_default()
    tray_cfg = load_tray_config()
    mm_per_px = tray_cfg.mm_per_px

    records: list[dict] = []
    lat_ms: list[float] = []
    for seed in ACCEPT_SEEDS:
        for i, cls in enumerate(DEFECT_CLASSES + ["normal"]):
            tray = compose_tray(seed=seed + i, config=_tray_cfg(cls))
            calib = calibrate_pair(tray.top_bgr, tray.bottom_bgr)
            warped = warp_to_tray(tray.top_bgr, np.asarray(calib.H_top), None)
            for j, bean in enumerate(tray.beans):
                mask = _oracle_mask(bean, j)
                crop = extract_mask_crop_rgba(warped, mask, mm_per_px)
                t0 = time.perf_counter()
                defect, conf, rank = model.classify(crop, mask)
                lat_ms.append((time.perf_counter() - t0) * 1000.0)
                records.append(
                    {
                        "seed": seed,
                        "tray_cls": cls,
                        "bean_id": mask.mask_id,
                        "truth": bean.cls,
                        "pred": defect,
                        "conf": float(conf),
                        "rank": int(rank),
                    }
                )

    labels = list(TAX.keys())
    confusion = Counter((r["truth"], r["pred"]) for r in records)
    matrix = [[confusion.get((t, p), 0) for p in labels] for t in labels]
    n = len(records)
    correct = sum(confusion.get((c, c), 0) for c in labels)
    acc = correct / n
    normal_n = sum(confusion.get(("normal", p), 0) for p in labels)
    normal_recall = confusion.get(("normal", "normal"), 0) / normal_n if normal_n else 0.0

    per_class: dict[str, dict] = {}
    for c in labels:
        support = sum(confusion.get((c, p), 0) for p in labels)
        pred_n = sum(confusion.get((t, c), 0) for t in labels)
        per_class[c] = {
            "support": support,
            "correct": confusion.get((c, c), 0),
            "recall": (confusion.get((c, c), 0) / support) if support else 0.0,
            "precision": (confusion.get((c, c), 0) / pred_n) if pred_n else 0.0,
        }

    report = {
        "report_version": 1,
        "model": model.version,
        "seeds": list(ACCEPT_SEEDS),
        "n_trays": len(ACCEPT_SEEDS) * (len(DEFECT_CLASSES) + 1),
        "n_beans": n,
        "bean_counts": {c: per_class[c]["support"] for c in labels},
        "accuracy": acc,
        "normal_recall": normal_recall,
        "mean_ms_per_crop": float(np.mean(lat_ms)),
        "p95_ms_per_crop": float(np.percentile(lat_ms, 95)),
        "per_class": per_class,
        "confusion_matrix": {"labels": labels, "rows": matrix},
        "rules_config": str(DEFAULT_RULES_CONFIG_PATH),
        "rules_config_sha256": hashlib.sha256(
            DEFAULT_RULES_CONFIG_PATH.read_bytes()
        ).hexdigest(),
        "taxonomy_severity_order": list(TAX.severity_order),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "report": report,
        "records": records,
        "labels": labels,
        "confusion": confusion,
        "model": model,
    }


# ---------------------------------------------------------------------------
# 验收线（任务书）
# ---------------------------------------------------------------------------


def test_class_counts_12_defect_classes_ge30(eval_run: dict) -> None:
    """合成盘 12 缺陷类各 ≥30 粒，正常类也有样本。"""
    counts = eval_run["report"]["bean_counts"]
    for cls in DEFECT_CLASSES:
        assert counts[cls] >= 30, f"缺陷类 {cls} 只有 {counts[cls]} 粒（要求 ≥30）"
    assert counts["normal"] >= 30, f"正常类只有 {counts['normal']} 粒"
    assert sum(counts.values()) == eval_run["report"]["n_beans"]


def test_overall_accuracy_ge_075(eval_run: dict) -> None:
    assert eval_run["report"]["accuracy"] >= ACC_MIN, (
        f"总体准确率 {eval_run['report']['accuracy']:.4f} < {ACC_MIN}"
    )


def test_normal_recall_ge_095(eval_run: dict) -> None:
    assert eval_run["report"]["normal_recall"] >= NORMAL_RECALL_MIN, (
        f"正常类召回 {eval_run['report']['normal_recall']:.4f} < {NORMAL_RECALL_MIN}"
    )


def test_confusion_matrix_written(eval_run: dict) -> None:
    """混淆矩阵落盘 out/eval/classify_report.json，且与记录一致。"""
    assert REPORT_PATH.is_file(), f"评测报告未落盘: {REPORT_PATH}"
    rep = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    labels = rep["confusion_matrix"]["labels"]
    assert labels == list(TAX.keys())
    matrix = rep["confusion_matrix"]["rows"]
    assert len(matrix) == len(labels) and all(len(r) == len(labels) for r in matrix)
    # 对角线之和 == 全部正确数；逐类 correct 与矩阵一致
    assert sum(matrix[i][i] for i in range(len(labels))) == sum(
        rep["per_class"][c]["correct"] for c in labels
    )
    for i, c in enumerate(labels):
        assert matrix[i][i] == rep["per_class"][c]["correct"]
    # 报告口径与夹具实测一致（防"报告另算"）
    assert rep["accuracy"] == eval_run["report"]["accuracy"]
    assert rep["normal_recall"] == eval_run["report"]["normal_recall"]
    assert rep["rules_config_sha256"] == hashlib.sha256(
        DEFAULT_RULES_CONFIG_PATH.read_bytes()
    ).hexdigest()


# ---------------------------------------------------------------------------
# 契约与装配
# ---------------------------------------------------------------------------


def test_cls_output_contract(eval_run: dict) -> None:
    """逐粒输出满足冻结契约：合法类别、conf∈[0,1]、rank 与 taxonomy 一致。"""
    for r in eval_run["records"]:
        assert TAX.is_valid_key(r["pred"]), f"非法类别 {r['pred']}"
        assert 0.0 <= r["conf"] <= 1.0, f"conf 越界 {r['conf']}"
        assert r["rank"] == TAX.severity_rank(r["pred"]), (
            f"{r['pred']} rank {r['rank']} != taxonomy {TAX.severity_rank(r['pred'])}"
        )


def test_build_default_protocol_and_app_wiring() -> None:
    """build_default 工厂满足 ClsModel 形状；M13 装配器零改动自动接线。"""
    model = build_default()
    assert isinstance(model, RulesV0)
    assert model.stage == "classify"
    assert callable(model.classify)
    components = build_components(allow_probe=True)
    assert not components.classify.degraded, (
        f"beaneye.classify 未被装配器接入: {components.classify.reason}"
    )
    assert components.classify.impl.version == "rules_v0:v1"


def test_rules_config_covers_all_defect_classes() -> None:
    """规则表覆盖全部 12 个缺陷类（数据驱动：代码无类别知识）。"""
    cfg = load_rules_config()
    assert cfg.version == 1
    covered = {r.defect for r in cfg.rules}
    assert set(DEFECT_CLASSES) <= covered, f"规则表未覆盖: {set(DEFECT_CLASSES) - covered}"
    assert all(r.when for r in cfg.rules)
    assert all(c.feat in FEATURE_NAMES for r in cfg.rules for c in r.when)
    assert all(c.op in RULES_OPS for r in cfg.rules for c in r.when)


def test_classify_deterministic(eval_run: dict) -> None:
    """同一输入重复分类结果一致（规则引擎无随机性）。"""
    model = eval_run["model"]
    tray = compose_tray(seed=999001, config=_tray_cfg("black"))
    calib = calibrate_pair(tray.top_bgr, tray.bottom_bgr)
    warped = warp_to_tray(tray.top_bgr, np.asarray(calib.H_top), None)
    mm_per_px = load_tray_config().mm_per_px
    mask = _oracle_mask(tray.beans[0], 0)
    crop = extract_mask_crop_rgba(warped, mask, mm_per_px)
    assert model.classify(crop, mask) == model.classify(crop, mask)


def test_degenerate_crop_returns_normal_not_raise() -> None:
    """退化输入（空 alpha/零面积）返回 normal 而非抛异常（不阻塞管线）。"""
    model = build_default()
    fake = type(
        "B",
        (),
        {
            "poly_mm_top": [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]],
            "area_mm2": 1.0,
            "centroid_mm": (0.5, 0.5),
        },
    )()
    mask = _oracle_mask(fake, 0)
    empty = np.zeros((8, 8, 4), dtype=np.uint8)
    assert model.classify(empty, mask) == ("normal", 0.0, 0)
    tiny = np.zeros((8, 8, 4), dtype=np.uint8)
    tiny[2:6, 2:6, :3] = 128
    tiny[2:6, 2:6, 3] = 255
    zero_area = mask.model_copy(update={"area_mm2": 0.0})
    assert model.classify(tiny, zero_area) == ("normal", 0.0, 0)


def test_per_crop_latency(eval_run: dict) -> None:
    """CPU 时延：平均 ≤50ms/crop（开发指令 M5 通过线）。"""
    assert eval_run["report"]["mean_ms_per_crop"] <= LATENCY_MS_MAX, (
        f"平均 {eval_run['report']['mean_ms_per_crop']:.2f}ms/crop > {LATENCY_MS_MAX}"
    )


# ---------------------------------------------------------------------------
# 规则表加载器校验（数据即契约：非法规则必须在加载期拒绝）
# ---------------------------------------------------------------------------


def _write_cfg(tmp_path: Path, raw: dict) -> Path:
    p = tmp_path / "rules_bad.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return p


def _good_raw() -> dict:
    return {
        "version": 1,
        "defaults": {"normal_conf": 0.6},
        "rules": [
            {
                "defect": "black",
                "conf": 0.9,
                "when": [{"feat": "lab_l_mean", "op": "lt", "value": 95.0}],
            }
        ],
    }


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda r: r.update({"version": 2}), "version"),
        (lambda r: r.update({"unknown_key": 1}), "未知顶层键"),
        (lambda r: r["rules"][0]["when"][0].update({"feat": "no_such_feat"}), "未知特征"),
        (lambda r: r["rules"][0]["when"][0].update({"op": "eq"}), "op"),
        (lambda r: r["rules"][0].update({"defect": "normal"}), "非 normal"),
        (lambda r: r["rules"][0].update({"defect": "no_such_class"}), "缺陷类"),
        (lambda r: r["rules"][0].update({"conf": 1.5}), "conf"),
        (lambda r: r.update({"rules": []}), "非空列表"),
        (lambda r: r["rules"][0].update({"when": []}), "非空条件"),
    ],
)
def test_rules_config_rejects_illegal(tmp_path: Path, mutate, fragment: str) -> None:
    raw = _good_raw()
    mutate(raw)
    p = _write_cfg(tmp_path, raw)
    with pytest.raises(RulesConfigError) as ei:
        load_rules_config(p)
    assert fragment in str(ei.value)
    assert str(p) in str(ei.value)  # 错误信息带文件路径
