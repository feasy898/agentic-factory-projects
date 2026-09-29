"""assetkit 音频：ffmpeg 转低码率 AAC（.m4a）。

ffmpeg 缺席或单文件转码失败都不阻塞流水线：该素材保留原始并如实记录（宁可
不减不假报）。元数据全剥（-map_metadata -1），广告素材不需要封面/作者信息。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def find_ffmpeg() -> str | None:
    """定位 ffmpeg：环境变量 PF_ASSETKIT_FFMPEG 优先，其后 PATH。"""
    import os

    custom = os.environ.get("PF_ASSETKIT_FFMPEG")
    if custom and Path(custom).is_file():
        return custom
    return shutil.which("ffmpeg")


def transcode_audio(
    materials: list,
    out_dir: Path,
    bitrate: int = 48000,
    audio_bitrate: int | None = None,
) -> list[dict]:
    """转码全部 audio 素材为 .m4a；返回逐素材结果条目。"""
    if audio_bitrate is not None:  # 兼容显式命名参数
        bitrate = audio_bitrate
    audios = [m for m in materials if m.kind == "audio"]
    if not audios:
        return []
    ffmpeg = find_ffmpeg()
    entries: list[dict] = []
    if ffmpeg is None:
        for m in audios:
            entries.append({
                "key": m.key, "src": str(m.src), "kind": "audio",
                "status": "kept-original", "encoding": "original",
                "originalBytes": m.src.stat().st_size,
                "optimizedBytes": m.src.stat().st_size, "reductionPct": 0.0,
                "note": "ffmpeg 不可用（PATH 无 ffmpeg，可用 PF_ASSETKIT_FFMPEG 指定），保留原始",
            })
        return entries

    for m in audios:
        original_bytes = m.src.stat().st_size
        out_file = out_dir / (m.src.stem + ".m4a")
        cmd = [
            ffmpeg, "-y", "-nostdin", "-i", str(m.src),
            "-vn", "-map_metadata", "-1",
            "-codec:a", "aac", "-b:a", f"{int(bitrate)}",
            "-f", "ipod", str(out_file),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            entries.append({
                "key": m.key, "src": str(m.src), "kind": "audio",
                "status": "kept-original", "encoding": "original",
                "originalBytes": original_bytes, "optimizedBytes": original_bytes,
                "reductionPct": 0.0, "note": f"ffmpeg 启动失败：{exc}",
            })
            continue
        ok = proc.returncode == 0 and out_file.is_file() and out_file.stat().st_size > 0
        if not ok:
            tail = "\n".join((proc.stderr or "").strip().splitlines()[-3:])
            entries.append({
                "key": m.key, "src": str(m.src), "kind": "audio",
                "status": "kept-original", "encoding": "original",
                "originalBytes": original_bytes, "optimizedBytes": original_bytes,
                "reductionPct": 0.0,
                "note": f"转码失败（exit {proc.returncode}），保留原始：{tail}" if tail else "转码失败，保留原始",
            })
            continue
        new_bytes = out_file.stat().st_size
        if new_bytes >= original_bytes:
            entries.append({
                "key": m.key, "src": str(m.src), "kind": "audio",
                "status": "kept-original", "encoding": "original",
                "out": None,
                "originalBytes": original_bytes, "optimizedBytes": original_bytes,
                "reductionPct": 0.0,
                "note": f"低码率转码不小于原始（{new_bytes}B ≥ {original_bytes}B），保留原始",
            })
            continue
        entries.append({
            "key": m.key, "src": str(m.src), "kind": "audio",
            "status": "optimized", "out": out_file.name, "encoding": f"aac-{bitrate}",
            "originalBytes": original_bytes, "optimizedBytes": new_bytes,
            "reductionPct": round((1 - new_bytes / original_bytes) * 100, 1),
            "note": "",
        })
    return entries
