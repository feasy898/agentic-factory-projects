"""proto_shot_qa 离线测试（不依赖网络/模型/真实素材；ffmpeg 在位时补一条合成视频 e2e）。

运行：.venv/bin/python -m pytest test_proto_shot_qa.py -v
契约来源：repo pipeline/contracts.py（独立加载，绕过包 __init__ 的重依赖）。
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]  # proto_shot_qa → video-understanding → research → repo
sys.path.insert(0, str(HERE))

import kfextract  # noqa: E402
import shot_qa  # noqa: E402


def _load_contracts():
    # contracts.py 开了 PEP 563：pydantic 解析前向引用需查 sys.modules，先注册再 exec
    p = REPO_ROOT / "pipeline" / "contracts.py"
    spec = importlib.util.spec_from_file_location("drama_contracts_test", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 单元：差异分

def test_diff_score_identical_zero():
    a = np.full((64, 64), 100, dtype=np.uint8)
    assert kfextract.diff_score(a, a) == 0.0


def test_diff_score_full_cut_high():
    a = np.zeros((64, 64), dtype=np.uint8)
    b = np.full((64, 64), 255, dtype=np.uint8)
    assert kfextract.diff_score(a, b) > 0.5


def test_diff_score_corner_change_detected_by_block():
    """全局均值会被稀释，分块最大值应抓出角落小变化（双角度取大）。"""
    a = np.zeros((64, 64), dtype=np.uint8)
    b = np.zeros((64, 64), dtype=np.uint8)
    b[:8, :8] = 255  # 仅 1/64 像素变化
    s = kfextract.diff_score(a, b)
    global_only = float(np.abs(a.astype(int) - b.astype(int)).mean()) / 255.0
    assert s > global_only * 4  # 分块显著放大局部变化
    assert s > 0.1


# ---------------------------------------------------------------- 单元：阈值

def test_auto_threshold_floor_and_cap():
    assert kfextract.auto_threshold([0.0001] * 100) == pytest.approx(0.008)  # 地板
    assert kfextract.auto_threshold([0.5] * 100) == pytest.approx(0.08)      # 天花板
    # 中位数底噪 × 4.0
    assert kfextract.auto_threshold([0.01] * 100, noise_k=4.0) == pytest.approx(0.04)


def test_auto_threshold_empty():
    assert kfextract.auto_threshold([]) == pytest.approx(0.008)


# ---------------------------------------------------------------- 单元：选帧

def test_select_first_and_settle():
    """稳定→1 秒变化→稳定：首帧 + 变化结束后的稳定帧；变化中途不选（<motion_time）。

    差分索引口径：diffs[k] = 帧 k 与 k+1 之差，故变化帧为 20..30、首个稳定帧为 31。
    """
    fps, min_t, motion_t = 10.0, 0.3, 1.5
    diffs = [0.001] * 20 + [0.2] * 10 + [0.001] * 20
    got = kfextract.select_frames(diffs, fps, 0.05, min_t, motion_t)
    assert got[0] == 0
    assert 31 in got              # 变化结束后的首个稳定帧
    assert got == [0, 31]         # 变化全程 1.0s < motion_time，中途不补帧


def test_select_motion_fallback():
    """持续变化超 motion_time 应中途补帧 + 变化结束后的稳定帧。

    变化帧 6..35（diffs[5..34]=0.3），首变化帧 6 起算，2.1s 处（帧 21）补一张；
    diffs[35]=0.001 → 帧 36 为首个稳定帧。
    """
    fps = 10.0
    diffs = [0.001] * 5 + [0.3] * 30 + [0.001] * 5
    got = kfextract.select_frames(diffs, fps, 0.05, 0.3, 1.5)
    assert got == [0, 21, 36]


def test_downsample_keeps_order_and_cap():
    idx = list(range(0, 100, 2))
    got = kfextract.downsample_indices(idx, 12)
    assert len(got) <= 12
    assert got == sorted(got)
    assert got[0] == idx[0] and got[-1] == idx[-1]


# ---------------------------------------------------------------- 解码覆盖率守卫

def test_coverage_ok_real_cases():
    """didaozhan_p1 实测坏例（570 帧/29.97fps vs 容器 1541.8s）必须判 False。"""
    assert kfextract.coverage_ok(570, 29.97, 1541.8) is False      # 坏文件实况
    assert kfextract.coverage_ok(258, 25.0, 10.32) is True          # e2e01 实况（100%）
    assert kfextract.coverage_ok(0, 25.0, 10.32) is False
    assert kfextract.coverage_ok(100, 25.0, 0.0) is True            # 容器无时长不判坏
    with pytest.raises(kfextract.DecodeCoverageError):
        raise kfextract.DecodeCoverageError(570, 29.97, 1541.8)


# ---------------------------------------------------------------- 契约兼容

def test_candidate_bounds_and_contract_shotsheet():
    C = _load_contracts()
    bounds = shot_qa.build_candidate_shots([1.0, 2.0, 9.9], 10.32)
    assert bounds[0] == 0.0 and bounds[-1] == pytest.approx(10.32)
    sheet = shot_qa.contract_shotsheet(C, "t", 25.0, 10.32, bounds)
    assert len(sheet.shots) == len(bounds) - 1
    sheet.model_validate(sheet.model_dump())  # C1 冻结约束（唯一 shot_id、end>start）通过


def test_candidate_bounds_rejects_out_of_range():
    bounds = shot_qa.build_candidate_shots([0.0, 10.32, 5.0], 10.32)
    assert 0.0 not in bounds[1:]
    assert all(b <= 10.32 for b in bounds)


# ---------------------------------------------------------------- e2e（合成视频，需 ffmpeg）

_has_ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.mark.skipif(not _has_ffmpeg, reason="ffmpeg 不在 PATH")
def test_e2e_synthetic_hard_cut(tmp_path):
    """红→蓝硬切（3s 处）：前处理应至少给出一个 3.0±0.7s 的变化点。"""
    vid = tmp_path / "cut.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=128x128:d=3:r=10",
         "-f", "lavfi", "-i", "color=c=blue:s=128x128:d=3:r=10",
         "-filter_complex", "[0][1]concat=n=2:v=1:a=0",
         "-pix_fmt", "yuv420p", str(vid)],
        check=True, timeout=120)
    meta = kfextract.extract(vid, tmp_path / "out", max_frames=50)
    times = [k["time"] for k in meta["keyframes"]]
    assert any(2.3 <= t <= 3.7 for t in times), f"切点附近无变化点: {times}"
    assert meta["overview_count"] >= 1
    kf = json.loads((tmp_path / "out" / "keyframes.json").read_text(encoding="utf-8"))
    assert kf["keyframe_count"] == meta["keyframe_count"]
