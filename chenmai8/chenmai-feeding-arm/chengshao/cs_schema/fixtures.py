"""夹具装载：契约样例数据的读写助手。

fixtures/ 目录存放每个契约模型的合法样例 JSON（测试与评审共用）。
命名约定：文件名 = 模型类名的 snake_case（MouthPose -> mouth_pose.json），
复合样例可带后缀（arm_command_joints.json / safety_state_estop.json）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_ModelT = TypeVar("_ModelT", bound=BaseModel)

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def fixture_path(name: str) -> Path:
    """返回夹具文件路径（不含校验，供定位与报错）。"""
    return FIXTURES_DIR / f"{name}.json"


def load_fixture(name: str) -> dict[str, Any]:
    """按名装载夹具原始 dict（UTF-8）。"""
    path = fixture_path(name)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_model(name: str, model_cls: type[_ModelT]) -> _ModelT:
    """装载夹具并按契约模型校验，返回模型实例。"""
    return model_cls.model_validate(load_fixture(name))


def load_model_fixture(model_cls: type[_ModelT]) -> _ModelT:
    """按类名装载同名夹具（MouthPose -> mouth_pose.json）。"""
    name = _CAMEL_BOUNDARY.sub("_", model_cls.__name__).lower()
    return load_model(name, model_cls)


def save_fixture(name: str, model: BaseModel) -> Path:
    """把模型实例写回夹具文件（维护工具用；UTF-8、中文不转义）。"""
    path = fixture_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "FIXTURES_DIR",
    "fixture_path",
    "load_fixture",
    "load_model",
    "load_model_fixture",
    "save_fixture",
]
