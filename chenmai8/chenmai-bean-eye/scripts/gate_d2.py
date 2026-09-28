#!/usr/bin/env python3
"""BeanEye D2 里程碑闸门（gate_d2）。

覆盖 D2 批次（W2 采集 / W3 标定 / W6 配对 / W7 严重度）的整体验收。
本脚本用**系统 Python** 运行（不要求已激活 venv、不限定 cwd），
内部自行定位仓库根，并统一改用项目 .venv 解释器执行子检查（与 gate_d1 同约定）。

五项检查（任何一项 FAIL → 总退出码 1）：
  ① scripts/doctor.py 以 .venv python 运行且退出码 0
  ② .venv python -m pytest tests/ 全绿（含 D1 契约 test_schemas 与本批
     W2/W3/W6/W7 新测试；退出码 0）
  ③ 本批四个模块的 eval 入口**逐个**单独运行退出码 0：
       W3 M3 标定   tests/test_calibration.py
       W6 M6 配对   tests/test_pairing.py
       W7 M7 严重度 tests/test_severity.py
       W2 M2 采集   tests/test_acquisition.py
     （对应开发指令 §4 各模块 "eval: pytest tests/test_<pkg>.py -q"；
      入口文件缺失按该模块 FAIL 计）
  ④ 中性名扫描零命中：对 git 跟踪的文本文件全文本扫描上游名清单
     （§5 开源件锚点 + 数据集/论文来源名 + 素材映射原标签，模式见
     UPSTREAM_NAME_PATTERNS），命中即 FAIL。豁免名单 INTERNAL_ALLOWLIST
     仅收录**按 D-3/§6 定义的内部版文件**（requirements 钉版注释、环境
     装配、OSS 冒烟、数据集下载器/解锁说明——它们记录上游锚点是设计使然，
     D9 出公开仓时整体不随迁）；产品面（beaneye/ tests/ configs/ docs/
     README 等）零豁免。
  ⑤ 禁止 IO 扫描（W13 修复，评审 D 项）：产品代码不得出现
     ``cv2.imwrite(`` / ``cv2.imread(``（非 ASCII 路径静默失败）与
     ``np.fromfile(``（Windows 上同样不安全）——图像读写一律走
     ``beaneye.acquisition.base`` 的 ``imread_bgr``/``imwrite_bgr``
     （imencode/imdecode 字节缓冲）。命中即 FAIL。

用法（Git Bash / cmd / PowerShell 均可，任意 cwd）：
    python D:/workspace/澄迈8项目/咖啡豆质检/repo/scripts/gate_d2.py

输出：逐项 `[PASS]`/`[FAIL]` + 详情，结尾 `GATE D2: PASS/FAIL`。
退出码：全过 = 0；任一 FAIL = 1；前置缺失（.venv 不存在）时 ①②③判 FAIL、④照常执行。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# 闸门自身输出统一 UTF-8（Windows 控制台/重定向默认 GBK 会乱码）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

SUBPROC_TIMEOUT_S = 600

# ③ 本批模块 eval 入口（开发指令 §4：每模块 eval = pytest tests/test_<pkg>.py -q）
MODULE_EVALS: list[tuple[str, str, str]] = [
    ("W3", "M3 标定", "tests/test_calibration.py"),
    ("W6", "M6 配对", "tests/test_pairing.py"),
    ("W7", "M7 严重度", "tests/test_severity.py"),
    ("W2", "M2 采集", "tests/test_acquisition.py"),
]

# ④ 上游名清单（内部维护；D9 的 scripts/name_audit.py 将按 oss-manifest 全量接管）。
# 短词用 \b 词边界防误伤（usk/sahi/yolo 等），长 distinctive 词直接子串匹配。
# 覆盖：检测/分割 NN、SAM2、增强、标注复核、切片、向量库、LLM 服务/权重、
#       检索嵌入、数据集主辅源、论文出处、模型托管方、素材映射原标签（W13）。
UPSTREAM_NAME_PATTERNS: list[str] = [
    r"rf-?detr",                # 检测/分割 NN（中性名 beaneye-det）
    r"roboflow",                # 数据集托管（含 universe.roboflow.com）
    r"redtraining",             # 数据集 workspace 名
    r"sam-?2",                  # 抠图分割（中性名 beaneye-mat）
    r"segment[- ]anything",
    r"facebookresearch",
    r"facebook/",
    r"ultralytics",             # AGPL 禁用件（D-5 红线，出现即是事故）
    r"\byolo",                  # ultralytics 系模型名（yolov8/yolo11/...）
    r"albumentations",          # 增强（中性名 beaneye-aug；公开版不得出现）
    r"label[-_ ]?studio",       # 标注复核（中性名 beaneye-review）
    r"humansignal",
    r"\bsahi\b",                # 切片推理（中性名 beaneye-slice）
    r"\bobss\b",
    r"\bchroma\b",              # 向量库
    r"\bvllm\b",                # LLM 服务化
    r"\bqwen\b",                # LLM 权重
    r"bge[-_]m3",               # 检索嵌入
    r"\bbaai\b",
    r"defectos",                # 数据集主源（DefectosCafeVerde / defectos_cafe_verde）
    r"\busk\b",                 # 数据集辅源（USK-COFFEE）
    r"\bmdpi\b",                # 数据集论文出处
    r"huggingface",             # 模型托管方（含 facebook/sam2-* 模型 id 前缀）
    # -- W13 修复：素材映射原标签组（评审 E 项）——公开树只允许留在
    #    不入库内部文件 configs/upstream_mapping.internal.yaml（gitignore），
    #    data/datasets/README.md 与 download_datasets.py 属内部豁免件
    r"\bfrozen\b(?!=)",         # dataclass(frozen=True) 是合法 Python，(?!=) 排除
    r"\bblack_ear\b",
    r"\btriangle\b",
    r"\blongberry\b",
    r"\bpremium\b",
]

# ④ 豁免：内部版文件（D-3/§6 —— 内部文件可写开源名；D9 出公开仓时不随迁）。
# 名单外的任何命中都是 FAIL：新增豁免必须在本闸门提交信息里给出理由。
INTERNAL_ALLOWLIST: set[str] = {
    "requirements.txt",          # §6：pinned 内部版，可注释上游名；公开版另行裁剪
    "requirements-oss.txt",      # 同上（NN 冒烟件钉版与权重获取说明）
    "scripts/setup_env.ps1",     # 环境装配（内部）
    "scripts/doctor.py",         # 环境体检（核对 albumentations 安装，内部）
    "scripts/oss_smoke.py",      # OSS 四件套冒烟（内部）
    "scripts/download_datasets.py",  # 数据集下载器（内部数据管线，§10 不公开）
    "data/datasets/README.md",   # 数据集解锁步骤（内部）
    # 本闸门自身须枚举上游名清单才能执行扫描（与 D9 name_audit.py 同性质）——
    # 自 2026-09-28 提交后被 git 跟踪，实测模式列表自命中 23 处，故豁免自身。
    "scripts/gate_d2.py",
}

# 二进制扩展名（跳过文本扫描）
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico",
                   ".ttf", ".otf", ".woff", ".woff2",
                   ".pt", ".pth", ".onnx", ".ckpt", ".safetensors", ".npz",
                   ".zip", ".gz", ".7z", ".pdf", ".exe", ".dll", ".pd_"}

_SCAN_RE = re.compile("|".join(UPSTREAM_NAME_PATTERNS), re.IGNORECASE)

# ⑤ 禁止的图像 IO 调用（评审 D 项：中文路径下 cv2 直读直写会静默失败、
#    np.fromfile 在 Windows 同样不可靠）。def line 上必须出现这些字符串才能扫描，
#    本闸门自身已在 INTERNAL_ALLOWLIST 豁免。
FORBIDDEN_IO_PATTERNS: list[str] = [
    r"cv2\.imwrite\(",
    r"cv2\.imread\(",
    r"np\.fromfile\(",
]
_FORBIDDEN_IO_RE = re.compile("|".join(FORBIDDEN_IO_PATTERNS))


def _child_env() -> dict[str, str]:
    """子进程环境：强制 PYTHONUTF8=1（Windows 下默认跟随 GBK 代码页）。"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return env


def _run_in_venv(args: list[str]) -> subprocess.CompletedProcess[str]:
    """在仓库根用 .venv python 执行 args，捕获输出（UTF-8 解码）。"""
    return subprocess.run(
        [str(VENV_PY), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_child_env(),
        timeout=SUBPROC_TIMEOUT_S,
    )


def _tail(text: str, n_lines: int = 4) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else "(无输出)"


def check_venv() -> tuple[bool, str]:
    """前置检查：.venv 解释器存在可用。失败时 ①②③ 直接判 FAIL。"""
    if not VENV_PY.is_file():
        return False, f"未找到 .venv 解释器: {VENV_PY}（先运行 scripts/setup_env.ps1）"
    return True, str(VENV_PY)


def check_doctor() -> tuple[bool, str]:
    """检查 ① doctor.py 退出码 0。"""
    try:
        proc = _run_in_venv(["scripts/doctor.py"])
    except subprocess.TimeoutExpired:
        return False, f"doctor.py 超时（>{SUBPROC_TIMEOUT_S}s）"
    return proc.returncode == 0, f"exit={proc.returncode}, {_tail(proc.stdout + proc.stderr)}"


def check_pytest_all() -> tuple[bool, str]:
    """检查 ② pytest tests/ 全绿（D1 schema + 本批 W2/W3/W6/W7）。"""
    try:
        proc = _run_in_venv(["-m", "pytest", "tests/", "-q"])
    except subprocess.TimeoutExpired:
        return False, f"pytest 超时（>{SUBPROC_TIMEOUT_S}s）"
    summary = _tail(proc.stdout + proc.stderr)
    return proc.returncode == 0, f"exit={proc.returncode}, {summary}"


def check_module_evals() -> tuple[bool, str]:
    """检查 ③ 四模块 eval 入口逐个 exit 0（任一失败 → 整项 FAIL，逐条列出）。"""
    lines: list[str] = []
    n_ok = 0
    for wk, mod, entry in MODULE_EVALS:
        path = ROOT / entry
        if not path.is_file():
            lines.append(f"[FAIL] {wk} {mod} {entry}: 入口文件不存在")
            continue
        try:
            proc = _run_in_venv(["-m", "pytest", entry, "-q"])
        except subprocess.TimeoutExpired:
            lines.append(f"[FAIL] {wk} {mod} {entry}: 超时（>{SUBPROC_TIMEOUT_S}s）")
            continue
        summary = _tail(proc.stdout + proc.stderr)
        mark = "[PASS]" if proc.returncode == 0 else "[FAIL]"
        if proc.returncode == 0:
            n_ok += 1
        lines.append(f"{mark} {wk} {mod} {entry}: exit={proc.returncode}, {summary}")
    ok = n_ok == len(MODULE_EVALS)
    return ok, f"{n_ok}/{len(MODULE_EVALS)} 入口 exit 0\n  " + "\n  ".join(lines)


def _git_tracked_files() -> list[Path] | None:
    """git ls-files；失败（非 git 环境/git 不可用）返回 None。"""
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [ROOT / ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def check_neutral_names() -> tuple[bool, str]:
    """检查 ④ 中性名扫描零命中（git 跟踪文本文件，豁免内部版文件）。"""
    tracked = _git_tracked_files()
    if tracked is None:
        return False, "git ls-files 失败（需在 git 仓库内运行）"

    hits: list[str] = []
    n_scanned = 0
    n_skipped_bin = 0
    n_allowlisted = 0
    for path in tracked:
        rel = path.relative_to(ROOT).as_posix()
        if rel in INTERNAL_ALLOWLIST:
            n_allowlisted += 1
            continue
        if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            n_skipped_bin += 1
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:  # 二进制嗅探
            n_skipped_bin += 1
            continue
        text = raw.decode("utf-8", errors="replace")
        n_scanned += 1
        for m in _SCAN_RE.finditer(text):
            hits.append(f"{rel}: \"{m.group(0)}\"")

    if hits:
        shown = "\n  ".join(hits[:20])
        more = f"\n  ...（共 {len(hits)} 处命中）" if len(hits) > 20 else ""
        return False, f"命中 {len(hits)} 处上游名：\n  {shown}{more}"
    return True, (
        f"命中 0；扫描 {n_scanned} 个 git 跟踪文本文件"
        f"（豁免内部版 {n_allowlisted} 个，跳过二进制/缺失 {n_skipped_bin} 个），"
        f"模式 {len(UPSTREAM_NAME_PATTERNS)} 条"
    )


def check_forbidden_io() -> tuple[bool, str]:
    """检查 ⑤ 禁止 IO 零命中（cv2.imwrite / cv2.imread / np.fromfile）。"""
    tracked = _git_tracked_files()
    if tracked is None:
        return False, "git ls-files 失败（需在 git 仓库内运行）"

    hits: list[str] = []
    n_scanned = 0
    for path in tracked:
        rel = path.relative_to(ROOT).as_posix()
        if rel in INTERNAL_ALLOWLIST:
            continue
        if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        text = raw.decode("utf-8", errors="replace")
        n_scanned += 1
        for m in _FORBIDDEN_IO_RE.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            hits.append(f"{rel}:{line_no}: \"{m.group(0)}\"")

    if hits:
        shown = "\n  ".join(hits[:20])
        more = f"\n  ...（共 {len(hits)} 处命中）" if len(hits) > 20 else ""
        return False, f"命中 {len(hits)} 处禁止 IO：\n  {shown}{more}"
    return True, f"命中 0；扫描 {n_scanned} 个文本文件，模式 {len(FORBIDDEN_IO_PATTERNS)} 条（{', '.join(FORBIDDEN_IO_PATTERNS)}）"


def main() -> int:
    print("== BeanEye D2 闸门（gate_d2）==")
    print(f"仓库根: {ROOT}")

    venv_ok, venv_detail = check_venv()
    results: list[tuple[str, bool, str]] = []

    if venv_ok:
        results.append(("① doctor.py exit 0", *check_doctor()))
        results.append(("② pytest tests/ 全绿", *check_pytest_all()))
        results.append(("③ 模块 eval 入口 W3/W6/W7/W2 逐个 exit 0", *check_module_evals()))
    else:
        skip = f"跳过：{venv_detail}"
        results.append(("① doctor.py exit 0", False, skip))
        results.append(("② pytest tests/ 全绿", False, skip))
        results.append(("③ 模块 eval 入口 W3/W6/W7/W2 逐个 exit 0", False, skip))
    results.append(("④ 中性名扫描零命中", *check_neutral_names()))
    results.append(("⑤ 禁止 IO 扫描零命中", *check_forbidden_io()))

    failed = 0
    for name, ok, detail in results:
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"{mark} {name}: {detail}")
        if not ok:
            failed += 1

    print("----------------------------")
    if failed == 0:
        print(f"GATE D2: PASS ({len(results)}/{len(results)})")
        return 0
    print(f"GATE D2: FAIL ({failed}/{len(results)} 项未通过)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
