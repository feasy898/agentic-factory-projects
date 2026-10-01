"""PlayableSpec 校验入口：schema（draft 2020-12）+ 语义不变式 + 类型化解析。

校验次序与职责：
  1. ``validate_spec_dict``：先用 frozen 的 ``playable-spec.schema.json`` 做结构
     校验（jsonschema Draft 2020-12），错误定位到 json-path 字段路径；
  2. 结构通过后执行 :mod:`pfcore.invariants` 的五条语义不变式（I1-I5）；
  3. 全部通过后用 :mod:`pfcore.spec_model` 做 pydantic 类型化解析（表示层）。

任何一步失败都会以 :class:`SpecIssue`（含 ``$.field.path`` 路径）返回，由 CLI
层决定退出码——有任一 issue 即 exit 1。
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsValidationError

from .invariants import SpecIssue, check_invariants
from .spec_model import ValidationError, parse_spec

#: 缺字段错误的 message 形如 "'flow' is a required property"，用于把缺失字段
#: 补进路径（否则此类错误的 json_path 停留在父层）。
_REQUIRED_RE = re.compile(r"^'([^']+)' is a required property$")


def schema_path() -> Path:
    """schema 文件定位：环境变量 PF_SPEC_SCHEMA 优先，否则仓库根约定位置。"""
    env = os.environ.get("PF_SPEC_SCHEMA")
    if env:
        return Path(env)
    # 本模块经 pip -e 安装后 __file__ 仍指向仓库源码：python/pfcore/validation.py
    # -> parents[2] = 仓库根。
    return Path(__file__).resolve().parents[2] / "packages" / "spec" \
        / "playable-spec.schema.json"


@lru_cache(maxsize=4)
def load_validator(schema_file: str) -> Draft202012Validator:
    with open(schema_file, encoding="utf-8") as fh:
        schema = json.load(fh)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_issues(spec: dict) -> list[SpecIssue]:
    validator = load_validator(str(schema_path()))
    issues: list[SpecIssue] = []
    for err in sorted(validator.iter_errors(spec),
                      key=lambda e: (list(e.absolute_path), e.validator)):
        path = err.json_path
        m = _REQUIRED_RE.match(err.message or "")
        if err.validator == "required" and m:
            path = f"{path}.{m.group(1)}"
        issues.append(SpecIssue(path, err.message.splitlines()[0],
                                f"schema-{err.validator}"))
    return issues


def validate_spec_dict(spec: dict) -> list[SpecIssue]:
    """校验一个已反序列化的 spec dict，返回问题清单（空 = 通过）。"""
    if not isinstance(spec, dict):
        return [SpecIssue("$", f"顶层必须是 JSON object，得到 {type(spec).__name__}",
                          "schema-type")]
    issues = _schema_issues(spec)
    if issues:
        return issues
    issues = check_invariants(spec)
    if issues:
        return issues
    try:
        parse_spec(spec)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "$"
            issues.append(SpecIssue(f"$.{loc}", err["msg"], "model"))
    return issues


def validate_spec_file(path: str | Path) -> list[SpecIssue]:
    """校验一个 spec 文件；文件不存在/JSON 非法也归一为带路径的 issue。"""
    file = Path(path)
    if not file.is_file():
        return [SpecIssue("$", f"文件不存在：{file}", "io-not-found")]
    try:
        with open(file, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return [SpecIssue("$", f"读取/解析失败：{exc}", "io-parse")]
    return validate_spec_dict(spec)
