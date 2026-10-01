"""M4 真值分割 OracleSeg（W4a · plan/开发指令.md §4 M4）。

读铺盘合成器（:mod:`beaneye.synth.compose`）labels manifest 的逐粒真值掩码，
直接透传为契约 :class:`~beaneye.schemas.BeanMask`（``source="oracle"``、
``conf=1.0``）——合成盘上的**黄金分割器**：

- **端到端链路评估**：e2e oracle 路线（M14）的分割段由真值直出，链路
  自洽性检验（oracle 管线缺陷计数与真值完全一致）以此为分割基准；
- **classic 的上限对照**：同一合成盘上 OracleSeg = 真值上界，ClassicSeg
  与它的逐豆 IoU 差距即经典 CV 相对真值的差距（tests/test_oracle.py 将
  对照报告落盘 ``out/eval/oracle_vs_classic_report.json``）。

真值表示（三口径等价，tests/test_synth.py 真值一致性用例已证「RLE 解码 ==
标注多边形自栅格化逐字节」）：manifest 逐粒 ``poly_mm_top/poly_mm_bottom``
多边形（本实现**直接透传**，不引入栅格化损失）、托盘 mm 网格 COCO RLE
（``rle_top/rle_bottom``，:func:`beaneye.synth.compose.rle_decode` 解码即
真值栅格）、解析几何（``bbox_mm/centroid_mm/area_mm2``）。M4 spec 括注的
「RLE→polygon」即本透传路径——仓库 labels 的多边形与 RLE 由同一取整多边
形产出，直读多边形保真且免栅格阶梯顶点膨胀；栅格口径由 :meth:`truth_rasters`
按需提供。

面别约定（协议适配）：冻结 ``SegModel.predict(img_rgb, scan)`` 不携带
side，而 M12 成对语义下 top/bottom 真值**不同**（bottom 重采样同 mm 同类
另一变体 + ``mirror_bottom`` 镜像朝向），同一实例不可两面共用。约定与
ClassicSeg/NullSegModel 同款：实例按 ``side``（默认 top）出结果，需要另一
面时改 ``side`` 属性或直接调 :meth:`masks_for`；e2e/装配侧按面各备一个实
例（M13 ``normalize_seg_result`` 对已带正确 side 的结果原样放行）。

``predict(img_rgb, scan)`` 的 ``img_rgb`` 不参与计算（真值掩码来自 manifest，
与像素无关）；``scan`` 只读 ``scan_id`` 做真值索引，未索引即抛
:class:`OracleSegError`（附已索引 scan_id 清单）——黄金分割器宁缺毋错，
绝不对非合成盘伪装输出。

真值注册支持三种来源：labels JSON dict（``labels_to_json`` 产物/读盘回传）、
labels JSON 文件路径、内存 :class:`~beaneye.synth.compose.SynthTray`；
:meth:`from_batch_dir` 按 ``labels_*.json`` 扫整个合成 batch 目录建索引。
mask_id 沿用 ``{side}_{i:04d}``（i = manifest 豆序），与
``scripts/smoke_synth_chain.py`` 的 ``truth_by_mask`` 回查约定一致：
``entry(scan_id, mask_id)`` 可 O(1) 回到该粒真值标注（bean_id/类别）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from beaneye.acquisition.base import read_json
from beaneye.schemas import BeanMask, SegResult, TrayScan
from beaneye.synth.compose import (
    SynthTray,
    labels_to_json,
    rasterize_poly_mm,
    rle_decode,
)

__all__ = ["OracleSeg", "OracleSegError", "SUPPORTED_LABELS_VERSION"]

SUPPORTED_LABELS_VERSION = 1
_SIDES = ("top", "bottom")


class OracleSegError(ValueError):
    """Oracle 分割失败（真值缺失 / labels 非法 / scan_id 未索引 / 面别非法）。"""


# ---------------------------------------------------------------------------
# labels 校验与几何解析（与 beaneye.synth.compose 同公式，bottom 面真值重算用）
# ---------------------------------------------------------------------------


def _check_poly(poly: object, where: str) -> None:
    if not isinstance(poly, list) or len(poly) < 3:
        raise OracleSegError(f"{where}: 必须是 ≥3 点的多边形，得到 {type(poly).__name__}")
    for k, p in enumerate(poly):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise OracleSegError(f"{where}[{k}]: 必须是 [x, y] 两个坐标，得到 {p!r}")
        for c in p:
            if isinstance(c, bool) or not isinstance(c, (int, float)):
                raise OracleSegError(f"{where}[{k}]: 坐标必须是数值，得到 {c!r}")


def _validate_labels(labels: object) -> dict:
    """labels manifest 最小校验（结构层面；几何在构造 BeanMask 时即被契约校验）。"""
    if not isinstance(labels, dict):
        raise OracleSegError(f"labels 必须是 dict，得到 {type(labels).__name__}")
    version = labels.get("labels_version", SUPPORTED_LABELS_VERSION)
    if version != SUPPORTED_LABELS_VERSION:
        raise OracleSegError(
            f"labels_version {version!r} 不受支持（本实现支持 {SUPPORTED_LABELS_VERSION}，"
            "见 beaneye.synth.compose 的 labels schema）"
        )
    scan_id = labels.get("scan_id")
    if not isinstance(scan_id, str) or not scan_id:
        raise OracleSegError(f"labels.scan_id 必须是非空字符串，得到 {scan_id!r}")
    beans = labels.get("beans")
    if not isinstance(beans, list):
        raise OracleSegError(f"labels.beans 必须是列表，得到 {type(beans).__name__}")
    for i, entry in enumerate(beans):
        if not isinstance(entry, dict):
            raise OracleSegError(f"beans[{i}] 必须是 dict，得到 {type(entry).__name__}")
        if not isinstance(entry.get("bean_id"), str) or not entry["bean_id"]:
            raise OracleSegError(f"beans[{i}].bean_id 必须是非空字符串，得到 {entry.get('bean_id')!r}")
        for key in ("poly_mm_top", "poly_mm_bottom"):
            _check_poly(entry.get(key), f"beans[{i}].{key}")
    tray = labels.get("tray")
    if tray is not None and not isinstance(tray, dict):
        raise OracleSegError(f"labels.tray 必须是 dict（栅格真值需要 tray_mm/rle_grid_px）")
    return labels


def _shoelace_area_mm2(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return float(abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2.0)


def _bbox_mm(poly: np.ndarray) -> tuple[float, float, float, float]:
    x0, y0 = poly.min(axis=0)
    x1, y1 = poly.max(axis=0)
    return (float(x0), float(y0), float(x1), float(y1))


def _centroid_mm(poly: np.ndarray) -> tuple[float, float]:
    m = cv2.moments(np.round(poly, 3).astype(np.float32))
    if m["m00"] > 0:
        return (float(m["m10"] / m["m00"]), float(m["m01"] / m["m00"]))
    return (float(poly[:, 0].mean()), float(poly[:, 1].mean()))


# ---------------------------------------------------------------------------
# OracleSeg
# ---------------------------------------------------------------------------


class OracleSeg:
    """真值分割：合成 manifest 逐粒真值 → BeanMask 透传（source=oracle, conf=1.0）。

    满足冻结 ``SegModel`` Protocol，与 ClassicSeg / 未来 NN 模型可互换。
    """

    stage = "segment"
    version = "oracle:v1"

    def __init__(
        self,
        labels_by_scan: Mapping[str, Any] | None = None,
        *,
        side: str = "top",
    ) -> None:
        if side not in _SIDES:
            raise OracleSegError(f"side 只能是 {'/'.join(_SIDES)}，得到 {side!r}")
        self.side = side
        self._labels: dict[str, dict] = {}
        for scan_id, source in (labels_by_scan or {}).items():
            self.register(source, scan_id=scan_id)

    # ------------------------------------------------------------------
    # 真值注册
    # ------------------------------------------------------------------

    def register(self, source: Any, *, scan_id: str | None = None) -> str:
        """注册一份真值来源（labels dict / JSON 文件路径 / SynthTray）。

        返回实际索引的 scan_id；同 scan_id 重复注册视为配置事故（真值歧义），
        直接抛 :class:`OracleSegError`。
        """
        labels = self._load_labels(source)
        sid = str(scan_id) if scan_id is not None else str(labels["scan_id"])
        if not sid:
            raise OracleSegError("scan_id 不能为空")
        if sid in self._labels:
            raise OracleSegError(f"scan_id {sid!r} 重复注册（真值歧义，禁止覆盖）")
        self._labels[sid] = labels
        return sid

    @staticmethod
    def _load_labels(source: Any) -> dict:
        if isinstance(source, SynthTray):
            labels = labels_to_json(source, with_rle=True)
        elif isinstance(source, (str, Path)):
            try:
                labels = read_json(Path(source))
            except Exception as exc:  # AcquisitionError（缺文件/坏 JSON）→ 本包错误口径
                raise OracleSegError(f"labels JSON 读取失败: {source}（{exc}）") from exc
        elif isinstance(source, dict):
            labels = source
        else:
            raise OracleSegError(
                f"不支持的真值来源类型 {type(source).__name__}（支持 labels dict / JSON 路径 / SynthTray）"
            )
        return _validate_labels(labels)

    @classmethod
    def from_batch_dir(
        cls, directory: str | Path, *, side: str = "top", pattern: str = "labels_*.json"
    ) -> "OracleSeg":
        """扫描合成 batch 目录（``write_batch`` 产物）按 labels 文件建真值索引。"""
        d = Path(directory)
        if not d.is_dir():
            raise OracleSegError(f"合成 batch 目录不存在: {d}")
        files = sorted(d.glob(pattern))
        if not files:
            raise OracleSegError(f"{d} 下没有匹配 {pattern!r} 的 labels 文件")
        seg = cls(side=side)
        for f in files:
            seg.register(f)
        return seg

    @classmethod
    def from_tray(cls, tray: SynthTray, *, side: str = "top", with_rle: bool = True) -> "OracleSeg":
        """直接从内存合成盘建真值索引（demo/e2e 免落盘路径）。"""
        seg = cls(side=side)
        seg.register(labels_to_json(tray, with_rle=with_rle))
        return seg

    # ------------------------------------------------------------------
    # SegModel Protocol
    # ------------------------------------------------------------------

    def predict(self, img_rgb: Any, scan: TrayScan) -> SegResult:
        """分割 = 真值透传（``img_rgb`` 不参与；side 取实例 ``self.side``）。"""
        t0 = time.perf_counter()
        masks = self.masks_for(scan.scan_id, side=self.side)
        return SegResult(
            scan_id=scan.scan_id,
            side=self.side,  # type: ignore[arg-type]
            masks=masks,
            runtime_s=time.perf_counter() - t0,
        )

    # ------------------------------------------------------------------
    # 真值访问
    # ------------------------------------------------------------------

    def scan_ids(self) -> list[str]:
        """已索引的 scan_id（排序稳定）。"""
        return sorted(self._labels)

    def _require(self, scan_id: str) -> dict:
        labels = self._labels.get(scan_id)
        if labels is None:
            raise OracleSegError(
                f"OracleSeg 未索引 scan_id={scan_id!r}；已索引: {self.scan_ids() or '（空）'}"
            )
        return labels

    def labels_for(self, scan_id: str) -> dict:
        """该盘完整 labels manifest（只读约定，勿改动内部引用）。"""
        return self._require(scan_id)

    def bean_ids(self, scan_id: str) -> list[str]:
        """manifest 豆序的 bean_id 列表（与两面 mask 下标一一对应）。"""
        return [str(e["bean_id"]) for e in self._require(scan_id)["beans"]]

    def entry(self, scan_id: str, mask_id: str) -> dict:
        """mask_id（``{side}_{i:04d}``）→ 该粒真值标注 dict（bean_id/类别/多边形）。"""
        self._require(scan_id)
        side, sep, idx = mask_id.rpartition("_")
        if side not in _SIDES or not sep or not idx.isdigit():
            raise OracleSegError(f"mask_id {mask_id!r} 不符合 {{side}}_{{i:04d}} 约定")
        beans = self._labels[scan_id]["beans"]
        i = int(idx)
        if not 0 <= i < len(beans):
            raise OracleSegError(f"mask_id {mask_id!r} 下标越界（该盘 {len(beans)} 粒）")
        return beans[i]

    def masks_for(self, scan_id: str, side: str | None = None) -> list[BeanMask]:
        """逐粒真值 BeanMask（manifest 豆序；mask_id=``{side}_{i:04d}``）。

        top 面几何字段（bbox/质心/面积）自 manifest 透传；manifest 的几何
        字段按 M12 约定为 top 口径，bottom 面由真值多边形解析重算（与
        compose 同公式，3 位小数取整）。
        """
        s = side or self.side
        if s not in _SIDES:  # 先校验调用方参数，再查真值索引（fail-fast 语义清晰）
            raise OracleSegError(f"side 只能是 {'/'.join(_SIDES)}，得到 {s!r}")
        labels = self._require(scan_id)
        out: list[BeanMask] = []
        for i, e in enumerate(labels["beans"]):
            poly = [[float(x), float(y)] for x, y in e[f"poly_mm_{s}"]]
            if s == "top":
                bbox = tuple(float(v) for v in e["bbox_mm"])
                area = float(e["area_mm2"])
                centroid = tuple(float(v) for v in e["centroid_mm"])
            else:
                arr = np.asarray(poly, dtype=np.float64)
                bbox = tuple(round(float(v), 3) for v in _bbox_mm(arr))
                area = round(_shoelace_area_mm2(arr), 3)
                centroid = tuple(round(float(v), 3) for v in _centroid_mm(arr))
            out.append(
                BeanMask(
                    mask_id=f"{s}_{i:04d}",
                    side=s,  # type: ignore[arg-type]
                    polygon=poly,
                    bbox_mm=(bbox[0], bbox[1], bbox[2], bbox[3]),
                    area_mm2=area,
                    centroid_mm=(centroid[0], centroid[1]),
                    source="oracle",
                    conf=1.0,
                )
            )
        return out

    def truth_rasters(
        self, scan_id: str, side: str, *, grid_px: int | None = None
    ) -> list[np.ndarray]:
        """逐豆真值栅格（托盘 mm 网格 uint8 {0,255}，豆序与 masks_for 对齐）。

        优先解码 manifest 逐粒 RLE（合成器同一栅格化）；RLE 不在位时按标注
        多边形 :func:`beaneye.synth.compose.rasterize_poly_mm` 自栅格化——
        两表示逐字节等价（tests/test_synth.py 真值一致性用例）。IoU 对照、
        e2e 真值核对等栅格口径比较用本入口，勿自绘真值。
        """
        labels = self._require(scan_id)
        if side not in _SIDES:
            raise OracleSegError(f"side 只能是 {'/'.join(_SIDES)}，得到 {side!r}")
        tray = labels.get("tray") or {}
        tray_mm = float(tray.get("tray_mm", 0.0) or 0.0)
        g = int(grid_px if grid_px is not None else tray.get("rle_grid_px", 0) or 0)
        if tray_mm <= 0.0 or g <= 0:
            raise OracleSegError(
                f"labels[{scan_id!r}].tray 缺 tray_mm/rle_grid_px，无法给出栅格真值"
                "（with_rle 落盘或带 tray 节的 labels 才支持）"
            )
        buf = np.zeros((g, g), dtype=np.uint8)
        rle_key = f"rle_{side}"
        poly_key = f"poly_mm_{side}"
        out: list[np.ndarray] = []
        for e in labels["beans"]:
            rle = e.get(rle_key)
            if rle is not None:
                m = rle_decode(rle)
                if m.shape != (g, g):
                    raise OracleSegError(
                        f"{e['bean_id']}.{rle_key}: RLE 尺寸 {m.shape} != 网格 {(g, g)}"
                    )
                out.append(m)
            else:
                poly = np.asarray(e[poly_key], dtype=np.float64)
                out.append(rasterize_poly_mm(poly, grid_px=g, tray_mm=tray_mm, out=buf).copy())
        return out
