"""M10 质量护照：证据卡素材（裁剪图内嵌 + 缺图占位图）。

- 裁剪图（``BeanObservation.crop_path``）存在则读回并转
  ``data:image/png;base64,...`` 内嵌，使 HTML 护照自包含单文件；
  读取一律走 ``imencode/imdecode`` 字节缓冲（工程路径含中文，cv2 直接
  传路径会静默失败——W0b 实测坑，与采集包同约定）。
- 裁剪图缺失 / 损坏时**不中断**，生成确定性占位图（占位图上标注豆号、
  「PLACEHOLDER」与盘面坐标 mm——W10 验收「占位图+坐标」），卡片按
  三语文案标记「占位图（无裁剪证据）」。
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import cv2
import numpy as np

from beaneye.schemas import BeanObservation

__all__ = ["DEFECT_TINT_BGR", "placeholder_png", "load_crop_data_uri", "side_image"]

# 占位图豆体色调（BGR；按缺陷类的视觉联想，仅示意，不做判定依据）
DEFECT_TINT_BGR: dict[str, tuple[int, int, int]] = {
    "normal": (168, 190, 148),
    "black": (45, 42, 40),
    "mold": (216, 200, 235),
    "sour": (60, 130, 200),
    "insect": (90, 110, 170),
    "dried": (90, 150, 200),
    "broken": (110, 150, 215),
    "brocade": (150, 170, 225),
    "immature": (160, 200, 225),
    "faded": (200, 220, 240),
    "shell": (170, 205, 235),
    "elephant": (120, 180, 240),
    "peaberry": (150, 190, 235),
}
_DEFAULT_TINT = (140, 170, 220)

_PLACEHOLDER_SIZE = (160, 120)  # (w, h)


def placeholder_png(
    bean_id: str,
    defect_key: str,
    centroid_mm: tuple[float, float] | None,
    *,
    side: str = "",
) -> bytes:
    """确定性占位图 PNG：豆号 + PLACEHOLDER + 盘面坐标（mm）。

    同一 ``(bean_id, side)`` 输入像素级一致（用 sha256 派生扰动）。
    """
    w, h = _PLACEHOLDER_SIZE
    img = np.full((h, w, 3), (246, 244, 238), dtype=np.uint8)
    seed = hashlib.sha256(f"{bean_id}|{side}".encode("utf-8")).digest()
    jitter = int(seed[0]) % 17 - 8
    tint = np.array(DEFECT_TINT_BGR.get(defect_key, _DEFAULT_TINT), dtype=np.int16)
    tint = np.clip(tint + jitter, 0, 255).astype(np.uint8)
    center = (w // 2, h // 2 - 2)
    axes = (int(w * 0.30 + seed[1] % 7), int(h * 0.34 + seed[2] % 5))
    angle = int(seed[3] % 180)
    cv2.ellipse(img, center, axes, angle, 0, 360, tint.tolist(), -1, lineType=cv2.LINE_AA)
    cv2.ellipse(img, center, axes, angle, 0, 360, (120, 120, 120), 1, lineType=cv2.LINE_AA)

    dark = (60, 60, 60)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (170, 170, 170), 1)
    cv2.putText(img, bean_id, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, dark, 1, cv2.LINE_AA)

    label = "PLACEHOLDER"
    (lw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
    cv2.putText(img, label, ((w - lw) // 2, h // 2 + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (110, 110, 110), 1, cv2.LINE_AA)

    if centroid_mm is not None:
        coord = f"({centroid_mm[0]:.1f},{centroid_mm[1]:.1f})mm"
        cv2.putText(img, coord, (6, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.40, dark, 1, cv2.LINE_AA)

    ok, buf = cv2.imencode(".png", img)
    if not ok:  # pragma: no cover - 内存编码不会失败，防御性兜底
        raise RuntimeError("占位图 PNG 编码失败")
    return buf.tobytes()


def load_crop_data_uri(path: str | Path) -> str | None:
    """读回裁剪图并转 data URI；文件缺失/损坏返回 None（调用方落占位图）。"""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        buf = np.frombuffer(p.read_bytes(), dtype=np.uint8)
    except OSError:
        return None
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)  # 中文路径安全（字节缓冲）
    if img is None:
        return None
    if img.ndim == 2:  # 灰度 → BGR，统一编码
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    ok, enc = cv2.imencode(".png", img)
    if not ok:
        return None
    return "data:image/png;base64," + base64.b64encode(enc.tobytes()).decode("ascii")


def side_image(
    obs: BeanObservation | None,
    *,
    bean_id: str,
    defect_key: str,
    crop_root: Path,
) -> dict[str, object]:
    """单面证据素材：``{img_uri, placeholder, centroid, coord_text}``。

    ``obs`` 为 None（该面无观测）→ 各字段置空，卡片显示「无」。
    """
    if obs is None:
        return {
            "img_uri": None,
            "placeholder": False,
            "centroid": None,
            "coord_text": None,
            "has_obs": False,
        }
    uri = load_crop_data_uri(_resolve(crop_root, obs.crop_path))
    placeholder = uri is None
    if placeholder:
        raw = placeholder_png(bean_id, defect_key, obs.mask.centroid_mm, side=obs.side)
        uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    x, y = obs.mask.centroid_mm
    return {
        "img_uri": uri,
        "placeholder": placeholder,
        "centroid": (x, y),
        "coord_text": f"{x:.2f}, {y:.2f} mm",
        "has_obs": True,
    }


def _resolve(root: Path, rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else root / p
