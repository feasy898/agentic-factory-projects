#!/usr/bin/env python3
"""公开导出定稿（T8.2）：git 跟踪文件 → 公开树 → 依赖清单处理 → 严格档终检。

name_lint 的豁免面（pyproject.toml / constraints.txt / clone_oss.sh / 词表自身）
不是免检，而是把检查挪到导出口——本脚本就是那个出口。四步（任务单 T8.2 ①–④）：

1. **导出树 = git 跟踪文件过滤**：``git ls-files`` 枚举源仓库跟踪文件，
   排除 ``.env``（``.env.example`` 保留）、``data/``、``tmp/`` 等本地工件目录，
   以及两份内部坐标文件——``constraints.txt``（依赖冻结真相，开发指令 §7.3：
   默认排除，公开版依赖清单由 DEPS.txt 承接）与 ``ops/clone_oss.sh``
   （第三方参考件克隆坐标，third_party/ 本就不进公开导出，脚本单独分发无意义，
   其说明移入 DEPS.txt）；词表 ``ops/forbidden_names.txt`` 原样携带
   （导出树内 name_lint 依它自查）。
2. **依赖清单处理**：``pyproject.toml`` 命中词表的行整行剔除，并在文件头写入
   ``_BY_DEPLOYER_`` 置换说明；``config/*.yaml|*.json`` 行内命中的内部依赖坐标
   token 置换为 ``_BY_DEPLOYER_``（YAML/JSON 保持可解析，相关功能未配置前显式
   失败——公开版必须自行配置真实提供方，不能默默继承内部坐标）；
   依赖安装记录单独落 ``DEPS.txt`` 给部署者（保留项实测版本、被剔除依赖组
   计数、_BY_DEPLOYER_ 出现位置、安装与冒烟命令），替代不分发的 constraints.txt。
3. **docker-compose.yml + README.public.md**：两份公开交付文档随仓库跟踪，
   经步骤 1 原样进导出树（compose 未在无 Docker 环境实测——文件头如实声明）。
4. **终检**：对导出树跑 :func:`ops.name_lint.lint_repo`（strict=True，含
   yaml/toml/json 配置档）——零命中才算过，任何命中退出码 1。

用法::

    python ops/export_public.py                                # 默认导出 out/public-export
    python ops/export_public.py --out out/public-export-v2     # 指定导出目录

导出树自验收（部署者冒烟，见 README.public.md）::

    cd <导出树> && <任一 venv python> -m pytest evals/m0_infra --pythonpath <导出树>

退出码：0 = 导出完成且严格档零命中；1 = 仍有命中 / git 不可用 / IO 失败。
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.name_lint import (  # noqa: E402
    lint_repo,
    load_patterns,
)

#: 依赖清单（命中词表行整行剔除）；constraints.txt 整文件排除（见 EXCLUDED_TRACKED）
MANIFEST_DROP_LINE_FILES = frozenset({"pyproject.toml"})

#: git 跟踪但**不进公开树**的文件：内部依赖冻结真相（§7.3，由 DEPS.txt 承接）
#: 与第三方参考件克隆坐标（third_party/ 不进公开导出，克隆脚本随它一并留在内部）
EXCLUDED_TRACKED = ("constraints.txt", "ops/clone_oss.sh")

#: 本地工件顶层目录（跟踪文件本不应在其中，防御性过滤；任务单 T8.2 ①）
EXCLUDED_TOP_DIRS = frozenset({
    "data", "tmp", "out", "plan", "third_party", ".venv", "venv",
    ".git", "node_modules", "__pycache__",
})

#: 词表自身：原样携带（导出树内 name_lint 依它自查；同坐标在 lint 侧豁免）
COPY_ASIS_FILES = ("ops/forbidden_names.txt",)

#: config 模块名行内替换占位（部署方自行配置真实提供方；加载即显式失败）
DEPLOYER_PLACEHOLDER = "_BY_DEPLOYER_"

#: pyproject.toml 剔除后前置的置换说明（T8.2 ②）
PYPROJECT_NOTE = """\
# ── 公开导出说明（ops/export_public.py 自动生成）────────────────────────
# 公开版依赖清单：命中内部词表的依赖行已整行剔除（内部引擎坐标不随公开仓分发）。
# config/*.yaml 与 config/install_check.json 中的 _BY_DEPLOYER_ = 部署方自行注入
# 的内部依赖坐标；未配置时相关功能（PDF 清理引擎 / OCR 引擎 / 合成语料库）显式
# 失败，识别/脱敏/路由/审计主链路不受影响。
# 依赖安装记录（保留项实测版本、被剔除依赖组、安装与冒烟命令）见 DEPS.txt。
"""

#: 含 _BY_DEPLOYER_ 置换的 YAML 前置注记（JSON 不能带注释，说明只进 DEPS.txt）
YAML_NOTE = (
    "# 【公开导出】{n} 处 _BY_DEPLOYER_ = 部署方注入的内部依赖坐标"
    "（说明见 DEPS.txt；未配置时相关功能显式失败）\n"
)


def _git_tracked_files() -> list[Path]:
    """源仓库 ``git ls-files -z`` → 跟踪文件相对路径列表。git 不可用即抛错。"""
    try:
        raw = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"git ls-files 失败（导出树必须以 git 跟踪面为准）: {exc}") from exc
    return [REPO_ROOT / rel for rel in raw.decode("utf-8").split("\0") if rel]


def _keep(rel_posix: str) -> bool:
    """跟踪文件过滤（T8.2 ①）：.env / data|tmp 等本地工件 / 内部坐标文件排除。"""
    rel = rel_posix.lower()
    if rel in EXCLUDED_TRACKED:
        return False
    if rel == ".env" or (rel.startswith(".env.") and rel != ".env.example"):
        return False
    top = rel.split("/", 1)[0]
    if top in EXCLUDED_TOP_DIRS:
        return False
    return True


def _rewrite_text(rel_lower: str, text: str, tokens: list[tuple[str, object]]) -> tuple[str, int, int]:
    """按文件类别改写文本；返回 (新文本, 剔除行数, 置换处数)。"""
    dropped = replaced = 0
    out_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.endswith("\r\n"):
            body, nl = line[:-2], "\r\n"
        elif line.endswith("\n"):
            body, nl = line[:-1], "\n"
        else:
            body, nl = line, ""
        hit = any(pattern.search(body) is not None for _, pattern in tokens)
        if hit and rel_lower in MANIFEST_DROP_LINE_FILES:
            dropped += 1  # 依赖清单：命中行整行剔除（公开版依赖由部署方按 DEPS.txt 对照）
            continue
        if hit:
            for _, pattern in tokens:  # config 等：行内 token 置换为部署方占位
                body, n = pattern.subn(DEPLOYER_PLACEHOLDER, body)
                replaced += n
        out_lines.append(body + nl)
    new_text = "".join(out_lines)
    if rel_lower == "pyproject.toml" and (dropped or replaced):
        new_text = PYPROJECT_NOTE + new_text
    elif rel_lower.endswith((".yaml", ".yml")) and replaced:
        new_text = YAML_NOTE.format(n=replaced) + new_text
    return new_text, dropped, replaced


def _canonical_dep_name(requirement: str) -> str:
    """``uvicorn[standard]>=0.30`` → ``uvicorn``（PEP 508 名部，规范化连字符）。"""
    return re.split(r"[><=!~;\[\s(]", requirement.strip(), maxsplit=1)[0].strip().lower().replace("_", "-")


def _load_frozen_versions() -> dict[str, str]:
    """constraints.txt（pip freeze 真相）→ {规范化发行名: 版本}。缺失即空表。"""
    path = REPO_ROOT / "constraints.txt"
    frozen: dict[str, str] = {}
    if not path.exists():
        return frozen
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "==" not in line or line.startswith("#"):
            continue
        name, _, ver = line.partition("==")
        frozen[_canonical_dep_name(name)] = ver.split(";")[0].strip()
    return frozen


def _build_deps_text(rewrite_stat: dict[str, tuple[int, int]]) -> str:
    """依赖安装记录 DEPS.txt（T8.2 ②）：给部署者的替代 constraints.txt 面。

    rewrite_stat: {相对路径: (剔除行数, 占位置换处数)}。只记录**保留项**
    （公开 pyproject 过滤后仍在其列的依赖）的实测冻结版本与被剔除组的**计数**
    ——被剔除坐标本身不进公开树（词表口径），DEPS.txt 同守。
    """
    tokens = load_patterns()
    frozen = _load_frozen_versions()
    raw = (REPO_ROOT / "pyproject.toml").read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    project = data["project"]
    extras: dict[str, list[str]] = data["project"].get("optional-dependencies", {})

    def is_kept(req: str) -> bool:
        return not any(pattern.search(req) is not None for _, pattern in tokens)

    def render(reqs: list[str], indent: str = "  ") -> list[str]:
        rows = []
        for req in reqs:
            if not is_kept(req):
                continue
            name = _canonical_dep_name(req)
            ver = frozen.get(name)
            rows.append(f"{indent}{req:<38} # 实测冻结 {name}=={ver}" if ver
                        else f"{indent}{req:<38} # 冻结清单未记（随 pip 解析）")
        return rows

    lines: list[str] = [
        "================================================================",
        " DEPS.txt — 公开版依赖安装记录（ops/export_public.py 自动生成，供部署者）",
        "================================================================",
        "",
        "一、为什么有本文件",
        "  内部依赖冻结清单（constraints.txt）与第三方参考件克隆脚本",
        "  （ops/clone_oss.sh）不随公开仓分发；pyproject.toml 中命中内部词表的",
        "  依赖行已整行剔除；config/*.yaml、config/install_check.json 中需部署",
        "  方自行提供的内部依赖坐标以 _BY_DEPLOYER_ 占位（YAML/JSON 仍可解析，",
        "  相关功能未配置前显式失败，不会静默降级）。",
        "",
        "二、核心依赖（pyproject.toml 保留项；「实测冻结」= 本项目 venv 版本真相）",
        f"  requires-python: {project.get('requires-python', '>=3.12')}",
        *[row for row in render(list(project.get("dependencies", [])))],
        "",
        "三、可选依赖组（pip install -e \".[dev,ocr,ml]\"）",
    ]
    dropped_total = 0
    for group, reqs in extras.items():
        kept = [r for r in reqs if is_kept(r)]
        dropped_total += len(reqs) - len(kept)
        lines.append(f"  [{group}]")
        lines.extend(render(reqs, indent="    "))
        if not kept:
            lines.append("    （整组随内部词表剔除：内部基线对比件，默认不装）")
    placeholder_files = sorted(rel for rel, (_, n_rep) in rewrite_stat.items() if n_rep)
    dropped_manifest = rewrite_stat.get("pyproject.toml", (0, 0))[0]
    lines += [
        "",
        "四、需部署方自行注入的内部坐标（_BY_DEPLOYER_ 出现位置）",
        *[f"  {rel}: {rewrite_stat[rel][1]} 处" for rel in placeholder_files],
        "  语义对照（坐标本体不入公开树）：",
        "    - config/app.yaml            pdf_engine_module（PDF 清理引擎主引擎）",
        "    - config/filechannel.yaml    PDF 文本读取 / 内容流手术引擎 / 栅格兜底渲染",
        "                                 / OCR 引擎（源码经 importlib 按配置动态加载）",
        "    - config/synthetic_corpus.yaml 合成语料库与 PDF 写入坐标（benchmark 生成器）",
        "    - config/install_check.json  安装自检条目中的内部引擎 dist/import",
        "                                 （装好后回填真实导入名即可恢复该自检项）",
        f"  依赖清单剔除计数：pyproject.toml 剔除 {dropped_manifest} 行；"
        f"可选组剔除 {dropped_total} 行。",
        "",
        "五、安装与冒烟（README.public.md 同款）",
        "  python -m venv .venv",
        '  ./.venv/Scripts/pip install -e ".[dev]"      # POSIX: .venv/bin/pip',
        "  cp .env.example .env                          # 至少填写 MASK_KEY",
        "  python -m pytest evals/m0_infra               # 基础设施冒烟，exit 0 = 通过",
        "  注：文件通道 / OCR / 合成语料与全链路端到端验收，需先按第四节注入内部",
        "  坐标后运行；识别 / 脱敏 / 路由 / 审计主链路不依赖这些坐标，本地模式",
        "  （两路 mock 上游，原样回显）装完核心依赖即可全离线体验。",
        "",
    ]
    return "\n".join(lines)


def _rmtree_retry(out_dir: Path, attempts: int = 6) -> None:
    """清空导出目录；Windows 下新写目录常被索引/杀软短暂持锁，失败退避重试。"""
    import time

    for i in range(attempts):
        try:
            shutil.rmtree(out_dir)
            return
        except OSError:
            if i == attempts - 1:
                raise
            time.sleep(1.0)


def export(out_dir: Path) -> tuple[int, dict[str, tuple[int, int]]]:
    """导出 + 改写；返回 (复制文件数, {相对路径: (剔除行数, 置换处数)})。out_dir 先清空重建。"""
    if out_dir.exists():
        _rmtree_retry(out_dir)
    tokens = load_patterns()
    rewrite_stat: dict[str, tuple[int, int]] = {}
    copied = 0
    for path in _git_tracked_files():
        rel = path.relative_to(REPO_ROOT)
        rel_lower = rel.as_posix().lower()
        if not _keep(rel_lower):
            continue
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel_lower in COPY_ASIS_FILES:
            shutil.copyfile(path, target)
            copied += 1
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(path, target)  # 非文本跟踪文件原样携带
            copied += 1
            continue
        new_text, dropped, replaced = _rewrite_text(rel_lower, text, tokens)
        target.write_text(new_text, encoding="utf-8")
        copied += 1
        if dropped or replaced:
            rewrite_stat[rel.as_posix()] = (dropped, replaced)
    (out_dir / "DEPS.txt").write_text(_build_deps_text(rewrite_stat), encoding="utf-8")
    return copied, rewrite_stat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="公开导出定稿：git 跟踪面导出 + 依赖清单处理 + 严格档终检")
    parser.add_argument("--out", default=str(REPO_ROOT / "out" / "public-export"),
                        help="导出目录（默认 out/public-export；每次重建）")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    try:
        copied, rewrite_stat = export(out_dir)
    except (OSError, RuntimeError, tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        print(f"export_public: 导出失败：{exc}")
        return 1
    print(f"export_public: copied {copied} tracked files -> {out_dir}")
    for rel, (dropped, replaced) in sorted(rewrite_stat.items()):
        ops_ = []
        if dropped:
            ops_.append(f"{dropped} line(s) dropped")
        if replaced:
            ops_.append(f"{replaced} token(s) -> _BY_DEPLOYER_")
        print(f"export_public: rewritten {rel} ({', '.join(ops_)})")
    print("export_public: DEPS.txt written (依赖安装记录，供部署者)")
    violations, scanned = lint_repo(out_dir, strict=True)
    for rel, line_no, token in violations:
        print(f"VIOLATION {rel}:{line_no}: 禁用词「{token}」")
    print(f"export_public strict lint: scanned {scanned} files, {len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
