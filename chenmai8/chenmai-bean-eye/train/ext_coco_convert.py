#!/usr/bin/env python3
"""外部公开集 COCO → taxonomy 13 类口径转换（ext_coco_convert）。

把四个外部公开咖啡豆数据集（Roboflow 导出 COCO，类别名为西语/英语原名）
按各集根目录 ``mapping.yaml`` 重写为 taxonomy 13 类口径，输出 **v2synth
同构布局**（``{split}/_annotations.coco.json`` + 同目录图像），供既有
``train/prepare_crops.py`` 直接 ``--data-dir`` 消费——本脚本只做口径转换，
不裁片；裁片一律由 prepare_crops 完成（单一职责）。

对齐 prepare_crops 的两个硬约束（见其 ``_select_tasks``/``_run_split``）：

- image 与 annotation 条目都补 ``side`` 字段（外部集为单面图，统一
  ``"top"``；缺失该字段 prepare_crops 会整 split 报错或全量 dangling）；
- ``categories`` 重写为 taxonomy 全 13 类（id = severity_order 位次 1..13，
  经 ``_common.build_categories``；0 裁片类也保留目录，结构完整）。

映射语义与 ``train/prepare_coco.py`` ``load_category_mapping`` 一致：
顶层键 = 中性来源代号（--code），内层 = {上游类名: taxonomy key | null}；
null 类的标注**丢弃并计数**（不静默）；映射键未覆盖的上游类名属结构性
错误（exit 2），宁可失败也不漏映射。eval_only 数据集（如 ext-rseg：转换
照做、是否入训练等批 5 结论）用 ``--eval-only`` 在 convert_stats.json 里
如实标记，不改变转换行为。

图像落盘默认符号链接（GPU 机 /data 同机软链省盘）；本机无特权环境下
``--link auto`` 依次回退 hardlink → copy，实际方式计数进 stats。仅转换
train/valid 两个 split（test 留作各集原生口径评测）。

输入
    ``--src``：外部集 content 目录（含 {train,valid,test}/_annotations.coco.json）；
    ``--mapping``：mapping.yaml；``--code``：顶层来源代号。

输出
    ``<out>/<split>/_annotations.coco.json`` + 图像（file_name 原名，实测
    各 split 内无重名）+ 根下 ``convert_stats.json``（每 split 每上游类
    kept/dropped、图像去留、链接方式与耗时）。

失败回退
    转换确定性（同输入同名）+ 已存在跳过——中断重跑即断点续跑；缺图
    文件逐条计数，结尾缺失 >0 → exit 1（不静默出假数据集）。

中性名说明：上游数据集专有名不落入本文件（gate_d3 纪律），一律经
``--code`` 代号（ext-main/ext-scaa17/ext-rgreen/ext-rseg）引用；
``--limit-images`` 为小样本自检通道（只转每 split 前 N 张图）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
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

SPLITS = ("train", "valid")  # test 留作各集原生口径，不转换
SIDEBAND = "top"  # 外部集单面图统一 side 标记（prepare_crops 按 (id, side) join）


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="外部集 COCO → taxonomy 13 类口径（v2synth 同构；--dry-run 纯校验）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不写任何产物，只校验映射覆盖并打印逐类计划（exit 0）")
    ap.add_argument("--src", required=True,
                    help="外部集 content 目录（含 {split}/_annotations.coco.json；"
                         "相对路径相对仓库根）")
    ap.add_argument("--mapping", required=True,
                    help="mapping.yaml（顶层键=集代号，内层 {上游类名: taxonomy key|null}）")
    ap.add_argument("--code", required=True,
                    help="来源代号（mapping.yaml 顶层键，如 ext-main）")
    ap.add_argument("--out", required=True,
                    help="转换输出根（v2synth 同构布局；相对路径相对仓库根）")
    ap.add_argument("--eval-only", action="store_true",
                    help="标记 eval_only:true（仅入 convert_stats.json；"
                         "训练是否纳入由批次结论决定，不影响转换）")
    ap.add_argument("--splits", default="train,valid",
                    help=f"处理哪些 split（逗号分隔；仅允许 {','.join(SPLITS)}）")
    ap.add_argument("--link", choices=("auto", "symlink", "hardlink", "copy"),
                    default="auto",
                    help="图像落盘方式（默认 auto：symlink→hardlink→copy 逐级回退）")
    ap.add_argument("--limit-images", type=int, default=0,
                    help="每 split 只转前 N 张图（0 = 全量；小样本自检用）")
    return ap


# ---------------------------------------------------------------------------
# 映射装载与校验（语义对齐 prepare_coco.load_category_mapping，但更严：
# 映射键必须覆盖 json 实际类别全集——漏键属结构性错误而非静默丢弃）
# ---------------------------------------------------------------------------


def load_mapping(mapping_path: Path, code: str, tax_keys: set[str]) -> dict[str, str | None]:
    """mapping.yaml → {上游类名: taxonomy key | None}；目标键非法即抛 ValueError。"""
    import yaml  # 合成配置同款依赖（核心钉版 pyyaml）

    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"映射文件顶层必须是映射: {mapping_path}")
    node = data.get(code)
    if node is None:
        raise ValueError(f"映射文件缺来源键 {code!r}（现有: {sorted(data)}）")
    mapping: dict[str, str | None] = {}
    for k, v in node.items():
        if v is None:
            mapping[str(k)] = None
            continue
        target = str(v)
        if target not in tax_keys:
            raise ValueError(f"映射目标 {target!r} 不是 taxonomy key（上游 {k!r}）")
        mapping[str(k)] = target
    return mapping


def build_cat_map(up_by_id: dict[int, str], mapping: dict[str, str | None],
                  name2taxid: dict[str, int]) -> tuple[dict[int, int], Counter, list[str]]:
    """上游 category_id → taxonomy id；null/缺键处置与逐类丢弃计数。

    返回 (cat_map, dropped_by_upname, unmapped_names)；缺键在此按结构性
    错误抛出（调用方捕获后 exit 2），不静默。
    """
    cat_map: dict[int, int] = {}
    dropped: Counter = Counter()
    unmapped: list[str] = []
    for up_id, up_name in up_by_id.items():
        target = mapping.get(up_name, "__missing__")
        if target == "__missing__":
            unmapped.append(up_name)
            continue
        if target is None:
            dropped[up_name]  # 占位：逐类丢弃数在标注遍历时累加
            continue
        cat_map[up_id] = name2taxid[target]
    return cat_map, dropped, unmapped


# ---------------------------------------------------------------------------
# 图像落盘（symlink → hardlink → copy）
# ---------------------------------------------------------------------------


def place_image(src_file: Path, dst_file: Path, mode: str) -> tuple[str, bool]:
    """把一张图像落到 dst；返回 (实际方式, 已存在跳过)。

    auto 依次回退 symlink → hardlink → copy（Windows 无特权环境 symlink
    会 OSError）；目标已存在即视为断点续跑已完成（确定性命名）。
    """
    if dst_file.exists():
        return ("existed", True)
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    order = {"auto": ("symlink", "hardlink", "copy"),
             "symlink": ("symlink",), "hardlink": ("hardlink",), "copy": ("copy",)}[mode]
    last_exc: Exception | None = None
    for m in order:
        try:
            if m == "symlink":
                os.symlink(src_file.resolve(), dst_file)
            elif m == "hardlink":
                os.link(src_file, dst_file)
            else:
                dst_file.write_bytes(src_file.read_bytes())
            return (m, False)
        except OSError as exc:
            last_exc = exc
    raise RuntimeError(f"图像落盘失败 {dst_file}: {last_exc}")


# ---------------------------------------------------------------------------
# 单 split 转换
# ---------------------------------------------------------------------------


def convert_split(split: str, src_split_dir: Path, out_split_dir: Path,
                  mapping: dict[str, str | None], name2taxid: dict[str, str],
                  args: argparse.Namespace) -> dict:
    """转换单个 split：标注重写 + 图像链接 + 逐类计数。返回 stats dict。"""
    json_path = src_split_dir / "_annotations.coco.json"
    coco = load_json(json_path)
    if not isinstance(coco, dict):
        raise ValueError(f"COCO 根须为对象: {json_path}")
    for key in ("images", "annotations", "categories"):
        if not isinstance(coco.get(key), list):
            raise ValueError(f"COCO 缺 {key} 列表: {json_path}")

    up_by_id = {int(c["id"]): str(c.get("name", c["id"])) for c in coco["categories"]}
    cat_map, _, unmapped = build_cat_map(up_by_id, mapping, name2taxid)
    if unmapped:
        raise ValueError(
            f"{split}: 映射键未覆盖上游类别 {sorted(unmapped)}（宁可失败不漏映射；"
            f"请补 {args.mapping} [{args.code}] 后重跑）"
        )

    # --limit-images：按 json 顺序只保留前 N 张图（小样本自检）
    images = coco["images"]
    if args.limit_images > 0:
        images = images[: args.limit_images]
    keep_img_ids = {int(im["id"]) for im in images}
    img_ids_seen: set[int] = set()
    for im in images:
        iid = int(im["id"])
        if iid in img_ids_seen:
            raise ValueError(f"{split}: images 存在重复 id={iid}")
        img_ids_seen.add(iid)

    # 标注重写：null 类丢弃计数；图像缺文件计数；无存活标注的图像不产出
    kept_anns: list[dict] = []
    kept_img_ids: set[int] = set()
    ann_raw = Counter()
    ann_kept = Counter()
    ann_dropped = Counter()
    n_missing_file = 0
    for ann in coco["annotations"]:
        if int(ann["image_id"]) not in keep_img_ids:
            continue  # --limit-images 截掉的图的标注（不计入 raw 统计）
        up_name = up_by_id.get(int(ann["category_id"]))
        ann_raw[up_name] += 1
        tax_id = cat_map.get(int(ann["category_id"]))
        if tax_id is None:
            ann_dropped[up_name] += 1
            continue
        if int(ann["image_id"]) not in img_ids_seen:
            continue  # 悬挂标注（指向不存在图像）：不产出，计数
        kept_anns.append({
            **ann,
            "category_id": tax_id,
            "side": SIDEBAND,  # prepare_crops 按 (image_id, side) join
        })
        ann_kept[up_name] += 1
        kept_img_ids.add(int(ann["image_id"]))

    # 图像落盘 + 条目重写（补 side；无存活标注的图像不产出并计数）
    link_mode_count: Counter = Counter()
    out_images: list[dict] = []
    n_no_ann_img = 0
    for im in images:
        iid = int(im["id"])
        if iid not in kept_img_ids:
            n_no_ann_img += 1
            continue
        fname = str(im["file_name"])
        src_file = src_split_dir / fname
        if not src_file.is_file():
            n_missing_file += 1
            continue
        actual, _ = place_image(src_file, out_split_dir / fname, args.link)
        link_mode_count[actual] += 1
        out_images.append({**im, "side": SIDEBAND})

    # 类别表重写为 taxonomy 全 13 类（0 裁片类也保留，结构完整）
    tax_cats, _ = build_categories()

    out_coco = {
        "info": coco.get("info", {"description": f"{args.code} {split} → taxonomy 13 类"}),
        "images": out_images,
        "annotations": kept_anns,
        "categories": tax_cats,
    }
    if not args.dry_run:
        save_json(out_split_dir / "_annotations.coco.json", out_coco)

    def _per_class() -> dict:
        rows = {}
        for name in sorted(set(up_by_id.values())):
            rows[name] = {
                "raw": int(ann_raw.get(name, 0)),
                "kept": int(ann_kept.get(name, 0)),
                "dropped": int(ann_dropped.get(name, 0)),
            }
        return rows

    return {
        "images_src": len(images),
        "images_kept": len(out_images),
        "images_no_kept_ann": n_no_ann_img,
        "images_missing_file": n_missing_file,
        "anns_src": int(sum(ann_raw.values())),
        "anns_kept": int(sum(ann_kept.values())),
        "anns_dropped": int(sum(ann_dropped.values())),
        "link_modes": {k: int(v) for k, v in link_mode_count.items()},
        "per_upstream_class": _per_class(),
    }


# ---------------------------------------------------------------------------
# dry-run / run / main
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    """纯离线校验：路径/映射覆盖检查 + 逐类计划打印（不写产物）。"""
    rep.header("ext_coco_convert.py", "外部集 COCO → taxonomy 13 类")
    rep.section("输入")
    src_dir = resolve_path(args.src)
    rep.check_dir(src_dir, "外部集 content 目录 --src")
    mapping_path = resolve_path(args.mapping)
    rep.check_file(mapping_path, "映射文件 --mapping")

    tax_cats, _ = build_categories()
    tax_keys = {str(c["name"]) for c in tax_cats}
    name2taxid = {str(c["name"]): int(c["id"]) for c in tax_cats}
    rep.ok(f"taxonomy {len(tax_keys)} 类（id=severity_order 位次，1 起）: "
           + ",".join(sorted(tax_keys, key=lambda k: name2taxid[k])))

    try:
        mapping = load_mapping(mapping_path, args.code, tax_keys)
        rep.ok(f"映射 [{args.code}]: {len(mapping)} 键"
               f"（null {sum(1 for v in mapping.values() if v is None)} 类）")
    except ValueError as exc:
        rep.error(str(exc))
        return rep.finish()

    rep.section("逐 split 计划")
    out_root = resolve_path(args.out)
    for split in args.splits:
        json_path = src_dir / split / "_annotations.coco.json"
        if not rep.check_file(json_path, f"{split} COCO 标注"):
            continue
        try:
            coco = load_json(json_path)
            up_by_id = {int(c["id"]): str(c.get("name", c["id"]))
                        for c in coco["categories"]}
            cat_map, _, unmapped = build_cat_map(up_by_id, mapping, name2taxid)
            if unmapped:
                rep.error(f"{split}: 映射键未覆盖上游类别 {sorted(unmapped)}")
                continue
            kept = dropped = 0
            for ann in coco["annotations"]:
                if int(ann["category_id"]) in cat_map:
                    kept += 1
                else:
                    dropped += 1
            rep.ok(f"{split}: {len(coco['images'])} 图 / {kept + dropped} 标注 → "
                   f"保留 {kept}、丢弃 {dropped}（null/容器类）→ {out_root / split}")
            for name in sorted(up_by_id.values()):
                mark = mapping.get(name)
                rep.plan(f"  {name!r} → {mark or 'null(丢弃)'}")
        except ValueError as exc:
            rep.error(str(exc))

    rep.section("输出计划")
    rep.plan(f"输出根 --out: {out_root}（v2synth 同构；图像 --link {args.link}）")
    rep.plan(f"image/annotation 补 side={SIDEBAND!r}；categories 重写 taxonomy 全 13 类")
    rep.plan(f"stats: {out_root / 'convert_stats.json'}（逐类 kept/dropped、链接方式）")
    rep.plan(f"eval_only={args.eval_only}；splits={','.join(args.splits)}；"
             f"limit-images={args.limit_images or '全量'}")
    rep.plan("test split 留作各集原生口径，不转换")
    return rep.finish()


def run(args: argparse.Namespace, rep: PlanReporter) -> int:
    """真实模式：逐 split 转换 → convert_stats.json。"""
    src_dir = resolve_path(args.src)
    out_root = resolve_path(args.out)
    mapping_path = resolve_path(args.mapping)
    if not src_dir.is_dir():
        print(f"[FAIL] 外部集 content 目录不存在: {src_dir}")
        return EXIT_USAGE
    if not mapping_path.is_file():
        print(f"[FAIL] 映射文件不存在: {mapping_path}")
        return EXIT_USAGE

    tax_cats, _ = build_categories()
    tax_keys = {str(c["name"]) for c in tax_cats}
    name2taxid = {str(c["name"]): int(c["id"]) for c in tax_cats}
    try:
        mapping = load_mapping(mapping_path, args.code, tax_keys)
    except ValueError as exc:
        print(f"[FAIL] {exc}")
        return EXIT_USAGE

    out_root.mkdir(parents=True, exist_ok=True)
    splits_stats: dict[str, dict] = {}
    t_all = time.time()
    for split in args.splits:
        src_split_dir = src_dir / split
        if not (src_split_dir / "_annotations.coco.json").is_file():
            print(f"[FAIL] 缺 {split} 标注: {src_split_dir / '_annotations.coco.json'}")
            return EXIT_USAGE
        out_split_dir = out_root / split
        out_split_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        stats = convert_split(split, src_split_dir, out_split_dir,
                              mapping, name2taxid, args)
        stats["seconds"] = round(time.time() - t0, 1)
        splits_stats[split] = stats
        print(f"[{split}] 保留图 {stats['images_kept']}/{stats['images_src']}"
              f"（无存活标注 {stats['images_no_kept_ann']}、缺文件 "
              f"{stats['images_missing_file']}），标注 {stats['anns_kept']}/"
              f"{stats['anns_src']}（丢弃 {stats['anns_dropped']}），"
              f"链接 {stats['link_modes']}，{stats['seconds']}s", flush=True)

    n_missing = int(sum(s["images_missing_file"] for s in splits_stats.values()))
    stats_doc = {
        "converted_by": "train/ext_coco_convert.py (beaneye 训练线)",
        "code": args.code,
        "src": str(src_dir),
        "mapping": str(mapping_path),
        "eval_only": bool(args.eval_only),
        "link_arg": args.link,
        "limit_images": args.limit_images,
        "splits": splits_stats,
        "totals": {
            "anns_src": int(sum(s["anns_src"] for s in splits_stats.values())),
            "anns_kept": int(sum(s["anns_kept"] for s in splits_stats.values())),
            "anns_dropped": int(sum(s["anns_dropped"] for s in splits_stats.values())),
            "images_kept": int(sum(s["images_kept"] for s in splits_stats.values())),
            "images_missing_file": n_missing,
            "seconds": round(time.time() - t_all, 1),
        },
    }
    stats_path = save_json(out_root / "convert_stats.json", stats_doc)
    print(f"[stats] {stats_path}", flush=True)
    print(f"[总计] 标注保留 {stats_doc['totals']['anns_kept']}/"
          f"{stats_doc['totals']['anns_src']}（丢弃 {stats_doc['totals']['anns_dropped']}），"
          f"耗时 {stats_doc['totals']['seconds']}s", flush=True)

    if n_missing > 0:
        print(f"[FAIL] {n_missing} 张源图缺失（不静默出假数据集），详见 convert_stats.json")
        return EXIT_FAILED
    return EXIT_OK


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    splits = [s.strip() for s in args.splits.split(",") if s.strip()]
    if not splits or any(s not in SPLITS for s in splits):
        print(f"[错误] --splits 只能取 {','.join(SPLITS)}（test 留作原生口径）")
        return EXIT_USAGE
    args.splits = splits
    if args.limit_images < 0:
        print("[错误] --limit-images 须 >=0")
        return EXIT_USAGE
    rep = PlanReporter(dry_run=args.dry_run)
    try:
        if args.dry_run:
            return dry_run(args, rep)
        return run(args, rep)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[FAIL] 输入结构性错误: {exc}")  # 映射缺键/JSON 解析失败等 → 2
        return EXIT_USAGE
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")  # 执行期失败（落盘等）→ 1
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
