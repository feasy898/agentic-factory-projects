"""配置加载：YAML 主配置 + 环境变量覆盖（全模块共用，M0 定稿）。

规则：
1. 主配置 ``config/app.yaml``；部门 key 映射 ``config/dept_keys.yaml``。
2. 环境变量覆盖：对顶层键 K，若存在环境变量 ``ANONGW_<K 大写>``（如
   ``ANONGW_LISTEN``、``ANONGW_SESSION_TTL_H``），其值覆盖 yaml；
   值按 JSON 解析（int/bool/list 生效），解析失败则按原样字符串。
3. 密钥不写进任何配置文件：yaml 只存环境变量 *名*（``mask_key_env``、
   ``api_key_env``），运行时经 :func:`resolve_secret` 解析。
4. ``.env`` 文件可用 :func:`load_env_file` 预载（默认不覆盖已有环境变量）。

全部 I/O 显式 UTF-8；路径用 pathlib。
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

ENV_PREFIX = "ANONGW_"
REPO_ROOT = Path(__file__).resolve().parents[1]


class UpstreamCfg(BaseModel):
    """单条上游定义（字段即契约，只增不改名）。"""

    model_config = ConfigDict(extra="allow")

    name: str
    base_url: str
    api_key_env: str
    models: list[str] = Field(default_factory=list)
    route: str = "INTERNET"  # INTERNET | GOVCLOUD


class ThresholdsCfg(BaseModel):
    """路由/识别阈值（字段即契约，只增不改名）。"""

    model_config = ConfigDict(extra="allow")

    batch_pii_to_govcloud: int = 3


class AppConfig(BaseModel):
    """主配置模型（字段即契约，只增不改名）。"""

    model_config = ConfigDict(extra="allow")

    listen: int = 9000
    mask_key_env: str = "MASK_KEY"
    session_ttl_h: int = 24
    upstreams: list[UpstreamCfg] = Field(default_factory=list)
    ai_label: str = "本内容由AI生成"
    thresholds: ThresholdsCfg = Field(default_factory=ThresholdsCfg)
    # 库文件（T1.3，相对路径按仓库根解析）：审计库与会话映射库**必须分文件**——
    # 审计库要过 bytes 级全文件零明文扫描（§9 U5），而 masking_map 必须存归一化
    # 原值才能还原（见 masking/session_store.py 模块文档）
    audit_db: str = "data/audit.db"
    session_db: str = "data/session_map.db"


def _override_from_env(data: dict[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    for key in list(data.keys()):
        env_name = ENV_PREFIX + str(key).upper()
        if env_name in env:
            raw = env[env_name]
            try:
                data[key] = json.loads(raw)
            except (ValueError, TypeError):
                data[key] = raw
    return data


def load_app_config(path: str | Path | None = None, env: Mapping[str, str] | None = None) -> AppConfig:
    """加载主配置；``env`` 传 None 时读真实进程环境（便于测试注入）。"""
    p = Path(path) if path else REPO_ROOT / "config" / "app.yaml"
    raw_env = os.environ if env is None else env
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"app config must be a mapping: {p}")
    data = _override_from_env(data, raw_env)
    return AppConfig.model_validate(data)


def load_dept_keys(path: str | Path | None = None) -> dict[str, str]:
    """返回 部门名 -> key 的 sha256 十六进制（小写）。库存哈希，永不存明文。"""
    p = Path(path) if path else REPO_ROOT / "config" / "dept_keys.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    departments = data.get("departments") or {}
    out: dict[str, str] = {}
    for dept, digest in departments.items():
        d = str(digest).strip().lower()
        if len(d) != 64 or any(c not in "0123456789abcdef" for c in d):
            raise ValueError(f"dept key digest invalid for {dept!r}")
        out[str(dept)] = d
    if not out:
        raise ValueError("no departments configured")
    return out


def resolve_secret(
    env_name: str, env: Mapping[str, str] | None = None, required: bool = True
) -> str | None:
    """按环境变量名解析密钥；缺失时 required=True 抛 RuntimeError，否则返回 None。"""
    raw_env = os.environ if env is None else env
    val = raw_env.get(env_name)
    if val is None or val == "":
        if required:
            raise RuntimeError(f"missing required secret env: {env_name}")
        return None
    return val


def load_env_file(path: str | Path | None = None, override: bool = False) -> list[str]:
    """极简 .env 加载（KEY=VALUE，# 注释；不覆盖已有环境变量）。返回实际写入的键名。"""
    p = Path(path) if path else REPO_ROOT / ".env"
    loaded: list[str] = []
    if not p.exists():
        return loaded
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = val
            loaded.append(key)
    return loaded
