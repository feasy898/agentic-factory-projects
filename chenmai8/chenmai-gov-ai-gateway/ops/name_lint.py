#!/usr/bin/env python3
"""名称守卫：扫描仓库源码/文档中的禁用上游项目名与许可证字样（公开仓库卫生把关）。

公开仓库的代码、注释、README 一律使用中性名，不得出现内部对照词表中的
上游项目名/许可证字样；词表见 ``ops/forbidden_names.txt``。

用法::

    python ops/name_lint.py                 # 标准档：扫源码与文档
    python ops/name_lint.py --strict        # 严格档：额外扫描 yaml/toml/json 等配置
    python ops/name_lint.py --root <dir>    # 指定根目录（默认仓库根）

退出码：0 = 零命中；1 = 有命中或词表缺失/为空。

范围与豁免（有意设计，勿随意收紧）：
- 默认扫描后缀：.py .md .txt .html .js .ts .css .sh .bat .ps1（源码/注释/文档）；
- 严格档额外扫 .yaml .yml .toml .json .cfg .ini（用于公开导出前的终检）；
- 排除目录：.git .venv venv plan third_party data node_modules __pycache__ .zcode（本地工具状态）等；
- 永远豁免的文件：constraints.txt、pyproject.toml、third_party/PINNED.txt、
  ops/clone_oss.sh（内部克隆坐标）、LICENSE*、词表自身、各锁文件——
  依赖清单/锁文件/克隆坐标必须携带真实 pip 包名与上游地址，
  公开版依赖清单由导出阶段（ops/export_public.py）统一替换后另走严格档终检；
- 配置文件默认不扫：第三方库的模块名只允许出现在 config/ 中，
  源码经 importlib 按配置动态加载，不得硬编码库名（本仓库唯一允许的携带方式）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORDLIST_PATH = Path(__file__).resolve().parent / "forbidden_names.txt"

DEFAULT_SCAN_SUFFIXES = {".py", ".md", ".txt", ".html", ".js", ".ts", ".css", ".sh", ".bat", ".ps1"}
STRICT_EXTRA_SUFFIXES = {".yaml", ".yml", ".toml", ".json", ".cfg", ".ini"}
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "plan", "third_party", "data", "node_modules",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "dist", "build", "out", "tmp",
    ".zcode",  # 本地工作流工具状态（自持 .gitignore，非仓库源码，T1.4）
}
ALWAYS_EXCLUDED_FILES = {
    "constraints.txt", "pyproject.toml", "pinned.txt", "forbidden_names.txt",
    "clone_oss.sh", "package-lock.json", "poetry.lock", "uv.lock", "pipfile.lock",
}


def load_patterns(wordlist_path: Path = WORDLIST_PATH) -> list[tuple[str, re.Pattern[str]]]:
    """词表 → (原始 token, 编译后正则)。普通行做大小写不敏感子串匹配。"""
    if not wordlist_path.exists():
        raise FileNotFoundError(f"wordlist missing: {wordlist_path}")
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for raw in wordlist_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("re:"):
            expr = line[3:]
            patterns.append((line, re.compile(expr)))
        else:
            patterns.append((line, re.compile(re.escape(line), re.IGNORECASE)))
    if not patterns:
        raise ValueError(f"wordlist empty: {wordlist_path}")
    return patterns


def iter_files(root: Path, strict: bool = False):
    suffixes = set(DEFAULT_SCAN_SUFFIXES) | (STRICT_EXTRA_SUFFIXES if strict else set())
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        dirs = {seg.lower() for seg in path.relative_to(root).parts[:-1]}
        # *.egg-info 等构建产物目录：生成物元数据（同 .venv，gitignore 覆盖，非源码）
        if dirs & EXCLUDED_DIRS or any(seg.endswith(".egg-info") for seg in dirs):
            continue
        name = path.name.lower()
        if name in ALWAYS_EXCLUDED_FILES or name.startswith("license"):
            continue
        if path.suffix.lower() not in suffixes:
            continue
        yield path


def lint_repo(root: Path = REPO_ROOT, strict: bool = False):
    """返回 (violations, scanned_files)。violations 元素 = (相对路径, 行号, token)。"""
    root = Path(root).resolve()
    patterns = load_patterns(root / "ops" / "forbidden_names.txt")
    violations: list[tuple[str, int, str]] = []
    scanned = 0
    for path in iter_files(root, strict):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 非 UTF-8 文本（二进制/其他编码）跳过
        scanned += 1
        for token, rx in patterns:
            for m in rx.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                violations.append((path.relative_to(root).as_posix(), line_no, token))
    return violations, scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="仓库禁用词守卫（公开仓库卫生）")
    parser.add_argument("--root", default=str(REPO_ROOT), help="扫描根目录")
    parser.add_argument("--strict", action="store_true", help="额外扫描 yaml/toml/json 配置文件")
    args = parser.parse_args(argv)
    violations, scanned = lint_repo(Path(args.root), strict=args.strict)
    for rel, line_no, token in violations:
        print(f"VIOLATION {rel}:{line_no}: 禁用词「{token}」")
    print(f"name_lint: scanned {scanned} files, {len(violations)} violation(s)"
          + (" [strict]" if args.strict else ""))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
