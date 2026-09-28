"""合成人名/单位/职业语料（M8 · T1.1）。

第三方语料库模块名只写在 ``config/synthetic_corpus.yaml``（公开仓库卫生，铁律 E），
本模块经 importlib 按配置动态加载，源码不得硬编码库名；加载失败时报错并给出
配置位置，不做静默降级。
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from common.config import REPO_ROOT

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "synthetic_corpus.yaml"


def load_corpus_config(path: str | Path | None = None) -> dict[str, Any]:
    """读取合成语料依赖坐标（personas / pdf_writer 两组 module/factory 坐标）。"""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    for group in ("personas", "pdf_writer"):
        if not isinstance(data.get(group), dict) or not data[group].get("module"):
            raise ValueError(f"synthetic corpus config missing group {group!r}: {p}")
    return data


class Personas:
    """按 seed 播种的合成人名/单位/职业提供器（确定性：同 seed 同序列）。"""

    def __init__(self, seed: int, config_path: str | Path | None = None) -> None:
        cfg = load_corpus_config(config_path)["personas"]
        module = importlib.import_module(str(cfg["module"]))
        factory = getattr(module, str(cfg.get("factory", "Factory")))
        self._f = factory(str(cfg.get("locale", "zh_CN")))
        self._f.seed_instance(seed)

    def person_name(self) -> str:
        """中文人名（2-4 字）。"""
        return self._f.name()

    def company_name(self) -> str:
        """企业/单位名。"""
        return self._f.company()

    def job_title(self) -> str:
        """职业/岗位名。"""
        return self._f.job()
