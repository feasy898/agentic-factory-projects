"""M3 人声/背景分离（规划 §4 M3，【本机 CPU 验收 / GPU 可选】）。

职责（只读写 01_media/ 与 04_dial/ 两层，跨层交换只经冻结契约）：
  1. 输入 ``01_media/audio_48k.wav``（M1 混音底座；缺失时回退 ``audio_16k.wav``）
     → audiosplit 组件（分离框架，中性名见 configs/models.yaml）载入
     **mel-band-roformer 系卡拉OK分离模型**（aufr33/viperx karaoke，标称 SDR 12.98）
     → 人声 + 背景两轨；
  2. 产物（B1 冻结槽位，docs/b1_contract_notes.md §1 与 scaffold.EXPECTED_FILES）：
     - ``04_dial/vocals.wav`` —— 人声（16k 单声道 pcm_s16le，M4 唯一识别输入口径）；
     - ``01_media/bgm.wav``  —— 背景音（与分离输入同采样率/声道，M9 混音底座配套）；
     - ``04_dial/separate.json`` —— 分离报告（设备/模型/耗时/时长/RMS 判据实测）。
  3. 设备双路径（configs/models.yaml ``routing.separation`` 路由）：
     - ``cpu``（默认）→ 组件 ``audiosplit``（device: cpu），强制 ``CUDA_VISIBLE_DEVICES=""``
       后再 import torch（防 CUDA 构建抢跑），并默认 120s 分块（防内存膨胀）；
     - ``cuda`` → 组件 ``audiosplit-cuda``（device: cuda:0），整轨处理；
       本机 torch 无 CUDA 时报错退出（GPU 路径在 anolis-gpu-01 验收）。
     模型内部固定 44.1k 处理：产物经 ffmpeg 重采样回输入口径，并 apad/-t 对齐
     输入时长（eval ①：输出时长=输入）。

RMS 判据（规划 §4 M3 eval ②，真值区间来源）：
  - 有声区间（正片用 M2 字幕区间；eval 用合成样本的已知真值）内：
    人声 RMS ≥ 总轨 RMS − 6dB；
  - 纯背景区间内：人声 RMS ≤ −15dBFS。
  真值经 ``--truth`` 注入（JSON：``{"voiced": [[s,e],...], "bgm_only": [[s,e],...]}``，
  单位秒）；缺省时跳过判据计算（报告记 null）。

CLI（规划 §4 冻结形态）::

    python -m pipeline.m3_separate --ep ep01 [--device cpu|cuda]

扩展参数：--jobs-dir / --model / --chunk-s / --truth。
退出码：0 成功；1 分离失败/设备不可用；2 用法错误。

依赖注意（与仓库级约束一致）：
  - torch 必须先于 paddle 导入（本模块只碰 torch，无 paddle 依赖）；
  - 权重缓存 ``models/audiosplit/`` 不入公开仓（configs/models.yaml weights 字段）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from pipeline.config import load_pipeline_config
from pipeline.m1_ingest import FFMPEG, IngestError, ffprobe_json
from pipeline.scaffold import create_workspace, ep_dir

__all__ = [
    "SeparationError",
    "load_separation_config",
    "rms_dbfs",
    "interval_rms_dbfs",
    "load_truth_intervals",
    "separate",
    "main",
]

#: 默认模型（mel-band-roformer 系卡拉OK分离，aufr33/viperx，标称 SDR 12.98）
DEFAULT_MODEL = "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt"
#: CPU 路径默认分块秒数（eval 60s 素材单块内完成；长素材防内存膨胀）
DEFAULT_CHUNK_S = 120.0
#: 人声产物（M4 识别输入口径）：16k 单声道
VOCALS_SR = 16000
#: 输入候选（按序）：48k 混音底座优先，16k 兜底
INPUT_CANDIDATES = ("audio_48k.wav", "audio_16k.wav")
#: RMS 判据冻结阈值（规划 §4 M3 eval ②）
VOICED_MARGIN_DB = 6.0   # 人声 RMS ≥ 总轨 RMS − 6dB（有声区间）
BGMONLY_CEILING_DBFS = -15.0  # 人声 RMS ≤ −15dBFS（纯背景区间）
#: 时长对齐容差（与 M1 同一口径）
DUR_TOL_S = 0.2


class SeparationError(RuntimeError):
    """分离流程失败（设备不可用/模型缺失/引擎异常/ffmpeg 失败）。"""


# ---------------------------------------------------------------------------
# models.yaml 路由（CPU/GPU 双路径配置的唯一事实源）
# ---------------------------------------------------------------------------

def _models_cfg() -> dict[str, Any]:
    from pipeline.config import CONFIG_DIR, load_yaml

    return load_yaml(CONFIG_DIR / "models.yaml")


def load_separation_config(
    device: str = "cpu",
    *,
    model: str | None = None,
    cfg: dict[str, Any] | None = None,
    pipeline_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按设备解析分离组件配置（models.yaml routing.separation + components）。

    返回：{component, device, weights_dir, model, chunk_s}。
    ``weights_dir`` 解析：components.<name>.weights 形如 ``models/audiosplit/``，
    相对 ``pipeline.yaml paths.models_dir`` 的父目录（即项目根）解析为绝对路径。
    """
    if device not in ("cpu", "cuda"):
        raise SeparationError(f"未知 device {device!r}（可选 cpu|cuda）")
    mcfg = cfg if cfg is not None else _models_cfg()
    routing = (mcfg.get("routing") or {}).get("separation") or {}
    comp_name = routing.get("cuda" if device == "cuda" else "default")
    if not comp_name:
        raise SeparationError("models.yaml 缺 routing.separation 路由（default/cuda）")
    comp = (mcfg.get("components") or {}).get(comp_name)
    if not comp:
        raise SeparationError(f"models.yaml 缺组件定义: {comp_name}")

    rel = str(comp.get("weights") or "models/audiosplit/").replace("\\", "/")
    if pipeline_cfg is None:
        pipeline_cfg = load_pipeline_config()
    models_dir = Path(pipeline_cfg["paths"]["models_dir"])
    weights_dir = (models_dir.parent / rel).resolve()

    return {
        "component": comp_name,
        "device": device,
        "device_claim": str(comp.get("device") or ("cuda:0" if device == "cuda" else "cpu")),
        "weights_dir": weights_dir,
        "model": model or str(comp.get("model") or DEFAULT_MODEL),
        "chunk_s": (float(comp["chunk_s"]) if comp.get("chunk_s") is not None else DEFAULT_CHUNK_S)
        if device == "cpu" else None,  # cuda 整轨
        "threads": int(comp["threads"]) if comp.get("threads") else 0,  # 0=不改 torch 线程数
        "version": comp.get("version"),
    }


# ---------------------------------------------------------------------------
# RMS 判据（规划 §4 M3 eval ② 的度量原语）
# ---------------------------------------------------------------------------

def rms_dbfs(x: np.ndarray) -> float:
    """波形 RMS → dBFS（20*log10；全零/极小值以 -120dBFS 兜底）。"""
    x = np.asarray(x, dtype=np.float64)
    r = float(np.sqrt(np.mean(np.square(x))) if x.size else 0.0)
    return max(20.0 * np.log10(r) if r > 0 else -120.0, -120.0)


def interval_rms_dbfs(
    wav: str | Path, intervals: list[list[float]] | None = None,
) -> list[float]:
    """逐区间 RMS（dBFS）。``intervals=None`` → 全轨单值（[整体]）。"""
    x, sr = sf.read(str(wav), dtype="float64", always_2d=True)
    mono = x.mean(axis=1)
    out: list[float] = []
    for s, e in (intervals or [[0.0, mono.shape[0] / sr]]):
        i0, i1 = max(0, int(s * sr)), min(mono.shape[0], int(e * sr))
        out.append(rms_dbfs(mono[i0:i1]) if i1 > i0 else -120.0)
    return out


def load_truth_intervals(path: str | Path) -> dict[str, list[list[float]]]:
    """读真值区间 JSON：{"voiced": [[s,e],...], "bgm_only": [[s,e],...]}（秒）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    voiced = [[float(s), float(e)] for s, e in (data.get("voiced") or [])]
    bgm_only = [[float(s), float(e)] for s, e in (data.get("bgm_only") or [])]
    if not voiced or not bgm_only:
        raise SeparationError(f"真值区间文件缺 voiced/bgm_only: {path}")
    return {"voiced": voiced, "bgm_only": bgm_only}


# ---------------------------------------------------------------------------
# 引擎封装（audiosplit：分离框架中性名，见 configs/models.yaml）
# ---------------------------------------------------------------------------

def _run_ffmpeg(cmd: list[str]) -> None:
    """ffmpeg 封装（复用 M1 的错误归一）。"""
    exe = cmd[0]
    if shutil.which(exe) is None:
        raise SeparationError(f"未找到可执行文件 {exe!r}（请确认 ffmpeg 在 PATH）")
    import subprocess

    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SeparationError(f"ffmpeg 退出码 {r.returncode}: {' '.join(cmd[:8])}...\n"
                              f"{(r.stderr or '').strip()[-1500:]}")


def _pick_input(media_dir: Path) -> Path:
    for name in INPUT_CANDIDATES:
        p = media_dir / name
        if p.is_file():
            return p
    raise SeparationError(
        f"缺分离输入（{', '.join(INPUT_CANDIDATES)}）——先跑 M1: python -m pipeline.m1_ingest")


def _postprocess_stem(
    src: Path, dst: Path, *, sr: int, channels: int, duration_s: float,
) -> None:
    """重采样到产物口径 + apad/-t 精确对齐输入时长（eval ①）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
        "-af", f"apad", "-t", f"{duration_s:.3f}",
        "-ar", str(sr), "-ac", str(channels), "-c:a", "pcm_s16le", str(dst),
    ])


def separate(
    ep: str,
    jobs_dir: str | Path,
    *,
    device: str = "cpu",
    model: str | None = None,
    chunk_s: float | None = None,
    truth: dict[str, list[list[float]]] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """M3 主流程：01_media 输入 → 04_dial/vocals.wav + 01_media/bgm.wav + separate.json。

    返回报告 dict（同时落盘 04_dial/separate.json）。
    """
    import tempfile

    cfg = cfg if cfg is not None else load_pipeline_config()
    jobs_root = Path(jobs_dir)
    create_workspace(ep, jobs_root)
    root = ep_dir(ep, jobs_root)
    media_dir, dial_dir = root / "01_media", root / "04_dial"

    src = _pick_input(media_dir)
    probe = ffprobe_json(src)
    a = next(s for s in probe["streams"] if s.get("codec_type") == "audio")
    in_sr, in_ch = int(a["sample_rate"]), int(a["channels"])
    duration_s = float(probe["format"]["duration"])

    comp = load_separation_config(device, model=model, pipeline_cfg=cfg)
    ckpt = comp["weights_dir"] / comp["model"]
    if not ckpt.is_file():
        raise SeparationError(
            f"分离权重缺失: {ckpt}（下载见 configs/models.yaml audiosplit 条目）")

    # 设备强制：cpu 路径在 import torch 前清空 CUDA_VISIBLE_DEVICES；
    # （仓库硬约束：torch 须先于 paddle 导入——本模块不涉 paddle。）
    if device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    import torch  # noqa: PLC0415  延迟导入（先设环境变量）

    if device == "cuda" and not torch.cuda.is_available():
        raise SeparationError(
            "device=cuda 但本机 torch 无 CUDA（GPU 路径在 anolis-gpu-01 验收；"
            "本机用默认 cpu 路径）")
    # CPU 线程数（models.yaml audiosplit.threads）：windev-01 实测定值 16 ——
    # 默认全核(64)线程互踩，单窗 65s → 16 线程 11.2s（eval ③ 时间预算的关键）。
    if comp["threads"] > 0:
        torch.set_num_threads(comp["threads"])

    from audio_separator.separator import Separator  # noqa: PLC0415  torch 之后导入

    timings: dict[str, float] = {}
    report: dict[str, Any] = {
        "ep": ep,
        "module": "m3_separate",
        "schema_version": 1,
        "component": comp["component"],
        "device": device,
        "device_claim": comp["device_claim"],
        "model": comp["model"],
        "torch": torch.__version__,
        "torch_threads": torch.get_num_threads(),
        "cuda_available": bool(torch.cuda.is_available()),
        "input": {"path": str(src), "sample_rate": in_sr, "channels": in_ch,
                  "duration_s": round(duration_s, 3)},
        "outputs": {},
        "timing": timings,
        "rms": None,
    }

    with tempfile.TemporaryDirectory(prefix=f"m3_{ep}_") as work:
        sep = Separator(
            model_file_dir=str(comp["weights_dir"]),
            output_dir=work,
            output_format="WAV",
            chunk_duration=(chunk_s if chunk_s is not None else comp["chunk_s"]),
        )
        t0 = time.perf_counter()
        sep.load_model(comp["model"])
        t1 = time.perf_counter()
        stems = sep.separate(
            str(src), custom_output_names={"Vocals": "vocals", "Instrumental": "bgm"})
        t2 = time.perf_counter()
        timings["load_s"] = round(t1 - t0, 2)
        timings["separate_s"] = round(t2 - t1, 2)
        timings["total_s"] = round(t2 - t0, 2)

        work_vocals = Path(work) / "vocals.wav"
        work_bgm = Path(work) / "bgm.wav"
        for want in (work_vocals, work_bgm):
            if not want.is_file():  # 引擎可能返回相对/异名路径 → 输出目录内按名兜底
                cand = [p for p in Path(work).rglob(want.name) if p.is_file()]
                if not cand:
                    raise SeparationError(f"引擎未产出 {want.name}（stems={stems}）")
                shutil.copy2(cand[0], want)

        # 产物口径：人声 16k 单声道（M4 输入）；背景与输入同采样率/声道（M9 配套）
        vocals_dst = dial_dir / "vocals.wav"
        bgm_dst = media_dir / "bgm.wav"
        _postprocess_stem(work_vocals, vocals_dst, sr=VOCALS_SR, channels=1,
                          duration_s=duration_s)
        _postprocess_stem(work_bgm, bgm_dst, sr=in_sr, channels=in_ch,
                          duration_s=duration_s)

    for key, path, sr_exp, ch_exp in (
        ("vocals", vocals_dst, VOCALS_SR, 1),
        ("bgm", bgm_dst, in_sr, in_ch),
    ):
        pr = ffprobe_json(path)
        st = next(s for s in pr["streams"] if s.get("codec_type") == "audio")
        report["outputs"][key] = {
            "path": str(path),
            "duration_s": round(float(pr["format"]["duration"]), 3),
            "sample_rate": int(st["sample_rate"]),
            "channels": int(st["channels"]),
            "expected_sample_rate": sr_exp,
            "expected_channels": ch_exp,
        }

    # RMS 判据（规划 §4 M3 eval ②；真值缺省则记 null）
    if truth is not None:
        mix_voiced = interval_rms_dbfs(src, truth["voiced"])
        voc_voiced = interval_rms_dbfs(vocals_dst, truth["voiced"])
        voc_bgm = interval_rms_dbfs(vocals_dst, truth["bgm_only"])
        rms = {
            "truth_source": "explicit",
            "mix_voiced_dbfs": [round(v, 2) for v in mix_voiced],
            "vocals_voiced_dbfs": [round(v, 2) for v in voc_voiced],
            "vocals_bgmonly_dbfs": [round(v, 2) for v in voc_bgm],
            "voiced_min_margin_db": round(min(v - m for v, m in zip(voc_voiced, mix_voiced)), 2),
            "bgmonly_max_dbfs": round(max(voc_bgm), 2),
            "criteria": {
                "voiced_ge_mix_minus_6db": min(
                    v - m for v, m in zip(voc_voiced, mix_voiced)) >= -VOICED_MARGIN_DB,
                "bgmonly_le_-15dbfs": max(voc_bgm) <= BGMONLY_CEILING_DBFS,
            },
        }
        report["rms"] = rms

    out_path = dial_dir / "separate.json"
    # numpy 标量（np.bool_/np.int64 等，来自 RMS 判据比较与时长运算）不可直接
    # JSON 序列化 —— 统一回退为 Python 原生标量（.item()）
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2,
                   default=lambda o: o.item() if isinstance(o, np.generic) else str(o)) + "\n",
        encoding="utf-8")
    report["report_path"] = str(out_path)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.m3_separate",
        description="M3 人声/背景分离：01_media 音频 → 04_dial/vocals.wav + 01_media/bgm.wav",
    )
    parser.add_argument("--ep", required=True, help="集 ID，如 ep01")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                        help="cpu=默认（分块）；cuda=GPU 路径（models.yaml routing.separation）")
    parser.add_argument("--jobs-dir", default=None,
                        help="jobs 根目录（默认取 configs/pipeline.yaml paths.jobs_dir）")
    parser.add_argument("--model", default=None, help="覆盖默认分离模型文件名")
    parser.add_argument("--chunk-s", type=float, default=None,
                        help="CPU 分块秒数（默认 120；cuda 忽略）")
    parser.add_argument("--truth", default=None,
                        help='真值区间 JSON：{"voiced":[[s,e]..],"bgm_only":[[s,e]..]}（秒）')
    args = parser.parse_args(argv)

    cfg = load_pipeline_config()
    jobs_root = Path(args.jobs_dir) if args.jobs_dir else Path(cfg["paths"]["jobs_dir"])
    try:
        truth = load_truth_intervals(args.truth) if args.truth else None
        report = separate(args.ep, jobs_root, device=args.device, model=args.model,
                          chunk_s=args.chunk_s, truth=truth, cfg=cfg)
    except (SeparationError, IngestError) as exc:
        print(f"FAIL m3_separate: {exc}")
        return 1

    o = report["outputs"]
    parts = [
        f"device={report['device']}({report['component']})",
        f"model={report['model']}",
        f"in={report['input']['duration_s']}s/{report['input']['sample_rate']}Hz",
        f"vocals={o['vocals']['duration_s']}s/{o['vocals']['sample_rate']}Hz",
        f"bgm={o['bgm']['duration_s']}s/{o['bgm']['sample_rate']}Hz",
        f"load={report['timing']['load_s']}s sep={report['timing']['separate_s']}s",
    ]
    print(f"OK m3_separate {args.ep}: " + ", ".join(parts))
    rms = report.get("rms")
    if rms:
        print(f"   RMS 判据: voiced≥mix-6dB {rms['criteria']['voiced_ge_mix_minus_6db']}"
              f"（最小裕量 {rms['voiced_min_margin_db']}dB）; "
              f"bgmonly≤-15dBFS {rms['criteria']['bgmonly_le_-15dbfs']}"
              f"（最大 {rms['bgmonly_max_dbfs']}dBFS）")
    print(f"   separate.json → {report['report_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
