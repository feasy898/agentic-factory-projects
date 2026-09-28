#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B0 批次门禁（gate_b0）—— T0/T0b/T1/T3 收口检查。

用法（系统 Python，任意 cwd 均可运行；内部自动定位仓库根并使用 .venv 的解释器）：
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b0.py

检查项（逐项打印 [PASS]/[FAIL]，任何 FAIL 退出码 1）：
  ① pytest tests/ 全绿（用 .venv 的 python 在仓库根执行）；
  ② configs/models.yaml 存在，且每个引擎条目（components 下）含 fallback 字段；
  ③ data/gpu_smoke_report.json 存在，且含 4 个模型条目（去重后的 model 字段）；
  ④ 仓库中性名检查：对内部台账附录A 的上游名做 grep，公开目录零命中。

公开目录口径（与 tests/test_skeleton.py::test_neutral_naming_discipline 既有口径一致
并作扩展）：git 追踪的全部文本文件；其中 docs/ 与 requirements.txt 为依赖安装记录，
必须使用真实 PyPI 发行名，不在本检查范围。扫描后缀：.py/.yaml/.yml/.md/.json/
.sh/.ps1/.toml/.txt。被禁 token 在本文件中以拼接构造，避免自命中。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]

# 附录A 上游名 → 中性名 的被禁 token（小写、子串匹配；拼接构造避免本文件自命中）
BANNED_TOKENS = [
    "paddle" + "ocr",
    "audio-" + "separator",       # 含 python-audio-separator
    "dem" + "ucs",
    "qw" + "en",                  # 含 Qwen3-ASR / Qwen3-TTS / qwen0.6b 等
    "forced" + "aligner",
    "sense" + "voice",
    "fun" + "asr",
    "3d-" + "speaker",
    "cam" + "++",
    "pyan" + "note",
    "light-" + "asd",
    "media" + "pipe",
    "trans" + "net",              # 含 TransNetV2
    "video-subtitle-" + "remover",
    "hy-" + "mt",                 # 含 Hy-MT2 / HY-MT1.5
    "index" + "tts",              # 含 IndexTTS-2.5 / IndexTTS2 / index-tts
    "vox" + "cpm",                # 含 VoxCPM2
    "muse" + "talk",
    "latent" + "sync",
    "audio" + "seal",
    "c2pa" + "tool",
    "c2pa-" + "python",
    "content" + "auth",
    "dub" + "mt",
]

SCAN_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".json", ".sh", ".ps1", ".toml", ".txt"}
# 依赖安装记录：必须写真实 PyPI 发行名，无法用中性名替代 → 不在公开扫描范围
SCOPE_EXCLUDES = ("docs/", "requirements.txt")

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
    missing = sorted(n for n, c in comps.items()
                     if not isinstance(c, dict) or "fallback" not in c)
    if missing:
        return False, f"缺 fallback 字段的引擎条目: {missing}"
    return True, f"models.yaml 存在，{len(comps)} 个引擎条目均含 fallback 字段"


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
    return True, f"gpu_smoke_report.json 存在，含 {len(models)} 个模型条目: {', '.join(models)}"


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


def check_neutral_names() -> tuple[bool, str]:
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
        return False, f"{len(hits)} 处上游名命中:\n    " + "\n    ".join(hits)
    return True, f"中性名检查通过（扫描 {scanned} 个公开文件 × {len(BANNED_TOKENS)} 个被禁 token，零命中）"


# ---------------------------------------------------------------------------

def main() -> int:
    checks = [
        ("① pytest tests/ 全绿", check_pytest),
        ("② configs/models.yaml 每引擎条目含 fallback", check_models_yaml),
        ("③ data/gpu_smoke_report.json 含 4 个模型条目", check_smoke_report),
        ("④ 仓库中性名检查（附录A 上游名零命中）", check_neutral_names),
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
