"""勺上分类器：帧数据导出/自动标注（training-plan §3；只写不跑的延后资产）。

职责：把 ScriptedScoop 运行帧目录（episode 布局）转换成训练用清单——
自动标注（舀取完成帧→has_food=1、咬合结束帧→has_food=0，各取前后
±context_frames 帧）、模糊帧剔除（可选解码检查）、按**回合**切分
train/val/test=70/15/15（防同回合泄漏）。

Episode 输入布局（--episodes-root）::

    <root>/<episode_id>/events.json   # {"frames": ["f000001.png", ...],
                                      #  "scoop_done": [idx, ...],
                                      #  "bite_end": [idx, ...]}
    <root>/<episode_id>/f*.png        # 腕部相机帧（--decode 时才读取）

输出（--out，缺省 data/spoon_cls/dataset，仓库相对）::

    index.csv    # split,episode_id,frame,label（label: 1=has_food, 0=empty）
    split.json   # 各 split 的 episode_id 列表（可审计切分）
    manifest.json# 生成参数与计数

用法（仓库根）::

    python -m chengshao.training.spoon_cls.prepare_data \
        --episodes-root data/spoon_cls/raw --out data/spoon_cls/dataset --write
    # 缺省 dry-run：校验布局并打印计划，不写任何文件

退出码：0=成功；1=阈值/规模未达（min_frames_total 只提示不判失败，见
config/spoon_cls.json 的 note）；2=参数/布局/配置错误。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chengshao.training.common import (  # noqa: E402
    ConfigError,
    dump_json,
    fail,
    load_json,
    safe_rel_output,
    utc_now_iso,
)

_MODULE = "training.spoon_cls.prepare_data"
LABEL_POS, LABEL_NEG = 1, 0
SPLIT_ORDER = ("train", "val", "test")


def load_events(episode_dir: Path) -> dict[str, Any]:
    path = episode_dir / "events.json"
    if not path.is_file():
        raise ConfigError(f"episode 缺 events.json：{episode_dir}")
    ev = load_json(path)
    frames = ev.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ConfigError(f"{path}: frames 必须为非空列表")
    for key in ("scoop_done", "bite_end"):
        v = ev.get(key, [])
        if not isinstance(v, list) or any(not isinstance(x, int) for x in v):
            raise ConfigError(f"{path}: {key} 必须为整数下标列表")
        if any(x < 0 or x >= len(frames) for x in v):
            raise ConfigError(f"{path}: {key} 下标越界")
    if len(set(ev.get("scoop_done", [])) & set(ev.get("bite_end", []))) != 0:
        raise ConfigError(f"{path}: 同一帧不得同时标 scoop_done 与 bite_end")
    return ev


def auto_label(ev: dict[str, Any], context_frames: int) -> list[tuple[int, int]]:
    """自动标注：事件帧 ± context_frames 取窗；同帧双标已在 load_events 拒绝。"""
    labels: dict[int, int] = {}
    for idx in ev.get("scoop_done", []):
        for k in range(max(0, idx - context_frames), idx + context_frames + 1):
            if 0 <= k < len(ev["frames"]):
                labels[k] = LABEL_POS
    for idx in ev.get("bite_end", []):
        for k in range(max(0, idx - context_frames), idx + context_frames + 1):
            if 0 <= k < len(ev["frames"]):
                labels.setdefault(k, LABEL_NEG)  # 已标正者不覆盖（宁可重舀的偏置语义）
    return sorted(labels.items())


def episode_split(episode_ids: list[str], ratios: list[float],
                  seed: int) -> dict[str, list[str]]:
    """按回合确定性切分（id 哈希 + seed 洗牌；无泄漏：同回合只进一个 split）。"""
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ConfigError(f"split 比例之和必须为 1：{ratios}")
    ids = sorted(episode_ids)
    # 确定性洗牌：以 seed+id 哈希为键排序（不依赖解释器内建 hash 的随机化）
    ids.sort(key=lambda e: hashlib.sha256(f"{seed}:{e}".encode("utf-8")).hexdigest())
    n = len(ids)
    n_train = round(ratios[0] * n)
    n_val = round(ratios[1] * n)
    return {
        "train": ids[:n_train],
        "val": ids[n_train:n_train + n_val],
        "test": ids[n_train + n_val:],
    }


def build_items(episodes_root: Path, context_frames: int,
                decode: bool, blur_var_min: float) -> tuple[list[dict], list[str], list[str]]:
    """扫描全部 episode，产出 (items, dropped_blur, warnings)。"""
    if not episodes_root.is_dir():
        raise ConfigError(f"--episodes-root 不存在：{episodes_root}")
    items: list[dict] = []
    dropped_blur: list[str] = []
    warnings: list[str] = []
    episode_dirs = sorted(d for d in episodes_root.iterdir() if d.is_dir())
    if not episode_dirs:
        raise ConfigError(f"--episodes-root 下没有 episode 目录：{episodes_root}")
    for edir in episode_dirs:
        ev = load_events(edir)
        for idx, label in auto_label(ev, context_frames):
            frame = ev["frames"][idx]
            fpath = edir / frame
            if decode:
                import numpy as np

                from chengshao.cs_mouth.imgio import imread_u  # 中文路径安全读取

                img = imread_u(fpath)
                if img is None:
                    warnings.append(f"{edir.name}/{frame}: 读取失败，已剔除")
                    continue
                gray = img if img.ndim == 2 else np.mean(img, axis=2)
                if cv2_laplacian_var(gray) < blur_var_min:
                    dropped_blur.append(f"{edir.name}/{frame}")
                    continue
            items.append({"episode_id": edir.name, "frame": frame, "label": label})
    return items, dropped_blur, warnings


def cv2_laplacian_var(gray) -> float:
    import cv2

    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def write_outputs(out_dir: Path, items: list[dict], splits: dict[str, list[str]],
                  params: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    split_of = {e: s for s, eps in splits.items() for e in eps}
    with open(out_dir / "index.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["split", "episode_id", "frame", "label"])
        for it in items:
            w.writerow([split_of[it["episode_id"]], it["episode_id"],
                        it["frame"], it["label"]])
    dump_json(out_dir / "split.json", {"splits": splits})
    dump_json(out_dir / "manifest.json", params)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.spoon_cls.prepare_data",
        description="勺上分类器帧数据导出/自动标注（dry-run 缺省；--write 才落盘）")
    parser.add_argument("--episodes-root", type=Path, required=True,
                        help="episode 布局的原始帧根目录")
    parser.add_argument("--out", type=Path, default=None,
                        help="输出数据集目录（仓库相对；缺省 data/spoon_cls/dataset）")
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).resolve().parents[1] / "config" / "spoon_cls.json")
    parser.add_argument("--decode", action="store_true",
                        help="读取图像做模糊剔除（缺省只按清单产出，不碰图像）")
    parser.add_argument("--write", action="store_true",
                        help="实际写出 index/split/manifest（缺省 dry-run 只打印计划）")
    parser.add_argument("--report", type=Path, default=None,
                        help="§10.2 证据报告输出路径（配合 --write）")
    args = parser.parse_args(argv)

    try:
        cfg = load_json(args.config)
        context = int(cfg["data"]["context_frames"])
        blur_var_min = float(cfg["data"]["blur_drop_var"])
        ratios = [float(v) for v in cfg["data"]["split"]]
        seed = int(cfg["data"]["split_seed"])
        min_frames = int(cfg["data"]["min_frames_total"])
        out_dir = safe_rel_output(
            str(args.out) if args.out else "data/spoon_cls/dataset",
            field="--out")
    except (ConfigError, KeyError, TypeError, ValueError) as exc:
        fail(f"配置装载失败：{exc}")

    try:
        items, dropped, warnings = build_items(args.episodes_root, context,
                                               args.decode, blur_var_min)
        splits = episode_split(sorted({it["episode_id"] for it in items}),
                               ratios, seed)
    except ConfigError as exc:
        fail(str(exc))

    counts = {s: sum(1 for it in items
                     if it["episode_id"] in set(splits[s])) for s in SPLIT_ORDER}
    pos = sum(1 for it in items if it["label"] == LABEL_POS)
    plan = {
        "episodes": len(splits["train"]) + len(splits["val"]) + len(splits["test"]),
        "episodes_by_split": {s: len(splits[s]) for s in SPLIT_ORDER},
        "labeled_frames": len(items),
        "frames_by_split": counts,
        "positive_ratio": round(pos / len(items), 4) if items else None,
        "dropped_blur": len(dropped),
        "warnings": warnings[:20],
        "min_frames_total_target": min_frames,
        "meets_target": len(items) >= min_frames,
        "write": bool(args.write),
        "out_dir": str(out_dir),
    }
    print("PLAN:", plan if not args.write else "(writing)")
    if args.write:
        write_outputs(out_dir, items, splits, {
            "module": _MODULE, "date": utc_now_iso(),
            "context_frames": context, "blur_drop_var": blur_var_min,
            "split": ratios, "split_seed": seed, "decode": bool(args.decode),
            "dropped_blur": dropped[:200], **plan,
        })
        print(f"WROTE: {out_dir}")
        if args.report is not None:
            from chengshao.training.common import write_report

            write_report(args.report, module=_MODULE,
                         cmd="python -m chengshao.training.spoon_cls.prepare_data --write",
                         metrics=plan,
                         thresholds={"min_frames_total": min_frames,
                                     "note": "min_frames_total 为目标值非硬线"},
                         passed=True)
            print(f"REPORT: {args.report}")
    else:
        print("NOTE: dry-run 未写任何文件；确认计划后加 --write 落盘。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
