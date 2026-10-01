"""生成内置语音样本（assets/voice_samples/*.wav + labels.json）。

D1 样本规范（开发指令 §5.4）要求手机真人录制；**在无麦克风/无真人的
构建环境里，本脚本用 Windows SAPI 本地 TTS（离线）合成等效样本集**：
4 类指令 × 4 条 + 4 条干扰（2 条无关语句 + 2 条非语音噪声）= 20 条，
16 kHz 单声道 PCM16。真人样本到位后可用 scripts/import_voice_samples.py
直接覆盖（labels.json 结构一致），链路不变。

用法::

    python chengshao/scripts/gen_voice_samples.py \
        [--out chengshao/assets/voice_samples]

依赖 Windows SAPI 中文语音（Microsoft Huihui 等）；不可用时 exit 1。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_PKG_ROOT = _HERE.parents[1]
_REPO_ROOT = _HERE.parents[2]
for _p in (str(_PKG_ROOT), str(_REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from cs_voice.tts import Speaker  # noqa: E402

# (文件名, 文本, intent, dish, 语速扰动)。语速扰动制造说话风格差异。
UTTERANCES: list[tuple[str, str, str, str | None, int]] = [
    ("next_1.wav", "下一口", "next", None, 190),
    ("next_2.wav", "请下一口", "next", None, 200),
    ("next_3.wav", "再来一口", "next", None, 180),
    ("next_4.wav", "该下一口了", "next", None, 210),
    ("pause_1.wav", "等一下", "pause", None, 190),
    ("pause_2.wav", "请等一下", "pause", None, 205),
    ("pause_3.wav", "暂停一下", "pause", None, 180),
    ("pause_4.wav", "先等一下", "pause", None, 195),
    ("done_1.wav", "吃饱了", "done", None, 190),
    ("done_2.wav", "我吃饱了", "done", None, 200),
    ("done_3.wav", "真的吃饱了", "done", None, 180),
    ("done_4.wav", "吃不下了", "done", None, 210),
    ("select_1.wav", "我想吃芋泥", "select", "芋泥", 190),
    ("select_2.wav", "来点南瓜粥", "select", "南瓜粥", 200),
    ("select_3.wav", "换椰子冻", "select", "椰子冻", 180),
    ("select_4.wav", "我想吃南瓜粥", "select", "南瓜粥", 195),
    # 干扰：无关语句（应判 unknown）
    ("noise_1.wav", "今天天气怎么样", "unknown", None, 190),
    ("noise_2.wav", "帮我查一下明天几点开会", "unknown", None, 200),
    # 干扰：非语音（应判 unknown）
    ("noise_3.wav", "", "unknown", None, 0),  # 白噪声，合成见 _synth_noise
    ("noise_4.wav", "", "unknown", None, 0),  # 扫频音，合成见 _synth_noise
]


def _synth_noise(path: Path, kind: str, sr: int = 16000) -> None:
    import numpy as np
    import soundfile as sf

    dur = 1.6
    t = np.arange(int(sr * dur)) / sr
    rng = np.random.default_rng(20260928)
    if kind == "white":
        wave = 0.03 * rng.standard_normal(len(t))
    else:  # chirp：220Hz→1.1kHz 扫频
        f0, f1 = 220.0, 1100.0
        freqs = np.linspace(f0, f1, len(t))
        phase = 2 * np.pi * np.cumsum(freqs) / sr
        wave = 0.05 * np.sin(phase)
    sf.write(str(path), wave.astype("float32"), sr, subtype="PCM_16")


def _to_16k_mono(src: Path, dst: Path, sr_target: int = 16000) -> None:
    """SAPI 原生输出（通常 22.05k）→ 16k 单声道 PCM16。"""
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(str(src), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != sr_target:
        try:
            import soxr

            mono = soxr.resample(mono, sr, sr_target)
        except ImportError:
            from math import gcd

            from scipy.signal import resample_poly

            g = gcd(sr, sr_target)
            mono = resample_poly(mono, sr_target // g, sr // g)
    peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
    if peak > 0.99:  # 防削波
        mono = mono * (0.99 / peak)
    sf.write(str(dst), mono, sr_target, subtype="PCM_16")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成内置语音样本（离线 TTS）")
    ap.add_argument("--out", type=Path,
                    default=_PKG_ROOT / "assets" / "voice_samples")
    args = ap.parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    spk = Speaker(rate=190)
    labels = []
    import tempfile

    for fname, text, intent, dish, rate in UTTERANCES:
        dst = out / fname
        if fname.startswith("noise_") and not text:
            _synth_noise(dst, "white" if fname.endswith("3.wav") else "chirp")
        else:
            with tempfile.TemporaryDirectory() as td:
                raw = Path(td) / "raw.wav"
                if not spk.synth_to_wav(text, raw, rate=rate):
                    print(f"[gen] TTS 合成失败（缺 SAPI 中文语音?）: {fname}",
                          file=sys.stderr)
                    return 1
                _to_16k_mono(raw, dst)
        labels.append({"file": fname, "text": text, "intent": intent,
                       "dish": dish})
        print(f"[gen] {fname}  {intent:<7} {text!r}")

    (out / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"[gen] {len(labels)} 条样本 + labels.json -> {out}")
    print("[gen] 注：本批为离线 TTS 合成样本（无麦克风环境等效集），"
          "真人录音可经 import 流程覆盖")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
