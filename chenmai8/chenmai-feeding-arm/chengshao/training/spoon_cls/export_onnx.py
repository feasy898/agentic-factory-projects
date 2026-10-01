"""勺上分类器 ONNX 导出（training-plan §3；延后资产）。

把训练好的 checkpoint（state_dict）导出为 ONNX，供运行期以
onnxruntime 无感替换 cs_food 的启发式勺检（``SpoonClassifier`` 接口冻结）。

- 缺省 dry-run：校验参数与计划（算子集/输入形状/opset），不 import torch、
  不读 checkpoint 内容；
- 实际导出（无 --dry-run）：要求 checkpoint 文件存在且本环境装有 torch；
  导出参数记录进 §10.2 报告。

退出码：0=成功；2=参数/环境错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chengshao.training.common import fail, load_json, safe_rel_output, utc_now_iso  # noqa: E402

_MODULE = "training.spoon_cls.export_onnx"
OPSET = 17


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.spoon_cls.export_onnx",
        description="checkpoint -> ONNX（dry-run 缺省）")
    parser.add_argument("--checkpoint", type=Path, required=True,
                        help="训练产物 state_dict（.pt）")
    parser.add_argument("--out", type=Path, default=None,
                        help="输出 .onnx 路径（仓库相对；缺省 data/runs/spoon_cls_v1/spoon_cls.onnx）")
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).resolve().parents[1] / "config" / "spoon_cls.json")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划（缺省即 dry-run）")
    parser.add_argument("--report", type=Path, default=None, help="§10.2 报告输出路径")
    args = parser.parse_args(argv)

    if not args.dry_run and not args.checkpoint.is_file():
        fail(f"checkpoint 不存在：{args.checkpoint}（仅打印计划请加 --dry-run）")
    try:
        cfg = load_json(args.config)
        out_path = safe_rel_output(
            str(args.out) if args.out else "data/runs/spoon_cls_v1/spoon_cls.onnx",
            field="--out")
    except Exception as exc:  # noqa: BLE001
        fail(f"配置/参数错误：{exc}")

    m = cfg["model"]
    plan = {
        "checkpoint": str(args.checkpoint),
        "out": str(out_path),
        "input_shape": ["batch", 3, m["input_size"], m["input_size"]],
        "outputs": ["food_prob(sigmoid)"],
        "opset": OPSET,
        "dynamic_axes": {"input": {0: "batch"}, "food_prob": {0: "batch"}},
        "note": "输出为 has_food 概率；运行期判定阈值取 config/spoon_cls.json thresholds.decision_threshold",
    }
    if args.dry_run:
        print("PLAN:", plan)
        print(f"NOTE: dry-run @ {utc_now_iso()}；实际导出需 checkpoint + torch 环境。")
    else:
        try:
            import torch

            from chengshao.training.spoon_cls.model import build_model

            model = build_model(cfg)
            state = torch.load(args.checkpoint, map_location="cpu")
            model.load_state_dict(state["model"] if isinstance(state, dict) and "model" in state
                                  else state)
            model.eval()
            dummy = torch.randn(1, 3, m["input_size"], m["input_size"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            torch.onnx.export(
                model, dummy, str(out_path), opset_version=OPSET, input_names=["input"],
                output_names=["food_prob"], dynamic_axes={
                    "input": {0: "batch"}, "food_prob": {0: "batch"}},
            )
            print(f"EXPORTED: {out_path}")
        except ImportError:
            fail("未安装 torch——导出环境见 chengshao/training/requirements-gpu.txt")
        except Exception as exc:  # noqa: BLE001
            fail(f"导出失败：{type(exc).__name__}: {exc}")
    if args.report is not None:
        from chengshao.training.common import write_report

        write_report(args.report, module=_MODULE,
                     cmd="python -m chengshao.training.spoon_cls.export_onnx",
                     metrics=plan, thresholds={"opset": OPSET}, passed=True)
        print(f"REPORT: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
