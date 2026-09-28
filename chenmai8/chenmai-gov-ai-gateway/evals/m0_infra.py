"""M0 基础设施验收：安装自检 + 配置加载 + 名称守卫零命中。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m0_infra

exit 0 = 通过。检查项：
1. 运行于仓库 venv；``pip install -e .`` 生效（本项目发行版元数据存在）；
2. 主依赖与扩展组（dev/ocr/ml）全部可导入，版本钉子匹配 config/install_check.json；
3. config/app.yaml 加载 + 字段契约 + ANONGW_* 环境覆盖 + 密钥解析 + .env 加载；
4. config/dept_keys.yaml：3 个部门、sha256 格式合法；
5. ops/name_lint.py 全仓零命中（标准档），词表非空；
6. constraints.txt 存在且为 pip freeze 形态；.env.example/.gitignore 卫生。
"""
from __future__ import annotations

import importlib
import importlib.metadata as md
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.config import (  # noqa: E402
    load_app_config,
    load_dept_keys,
    load_env_file,
    resolve_secret,
)
from ops import name_lint  # noqa: E402

INSTALL_CHECK = REPO_ROOT / "config" / "install_check.json"
RESULTS: list[tuple[bool, str]] = []


def _record(name: str, fn):
    try:
        detail = fn()
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _load_install_check() -> dict[str, Any]:
    data = json.loads(INSTALL_CHECK.read_text(encoding="utf-8"))
    for group in ("main", "extras"):
        if not data.get(group):
            raise ValueError(f"install_check missing group {group!r}")
    return data


def _version_matches(version: str, spec: str) -> bool:
    """spec 形如 '10.14.*' / '40.*'：按点分段前缀匹配。"""
    prefix = spec.replace(".*", "").split(".")
    actual = version.split(".")
    return len(actual) >= len(prefix) and actual[: len(prefix)] == prefix


def _version_at_least(version: str, floor: str) -> bool:
    def nums(v: str) -> list[int]:
        out = []
        for part in v.split(".")[: len(floor.split("."))]:
            digits = "".join(ch for ch in part if ch.isdigit())
            out.append(int(digits or 0))
        return out

    return nums(version) >= nums(floor)


# ── 1. 安装自检 ────────────────────────────────────────────────────
def check_venv() -> str:
    running = Path(sys.executable).resolve()
    expected = (REPO_ROOT / ".venv" / "Scripts" / "python.exe").resolve()
    if running != expected:
        raise AssertionError(f"not running under repo venv: {running}")
    return str(running)


def check_self_install() -> str:
    md.version("gov-anon-gateway")  # 未安装则 PackageNotFoundError
    for pkg in ("common", "ops", "evals"):
        importlib.import_module(pkg)
    return "editable install + project packages importable"


def check_deps(group: str):
    entries = _load_install_check()[group]

    def run() -> str:
        problems: list[str] = []
        versions: list[str] = []
        for entry in entries:
            dist = entry["dist"]
            try:
                ver = md.version(dist)
            except md.PackageNotFoundError:
                problems.append(f"{dist}: not installed")
                continue
            if "pin" in entry and not _version_matches(ver, entry["pin"]):
                problems.append(f"{dist}=={ver} !~ {entry['pin']}")
            if "min" in entry and not _version_at_least(ver, entry["min"]):
                problems.append(f"{dist}=={ver} < {entry['min']}")
            if "import" in entry:
                try:
                    importlib.import_module(entry["import"])
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"import {entry['import']}: {type(exc).__name__}: {exc}")
            versions.append(f"{dist}=={ver}")
        if problems:
            raise AssertionError("; ".join(problems))
        return f"{len(entries)} dists ok ({'; '.join(versions)})"

    return run


# ── 2. 配置加载 ────────────────────────────────────────────────────
def check_app_config() -> str:
    cfg = load_app_config()
    assert cfg.listen == 9000, f"listen={cfg.listen}"
    assert cfg.mask_key_env == "MASK_KEY"
    assert cfg.session_ttl_h == 24, f"session_ttl_h={cfg.session_ttl_h}"
    assert len(cfg.upstreams) >= 2, "need >=2 upstreams"
    routes = set()
    for upstream in cfg.upstreams:
        assert upstream.name and upstream.base_url and upstream.api_key_env
        assert upstream.models, f"{upstream.name}: empty models"
        assert upstream.route in {"INTERNET", "GOVCLOUD", "BLOCK"}
        routes.add(upstream.route)
    assert {"INTERNET", "GOVCLOUD"} <= routes, f"routes={routes}"
    assert cfg.ai_label, "ai_label empty"
    assert cfg.thresholds.batch_pii_to_govcloud == 3
    names = ",".join(u.name for u in cfg.upstreams)
    return f"listen={cfg.listen}, upstreams=[{names}], ai_label={cfg.ai_label!r}"


def check_env_override() -> str:
    injected = load_app_config(env={"ANONGW_LISTEN": "9100", "ANONGW_SESSION_TTL_H": "48"})
    assert injected.listen == 9100 and injected.session_ttl_h == 48
    label_case = load_app_config(env={"ANONGW_AI_LABEL": "测试标识"})
    assert label_case.ai_label == "测试标识"
    untouched = load_app_config(env={})
    assert untouched.listen == 9000 and untouched.session_ttl_h == 24

    key = "ANONGW_LISTEN"
    old = os.environ.get(key)
    os.environ[key] = "9200"
    try:
        assert load_app_config().listen == 9200, "os.environ override not applied"
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old
    return "ANONGW_* overrides apply (int + str), no cross-contamination"


def check_secrets() -> str:
    assert resolve_secret("M0_PROBE_SECRET", env={"M0_PROBE_SECRET": "abc"}) == "abc"
    assert resolve_secret("M0_PROBE_SECRET", env={}, required=False) is None
    try:
        resolve_secret("M0_PROBE_SECRET", env={})
    except RuntimeError:
        pass
    else:
        raise AssertionError("missing required secret did not raise")
    return "resolve_secret ok (present/optional/required-missing)"


def check_env_file() -> str:
    probe_dir = REPO_ROOT / "data"
    probe_dir.mkdir(exist_ok=True)
    probe = probe_dir / "m0_envfile_probe.env"
    probe.write_text("# comment\nM0_ENVFILE_PROBE=hello\n", encoding="utf-8")
    try:
        os.environ.pop("M0_ENVFILE_PROBE", None)
        loaded = load_env_file(probe)
        assert loaded == ["M0_ENVFILE_PROBE"], loaded
        assert os.environ.get("M0_ENVFILE_PROBE") == "hello"
        os.environ["M0_ENVFILE_PROBE"] = "keep-me"
        loaded2 = load_env_file(probe, override=False)
        assert loaded2 == [] and os.environ["M0_ENVFILE_PROBE"] == "keep-me"
    finally:
        os.environ.pop("M0_ENVFILE_PROBE", None)
        probe.unlink(missing_ok=True)
    return "load_env_file ok (parse / no-override)"


def check_dept_keys() -> str:
    departments = load_dept_keys()
    assert len(departments) == 3, f"expect 3 departments, got {len(departments)}"
    for dept, digest in departments.items():
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), dept
    return "3 departments, sha256 digests valid"


# ── 3. 名称守卫 ────────────────────────────────────────────────────
def check_name_lint() -> str:
    violations, scanned = name_lint.lint_repo(REPO_ROOT)
    assert not violations, "; ".join(f"{r}:{l}:{t}" for r, l, t in violations[:20])
    wordlist = (REPO_ROOT / "ops" / "forbidden_names.txt").read_text(encoding="utf-8")
    entries = [ln for ln in wordlist.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert len(entries) >= 10, f"wordlist too small: {len(entries)}"
    return f"{scanned} files scanned, 0 violations, {len(entries)} patterns"


def check_env_example_and_gitignore() -> str:
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("MASK_KEY=", "MOCK_KEY="):
        assert key in env_example, f"missing {key} in .env.example"
    assert "UPSTREAM_" in env_example, "missing UPSTREAM_*_KEY placeholder"
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore and "!.env.example" in gitignore, ".gitignore must ignore .env but keep .env.example"
    return ".env.example placeholders + .gitignore exception ok"


def check_constraints() -> str:
    path = REPO_ROOT / "constraints.txt"
    assert path.exists(), "constraints.txt missing (run: pip freeze > constraints.txt)"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 20, f"constraints.txt too thin: {len(lines)} lines"
    assert not any(ln.startswith(("-e ", "common")) for ln in lines), "constraints must be pure freeze (no -e lines)"
    return f"{len(lines)} pinned distributions"


def main() -> int:
    _record("venv", check_venv)
    _record("self-install", check_self_install)
    _record("deps:main", check_deps("main"))
    _record("deps:extras(dev/ocr/ml)", check_deps("extras"))
    _record("config:app.yaml", check_app_config)
    _record("config:env-override", check_env_override)
    _record("config:secrets", check_secrets)
    _record("config:env-file", check_env_file)
    _record("config:dept_keys.yaml", check_dept_keys)
    _record("name-lint", check_name_lint)
    _record("env-example+gitignore", check_env_example_and_gitignore)
    _record("constraints.txt", check_constraints)

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M0 INFRA: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
