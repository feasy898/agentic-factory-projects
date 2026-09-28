#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B0 批次门禁（gate_b0）—— T0/T0b/T1/T3 收口检查。

用法（系统 Python，任意 cwd 均可运行；内部自动定位仓库根并使用 .venv 的解释器）：
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b0.py

检查项（逐项打印 [PASS]/[FAIL]，任何 FAIL 退出码 1）：
  ① pytest tests/ 全绿（用 .venv 的 python 在仓库根执行）；
  ② configs/models.yaml：每个引擎条目含 fallback 字段，且四个已冒烟引擎
    （dub-tts / alt-tts-b / lip-fast / asr-core）含非空 volta_status；
  ③ data/gpu_smoke_report.json 存在，且含 4 个模型条目（去重后的 model 字段；
    失败项如实记录 error 亦可）；
  ④ 仓库中性名检查：被禁 token 对应内部台账 plan/oss-manifest.md 附录A 的上游名
    （台账为仓库外内部文件，位于 ../plan/oss-manifest.md；可读时自动解析附录A 并做
    覆盖校验——每条上游名必须至少被一个 token 命中，防止 token 表与台账脱节），
    对公开文件 grep 零命中。

公开目录口径（与 tests/test_skeleton.py::test_neutral_naming_discipline 既有口径一致
并作扩展）：git 追踪的全部文本文件；其中 docs/ 与 requirements.txt 为依赖安装记录，
必须使用真实 PyPI 发行名，不在本检查范围。扫描后缀：.py/.yaml/.yml/.md/.json/
.sh/.ps1/.toml/.txt。被禁 token 在本文件中以拼接构造，避免自命中。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]

# 被禁 token（小写、子串匹配），与内部台账附录A 的上游名一一对应；映射关系只在台账维护。
# 一律拼接构造：本文件自身也在公开扫描集内，任何位置（含注释）不得出现连续上游名。
# 说明：
#   - 裸 "c2pa" 不禁：那是 C2PA 标准名（台账第 3 节），已固化进 C1-C8 契约
#     字段（contracts.py 的 label_status.c2pa 与 c2pa_manifest.json 工件名）；
#     禁的是上游**软件**名及其组合短语（见下行 token）。
#   - 裸 "lora" 不禁：中性名 isomt-lora 本身含该子串。
BANNED_TOKENS = [
    # 附录A: audiosplit 组
    "paddle" + "ocr",
    "audio-" + "separator",
    "dem" + "ucs",
    # 附录A: asr-core / alt-tts-a / align-core 共同上游前缀
    "qw" + "en",
    # 附录A: align-core 组
    "forced" + "aligner",
    # 附录A: emo-tag 组（框架名 + 模型名）
    "sense" + "voice",
    "fun" + "asr",
    # 附录A: voxdia 组
    "3d-" + "speaker",
    "cam" + "++",
    "pyan" + "note",
    # 附录A: actspk 组
    "light-" + "asd",
    # 附录A: facemesh 组
    "media" + "pipe",
    # 附录A: shot-cut 组
    "trans" + "net",
    # 附录A: cap-clean 组
    "video-subtitle-" + "remover",
    # 附录A: mt-core 组
    "hy-" + "mt",
    # 附录A: dub-tts 组（含连字符仓名变体）
    "index" + "tts",
    "index" + "-tts",
    # 附录A: alt-tts-b 组
    "vox" + "cpm",
    # 附录A: lip-fast 组
    "muse" + "talk",
    # 附录A: lip-pro 组
    "latent" + "sync",
    # 附录A: audmark 组
    "audio" + "seal",
    # 附录A: provenance 组（工具名 ×3 + 短语）
    "c2pa" + "tool",
    "c2pa-" + "python",
    "content" + "auth",
    "c2pa" + " toolchain",
    # 附录A: isomt-lora 组
    "dub" + "mt",
    # 台账正文同禁（与 tests/test_skeleton.py::_banned_tokens 保持一致的超集）
    "paddle" + "paddle",
    "wav2" + "lip",
    "whis" + "per",
    "flash" + "attention",
    "vll" + "m",
]

SCAN_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".sh", ".ps1", ".toml", ".txt"}
# 依赖安装记录：必须写真实 PyPI 发行名，无法用中性名替代 → 不在公开扫描范围
SCOPE_EXCLUDES = ("docs/", "requirements.txt")

# ② 中要求有 volta_status 的引擎（T3 已冒烟收口的四组件）
VOLTA_REQUIRED = ("dub-tts", "alt-tts-b", "lip-fast", "asr-core")

# 内部台账（附录A 上游名权威来源）；仓库外内部文件，独立克隆时不可得 → 优雅降级
MANIFEST_CANDIDATES = (ROOT.parent / "plan" / "oss-manifest.md",
                       ROOT / "plan" / "oss-manifest.md")

PYTEST_TIMEOUT_S = 900


def venv_python() -> Path | None:
    """定位仓库 .venv 的解释器（Windows/Linux 两种布局）。"""
    for rel in ((".venv", "Scripts", "python.exe"),
                (".venv", "bin", "python"),
                (".venv", "bin", "python3")):
        p = ROOT.joinpath(*rel)
        if p.is_file():
            return p
    return None


def run_venv_json(code: str, args: list[str]) -> object:
    """经 .venv python 执行一段返回 JSON 的代码（系统 python 缺三方库时的桥）。"""
    vpy = venv_python()
    if vpy is None:
        raise RuntimeError("未找到 .venv 解释器")
    r = subprocess.run([str(vpy), "-c", code, *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"venv 桥执行失败: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def load_yaml(path: Path) -> object:
    try:
        import yaml  # 系统解释器自带则直接用
    except ImportError:
        return run_venv_json(
            "import sys, yaml, json;"
            "print(json.dumps(yaml.safe_load(open(sys.argv[1], encoding='utf-8'))))",
            [str(path)])
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 检查项
# ---------------------------------------------------------------------------

def check_pytest() -> tuple[bool, str]:
    vpy = venv_python()
    if vpy is None:
        return False, "未找到 .venv 解释器（.venv/Scripts/python.exe 或 .venv/bin/python）"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run([str(vpy), "-m", "pytest", "tests/", "-q"],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=PYTEST_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return False, f"pytest 超时（>{PYTEST_TIMEOUT_S}s）"
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    tail = " | ".join(lines[-3:])[:300] if lines else (r.stderr or "").strip()[:300]
    if r.returncode != 0:
        return False, f"pytest 退出码 {r.returncode}: {tail}"
    return True, tail


def check_models_yaml() -> tuple[bool, str]:
    path = ROOT / "configs" / "models.yaml"
    if not path.is_file():
        return False, "configs/models.yaml 不存在"
    try:
        data = load_yaml(path)
    except Exception as exc:  # 解析失败即 FAIL
        return False, f"models.yaml 解析失败: {exc}"
    if not isinstance(data, dict) or not isinstance(data.get("components"), dict):
        return False, "models.yaml 缺 components 引擎表"
    comps = data["components"]
    if not comps:
        return False, "components 为空"
    missing_fb = sorted(n for n, c in comps.items()
                        if not isinstance(c, dict) or "fallback" not in c)
    if missing_fb:
        return False, f"缺 fallback 字段的引擎条目: {missing_fb}"
    absent = [n for n in VOLTA_REQUIRED if n not in comps]
    if absent:
        return False, f"缺引擎条目: {absent}"
    empty_volta = [n for n in VOLTA_REQUIRED
                   if not str(comps[n].get("volta_status") or "").strip()]
    if empty_volta:
        return False, f"缺 volta_status（或为空）: {empty_volta}"
    volta_brief = ", ".join(f"{n}={comps[n]['volta_status']}" for n in VOLTA_REQUIRED)
    return True, (f"{len(comps)} 个引擎条目均含 fallback 字段；"
                  f"四组件 volta_status: {volta_brief}")


def check_smoke_report() -> tuple[bool, str]:
    path = ROOT / "data" / "gpu_smoke_report.json"
    if not path.is_file():
        return False, "data/gpu_smoke_report.json 不存在"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"gpu_smoke_report.json 解析失败: {exc}"
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return False, "gpu_smoke_report.json 无 items 列表"
    models = sorted({it["model"] for it in items
                     if isinstance(it, dict) and isinstance(it.get("model"), str)})
    if len(models) < 4:
        return False, f"模型条目仅 {len(models)} 个（<4）: {models}"
    n_ok = sum(1 for it in items if isinstance(it, dict) and it.get("ok") is True)
    n_fail = len(items) - n_ok
    return True, (f"gpu_smoke_report.json 存在，含 {len(models)} 个模型条目"
                  f"（共 {len(items)} 项: ok={n_ok}, 如实记录失败={n_fail}）: "
                  f"{', '.join(models)}")


def public_files() -> list[Path]:
    """公开目录文件集 = git 追踪文件 − 依赖安装记录 − 非文本后缀。"""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                             capture_output=True, check=True, timeout=60).stdout
        names = [n for n in out.decode("utf-8", "replace").split("\0") if n]
    except Exception:
        # git 不可用时退化为目录枚举（仍覆盖全部公开代码/配置目录）
        names = []
        for sub in ("pipeline", "configs", "tests", "scripts", "gpu", "data"):
            d = ROOT / sub
            if d.is_dir():
                names.extend(str(p.relative_to(ROOT)) for p in sorted(d.rglob("*"))
                             if p.is_file() and "__pycache__" not in p.parts)
        for extra in ("README.md", "conftest.py", "requirements.txt"):
            if (ROOT / extra).is_file():
                names.append(extra)
    picked = []
    for n in names:
        n = n.replace("\\", "/")
        if n.startswith(SCOPE_EXCLUDES) or n in SCOPE_EXCLUDES:
            continue
        if Path(n).suffix.lower() in SCAN_SUFFIXES:
            picked.append(ROOT / n)
    return picked


APPENDIX_HEADING_RE = re.compile(r"^#{1,6}\s*附录\s*A")


def parse_manifest_appendix() -> tuple[Path | None, list[tuple[str, str]]]:
    """解析内部台账附录A → [(中性名, 上游名单元格), ...]；找不到/解析不出返回 (None, [])。

    锚定规则：以「## 附录A」标题行定位（正文其他位置也会提到“附录A”三字，
    不能用子串包含判断），且只认其后含「中性名」表头的那张表，防止误吞前文章节表。
    """
    manifest = next((p for p in MANIFEST_CANDIDATES if p.is_file()), None)
    if manifest is None:
        return None, []
    try:
        lines = manifest.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return manifest, []
    rows: list[tuple[str, str]] = []
    started = header_seen = False
    for raw in lines:
        s = raw.strip()
        if not started:
            if APPENDIX_HEADING_RE.match(s):
                started = True
            continue
        if not header_seen:
            if s.startswith("|") and "中性名" in s:
                header_seen = True
            continue
        if not s.startswith("|"):
            if rows:
                break  # 表格结束
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue  # 分隔行
        neutral, upstream = cells[0], cells[1]
        if neutral and upstream and neutral != "中性名":
            rows.append((neutral, upstream))
    return manifest, rows


def check_neutral_names() -> tuple[bool, str]:
    # 第一步：台账附录A 覆盖校验（可读时）——每条上游名必须被至少一个 token 命中，
    # 否则说明新增上游名未进 BANNED_TOKENS，属配置脱节，判 FAIL。
    manifest, rows = parse_manifest_appendix()
    notes: list[str] = []
    if manifest is None:
        notes.append("内部台账不可读（独立克隆场景）——仅用内置 token 表")
    elif not rows:
        notes.append("内部台账已找到但附录A 解析出 0 条——仅用内置 token 表（请人工核对）")
    else:
        uncovered = [neutral for neutral, upstream in rows
                     if not any(tok in upstream.lower() for tok in BANNED_TOKENS)]
        if uncovered:
            return False, ("附录A 上游名未被 token 表覆盖（请更新 BANNED_TOKENS），"
                           "中性名: " + ", ".join(uncovered))
        notes.append(f"附录A 覆盖校验通过（{len(rows)} 条上游名均被 token 表覆盖）")
    # 第二步：公开文件 grep
    files = public_files()
    if not files:
        return False, "公开文件集为空（扫描范围异常）"
    hits: list[str] = []
    scanned = 0
    for path in files:
        try:
            text = path.read_bytes().decode("utf-8", "replace").lower()
        except OSError as exc:
            return False, f"无法读取 {path.relative_to(ROOT)}: {exc}"
        scanned += 1
        for token in BANNED_TOKENS:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}: {token!r}")
    if hits:
        return False, (f"{len(hits)} 处上游名命中:\n    " + "\n    ".join(hits))
    notes.append(f"扫描 {scanned} 个公开文件 × {len(BANNED_TOKENS)} 个被禁 token，零命中")
    return True, "；".join(notes)


# ---------------------------------------------------------------------------

def main() -> int:
    checks = [
        ("① pytest tests/ 全绿", check_pytest),
        ("② models.yaml 每条目含 fallback 且四组件有 volta_status", check_models_yaml),
        ("③ gpu_smoke_report.json 含 4 个模型条目", check_smoke_report),
        ("④ 中性名检查（附录A 上游名零命中）", check_neutral_names),
    ]
    n_fail = 0
    for title, fn in checks:
        try:
            ok, detail = fn()
        except Exception as exc:  # 检查本身抛错 = 该项 FAIL
            ok, detail = False, f"检查执行异常: {exc}"
        if not ok:
            n_fail += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {title}")
        for ln in detail.splitlines():
            print(f"       {ln}")
    total = len(checks)
    print(f"== gate_b0: {total - n_fail}/{total} PASS ==")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
