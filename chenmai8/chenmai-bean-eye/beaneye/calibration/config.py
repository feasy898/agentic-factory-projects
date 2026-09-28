"""M3 托盘标定配置（configs/tray.yaml）的加载与校验。

只依赖 PyYAML（不 import cv2/numpy），保证 ``beaneye.calibration`` 的配置面
在任何轻量场景可独立使用。全部校验失败抛 :class:`TrayConfigError`，
错误信息带文件路径与字段名，便于现场排查。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "tray.yaml"

# ArUco 字典名形如 DICT_4X4_50 / DICT_6X6_250（cv2.aruco 常量名）；格式在加载期把关，
# 具体字典是否存在在检测期由 cv2 解析（见 core._detect_markers）。
_DICT_NAME_RE = re.compile(r"^DICT_\d+X\d+_\d+$")

_CORNER_KEYS = ("lt", "rt", "rb", "lb")
_INTERP_CHOICES = ("linear", "cubic", "nearest")


class TrayConfigError(ValueError):
    """托盘配置缺失 / YAML 非法 / 字段越界或自相矛盾。"""


@dataclass(frozen=True)
class TrayConfig:
    """托盘几何与 ArUco 布局（_immutable_，标定全程只读）。

    ``centers_mm``：marker id → 码中心盘面 mm 坐标。角位公式只是默认值，
    异形托盘可显式给任意四点（无三点共线即可），配对永远按 id。
    """

    tray_mm: float
    grid_px: int
    dictionary: str
    marker_mm: float
    centers_mm: dict[int, tuple[float, float]]
    corner_ids: dict[str, int]
    interp: str = "linear"
    border_value: int = 235

    @property
    def mm_per_px(self) -> float:
        """正射网格分辨率（mm/px）= tray_mm / grid_px。"""
        return self.tray_mm / self.grid_px

    @property
    def center_mm(self) -> tuple[float, float]:
        """盘面中心（px_per_mm 的估计点）。"""
        h = self.tray_mm / 2.0
        return (h, h)


def load_tray_config(path: str | Path | None = None) -> TrayConfig:
    """加载并校验托盘配置；``path=None`` 用仓库默认 ``configs/tray.yaml``。"""
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not p.is_file():
        raise TrayConfigError(f"托盘配置文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TrayConfigError(f"托盘配置 YAML 解析失败 {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TrayConfigError(f"托盘配置顶层必须是映射，{p} 得到 {type(raw).__name__}")

    where = f"{p}"

    def _num(key: str) -> float:
        val = raw.get(key, None)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TrayConfigError(f"{where}: `{key}` 必须是数值，得到 {val!r}")
        v = float(val)
        if not math.isfinite(v):
            raise TrayConfigError(f"{where}: `{key}` 必须是有限数，得到 {v}")
        return v

    tray_mm = _num("tray_mm")
    if not (0.0 < tray_mm <= 2000.0):
        raise TrayConfigError(f"{where}: `tray_mm` 必须在 (0, 2000] mm，得到 {tray_mm}")
    grid_px = raw.get("grid_px", None)
    if isinstance(grid_px, bool) or not isinstance(grid_px, int):
        raise TrayConfigError(f"{where}: `grid_px` 必须是整数，得到 {grid_px!r}")
    if not (0 < grid_px <= 16384):
        raise TrayConfigError(f"{where}: `grid_px` 必须在 (0, 16384]，得到 {grid_px}")

    aruco = raw.get("aruco", None)
    if not isinstance(aruco, dict):
        raise TrayConfigError(f"{where}: 缺少 `aruco` 节或其不是映射")
    dictionary = aruco.get("dictionary", None)
    if not isinstance(dictionary, str) or not _DICT_NAME_RE.match(dictionary):
        raise TrayConfigError(
            f"{where}: `aruco.dictionary` 必须形如 DICT_4X4_50，得到 {dictionary!r}"
        )
    marker_mm = aruco.get("marker_mm", None)
    if isinstance(marker_mm, bool) or not isinstance(marker_mm, (int, float)):
        raise TrayConfigError(f"{where}: `aruco.marker_mm` 必须是数值，得到 {marker_mm!r}")
    marker_mm = float(marker_mm)
    if not (0.0 < marker_mm):
        raise TrayConfigError(f"{where}: `aruco.marker_mm` 必须 > 0 mm，得到 {marker_mm}")
    if marker_mm * 2.0 >= tray_mm:
        raise TrayConfigError(
            f"{where}: 码边长过大（marker_mm={marker_mm}, tray_mm={tray_mm}），四角码会重叠"
        )

    corner_ids = aruco.get("corner_ids", None)
    if not isinstance(corner_ids, dict) or set(corner_ids) != set(_CORNER_KEYS):
        raise TrayConfigError(f"{where}: `aruco.corner_ids` 必须含且仅含 {list(_CORNER_KEYS)}")
    cid: dict[str, int] = {}
    for k in _CORNER_KEYS:
        v = corner_ids[k]
        if isinstance(v, bool) or not isinstance(v, int):
            raise TrayConfigError(f"{where}: `aruco.corner_ids.{k}` 必须是整数 id，得到 {v!r}")
        cid[k] = v
    if sorted(cid.values()) != [0, 1, 2, 3]:
        raise TrayConfigError(
            f"{where}: `aruco.corner_ids` 的取值必须恰为 [0,1,2,3]（契约 CalibResult 要求），得到 {sorted(cid.values())}"
        )

    centers_raw = aruco.get("centers_mm", None)
    if not isinstance(centers_raw, dict) or not centers_raw:
        raise TrayConfigError(f"{where}: 缺少 `aruco.centers_mm`（四码中心 mm 坐标）")
    centers: dict[int, tuple[float, float]] = {}
    for k, v in centers_raw.items():
        try:
            mid = int(k)
        except (TypeError, ValueError) as exc:
            raise TrayConfigError(f"{where}: centers_mm 键必须是整数 marker id，得到 {k!r}") from exc
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            raise TrayConfigError(f"{where}: centers_mm[{mid}] 必须是 [x, y]，得到 {v!r}")
        try:
            x, y = float(v[0]), float(v[1])
        except (TypeError, ValueError) as exc:
            raise TrayConfigError(f"{where}: centers_mm[{mid}] 坐标必须是数值，得到 {v!r}") from exc
        if not (math.isfinite(x) and math.isfinite(y)):
            raise TrayConfigError(f"{where}: centers_mm[{mid}] 必须是有限坐标，得到 {v!r}")
        if not (0.0 <= x <= tray_mm and 0.0 <= y <= tray_mm):
            raise TrayConfigError(
                f"{where}: centers_mm[{mid}]=[{x}, {y}] 超出盘面 [0, {tray_mm}] mm"
            )
        centers[mid] = (x, y)
    if sorted(centers) != [0, 1, 2, 3]:
        raise TrayConfigError(
            f"{where}: centers_mm 必须恰含 id 0..3（契约 CalibResult 要求），得到 {sorted(centers)}"
        )
    _check_not_collinear(centers, where)

    warp = raw.get("warp", {}) or {}
    if not isinstance(warp, dict):
        raise TrayConfigError(f"{where}: `warp` 节必须是映射")
    interp = warp.get("interp", "linear")
    if interp not in _INTERP_CHOICES:
        raise TrayConfigError(f"{where}: `warp.interp` 必须是 {list(_INTERP_CHOICES)}，得到 {interp!r}")
    border = warp.get("border_value", 235)
    if isinstance(border, bool) or not isinstance(border, int) or not (0 <= border <= 255):
        raise TrayConfigError(f"{where}: `warp.border_value` 必须是 0..255 整数，得到 {border!r}")

    return TrayConfig(
        tray_mm=tray_mm,
        grid_px=grid_px,
        dictionary=dictionary,
        marker_mm=marker_mm,
        centers_mm=centers,
        corner_ids=cid,
        interp=interp,
        border_value=border,
    )


def _check_not_collinear(centers: dict[int, tuple[float, float]], where: str) -> None:
    """四码中心任意三点不得共线（否则单应退化无解）。"""
    ids = sorted(centers)
    pts = [centers[i] for i in ids]
    for a in range(4):
        for b in range(a + 1, 4):
            for c in range(b + 1, 4):
                (x0, y0), (x1, y1), (x2, y2) = pts[a], pts[b], pts[c]
                cross = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
                if abs(cross) < 1e-6:
                    raise TrayConfigError(
                        f"{where}: centers_mm 中 id {ids[a]}/{ids[b]}/{ids[c]} 三点共线，单应无解"
                    )
