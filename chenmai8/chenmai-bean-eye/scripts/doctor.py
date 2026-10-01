#!/usr/bin/env python3
"""BeanEye 环境体检（doctor）。

逐项检查并输出 [OK]/[NG] 清单：
  1) Python 版本（锚定 3.12.x）与是否使用本项目 .venv
  2) requirements.txt 全部钉版依赖：可导入、且安装版本与钉版一致
  3) OpenCV ArUco 功能可用（M3 标定硬依赖，不只是 import）
  4) ffmpeg（可选：仅演示视频剪辑用，主管线不依赖）
  5) 中文字体（M10 三语护照直方图中文渲染需要，SimHei 为主）

结尾打印 `DOCTOR: PASS` 或 `DOCTOR: FAIL (n)`。
退出码：必需项全部通过 = 0；任一必需项 [NG] = 1。
可选项（标注"可选"）失败不影响退出码。

用法：
    ./.venv/Scripts/python.exe scripts/doctor.py
"""

from __future__ import annotations

import importlib
import importlib.metadata as importlib_metadata
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 输出统一 UTF-8（Windows 下被重定向时 Python 3.12 默认跟随 GBK 代码页，会乱码）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
REQ_FILE = ROOT / "requirements.txt"

REQUIRED_PYTHON = (3, 12)

# albumentations 由 setup_env.ps1 以 --no-deps 安装（不在 requirements.txt 内），
# 钉版在此独立核对；三处必须一致：requirements.txt 注释 / setup_env.ps1 / 此处。
ALBUMENTATIONS_PIN = "2.0.8"

# requirements.txt 中的发行名 -> 实际 import 名（不一致者列出，其余同名）
DIST_TO_MODULE = {
    "opencv-python": "cv2",
    "scikit-image": "skimage",
    "pillow": "PIL",
    "pyyaml": "yaml",
    "zxing-cpp": "zxingcpp",
    "python-multipart": "python_multipart",
}

PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.+!_-]*)$")


def parse_pins() -> list[tuple[str, str]]:
    """从 requirements.txt 解析 (发行名, 钉版) 列表；跳过注释与空行。"""
    pins: list[tuple[str, str]] = []
    for raw in REQ_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = PIN_RE.match(line)
        if not m:
            raise SystemExit(f"[doctor] requirements.txt 存在无法解析的行: {raw!r}")
        pins.append((m.group(1), m.group(2)))
    return pins


def check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    ok = (v.major, v.minor) == REQUIRED_PYTHON
    detail = (
        f"{v.major}.{v.minor}.{v.micro} ({platform.python_implementation()}) "
        f"@ {sys.executable}"
    )
    return ok, detail


def check_project_venv() -> tuple[bool, str]:
    exe = Path(sys.executable).resolve()
    venv_dir = (ROOT / ".venv").resolve()
    in_project_venv = venv_dir in exe.parents
    if in_project_venv:
        return True, f"使用项目 venv: {venv_dir}"
    return False, (
        f"未运行于项目 venv（当前解释器 {exe}，期望位于 {venv_dir} 下）；"
        "请用 .venv\\Scripts\\python.exe 运行本脚本"
    )


def check_dependency(dist: str, pin: str) -> tuple[bool, str]:
    module_name = DIST_TO_MODULE.get(dist, dist)
    # 1) 可导入
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # ImportError 及包自身导入期错误都算 NG
        return False, f"import {module_name} 失败: {exc.__class__.__name__}: {exc}"
    # 2) 安装版本与钉版一致（以发行元数据为准）
    try:
        installed = importlib_metadata.version(dist)
    except importlib_metadata.PackageNotFoundError:
        return False, f"模块 {module_name} 可导入，但发行包 {dist} 未安装"
    if installed != pin:
        return False, f"版本不符: 安装 {installed} != 钉版 {pin}"
    # 3) 模块自报版本交叉核对（存在 __version__ 时；不一致仅提示不判负）
    extra = ""
    mod_ver = getattr(module, "__version__", None)
    if mod_ver and str(mod_ver) != installed:
        extra = f"（注意: {module_name}.__version__={mod_ver} 与元数据不一致）"
    return True, f"{dist}=={installed}{extra}"


def check_cv2_aruco() -> tuple[bool, str]:
    """ArUco 功能冒烟：渲染 DICT_4X4_50 的 id=0 码并检测回（M3 标定硬依赖）。

    注意：生成的码四周必须有白色静区（quiet zone），否则检测器找不到边界。
    """
    try:
        import cv2

        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        marker = cv2.aruco.generateImageMarker(dictionary, 0, 64)
        # 四周加 16px 白边作为静区
        canvas = cv2.copyMakeBorder(
            marker, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=255
        )
        detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        corners, ids, _ = detector.detectMarkers(canvas)
        if ids is not None and len(ids) == 1 and int(ids[0][0]) == 0:
            return True, f"cv2 {cv2.__version__}: DICT_4X4_50 渲染+检测正常"
        return False, f"cv2 {cv2.__version__}: ArUco 检测结果异常 ids={ids}"
    except Exception as exc:
        return False, f"ArUco 冒烟失败: {exc.__class__.__name__}: {exc}"


def check_albumentations() -> tuple[bool, str]:
    """albumentations（setup_env.ps1 --no-deps 安装，独立于 requirements.txt 核对）。"""
    try:
        import albumentations  # noqa: F401

        installed = importlib_metadata.version("albumentations")
    except Exception as exc:
        return False, f"导入/定位失败: {exc.__class__.__name__}: {exc}"
    if installed != ALBUMENTATIONS_PIN:
        return False, f"版本不符: 安装 {installed} != 钉版 {ALBUMENTATIONS_PIN}"
    return True, f"albumentations=={installed}（--no-deps，规避 opencv-headless 冲突）"


def check_ffmpeg() -> tuple[bool, str]:
    """ffmpeg（可选，仅演示视频剪辑需要，主管线不依赖）。"""
    exe = shutil.which("ffmpeg")
    if not exe:
        return False, "PATH 中未找到 ffmpeg（可选；视频剪辑时再装）"
    try:
        proc = subprocess.run(
            [exe, "-version"], capture_output=True, text=True, timeout=20
        )
        m = re.search(r"ffmpeg version (\S+)", proc.stdout or "")
        version = m.group(1) if m else "未知版本"
        return True, f"{exe} ({version})"
    except Exception as exc:
        return False, f"ffmpeg 存在但执行失败: {exc}"


def check_fonts() -> tuple[bool, str]:
    """中文字体（SimHei 必须；雅黑/宋体加分项）。"""
    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = {
        "simhei.ttf": "SimHei 黑体（必须）",
        "msyh.ttc": "微软雅黑",
        "simsun.ttc": "宋体",
    }
    found, missing = [], []
    for fname, label in candidates.items():
        (found if (fonts_dir / fname).is_file() else missing).append(
            f"{label}:{fname}"
        )
    if any("simhei" in f for f in found):
        return True, f"{fonts_dir} 命中: {'; '.join(found)}"
    detail = f"{fonts_dir} 缺少 SimHei（simhei.ttf）"
    if missing:
        detail += f"；缺失项: {'; '.join(missing)}"
    return False, detail


def main() -> int:
    print("== BeanEye 环境体检（doctor）==")
    results: list[tuple[str, bool, str, bool]] = []  # (名称, 是否通过, 详情, 是否必需)

    results.append(("python", *check_python_version(), True))
    results.append(("venv", *check_project_venv(), True))

    pins = parse_pins()
    print(f"-- 依赖钉版核对（{REQ_FILE.name}，共 {len(pins)} 项）--")
    for dist, pin in pins:
        results.append((f"dep:{dist}", *check_dependency(dist, pin), True))

    results.append(("cv2.aruco", *check_cv2_aruco(), True))
    results.append(("albumentations", *check_albumentations(), True))
    results.append(("ffmpeg", *check_ffmpeg(), False))
    results.append(("fonts", *check_fonts(), True))

    failed_required = 0
    for name, ok, detail, required in results:
        mark = "[OK]" if ok else "[NG]"
        suffix = "" if required else "（可选）"
        print(f"{mark} {name}{suffix}: {detail}")
        if not ok and required:
            failed_required += 1

    print("----------------------------")
    if failed_required == 0:
        print("DOCTOR: PASS")
        return 0
    print(f"DOCTOR: FAIL ({failed_required} 项必需检查未通过)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
