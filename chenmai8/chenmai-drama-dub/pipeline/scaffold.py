"""jobs/<ep> 每集工作区生成器（目录布局冻结于规划 §3）。

原则：只创建目录骨架，**不预生成任何媒体/契约文件** —— 文件一律由各模块按
: data:`EXPECTED_FILES` 的命名规则产出，避免把空文件误当成产物。
跨层数据交换只通过冻结契约（pipeline/contracts.py，C1–C8）。
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["LAYERS", "EXPECTED_FILES", "ep_dir", "create_workspace", "expected_path"]

#: 集 ID 白名单（安全：ep 是路径组件，来自 CLI --ep，禁止穿越/绝对路径/空名）
_EP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

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
    # 01_media 保存混音口径产物：audio_16k.wav/audio_48k.wav 为 M1 重采样混音（含 BGM/音效），
    # bgm.wav 为 M3 分离出的背景音。人声不落本层 —— B1 冻结：M3 人声产出到 04_dial/vocals.wav。
    "01_media": ("video_1080x1920_25fps.mp4", "audio_16k.wav", "audio_48k.wav", "bgm.wav",
                 "probe.json"),  # probe.json 为 M1 产出口径（规划 §4 M1）
    "02_shots": ("shots.json",),  # C1
    "03_ocr": ("ocr_raw.jsonl", "ocr_merged.jsonl"),
    "04_dial": (
        # B1 冻结槽位（2026-09-28）：M3 人声分离产出 → 04_dial/vocals.wav；
        # M4（ASR/对齐/情绪）只读人声 vocals.wav，不读 01_media/audio_16k.wav
        # （混音含 BGM/音效会污染识别、对齐与情绪）。时间零点与切句规则见
        # pipeline/contracts.py 冻结规则 7/8 与 docs/b1_contract_notes.md。
        "vocals.wav",
        "asr.jsonl",
        "forced.jsonl",
        "diar.jsonl",  # C2-pre（说话人段级预分段 schema；speaker 由 M5 回填，M5 执行归 B2）
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
    """ep 工作区根目录路径（ep 经白名单校验，杜绝 ``--ep ../x`` 类路径穿越）。

    合法集 ID：字母/数字开头，仅含字母、数字、点、下划线、连字符
    （如 ``ep01``）；含路径分隔符、``..``、空串或绝对路径一律拒绝。
    """
    if not isinstance(ep, str) or not _EP_RE.match(ep):
        raise ValueError(
            f"非法集 ID: {ep!r}（须为匹配 {_EP_RE.pattern} 的字符串，"
            "禁止路径分隔符 / .. / 空串）"
        )
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
