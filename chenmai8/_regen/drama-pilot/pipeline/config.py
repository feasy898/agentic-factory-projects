"""pipeline 全局配置：REPO_ROOT / jobs_dir() / 媒体规范化目标参数。

依 spec（docs/assets/specs/m1-ingest.md §2 重生成约束）：
``configs/pipeline.yaml`` 的 ``media`` 段为规范化目标的唯一事实源；
文件缺失、段落缺失或单值解析失败时逐项回落到代码兜底常量 ``_DEFAULT_MEDIA``。

只用标准库：内置两级平铺 YAML 最小解析器（section: 下缩进 ``key: 标量``），
不引入第三方依赖，保证试点工作区自含。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "configs" / "pipeline.yaml"

# 代码兜底常量（值取自 spec m1-ingest §2：1080x1920@25 / 48k 混音底座 / 16k 识别 /
# -16 LUFS、TP -1.5dBTP、LRA 11 / libx264 crf18 veryfast / 容器内音轨 AAC 192k）。
_DEFAULT_MEDIA: dict = {
    "width": 1080,
    "height": 1920,
    "fps": 25,
    "mix_sr": 48000,
    "asr_sr": 16000,
    "loudness_lufs": -16.0,
    "true_peak_dbtp": -1.5,
    "lra": 11,
    "crf": 18,
    "preset": "veryfast",
    "video_audio_bitrate": "192k",
}

_INT_KEYS = {"width", "height", "fps", "mix_sr", "asr_sr", "lra", "crf"}
_FLOAT_KEYS = {"loudness_lufs", "true_peak_dbtp"}


def _coerce(key: str, raw: str):
    text = str(raw).strip().strip("'\"")
    if key in _INT_KEYS:
        return int(float(text))
    if key in _FLOAT_KEYS:
        return float(text)
    return text


def _parse_flat_yaml(text: str) -> dict:
    """两级平铺 YAML 最小解析（仅支持 section → 键 → 标量，# 注释与空行忽略）。"""
    out: dict = {}
    section: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0:
            head = stripped.split(" #", 1)[0].rstrip()
            section = head[:-1].strip() if head.endswith(":") else None
            if section:
                out.setdefault(section, {})
            continue
        if section is not None and ":" in stripped:
            key, _, raw = stripped.partition(":")
            out[section][key.strip()] = raw.split(" #", 1)[0].strip()
    return out


def media_config() -> dict:
    """媒体规范化目标：configs/pipeline.yaml ``media`` 段优先，缺失逐项兜底。"""
    media = dict(_DEFAULT_MEDIA)
    try:
        data = _parse_flat_yaml(CONFIG_PATH.read_text(encoding="utf-8"))
    except OSError:
        return media
    for key, raw in (data.get("media") or {}).items():
        try:
            media[key] = _coerce(key, raw)
        except (TypeError, ValueError):
            continue  # 单值非法不致命：保留兜底值
    return media


def jobs_dir() -> Path:
    """默认共享工作区：``<REPO_ROOT>/jobs``（CLI ``--jobs-dir`` 可覆盖）。"""
    return REPO_ROOT / "jobs"
