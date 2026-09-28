"""对外命名检查：扫描仓库，确保公开内容不泄漏上游参考项目的名称。

CI 式用法（作为 e2e 前置，见开发指令 §10.5）::

    python chengshao/scripts/check_naming.py            # 扫描 git 仓库根
    python chengshao/scripts/check_naming.py --root PATH

退出码：0 = 干净；1 = 存在禁用名。WARNING 级只提示不判失败，需人工复核。

规则说明（刻意为之，非疏漏）：
- 本脚本自身包含禁用词的字面量（否则无法 grep），扫描时豁免本文件；
- 依赖清单（requirements*.txt / pyproject.toml / uv.lock 等）为 pip freeze /
  打包器的机器输出，其中生态依赖的发行名不可避免，整体豁免（见下 MANIFEST_NAMES）。
- _vendor/（上游参考件克隆，gitignore）与 .venv/ 等本地目录不在扫描范围。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# ---- 一级禁用：任何入库文件（含依赖清单）都不得出现 ----------------------
FORBIDDEN_ALL: list[str] = [
    r"huggingface",
    r"therobotstudio",
    r"personalrobotics",
    r"tonyzhaozh",
    r"\bso[-_]?arm(?:[-_]?100)?\b",   # SO-ARM / SO_ARM / SO-ARM100
    r"\bso[-_]?10[01]\b",             # SO-100 / SO101 / so_100 ...
    r"\bada[-_]feeding\b",
]

# ---- 二级禁用：代码/文档不得出现；依赖清单（pip 包名）豁免 ----------------
FORBIDDEN_EXCEPT_MANIFESTS: list[str] = [
    r"\ble[-_]?robot(?:dataset)?\b",  # LeRobot / lerobot / LeRobotDataset
]

# ---- 警告级：不判失败，人工复核 ------------------------------------------
WARNINGS: list[tuple[str, str]] = [
    (r"\bACT\b", "通用缩写，请确认非指代上游策略仓库名"),
    (r"\bsmolvla\b", "上游内置模型代号，公开文档请改用中性描述"),
]

SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "_vendor", "node_modules",
    ".pytest_cache", ".ruff_cache", ".mypy_cache", ".idea", ".vscode",
    "build", "dist", "data", "models",
}

# 依赖清单（requirements*/pyproject 等）整体豁免：它们是 pip freeze / 打包器的
# 机器输出，生态依赖的发行名（含传递依赖）不可避免，属依赖声明而非内容引用上游。
# 构建指令 §2/§4 既要求入库全量 freeze、又要求经 pip 安装参考栈，故均不检查。
MANIFEST_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "uv.lock", "poetry.lock",
    "Pipfile", "Pipfile.lock", "environment.yml",
    # requirements* 由 _is_manifest() 的前缀规则覆盖
}

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf",
    ".npz", ".npy", ".db", ".sqlite", ".sqlite3", ".task", ".onnx",
    ".pt", ".pth", ".ckpt", ".safetensors", ".bin", ".zip", ".gz", ".tgz",
    ".7z", ".rar", ".whl", ".exe", ".dll", ".so", ".dylib", ".mp4", ".mp3",
    ".wav", ".avi", ".mkv", ".mov", ".flac", ".ogg",
}


def _git_toplevel() -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(out) if out else None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _is_manifest(path: Path) -> bool:
    return path.name in MANIFEST_NAMES or path.name.startswith("requirements")


def _iter_text_files(root: Path, self_path: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path == self_path:
            continue  # 本文件含禁用词字面量（黑名单本体），豁免
        if path.suffix.lower() in BINARY_EXTS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _match_lines(patterns: list[re.Pattern[str]], path: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pat in patterns:
            m = pat.search(line)
            if m:
                hits.append((lineno, m.group(0)))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="上游名称泄漏检查（CI 前置）")
    parser.add_argument("--root", type=Path, default=None, help="扫描根目录（默认 git 仓库根）")
    args = parser.parse_args(argv)

    root = args.root or _git_toplevel() or Path(__file__).resolve().parents[2]
    self_path = Path(__file__).resolve()

    pat_all = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_ALL]
    pat_code = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_EXCEPT_MANIFESTS]
    pat_warn = [(re.compile(p, re.IGNORECASE), why) for p, why in WARNINGS]

    failures: list[str] = []
    warns: list[str] = []

    for path in _iter_text_files(root, self_path):
        rel = path.relative_to(root).as_posix()
        if not _is_manifest(path):
            hits = _match_lines(pat_all, path) + _match_lines(pat_code, path)
            failures.extend(f"FORBIDDEN {rel}:{ln}: {name!r}" for ln, name in hits)

            for pat, why in pat_warn:
                for ln, name in _match_lines([pat], path):
                    warns.append(f"WARNING  {rel}:{ln}: {name!r} — {why}")

    for line in warns:
        print(line)
    for line in failures:
        print(line, file=sys.stderr)

    print(f"check_naming: root={root} forbidden={len(failures)} warnings={len(warns)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
