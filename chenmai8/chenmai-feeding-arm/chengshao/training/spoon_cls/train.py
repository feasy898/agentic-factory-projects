"""勺上分类器训练入口（training-plan §3；延后资产，本机**禁止**真实训练）。

模型：MobileNetV3-Small（torchvision 预训练干）+ 2 层 MLP 头，输入 224×224，
CE loss + 色彩抖动；判定阈值向 has_food 偏置（漏检比误检严重）。

纪律（开发指令 §10.3）：
- 缺省 **dry-run**：校验配置与数据集清单、输出训练计划（步数/参数量/预计
  时长），不 import torch、不碰数据；
- ``--execute`` 需同时满足：环境变量 ``CS_ALLOW_TRAIN=1``（人工放行真实
  训练）且 CUDA 可用——本机（windev-01，无 GPU）两者皆无，天然拒绝，
  exit 2；真实训练只允许在 GPU 机执行。

退出码：0=计划/执行成功；1=训练完成但阈值未达；2=参数/环境/纪律拒绝。
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chengshao.training.common import (  # noqa: E402
    ConfigError,
    fail,
    load_json,
    safe_rel_output,
    utc_now_iso,
)

_MODULE = "training.spoon_cls.train"


def load_index(dataset_dir: Path) -> dict[str, Any]:
    index = dataset_dir / "index.csv"
    split = dataset_dir / "split.json"
    if not index.is_file() or not split.is_file():
        raise ConfigError(f"数据集目录缺 index.csv/split.json（先跑 prepare_data）：{dataset_dir}")
    rows = index.read_text(encoding="utf-8").strip().splitlines()
    if not rows or rows[0] != "split,episode_id,frame,label":
        raise ConfigError(f"index.csv 表头不符：{index}")
    per_split: dict[str, int] = {}
    pos_by_split: dict[str, int] = {}
    for line in rows[1:]:
        s = line.split(",")[0]
        per_split[s] = per_split.get(s, 0) + 1
        if line.endswith(",1"):
            pos_by_split[s] = pos_by_split.get(s, 0) + 1
    if not per_split.get("train"):
        raise ConfigError("index.csv 无 train 样本")
    return {"rows": len(rows) - 1, "per_split": per_split, "pos_by_split": pos_by_split}


def plan_training(cfg: dict[str, Any], index_info: dict[str, Any]) -> dict[str, Any]:
    """由配置+清单算训练计划（不 import torch）。"""
    model_cfg, train_cfg = cfg["model"], cfg["train"]
    n_train = index_info["per_split"].get("train", 0)
    batch = int(train_cfg["batch_size"])
    epochs = int(train_cfg["epochs"])
    steps_per_epoch = max(1, math.ceil(n_train / batch))
    return {
        "model": {
            "backbone": model_cfg["backbone"],
            "pretrained": bool(model_cfg["pretrained"]),
            "head_hidden": model_cfg["head_hidden"],
            "input_size": model_cfg["input_size"],
            "dropout": model_cfg["dropout"],
            "approx_params_m": round(2.7 + model_cfg["head_hidden"] * 2 * 0.0006, 2),
        },
        "train": {
            "batch_size": batch, "epochs": epochs, "lr": train_cfg["lr"],
            "weight_decay": train_cfg["weight_decay"], "amp": train_cfg["amp"],
            "steps_total": steps_per_epoch * epochs,
            "steps_per_epoch": steps_per_epoch,
        },
        "data": index_info["per_split"],
        "positive_ratio_train": round(
            index_info["pos_by_split"].get("train", 0) / max(1, n_train), 4),
        "decision_threshold": cfg["thresholds"]["decision_threshold"],
        "est_gpu_hours": round(steps_per_epoch * epochs * 0.02 / 3600, 4),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.spoon_cls.train",
        description="勺上分类器训练（dry-run 缺省；--execute 只允许 GPU 机 + 人工放行）")
    parser.add_argument("--dataset", type=Path, default=None,
                        help="prepare_data 产物目录（仓库相对；缺省 data/spoon_cls/dataset）")
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).resolve().parents[1] / "config" / "spoon_cls.json")
    parser.add_argument("--output", type=Path, default=None,
                        help="checkpoint 输出目录（仓库相对；缺省 data/runs/spoon_cls_v1）")
    parser.add_argument("--execute", action="store_true",
                        help="真实训练（需 CS_ALLOW_TRAIN=1 + CUDA；本机禁止）")
    parser.add_argument("--report", type=Path, default=None, help="§10.2 报告输出路径")
    args = parser.parse_args(argv)

    if args.execute:
        import os

        if os.environ.get("CS_ALLOW_TRAIN") != "1":
            print("[training] 拒绝：真实训练需人工放行（CS_ALLOW_TRAIN=1），"
                  "且只允许在 GPU 机执行（开发指令 §10.3）。本机只做 dry-run。",
                  file=sys.stderr)
            return 2
        try:
            import torch

            if not torch.cuda.is_available():
                fail("CS_ALLOW_TRAIN=1 但无 CUDA——真实训练只允许在 GPU 机执行")
        except ImportError:
            fail("未安装 torch——真实训练环境见 chengshao/training/requirements-gpu.txt")
        fail("--execute 的真实训练循环属延后资产：本仓库版本只交付到"
             "「环境/纪律门 + 计划生成」，训练循环在 GPU 机按 runbook_gpu.md 执行")
    # ---- dry-run（缺省）----
    try:
        cfg = load_json(args.config)
        dataset_dir = safe_rel_output(
            str(args.dataset) if args.dataset else "data/spoon_cls/dataset",
            field="--dataset")
        output_dir = safe_rel_output(
            str(args.output) if args.output else "data/runs/spoon_cls_v1",
            field="--output")
        index_info = load_index(dataset_dir)
        plan = plan_training(cfg, index_info)
    except ConfigError as exc:
        fail(str(exc))
    plan["output_dir"] = str(output_dir)
    print("PLAN:", plan)
    if args.report is not None:
        from chengshao.training.common import write_report

        write_report(args.report, module=_MODULE,
                     cmd="python -m chengshao.training.spoon_cls.train (dry-run)",
                     metrics=plan,
                     thresholds={"execute_policy": "GPU 机 + CS_ALLOW_TRAIN=1"},
                     passed=True)
        print(f"REPORT: {args.report}")
    print(f"NOTE: dry-run @ {utc_now_iso()}；真实训练在 GPU 机（runbook_gpu.md）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
