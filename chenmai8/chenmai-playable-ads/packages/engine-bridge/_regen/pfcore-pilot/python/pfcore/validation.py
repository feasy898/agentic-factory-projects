"""pfcore.validation — PlayableSpec 三阶段校验（schema → 不变式 → pydantic）。

spec-contract §2.4/§2.5（冻结）：
- 校验次序：schema 结构 → 不变式 → pydantic 类型化解析（code="model"）；任一阶段失败即止，不合并报告。
- 错误形状 {path, message, code}；path 为 json-path 风格；schema required 错误把缺失字段名补进路径。
- schema 定位：env PF_SPEC_SCHEMA 优先，否则 validation.py 的 parents[2] 仓库根约定（模块位置不可挪）。
- 文件不存在 → io-not-found；JSON 非法 → io-parse；glob 无匹配 → 该模式计一条失败。
"""

from __future__ import annotations

import glob as _glob
import json
import os
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from . import invariants
from .spec_model import build_model

Issue = dict[str, str]

#: 门禁与文档引用的字段路径正则（spec-contract §4）
FIELD_PATH_PATTERN = r"\$\.[A-Za-z_][\w.\[\]]*"


# ---------------------------------------------------------------------------
# schema 定位与加载
# ---------------------------------------------------------------------------


def schema_path() -> Path:
    """env PF_SPEC_SCHEMA 优先，否则 parents[2] 仓库根约定（python/pfcore/validation.py）。"""
    override = os.environ.get("PF_SPEC_SCHEMA")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "packages" / "spec" / "playable-spec.schema.json"


_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def load_schema() -> dict[str, Any]:
    path = schema_path()
    key = str(path)
    cached = _SCHEMA_CACHE.get(key)
    if cached is None:
        with open(path, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        Draft202012Validator.check_schema(cached)
        _SCHEMA_CACHE[key] = cached
    return cached


# ---------------------------------------------------------------------------
# json-path 构造（含 required 缺字段补名约定）
# ---------------------------------------------------------------------------


def _json_path(instance_path: Iterator[Any] | tuple[Any, ...], extra_key: str | None = None) -> str:
    parts = list(instance_path)
    if extra_key is not None:
        parts.append(extra_key)
    out = "$"
    for part in parts:
        if isinstance(part, (int, float)) and not isinstance(part, bool):
            out += f"[{int(part)}]"
        else:
            out += f".{part}"
    return out


def _required_missing_fields(message: str) -> list[str]:
    """从 jsonschema 的 required 错误消息里取缺失字段名（单缺或列表缺）。"""
    import ast

    body = message.split(" is a required property", 1)[0].strip()
    try:
        value = ast.literal_eval(body)
    except (ValueError, SyntaxError):
        value = body.strip("'\"")
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _schema_issues(errors: Iterator[Any]) -> list[Issue]:
    issues: list[Issue] = []
    for err in errors:
        code = f"schema-{err.validator}" if err.validator is not None else "schema"
        if err.validator == "required":
            # 缺字段路径补名约定（两侧一致）：$.flow 而非停 $
            for field in _required_missing_fields(err.message):
                issues.append(
                    {
                        "path": _json_path(err.absolute_path, field),
                        "message": err.message,
                        "code": code,
                    }
                )
        else:
            issues.append(
                {"path": _json_path(err.absolute_path), "message": err.message, "code": code}
            )
    return issues


# ---------------------------------------------------------------------------
# 三阶段校验
# ---------------------------------------------------------------------------


def validate_spec_dict(spec: Any) -> list[Issue]:
    """校验一个已解析的 spec dict；空列表 = 通过。阶段失败即止。"""
    if not isinstance(spec, dict):
        return [
            {
                "path": "$",
                "message": f"spec root must be a JSON object, got {type(spec).__name__}",
                "code": "schema-type",
            }
        ]

    # 阶段 1：schema 结构
    validator = Draft202012Validator(load_schema())
    schema_issues = _schema_issues(validator.iter_errors(spec))
    if schema_issues:
        return schema_issues

    # 阶段 2：不变式（I1–I5 + merge）
    invariant_issues = invariants.check_invariants(spec)
    if invariant_issues:
        return invariant_issues

    # 阶段 3：pydantic 类型化解析（表示层）
    try:
        build_model(spec)
    except Exception as exc:  # pydantic.ValidationError 及任何建模失败
        return [{"path": "$", "message": f"{type(exc).__name__}: {exc}", "code": "model"}]
    return []


def validate_spec_file(path: str | os.PathLike[str]) -> list[Issue]:
    """校验一个 spec 文件；io 失败归一为带路径 issue（io-not-found / io-parse）。"""
    display = str(path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return [{"path": "$", "message": f"file not found: {display}", "code": "io-not-found"}]
    except IsADirectoryError:
        return [{"path": "$", "message": f"not a file: {display}", "code": "io-not-found"}]
    except OSError as exc:
        return [{"path": "$", "message": f"cannot read {display}: {exc}", "code": "io-not-found"}]
    try:
        spec = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [{"path": "$", "message": f"invalid JSON in {display}: {exc}", "code": "io-parse"}]
    return validate_spec_dict(spec)


def expand_targets(targets: list[str]) -> list[tuple[str, list[Issue]]]:
    """展开目标列表（glob 内建展开）；glob 无匹配 → 该模式计一条失败（防静默通过）。

    返回 [(显示名, issues)]，显示名为命令行原样写法（glob 模式）或具体文件路径。
    """
    results: list[tuple[str, list[Issue]]] = []
    for target in targets:
        has_wildcard = any(ch in target for ch in "*?[")
        if has_wildcard:
            matches = sorted(_glob.glob(target))
            if not matches:
                results.append(
                    (
                        target,
                        [
                            {
                                "path": "$",
                                "message": f"glob matched no files: {target}",
                                "code": "io-not-found",
                            }
                        ],
                    )
                )
            else:
                results.extend((match, validate_spec_file(match)) for match in matches)
        else:
            results.append((target, validate_spec_file(target)))
    return results
