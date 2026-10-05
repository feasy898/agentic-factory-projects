#!/usr/bin/env python3
"""单粒豆裁片产出 · v2synth COCO 数据集 → 固定边长单粒分类裁片（prepare_crops）。

对应训练计划 T0 之后、单粒分类训练之前的数据准备：从 v2synth 合成集
（train/valid/test 三 split 的 COCO 标注 + 2048² JPG，top/bottom 两面各为
独立图像）逐标注裁出单粒豆小图并归一化到 ``--size``²，供单粒分类器使用。
**holdout 语义保持**：valid/test 裁片只作评测，永不入训练（与 prepare_coco
的 redline 一致；本脚本不做任何 split 间数据搬移）。

输入目录约定
    ``--data-dir``：v2synth 数据集根（默认 ``train/runs/datasets/v2synth``，
    相对路径一律相对仓库根），下含 ``{train,valid,test}/_annotations.coco.json``
    与同目录 JPG（file_name 相对所在 split 目录解析）。
    **v2synth 的 image id 为 top/bottom 对共用**（valid 实测 500 图仅 250 个
    不同 id：top_0001 与 bottom_0001 同为 id=1），标注须按
    ``(image_id, side)`` join 才能唯一定位图像——side 缺失/对不上的标注计
    dangling、不产出（manifest 如实记录，不静默错裁）。

输出目录（GPU 机默认 ``/data/coffee-bean/crops``；相对路径相对仓库根）
    ``<split>/<classkey>/<hash>.jpg``（classkey = taxonomy 13 类 key；
    hash = sha1("split|file_name|ann_id") 前 16 hex——确定性命名，同输入
    同名，支持断点续跑）+ ``manifest.json``（每 split 每类 raw/kept/produced
    计数与总数）。类不平衡**如实记录**：normal 在合成集 raw 计数占绝对
    大头，manifest 保留 raw 与 kept 两套计数，重采样/加权留给训练侧。

期望运行时长
    GPU 机（16 核，--workers 12）：train 20000 图 / 约 208 万裁片 ≈ 20–40 min，
    valid/test 各 500 图各 ≈ 1–2 min；``--workers 1`` 单进程慢约一个量级。
    内存：train 标注 json ≈7.5GB，全量解析峰值 ≈30–40GB（一次性，解析后
    立即瘦身释放；<64GB 空闲内存的机器请勿跑 train split 全量）。

失败回退
    裁片确定性命名 + 已存在跳过——中断后重跑同命令即断点续跑；缺图与
    退化 bbox 逐条跳过并计数进 manifest，结尾 ``images_missing > 0`` 或
    worker 出错 → exit 1（不静默）。

bbox 取法
    优先标注自带 ``bbox``（[x,y,w,h]）；缺失/退化时回退 segmentation：
    polygon 取坐标外接框，未压缩 RLE（列主序，与 ``train/_metrics.py``
    ``decode_segmentation`` / ``beaneye.synth.rle_decode`` 同约定）手写
    解码取前景外接框——不引入 pycocotools（守「本轮零新增依赖」）。

GPU 机执行顺序与数据中转（详见 train/README.md）
    v2synth（prepare_coco 产物，经 COS 中转到位）→ 本脚本 → 单粒分类训练；
    裁片落 /data（磁盘预算内，实测约 3–4GB），仓库与 train/runs 不放大数据。

中性名说明：上游 NN/数据集专有名不出现在本文件（gate_d3 纪律）；
``--limit-images`` 为小样本自检通道（只裁每 split 前 N 张图）。
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import math
import random
import sys
import time
from collections import Counter
from multiprocessing import get_context
from pathlib import Path

import _common
from _common import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    PlanReporter,
    build_categories,
    load_json,
    resolve_path,
    save_json,
)

SPLITS = ("train", "valid", "test")

# dry-run 不解析大 json（train 标注 json ≈7.5GB），规模引用数据集自带
# manifest.json 的 stats 字段打印（真实模式全量解析、以实测计数为准）。


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="单粒豆裁片产出：v2synth COCO → 分类裁片（--dry-run 纯离线打印计划）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不读图像/不裁剪/不写产物，只校验并打印计划（离线，exit 0）")
    ap.add_argument("--data-dir", default="train/runs/datasets/v2synth",
                    help="v2synth 数据集根（相对仓库根；默认 train/runs/datasets/v2synth）")
    ap.add_argument("--out", default="/data/coffee-bean/crops",
                    help="裁片输出根（默认 /data/coffee-bean/crops；相对路径相对仓库根）")
    ap.add_argument("--size", type=int, default=224,
                    help="裁片目标边长（正方形；默认 224）")
    ap.add_argument("--pad-frac", type=float, default=0.15,
                    help="bbox 外扩比例（相对 bbox 边长；默认 0.15）")
    ap.add_argument("--per-class-cap", type=int, default=20000,
                    help="每 split 每类裁片上限（超则固定种子随机下采样；默认 20000）")
    ap.add_argument("--quality", type=int, default=90,
                    help="JPEG 编码质量（默认 90）")
    ap.add_argument("--workers", type=int, default=12,
                    help="并行 worker 数（默认 12；1 = 单进程）")
    ap.add_argument("--seed", type=int, default=0,
                    help="每类下采样固定种子（默认 0；保证重跑可复现、断点可续）")
    ap.add_argument("--splits", default="train,valid,test",
                    help="处理哪些 split（逗号分隔；默认 train,valid,test）")
    ap.add_argument("--limit-images", type=int, default=0,
                    help="每 split 只处理前 N 张图（0 = 全量；小样本自检用）")
    return ap


# ---------------------------------------------------------------------------
# bbox 取法：直接 bbox → polygon 外接框 → 未压缩 RLE 解码（列主序）
# ---------------------------------------------------------------------------


def _polygon_bbox(seg: list) -> tuple[float, float, float, float] | None:
    """polygon 列表（[[x1,y1,x2,y2,...], ...]）→ 外接框 (x,y,w,h)；空/畸形 → None。"""
    xs: list[float] = []
    ys: list[float] = []
    for part in seg:
        if isinstance(part, (list, tuple)) and len(part) >= 6 and len(part) % 2 == 0:
            xs.extend(float(v) for v in part[0::2])
            ys.extend(float(v) for v in part[1::2])
    if not xs or not ys:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return (x0, y0, x1 - x0, y1 - y0)


def _rle_bbox(seg: dict, w: int, h: int) -> tuple[float, float, float, float] | None:
    """未压缩 RLE dict（{'size':[h,w],'counts':[...]}，列主序）→ 前景外接框。

    与 ``train/_metrics.py`` ``decode_segmentation`` 复用的
    ``beaneye.synth.rle_decode`` 同一约定：列主序，线性下标 k = col*h + row。
    手写实现以守住「零新增依赖」（不引入 pycocotools）；只扫前景 run 的
    端点换算行列，不做全像素展开。
    """
    counts = seg.get("counts")
    size = seg.get("size")
    if not isinstance(counts, list) or not isinstance(size, (list, tuple)):
        return None
    if len(size) != 2 or int(size[0]) != h or int(size[1]) != w:
        return None
    x0, y0 = math.inf, math.inf
    x1, y1 = -math.inf, -math.inf
    idx = 0
    val = 0
    for c in counts:
        c = int(c)
        if c < 0:
            return None
        if val and c:  # 前景 run [idx, idx+c-1]
            a, b = idx, idx + c - 1
            col_a, row_a = divmod(a, h)
            col_b, row_b = divmod(b, h)
            x0 = min(x0, col_a, col_b)
            x1 = max(x1, col_a, col_b)
            if col_a == col_b:
                y0 = min(y0, row_a)
                y1 = max(y1, row_b)
            else:  # 跨列：col_a 段到行底、col_b 段自行顶起，整体覆盖全行范围
                y0 = 0.0
                y1 = float(h - 1)
        idx += c
        val ^= 1
    if x1 < x0:
        return None
    return (float(x0), float(y0), x1 - x0 + 1.0, y1 - y0 + 1.0)


def ann_bbox(ann: dict, w: int, h: int) -> tuple[float, float, float, float] | None:
    """标注 → (x,y,w,h)：直接 bbox 优先；缺失/非正/非有限时回退 segmentation。"""
    bbox = ann.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            x, y, bw, bh = (float(v) for v in bbox)
        except (TypeError, ValueError):
            x, y, bw, bh = math.nan, math.nan, 0.0, 0.0
        if bw > 0 and bh > 0 and all(math.isfinite(v) for v in (x, y, bw, bh)):
            return (x, y, bw, bh)
    seg = ann.get("segmentation")
    if isinstance(seg, list):
        return _polygon_bbox(seg)
    if isinstance(seg, dict):
        return _rle_bbox(seg, w, h)
    return None


# ---------------------------------------------------------------------------
# 真实模式：裁片 worker（重依赖 PIL 只在真实分支导入；dry-run 路径零重依赖）
# ---------------------------------------------------------------------------


def _crop_worker(task: tuple) -> dict:
    """处理一张图：逐任务标注 → pad 外扩 → 裁片 → resize → JPEG 落盘。

    task = (split, img_path, out_split_dir, size, pad_frac, quality,
            [(ann_id, classkey, (x,y,w,h)), ...])
    返回 {"produced": Counter, "existed": Counter, "skipped": int,
          "error": str | None}；同名裁片已存在则跳过（断点续跑）。
    """
    from PIL import Image

    split, img_path, out_split_dir, size, pad_frac, quality, anns = task
    produced: Counter = Counter()
    existed: Counter = Counter()
    skipped = 0
    try:
        img = Image.open(img_path)
        img.load()
    except Exception as exc:  # 缺图/坏图：整图任务计 error，不中断全局
        return {"produced": produced, "existed": existed,
                "skipped": len(anns), "error": f"{img_path}: {exc}"}
    try:
        W, H = img.size
        for ann_id, key, (x, y, bw, bh) in anns:
            dx = bw * pad_frac
            dy = bh * pad_frac
            left = max(0, int(math.floor(x - dx)))
            top = max(0, int(math.floor(y - dy)))
            right = min(W, int(math.ceil(x + bw + dx)))
            bottom = min(H, int(math.ceil(y + bh + dy)))
            if right - left < 1 or bottom - top < 1:
                skipped += 1
                continue
            name = hashlib.sha1(
                f"{split}|{Path(img_path).name}|{ann_id}".encode("utf-8")
            ).hexdigest()[:16]
            dest = Path(out_split_dir) / key / f"{name}.jpg"
            if dest.exists():  # 断点续跑：确定性命名 → 已存在即已完成
                existed[key] += 1
                continue
            crop = img.crop((left, top, right, bottom))
            crop = crop.resize((size, size), Image.BILINEAR)
            crop.save(dest, format="JPEG", quality=quality)
            produced[key] += 1
    except Exception as exc:
        return {"produced": produced, "existed": existed,
                "skipped": len(anns), "error": f"{img_path}: {exc}"}
    return {"produced": produced, "existed": existed, "skipped": 0, "error": None}


# ---------------------------------------------------------------------------
# 真实模式：单 split 处理
# ---------------------------------------------------------------------------


def _load_split_coco(json_path: Path) -> dict:
    """读取并基本校验一个 split 的 COCO json（categories/images/annotations）。"""
    coco = load_json(json_path)
    if not isinstance(coco, dict):
        raise ValueError(f"COCO 根须为对象: {json_path}")
    for key in ("images", "annotations", "categories"):
        if not isinstance(coco.get(key), list):
            raise ValueError(f"COCO 缺 {key} 列表: {json_path}")
    return coco


def _select_tasks(
    split: str,
    coco: dict,
    split_dir: Path,
    out_root: Path,
    args: argparse.Namespace,
) -> tuple[list[tuple], dict, dict, int, int]:
    """标注 → 每类封顶采样 → 按图分组的 worker 任务与计数。

    返回 (tasks, raw_counter, kept_counter, n_dangling, n_images)。
    封顶：每类独立、固定 ``--seed`` 随机下采样（可复现）；
    ``--limit-images`` 只保留前 N 张图（按 json 顺序）的标注，供小样本自检。

    图像定位：v2synth 的 image id 为 top/bottom 对共用，须按
    ``(image_id, side)`` join（见模块 docstring）；对不上的标注计 dangling。
    """
    id2name = {int(c["id"]): str(c["name"]) for c in coco["categories"]}
    imgs: dict[tuple[int, str], dict] = {}
    for im in coco["images"]:
        side = str(im.get("side", ""))
        if not side:
            raise ValueError(
                f"{split}: image 条目缺 side（id={im.get('id')}），"
                "无法按 (image_id, side) 与标注对账"
            )
        key = (int(im["id"]), side)
        if key in imgs:
            raise ValueError(f"{split}: images 存在重复 (id, side)={key}")
        imgs[key] = im

    # 逐类收集 (ann_id, image_key, bbox)；bbox 缺失/退化、图像对不上的标注淘汰
    per_class: dict[int, list[tuple]] = {}
    raw: Counter = Counter()
    dangling = 0
    for ann in coco["annotations"]:
        cid = int(ann["category_id"])
        raw[cid] += 1
        ann_side = str(ann.get("side", ""))
        im = imgs.get((int(ann["image_id"]), ann_side))
        if im is None:
            dangling += 1  # (image_id, side) 对不上：不产出，manifest 如实计数
            continue
        bbox = ann_bbox(ann, int(im["width"]), int(im["height"]))
        if bbox is None:
            continue
        per_class.setdefault(cid, []).append(
            (int(ann["id"]), (int(ann["image_id"]), ann_side), bbox)
        )

    # 每类封顶（0 = 不封顶）：原地洗牌后截断并**写回 per_class[cid]**——
    # 只重绑局部变量会让按图分组拿到未封顶全量（smoke 实测踩坑）
    kept: Counter = Counter()
    for cid, items in per_class.items():
        if args.per_class_cap and len(items) > args.per_class_cap:
            random.Random(args.seed).shuffle(items)
            per_class[cid] = items[: args.per_class_cap]
        kept[cid] = len(per_class[cid])

    # 按图分组（--limit-images 限前 N 张，按 json images 顺序）
    limit = args.limit_images if args.limit_images > 0 else None
    by_img: dict[tuple[int, str], list[tuple]] = {}
    for cid, items in per_class.items():
        for ann_id, img_key, bbox in items:
            by_img.setdefault(img_key, []).append((ann_id, id2name[cid], bbox))

    tasks: list[tuple] = []
    out_split_dir = out_root / split
    ordered_keys = list(imgs.keys())
    if limit is not None:
        ordered_keys = ordered_keys[:limit]
    for img_key in ordered_keys:
        anns = by_img.get(img_key)
        if not anns:
            continue
        im = imgs[img_key]
        tasks.append((
            split,
            str(split_dir / str(im["file_name"])),
            str(out_split_dir),
            args.size,
            args.pad_frac,
            args.quality,
            anns,
        ))
    return tasks, raw, kept, dangling, len(imgs)


def _run_split(split: str, split_dir: Path, out_root: Path,
               args: argparse.Namespace, tax_id2name: dict[int, str]) -> tuple[dict, list[str]]:
    """处理单个 split：解析 → 封顶采样 → 并行裁剪 → 汇总统计。"""
    errors: list[str] = []
    json_path = split_dir / "_annotations.coco.json"
    coco = _load_split_coco(json_path)

    # 类别表与 taxonomy severity_order 对账（id 1..13 ↔ key 顺序一致才继续）
    got = {int(c["id"]): str(c["name"]) for c in coco["categories"]}
    if got != tax_id2name:
        errors.append(
            f"{split}: categories 与 taxonomy severity_order 不一致 got={got}"
        )
        raise ValueError(errors[-1])

    for key in tax_id2name.values():  # 类目录先行建齐（含 0 裁片类，结构完整）
        (out_root / split / key).mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    tasks, raw, kept, dangling, n_images = _select_tasks(
        split, coco, split_dir, out_root, args)
    n_imgs = len(tasks)
    n_anns = sum(len(t[6]) for t in tasks)
    del coco
    gc.collect()
    print(f"[{split}] 标注解析+封顶采样 {time.time()-t0:.1f}s："
          f"{n_images} 图（{n_imgs} 图有标注）/ {n_anns} 标注待裁 "
          f"（raw={sum(raw.values())}, kept={sum(kept.values())}, "
          f"dangling={dangling}）", flush=True)

    produced: Counter = Counter()
    existed: Counter = Counter()
    skipped = 0
    n_missing_imgs = 0
    t0 = time.time()
    done = 0
    if args.workers <= 1:
        results = map(_crop_worker, tasks)
    else:
        ctx = get_context("fork")  # Linux GPU 机；父进程已瘦身，fork 共享任务表
        pool = ctx.Pool(processes=args.workers)
        results = pool.imap_unordered(_crop_worker, tasks, chunksize=8)
    for res in results:
        done += 1
        produced.update(res["produced"])
        existed.update(res["existed"])
        skipped += res["skipped"]
        if res["error"]:
            n_missing_imgs += 1
            if len(errors) < 20:
                errors.append(res["error"])
        if done % 500 == 0 or done == n_imgs:
            rate = done / max(time.time() - t0, 1e-6)
            eta = (n_imgs - done) / max(rate, 1e-6)
            print(f"[{split}] {done}/{n_imgs} 图，新裁 {sum(produced.values())}，"
                  f"{rate:.1f} 图/s，ETA {eta:.0f}s", flush=True)
    if args.workers > 1:
        pool.close()
        pool.join()

    per_class = {}
    for cid, key in tax_id2name.items():
        per_class[key] = {
            "raw": int(raw.get(cid, 0)),
            "kept": int(kept.get(cid, 0)),
            "crops_new": int(produced.get(key, 0)),
            "crops_existed": int(existed.get(key, 0)),
        }
    stats = {
        "images": n_images,
        "images_with_anns": n_imgs,
        "images_missing_or_failed": n_missing_imgs,
        "annotations_raw": int(sum(raw.values())),
        "annotations_kept": int(sum(kept.values())),
        "annotations_dangling": int(dangling),
        "crops_new": int(sum(produced.values())),
        "crops_existed": int(sum(existed.values())),
        "skipped_bad_bbox": int(skipped),
        "seconds": round(time.time() - t0, 1),
        "per_class": per_class,
    }
    return stats, errors


# ---------------------------------------------------------------------------
# dry-run / run / main
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    """纯离线计划打印：路径/参数校验 + 数据集规模引用（不解析大 json）。"""
    rep.header("prepare_crops.py", "单粒豆裁片产出")
    rep.section("输入")
    data_dir = resolve_path(args.data_dir)
    rep.check_dir(data_dir, "数据集根 --data-dir")
    for split in args.splits:
        rep.check_file(data_dir / split / "_annotations.coco.json",
                       f"{split} COCO 标注")
    manifest_path = data_dir / "manifest.json"
    if manifest_path.is_file():  # 规模引用（真实模式以全量解析实测为准）
        try:
            stats = (load_json(manifest_path) or {}).get("stats", {})
            for split in args.splits:
                if split in stats:
                    rep.ok(f"{split} 规模（据数据集 manifest）: "
                           f"{stats[split]['images']} 图 / "
                           f"{stats[split]['annotations']} 标注")
        except (ValueError, FileNotFoundError) as exc:
            rep.warn(f"数据集 manifest.json 读取失败（不影响 dry-run）: {exc}")

    rep.section("类别")
    try:
        tax_cats, _ = build_categories()
        rep.ok(f"taxonomy 类别 {len(tax_cats)} 类（id=severity_order 位次，1 起）: "
               + ",".join(str(c["name"]) for c in tax_cats))
        tax_id2name = {int(c["id"]): str(c["name"]) for c in tax_cats}
    except Exception as exc:  # taxonomy 加载失败属结构性错误
        rep.error(f"taxonomy 加载失败: {exc}")
        return rep.finish()

    rep.section("输出计划")
    out_root = resolve_path(args.out)
    rep.plan(f"输出根 --out: {out_root}（磁盘预算内放 /data；不入库）")
    rep.plan(f"裁片 <split>/<classkey>/<sha1[:16]>.jpg，尺寸 {args.size}²、"
             f"JPEG q{args.quality}、bbox 外扩 {args.pad_frac}")
    rep.plan(f"每类封顶 {args.per_class_cap}（固定种子 {args.seed} 随机下采样，"
             f"normal 等超限类生效；raw/kept 双计数如实入 manifest）")
    rep.plan(f"splits={','.join(args.splits)}，workers={args.workers}，"
             f"limit-images={args.limit_images or '全量'}")
    rep.plan(f"manifest: {out_root / 'manifest.json'}（每 split 每类计数 + 总数）")
    rep.plan("holdout 语义：valid/test 裁片仅评测，永不入训练")
    rep.plan(f"期望类别目录: {len(args.splits)} split × {len(tax_id2name)} 类")
    if args.limit_images:
        rep.plan("小样本自检模式（--limit-images）：产物仅用于链路验证")
    return rep.finish()


def run(args: argparse.Namespace, rep: PlanReporter) -> int:
    """真实模式：逐 split 解析标注 → 封顶采样 → 并行裁剪 → manifest。"""
    try:
        import PIL  # noqa: F401  真实模式可用性预检（缺则开跑前即失败）
    except ImportError as exc:
        print(f"[FAIL] 真实模式需要 Pillow（venv 未装）: {exc}")
        return EXIT_FAILED

    data_dir = resolve_path(args.data_dir)
    out_root = resolve_path(args.out)
    if not data_dir.is_dir():
        print(f"[FAIL] 数据集根不存在: {data_dir}")
        return EXIT_USAGE
    for split in args.splits:
        if not (data_dir / split / "_annotations.coco.json").is_file():
            print(f"[FAIL] 缺 {split} 标注: {data_dir / split / '_annotations.coco.json'}")
            return EXIT_USAGE
    _, tax = build_categories()
    tax_id2name = {i: key for i, key in enumerate(tax.severity_order, start=1)}

    out_root.mkdir(parents=True, exist_ok=True)
    all_errors: list[str] = []
    splits_stats: dict[str, dict] = {}
    t_all = time.time()
    for split in args.splits:
        stats, errors = _run_split(split, data_dir / split, out_root,
                                   args, tax_id2name)
        splits_stats[split] = stats
        all_errors.extend(errors)
        print(f"[{split}] 完成：新裁 {stats['crops_new']}，已存在跳过 "
              f"{stats['crops_existed']}，坏/缺跳过 {stats['skipped_bad_bbox']}，"
              f"失败图 {stats['images_missing_or_failed']}，"
              f"耗时 {stats['seconds']}s", flush=True)

    def _tot(field: str) -> int:
        return int(sum(s[field] for s in splits_stats.values()))

    manifest = {
        "prepared_by": "train/prepare_crops.py (beaneye 训练线)",
        "source_dataset": str(data_dir),
        "args": {
            "size": args.size, "pad_frac": args.pad_frac,
            "per_class_cap": args.per_class_cap, "quality": args.quality,
            "workers": args.workers, "seed": args.seed,
            "splits": list(args.splits), "limit_images": args.limit_images,
        },
        "holdout_note": "valid/test 裁片仅评测，永不入训练（redline）",
        "cap_note": f"per-class-cap={args.per_class_cap} 按 split 独立生效；"
                    f"超限类以 seed={args.seed} 随机下采样",
        "imbalance_note": "normal 在合成集 raw 计数占绝对大头（见各 split "
                          "per_class.raw），未做重采样；加权/采样留给训练侧",
        "splits": splits_stats,
        "totals": {
            "crops_new": _tot("crops_new"),
            "crops_existed": _tot("crops_existed"),
            "annotations_raw": _tot("annotations_raw"),
            "annotations_kept": _tot("annotations_kept"),
            "annotations_dangling": _tot("annotations_dangling"),
            "skipped_bad_bbox": _tot("skipped_bad_bbox"),
            "images_missing_or_failed": _tot("images_missing_or_failed"),
            "seconds": round(time.time() - t_all, 1),
        },
    }
    man_path = save_json(out_root / "manifest.json", manifest)
    print(f"[manifest] {man_path}", flush=True)
    print(f"[总计] 新裁 {manifest['totals']['crops_new']} 张，"
          f"总耗时 {manifest['totals']['seconds']}s", flush=True)

    if all_errors:
        for e in all_errors[:20]:
            print(f"[错误] {e}")
        print(f"[FAIL] 有 {len(all_errors)} 条错误（缺图/坏图等），详见上与 manifest")
        return EXIT_FAILED
    return EXIT_OK


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    if not splits or any(s not in SPLITS for s in splits):
        print(f"[错误] --splits 只能取 {','.join(SPLITS)} 的子集")
        return EXIT_USAGE
    args.splits = splits
    if args.size <= 0 or args.workers <= 0 or args.limit_images < 0:
        print("[错误] --size/--workers 须 >0，--limit-images 须 >=0")
        return EXIT_USAGE
    if not 0.0 <= args.pad_frac <= 1.0:
        print("[错误] --pad-frac 须在 [0,1]")
        return EXIT_USAGE
    if args.per_class_cap < 0:
        print("[错误] --per-class-cap 须 >=0（0 = 不封顶）")
        return EXIT_USAGE
    if not 1 <= args.quality <= 95:
        print("[错误] --quality 须在 [1,95]")
        return EXIT_USAGE
    rep = PlanReporter(dry_run=args.dry_run)
    try:
        if args.dry_run:
            return dry_run(args, rep)
        return run(args, rep)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[FAIL] 输入结构性错误: {exc}")  # JSON 解析失败/类别表不一致等 → 2
        return EXIT_USAGE
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")  # 执行期失败（并行栈等）→ 1
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
