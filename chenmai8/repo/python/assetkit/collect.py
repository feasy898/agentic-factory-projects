"""assetkit 素材收集：目录/文件参数 + spec 声明素材 → 去重后的素材清单。

spec 声明素材的路径解析次序与模板构建脚本（packages/templates/*/build.mjs）
逐字对齐：先相对 spec 文件目录，再相对仓库根；两处都不存在则不收集（由构建
脚本按"缺素材回退"语义告警，assetkit 不越权替构建器裁决）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma"}
FONT_EXTS = {".ttf", ".otf", ".ttc"}


@dataclass
class Material:
    """一个待处理素材：绝对路径 + optmap 键 + 类别。"""

    src: Path
    key: str  # optmap 键：spec 声明的相对路径串（spec 来源）或规范化绝对路径
    kind: str  # image | audio | font


def classify(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in FONT_EXTS:
        return "font"
    return None


def _norm_abs(p: Path) -> Path:
    return Path(p).expanduser().resolve()


def spec_asset_rel_paths(spec: dict) -> list[str]:
    """按声明顺序取 spec.assets 里的全部素材相对路径串（存在性后置判断）。"""
    assets = spec.get("assets") or {}
    rels: list[str] = []
    bg = assets.get("background")
    if isinstance(bg, str) and bg:
        rels.append(bg)
    for rel in (assets.get("sprites") or {}).values():
        if isinstance(rel, str) and rel:
            rels.append(rel)
    for rel in (assets.get("audio") or {}).values():
        if isinstance(rel, str) and rel:
            rels.append(rel)
    fs = assets.get("fontSubset")
    if isinstance(fs, str) and fs:
        rels.append(fs)
    return rels


def resolve_spec_asset(rel: str, spec_dir: Path, repo_root: Path) -> Path | None:
    """与模板构建脚本同次序的相对路径解析；找不到返回 None。"""
    for base in (spec_dir, repo_root):
        cand = (base / rel).resolve()
        if cand.is_file():
            return cand
    return None


def collect(
    inputs: list[str | Path],
    spec_path: Path | None,
    repo_root: Path | None = None,
) -> list[Material]:
    """收集素材：spec 声明优先（键用声明串），其后目录/文件参数（键用绝对路径）。

    同一文件只收一次（按规范化绝对路径去重，先到先得）。目录递归收集，符号
    链接不跟随（防环）。不可识别扩展名的文件直接忽略（收集面即四类素材）。
    """
    root = _norm_abs(repo_root) if repo_root else Path.cwd()
    found: dict[str, Material] = {}

    def _add(src: Path, key: str) -> None:
        abs_src = _norm_abs(src)
        if str(abs_src) in found:
            return
        kind = classify(abs_src)
        if kind is None:
            return
        found[str(abs_src)] = Material(src=abs_src, key=key, kind=kind)

    # 1) spec 声明素材（键 = spec 里的声明串，模板构建脚本按同串接线）
    if spec_path is not None:
        spec_file = _norm_abs(spec_path)
        if not spec_file.is_file():
            raise FileNotFoundError(f"spec 不存在：{spec_file}")
        spec = json.loads(spec_file.read_text(encoding="utf-8"))
        spec_dir = spec_file.parent
        for rel in spec_asset_rel_paths(spec):
            abs_path = resolve_spec_asset(rel, spec_dir, root)
            if abs_path is not None:
                _add(abs_path, rel)

    # 2) 显式输入（目录递归 / 单文件）
    for item in inputs:
        p = Path(item).expanduser()
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    _add(f, str(_norm_abs(f)))
        elif p.is_file():
            _add(p, str(_norm_abs(p)))
        # 不存在的输入路径静默忽略：调用方（CLI/make）只关心收进了什么，
        # 报告里有逐素材清单，缺了什么一目了然。

    return list(found.values())
