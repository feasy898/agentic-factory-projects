"""configs/ 目录读取助手（路径解析基准 = configs/ 目录本身）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#: 仓库根/pipeline/config.py → parents[1] = 仓库根
REPO_ROOT = Path(__file__).resolve().parents[1]
#: 默认配置目录：<仓库根>/configs
CONFIG_DIR = REPO_ROOT / "configs"


def load_yaml(path: str | Path) -> dict[str, Any]:
    """读取 YAML 文件为 dict（空文件返回 {}）。"""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data or {}


def _resolve(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()


def load_pipeline_config(configs_dir: str | Path | None = None) -> dict[str, Any]:
    """读取 pipeline.yaml，并把 paths.* 解析为绝对路径（相对 configs/ 目录）。"""
    base = Path(configs_dir) if configs_dir else CONFIG_DIR
    cfg = load_yaml(base / "pipeline.yaml")
    paths = cfg.get("paths") or {}
    for key, value in list(paths.items()):
        if isinstance(value, str):
            paths[key] = str(_resolve(base, value))
    return cfg


def jobs_dir(configs_dir: str | Path | None = None) -> Path:
    """默认 jobs 根目录（pipeline.yaml paths.jobs_dir，相对 configs/ 解析）。"""
    cfg = load_pipeline_config(configs_dir)
    return Path(cfg["paths"]["jobs_dir"])
