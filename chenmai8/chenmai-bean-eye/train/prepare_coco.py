#!/usr/bin/env python3
"""T0 训练集产出 · 合成集 + 外部主源 COCO → 训练用 COCO 目录（prepare_coco）。

对应训练计划 T0/T6（``plan--咖啡豆质检/training-plan.md``）：从合成引擎
（:mod:`beaneye.synth`）产出 COCO 分割标注（13 类 taxonomy，polygon 或
未压缩 RLE），完成 holdout 划分（未见素材粒 + 固定种子，**永不入训练**）、
外部主源 COCO 类别映射合并、自采集真实盘评测目录（**仅评测**）与 sha256
完整性清单。

输入目录约定
    - ``--synth-config``：configs/synth.yaml（合成器标准输入；holdout 素材库
      种子 = ``library.seed + 1``，即「未见素材粒」）；
    - ``--from-existing DIR``：既有 ``write_batch`` 产物目录（labels_*.json +
      top/bottom PNG），离线转换、不重新合成；
    - ``--ext-coco-json``（+ ``--ext-image-root``）：外部主源 COCO 分割导出，
      类别经 ``--mapping-yaml``/taxonomy upstream_mapping 映射进 13 类；
    - ``--real-coco-json``（+ ``--real-image-root``）：自采集真实盘 COCO
      （类别 = 内部 taxonomy key），**只**产 ``real_test/`` 评测目录。

输出目录（默认 ``train/runs/datasets/v1``）
    ``train/`` ``valid/`` ``test/``（各含 _annotations.coco.json + 图像）、
    可选 ``real_test/``、``manifest.json``、``SHA256SUMS``（sha256sum -c 兼容）。

期望运行时长
    合成 2048² 对 ≈ 2–5 s/对（CPU）——10k 对约 6–14 h；``--seg-format rle``
    的掩码栅格化另加 ≈10 s/对（仅建议用于 holdout 500 对与小样本）；
    ``--emit-sample``（512² 小盘 1 对）秒级，纯离线。

失败回退
    合成逐对落盘、已存在产物自动跳过——中断后重跑同命令即断点续跑；
    SHA256SUMS 可随时校验已产出文件完整性。

GPU 机执行顺序与数据中转（六脚本通用，详见 train/README.md）
    T0（本脚本）→ T1（det_finetune）→ T2/T3（eval_ablation / domain_mix）；
    数据集经 COS 中转上传/下载（工程纪律：跨机不直传），到位后先
    ``sha256sum -c SHA256SUMS`` 校验。

中性名说明：上游 NN/数据集专有名不出现在本文件（gate_d3 纪律）；
``--emit-sample`` 为「dry-run 只打印计划」之外的离线小样本通道。
"""

from __future__ import annotations

import argparse
import dataclasses
import shutil
import sys
from pathlib import Path

import _common
from _common import (
    EXIT_USAGE,
    PlanReporter,
    build_categories,
    categories_by_name,
    load_json,
    resolve_path,
    save_json,
)

# 每对合成盘的粗略时长估算系数（秒/CPU 对，2048²；仅 dry-run 估算用）
EST_SECONDS_PER_PAIR = 3.5
# RLE 掩码形态下每对附加栅格化估算（秒；2048² × 2 面 × ~百粒）
EST_RLE_SECONDS_PER_PAIR = 10.0

SYNTH_SIDES = ("top", "bottom")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="T0 训练集产出：合成集 + 外部主源 → COCO 目录（--dry-run 纯离线打印计划）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不合成/不下载/不写产物，只校验并打印计划（离线，exit 0）")
    ap.add_argument("--synth-config", default="configs/synth.yaml",
                    help="合成器配置（YAML 标准输入；默认 configs/synth.yaml）")
    ap.add_argument("--out", default="train/runs/datasets/v1",
                    help="输出数据集根（相对仓库根；默认 train/runs/datasets/v1）")
    ap.add_argument("--train-pairs", type=int, default=10000,
                    help="训练对数（top+bottom 计 2×图像；计划 v1 = 10000 对）")
    ap.add_argument("--train-seed0", type=int, default=860001,
                    help="训练盘种子起点（默认 860001）")
    ap.add_argument("--holdout-pairs", type=int, default=500,
                    help="holdout 固定集对数（未见素材粒 + 新种子；默认 500，永不入训练）")
    ap.add_argument("--holdout-seed0", type=int, default=960001,
                    help="holdout 种子起点（与训练种子区间不得重叠）")
    ap.add_argument("--holdout-val-frac", type=float, default=0.5,
                    help="holdout 内部再分 valid 的比例（其余为 test；默认 0.5）")
    ap.add_argument("--seg-format", choices=("polygon", "rle"), default="polygon",
                    help="COCO segmentation 形态：polygon（默认，全量友好）| rle（未压缩 RLE，慢）")
    ap.add_argument("--image-format", choices=("png", "jpg"), default="png",
                    help="合成图像落盘格式：png（默认，训练计划规格）| jpg（磁盘预算受限的全量产出）")
    ap.add_argument("--jpeg-quality", type=int, default=92,
                    help="jpg 编码质量（--image-format jpg 时生效，默认 92）")
    # 合成分布覆盖（缺省 = 合成配置；训练计划 T0：80–600 粒/盘、粘连分档）
    ap.add_argument("--n-beans-min", type=int, default=None,
                    help="每盘豆数下限覆盖（默认取合成配置）")
    ap.add_argument("--n-beans-max", type=int, default=None,
                    help="每盘豆数上限覆盖（默认取合成配置）")
    ap.add_argument("--defect-rate", type=float, default=None,
                    help="缺陷豆占比覆盖 [0,1]（默认取合成配置）")
    ap.add_argument("--contact-min", type=int, default=None,
                    help="每盘接触/重叠豆数下限覆盖（粘连率分档用）")
    ap.add_argument("--contact-max", type=int, default=None,
                    help="每盘接触/重叠豆数上限覆盖（粘连率分档用）")
    ap.add_argument("--from-existing", default=None,
                    help="离线转换既有 write_batch 产物目录（labels_*.json）；给了它就不再在线合成")
    ap.add_argument("--ext-coco-json", default=None,
                    help="外部主源 COCO 分割导出 json（映射合并进 train/）")
    ap.add_argument("--ext-image-root", default=None,
                    help="外部主源图像根目录（file_name 相对它解析）")
    ap.add_argument("--mapping-yaml", default=None,
                    help="类别映射 YAML：{来源名: {上游标签: taxonomy key|null}}")
    ap.add_argument("--mapping-source", default="main",
                    help="映射文件/taxonomy upstream_mapping 里本数据集的来源键名（默认 main）")
    ap.add_argument("--real-coco-json", default=None,
                    help="自采集真实盘 COCO json（taxonomy key；只产 real_test/ 评测目录）")
    ap.add_argument("--real-image-root", default=None,
                    help="自采集真实盘图像根目录")
    ap.add_argument("--limit-pairs", type=int, default=0,
                    help="在线合成模式限制对数（冒烟/小样本；0=全量）")
    ap.add_argument("--emit-sample", default=None,
                    help="真实模式独占：离线产出 1 个 512² 小样本对 + COCO json 到该目录后退出（链路自检；与全量产出二选一）")
    ap.add_argument("--sample-seed", type=int, default=860001, help="小样本种子")
    return ap


# ---------------------------------------------------------------------------
# 合成标注 → COCO（核心转换；真实分支调用）
# ---------------------------------------------------------------------------


def _shoelace_px(pts: list[list[float]]) -> float:
    """像素多边形面积（shoelace；与合成引擎 mm 口径同式）。"""
    import numpy as np

    arr = np.asarray(pts, dtype=np.float64)
    x, y = arr[:, 0], arr[:, 1]
    return float(abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2.0)


def canvas_rle(poly_px: list[list[float]], w: int, h: int, canvas) -> tuple[dict, int]:
    """像素多边形 → 整幅画布未压缩 RLE（列主序）+ 栅格化面积（px²）。

    复用 :func:`beaneye.synth.rle_encode`（与 COCO 未压缩 RLE 同构）；栅格在
    多边形外接框局部完成、再贴回调用方复用的整幅缓冲（避免逐粒 2048² 重复分配）。
    面积返回**栅格化后的掩码像素数**（与 COCO 语义一致——pycocotools 的 area
    即掩码像素数；小粒上与多边形 shoelace 面积可差数十个百分点，不能混用）。
    """
    import cv2
    import numpy as np

    from beaneye.synth import rle_encode  # 复用合成引擎（列主序未压缩 RLE）

    pts = np.round(np.asarray(poly_px, dtype=np.float64)).astype(np.int32)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    pad = 2
    lx0, ly0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
    lx1, ly1 = min(int(w) - 1, int(x1) + pad), min(int(h) - 1, int(y1) + pad)
    if lx1 < lx0 or ly1 < ly0:
        raise ValueError(f"多边形完全落在画布外: bbox=({x0},{y0},{x1},{y1}) canvas={w}x{h}")
    local = np.zeros((ly1 - ly0 + 1, lx1 - lx0 + 1), dtype=np.uint8)
    cv2.fillPoly(local, [pts - np.asarray([lx0, ly0], dtype=np.int32)], 255)
    canvas[:] = 0
    canvas[ly0 : ly1 + 1, lx0 : lx1 + 1] |= local
    return rle_encode(canvas), int((local > 0).sum())


def synth_labels_to_coco(
    labels: dict,
    *,
    seg_format: str,
    name2id: dict[str, int],
    ann_id_start: int = 1,
) -> tuple[list[dict], list[dict]]:
    """一盘合成 labels（write_batch 产物）→ 两条 COCO image 记录 + 逐粒标注。

    image 记录带 ``side`` 字段（top/bottom），``file_name`` 由调用方按实际落盘名
    回填。标注扩展字段 = 训练计划 T0 真值口径：{bean_id, side, class_top,
    class_bottom, eq_diameter_mm}（毫米几何不进 COCO，留在 labels json）。
    """
    tray = labels.get("tray") or {}
    w, h = (int(v) for v in tray["canvas_px"])
    ox, oy = (float(v) for v in tray["origin_px"])
    ppm = float(tray["px_per_mm"])

    images: list[dict] = []
    anns: list[dict] = []
    ann_id = ann_id_start
    canvas = None
    import numpy as np

    for side in SYNTH_SIDES:
        images.append({
            "id": len(images) + 1,
            "file_name": None,
            "width": w,
            "height": h,
            "side": side,
        })
        for bean in labels.get("beans", []):
            cls_name = str(bean[f"class_{side}"])
            cat_id = name2id.get(cls_name)
            if cat_id is None:
                raise ValueError(
                    f"labels 内出现未知类别 {cls_name!r}（须为 taxonomy 13 类之一）"
                )
            poly_mm = bean[f"poly_mm_{side}"]
            poly_px = [[ox + float(x) * ppm, oy + float(y) * ppm] for x, y in poly_mm]
            xs = [p[0] for p in poly_px]
            ys = [p[1] for p in poly_px]
            bbox = [
                round(min(xs), 2), round(min(ys), 2),
                round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2),
            ]
            if seg_format == "polygon":
                segmentation: object = [[round(v, 2) for pt in poly_px for v in pt]]
                area_px = _shoelace_px(poly_px)
            else:
                if canvas is None:
                    canvas = np.zeros((h, w), dtype=np.uint8)
                segmentation, area_px = canvas_rle(poly_px, w, h, canvas)
            anns.append({
                "id": ann_id,
                "image_id": images[-1]["id"],
                "category_id": cat_id,
                "segmentation": segmentation,
                "bbox": bbox,
                "area": round(area_px, 2),
                "iscrowd": 0,
                "bean_id": bean.get("bean_id"),
                "side": side,
                "class_top": bean.get("class_top"),
                "class_bottom": bean.get("class_bottom"),
                "eq_diameter_mm": bean.get("eq_diameter_mm"),
            })
            ann_id += 1
    return images, anns


def synth_one_pair(seed: int, cfg, library, out_dir: Path, index: int,
                   img_ext: str = ".png", jpeg_quality: int = 92) -> Path:
    """合成一对盘并落盘（复用 beaneye.synth compose/write_batch），返回 labels 路径。

    with_rle=False：本脚本 COCO 标注自行按像素栅格化，托盘 mm 网格 RLE
    对训练无用，关掉以省 2048² × 每粒 的落盘开销。
    img_ext/jpeg_quality 透传 write_batch（默认 PNG，训练计划规格）。
    """
    from beaneye.synth import compose_tray, write_batch

    tray = compose_tray(seed=seed, config=cfg, library=library)
    paths = write_batch(tray, out_dir, index=index, with_rle=False,
                        img_ext=img_ext, jpeg_quality=jpeg_quality)
    return paths["labels"]


def load_synth_config(path: Path):
    """加载合成配置（真实分支；严格校验由 beaneye.synth.config 负责）。"""
    from beaneye.synth.config import load_compose_config

    return load_compose_config(path)


def override_synth_config(cfg, args: argparse.Namespace):
    """按 CLI 覆盖项派生训练用合成配置（区间校验仍由 loader/replace 后语义保证）。"""
    kw: dict = {}
    if args.n_beans_min is not None:
        kw["n_beans_min"] = args.n_beans_min
    if args.n_beans_max is not None:
        kw["n_beans_max"] = args.n_beans_max
    if args.defect_rate is not None:
        kw["defect_rate"] = args.defect_rate
    if args.contact_min is not None:
        kw["contact_min"] = args.contact_min
    if args.contact_max is not None:
        kw["contact_max"] = args.contact_max
    if not kw:
        return cfg
    cfg2 = dataclasses.replace(cfg, **kw)
    if cfg2.n_beans_min > cfg2.n_beans_max:
        raise ValueError(f"--n-beans 区间须 min<=max，得到 ({cfg2.n_beans_min}, {cfg2.n_beans_max})")
    if cfg2.contact_min > cfg2.contact_max:
        raise ValueError(f"--contact 区间须 min<=max，得到 ({cfg2.contact_min}, {cfg2.contact_max})")
    if not 0.0 <= cfg2.defect_rate <= 1.0:
        raise ValueError(f"--defect-rate 须在 [0,1]，得到 {cfg2.defect_rate}")
    return cfg2


# ---------------------------------------------------------------------------
# 外部主源 / 自采集合并（真实分支调用）
# ---------------------------------------------------------------------------


def load_category_mapping(args: argparse.Namespace, tax) -> dict[str, str | None]:
    """解析类别映射：--mapping-yaml 优先，其次 taxonomy upstream_mapping。"""
    if args.mapping_yaml:
        import yaml  # 合成配置同款依赖（核心钉版 pyyaml）

        data = yaml.safe_load(Path(args.mapping_yaml).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"映射文件顶层必须是映射: {args.mapping_yaml}")
        node = data.get(args.mapping_source)
        if node is None:
            raise ValueError(
                f"映射文件缺来源键 {args.mapping_source!r}（现有: {sorted(data)}）"
            )
    else:
        mapped = tax.upstream_mapping.get(args.mapping_source)
        if mapped is None:
            raise ValueError(
                f"taxonomy 无来源键 {args.mapping_source!r} 的 upstream_mapping，"
                f"且未提供 --mapping-yaml（现有来源: {tax.upstream_sources() or ['(空)']}）"
            )
        node = mapped
    return {str(k): (None if v is None else str(v)) for k, v in node.items()}


def merge_ext_coco(
    args: argparse.Namespace,
    tax,
    name2id: dict[str, int],
    out_split_dir: Path,
) -> tuple[list[dict], list[dict], dict]:
    """外部主源 COCO → 映射合并（图像复制加 ext_ 前缀防撞名）。

    返回 (images, anns, stats)——由调用方并入 train split 后统一写 json。
    """
    import shutil

    ext = load_json(args.ext_coco_json)
    if not isinstance(ext, dict) or "images" not in ext or "annotations" not in ext:
        raise ValueError(f"外部 COCO json 结构不完整: {args.ext_coco_json}")
    mapping = load_category_mapping(args, tax)
    image_root = resolve_path(args.ext_image_root) if args.ext_image_root else None

    up_by_id = {int(c["id"]): str(c.get("name", c["id"])) for c in ext.get("categories", [])}
    cat_map: dict[int, int] = {}
    skipped_cats: list[str] = []
    for up_id, up_name in up_by_id.items():
        target = mapping.get(up_name, "__missing__")
        if target in (None, "__missing__"):
            skipped_cats.append(up_name)
            continue
        if target not in name2id:
            raise ValueError(
                f"映射目标 {target!r} 不是 taxonomy key（upstream {up_name!r}）"
            )
        cat_map[up_id] = name2id[target]

    img_by_id = {int(i["id"]): i for i in ext["images"]}
    # 一张外部图上多粒是常态：image 记录按目标文件名**去重**（首见建条），
    # 各标注回指同一 image id——否则一图 N 粒会产出 N 条重复 image 条目、
    # 训练集语义损坏且 stats 虚高（复核 HIGH 项实测：1 图×3 标注 → images=3）。
    img_by_dst: dict[str, dict] = {}
    out_anns: list[dict] = []
    n_skip_cat = n_skip_crowd = n_skip_file = 0
    for ann in ext["annotations"]:
        up_cat = int(ann.get("category_id", -1))
        if up_cat not in cat_map:
            n_skip_cat += 1
            continue
        if int(ann.get("iscrowd", 0)):
            n_skip_crowd += 1
            continue
        src_img = img_by_id.get(int(ann["image_id"]))
        if src_img is None:
            n_skip_file += 1
            continue
        fname = Path(str(src_img.get("file_name", ""))).name
        src = image_root / fname if image_root else None
        if src is None or not src.is_file():
            n_skip_file += 1
            continue
        dst_name = f"ext_{fname}"
        img_entry = img_by_dst.get(dst_name)
        if img_entry is None:
            dst = out_split_dir / dst_name
            if not dst.exists():
                shutil.copy2(src, dst)
            img_entry = {
                "id": len(img_by_dst) + 1,
                "file_name": dst_name,
                "width": int(src_img.get("width", 0)),
                "height": int(src_img.get("height", 0)),
                "side": "ext",
            }
            img_by_dst[dst_name] = img_entry
        out_anns.append({
            "id": len(out_anns) + 1,
            "image_id": img_entry["id"],
            "category_id": cat_map[up_cat],
            "segmentation": ann.get("segmentation", []),
            "bbox": ann.get("bbox", []),
            "area": ann.get("area", 0.0),
            "iscrowd": 0,
            "source": "ext",
        })
    out_images = list(img_by_dst.values())
    stats = {
        "images": len(out_images),
        "annotations": len(out_anns),
        "skipped_unmapped_cat": n_skip_cat,
        "skipped_crowd": n_skip_crowd,
        "skipped_missing_file": n_skip_file,
        "skipped_categories": sorted(set(skipped_cats)),
    }
    return out_images, out_anns, stats


def convert_real_coco(
    args: argparse.Namespace,
    name2id: dict[str, int],
    out_dir: Path,
) -> dict:
    """自采集真实盘 COCO → real_test/ 评测目录（**永不入训练**，红线）。"""
    import shutil

    data = load_json(args.real_coco_json)
    if not isinstance(data, dict) or "images" not in data or "annotations" not in data:
        raise ValueError(f"真实盘 COCO json 结构不完整: {args.real_coco_json}")
    image_root = resolve_path(args.real_image_root) if args.real_image_root else None
    real_dir = out_dir / "real_test"
    real_dir.mkdir(parents=True, exist_ok=True)

    out_anns: list[dict] = []
    n_bad_cat = n_skip_file = 0
    cat_by_id = {int(c["id"]): str(c.get("name", c["id"])) for c in data.get("categories", [])}
    img_by_id = {int(i["id"]): i for i in data["images"]}
    img_by_dst: dict[str, dict] = {}  # image 条目按目标文件名去重（不依赖标注相邻序）
    for ann in data["annotations"]:
        cls_name = cat_by_id.get(int(ann.get("category_id", -1)))
        if cls_name is None or cls_name not in name2id:
            n_bad_cat += 1
            continue
        src_img = img_by_id.get(int(ann["image_id"]))
        if src_img is None:
            continue
        fname = Path(str(src_img.get("file_name", ""))).name
        src = image_root / fname if image_root else None
        if src is None or not src.is_file():
            n_skip_file += 1
            continue
        dst_name = f"real_{fname}"
        img_entry = img_by_dst.get(dst_name)
        if img_entry is None:
            dst = real_dir / dst_name
            if not dst.exists():
                shutil.copy2(src, dst)
            img_entry = {
                "id": len(img_by_dst) + 1,
                "file_name": dst_name,
                "width": int(src_img.get("width", 0)),
                "height": int(src_img.get("height", 0)),
            }
            img_by_dst[dst_name] = img_entry
        out_anns.append({
            "id": len(out_anns) + 1,
            "image_id": img_entry["id"],
            "category_id": name2id[cls_name],
            "segmentation": ann.get("segmentation", []),
            "bbox": ann.get("bbox", []),
            "area": ann.get("area", 0.0),
            "iscrowd": 0,
            "source": "real_self_collected",
        })
    out_images = list(img_by_dst.values())
    save_json(
        real_dir / "_annotations.coco.json",
        {"images": out_images, "annotations": out_anns},
    )
    return {
        "images": len(out_images),
        "annotations": len(out_anns),
        "bad_category": n_bad_cat,
        "skipped_missing_file": n_skip_file,
    }


# ---------------------------------------------------------------------------
# 输出装配
# ---------------------------------------------------------------------------


def write_split_json(split_dir: Path, images: list[dict], anns: list[dict], cats: list[dict]) -> Path:
    split_dir.mkdir(parents=True, exist_ok=True)
    return save_json(
        split_dir / "_annotations.coco.json",
        {"images": images, "annotations": anns, "categories": cats},
    )


def write_manifest(out_dir: Path, args: argparse.Namespace, cats: list[dict], stats: dict) -> Path:
    import hashlib

    tax_sha = hashlib.sha256(_common.DEFAULT_TAXONOMY.read_bytes()).hexdigest()
    manifest = {
        "prepared_by": "train/prepare_coco.py (beaneye 训练线)",
        "seg_format": args.seg_format,
        "storage_format": {
            "image_format": args.image_format,
            "jpeg_quality": args.jpeg_quality if args.image_format == "jpg" else None,
            "deviation_note": (
                "jpg 偏离训练计划 PNG 规格：GPU 机磁盘预算受限"
                "（/data 可用 < PNG 全量约 147GB 实测外推），"
                "owner 2026-10-03 授权改 JPG（质量≥92）"
                if args.image_format == "jpg" else "png（训练计划规格）"
            ),
        },
        "seeds": {
            "train_seed0": args.train_seed0,
            "train_pairs": args.train_pairs,
            "holdout_seed0": args.holdout_seed0,
            "holdout_pairs": args.holdout_pairs,
            "holdout_val_frac": args.holdout_val_frac,
        },
        "taxonomy_sha256": tax_sha,
        "categories": cats,
        "redlines": [
            "holdout（valid/test）固定集永不入训练（工程纪律）",
            "自采集真实盘只产 real_test/ 评测目录，永不入训练（v0.1 全量仅评测/阈值回填）",
        ],
        "stats": stats,
    }
    return save_json(out_dir / "manifest.json", manifest)


# ---------------------------------------------------------------------------
# 防泄漏红线：种子区间重叠校验（dry-run 与真实模式共用，双向对称）
# ---------------------------------------------------------------------------


def seed_overlap_error(args: argparse.Namespace) -> str | None:
    """训练/holdout 种子区间**双向**重叠检测；重叠返回错误描述。

    区间：train = [train_seed0, train_seed0 + 有效训练对数)，
    holdout = [holdout_seed0, holdout_seed0 + holdout_pairs)。
    任何方向的部分交叠都拒绝（防泄漏红线；复核实测单向校验有逃逸方向）。
    """
    n_train = min(args.train_pairs, args.limit_pairs) if args.limit_pairs else args.train_pairs
    t0, t1 = args.train_seed0, args.train_seed0 + max(n_train, 0)
    h0, h1 = args.holdout_seed0, args.holdout_seed0 + args.holdout_pairs
    if n_train > 0 and t0 < h1 and h0 < t1:
        return (
            f"种子区间重叠（防泄漏红线）：train [{t0}, {t1}) × "
            f"holdout [{h0}, {h1}) 相交"
        )
    return None


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    rep.header("prepare_coco.py", "T0 训练集产出（合成集 + 外部主源 → COCO）")

    rep.section("1. 输入")
    cfg_path = resolve_path(args.synth_config)
    rep.check_file(cfg_path, "合成配置")
    if args.from_existing:
        d = resolve_path(args.from_existing)
        if d.is_dir():
            n_labels = len(list(d.glob("labels_*.json")))
            rep.ok(f"既有合成产物目录: {d}（labels_*.json × {n_labels}，离线转换、不再合成）")
        else:
            rep.missing(f"既有合成产物目录: {d}")
    else:
        rep.plan("在线合成模式（beaneye.synth compose_tray/write_batch 逐对落盘，断点续跑）")
    if args.ext_coco_json:
        p = resolve_path(args.ext_coco_json)
        if p.is_file():
            try:
                ext = load_json(p)
                if not isinstance(ext, dict) or "images" not in ext:
                    raise ValueError("顶层缺 images/annotations")
                rep.ok(
                    f"外部主源 COCO: {p}（图像 {len(ext['images'])}，标注 "
                    f"{len(ext.get('annotations', []))}，上游类别 "
                    f"{[c.get('name') for c in ext.get('categories', [])]}）"
                )
            except ValueError as exc:
                rep.error(f"外部主源 COCO json 非法: {exc}")
        else:
            rep.missing(f"外部主源 COCO: {p}")
        if not args.ext_image_root:
            rep.error("--ext-coco-json 提供时必须同时提供 --ext-image-root")
    if args.real_coco_json:
        p = resolve_path(args.real_coco_json)
        if p.is_file():
            try:
                real = load_json(p)
                if not isinstance(real, dict) or "images" not in real:
                    raise ValueError("顶层缺 images/annotations")
                rep.ok(
                    f"自采集真实盘 COCO: {p}（图像 {len(real['images'])}，"
                    f"标注 {len(real.get('annotations', []))}；只产 real_test/ 评测目录）"
                )
            except ValueError as exc:
                rep.error(f"真实盘 COCO json 非法: {exc}")
        else:
            rep.missing(f"自采集真实盘 COCO: {p}")
        if not args.real_image_root:
            rep.error("--real-coco-json 提供时必须同时提供 --real-image-root")
    overlap = seed_overlap_error(args)
    if overlap:
        rep.error(overlap)

    rep.section("2. 类别表（taxonomy 13 类 → COCO category id）")
    try:
        cats, _tax = build_categories()
        for c in cats:
            rep.plan(f"id={c['id']:>2}  {c['name']:<10} kind={c['supercategory']}")
    except Exception as exc:  # noqa: BLE001（taxonomy 缺失/非法要在 dry-run 暴露）
        rep.error(f"taxonomy 加载失败: {exc}")

    rep.section("3. 划分计划（防泄漏红线）")
    n_train = min(args.train_pairs, args.limit_pairs) if args.limit_pairs else args.train_pairs
    n_val = int(round(args.holdout_pairs * args.holdout_val_frac))
    n_test = args.holdout_pairs - n_val
    rep.plan(
        f"train/：种子 [{args.train_seed0}, {args.train_seed0 + n_train}) 共 {n_train} 对"
        f" → {2 * n_train} 图（n_beans/粘连档默认取合成配置；训练计划口径 80–600 粒/盘）"
    )
    rep.plan(
        f"valid/：holdout 前 {n_val} 对（种子 [{args.holdout_seed0}, "
        f"{args.holdout_seed0 + n_val})）；test/：其余 {n_test} 对——"
        "素材库种子 = library.seed + 1（未见素材粒，与训练素材零共享）"
    )
    est_h = EST_SECONDS_PER_PAIR * max(n_train + args.holdout_pairs, 0) / 3600.0
    msg = f"估算时长（CPU）：合成 ≈{EST_SECONDS_PER_PAIR:.1f}s/对 → {est_h:.1f} h"
    if args.seg_format == "rle":
        msg += (
            f"；--seg-format rle 掩码栅格化另加 ≈"
            f"{EST_RLE_SECONDS_PER_PAIR * (n_train + args.holdout_pairs) / 3600:.1f} h"
            "（RLE 建议只用于 holdout 与小样本，全量用 polygon）"
        )
    rep.plan(msg)
    rep.warn("holdout（valid/test）固定集永不入训练；训练集划分与 holdout 素材/种子完全隔离")

    rep.section("4. 输出布局")
    out = resolve_path(args.out)
    rep.plan(f"数据集根: {out}")
    for sub in ("train", "valid", "test"):
        rep.plan(f"{out / sub / '_annotations.coco.json'} + 图像")
    if args.real_coco_json:
        rep.plan(f"{out / 'real_test' / '_annotations.coco.json'}（仅评测，永不入训练）")
    rep.plan(f"{out / 'manifest.json'} + {out / 'SHA256SUMS'}（sha256sum -c 可校验）")

    rep.section("5. 红线提示")
    rep.warn("自采集 v0.1 全量只用于评测/阈值回填；训练混入走 domain_mix.py 且需显式红线确认")
    rep.warn("数据集跨机传输走 COS 中转（跨机不直传），到位后 sha256sum -c 校验")
    if args.emit_sample:
        rep.plan(
            f"--emit-sample {resolve_path(args.emit_sample)}：真实模式产出 1 个 512² 小样本"
            "（compose_tray + write_batch + COCO json，纯离线链路自检）"
        )
    return rep.finish()


# ---------------------------------------------------------------------------
# 真实执行
# ---------------------------------------------------------------------------


def emit_sample(args: argparse.Namespace, cats: list[dict], name2id: dict[str, int]) -> dict:
    """离线小样本：512² 小盘 1 对 → write_batch + COCO json（链路自检用）。"""
    cfg = load_synth_config(resolve_path(args.synth_config))
    small = dataclasses.replace(
        cfg,
        width_px=512,
        height_px=512,
        margin_mm=10.0,
        n_beans_min=6,
        n_beans_max=10,
        contact_min=1,
        contact_max=3,
    )
    sample_dir = resolve_path(args.emit_sample)
    sample_dir.mkdir(parents=True, exist_ok=True)
    labels_path = synth_one_pair(args.sample_seed, small, None, sample_dir, index=1)
    labels = load_json(labels_path)
    images, anns = synth_labels_to_coco(labels, seg_format=args.seg_format, name2id=name2id)
    for img in images:
        img["file_name"] = f"{img['side']}_0001.png"
    save_json(
        sample_dir / "_annotations.coco.json",
        {"images": images, "annotations": anns, "categories": cats},
    )
    return {
        "dir": str(sample_dir),
        "images": len(images),
        "annotations": len(anns),
        "seg_format": args.seg_format,
    }


def run(args: argparse.Namespace, rep: PlanReporter) -> int:
    cats, tax = build_categories()
    name2id = categories_by_name(cats)
    out = resolve_path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stats: dict[str, dict] = {}

    # ---- 1) 小样本自检通道（独占模式：只产出小样本并退出） ------------------
    if args.emit_sample:
        stats["sample"] = emit_sample(args, cats, name2id)
        print(f"[prepare] emit-sample: {stats['sample']}", flush=True)
        write_manifest(out_dir=out, args=args, cats=cats, stats=stats)
        print(f"[prepare] 小样本自检完成: {args.emit_sample}"
              "（--emit-sample 为独占模式；全量产出请去掉该参数再跑）")
        return 0

    cfg = override_synth_config(load_synth_config(resolve_path(args.synth_config)), args)
    n_holdout_val = int(round(args.holdout_pairs * args.holdout_val_frac))
    splits: dict[str, dict] = {
        name: {"images": [], "anns": [], "dir": out / name}
        for name in ("train", "valid", "test")
    }
    split_files: list[Path] = []

    # ---- 2) 合成对（在线合成或离线转换既有产物） ----------------------------
    if args.from_existing:
        src = resolve_path(args.from_existing)
        labels_paths = sorted(src.glob("labels_*.json"))
        if not labels_paths:
            print(f"[FAIL] 既有产物目录无 labels_*.json: {src}")
            return 1
        for node in splits.values():  # 图像复制目标目录先行就绪
            node["dir"].mkdir(parents=True, exist_ok=True)
        for lp in labels_paths:
            labels = load_json(lp)
            seed = int(labels["seed"])
            if args.holdout_seed0 <= seed < args.holdout_seed0 + args.holdout_pairs:
                idx = seed - args.holdout_seed0
                split = "valid" if idx < n_holdout_val else "test"
            else:
                split = "train"
            node = splits[split]
            images, anns = synth_labels_to_coco(
                labels, seg_format=args.seg_format, name2id=name2id,
                ann_id_start=len(node["anns"]) + 1,
            )
            stem = lp.stem.replace("labels_", "")
            for img in images:
                fname = f"{img['side']}_{stem}.png"
                img["file_name"] = fname
                img["id"] = len(node["images"]) + 1
                src_png = lp.parent / fname
                if not src_png.is_file():
                    raise FileNotFoundError(f"既有产物缺图像文件: {src_png}")
                dst_png = node["dir"] / fname
                if not dst_png.exists():
                    shutil.copy2(src_png, dst_png)
            for ann in anns:  # image_id 重排到本 split 的连续 id
                ann["image_id"] = images[0]["id"] if ann["side"] == "top" else images[1]["id"]
            node["images"].extend(images)
            node["anns"].extend(anns)
    else:
        n_train = min(args.train_pairs, args.limit_pairs) if args.limit_pairs else args.train_pairs
        from beaneye.synth import sample_library  # 真实分支惰性导入（重量级）

        holdout_cfg = dataclasses.replace(cfg, library_seed=cfg.library_seed + 1)
        train_lib = sample_library(cfg.library_seed, cfg.per_class)
        holdout_lib = sample_library(holdout_cfg.library_seed, holdout_cfg.per_class)
        counters = {"train": 0, "valid": 0, "test": 0}
        img_ext = ".jpg" if args.image_format == "jpg" else ".png"
        jobs: list[tuple[int, object, object, str]] = []
        for k in range(n_train):
            jobs.append((args.train_seed0 + k, cfg, train_lib, "train"))
        for k in range(args.holdout_pairs):
            split = "valid" if k < n_holdout_val else "test"
            jobs.append((args.holdout_seed0 + k, holdout_cfg, holdout_lib, split))
        for seed, scfg, lib, split in jobs:
            node = splits[split]
            counters[split] += 1
            idx = counters[split]
            sdir = node["dir"]
            labels_path = sdir / f"labels_{idx:04d}.json"
            if not labels_path.exists():  # 断点续跑：已有产物跳过
                synth_one_pair(seed, scfg, lib, sdir, index=idx,
                               img_ext=img_ext, jpeg_quality=args.jpeg_quality)
            labels = load_json(labels_path)
            images, anns = synth_labels_to_coco(
                labels, seg_format=args.seg_format, name2id=name2id,
                ann_id_start=len(node["anns"]) + 1,
            )
            for img in images:
                img["file_name"] = f"{img['side']}_{idx:04d}{img_ext}"
                img["id"] = len(node["images"]) + 1
            for ann in anns:
                ann["image_id"] = images[0]["id"] if ann["side"] == "top" else images[1]["id"]
            node["images"].extend(images)
            node["anns"].extend(anns)
            if idx % 50 == 0:
                print(f"[prepare] {split}: {idx} 对完成", flush=True)

    # ---- 3) 外部主源合并进 train / 自采集评测目录 ---------------------------
    if args.ext_coco_json:
        ext_imgs, ext_anns, ext_stats = merge_ext_coco(args, tax, name2id, out / "train")
        base = len(splits["train"]["images"])
        for img in ext_imgs:
            img["id"] = base + img["id"]
        for ann in ext_anns:
            ann["id"] = len(splits["train"]["anns"]) + 1
            ann["image_id"] = base + ann["image_id"]
        splits["train"]["images"].extend(ext_imgs)
        splits["train"]["anns"].extend(ext_anns)
        stats["ext_merged_into_train"] = ext_stats
    if args.real_coco_json:
        stats["real_test_eval_only"] = convert_real_coco(args, name2id, out)
        split_files.append(out / "real_test" / "_annotations.coco.json")

    # ---- 4) split json 落盘 + manifest + sha256 清单 ------------------------
    for name, node in splits.items():
        if node["images"]:
            stats.setdefault(name, {})
            stats[name] = {"images": len(node["images"]), "annotations": len(node["anns"])}
            split_files.append(write_split_json(node["dir"], node["images"], node["anns"], cats))
            split_files.extend(node["dir"] / i["file_name"] for i in node["images"])
    if args.real_coco_json and (out / "real_test").is_dir():
        split_files.extend(p for p in sorted((out / "real_test").glob("*.png")))

    write_manifest(out, args, cats, stats)
    split_files.append(out / "manifest.json")
    _common.write_sha256_sums(out, split_files, out / "SHA256SUMS")

    print(f"[prepare] 完成：{stats}")
    print(f"[prepare] 数据集根: {out}（SHA256SUMS 可用 sha256sum -c 校验）")
    print("[prepare] 上传 GPU 机走 COS 中转（跨机不直传）")
    return 0


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    if args.limit_pairs < 0 or args.train_pairs < 0 or args.holdout_pairs <= 0:
        print("[错误] --train-pairs/--limit-pairs 须 >=0，--holdout-pairs 须 >0")
        return EXIT_USAGE
    if not 0.0 < args.holdout_val_frac < 1.0:
        print("[错误] --holdout-val-frac 须在 (0,1)")
        return EXIT_USAGE
    if (args.n_beans_min is not None and args.n_beans_max is not None
            and args.n_beans_min > args.n_beans_max):
        print("[错误] --n-beans-min/max 区间须 min<=max")
        return EXIT_USAGE
    if (args.contact_min is not None and args.contact_max is not None
            and args.contact_min > args.contact_max):
        print("[错误] --contact-min/max 区间须 min<=max")
        return EXIT_USAGE
    if args.defect_rate is not None and not 0.0 <= args.defect_rate <= 1.0:
        print("[错误] --defect-rate 须在 [0,1]")
        return EXIT_USAGE
    overlap = seed_overlap_error(args)  # 双向对称校验；dry-run 与真实模式同样拒绝
    if overlap:
        print(f"[错误] {overlap}")
        return EXIT_USAGE
    rep = PlanReporter(dry_run=args.dry_run)
    try:
        if args.dry_run:
            return dry_run(args, rep)
        return run(args, rep)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
