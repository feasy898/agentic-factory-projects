#!/usr/bin/env python3
"""公开导出门（审查 §E）：导出公开文本面 → 替换内部依赖/模块名 → 严格档终检。

name_lint 的豁免面（pyproject.toml / constraints.txt / clone_oss.sh / 词表自身）
不是免检，而是把检查挪到导出口——本脚本就是那个出口：

1. 按 :mod:`ops.name_lint` 严格档文件集（默认+yaml/toml/json 后缀）把仓库文本面
   复制到 ``--out`` 目录；
2. **依赖清单替换**：根级 ``pyproject.toml`` / ``constraints.txt`` 中命中词表的
   行整体剔除——公开版只保留中性核心依赖；内部引擎（PDF/OCR/语料生成等）
   由部署方经 config 注入，不随公开仓分发；
3. **config 模块名替换**：``config/*.yaml`` 行内命中的 token 置换为
   ``_BY_DEPLOYER_``（YAML 保持可解析、加载即显式失败——公开版必须自行配置
   真实提供方，不能默默继承内部坐标）；
4. 对 ``--out`` 树跑 :func:`ops.name_lint.lint_repo`（strict=True）——零命中
   才算过，任何命中退出码 1。

本脚本验收的是「公开文本面零禁用词」；完整发布打包（二进制/数据/文档裁剪）
由发布流程另行组装，不在本门职责内。

用法::

    python ops/export_public.py                       # 默认导出 out/public 并终检
    python ops/export_public.py --out out/public-v2   # 指定导出目录

退出码：0 = 导出完成且严格档零命中；1 = 仍有命中或 IO 失败。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.name_lint import (  # noqa: E402
    iter_files,
    lint_repo,
    load_patterns,
)

#: 依赖清单（整行剔除）；行内命中任一禁用词即剔除该行
MANIFEST_DROP_LINE_FILES = frozenset({"pyproject.toml", "constraints.txt"})

#: 根级豁免但**随导出改写**的文件（iter_files 不产出它们，这里显式带上）
REWRITE_EXEMPT_FILES = ("pyproject.toml", "constraints.txt", "ops/clone_oss.sh")

#: 根级豁免且**原样携带**的文件（词表自身；导出树扫描时同坐标自豁免）
COPY_ASIS_FILES = ("ops/forbidden_names.txt",)

#: config 模块名行内替换占位（部署方自行配置真实提供方；加载即显式失败）
DEPLOYER_PLACEHOLDER = "_BY_DEPLOYER_"


def _rewrite_line(rel_lower: str, line: str, tokens: list[tuple[str, object]]) -> str | None:
    """按文件类别改写一行；返回 None 表示整行剔除。"""
    if not any(pattern.search(line) is not None for _, pattern in tokens):
        return line
    if rel_lower in MANIFEST_DROP_LINE_FILES:
        return None  # 依赖清单：命中行整体剔除（公开版依赖由部署方按 config 注入）
    for _, pattern in tokens:  # config 等：行内 token 置换为部署方占位
        line = pattern.sub(DEPLOYER_PLACEHOLDER, line)
    return line


def export(out_dir: Path) -> tuple[int, int]:
    """导出 + 改写；返回 (复制文件数, 改写行数)。out_dir 先清空重建。"""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tokens = load_patterns()
    copied, rewritten = 0, 0
    paths = list(iter_files(REPO_ROOT, strict=True))
    for rel_s in (*REWRITE_EXEMPT_FILES, *COPY_ASIS_FILES):
        p = REPO_ROOT / rel_s
        if p.exists():
            paths.append(p)
    for path in paths:
        rel = path.relative_to(REPO_ROOT)
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        rel_lower = rel.as_posix().lower()
        if rel_lower in COPY_ASIS_FILES:
            shutil.copyfile(path, target)
            copied += 1
            continue
        text = path.read_text(encoding="utf-8")
        out_lines: list[str] = []
        for line in text.splitlines(keepends=True):
            if line.endswith("\r\n"):
                body, nl = line[:-2], "\r\n"
            elif line.endswith("\n"):
                body, nl = line[:-1], "\n"
            else:
                body, nl = line, ""
            new = _rewrite_line(rel_lower, body, tokens)
            if new is None:
                rewritten += 1
                continue
            if new != body:
                rewritten += 1
            out_lines.append(new + nl)
        target.write_text("".join(out_lines), encoding="utf-8")
        copied += 1
    return copied, rewritten


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公开导出门：导出 + 替换内部名 + 严格档终检")
    parser.add_argument("--out", default=str(REPO_ROOT / "out" / "public"),
                        help="导出目录（默认 out/public；每次重建）")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    try:
        copied, rewritten = export(out_dir)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"export_public: 导出失败：{exc}")
        return 1
    print(f"export_public: copied {copied} files -> {out_dir} ({rewritten} lines rewritten)")
    violations, scanned = lint_repo(out_dir, strict=True)
    for rel, line_no, token in violations:
        print(f"VIOLATION {rel}:{line_no}: 禁用词「{token}」")
    print(f"export_public strict lint: scanned {scanned} files, {len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
