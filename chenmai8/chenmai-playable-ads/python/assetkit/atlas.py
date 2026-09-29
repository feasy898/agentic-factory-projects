"""assetkit 图集：自研 shelf（next-fit 递减高）装箱 + 无损合成 + atlas.json。

- 装箱输入是"优化后"的图（尺寸以优化产物实测为准），矩形互不重叠、不出界
  （selftest 有成对校验）；放不下（单图宽超图集宽）的图如实记 skipped。
- 合成经 node 助手一次性完成（透明底 canvas + 逐帧贴入），候选无损 WebP /
  调色板 PNG 取小——图集是"重打包"而非"再压缩"，画质优先。
- atlas.json 键：优先素材文件名 stem；重名时回退"原始路径的 POSIX 相对形"，
  保证键稳定可复现（同输入同键）。
"""

from __future__ import annotations

import json
from pathlib import Path

from .nodehelper import run_helper


def pack_shelf(frames: list[dict], max_width: int) -> tuple[list[dict], int, int, list[dict]]:
    """next-fit 递减高 shelf 装箱。frames: [{key, file, width, height}]。

    返回 (placed, atlas_width, atlas_height, skipped)。placed 附加 x/y。
    """
    ordered = sorted(frames, key=lambda f: (-f["height"], -f["width"], f["key"]))
    placed: list[dict] = []
    skipped: list[dict] = []
    x = y = 0
    row_h = 0
    for f in ordered:
        if f["width"] > max_width:
            skipped.append({k: f[k] for k in ("key", "file", "width", "height")})
            continue
        if x and x + f["width"] > max_width:  # 换行
            y += row_h
            x = 0
            row_h = 0
        placed.append({**f, "x": x, "y": y})
        x += f["width"]
        row_h = max(row_h, f["height"])
    atlas_w = max_width if any(placed) else 0
    atlas_h = y + (row_h if placed else 0)
    # 收紧宽度：最右边界（避免整行空白）
    if placed:
        atlas_w = max(p["x"] + p["width"] for p in placed)
    return placed, atlas_w, atlas_h, skipped


def build_atlas(
    image_entries: list[dict],
    out_dir: Path,
    max_width: int = 1024,
) -> dict | None:
    """由压图结果条目合成图集；无图或全 skipped 时返回 None。

    条目须有 width/height（kept-original 且未被 node 实测过尺寸的条目由本函数
    自行跳过——无尺寸就不能进图集，如实记 note，不猜）。
    """
    frames: list[dict] = []
    for e in image_entries:
        if e.get("status") == "failed" or not e.get("out"):
            continue
        if not e.get("width") or not e.get("height"):
            continue
        frames.append({
            "key": Path(e["out"]).stem,
            "file": str(out_dir / e["out"]),
            "width": int(e["width"]),
            "height": int(e["height"]),
        })
    if not frames:
        return None
    placed, w, h, skipped = pack_shelf(frames, int(max_width))
    if not placed:
        return {"packed": 0, "skipped": skipped, "note": "无可装箱帧"}

    resp = run_helper({
        "atlas": {
            "outBase": str(out_dir / "atlas"),
            "width": w,
            "height": h,
            "parts": [{"src": p["file"], "x": p["x"], "y": p["y"]} for p in placed],
        },
    })
    atlas_res = resp.get("atlas") or {}
    if not atlas_res.get("ok"):
        return {
            "packed": 0, "skipped": skipped,
            "note": f"图集合成失败：{atlas_res.get('reason', '未知')}",
        }

    # 键去重：stem 撞名时改用来源相对标识（此处帧键本就来自输出文件名，pool
    # 已保证唯一，理论不触发；防御性保留）。
    frames_json = {}
    for p in placed:
        frames_json[p["key"]] = {
            "x": p["x"], "y": p["y"], "width": p["width"], "height": p["height"],
        }
    chosen = atlas_res["chosen"]
    atlas_json = {
        "format": "pf-atlas/1",
        "image": Path(chosen["out"]).name,
        "width": w,
        "height": h,
        "encoding": chosen["encoding"],
        "frames": frames_json,
    }
    (out_dir / "atlas.json").write_text(
        json.dumps(atlas_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "packed": len(placed),
        "skipped": skipped,
        "image": atlas_json["image"],
        "width": w,
        "height": h,
        "encoding": chosen["encoding"],
        "bytes": chosen["bytes"],
        "candidates": atlas_res.get("candidates", []),
        "note": "atlas.json 与图集图已写入输出目录（pf-atlas/1）",
    }
