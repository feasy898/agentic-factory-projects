"""jobs/<ep> 每集工作区生成器（spec contract-io §3.1/§3.2 冻结布局；重生成实现）。

原则：只创建目录骨架，**不预生成任何文件**（避免空文件被当产物）。
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["LAYERS", "EXPECTED_FILES", "ep_dir", "create_workspace"]

#: 集 ID 白名单（ep 是路径组件，来自 CLI --ep，禁止穿越/绝对路径/空名）
_EP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: 13 层目录 → 子目录（相对 ep 工作区根；contract-io §3.1）
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

#: 各层预期产物文件名（contract-io §3.2）
EXPECTED_FILES: dict[str, tuple[str, ...]] = {
    "00_raw": ("input.mp4",),  # M1 收件固定名（任意容器一律此名）
    "01_media": (
        "video_1080x1920_25fps.mp4",  # 默认 targets 名（真名随 targets 联动）
        "audio_16k.wav",
        "audio_48k.wav",
        "bgm.wav",  # M3 分离背景
        "video_1080x1920_25fps_clean.mp4",  # M11 擦除基带
        "probe.json",  # M1 探针
    ),
    "02_shots": ("shots.json",),  # C1
    "03_ocr": ("ocr_raw.jsonl", "ocr_merged.jsonl"),
    "04_dial": (
        "vocals.wav",  # B1 冻结：M3 人声、M4 唯一识别输入
        "asr.jsonl",
        "forced.jsonl",
        "diar.jsonl",  # C2-pre
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
    "12_out": (),  # 按语种命名：<ep>.<lang>.mp4 / compliance.<lang>.json（C8）
}


def ep_dir(ep: str, jobs_dir: str | Path) -> Path:
    """ep 工作区根目录（ep 经白名单校验，杜绝 --ep ../x 类路径穿越）。

    白名单外：未捕获 ValueError（spec m1-ingest §5——进程 exit 1 带 traceback），
    且校验发生在建任何目录之前。
    """
    if not isinstance(ep, str) or not _EP_RE.match(ep):
        raise ValueError(
            f"非法集 ID: {ep!r}（须为匹配 {_EP_RE.pattern} 的字符串，"
            "禁止路径分隔符 / .. / 空串）"
        )
    return Path(jobs_dir) / ep


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
