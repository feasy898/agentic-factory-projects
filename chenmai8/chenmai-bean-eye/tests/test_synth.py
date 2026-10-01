"""M12 合成数据引擎 eval（W12a-lite + W12b）：beaneye/synth。

运行（仓库根）::

    pytest tests/test_synth.py -q

覆盖（任务书自验收线）：
1. 程序化素材：13 类 taxonomy 类画像齐全、每类 ≥20 固定变体、库级种子
   复现（逐 BeanSpec 字段相等）、渲染 sprite 真值轮廓与多边形一致；
2. 合成盘真值一致性：labels 多边形（JSON 往返后）栅格化 == RLE 解码
   **逐字节相等**（真值直出的可检验定义）；解析面积/等效直径/质心/外接框
   与标注恒等；sprite alpha 与 mm 网栅格 IoU 高重合；豆确实出现在画布上
   标注位置（含光照扰动后的颜色校验）；
3. 接触/重叠目标数：contact_target≥1 时逐对凸包相交复核与 manifest 一致、
   接触豆至少压住一个 partner；无接触目标盘 overlap_pairs==[]；
4. 种子复现（字节级）：同种子两次 compose 图像 array_equal、labels JSON
   字节相等、write_batch 四件产物字节相等；异种子图像必异；
5. 标准 YAML 输入格式：configs/synth.yaml 默认加载 + manifest.yaml 回读
   → 同 seed 字节级复现；非法配置（未知键/坏类权重/区间矛盾）明确报错；
6. M1 兼容：labels 逐粒字段可直接构造 BeanMask（oracle 契约校验全过）。

测试盘用小画布（1024）+ 少豆 + module 级共享，控制套件时长。
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from beaneye.schemas import BeanMask
from beaneye.synth import (
    CLASS_PROFILES,
    BeanSpec,
    ComposeConfig,
    SynthBeanError,
    SynthConfigError,
    compose_tray,
    config_to_dict,
    labels_to_json,
    load_compose_config,
    rasterize_poly_mm,
    rle_decode,
    sample_library,
    sample_spec,
    write_batch,
)
from beaneye.synth.beans import bean_polygon_mm, render_sprite
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
CLASSES = TAX.keys()

# ---------------------------------------------------------------------------
# 共享夹具：小盘配置（1024 画布 / 12-18 豆 / 接触 2-4 / 高缺陷率保证覆盖）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small_cfg() -> ComposeConfig:
    return ComposeConfig(
        version=1,
        width_px=1024,
        height_px=1024,
        margin_mm=20.0,
        n_beans_min=12,
        n_beans_max=18,
        defect_rate=0.45,
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


@pytest.fixture(scope="module")
def library() -> dict[str, list[BeanSpec]]:
    return sample_library(20260929, 20)


@pytest.fixture(scope="module")
def tray(small_cfg: ComposeConfig, library):
    return compose_tray(seed=2026, config=small_cfg, library=library)


@pytest.fixture(scope="module")
def labels(tray) -> dict:
    return labels_to_json(tray, with_rle=True)


# ---------------------------------------------------------------------------
# ① W12a-lite：程序化素材库
# ---------------------------------------------------------------------------


def test_profiles_cover_all_taxonomy_classes():
    assert set(CLASS_PROFILES) == set(CLASSES), "类画像必须与 taxonomy 13 类一一对应"


def test_library_per_class_at_least_20_variants_fixed_seed(library):
    for cls in CLASSES:
        variants = library[cls]
        assert len(variants) >= 20, f"{cls} 变体数 {len(variants)} < 20（W12a-lite 交付线）"
        vids = {v.variant_id for v in variants}
        assert len(vids) == len(variants), f"{cls} variant_id 重复"
        for v in variants:
            assert v.cls == cls
            assert v.length_mm > 0 and v.aspect >= 1.0


def test_library_seed_reproducible():
    lib1 = sample_library(777, 20)
    lib2 = sample_library(777, 20)
    for cls in CLASSES:
        for a, b in zip(lib1[cls], lib2[cls]):
            assert a == b, f"{cls} 变体不一致：同种子素材库必须逐字段复现"
    lib3 = sample_library(778, 20)
    assert lib3["normal"][0] != lib1["normal"][0], "异种子素材库应不同"


def test_library_per_class_below_20_rejected():
    with pytest.raises(SynthBeanError):
        sample_library(1, 19)


def test_sample_spec_deterministic(library):
    v = library["black"]
    s1 = sample_spec(v, np.random.default_rng([9, 9]), scale_jitter=0.1)
    s2 = sample_spec(v, np.random.default_rng([9, 9]), scale_jitter=0.1)
    assert s1 == s2
    s3 = sample_spec(v, np.random.default_rng([9, 10]), scale_jitter=0.1)
    assert s3 != s1


def test_all_classes_render_distinct_sprites(library):
    seen: dict[str, bytes] = {}
    for ci, cls in enumerate(CLASSES):
        spec = sample_spec(library[cls], np.random.default_rng([5, ci]))
        sp = render_sprite(spec, 6.0, np.random.default_rng([6, ci]))
        assert sp.alpha.shape == sp.bgr.shape[:2]
        assert sp.alpha.max() == 255 and sp.alpha.min() == 0
        assert (sp.alpha > 0).mean() > 0.05, f"{cls} sprite 轮廓异常"
        assert np.isfinite(sp.bgr).all()
        seen[cls] = sp.bgr.tobytes()
    assert len(set(seen.values())) == len(CLASSES), "13 类渲染应互不相同"


def test_broken_bean_polygon_is_chord_cut(library):
    """破碎豆轮廓：弦切口存在（一测平直段 + 面积小于同参数完整椭圆）。"""
    specs = [v for v in library["broken"] if v.cut is not None]
    assert specs, "broken 变体应带弦切"
    spec = specs[0]
    poly = bean_polygon_mm(spec)
    a = spec.length_mm / 2.0
    chord_x = a * (2.0 * spec.cut - 1.0)
    # 弦口锯齿顶点：x 邻近 chord_x（锯齿幅 ±0.10mm）的顶点 ≥4（弦上 6 点 + 弧端 2 点）
    on_chord = int((np.abs(poly[:, 0] - chord_x) <= 0.15).sum())
    assert on_chord >= 4, "弦切口锯齿顶点缺失"
    full = 3.141592653589793 * (spec.length_mm / 2.0) * (spec.width_mm / 2.0)
    area = 0.5 * abs(
        np.dot(poly[:, 0], np.roll(poly[:, 1], -1)) - np.dot(poly[:, 1], np.roll(poly[:, 0], -1))
    )
    assert area < full, "弓形段面积必须小于完整椭圆"


# ---------------------------------------------------------------------------
# ② 合成盘真值一致性（真值直出）
# ---------------------------------------------------------------------------


def _poly_rounded(entry: dict, key: str) -> np.ndarray:
    return np.asarray(entry[key], dtype=np.float64)


def test_truth_rle_equals_polygon_rasterization_byte_exact(tray, labels):
    """核心交付线：RLE 解码掩码 == 按标注多边形自栅格化（逐字节）。"""
    grid = tray.rle_grid_px
    buf = np.zeros((grid, grid), dtype=np.uint8)
    n_checked = 0
    for entry in labels["beans"]:
        for poly_key, rle_key in (("poly_mm_top", "rle_top"), ("poly_mm_bottom", "rle_bottom")):
            assert rle_key in entry, "with_rle=True 时逐粒双面 RLE 必须在位"
            poly = _poly_rounded(entry, poly_key)
            expect = rasterize_poly_mm(poly, grid_px=grid, tray_mm=tray.tray_mm, out=buf)
            got = rle_decode(entry[rle_key])
            assert np.array_equal(expect, got), (
                f"{entry['bean_id']}.{rle_key}: RLE 与多边形栅格化不一致"
            )
            n_checked += 1
    assert n_checked == 2 * len(labels["beans"]) > 0


def test_truth_geometry_matches_synthesis_params(tray, labels):
    """面积/等效直径/质心/外接框与标注多边形恒等（取整后解析重算）。"""
    for entry in labels["beans"]:
        poly = _poly_rounded(entry, "poly_mm_top")
        x, y = poly[:, 0], poly[:, 1]
        area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
        assert abs(area - entry["area_mm2"]) <= 1e-2, entry["bean_id"]
        eq = 2.0 * (area / np.pi) ** 0.5
        assert abs(eq - entry["eq_diameter_mm"]) <= 1e-2
        x0, y0 = poly.min(axis=0)
        x1, y1 = poly.max(axis=0)
        assert np.allclose([x0, y0, x1, y1], entry["bbox_mm"], atol=1e-2)
        m = cv2.moments(poly.astype(np.float32))
        assert abs(m["m10"] / m["m00"] - entry["centroid_mm"][0]) <= 1e-2
        assert abs(m["m01"] / m["m00"] - entry["centroid_mm"][1]) <= 1e-2


def test_truth_masks_consistent_across_representations(tray, labels):
    """sprite alpha ↔ mm 网栅格 ↔ 画布位置三口径一致。"""
    ppm_canvas = tray.px_per_mm
    grid = tray.rle_grid_px
    s = grid / tray.tray_mm
    for entry, bean in zip(labels["beans"], tray.beans):
        # (a) sprite alpha（真值轮廓原像）vs 同多边形 mm 网栅格：尺度重采样后高重合
        sp = render_sprite(bean.spec_top, ppm_canvas, np.random.default_rng([tray.seed, 7, 0, 0]))
        # 仅核对几何（用同一 spec 重渲染的 alpha；渲染 rng 不同只影响颜色不影响轮廓）
        poly_loc = sp.poly_mm
        m2 = cv2.moments(poly_loc.astype(np.float32))
        # sprite 系 → mm 系（平移到质心再搬到标注质心）
        local = poly_loc - np.asarray([m2["m10"] / m2["m00"], m2["m01"] / m2["m00"]])
        relocated = local + np.asarray(entry["centroid_mm"])
        raster = rasterize_poly_mm(
            np.round(relocated, 3), grid_px=grid, tray_mm=tray.tray_mm
        )
        truth = rle_decode(entry["rle_top"]) > 0
        inter = int(((raster > 0) & truth).sum())
        union = int(((raster > 0) | truth).sum())
        iou = inter / union
        assert iou >= 0.80, f"{entry['bean_id']} sprite↔mm 网栅格 IoU={iou:.3f} 过低"
        # (b) 画布上标注位置确有该豆（bbox 内像素与背景色差显著）
        x0, y0, x1, y1 = entry["bbox_mm"]
        cxx0 = int(tray.origin_px[0] + x0 * ppm_canvas) - 2
        cyy0 = int(tray.origin_px[1] + y0 * ppm_canvas) - 2
        cxx1 = int(tray.origin_px[0] + x1 * ppm_canvas) + 3
        cyy1 = int(tray.origin_px[1] + y1 * ppm_canvas) + 3
        patch = tray.top_bgr[
            max(0, cyy0) : min(1024, cyy1), max(0, cxx0) : min(1024, cxx1)
        ]
        assert patch.size > 0
        # 豆绿色与亚克力灰底（configs/synth.yaml background_bgr）有明显色差
        bg_g, bg_r = 203.0, 208.0  # BGR 中 G/R 分量
        med = np.median(patch.reshape(-1, 3), axis=0)
        assert abs(float(med[1]) - bg_g) > 8.0 or abs(
            float(med[2]) - bg_r
        ) > 8.0, f"{entry['bean_id']} 画布位置未见豆像素"


def test_class_truth_within_taxonomy(labels):
    for entry in labels["beans"]:
        assert TAX.is_valid_key(entry["class_top"])
        assert entry["class_top"] == entry["class_bottom"], "M12 成对语义：上下同类"
    cls_set = {e["class_top"] for e in labels["beans"]}
    assert "normal" in cls_set and cls_set - {"normal"}, "夹具盘应同时含好豆与缺陷豆"


# ---------------------------------------------------------------------------
# ③ 接触/重叠目标数
# ---------------------------------------------------------------------------


def _hull(poly: np.ndarray) -> np.ndarray:
    return cv2.convexHull(np.round(poly, 3).astype(np.float32))


def test_overlap_pairs_verified_by_hull_intersection(tray, labels):
    """manifest 重叠对与逐对凸包相交复核完全一致；接触豆必有 partner。"""
    n = len(tray.beans)
    hulls = [_hull(np.asarray(e["poly_mm_top"])) for e in labels["beans"]]
    expect = []
    for i in range(n):
        for j in range(i + 1, n):
            area_ij, _ = cv2.intersectConvexConvex(hulls[i], hulls[j])
            if float(area_ij) > 0.01:
                expect.append([i, j])
    assert [list(p) for p in tray.overlap_pairs] == expect, "重叠对须与凸包相交复核一致"
    # 接触豆必有 ≥1 个重叠 partner；自由豆两两不相交（free_factor 保证），
    # 故任何重叠对至少含 1 粒接触豆（自由豆只能被后放的接触豆压住）
    for i, bean in enumerate(tray.beans):
        partners = {k for pair in tray.overlap_pairs for k in pair if i in pair and k != i}
        if bean.contact_bean:
            assert partners, f"{bean.bean_id} 为接触豆却无重叠 partner"
        else:
            assert all(tray.beans[k].contact_bean for k in partners), (
                f"{bean.bean_id} 的重叠 partner 里没有接触豆（自由豆互叠）"
            )
    # overlap_with 双向对称
    for i, j in tray.overlap_pairs:
        assert j in tray.beans[i].overlap_with and i in tray.beans[j].overlap_with


def test_contact_target_achieved(tray):
    assert tray.contact_target >= 2
    assert tray.n_contact_placed >= 1, "接触/重叠目标应至少放下 1 粒"
    assert (
        sum(1 for b in tray.beans if b.contact_bean) == tray.n_contact_placed
    )


def test_sparse_tray_has_zero_overlap(library):
    cfg = ComposeConfig(
        version=1,
        width_px=1024,
        height_px=1024,
        margin_mm=20.0,
        n_beans_min=10,
        n_beans_max=10,
        defect_rate=0.0,
        class_weights={},
        contact_min=0,
        contact_max=0,
        free_factor=1.3,
        per_class=20,
        library_seed=20260929,
    )
    t = compose_tray(seed=31, config=cfg, library=library)
    assert t.overlap_pairs == []
    assert all(not b.contact_bean for b in t.beans)


# ---------------------------------------------------------------------------
# ④ 种子复现（字节级）
# ---------------------------------------------------------------------------


def test_seed_reproducibility_images_and_labels(library, small_cfg):
    t1 = compose_tray(seed=20260929, config=small_cfg, library=library)
    t2 = compose_tray(seed=20260929, config=small_cfg, library=library)
    assert np.array_equal(t1.top_bgr, t2.top_bgr), "top 图必须逐像素一致"
    assert np.array_equal(t1.bottom_bgr, t2.bottom_bgr), "bottom 图必须逐像素一致"
    l1 = json.dumps(labels_to_json(t1), ensure_ascii=False, sort_keys=True)
    l2 = json.dumps(labels_to_json(t2), ensure_ascii=False, sort_keys=True)
    assert l1 == l2, "labels JSON 必须字节级一致"
    t3 = compose_tray(seed=20260930, config=small_cfg, library=library)
    assert not np.array_equal(t1.top_bgr, t3.top_bgr), "异种子图像应不同"


def test_write_batch_byte_reproducible(tray, tmp_path):
    p1 = write_batch(tray, tmp_path / "a", index=1, with_rle=False)
    p2 = write_batch(tray, tmp_path / "b", index=1, with_rle=False)
    for key in ("top", "bottom", "labels", "manifest"):
        assert p1[key].read_bytes() == p2[key].read_bytes(), f"{key} 字节级不一致"


# ---------------------------------------------------------------------------
# ⑤ 标准 YAML 输入格式：默认配置 + manifest 回读复现 + 严格校验
# ---------------------------------------------------------------------------


def test_default_config_loads_and_validates():
    cfg = load_compose_config()  # 仓库默认 configs/synth.yaml
    d = config_to_dict(cfg)
    assert d["version"] == 1
    assert set(d) == {"version", "canvas", "layout", "render", "library"}
    assert 0.0 <= d["layout"]["defect_rate"] <= 1.0
    assert d["library"]["per_class"] >= 20


def test_manifest_yaml_roundtrip_reproduces_batch(tray, tmp_path):
    """manifest.yaml 回读 → 同 seed 重新合成 → 四件产物字节级一致。"""
    paths = write_batch(tray, tmp_path, index=7, with_rle=False)
    manifest = yaml.safe_load(paths["manifest"].read_text(encoding="utf-8"))
    assert manifest["seed"] == tray.seed
    cfg_path = tmp_path / "echo_synth.yaml"
    cfg_path.write_text(
        yaml.safe_dump(manifest["config"], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    cfg2 = load_compose_config(cfg_path)
    assert config_to_dict(cfg2) == tray.config_echo
    t2 = compose_tray(seed=manifest["seed"], config=cfg2)
    assert np.array_equal(t2.top_bgr, tray.top_bgr)
    assert np.array_equal(t2.bottom_bgr, tray.bottom_bgr)
    p2 = write_batch(t2, tmp_path / "re", index=7, with_rle=False)
    for key in ("top", "bottom", "labels", "manifest"):
        assert p2[key].read_bytes() == paths[key].read_bytes()


def _write_cfg(tmp_path: Path, patch: dict) -> Path:
    d = config_to_dict(load_compose_config())
    for k, v in patch.items():
        d[k] = v
    p = tmp_path / "bad_synth.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def test_config_rejects_unknown_key(tmp_path):
    p = _write_cfg(tmp_path, {"unknown_section": {"x": 1}})
    with pytest.raises(SynthConfigError, match="未知顶层键"):
        load_compose_config(p)


def test_config_rejects_bad_class_weight(tmp_path):
    p = _write_cfg(tmp_path, {"layout": {**config_to_dict(load_compose_config())["layout"],
                                        "class_weights": {"not_a_class": 1.0}}})
    with pytest.raises(SynthConfigError, match="taxonomy"):
        load_compose_config(p)


def test_config_rejects_contradictory_ranges(tmp_path):
    d = config_to_dict(load_compose_config())
    d["layout"]["n_beans"] = {"min": 50, "max": 10}
    p = tmp_path / "bad2.yaml"
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(SynthConfigError, match="min<=max"):
        load_compose_config(p)


def test_config_error_carries_file_path(tmp_path):
    p = _write_cfg(tmp_path, {"version": 99})
    with pytest.raises(SynthConfigError) as ei:
        load_compose_config(p)
    assert str(p) in str(ei.value)


# ---------------------------------------------------------------------------
# ⑥ M1 兼容：labels 逐粒可构造契约 BeanMask（oracle）
# ---------------------------------------------------------------------------


def test_labels_feed_m1_beanmask(tray, labels):
    masks: list[BeanMask] = []
    for i, e in enumerate(labels["beans"]):
        masks.append(
            BeanMask(
                mask_id=f"top_{i:04d}",
                side="top",
                polygon=[[float(x), float(y)] for x, y in e["poly_mm_top"]],
                bbox_mm=tuple(float(v) for v in e["bbox_mm"]),
                area_mm2=float(e["area_mm2"]),
                centroid_mm=tuple(float(v) for v in e["centroid_mm"]),
                source="oracle",
                conf=1.0,
            )
        )
    assert len(masks) == len(tray.beans)
    # 契约往返无损
    for m in masks[:5]:
        assert BeanMask.from_json(m.to_json()) == m
