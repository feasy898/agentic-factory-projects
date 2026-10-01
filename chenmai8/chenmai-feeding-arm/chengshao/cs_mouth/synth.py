"""程序合成样本：卡通人脸 / 无脸场景 / 真人种子的确定性变体。

用途（开发指令 §5.3 样本获取的 D1 替代，真机样本由主人后补）：
- 卡通脸：检出率、时延、失效保持路径的负载帧（几何口径比无真值，jaw 标签为 null）；
- 无脸场景：valid=False 拒识路径；
- 变体：对真人种子做确定性光度/几何/压缩扰动，扩充样本而不引入新身份。

全部函数确定性（固定参数 + numpy Generator），同版本重跑逐字节一致（JPEG 压缩
参数固定）。
"""

from __future__ import annotations

import numpy as np

# 变体定义（确定性，勿改已发布的名与序；只能追加）
VARIANTS: list[tuple[str, str]] = [
    ("v00", "identity"),
    ("v01", "flip"),
    ("v02", "bright"),
    ("v03", "dark"),
    ("v04", "gamma"),
    ("v05", "scale075"),
    ("v06", "scale135"),
    ("v07", "jpeg70"),
]


def draw_cartoon_face(
    width: int = 640,
    height: int = 480,
    mouth_open: float = 0.0,
    skin: tuple[int, int, int] = (150, 170, 200),
    shaded: bool = True,
) -> np.ndarray:
    """程序合成卡通正面脸（BGR）。mouth_open∈[0,1] 控制上下唇间距（仅供人看）。"""
    import cv2

    img = np.full((height, width, 3), (40, 44, 52), np.uint8)
    cx, cy = width // 2, height // 2
    fw, fh = int(width * 0.26), int(height * 0.36)
    if shaded:
        for i in range(fh, 0, -2):
            t = i / fh
            c = tuple(int(v * (0.85 + 0.15 * t)) for v in skin)
            cv2.ellipse(img, (cx, cy), (int(fw * t * 1.05), i), 0, 0, 360, c, -1)
    else:
        cv2.ellipse(img, (cx, cy), (fw, fh), 0, 0, 360, skin, -1)
    cv2.ellipse(img, (cx, cy - int(fh * 0.55)), (int(fw * 1.05), int(fh * 0.5)), 0, 180, 360, (45, 35, 30), -1)
    for s in (-1, 1):
        ex = cx + s * int(fw * 0.45)
        cv2.ellipse(img, (ex, cy - int(fh * 0.25)), (int(fw * 0.22), int(fh * 0.045)), s * 8, 0, 180, (60, 45, 35), -1)
    for s in (-1, 1):
        ex, ey = cx + s * int(fw * 0.45), cy - int(fh * 0.12)
        cv2.ellipse(img, (ex, ey), (int(fw * 0.16), int(fh * 0.085)), 0, 0, 360, (245, 245, 245), -1)
        cv2.circle(img, (ex, ey), int(fh * 0.05), (90, 60, 35), -1)
        cv2.circle(img, (ex, ey), int(fh * 0.022), (20, 20, 20), -1)
        cv2.circle(img, (ex - int(fh * 0.015), ey - int(fh * 0.015)), max(1, int(fh * 0.008)), (250, 250, 250), -1)
    cv2.ellipse(img, (cx, cy + int(fh * 0.08)), (int(fw * 0.07), int(fh * 0.14)), 0, 0, 360, tuple(int(v * 0.88) for v in skin), -1)
    cv2.ellipse(img, (cx, cy + int(fh * 0.16)), (int(fw * 0.11), int(fh * 0.03)), 0, 0, 360, tuple(int(v * 0.8) for v in skin), -1)
    my = cy + int(fh * 0.30)
    mw, mh = int(fw * 0.34), int(fh * 0.035)
    gap = int(mouth_open * fh * 0.10)
    cv2.ellipse(img, (cx, my), (mw, mh + gap // 2), 0, 0, 180, (120, 90, 100), -1)
    cv2.ellipse(img, (cx, my - gap), (mw, mh), 0, 180, 360, (120, 90, 100), -1)
    if gap > 2:
        cv2.ellipse(img, (cx, my - gap // 2), (int(mw * 0.8), max(gap // 2, 1)), 0, 0, 360, (60, 40, 45), -1)
        cv2.ellipse(img, (cx, my - gap - mh // 3), (int(mw * 0.45), int(mh * 0.6)), 0, 0, 360, (220, 215, 205), -1)
    return img


def draw_no_face(width: int = 640, height: int = 480, seed: int = 0) -> np.ndarray:
    """无脸场景（渐变背景 + 几何体），用于拒识路径。"""
    import cv2

    rng = np.random.default_rng(seed)
    top = rng.integers(30, 90, size=3)
    bottom = rng.integers(120, 220, size=3)
    grad = np.linspace(top, bottom, height, axis=0).astype(np.uint8)
    img = np.repeat(grad[:, None, :], width, axis=1)
    for _ in range(6):
        c = tuple(int(v) for v in rng.integers(40, 230, size=3))
        p = tuple(int(v) for v in rng.integers(0, [height, width]))
        ax, ay = int(rng.integers(20, 120)), int(rng.integers(20, 120))
        if rng.integers(0, 2):
            cv2.rectangle(img, p, (p[1] + ax, p[0] + ay), c, -1)
        else:
            cv2.circle(img, (p[1], p[0]), ax, c, -1)
    return img


def apply_variant(img: np.ndarray, kind: str) -> np.ndarray:
    """对种子图施加确定性变体（kind 取 VARIANTS 的第二列）。"""
    import cv2

    if kind == "identity":
        return img
    if kind == "flip":
        return cv2.flip(img, 1)
    if kind == "bright":
        return cv2.convertScaleAbs(img, alpha=1.25, beta=12.0)
    if kind == "dark":
        return cv2.convertScaleAbs(img, alpha=0.65, beta=-6.0)
    if kind == "gamma":
        lut = np.array(
            [min(255, int(round(((i / 255.0) ** 0.7) * 255))) for i in range(256)],
            dtype=np.uint8,
        )
        return cv2.LUT(img, lut)
    if kind == "scale075":
        h, w = img.shape[:2]
        small = cv2.resize(img, (int(w * 0.75), int(h * 0.75)), interpolation=cv2.INTER_AREA)
        canvas = np.zeros_like(img)
        y = (h - small.shape[0]) // 2
        x = (w - small.shape[1]) // 2
        canvas[y : y + small.shape[0], x : x + small.shape[1]] = small
        return canvas
    if kind == "scale135":
        h, w = img.shape[:2]
        big = cv2.resize(img, (int(w * 1.35), int(h * 1.35)), interpolation=cv2.INTER_CUBIC)
        bh, bw = big.shape[:2]
        y = (bh - h) // 2
        x = (bw - w) // 2
        return big[y : y + h, x : x + w]
    if kind == "jpeg70":
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not ok:
            return img
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    raise ValueError(f"未知变体：{kind}")
