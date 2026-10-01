"""配置加载: settings.yaml + api.env + 路径解析。

约定:
- 项目根 = 环境变量 CRADLE_ROOT, 否则 src/ 的上一级目录。
- api.env 为空(缺 BASE/KEY/MODEL)时, 该能力直接走本地兜底 (D-004)。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("CRADLE_ROOT", Path(__file__).resolve().parents[1]))


def project_root() -> Path:
    return Path(os.environ.get("CRADLE_ROOT", ROOT))


def settings_path() -> Path:
    return project_root() / "config" / "settings.yaml"


def api_env_path() -> Path:
    return project_root() / "config" / "api.env"


def default_db_path(settings: dict | None = None) -> Path:
    settings = settings or load_settings()
    p = settings.get("paths", {}).get("db", "workdir/cradle.sqlite3")
    return project_root() / p


def load_settings(path: str | os.PathLike | None = None) -> dict:
    """读取 settings.yaml; 文件缺失时返回内置默认值(与 config/settings.yaml 一致)。"""
    import yaml

    p = Path(path) if path else settings_path()
    if not p.exists():
        return _default_settings()
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    merged = _default_settings()
    merged.update(data)
    for k in ("paths", "budgets"):
        if k in data and isinstance(data[k], dict):
            merged[k] = {**_default_settings()[k], **data[k]}
    return merged


def _default_settings() -> dict:
    return {
        "project": "cradle",
        "device": "cuda",
        "dtype": "fp16",
        "hf_endpoint": "https://hf-mirror.com",
        "paths": {
            "assets": "assets",
            "candidates": "workdir/candidates",
            "gated": "workdir/gated",
            "output": "output",
            "db": "workdir/cradle.sqlite3",
        },
        "budgets": {
            "image_api": 300,
            "vlm_api": 1500,
            "tts_api": 200,
            "asr_api": 200,
            "wan_candidates_total": 200,
        },
        "debug_model": "ltx",
        "prod_model": "wan_i2v_13b",
        # M5 生产口径: Wan steps 缺省 20 (D-030 实测 364.9s/条, <6min); 首帧风格统一 denoise,
        # 0=关闭(调试期缺省), 生产沙箱设 0.3 (SPECS §5.3, M5 阶段0.4)
        "prod_steps": 20,
        "prod_stylize_denoise": 0.0,
    }


def parse_api_env(path: str | os.PathLike | None = None) -> dict:
    """解析 KEY=VALUE 格式的 api.env。兼容 ``X_MODEL`` 与 ``X_API_MODEL`` 两种命名。

    返回形如 {"image": {"base":..., "key":..., "model":...}, ...} 的 dict,
    base/key/model 任一为空即视为"未配置该能力"(走本地兜底)。
    """
    p = Path(path) if path else api_env_path()
    flat: dict[str, str] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            flat[k.strip()] = v.strip()

    def cap(name: str) -> dict:
        base = flat.get(f"{name}_API_BASE", "")
        key = flat.get(f"{name}_API_KEY", "")
        model = flat.get(f"{name}_MODEL", flat.get(f"{name}_API_MODEL", ""))
        return {"base": base, "key": key, "model": model, "configured": bool(base and key and model)}

    return {name: cap(name) for name in ("IMAGE", "VLM", "TTS", "ASR")}
