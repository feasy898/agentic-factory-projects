#!/usr/bin/env python3
"""BeanEye 开源组合四件套冒烟（M0 / W0b）。

依次验证四件开源件在 Windows 原生 CPU 环境下真实可用：
  1) aruco  —— OpenCV ArUco（DICT_4X4_50）合成盘面渲染 4 角码 + 检测 + 单应矩阵反算
  2) rfdetr —— 检测器（seg-nano COCO 权重，首次自动下载/已预缓存）对样图推理出框/掩码
  3) sam2   —— 分割器（HF transformers 路线，权重经 HF 镜像）对合成豆粒点提示出掩码
  4) qrcode —— segno 生成二维码 + zxing-cpp 解码回读

每件输出 {item, ok, seconds, error} 到 out/oss_smoke_report.json，
并打印逐件结果与 `[OSS-SMOKE] n/4 PASS` 汇总。

退出码：aruco 与 qrcode 为硬性项，任一失败退出 1；其余单项失败允许（记录原因）。
权重/模型缓存位置（均被 .gitignore 排除）：
  models/rf-detr-seg-nano.pt        （RF_HOME=<repo>/models）
  models/hf/hub/models--*           （HF_HOME=<repo>/models/hf，HF_ENDPOINT 默认 hf-mirror）
样图：data/samples/coco_sample_dogs.jpg（缺失时自动从下方 URL 列表下载）。

注意：本脚本为内部环境验证件，公开版发布物不含此脚本（见 plan §10）。
用法：
    ./.venv/Scripts/python.exe scripts/oss_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

# Windows 重定向时 stdout 默认 GBK，统一 UTF-8（与 doctor.py 同法）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "out"
SMOKE_DIR = OUT_DIR / "oss_smoke"
SAMPLES_DIR = ROOT / "data" / "samples"

# ---- 缓存与镜像环境变量：必须在导入任何相关库之前设置 ----
os.environ.setdefault("RF_HOME", str(ROOT / "models"))  # 检测器权重缓存目录（== <repo>/models）
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))  # HF 模型缓存
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")  # HF 直连不稳，默认走镜像
# 镜像站不支持 HF Xet 存储协议，禁用之（否则大权重下载挂起，2026-09-28 实测）
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# 合成 COCO 类样图下载源（按序尝试；样图仅用于冒烟推理）
SAMPLE_IMAGE_URLS = [
    # COCO 验证集照片（第三方代码仓内置副本，repo 为 Apache-2.0）
    "https://raw.githubusercontent.com/tensorflow/models/master/research/object_detection/test_images/image1.jpg",
    "https://images.cocodataset.org/val2017/000000039769.jpg",
]

HARD_ITEMS = ("aruco", "qrcode")  # 硬性项：任一失败则脚本退出 1


def _fmt_err(exc: BaseException) -> str:
    msg = f"{exc.__class__.__name__}: {exc}"
    return msg[:500]


def _imwrite_unicode(path: Path, img: "object") -> None:
    """cv2.imwrite 在非 ASCII 路径（本仓含中文目录）下会静默失败，改走编码字节流。"""
    import cv2
    import numpy as np

    ext = path.suffix or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise RuntimeError(f"图像编码失败: {path}")
    path.write_bytes(bytes(np.asarray(buf).tobytes()))


def _ensure_sample_image() -> Path:
    """确保 COCO 类样图存在；缺失则按 URL 列表顺序下载到 data/samples/。"""
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    dst = SAMPLES_DIR / "coco_sample_dogs.jpg"
    if dst.is_file() and dst.stat().st_size > 10_000:
        return dst
    import requests

    last_err: Exception | None = None
    for url in SAMPLE_IMAGE_URLS:
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            if len(resp.content) < 10_000:
                raise ValueError(f"样图过小: {len(resp.content)}B")
            dst.write_bytes(resp.content)
            return dst
        except Exception as exc:  # noqa: BLE001 — 逐源尝试，记录最后一个错误
            last_err = exc
    raise RuntimeError(f"样图下载失败（{SAMPLE_IMAGE_URLS}）: {last_err}")


# ---------------------------------------------------------------- item 1: ArUco
def smoke_aruco() -> str:
    """渲染 4 角 ArUco(4x4_50) 合成盘面 → 检测 → 单应矩阵 → 反投影校验。"""
    import cv2
    import numpy as np

    px_per_mm = 2.0          # 合成"照片"比例
    board_mm = 300.0         # 盘面边长
    marker_mm = 60.0         # 码边长（与 configs/tray.yaml 默认一致）
    margin_px = 100          # 盘面外留白（模拟拍摄视野）
    size_px = int(board_mm * px_per_mm) + 2 * margin_px

    board = np.full((size_px, size_px, 3), 235, dtype=np.uint8)  # 浅灰背景
    # 轻微噪声，模拟成像
    noise = np.random.default_rng(42).normal(0, 4, board.shape).astype(np.int16)
    board = np.clip(board.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    # 期望的 4 角码中心（盘面 mm 坐标系原点在盘面左上角）
    centers_mm = {
        0: (marker_mm / 2, marker_mm / 2),
        1: (board_mm - marker_mm / 2, marker_mm / 2),
        2: (board_mm - marker_mm / 2, board_mm - marker_mm / 2),
        3: (marker_mm / 2, board_mm - marker_mm / 2),
    }
    side_px = int(marker_mm * px_per_mm)
    half_px = side_px // 2
    for mid, (cx_mm, cy_mm) in centers_mm.items():
        marker = cv2.aruco.generateImageMarker(dictionary, mid, side_px)
        marker_bgr = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        cx = int(cx_mm * px_per_mm) + margin_px
        cy = int(cy_mm * px_per_mm) + margin_px
        # 码外留 1/4 边长白边作静区，避免码与背景/相邻元素粘连
        pad = max(4, side_px // 4)
        roi = board[cy - half_px - pad : cy + half_px + pad, cx - half_px - pad : cx + half_px + pad]
        white = np.full_like(roi, 255)
        white[pad : pad + side_px, pad : pad + side_px] = marker_bgr
        board[cy - half_px - pad : cy + half_px + pad, cx - half_px - pad : cx + half_px + pad] = white

    gray = cv2.cvtColor(board, cv2.COLOR_BGR2GRAY)
    detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None or len(ids) != 4:
        raise AssertionError(f"应检测到 4 个码，实际 {0 if ids is None else len(ids)}: ids={ids}")
    found = sorted(int(i[0]) for i in ids)
    if found != [0, 1, 2, 3]:
        raise AssertionError(f"码 id 应为 [0,1,2,3]，实际 {found}")

    # 4 角码中心 px → 盘面 mm 的单应矩阵
    obj_pts_mm, img_pts_px = [], []
    for corner, mid in zip(corners, ids):
        mid = int(mid[0])
        c_px = corner[0].mean(axis=0)  # 4 角点均值 = 码中心
        obj_pts_mm.append(centers_mm[mid])
        img_pts_px.append(c_px)
    H, _ = cv2.findHomography(np.float32(img_pts_px), np.float32(obj_pts_mm))
    if H is None:
        raise AssertionError("findHomography 求解失败")

    # 校验 1：检测中心反投影到 mm 后与真值距离
    proj = cv2.perspectiveTransform(np.float32([img_pts_px]), H)[0]
    err_mm = float(np.linalg.norm(proj - np.float32(obj_pts_mm), axis=1).max())

    # 校验 2：px_per_mm 相对误差（用对角线法：两对角中心距 px / 同距 mm）
    # H 的尺度 = sqrt(|A|)（无投影项修正的近似），直接用相邻中心距更稳：
    d_px = float(np.linalg.norm(np.float32(img_pts_px[0]) - np.float32(img_pts_px[2])))
    d_mm = float(np.linalg.norm(np.float32(obj_pts_mm[0]) - np.float32(obj_pts_mm[2])))
    ppm_est = d_px / d_mm
    ppm_err = abs(ppm_est - px_per_mm) / px_per_mm

    # 校验 3：盘面中心点 (150,150)mm 经 H^-1 落回图像，再正投影应闭合（<0.5mm）
    H_inv = np.linalg.inv(H)
    center_px = cv2.perspectiveTransform(np.float32([[[150, 150]]]), H_inv)[0][0]
    back_mm = cv2.perspectiveTransform(center_px.reshape(1, 1, 2).astype(np.float32), H)[0][0]
    center_err_mm = float(np.linalg.norm(back_mm - np.float32([150.0, 150.0])))

    if err_mm > 0.5 or ppm_err > 0.01 or center_err_mm > 0.5:
        raise AssertionError(
            f"标定精度不足: 中心反投影 {err_mm:.3f}mm, px_per_mm 误差 {ppm_err * 100:.2f}%, 中心闭合 {center_err_mm:.3f}mm"
        )

    # 证据图：标注检测框与 id
    annotated = board.copy()
    cv2.aruco.drawDetectedMarkers(annotated, corners, ids)
    _imwrite_unicode(SMOKE_DIR / "aruco_detected.png", annotated)
    return (
        f"ids={found}, reproj_max={err_mm:.3f}mm, px_per_mm={ppm_est:.3f}(err {ppm_err * 100:.2f}%), "
        f"center_close={center_err_mm:.3f}mm"
    )


# ---------------------------------------------------------------- item 2: 检测器
def smoke_rfdetr() -> str:
    """seg-nano COCO 权重加载 + 样图推理；断言 ≥1 框；掩码存在则一并记录。"""
    import numpy as np
    from PIL import Image

    img_path = _ensure_sample_image()
    image = Image.open(img_path).convert("RGB")

    import rfdetr  # 延迟导入：RF_HOME 已在模块顶部设置

    model = rfdetr.RFDETRSegNano(device="cpu")
    detections = model.predict(np.array(image), threshold=0.5)

    n_boxes = int(len(detections.xyxy))
    if n_boxes < 1:
        raise AssertionError("检测框数 < 1")
    masks = None
    if getattr(detections, "mask", None) is not None:
        masks = int(detections.mask.shape[0])
    elif isinstance(detections.data, dict) and detections.data.get("masks") is not None:
        masks = int(np.asarray(detections.data["masks"]).shape[0])
    class_ids = sorted({int(c) for c in detections.class_id.tolist()})
    confs = [float(c) for c in detections.confidence.tolist()]

    # 证据图：画框
    import cv2

    annotated = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    for (x0, y0, x1, y1), conf, cid in zip(
        detections.xyxy.tolist(), confs, detections.class_id.tolist()
    ):
        p0, p1 = (int(x0), int(y0)), (int(x1), int(y1))
        cv2.rectangle(annotated, p0, p1, (0, 200, 0), 2)
        cv2.putText(
            annotated, f"cls{cid} {conf:.2f}", (p0[0], max(0, p0[1] - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1, cv2.LINE_AA,
        )
    _imwrite_unicode(SMOKE_DIR / "rfdetr_boxes.jpg", annotated)
    del model
    return f"boxes={n_boxes}, masks={masks}, class_ids={class_ids}, max_conf={max(confs):.2f}"


# ---------------------------------------------------------------- item 3: 分割器
def _make_synthetic_bean(seed: int = 7) -> tuple["Image.Image", "np.ndarray"]:
    """合成一粒"豆"：浅背景 + 深棕椭圆（带轻微形变与噪点），返回 (RGB 图, 真值掩码)。"""
    import numpy as np
    from PIL import Image, ImageDraw

    rng = np.random.default_rng(seed)
    w, h = 480, 360
    arr = np.full((h, w, 3), 228, dtype=np.float32)
    arr += rng.normal(0, 3, arr.shape)  # 背景噪点

    # 豆粒：倾斜椭圆（中心、长短轴随机抖动）
    cx, cy = w // 2 + int(rng.integers(-30, 30)), h // 2 + int(rng.integers(-20, 20))
    a, b = 120, 78
    angle = float(rng.integers(0, 180))
    # 逐像素椭圆内判定（含中缝阴影更逼真，略）
    yy, xx = np.mgrid[0:h, 0:w]
    t = np.deg2rad(angle)
    xr = (xx - cx) * np.cos(t) + (yy - cy) * np.sin(t)
    yr = -(xx - cx) * np.sin(t) + (yy - cy) * np.cos(t)
    inside = (xr / a) ** 2 + (yr / b) ** 2 <= 1.0
    bean_rgb = np.array([96, 62, 38], dtype=np.float32)
    arr[inside] = bean_rgb + rng.normal(0, 8, (int(inside.sum()), 3))
    gt_mask = inside

    image = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGB")
    draw = ImageDraw.Draw(image)
    draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 40, 40))  # 中心标记点（提示位置）
    return image, gt_mask


def _sam2_try(model_id: str) -> str:
    """对指定 HF 仓做一次点提示分割；成功返回描述。异常上抛由调用方捕获。"""
    import numpy as np
    import torch
    from PIL import Image
    from transformers import Sam2Model, Sam2Processor

    image, gt_mask = _make_synthetic_bean()
    h, w = gt_mask.shape
    processor = Sam2Processor.from_pretrained(model_id)
    # 显式图像分割类；AutoModel 会按 config.architectures 解析成视频模型（需 inference_session）
    model = Sam2Model.from_pretrained(model_id)
    model.eval()

    # transformers 5.x 处理器要求 4 层嵌套: [image][object][point][xy]
    inputs = processor(images=image, input_points=[[[[w // 2, h // 2]]]], return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)

    masks_list = processor.post_process_masks(outputs.pred_masks, inputs["original_sizes"])
    # 稳健取最优掩码：展平 (object, n_masks) 两维后按 IoU 分数取 argmax
    masks_obj = masks_list[0].reshape(-1, *masks_list[0].shape[-2:])  # (O*N, H, W)
    scores = outputs.iou_scores.reshape(outputs.iou_scores.shape[0], -1)[0]  # 首图所有分数
    best = int(scores.argmax()) if scores.numel() == masks_obj.shape[0] else 0
    mask = masks_obj[best].numpy().astype(bool)

    frac = float(mask.mean())
    if not (0.005 < frac < 0.60):
        raise AssertionError(f"掩码覆盖率异常: {frac:.3%}")
    inter = float((mask & gt_mask).sum())
    union = float((mask | gt_mask).sum())
    iou_gt = inter / union if union else 0.0
    if iou_gt < 0.5:
        raise AssertionError(f"掩码与合成豆真值 IoU 过低: {iou_gt:.3f}（分割未生效）")

    # 叠加图
    overlay = np.array(image).copy()
    overlay[mask] = (0.45 * overlay[mask] + 0.55 * np.array([30, 180, 60])).astype(np.uint8)
    Image.fromarray(overlay).save(SMOKE_DIR / "sam2_overlay.png")
    del model
    return f"model={model_id}, mask_frac={frac:.2%}, IoU_vs_gt={iou_gt:.3f}, n_candidates={masks_obj.shape[0]}"


def smoke_sam2() -> str:
    """分割器点提示分割合成豆粒；按仓逐个尝试（首个成功者生效）。"""
    candidates = [
        "facebook/sam2-hiera-small",   # 开发指令锚定仓（transformers 格式权重）
        "danelcsb/sam2.1_hiera_tiny",  # transformers 文档示例仓（图像 SAM2.1）
    ]
    errors = []
    for mid in candidates:
        try:
            return _sam2_try(mid)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{mid}: {_fmt_err(exc)}")
    raise RuntimeError("全部候选分割仓失败 | " + " | ".join(errors))


# ---------------------------------------------------------------- item 4: 二维码
def smoke_qrcode() -> str:
    """segno 生成二维码 → zxing-cpp 解码 → payload 一致。"""
    import segno
    import zxingcpp
    from PIL import Image

    payload = f"https://verify.beaneye.example/r/SMOKE-{uuid.uuid4().hex[:12]}|sha256:{uuid.uuid4().hex}"
    qr_path = SMOKE_DIR / "qr.png"
    segno.make(payload, error="m").save(str(qr_path), scale=8, border=4)

    decoded = zxingcpp.read_barcodes(Image.open(qr_path))
    if not decoded:
        raise AssertionError("解码结果为空")
    text = decoded[0].text
    if text != payload:
        raise AssertionError(f"解码不一致: {text!r} != {payload!r}")
    return f"payload_len={len(payload)}, format={decoded[0].format.name}"


# ---------------------------------------------------------------- 主流程
def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SMOKE_DIR.mkdir(parents=True, exist_ok=True)

    items_spec = [
        ("aruco", smoke_aruco),
        ("rfdetr", smoke_rfdetr),
        ("sam2", smoke_sam2),
        ("qrcode", smoke_qrcode),
    ]
    items: list[dict] = []
    detail: dict[str, str] = {}
    for name, fn in items_spec:
        t0 = time.perf_counter()
        ok, error = True, ""
        try:
            detail[name] = fn()
        except Exception as exc:  # noqa: BLE001 — 单件失败记录后继续
            ok, error = False, _fmt_err(exc)
            detail[name] = "traceback 最后 3 行: " + " | ".join(
                traceback.format_exc().strip().splitlines()[-3:]
            )
        seconds = round(time.perf_counter() - t0, 2)
        items.append({"item": name, "ok": ok, "seconds": seconds, "error": error})
        mark = "PASS" if ok else "FAIL"
        print(f"[OSS-SMOKE] {name:<7} {mark}  ({seconds:6.2f}s)  {detail[name]}")

    n_pass = sum(1 for it in items if it["ok"])
    hard_ok = all(next(it for it in items if it["item"] == h)["ok"] for h in HARD_ITEMS)
    print(f"[OSS-SMOKE] {n_pass}/4 PASS" + ("（硬性项 aruco/qrcode 均 OK）" if hard_ok else "（硬性项未全过）"))

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "hard_items": list(HARD_ITEMS),
        "hard_ok": hard_ok,
        "items": items,  # 每项固定 {item, ok, seconds, error}
        "detail": detail,
    }
    report_path = OUT_DIR / "oss_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OSS-SMOKE] report -> {report_path}")
    return 0 if hard_ok else 1


if __name__ == "__main__":
    sys.exit(main())
