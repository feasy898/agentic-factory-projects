"""assetkit 字体子集：fontTools 按 spec i18n 字符集子集化，woff2/woff/ttf 输出。

字符集 = spec.i18n.strings 全语言值 ∪ meta.title ∪ 数字（得分/倒计时必然要渲染
数字，i18n 串未必含）∪ --extra-text。字体缺字形不报错：如实报告覆盖率（哪些
请求字符在原字体 cmap 里就没有），子集里自然只含有字形的部分。
"""

from __future__ import annotations

import io
from pathlib import Path

DIGITS = "0123456789"


def spec_subset_text(spec: dict | None, extra_text: str = "") -> str:
    """汇总 spec 里的全部应上屏字符（去重、保持首次出现序）。"""
    chars: list[str] = []
    seen: set[str] = set()

    def _push(s: str) -> None:
        for ch in s:
            if ch not in seen and not ch.isspace():
                seen.add(ch)
                chars.append(ch)

    if spec:
        _push(str((spec.get("meta") or {}).get("title") or ""))
        strings = ((spec.get("i18n") or {}).get("strings") or {})
        for table in strings.values():
            if isinstance(table, dict):
                for v in table.values():
                    if isinstance(v, str):
                        _push(v)
    _push(DIGITS)
    _push(extra_text or "")
    return "".join(chars)


def subset_fonts(
    materials: list,
    out_dir: Path,
    text: str,
) -> list[dict]:
    """子集化全部 font 素材；返回逐素材结果条目（含字符覆盖率）。"""
    fonts = [m for m in materials if m.kind == "font"]
    if not fonts:
        return []

    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:  # pragma: no cover - venv 必有 fonttools，防御性
        return [{
            "key": m.key, "src": str(m.src), "kind": "font", "status": "failed",
            "note": f"fontTools 不可用：{exc}",
        } for m in fonts]

    try:
        import brotli  # noqa: F401

        flavor = "woff2"
    except ImportError:
        flavor = "woff"  # zlib 恒在，woff 兜底；ttf 为最终兜底（个别库缺 woff writer 时）

    entries: list[dict] = []
    for m in fonts:
        original_bytes = m.src.stat().st_size
        font_number = 0 if m.src.suffix.lower() == ".ttc" else -1
        try:
            font = TTFont(str(m.src), fontNumber=font_number, lazy=True)
            cmap = font.getBestCmap() or {}
            requested = sorted({ch for ch in text})
            missing = [ch for ch in requested if ord(ch) not in cmap]
            covered = [ch for ch in requested if ord(ch) in cmap]
            if not covered:
                entries.append({
                    "key": m.key, "src": str(m.src), "kind": "font",
                    "status": "kept-original",
                    "originalBytes": original_bytes, "optimizedBytes": original_bytes,
                    "reductionPct": 0.0,
                    "note": "请求字符在该字体 cmap 中一个都没有，不产出空子集",
                })
                continue
            from fontTools import subset as ft_subset

            options = ft_subset.Options()
            options.flavor = flavor
            options.name_IDs = ["*"]
            options.notdef_outline = True
            options.recommended_glyphs = True
            options.glyph_names = False
            subsetter = ft_subset.Subsetter(options)
            subsetter.populate(unicodes=[ord(ch) for ch in covered])
            subsetter.subset(font)
            font.flavor = options.flavor  # 同 fontTools subset.save_font 的做法
            buf = io.BytesIO()
            font.save(buf)
            data = buf.getvalue()
        except Exception as exc:  # 字体解析/子集化失败：保留原始并记录，不阻塞
            entries.append({
                "key": m.key, "src": str(m.src), "kind": "font",
                "status": "kept-original",
                "originalBytes": original_bytes, "optimizedBytes": original_bytes,
                "reductionPct": 0.0,
                "note": f"子集化失败，保留原始：{exc}",
            })
            continue
        if flavor == "woff2" and data[:4] != b"wOF2":
            flavor_used = "woff" if data[:4] == b"wOFF" else "ttf"
        else:
            flavor_used = flavor
        ext = {"woff2": ".woff2", "woff": ".woff", "ttf": ".ttf"}[flavor_used]
        out_file = out_dir / (m.src.stem + ".subset" + ext)
        out_file.write_bytes(data)
        note_parts = [f"字符覆盖 {len(covered)}/{len(requested)}"]
        if missing:
            shown = "".join(missing[:12])
            more = f"（另 {len(missing) - 12} 字略）" if len(missing) > 12 else ""
            note_parts.append(f"字体缺 {len(missing)} 字形：{shown!r}{more}")
        if data and len(data) >= original_bytes:
            note_parts.append(f"子集不小于原始（{len(data)}B ≥ {original_bytes}B），仅作记录仍落盘")
        entries.append({
            "key": m.key, "src": str(m.src), "kind": "font",
            "status": "optimized" if len(data) < original_bytes else "kept-original",
            "out": out_file.name, "encoding": flavor_used,
            "originalBytes": original_bytes, "optimizedBytes": len(data),
            "reductionPct": round((1 - len(data) / original_bytes) * 100, 1) if len(data) < original_bytes else 0.0,
            "charsRequested": len(requested),
            "charsCovered": len(covered),
            "note": "；".join(note_parts),
        })
    return entries
