"""jobs/<ep> 每集工作区生成器（目录布局冻结于规划 §3）。

原则：只创建目录骨架，**不预生成任何媒体/契约文件** —— 文件一律由各模块按
: data:`EXPECTED_FILES` 的命名规则产出，避免把空文件误当成产物。
跨层数据交换只通过冻结契约（pipeline/contracts.py，C1–C8）。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["LAYERS", "EXPECTED_FILES", "ep_dir", "create_workspace", "expected_path"]

#: 13 层目录 → 子目录（相对 ep 工作区根）
LAYERS: dict[str, tuple[str, ...]] = {
    "00_raw": (),
    "01_media": (),
    "02_shots": (),
    "03_ocr": (),
    "04_dial": ("emo_refs",),
    "05_cast": ("voicebank", "consent"),
    "06_mt": (),
    "07_synth": ("wavs",),
    "08_mix": (),
    "09_lip": ("done",),
    "10_subs": (),
    "11_labels": (),
    "12_out": (),
}

#: 各层预期产物文件名（模块按此命名；契约号注明出处）
EXPECTED_FILES: dict[str, tuple[str, ...]] = {
    "00_raw": ("input.mp4",),
    "01_media": ("video_1080x1920_25fps.mp4", "audio_16k.wav", "audio_48k.wav", "bgm.wav"),
    "02_shots": ("shots.json",),  # C1
    "03_ocr": ("ocr_raw.jsonl", "ocr_merged.jsonl"),
    "04_dial": (
        "asr.jsonl",
        "forced.jsonl",
        "diar.jsonl",
        "emo.jsonl",
        "utterances.jsonl",  # C2
    ),
    "05_cast": ("characters.json",),  # C3
    "06_mt": ("context.json", "translations.jsonl"),  # C4
    "07_synth": ("synth_plan.jsonl",),  # C5
    "08_mix": ("dubbed.wav", "mix.wav"),
    "09_lip": ("lip_plan.jsonl",),  # C6
    "10_subs": ("src.ass", "tgt.en.ass", "tgt.es.ass", "tgt.ar.ass"),
    "11_labels": ("labels.json", "c2pa_manifest.json", "audio_wm.wav"),  # C7
    "12_out": (),  # <ep>.<lang>.mp4 / compliance.<lang>.json 按语种命名  # C8
}


def ep_dir(ep: str, jobs_dir: str | Path) -> Path:
    """ep 工作区根目录路径。"""
    return Path(jobs_dir) / ep


def expected_path(ep: str, layer: str, name: str, jobs_dir: str | Path) -> Path:
    """某层某预期产物的完整路径（供各模块统一取路径，避免写死）。"""
    if layer not in LAYERS:
        raise KeyError(f"未知层 {layer!r}，合法层：{sorted(LAYERS)}")
    return ep_dir(ep, jobs_dir) / layer / name


def create_workspace(ep: str, jobs_dir: str | Path) -> list[Path]:
    """生成 jobs/<ep> 全部目录与子目录（幂等）。返回已就绪目录列表。"""
    root = ep_dir(ep, jobs_dir)
    created: list[Path] = [root]
    root.mkdir(parents=True, exist_ok=True)
    for layer, subs in LAYERS.items():
        d = root / layer
        d.mkdir(exist_ok=True)
        created.append(d)
        for sub in subs:
            sd = d / sub
            sd.mkdir(exist_ok=True)
            created.append(sd)
    return created
