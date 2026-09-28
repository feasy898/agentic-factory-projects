"""勺上分类器评测（training-plan §3：test acc ≥95%、漏检率 <3%、CPU ≤15ms）。

读一份预测汇总 JSON（验证集/测试集上的预测记录），对照
config/spoon_cls.json 的 thresholds 独立重算：

- ``test_acc``：整体准确率（有标签帧上的 (tp+tn)/n）；
- ``miss_rate``：漏检率（有食物判无）——比误检严重，是**硬线**；
- ``cpu_latency_ms``：CPU 单帧推理时延均值。

输入布局（--metrics）::

    {"split": "test", "predictions": [{"prob": 0.83, "label": 1}, ...],
     "cpu_latency_ms": [11.2, 12.0, ...]}

退出码：0=达标；1=存在未达硬线；2=参数/结构错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chengshao.training.common import (  # noqa: E402
    fail,
    load_json,
    utc_now_iso,
    write_report,
)

_MODULE = "training.spoon_cls.eval"


def compute_metrics(payload: dict, threshold: float) -> dict:
    preds = payload.get("predictions")
    lat = payload.get("cpu_latency_ms")
    if not isinstance(preds, list) or not preds:
        raise ValueError("predictions 必须为非空列表")
    tp = tn = fp = fn = 0
    for p in preds:
        if not isinstance(p, dict) or "prob" not in p or "label" not in p:
            raise ValueError(f"预测记录缺 prob/label：{p!r}")
        pred = 1 if float(p["prob"]) >= threshold else 0
        label = int(p["label"])
        if label == 1 and pred == 1:
            tp += 1
        elif label == 1 and pred == 0:
            fn += 1
        elif label == 0 and pred == 0:
            tn += 1
        else:
            fp += 1
    n = tp + tn + fp + fn
    acc = (tp + tn) / n
    miss = fn / max(1, tp + fn)  # 有食物判无
    false_pos = fp / max(1, tn + fp)  # 只记录
    out = {
        "split": payload.get("split", "unknown"),
        "threshold": threshold,
        "n": n,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "accuracy": round(acc, 4),
        "miss_rate": round(miss, 4),
        "false_positive_rate": round(false_pos, 4),
        "cpu_latency_ms_mean": (round(sum(float(v) for v in lat) / len(lat), 3)
                                if isinstance(lat, list) and lat else None),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.spoon_cls.eval",
        description="勺上分类器阈值评测（acc/漏检率/时延 vs 配置硬线）")
    parser.add_argument("--metrics", type=Path, required=True, help="预测汇总 JSON")
    parser.add_argument("--config", type=Path,
                        default=Path(__file__).resolve().parents[1] / "config" / "spoon_cls.json")
    parser.add_argument("--report", type=Path, default=None, help="§10.2 报告输出路径")
    args = parser.parse_args(argv)

    try:
        payload = load_json(args.metrics)
        cfg = load_json(args.config)
        th = cfg["thresholds"]
        m = compute_metrics(payload, float(th["decision_threshold"]))
    except (ValueError, KeyError, TypeError) as exc:
        fail(f"输入不合法：{exc}")

    checks = {
        "accuracy": m["accuracy"] >= float(th["test_acc_min"]),
        "miss_rate": m["miss_rate"] <= float(th["miss_rate_max"]),
        "latency": (m["cpu_latency_ms_mean"] is None
                    or m["cpu_latency_ms_mean"] <= float(th["cpu_latency_ms_max"])),
    }
    passed = all(checks.values())
    print("METRICS:", m)
    print("CHECKS:", checks)
    if args.report is not None:
        write_report(args.report, module=_MODULE,
                     cmd=f"python -m chengshao.training.spoon_cls.eval --metrics {args.metrics}",
                     metrics={**m, "checks": checks}, thresholds=th, passed=passed)
        print(f"REPORT: {args.report}")
    print(f"NOTE: eval @ {utc_now_iso()}；漏检率（miss_rate）为硬线：漏检导致喂空勺。")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
