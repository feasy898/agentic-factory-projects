"""对外命名检查：扫描仓库，确保公开内容不泄漏上游参考项目的名称。

CI 式用法（作为 e2e 前置，见开发指令 §10.5）::

    python chengshao/scripts/check_naming.py            # 扫描 git 仓库根
    python chengshao/scripts/check_naming.py --root PATH

退出码：0 = 干净；1 = 存在禁用名。WARNING 级只提示不判失败，需人工复核。

规则说明（刻意为之，非疏漏）：
- 本脚本自身包含禁用词的字面量（否则无法 grep），扫描时豁免本文件；
- 依赖清单（requirements*.txt）**不再整体豁免**（审查 E16）：逐行解析出
  pip 包名本身放行（生态依赖的发行名不可避免，属依赖声明而非内容引用），
  行内其余文本（版本约束后的杂注、行尾/整行注释、非法requirement 行）仍按
  全部规则扫描——上游名不得借注释或杂注混入清单；
- pyproject/uv.lock 等打包器机器输出（MANIFEST_NAMES）仍整体豁免；
- _vendor/（上游参考件克隆，gitignore）与 .venv/ 等本地目录不在扫描范围；
- **符号链接不跟随**（v3.1）：仓库内的 symlink（如临时挂进来的外部工程）
  不是本仓库内容——git 只存链接本身、从不跟随，扫描口径与 git 对齐。
"""

from __future__ import annotations

import argparse
import os
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
    ".zcode",  # agent 工具运行时目录（gitignore，非仓库内容）
    "build", "dist", "data", "models",
}

# 打包器机器输出（整体豁免）：pip freeze 之外的锁定/打包格式，逐行语义
# 解析不可靠（嵌套字符串表、哈希续行等），维持豁免并在此记录。
# requirements*.txt 不在此列——走 _strip_requirement_name() 的包名白名单。
MANIFEST_NAMES = {
    "pyproject.toml", "setup.py", "setup.cfg", "uv.lock", "poetry.lock",
    "Pipfile", "Pipfile.lock", "environment.yml",
}

# pip requirement 行的包名头部：name[extras] 后跟版本约束/环境标记/行尾
_REQ_NAME_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<extras>\[[^\]]*\])?\s*"
    r"(?P<rest>$|[=<>!~;(]|@)"
)

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


def _strip_requirement_name(line: str) -> str:
    """requirements 行：剥掉 pip 包名本身（发行名白名单），其余文本照扫。

    - `huggingface_hub==1.33.0` -> `==1.33.0`（包名放行）；
    - 整行/行尾注释、`-r`/`--hash` 等选项行、解析不出 requirement 头的行
      原样返回（全部文本参与扫描）。
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("-"):
        return line
    m = _REQ_NAME_RE.match(line)
    if not m:
        return line
    return line[: m.start()] + line[m.end():]


def _under_symlink(path: Path, root: Path) -> bool:
    """path（含各级祖先，root 之下）是否经过符号链接/目录联接（junction）。

    Windows 下 Git Bash 的 ``ln -s`` 可能落成 junction，``Path.is_symlink``
    不识别 junction，故用 realpath 解析结果与字面路径比对（解析后跳出
    原位即链）。
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    cur = root
    for part in rel.parts:
        cur = cur / part
        try:
            if os.path.realpath(str(cur)) != os.path.abspath(str(cur)):
                return True
        except OSError:
            return True
    return False


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
        if _under_symlink(path, root):
            continue  # 仓库内 symlink 指向的外部内容不是本仓库内容（与 git 口径一致）
        yield path


def _match_lines(patterns: list[re.Pattern[str]], path: Path,
                 manifest: bool = False) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        if manifest and path.name.startswith("requirements"):
            line = _strip_requirement_name(line)  # 包名白名单：只放行发行名本身
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
        manifest = _is_manifest(path)
        hits = _match_lines(pat_all, path, manifest=manifest) + _match_lines(
            pat_code, path, manifest=manifest
        )
        failures.extend(f"FORBIDDEN {rel}:{ln}: {name!r}" for ln, name in hits)

        for pat, why in pat_warn:
            for ln, name in _match_lines([pat], path, manifest=manifest):
                warns.append(f"WARNING  {rel}:{ln}: {name!r} — {why}")

    for line in warns:
        print(line)
    for line in failures:
        print(line, file=sys.stderr)

    print(f"check_naming: root={root} forbidden={len(failures)} warnings={len(warns)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
