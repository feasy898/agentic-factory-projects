"""M2 采集测试：Mock 帧序列 + Usb 无设备优雅报错两分支（§4 W2 eval）。

运行（仓库根）::

    pytest tests/test_acquisition.py -q

对应开发指令 §4 M2 通过线：
- Mock 产出 TrayScan 通过 M1 校验；双图存在且分辨率一致；
- Usb 无相机时构造/采集优雅报错（AcquisitionError + 提示 Mock）而非 traceback；
- ``--list-cams`` 无相机退出码 2 而非异常（CLI 逻辑注入测试 + 真机运行见冒烟）。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from beaneye import schemas
from beaneye.acquisition import (
    AcquisitionError,
    MockSource,
    Source,
    SynthSource,
    UsbSource,
    imread_bgr,
    imwrite_bgr,
    load_camera_config,
    scan_paths,
)
from beaneye.acquisition import usb as usb_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMERA_YAML = REPO_ROOT / "configs" / "camera.yaml"

# 本机（无相机服务器）上确定不存在的 DirectShow 设备号：
# 即便机器插了 1-2 台相机，31/32 也超出 Windows 枚举范围。
GHOST_TOP = 31
GHOST_BOTTOM = 32


# ---------------------------------------------------------------------------
# 分支一：MockSource 内置合成帧序列
# ---------------------------------------------------------------------------


class TestMockSequence:
    def test_sequence_of_pairs_passes_m1(self, tmp_path: Path) -> None:
        """帧序列：连采 3 对，每个 TrayScan 过 M1 往返、双图存在且分辨率一致。"""
        src = MockSource(tmp_path, n_beans=25, width=320, height=320, seed=7)
        scans = [src.capture_pair("sample_001", "tray_01") for _ in range(3)]

        assert [s.scan_id for s in scans] == [
            "scan_mock_0001",
            "scan_mock_0002",
            "scan_mock_0003",
        ]
        paths = [scan_paths(s, tmp_path) for s in scans]
        for scan, pp in zip(scans, paths):
            assert scan.source == "mock"
            assert scan.sample_id == "sample_001" and scan.tray_id == "tray_01"
            assert scan.calibration is None  # 标定是 M3 职责
            # M1 契约往返无损
            rt = schemas.TrayScan.from_json(scan.to_json())
            assert rt == scan
            # 双图存在 + 分辨率一致 + 是真实解码的 3 通道图
            top = imread_bgr(pp["top"])
            bot = imread_bgr(pp["bottom"])
            assert top.shape == bot.shape == (320, 320, 3)
            # 相对路径以 out_dir 为根
            assert pp["top"].is_file() and pp["bottom"].is_file()

    def test_manifest_json_next_to_images(self, tmp_path: Path) -> None:
        """每对帧落 manifest.json（TrayScan JSON），与返回对象逐字段一致。"""
        src = MockSource(tmp_path, n_beans=10, width=256, height=256, seed=3)
        scan = src.capture_pair("s1", "t1")
        manifest = tmp_path / scan.scan_id / "manifest.json"
        assert manifest.is_file()
        loaded = schemas.TrayScan.from_json(manifest.read_text(encoding="utf-8"))
        assert loaded == scan

    def test_deterministic_same_seed_pixel_identical(self, tmp_path: Path) -> None:
        """同 seed 同帧序 → 像素级一致；不同 seed → 不同图。"""
        a = MockSource(tmp_path / "a", n_beans=20, width=256, height=256, seed=42)
        b = MockSource(tmp_path / "b", n_beans=20, width=256, height=256, seed=42)
        c = MockSource(tmp_path / "c", n_beans=20, width=256, height=256, seed=43)
        sa, sb, sc = a.capture_pair("s", "t"), b.capture_pair("s", "t"), c.capture_pair("s", "t")
        top_a = imread_bgr(scan_paths(sa, tmp_path / "a")["top"])
        top_b = imread_bgr(scan_paths(sb, tmp_path / "b")["top"])
        top_c = imread_bgr(scan_paths(sc, tmp_path / "c")["top"])
        assert np.array_equal(top_a, top_b)
        assert not np.array_equal(top_a, top_c)

    def test_bottom_differs_from_top_but_same_layout_seed(self, tmp_path: Path) -> None:
        """成对图：top 与 bottom 同布局但受翻面抖动/光照扰动 → 像素不同。"""
        src = MockSource(tmp_path, n_beans=15, width=256, height=256, seed=5)
        scan = src.capture_pair("s", "t")
        pp = scan_paths(scan, tmp_path)
        assert not np.array_equal(imread_bgr(pp["top"]), imread_bgr(pp["bottom"]))

    def test_satisfies_camera_source_contract(self, tmp_path: Path) -> None:
        """结构满足冻结契约 CameraSource Protocol（capture_pair 签名兼容）。"""
        src = MockSource(tmp_path, n_beans=5, width=128, height=128)
        assert isinstance(src, Source)
        sig = inspect.signature(src.capture_pair)
        params = list(sig.parameters)
        assert params[:2] == ["sample_id", "tray_id"]
        assert sig.return_annotation in ("TrayScan", schemas.TrayScan)

    def test_mock_image_has_content(self, tmp_path: Path) -> None:
        """合成帧非空盘：前景（深色豆）与浅背景有可分割的对比度。"""
        src = MockSource(tmp_path, n_beans=40, width=256, height=256, seed=11, defect_rate=0.2)
        scan = src.capture_pair("s", "t")
        top = imread_bgr(scan_paths(scan, tmp_path)["top"])
        dark_ratio = float((top.mean(axis=2) < 100).mean())
        assert 0.005 < dark_ratio < 0.6, f"前景占比异常: {dark_ratio:.3f}"

    def test_mock_frames_carry_detectable_aruco(self, tmp_path: Path) -> None:
        """四角 ArUco（id=0..3）在双面帧上可检测 —— Mock 帧可直接喂 M3 标定。

        回归锚点（W13 更新）：码心取 configs/tray.yaml 的 centers_mm（贴盘角
        30mm），side/4 静区伸出盘外由画布外缘（20mm 视野边）完整保住
        （W2 实测坑：静区被裁则检测失败——用视野外缘而非内缩码心解决）。
        512px 为最小可检分辨率。
        """
        import cv2

        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        for width in (512, 1024):
            src = MockSource(tmp_path / f"w{width}", n_beans=30, width=width, height=width, seed=7)
            scan = src.capture_pair("s", "t")
            for side_key in ("top", "bottom"):
                img = imread_bgr(scan_paths(scan, tmp_path / f"w{width}")[side_key])
                ids = detector.detectMarkers(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))[1]
                found = sorted(int(i[0]) for i in ids) if ids is not None else []
                assert found == [0, 1, 2, 3], f"{width}px {side_key}: 检出 {found}"

    def test_mock_frame_calibrates_against_default_tray_config(self, tmp_path: Path) -> None:
        """Mock 帧对默认配置标定：px_per_mm 相对误差 <1%（W13 修复①的回归锚点）。

        码位几何单一真源 = configs/tray.yaml（Mock / make_aruco / 标定同坐标）。
        修复前 Mock 自行内缩到 45mm 而配置是 30mm，跨距 210mm 被配到 240mm，
        本测试会以 ~14% 尺度误差失败——「检测点对配置点」的自洽门（2mm）挡
        不住这种布局漂移，必须靠这条端到端断言。
        """
        from beaneye.calibration import calibrate, load_tray_config

        src = MockSource(tmp_path, n_beans=30, seed=7)  # 默认 2048×2048
        scan = src.capture_pair("s", "t")
        img = imread_bgr(scan_paths(scan, tmp_path)["top"])

        cal = calibrate(img, load_tray_config())
        ppm_rel = abs(cal.px_per_mm - src.px_per_mm) / src.px_per_mm
        assert ppm_rel < 0.01, (
            f"Mock 帧标定 px_per_mm 相对误差 {ppm_rel * 100:.2f}% ≥ 1%——"
            "Mock 布局与 configs/tray.yaml 已漂移（码位几何单一真源被破坏）"
        )
        # 四码中心反投影 ≤1mm（合成空盘检测残差口径，比 0.5mm 主通过线放宽）
        from beaneye.calibration import px_to_mm

        errs = [
            float(np.linalg.norm(np.asarray(px_to_mm(cal.centers_px[m], cal.H)) - np.asarray(c)))
            for m, c in load_tray_config().centers_mm.items()
        ]
        assert max(errs) <= 1.0, f"Mock 帧码中心反投影最大误差 {max(errs):.3f}mm > 1mm"


# ---------------------------------------------------------------------------
# 分支二：UsbSource 无设备时优雅报错
# ---------------------------------------------------------------------------


class TestUsbNoDevice:
    def test_constructor_raises_acquisition_error_with_mock_hint(self, tmp_path: Path) -> None:
        """无相机：构造即抛 AcquisitionError（非 cv2/系统异常），且提示 Mock。"""
        with pytest.raises(AcquisitionError) as ei:
            UsbSource(tmp_path, top_index=GHOST_TOP, bottom_index=GHOST_BOTTOM, warmup_frames=0)
        msg = str(ei.value)
        assert "MockSource" in msg
        assert str(GHOST_TOP) in msg

    def test_error_is_not_traceback_leak(self, tmp_path: Path) -> None:
        """优雅报错分支：不是 cv2.error / OSError / 裸 RuntimeError。"""
        with pytest.raises(AcquisitionError):
            UsbSource(tmp_path, top_index=GHOST_TOP, bottom_index=GHOST_BOTTOM, warmup_frames=0)

    def test_list_cams_cli_exit_2_when_no_cams(self, monkeypatch, capsys, tmp_path: Path) -> None:
        """--list-cams 无相机 → 退出码 2 且打印提示（注入空探测，机器无关）。"""
        monkeypatch.setattr(usb_mod, "probe_cameras", lambda indices, *, width, height: [])
        rc = usb_mod.main(["--list-cams", "--config", str(CAMERA_YAML)])
        out = capsys.readouterr().out
        assert rc == 2
        assert "未发现任何相机" in out
        assert "MockSource" in out

    def test_list_cams_cli_exit_0_when_found(self, monkeypatch, capsys, tmp_path: Path) -> None:
        """--list-cams 有相机 → 退出码 0 且列出设备号与分辨率（注入）。"""
        monkeypatch.setattr(
            usb_mod, "probe_cameras", lambda indices, *, width, height: [(0, (3840, 2160))]
        )
        rc = usb_mod.main(["--list-cams", "--config", str(CAMERA_YAML)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "index=0" in out and "3840x2160" in out

    def test_camera_yaml_loads_with_required_keys(self) -> None:
        cfg = load_camera_config(CAMERA_YAML)
        assert cfg["top_index"] == 0 and cfg["bottom_index"] == 1
        assert (cfg["width"], cfg["height"]) == (3840, 2160)
        assert cfg["warmup_frames"] >= 0


# ---------------------------------------------------------------------------
# UsbSource 注入测试（W13 修复⑧：读失败关-开恢复 + 分辨率读回核对，机器无关）
# ---------------------------------------------------------------------------


class _FakeCap:
    """cv2.VideoCapture 替身：可编程 isOpened/set/get/read 行为。

    ``fail_reads`` 预算按**设备号跨实例共享**（同设备号的前 N 次 read 失败，
    之后全部成功）——这样「重开后的新实例读到成功帧」可被真实模拟。
    """

    calls: list[str] = []
    _fail_budget: dict[int, int] = {}

    def __init__(self, behavior: dict, index: int = 0) -> None:
        self._b = behavior
        self._index = index
        self.released = False
        self.read_calls = 0
        self.w = behavior.get("reported_wh", (640, 480))[0]
        self.h = behavior.get("reported_wh", (640, 480))[1]
        type(self).calls.append(f"open{index}")

    def isOpened(self) -> bool:
        return not self.released and self._b.get("opens", True)

    def set(self, prop: int, value: float) -> bool:
        type(self).calls.append(f"set{self._index}")
        return True

    def get(self, prop: int) -> float:
        if prop == 3:  # CAP_PROP_FRAME_WIDTH
            return float(self.w)
        if prop == 4:  # CAP_PROP_FRAME_HEIGHT
            return float(self.h)
        return 0.0

    def grab(self) -> bool:
        return True

    def read(self) -> tuple[bool, object]:
        self.read_calls += 1
        type(self).calls.append(f"read{self._index}#{self.read_calls}")
        budget = type(self)._fail_budget.get(self._index, 0)
        if budget > 0:
            type(self)._fail_budget[self._index] = budget - 1
            return False, None
        return True, np.zeros((self.h, self.w, 3), dtype=np.uint8)

    def release(self) -> None:
        self.released = True
        type(self).calls.append(f"release{self._index}")


def _install_fake_cv2(monkeypatch, behavior_by_index: dict[int, dict]) -> list[str]:
    """把 usb 模块可见的 cv2.VideoCapture 换成替身工厂，返回调用日志。"""
    import beaneye.acquisition.usb as usb

    _FakeCap.calls = []
    _FakeCap._fail_budget = {i: b.get("fail_reads", 0) for i, b in behavior_by_index.items()}

    def factory(index: int, backend: int = None):  # noqa: ANN001
        return _FakeCap(behavior_by_index.get(index, {}), index)

    monkeypatch.setattr(usb.cv2, "VideoCapture", factory)
    return _FakeCap.calls


class TestUsbRecoveryInjected:
    def test_read_failure_reopens_once_and_succeeds(self, monkeypatch, tmp_path: Path) -> None:
        """读帧失败 → release + 重开 + 重读成功（热插拔恢复，W13 ⑧）。

        fail_reads=1：top 同设备号的前 1 次读失败（构造后的首读），重开后的
        实例读到成功帧；构造期只 warmup(grab) 不 read，不触发。
        """
        calls = _install_fake_cv2(monkeypatch, {0: {"reported_wh": (3840, 2160), "fail_reads": 1},
                                                1: {"reported_wh": (3840, 2160)}})
        src = UsbSource(tmp_path, top_index=0, bottom_index=1, warmup_frames=0)
        scan = src.capture_pair("s", "t")
        assert scan.source == "usb"
        assert any(c.startswith("release0") for c in calls), "读失败后必须先 release"
        assert calls.count("open0") == 2, f"top 相机应重开一次，实际 opens={calls.count('open0')}"
        src.close()

    def test_persistent_read_failure_raises_acquisition_error(self, monkeypatch, tmp_path: Path) -> None:
        """重开后仍读失败 → AcquisitionError（不再无限重试）。"""
        _install_fake_cv2(monkeypatch, {0: {"reported_wh": (3840, 2160), "fail_reads": 99},
                                        1: {"reported_wh": (3840, 2160)}})
        src = UsbSource(tmp_path, top_index=0, bottom_index=1, warmup_frames=0)
        with pytest.raises(AcquisitionError, match="仍读帧失败"):
            src.capture_pair("s", "t")
        src.close()

    def test_resolution_mismatch_raises_acquisition_error(self, monkeypatch, tmp_path: Path) -> None:
        """UVC 静默忽略请求分辨率（get 读回不符）→ AcquisitionError（W13 ⑧）。"""
        _install_fake_cv2(monkeypatch, {0: {"reported_wh": (1920, 1080)},   # 请求 3840x2160
                                        1: {"reported_wh": (3840, 2160)}})
        with pytest.raises(AcquisitionError, match="实际分辨率 1920x1080"):
            UsbSource(tmp_path, top_index=0, bottom_index=1, warmup_frames=0)

    def test_resolution_match_opens_normally(self, monkeypatch, tmp_path: Path) -> None:
        """分辨率读回与请求一致 → 正常构造 + capture_pair 出 TrayScan。"""
        _install_fake_cv2(monkeypatch, {0: {"reported_wh": (3840, 2160), "reads": 0},
                                        1: {"reported_wh": (3840, 2160), "reads": 0}})
        src = UsbSource(tmp_path, top_index=0, bottom_index=1, warmup_frames=1)
        scan = src.capture_pair("s", "t")
        assert scan.calibration is None
        assert src.resolutions() == {"top": (3840, 2160), "bottom": (3840, 2160)}
        src.close()


# ---------------------------------------------------------------------------
# SynthSource 接口占位（W12b 后补）
# ---------------------------------------------------------------------------


def test_synth_source_stub_reserved_interface(tmp_path: Path) -> None:
    src = SynthSource(tmp_path)
    with pytest.raises(AcquisitionError) as ei:
        src.capture_pair("s", "t")
    assert "W12b" in str(ei.value)
    assert isinstance(src, Source)


# ---------------------------------------------------------------------------
# 中文路径图像 IO（D1 实测坑 ① 的回归锚点）
# ---------------------------------------------------------------------------


class TestUnicodePathIO:
    def test_roundtrip_chinese_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "采集目录_澄迈" / "豆盘_top.png"
        img = np.arange(3 * 64 * 64, dtype=np.uint8).reshape(64, 64, 3)
        written = imwrite_bgr(target, img)
        assert written.is_file()
        back = imread_bgr(target)
        assert back.shape == img.shape
        assert np.array_equal(back, img)  # PNG 无损：imencode/imdecode 往返逐像素一致

    def test_read_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AcquisitionError):
            imread_bgr(tmp_path / "不存在.png")

    def test_write_bad_extension_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AcquisitionError):
            imwrite_bgr(tmp_path / "x.txt", np.zeros((4, 4, 3), dtype=np.uint8))

    def test_decode_garbage_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image at all")
        with pytest.raises(AcquisitionError):
            imread_bgr(bad)
