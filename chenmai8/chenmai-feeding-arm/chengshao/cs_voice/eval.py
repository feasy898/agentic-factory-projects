"""cs_voice eval：无硬件语音链路验收（开发指令 §5.4）。

用法（cwd 任意，兼容包根独立运行与仓库根集成运行）::

    python -m cs_voice.eval --input assets/voice_samples \
        --report reports/voice_eval.json

流程：装载内置样本（wav + labels.json）→ ASR 逐条转写 → 意图解析 →
与标签比对（select 还须 dish 一致）→ 统计正确率/延迟/后端/离线证据 →
报告 JSON 落盘。exit 0 = 通过。

通过线（§5.4）：20 条预录指令意图正确 ≥18（即 ≥0.90）；单条响应 ≤2.5s
（CPU）；全链路离线（eval 期间插座级断网由人工复测，这里以"零外联
连接"作为程序化证据并如实注明）。
"""

from __future__ import annotations

import argparse
import json
import socket
import statistics
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve()
_PKG_ROOT = _HERE.parents[1]        # .../chengshao
_REPO_ROOT = _HERE.parents[2]       # 仓库根（仅用于缺省路径推导）

from .asr import AsrEngine          # noqa: E402
from .intent import IntentParser    # noqa: E402
from .tts import Speaker            # noqa: E402

THRESHOLDS = {
    "min_correct": 18,        # 20 条中 ≥18 条意图正确
    "min_accuracy": 0.90,
    "max_latency_s": 2.5,     # 单条（ASR+解析）响应上限
}


class _OutboundGuard:
    """统计 eval 期间的全部出站连接尝试（离线证据；loopback 不计）。"""

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self._orig = socket.socket.connect

    def __enter__(self):
        guard = self

        def hooked(sock, address):  # noqa: ANN001
            try:
                host = address[0] if isinstance(address, tuple) else str(address)
            except Exception:  # noqa: BLE001
                host = str(address)
            if host not in ("127.0.0.1", "::1", "0.0.0.0"):
                guard.attempts.append(f"{host}")
            return guard._orig(sock, address)

        socket.socket.connect = hooked  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc) -> None:
        socket.socket.connect = self._orig  # type: ignore[method-assign]


def _load_samples(input_dir: Path) -> list[dict]:
    labels_path = input_dir / "labels.json"
    if not labels_path.is_file():
        raise FileNotFoundError(f"缺少标签文件: {labels_path}")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    out = []
    for item in labels:
        wav = input_dir / item["file"]
        if not wav.is_file():
            raise FileNotFoundError(f"样本缺失: {wav}")
        out.append({**item, "path": wav})
    return out


def run_eval(input_dir: Path, report_path: Path,
             skip_tts: bool = False) -> tuple[bool, dict]:
    """跑完整 eval，返回 (pass, report dict)。"""
    samples = _load_samples(input_dir)
    parser = IntentParser()

    details: list[dict] = []
    latencies: list[float] = []
    per_intent: dict[str, dict[str, int]] = {}

    with _OutboundGuard() as guard:
        engine = AsrEngine()
        t0 = time.perf_counter()
        backend = engine.ensure_loaded()
        model_load_s = time.perf_counter() - t0

        # 预热一次（排除首次推理的运行时初始化抖动，单独记录冷启动）
        cold_t0 = time.perf_counter()
        engine.transcribe_file(samples[0]["path"])
        cold_first_s = time.perf_counter() - cold_t0

        for item in samples:
            t1 = time.perf_counter()
            text = engine.transcribe_file(item["path"])
            vi = parser.parse(text)
            dt = time.perf_counter() - t1
            latencies.append(dt)

            expect_intent = item["intent"]
            ok_intent = vi.intent.value == expect_intent
            ok = ok_intent and (
                expect_intent != "select"
                or vi.slots.get("dish") == item.get("dish")
            )
            stat = per_intent.setdefault(
                expect_intent, {"total": 0, "correct": 0})
            stat["total"] += 1
            if ok:
                stat["correct"] += 1
            details.append({
                "file": item["file"],
                "expected": expect_intent,
                "dish_expected": item.get("dish"),
                "transcribed": text,
                "predicted": vi.intent.value,
                "dish_predicted": vi.slots.get("dish"),
                "confidence": round(vi.confidence, 3),
                "latency_s": round(dt, 3),
                "ok": bool(ok),
            })

        outbound = list(guard.attempts)

    n_total = len(details)
    n_correct = sum(1 for d in details if d["ok"])
    accuracy = n_correct / n_total if n_total else 0.0
    lat_sorted = sorted(latencies)
    p50 = lat_sorted[len(lat_sorted) // 2] if lat_sorted else 0.0
    p95 = lat_sorted[min(len(lat_sorted) - 1, int(len(lat_sorted) * 0.95))]
    max_lat = max(latencies) if latencies else 0.0

    # TTS 通路（合成到文件，不依赖音频输出设备；非通过线，仅记录）
    tts_info: dict = {"available": False, "synth_ok": False}
    if not skip_tts:
        spk = Speaker()
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "tts_check.wav"
            tts_info["synth_ok"] = bool(spk.synth_to_wav("好的，这就为您舀一勺", wav))
            if tts_info["synth_ok"]:
                import soundfile as sf

                data, sr = sf.read(str(wav))
                tts_info["duration_s"] = round(len(data) / sr, 2)
        tts_info["available"] = bool(spk.available)
        tts_info["voice"] = spk.voice_name
        spk.shutdown()

    offline_ok = not outbound
    pass_bool = bool(
        n_correct >= THRESHOLDS["min_correct"]
        and accuracy >= THRESHOLDS["min_accuracy"]
        and max_lat <= THRESHOLDS["max_latency_s"]
        and offline_ok
    )

    report = {
        "module": "cs_voice",
        "date": time.strftime("%Y-%m-%d"),
        "cmd": "python -m cs_voice.eval --input chengshao/assets/voice_samples "
               "--report chengshao/reports/voice_eval.json",
        "metrics": {
            "n_total": n_total,
            "n_correct": n_correct,
            "accuracy": round(accuracy, 4),
            "per_intent": per_intent,
            "latency": {
                "mean_s": round(statistics.fmean(latencies), 3) if latencies else 0.0,
                "p50_s": round(p50, 3),
                "p95_s": round(p95, 3),
                "max_s": round(max_lat, 3),
                "cold_first_s": round(cold_first_s, 3),
            },
            "asr": {
                "backend": backend,
                "model_load_s": round(model_load_s, 1),
            },
            "tts": tts_info,
            "offline": {
                "outbound_connect_attempts": len(outbound),
                "targets": sorted(set(outbound)),
                "note": "程序化证据=eval 期间零外联；拔网线复测属人工步骤，未执行",
            },
        },
        "thresholds": THRESHOLDS,
        "pass": pass_bool,
        "details": details,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return pass_bool, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="cs_voice eval（§5.4）")
    ap.add_argument("--input", type=Path,
                    default=_PKG_ROOT / "assets" / "voice_samples",
                    help="样本目录（wav + labels.json）")
    ap.add_argument("--report", type=Path,
                    default=_PKG_ROOT / "reports" / "voice_eval.json",
                    help="报告 JSON 输出路径")
    ap.add_argument("--skip-tts", action="store_true", help="跳过 TTS 自检")
    args = ap.parse_args(argv)

    ok, report = run_eval(args.input, args.report, skip_tts=args.skip_tts)
    m = report["metrics"]
    print(f"[cs_voice] backend={m['asr']['backend']} "
          f"correct={m['n_correct']}/{m['n_total']} "
          f"acc={m['accuracy']:.2f} max_lat={m['latency']['max_s']}s "
          f"tts_ok={m['tts'].get('synth_ok')} offline_ok={not m['offline']['outbound_connect_attempts']}")
    print(f"[cs_voice] report -> {args.report}")
    bad = [d for d in report["details"] if not d["ok"]]
    for d in bad:
        print(f"  MISS {d['file']}: expect={d['expected']}/{d['dish_expected']} "
              f"got={d['predicted']}/{d['dish_predicted']} text={d['transcribed']!r}")
    print(f"[cs_voice] pass={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
