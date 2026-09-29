"""assetkit 编排：收集 → 压图 → 音频 → 字体 → 图集 → optmap + report。

输出目录整体重建（先清空）——素材管线是纯函数式的：同输入同输出，残留产物
只会造成"哪次生成的"的歧义。汇总降幅只统计"素材本身"（图/音/字），图集是
附加产物单列（它不是替换关系，计入会虚增降幅）。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from . import ASSETKIT_VERSION, OPTMAP_NAME, REPORT_NAME, AssetkitError
from .atlas import build_atlas
from .audio import transcode_audio
from .collect import collect
from .fonts import spec_subset_text, subset_fonts
from .images import optimize_images

EXTRA_SUBSET_TEXT_DEFAULT = ""  # 数字已内建于字符集（得分必然要渲染）


def _log_print(msg: str) -> None:
    print(f"[assetkit] {msg}", flush=True)


def run_assetkit(
    inputs: list[str | Path],
    out: str | Path,
    spec: str | Path | None = None,
    image_quality: int = 75,
    audio_bitrate: int = 48000,
    max_edge: int = 0,
    atlas: bool = True,
    atlas_max_width: int = 1024,
    extra_text: str = EXTRA_SUBSET_TEXT_DEFAULT,
    min_reduction_pct: float | None = None,
    repo_root: Path | None = None,
    log=_log_print,
) -> dict:
    """跑完整素材管线，返回报告 dict（同时落 report.json / asset-optmap.json）。

    抛 AssetkitError（exit_code 1=处理失败，2=用法/环境错误）。
    """
    out_dir = Path(out).resolve()
    spec_path = Path(spec).resolve() if spec else None
    if spec_path is not None and not spec_path.is_file():
        raise AssetkitError(f"spec 不存在：{spec_path}", 2)

    materials = collect(inputs, spec_path, repo_root=repo_root)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    log(f"素材 {len(materials)} 个（image {sum(1 for m in materials if m.kind == 'image')}"
        f" / audio {sum(1 for m in materials if m.kind == 'audio')}"
        f" / font {sum(1 for m in materials if m.kind == 'font')}）→ {out_dir}")

    notes: list[str] = []
    image_entries = optimize_images(materials, out_dir, quality=image_quality, max_edge=max_edge)
    audio_entries = transcode_audio(materials, out_dir, bitrate=audio_bitrate)
    subset_text = spec_subset_text(
        json.loads(spec_path.read_text(encoding="utf-8")) if spec_path else None,
        extra_text=extra_text)
    font_entries = subset_fonts(materials, out_dir, text=subset_text)

    failed = [e for e in (*image_entries, *audio_entries, *font_entries) if e.get("status") == "failed"]
    if failed:
        for e in failed:
            notes.append(f"素材 {e['key']} 处理失败：{e.get('note')}")
        raise AssetkitError(
            f"{len(failed)} 个素材处理失败（见 report.json notes）；"
            "素材管线宁可失败不可带病出报告", 1)

    atlas_info = None
    if atlas and image_entries:
        atlas_info = build_atlas(image_entries, out_dir, max_width=atlas_max_width)
        if atlas_info and atlas_info.get("note"):
            notes.append(f"图集：{atlas_info['note']}")

    all_entries = [*image_entries, *audio_entries, *font_entries]
    original_total = sum(int(e.get("originalBytes") or 0) for e in all_entries)
    optimized_total = sum(int(e.get("optimizedBytes") or 0) for e in all_entries)
    reduction_pct = round((1 - optimized_total / original_total) * 100, 2) if original_total else 0.0

    min_met: bool | None = None
    if min_reduction_pct is not None:
        min_met = original_total > 0 and reduction_pct >= float(min_reduction_pct)

    opt_entries = [
        {"key": e["key"], "src": e["src"], "out": e.get("out"),
         "kind": e["kind"], "encoding": e.get("encoding"),
         "originalBytes": e.get("originalBytes"), "optimizedBytes": e.get("optimizedBytes")}
        for e in all_entries if e.get("out")
    ]
    (out_dir / OPTMAP_NAME).write_text(
        json.dumps({
            "version": 1,
            "outDir": str(out_dir),
            "entries": opt_entries,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "assetkitVersion": ASSETKIT_VERSION,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "spec": str(spec_path) if spec_path else None,
        "outDir": str(out_dir),
        "subsetTextChars": len(subset_text),
        "materials": {"image": image_entries, "audio": audio_entries, "font": font_entries},
        "totals": {
            "count": len(all_entries),
            "originalBytes": original_total,
            "optimizedBytes": optimized_total,
            "reductionPct": reduction_pct,
            "minReductionPct": min_reduction_pct,
            "minReductionMet": min_met,
        },
        "atlas": atlas_info,
        "notes": notes,
    }
    (out_dir / REPORT_NAME).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log(f"汇总：{original_total:,}B → {optimized_total:,}B（降 {reduction_pct}%）"
        + (f"；图集 {atlas_info['packed']} 帧" if atlas_info and atlas_info.get("packed") else ""))
    for n in notes:
        log(f"注意：{n}")
    return report
