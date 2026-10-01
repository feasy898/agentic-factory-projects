"""M4 经典分割 ClassicSeg（plan/开发指令.md §4 M4）。

Otsu 前景 → 形态学开闭 → 距离变换种子 + ``cv2.watershed`` 切粘连粒 →
每个连通域/种子区域一枚 :class:`~beaneye.schemas.BeanMask`（盘面 mm 坐标：
外轮廓 polygon、bbox、质心、面积）。满足冻结 ``SegModel`` Protocol，
与 OracleSeg / 未来 NN 模型可互换。

**输入约定（与 M13 管线一致）**：``predict(img_rgb, scan)`` 收到的是
**标定 warp 后的托盘正射网格图**（RGB、``configs/tray.yaml`` 的 grid_px
覆盖 tray_mm），故 ``mm/px = tray_mm / 图宽``，mm 几何直接由像素线性换算，
不再依赖单应。

算法要点：

1. **角码抑制**：四角定位码是盘面印刷物（暗色方块），先按托盘配置的
   码中心/码边长把码区像素替换为全图中位数（≈背景）再做 Otsu，
   否则码区质量远大于豆、会把全局阈值拖歪（实测夹具上阈值被拖进豆灰度带内）；
2. **阈值极性自检**：浅色亚克力盘面约定前景=暗；若图像边框带的前景占比
   >50%，判定极性反转（防深色背景误配）；
3. **粘连切分**：对每个连通域算距离变换，局部极大（深度 ≥ peak_min_mm、
   间距 ≥ peak_min_dist_mm）作种子；单种子/无种子域整域输出（豆外轮廓
   凸且椭圆状时距离变换单峰，天然不误切长圆豆；贴边豆的窄条深峰不足，
   整域保留为部分掩码）；多种子域用 watershed 按种子切分。
   已知短板（§9 风险表）：深度重叠（>~60%）粘连粒共用一个深峰，切不开；
   NN 分割模型上线前的既定降级，稠密盘粒数误差另设验收线。

面别语义：冻结协议 ``predict(img_rgb, scan)`` 不携带 side，本实现按配置
``side``（默认 top）输出，M13 装配器（``beaneye.app.components``）对每面
各调一次并规范化 side/mask_id——与 ``NullSegModel`` 同约定。
"""

from __future__ import annotations

import time

import cv2
import numpy as np
from scipy import ndimage

from beaneye.calibration.config import TrayConfig, load_tray_config
from beaneye.schemas import BeanMask, SegResult, TrayScan

from .config import SegmentConfig, load_segment_config

__all__ = ["ClassicSeg"]


class ClassicSeg:
    """经典 CV 分割：Otsu + 形态学 + 距离变换分水岭。"""

    stage = "segment"
    version = "classic:v1"

    def __init__(
        self,
        cfg: SegmentConfig | None = None,
        tray_cfg: TrayConfig | None = None,
    ) -> None:
        self.cfg = cfg if cfg is not None else load_segment_config()
        self.tray = tray_cfg if tray_cfg is not None else load_tray_config()

    # ------------------------------------------------------------------
    # SegModel Protocol
    # ------------------------------------------------------------------

    def predict(self, img_rgb: np.ndarray, scan: TrayScan) -> SegResult:
        """分割一张托盘正射网格图 → :class:`SegResult`（side 取配置面）。"""
        t0 = time.perf_counter()
        masks = self.segment_masks(img_rgb, side=self.cfg.side)
        return SegResult(
            scan_id=scan.scan_id,
            side=self.cfg.side,
            masks=masks,
            runtime_s=time.perf_counter() - t0,
        )

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def segment_masks(self, img_rgb: np.ndarray, side: str | None = None) -> list[BeanMask]:
        """分割并返回 BeanMask 列表（按质心 y,x 排序；mask_id 由调用方语义定）。"""
        cfg, tray = self.cfg, self.tray
        side = side or cfg.side

        img = np.asarray(img_rgb)
        if img.ndim == 3 and img.shape[2] >= 3:
            bgr = cv2.cvtColor(img[:, :, :3], cv2.COLOR_RGB2BGR)
        elif img.ndim == 2:
            bgr = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        else:
            raise ValueError(f"输入图像形状不支持: {img.shape}（期望 HxWx3 或 HxW）")
        if img.dtype != np.uint8:
            bgr = np.clip(bgr, 0, 255).astype(np.uint8)

        h, w = bgr.shape[:2]
        if w <= 0 or h <= 0:
            return []
        mm_per_px = tray.tray_mm / float(w)  # 正射网格：图宽 = tray_mm

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        if cfg.channel == "lab_b":
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab)[:, :, 2]

        # ---- 1) 角码区抑制（换成背景中位数，避免码区质量拖歪全局 Otsu） ----
        if cfg.mask_markers:
            gray = self._suppress_markers(gray, mm_per_px)

        # ---- 2) 平滑 + Otsu（浅色盘面：前景=暗 → THRESH_BINARY_INV） -------
        blur = gray
        if cfg.blur_sigma_px > 0:
            k = 2 * int(4 * cfg.blur_sigma_px + 0.5) + 1
            blur = cv2.GaussianBlur(gray, (k, k), cfg.blur_sigma_px)
        thr_otsu, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # 背景锚定：码区白色静区/反光等**亮于盘面的印刷物**会把 Otsu 阈值抬到
        # 背景灰度之上（首轮 eval 实测：thr>205 → 整片背景被判前景 → 极性
        # 自检反转 → 只剩亮斑、豆全丢）。Otsu 只在「安全低于背景」时可信，
        # 否则退到 背景估计−bg_delta_gray 的保守线（无豆/纯噪场景 → 空前景）。
        bg_ref = self._background_level(gray)
        thr = min(float(thr_otsu), bg_ref - cfg.bg_delta_gray)
        if thr <= 0:
            return []
        fg = (blur < thr).astype(np.uint8)
        if self._frame_foreground_frac(fg) > 0.5:  # 极性自检：边框带大多是背景
            fg = (1 - fg).astype(np.uint8)

        # ---- 3) 形态学开闭 ------------------------------------------------
        if cfg.open_ksize > 1:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.open_ksize, cfg.open_ksize))
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k)
        if cfg.close_ksize > 1:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.close_ksize, cfg.close_ksize))
            fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k)

        # ---- 4) 连通域 → 种子/分水岭 → 逐豆掩码 ---------------------------
        min_area_px2 = cfg.min_area_mm2 / (mm_per_px * mm_per_px)
        # 巨型域护栏：单连通域盖过半张盘必是阈值病理（背景误判/整盘粘连噪声），
        # 不是豆——跳过以防在巨域上跑出分钟级分水岭（首轮 eval 实测 117s）。
        max_area_px2 = cfg.max_component_frac * float(w * h)
        n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
        out: list[tuple[tuple[float, float], BeanMask]] = []
        tmp_seq = 0
        for lab in range(1, n_lab):
            area_px = int(stats[lab, cv2.CC_STAT_AREA])
            if area_px < min_area_px2 or area_px > max_area_px2:
                continue
            ox = int(stats[lab, cv2.CC_STAT_LEFT])
            oy = int(stats[lab, cv2.CC_STAT_TOP])
            cw = int(stats[lab, cv2.CC_STAT_WIDTH])
            ch = int(stats[lab, cv2.CC_STAT_HEIGHT])
            pad = 2
            x0, y0 = max(0, ox - pad), max(0, oy - pad)
            x1, y1 = min(w, ox + cw + pad), min(h, oy + ch + pad)
            comp = (labels[y0:y1, x0:x1] == lab).astype(np.uint8)

            for region, conf in self._split_component(
                comp, blur[y0:y1, x0:x1], min_area_px2, mm_per_px
            ):
                mask = self._to_bean_mask(
                    region, conf, side, mm_per_px, off_px=(x0, y0), tmp_id=tmp_seq
                )
                tmp_seq += 1
                if mask is not None:
                    out.append((mask.centroid_mm, mask))

        out.sort(key=lambda t: (t[0][1], t[0][0]))  # 质心 y,x → mask_id 稳定有序
        masks = [m for _, m in out]
        for i, m in enumerate(masks):  # BeanMask 非冻结：排序后统一编号
            m.mask_id = f"{side}_{i:04d}"
        return masks

    # ------------------------------------------------------------------
    # 内部步骤
    # ------------------------------------------------------------------

    def _suppress_markers(self, gray: np.ndarray, mm_per_px: float) -> np.ndarray:
        """把四角码区（码边长 + 余量）像素替换为全图中位数（≈背景）。"""
        out = gray.copy()
        fill = float(np.median(gray))
        half_mm = self.tray.marker_mm / 2.0 + self.cfg.marker_margin_mm
        inv = 1.0 / mm_per_px
        h, w = out.shape[:2]
        for cx_mm, cy_mm in self.tray.centers_mm.values():
            px0 = max(0, int(round((cx_mm - half_mm) * inv)))
            py0 = max(0, int(round((cy_mm - half_mm) * inv)))
            px1 = min(w, int(round((cx_mm + half_mm) * inv)) + 1)
            py1 = min(h, int(round((cy_mm + half_mm) * inv)) + 1)
            if px1 > px0 and py1 > py0:
                out[py0:py1, px0:px1] = fill
        return out

    @staticmethod
    def _background_level(gray: np.ndarray, frac: float = 0.01) -> float:
        """背景灰度估计 = 图像边框带中位数（豆/码区占比小，中位数稳健）。"""
        h, w = gray.shape[:2]
        t = max(2, int(round(min(h, w) * frac)))
        frame = np.concatenate(
            [gray[:t, :].ravel(), gray[-t:, :].ravel(), gray[:, :t].ravel(), gray[:, -t:].ravel()]
        )
        return float(np.median(frame)) if frame.size else 255.0

    @staticmethod
    def _frame_foreground_frac(fg: np.ndarray, frac: float = 0.005) -> float:
        """图像边框带的前景占比（极性自检用）。"""
        h, w = fg.shape[:2]
        t = max(2, int(round(min(h, w) * frac)))
        frame = np.concatenate(
            [fg[:t, :].ravel(), fg[-t:, :].ravel(), fg[:, :t].ravel(), fg[:, -t:].ravel()]
        )
        return float(frame.mean()) if frame.size else 0.0

    def _split_component(
        self,
        comp: np.ndarray,
        crop_gray: np.ndarray,
        min_area_px2: float,
        mm_per_px: float,
    ) -> list[tuple[np.ndarray, float]]:
        """单连通域 → [(掩码, conf)]：单峰整域输出，多峰分水岭切分。

        ``mm_per_px`` 是**全局**口径（tray_mm / 网格图宽），与 crop 无关
        （正射图上线性一致，crop 裁剪不改变尺度）。
        """
        cfg = self.cfg
        # maskSize=5：精确 L2 DT。maskSize=3 的近似 DT 有量化台阶，会在长圆豆
        # 距离变换脊上制造长等值平台 → 多峰误切（首轮 eval 实测）。
        dt = cv2.distanceTransform(comp, cv2.DIST_L2, 5)
        peak_min_px = cfg.peak_min_mm / mm_per_px
        # 局部极大：3px 窗口（纯平台内全部保留），再以小半径并簇——半径只须
        # 把「同一粒豆的等值峰台」连成一种子；若取到半间距（1.8/2≈0.9mm），
        # 两粒豆的峰会被 DT 脊线单连成一个簇 → 每对粘连豆只出一种子、永不切分
        # （首轮 eval 实测 7/12 对未切）。鞍点簇由支配度过滤删除。
        local_max = ndimage.maximum_filter(dt, size=3)
        peaks = (dt >= peak_min_px) & (dt >= local_max - 1e-6)
        merge_px = max(2, int(round(0.25 * cfg.peak_min_dist_mm / mm_per_px)))
        peak_img = peaks.astype(np.uint8)
        if merge_px > 0:
            peak_img = cv2.dilate(
                peak_img, np.ones((2 * merge_px + 1, 2 * merge_px + 1), np.uint8)
            )
        n_clu, clab = cv2.connectedComponents(peak_img, connectivity=8)
        cand: list[tuple[float, float, float]] = []  # (sy, sx, depth)
        for clu in range(1, n_clu):
            member = clab == clu
            depth = np.where(member, dt, -1.0)
            sy, sx = np.unravel_index(int(np.argmax(depth)), depth.shape)  # 簇内最深点作种子
            d = float(dt[sy, sx])
            if d >= peak_min_px:
                cand.append((float(sy), float(sx), d))
        # ---- 支配度过滤：粘连颈部鞍点也是（浅的）距离变换局部极大，若不删，
        # ---- 一对豆会切出第三块碎片（夹具实测 8.7mm² 碎片）。浅于 dominance×
        # ---- 邻域最深种子的候选不成种子。等深邻豆互不抑制（比值=1）。
        dom_radius_px = cfg.seed_dominance_radius_mm / mm_per_px
        pts = np.array([(c[0], c[1]) for c in cand]) if cand else np.zeros((0, 2))
        depths = np.array([c[2] for c in cand]) if cand else np.zeros((0,))
        seeds: list[tuple[int, int]] = []
        for i, (sy, sx, d) in enumerate(cand):
            if len(cand) > 1:
                dist = np.hypot(pts[:, 0] - sy, pts[:, 1] - sx)
                neigh = depths[(dist > 0) & (dist <= dom_radius_px)]
                if neigh.size and d < cfg.seed_dominance * float(neigh.max()):
                    continue
            seeds.append((int(sy), int(sx)))
        n_seeds = len(seeds)
        if n_seeds <= 1:
            return [(comp, cfg.conf_single)]

        # ---- 分水岭：标签 1=确定背景（域外环带），≥2=种子，0=待分 ------------
        markers = np.zeros(comp.shape, dtype=np.int32)
        ring = cv2.dilate(comp, np.ones((3, 3), np.uint8)) - comp
        markers[ring > 0] = 1
        for k, (sy, sx) in enumerate(seeds, start=2):
            markers[sy, sx] = k
        ws_in = cv2.cvtColor(crop_gray, cv2.COLOR_GRAY2BGR)
        cv2.watershed(ws_in, markers)

        regions: list[tuple[np.ndarray, float]] = []
        for seed in range(2, n_seeds + 2):
            region = ((markers == seed) & (comp > 0)).astype(np.uint8)
            if int(region.sum()) >= min_area_px2:
                regions.append((region, cfg.conf_split))
        if len(regions) <= 1:  # 切分退化：整域保留，不产出碎片
            return [(comp, cfg.conf_single)]
        return regions

    def _to_bean_mask(
        self,
        region: np.ndarray,
        conf: float,
        side: str,
        mm_per_px: float,
        *,
        off_px: tuple[int, int],
        tmp_id: int,
    ) -> BeanMask | None:
        """区域像素掩码（crop 内）→ 盘面 mm BeanMask。"""
        ox, oy = off_px
        contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        contour = max(contours, key=cv2.contourArea)
        if len(contour) < 3:
            return None
        pts = contour.reshape(-1, 2).astype(np.float64)
        pts[:, 0] += ox
        pts[:, 1] += oy
        polygon = [[float(x * mm_per_px), float(y * mm_per_px)] for x, y in pts]

        m = cv2.moments(region, binaryImage=True)
        if m["m00"] <= 0:
            return None
        cx_px = m["m10"] / m["m00"] + ox
        cy_px = m["m01"] / m["m00"] + oy
        bx, by, bw, bh = cv2.boundingRect(region)
        x0_mm = (ox + bx) * mm_per_px
        y0_mm = (oy + by) * mm_per_px
        x1_mm = (ox + bx + bw) * mm_per_px
        y1_mm = (oy + by + bh) * mm_per_px
        area_mm2 = float(region.sum()) * mm_per_px * mm_per_px
        if area_mm2 <= 0:
            return None
        return BeanMask(
            mask_id=f"_tmp_{tmp_id:05d}",  # 占位；segment_masks 出口按序重键
            side=side,  # type: ignore[arg-type]
            polygon=polygon,
            bbox_mm=(x0_mm, y0_mm, x1_mm, y1_mm),
            area_mm2=area_mm2,
            centroid_mm=(float(cx_px * mm_per_px), float(cy_px * mm_per_px)),
            source="classic",
            conf=float(min(max(conf, 0.0), 1.0)),
        )
