"""scripts/collect_masks.py 单元测试（采集操作卡 §6 自检工具，离线合成图）。

覆盖：
- extract_mask：浅底深豆正常提取（连通域数/掩码取值 {0,255}）、小噪点滤除、
  极性自检（深底浅豆自动反转）、force_invert 手动反转；
- polygon_iou：同形状多边形 IoU=1.0、扰动多边形 IoU 与 numpy 手算一致、
  空掩码/非法顶点报错；
- load_polygon_points：labelme shapes 格式与 {"points": ...} 简式两种解析；
- main() CLI：extract 落盘同名 .png（正面+反面 _b，跳过散铺照）且逐图计数
  正确（tmp_path）；poly2mask 按原图尺寸栅格化落盘且与 rasterize_polygon 一致。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_collect_masks.py -q
"""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from scripts.collect_masks import extract_mask, load_polygon_points, main, polygon_iou, rasterize_polygon

W, H = 640, 480


def _bean_scene() -> np.ndarray:
    """浅灰底（≈RGB 208,203,200 的灰度 204）+ 两粒深色椭圆豆 + 一粒 2px 噪点。"""
    img = np.full((H, W, 3), 204, dtype=np.uint8)
    cv2.ellipse(img, (200, 240), (60, 40), 0, 0, 360, (90, 80, 70), -1)
    cv2.ellipse(img, (430, 240), (50, 35), 30, 0, 360, (100, 90, 80), -1)
    img[10:12, 10:12] = (60, 60, 60)  # 4px 噪点（< 默认 min_area_px=500，应滤除）
    return img


def test_extract_counts_and_values() -> None:
    mask, count, areas = extract_mask(_bean_scene())
    assert count == 2, f"应检出 2 粒（噪点滤除），得到 {count}"
    assert mask.dtype == np.uint8 and set(np.unique(mask).tolist()) <= {0, 255}
    assert len(areas) == 2 and all(a >= 500 for a in areas)


def test_extract_polarity_auto_invert() -> None:
    """深底浅豆：边框带前景占比 >50% → 自动反转，检出数不变。"""
    dark = 255 - _bean_scene()  # 深底 + 两粒浅豆
    mask, count, _areas = extract_mask(dark)
    assert count == 2


def test_extract_force_invert() -> None:
    """force_invert 手动反转且不被极性自检改回：浅底深豆场景反转后背景成前景。"""
    auto_mask, _auto_n, _ = extract_mask(_bean_scene())
    inv_mask, inv_n, _ = extract_mask(_bean_scene(), force_invert=True)
    assert inv_n == 1  # 反转后整幅背景连成一张巨连通域——证明确实反转了
    assert (inv_mask > 0).mean() > 0.5 and (auto_mask > 0).mean() < 0.5


def test_polygon_iou_perfect_and_perturbed() -> None:
    img = _bean_scene()
    mask, _count, _areas = extract_mask(img)
    # 完整覆盖单粒的矩形 vs 双豆整图掩码：IoU <1（含第二粒与背景），与 numpy 手算一致
    rect = [[140, 200], [260, 200], [260, 280], [140, 280]]
    iou = polygon_iou(mask, rect)
    m = mask > 0
    hand = np.zeros_like(m)
    hand[200:280, 140:260] = True
    expect = np.logical_and(m, hand).sum() / np.logical_or(m, hand).sum()
    # numpy 切片与 fillPoly 在边界一圈像素上有差（后者含右/下边界），
    # 容差给 0.02；关键断言是「矩形罩单粒 ≈ 0.5 而非 1.0」
    assert abs(iou - float(expect)) < 0.02
    assert iou < 0.9
    # 单粒裁剪掩码 + 沿粒缘手勾椭圆多边形：贴合度应过协议抽检门槛
    sub = mask[195:285, 135:265]
    pts = (cv2.ellipse2Poly((200, 240), (60, 40), 0, 0, 360, 5) - [135, 195]).tolist()
    single_iou = polygon_iou(sub, pts)
    assert 0.95 < single_iou <= 1.0


def test_polygon_iou_empty_and_bad_points() -> None:
    empty = np.zeros((H, W), dtype=np.uint8)
    rect = [[10, 10], [50, 10], [50, 50], [10, 50]]
    # 空掩码 + 合法多边形 → 交并为多边形本身，IoU=0（不报错）
    assert polygon_iou(empty, rect) == 0.0
    # 两者皆空（多边形在画布外）→ IoU 无定义，报错
    with pytest.raises(ValueError, match="均为空"):
        polygon_iou(empty, [[-20, -20], [-20, -10], [-10, -20]])
    with pytest.raises(ValueError, match="非法"):
        polygon_iou(empty, [[1, 2], [3, 4]])


def test_load_polygon_points_labelme_and_simple(tmp_path) -> None:
    labelme = {
        "imagePath": "black_20261003_001.png",
        "shapes": [{"label": "black", "points": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]}],
    }
    p1 = tmp_path / "labelme.json"
    p1.write_text(json.dumps(labelme), encoding="utf-8")
    assert load_polygon_points(p1) == [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
    p2 = tmp_path / "simple.json"
    p2.write_text(json.dumps({"points": [[9.0, 9.0], [9.0, 20.0], [20.0, 20.0]]}), encoding="utf-8")
    assert len(load_polygon_points(p2)) == 3
    p3 = tmp_path / "bad.json"
    p3.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="shapes"):
        load_polygon_points(p3)


def test_cli_extract_writes_masks(tmp_path, capsys) -> None:
    img_dir = tmp_path / "images" / "black"
    mask_dir = tmp_path / "masks" / "black"
    img_dir.mkdir(parents=True)
    cv2.imwrite(str(img_dir / "black_20261003_001.png"), _bean_scene())
    cv2.imwrite(str(img_dir / "black_20261003_001_b.png"), _bean_scene())  # 反面照也要掩码（同名 _b）
    cv2.imwrite(str(img_dir / "black_20261003_002_pile.png"), _bean_scene())  # 散铺照应被跳过
    rc = main(["extract", str(img_dir), str(mask_dir)])
    assert rc == 0
    written = sorted(p.name for p in mask_dir.glob("*.png"))
    assert written == ["black_20261003_001.png", "black_20261003_001_b.png"], (
        f"正面+反面都出掩码、散铺照跳过，实际 {written}"
    )
    out = capsys.readouterr().out
    assert "连通域 2 个" in out and "面积中位数" in out


def test_rasterize_polygon_and_poly2mask_cli(tmp_path, capsys) -> None:
    """poly2mask：手勾多边形按原图尺寸栅格化落盘（人工修正路径）。"""
    img = _bean_scene()
    img_path = tmp_path / "black_20261003_009.png"
    cv2.imwrite(str(img_path), img)
    pts = cv2.ellipse2Poly((200, 240), (60, 40), 0, 0, 360, 5).tolist()
    jf = tmp_path / "fix.json"
    jf.write_text(json.dumps({"points": pts}), encoding="utf-8")
    out = tmp_path / "masks" / "black_20261003_009.png"
    rc = main(["poly2mask", str(jf), str(img_path), str(out)])
    assert rc == 0
    mask = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
    assert mask.shape == img.shape[:2]
    assert set(np.unique(mask).tolist()) <= {0, 255}
    # 与 rasterize_polygon 直接实现一致（同一栅格化语义）
    expect = rasterize_polygon(pts, *img.shape[:2])
    assert int(np.logical_xor(mask > 0, expect > 0).sum()) == 0
    assert "前景" in capsys.readouterr().out


def test_cli_extract_few_samples_skips_flag(tmp_path, capsys) -> None:
    img_dir = tmp_path / "images" / "black"
    mask_dir = tmp_path / "masks" / "black"
    img_dir.mkdir(parents=True)
    cv2.imwrite(str(img_dir / "black_20261003_001.png"), _bean_scene())
    rc = main(["extract", str(img_dir), str(mask_dir)])
    assert rc == 0
    assert "跳过 ±40%" in capsys.readouterr().out
