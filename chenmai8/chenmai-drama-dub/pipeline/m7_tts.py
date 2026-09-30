"""M7 TTS 整集合成运行器（任务 T20 增补）—— C5 计划 → :9002 逐句合成。

背景：M7 的服务端（gpu-services/tts）与单句客户端（pipeline/tts_client.py）
T12 已交付，但"整集合成"此前只作为 scripts/e2e_smoke.sh 的内联段存在，
任务队列（pipeline/queue.py，M14）的默认步骤图需要可执行的模块 CLI ——
本模块把该内联段按原口径落成模块（行为忠实移植，含 atempo 微调）。

口径（与 e2e_smoke.sh 内联段一致）：
- 读 C5 ``07_synth/synth_plan.<lang>.jsonl``（缺则回退无后缀副本）；
- ``keep_original=true`` 句跳过（哭/尖叫等保留原声，不合成）；
- 逐句 ``TtsClient.synth``：voice_ref=角色音色参考、emo_ref=原片人声
  （音色与情绪参考分离）、emo_alpha/duration_factor/engine 均取 C5 行；
- ``atempo`` 偏离 1.0（>1e-3）时 ffmpeg 一次微调回写（M8 决策的执行位）；
- 一句都不可合成（C5 全 keep_original）→ exit 1（不伪造产出）。

CLI::

    python -m pipeline.m7_tts --ep ep01 --lang en [--jobs-dir <dir>] [--url ...]

在线依赖：tts 服务（默认 :9002，env M7_TTS_URL 可覆盖）；服务不可达时
本模块如实失败（不静默降级、不伪造产物）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


def synth_episode(ep: str, lang: str, *, jobs_dir: str | Path,
                  url: Optional[str] = None) -> dict:
    """C5 → :9002 整集合合成。返回 ``{"n": 合成句数, "skipped": 数, "wavs": [...]}``。"""
    from pipeline import contracts as C
    from pipeline.config import load_pipeline_config
    from pipeline.m1_ingest import FFMPEG
    from pipeline.tts_client import TtsClient

    if jobs_dir:
        root = Path(jobs_dir)
    else:
        root = Path(load_pipeline_config()["paths"]["jobs_dir"])
    ws = root / ep
    plan_path = ws / "07_synth" / f"synth_plan.{lang}.jsonl"
    if not plan_path.is_file():
        plan_path = ws / "07_synth" / "synth_plan.jsonl"
    if not plan_path.is_file():
        raise FileNotFoundError(
            f"C5 不存在: {ws/'07_synth'/f'synth_plan.{lang}.jsonl'}（先跑 M8）")
    rows = C.load_jsonl(plan_path, C.SynthPlanTable).root

    cli = TtsClient(url) if url else TtsClient()
    n = 0
    skipped = 0
    wavs: list[str] = []
    for r in rows:
        if r.keep_original:
            skipped += 1
            print(f"skip {r.utt_id} (keep_original)")
            continue
        out = ws / r.out
        res = cli.synth(
            r.text, str(ws / r.voice_ref),
            emo_ref=str(ws / r.emo_ref) if r.emo_ref else None,
            lang=lang, emo_alpha=float(r.emo_alpha),
            duration_factor=float(r.duration_factor),
            engine=r.engine or "auto", out=str(out), utt_id=r.utt_id)
        if r.atempo and abs(float(r.atempo) - 1.0) > 1e-3:
            tmp = out.with_name(out.stem + ".atempo.wav")
            subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-i", str(out),
                 "-af", f"atempo={float(r.atempo):.4f}", str(tmp)],
                check=True, timeout=300)
            tmp.replace(out)
        n += 1
        wavs.append(str(out))
        print(f"synth {r.utt_id} engine={res['engine']} "
              f"dur={res['duration_s']}s df={r.duration_factor} "
              f"atempo={r.atempo} expect={r.expect_dur}s")
    if n <= 0:
        raise RuntimeError("C5 无可合成句（全 keep_original？）——不出假交付")
    return {"n": n, "skipped": skipped, "wavs": wavs}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.m7_tts",
        description="M7 TTS 整集合成（C5 计划 → :9002 逐句合成 + atempo 微调）")
    ap.add_argument("--ep", required=True, help="集 ID，如 ep01")
    ap.add_argument("--lang", required=True, help="目标语种（en/es/ar）")
    ap.add_argument("--jobs-dir", default=None,
                    help="jobs 根目录（默认 configs/pipeline.yaml）")
    ap.add_argument("--url", default=None,
                    help="tts 服务地址（默认 M7_TTS_URL 或 http://127.0.0.1:9002）")
    args = ap.parse_args(argv)
    try:
        res = synth_episode(args.ep, args.lang, jobs_dir=args.jobs_dir,
                            url=args.url)
    except Exception as exc:  # 如实失败：报错到 stderr，退出码 1
        print(f"FAIL m7_tts {args.ep}/{args.lang}: {exc}", file=sys.stderr)
        return 1
    print(f"OK m7_tts {args.ep}/{args.lang} 合成 {res['n']} 句"
          f"（keep_original 跳过 {res['skipped']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
