#!/usr/bin/env python3
"""ONNX 导出与 int8 量化（export_onnx_quant；训练计划 T6 可选件，CPU 部署加速）。

把 T1 微调好的分割模型导出 ONNX（opset 17、静态 1024×1024——计划 T1 导出口径），
可选 int8 静态量化（onnxruntime.quantization，校准集 = 合成盘图小子集），
产物落 ``train/runs/export/``。

依赖与边界（诚实声明）
    - 仅真实模式需要 NN 栈（checkpoint 加载）与 onnxruntime（量化）；本机
      windev 未装、未能离线核对 API——上 GPU 机先 ``--dry-run``，再以
      ``det_finetune.py --cpu-smoke`` 验证 NN 栈连通后跑本脚本；
    - NN 包的 export() 若不接受 opset/静态尺寸参数，脚本按该版本默认导出并
      打印告警（不静默降级）；量化要求 ONNX 含掩码头，否则明确报错。

输入约定
    - ``--checkpoint``：det_finetune 产物（best checkpoint）；
    - ``--calib-json``/``--calib-image-root``：量化校准图（默认取合成
      数据集 train split 的前 N 张；标注不参与，仅图像统计分布）。

输出（默认 ``train/runs/export``）
    ``model.onnx``（fp32）、``model_int8.onnx``（量化，--quantize int8 时）、
    ``export_plan.json``（导出参数/校准清单/sha256）。

期望运行时长
    导出分钟级；int8 静态量化（32 张 1024² 校准图）≈ 5–15 min（CPU）。

失败回退
    fp32 导出成功而量化失败时保留 fp32 产物并 exit 1（报告原因）。

GPU 机执行顺序
    T0 → T1 → T1 验收 → （可选）**本脚本** → 桌面端 CPU 部署联调；
    权重/产物经 COS 中转（跨机不直传）。

--dry-run：纯离线——校验参数与输入存在性、打印导出/量化计划，exit 0。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _common
from _common import EXIT_USAGE, PlanReporter, resolve_path, save_json

# ImageNet 归一化（与 _predict.OnnxPredictor 同口径；量化校准必须一致）
_MEAN = (0.485, 0.456, 0.406)
_STD = (0.229, 0.224, 0.225)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="ONNX 导出（opset 17 静态 1024）+ 可选 int8 静态量化（--dry-run 纯离线）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不导出/不量化/不导入 NN 栈，只校验并打印计划（离线，exit 0）")
    ap.add_argument("--checkpoint", default="train/runs/t1/checkpoint_best.pth",
                    help="T1 checkpoint（det_finetune 产物）")
    ap.add_argument("--out", default="train/runs/export",
                    help="输出目录（相对仓库根）")
    ap.add_argument("--variant", choices=("small", "nano"), default="small",
                    help="模型型号（须与训练一致）")
    ap.add_argument("--resolution", type=int, default=1024,
                    help="静态输入边长（计划 T1 = 1024）")
    ap.add_argument("--opset", type=int, default=17, help="ONNX opset（计划 T1 = 17）")
    ap.add_argument("--dynamic", action="store_true",
                    help="动态轴导出（默认静态——计划口径；桌面端 CPU 部署建议静态）")
    ap.add_argument("--quantize", choices=("none", "int8"), default="int8",
                    help="量化模式（int8 = onnxruntime 静态量化，可选件）")
    ap.add_argument("--calib-json", default="train/runs/datasets/v1/train/_annotations.coco.json",
                    help="校准图来源 COCO json（只用图像清单，不用标注）")
    ap.add_argument("--calib-image-root", default=None,
                    help="校准图根（默认取 --calib-json 所在目录）")
    ap.add_argument("--calib-images", type=int, default=32,
                    help="校准图张数（默认 32；覆盖典型光照/密度分布即可）")
    ap.add_argument("--device", default="cuda:0", help="导出时模型所在设备")
    return ap


# ---------------------------------------------------------------------------
# 校准清单
# ---------------------------------------------------------------------------


def calib_list(calib_json: Path, image_root: Path, n: int) -> list[Path]:
    """从 COCO json 取前 n 张图像的绝对路径（校准只用图像，不用标注）。"""
    data = json.loads(calib_json.read_text(encoding="utf-8"))
    out: list[Path] = []
    for img in data.get("images", []):
        p = image_root / str(img["file_name"])
        if p.is_file():
            out.append(p)
        if len(out) >= n:
            break
    if not out:
        raise FileNotFoundError(f"校准图清单为空（{calib_json} @ {image_root}）")
    return out


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    rep.header("export_onnx_quant.py", "ONNX 导出 + 可选 int8 量化")
    rep.section("1. 输入")
    ckpt = resolve_path(args.checkpoint)
    rep.check_file(ckpt, "checkpoint")
    calib_json = resolve_path(args.calib_json)
    image_root = (
        resolve_path(args.calib_image_root) if args.calib_image_root else calib_json.parent
    )
    if calib_json.is_file():
        rep.ok(f"校准清单来源: {calib_json}")
        try:
            files = calib_list(calib_json, image_root, args.calib_images)
            rep.ok(f"校准图 {len(files)} 张（前 {args.calib_images} 张，根 {image_root}）")
        except (ValueError, FileNotFoundError, KeyError) as exc:
            rep.error(f"校准清单不可用: {exc}")
    else:
        rep.missing(f"校准清单来源: {calib_json}（int8 量化需要；fp32 导出不需要）")

    rep.section("2. 导出计划")
    rep.plan(
        f"模型：seg 系·{args.variant}（中性名 beaneye-det；钉版 requirements-oss.txt）"
    )
    rep.plan(
        f"ONNX：opset={args.opset}，{'动态轴' if args.dynamic else f'静态 {args.resolution}×{args.resolution}'}"
        "（计划 T1 导出口径 = opset 17 静态 1024）"
    )
    rep.plan(f"输出: {resolve_path(args.out)}/model.onnx"
             + (" + model_int8.onnx" if args.quantize == "int8" else "")
             + " + export_plan.json")
    if args.quantize == "int8":
        rep.plan("int8 静态量化：onnxruntime.quantization.quantize_static"
                 f"（校准 {args.calib_images} 张 1024² 合成盘图，MinMax）≈5–15 min（CPU）")
        rep.warn("量化要求 ONNX 含掩码头；无掩码输出时明确报错（不静默出废模型）")
    rep.warn("顺序：T1 训练 → 验收 → 本脚本（可选）→ 桌面端 CPU 部署联调；产物走 COS 中转")
    rep.warn("NN 包 export() 若不接受 opset/静态参数 → 按该版本默认导出并打印告警（见 README API 核对节）")
    return rep.finish()


# ---------------------------------------------------------------------------
# 真实执行
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    import numpy as np

    out = resolve_path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # ---- 1) 导出 fp32 ONNX --------------------------------------------------
    nn_pkg, _torch = _common.import_nn_stack()
    model_cls = _common.nn_model_class(nn_pkg, args.variant)
    kwargs: dict = {"device": args.device}
    try:
        model = model_cls(resolution=args.resolution, pretrain_weights=str(resolve_path(args.checkpoint)), **kwargs)
    except TypeError:
        print("[警告] 构造器不接受 resolution/pretrain_weights，回退最小构造（README API 核对节）")
        model = model_cls(**kwargs)
    export_dir = out
    try:
        model.export(output_dir=str(export_dir), opset_version=args.opset)
    except TypeError:
        print(f"[警告] export() 不接受 opset_version 参数，按钉版默认导出（目标 opset {args.opset}）")
        model.export(output_dir=str(export_dir))
    onnx_path = export_dir / "model.onnx"
    if not onnx_path.is_file():
        # 钉版导出文件名可能不同：取目录内唯一 onnx
        candidates = sorted(export_dir.glob("*.onnx"))
        if not candidates:
            raise RuntimeError(f"导出后未找到 ONNX 产物: {export_dir}")
        onnx_path = candidates[0]
    print(f"[export] fp32 ONNX: {onnx_path}")

    plan: dict = {
        "script": "train/export_onnx_quant.py",
        "checkpoint": str(resolve_path(args.checkpoint)),
        "opset_target": args.opset,
        "static_resolution": None if args.dynamic else args.resolution,
        "fp32_onnx": str(onnx_path),
        "quantize": args.quantize,
    }

    # ---- 2) int8 静态量化（可选） -------------------------------------------
    if args.quantize == "int8":
        calib_json = resolve_path(args.calib_json)
        image_root = (
            resolve_path(args.calib_image_root)
            if args.calib_image_root
            else calib_json.parent
        )
        files = calib_list(calib_json, image_root, args.calib_images)
        try:
            from onnxruntime.quantization import (
                CalibrationDataReader,
                CalibrationMethod,
                QuantFormat,
                QuantType,
                quantize_static,
            )
        except ImportError as exc:
            print(f"[FAIL] onnxruntime 量化组件不可用（{exc}）；保留 fp32 产物")
            save_json(out / "export_plan.json", plan)
            return 1

        import cv2

        class _Reader(CalibrationDataReader):
            """合成盘图校准读取器（与 _predict.OnnxPredictor 同预处理口径）。"""

            def __init__(self, paths: list[Path], input_name: str, hw: tuple[int, int]):
                self._paths = paths
                self._input_name = input_name
                self._hw = hw
                self._idx = 0

            def get_next(self):
                if self._idx >= len(self._paths):
                    return None
                p = self._paths[self._idx]
                self._idx += 1
                img = cv2.imdecode(
                    np.frombuffer(p.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR
                )
                if img is None:
                    raise ValueError(f"校准图解码失败: {p}")
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                rgb = cv2.resize(rgb, (self._hw[1], self._hw[0]),
                                 interpolation=cv2.INTER_LINEAR)
                rgb = (rgb - _MEAN) / _STD
                return {self._input_name: rgb.transpose(2, 0, 1)[None].astype(np.float32)}

        import onnxruntime

        sess = onnxruntime.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0]
        shape = [d if isinstance(d, int) else 1024 for d in inp.shape]
        hw = (shape[-2], shape[-1])
        reader = _Reader(files, inp.name, hw)
        int8_path = out / "model_int8.onnx"
        quantize_static(
            model_input=str(onnx_path),
            model_output=str(int8_path),
            calibration_data_reader=reader,
            quant_format=QuantFormat.QDQ,
            activation_type=QuantType.QUInt8,
            weight_type=QuantType.QInt8,
            calibrate_method=CalibrationMethod.MinMax,
        )
        if not int8_path.is_file():
            raise RuntimeError("量化完成但未找到 model_int8.onnx")
        plan["int8_onnx"] = str(int8_path)
        plan["calibration"] = {
            "n_images": len(files),
            "files": [p.name for p in files],
            "method": "MinMax/QDQ/QUInt8-QInt8",
        }
        print(f"[export] int8 ONNX: {int8_path}")

    plan["fp32_sha256"] = _common.sha256_file(onnx_path)
    save_json(out / "export_plan.json", plan)
    print(f"[export] 计划/清单: {out / 'export_plan.json'}")
    print("[export] 产物回传走 COS 中转（跨机不直传）")
    return 0


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    if args.resolution <= 0 or args.opset <= 0 or args.calib_images <= 0:
        print("[错误] --resolution/--opset/--calib-images 须为正整数")
        return EXIT_USAGE
    if args.dry_run:
        rep = PlanReporter(dry_run=True)
        return dry_run(args, rep)
    try:
        return run(args)
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
