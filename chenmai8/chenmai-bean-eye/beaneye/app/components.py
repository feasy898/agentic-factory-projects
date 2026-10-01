"""M13 应用壳 · 检测管线装配（组件注册表 + 缺省降级）。

开发指令 §4 M13：检测/分类模型按冻结接口
（``beaneye.schemas.SegModel`` / ``ClsModel`` Protocol）装配，实现可替换
（oracle → classic → NN）。当前仓库状态：

- M4（``beaneye.segment``）与 M5（``beaneye.classify``）**尚未落地**
  （等待素材库/数据集解锁）；
- 因此本装配器在缺省情况下给出**显式降级**：空实现 ``NullSegModel`` /
  ``NullClsModel``（0 检出、全部按 normal），并把降级阶段与原因写入
  API 响应（``degraded_stages`` / ``degraded_reasons``），绝不静默伪装
  成完整识别结果。

装配策略（:func:`build_components`）：

1. 显式注入优先（应用工厂 / 测试替身直接传实例）；
2. 否则探测 ``beaneye.segment`` / ``beaneye.classify`` 包：存在
   ``build_default(**kwargs)`` 工厂即调用接入（未来模块落地后零改动自动接线）；
3. 探测失败（未安装/工厂抛错）→ 对应阶段降级为 Null 实现，记录原因。

适配注记（协议缺陷，已上报规划方）：冻结的 ``SegModel.predict(img_rgb, scan)``
签名不携带 ``side``——M13 约定装配器**每面各调一次** predict，并把返回
``SegResult`` 的 ``side`` 与 ``mask_id`` 前缀按所处理面规范化
（:func:`normalize_seg_result`）。实现若已自行携带正确 side 则原样保留。
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from beaneye.schemas import BeanMask, SegResult, TrayScan

__all__ = [
    "ComponentError",
    "ComponentBox",
    "NullSegModel",
    "NullClsModel",
    "build_components",
    "normalize_seg_result",
    "SEG_PACKAGE",
    "CLS_PACKAGE",
    "FACTORY_ATTR",
]

# 未来 M4/M5 落地时的接线约定：<pkg>.build_default(**kwargs) -> 实现
SEG_PACKAGE = "beaneye.segment"
CLS_PACKAGE = "beaneye.classify"
FACTORY_ATTR = "build_default"


class ComponentError(RuntimeError):
    """组件装配失败（注入实现不满足接口 / 工厂异常且无降级位）。"""


# ---------------------------------------------------------------------------
# Null 实现（显式降级位：0 检出、版本号带 unavailable 标记）
# ---------------------------------------------------------------------------


class NullSegModel:
    """分割缺位时的显式降级实现：恒返回空 ``SegResult``（0 掩码）。"""

    stage = "segment"
    version = "unavailable:null"
    reason = "分割模型未接入（beaneye.segment 缺省）——本盘 0 检出，缺陷计数不代表样品实况"

    def predict(self, img_rgb: Any, scan: TrayScan) -> SegResult:
        t0 = time.perf_counter()
        return SegResult(
            scan_id=scan.scan_id,
            side="top",  # 由装配器按所处理面规范化（协议不携带 side，见模块 docstring）
            masks=[],
            runtime_s=time.perf_counter() - t0,
        )


class NullClsModel:
    """分类缺位时的显式降级实现：恒返回 normal（不会被调用到——无掩码即无 crop）。"""

    stage = "classify"
    version = "unavailable:null"
    reason = "分类模型未接入（beaneye.classify 缺省）——检出粒一律记 normal"

    def classify(self, crop_rgba: Any, mask: BeanMask) -> tuple[str, float, int]:
        return "normal", 0.0, 0


# ---------------------------------------------------------------------------
# 组件盒：阶段 → 实现 + 降级元数据
# ---------------------------------------------------------------------------


@runtime_checkable
class _Named(Protocol):
    """可选约定：实现暴露 stage/version/reason 自述（无则用盒上缺省）。"""

    stage: str
    version: str
    reason: str


@dataclass
class ComponentBox:
    """一个阶段的装配产物：实现实例 + 是否降级 + 原因。"""

    impl: Any
    degraded: bool
    reason: str = ""
    version: str = ""

    def resolved_version(self, default: str) -> str:
        return self.version or default


@dataclass
class Components:
    """整条检测管线的装配结果（segment/classify 可为 Null 降级实现）。"""

    segment: ComponentBox
    classify: ComponentBox

    def degraded_stages(self) -> list[str]:
        out: list[str] = []
        for box in (self.segment, self.classify):
            if box.degraded:
                out.append(box.impl.stage if isinstance(box.impl, _Named) else "")
        return [s for s in out if s]

    def degraded_reasons(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for box in (self.segment, self.classify):
            if box.degraded:
                out[box.impl.stage if isinstance(box.impl, _Named) else "pipeline"] = box.reason
        return out


def _wrap(impl: Any, stage: str, default_version: str, injected_reason: str) -> ComponentBox:
    if impl is None:
        null = _null_for(stage)
        return ComponentBox(impl=null, degraded=True, reason=null.reason, version=null.version)
    if not callable(getattr(impl, "predict" if stage == "segment" else "classify", None)):
        raise ComponentError(
            f"注入的 {stage} 实现缺少 {'predict' if stage == 'segment' else 'classify'} 方法："
            f"{type(impl).__name__}（冻结接口见 beaneye.schemas Protocol）"
        )
    return ComponentBox(
        impl=impl,
        degraded=False,
        reason="",
        version=str(getattr(impl, "version", "") or default_version),
    )


def _null_for(stage: str) -> Any:
    return NullSegModel() if stage == "segment" else NullClsModel()


def _try_factory(pkg_name: str, stage: str) -> tuple[Any | None, str]:
    """探测 <pkg>.build_default()；返回 (实例|None, 失败原因)。"""
    try:
        mod = importlib.import_module(pkg_name)
    except ImportError as exc:
        return None, f"{pkg_name} 未安装（{exc.__class__.__name__}）——{stage} 阶段降级"
    factory = getattr(mod, FACTORY_ATTR, None)
    if factory is None or not callable(factory):
        return None, f"{pkg_name} 存在但缺少 {FACTORY_ATTR}() 工厂——{stage} 阶段降级"
    try:
        impl = factory()
    except Exception as exc:  # 工厂自身失败（缺权重/缺配置）同样降级，不阻塞应用
        return None, f"{pkg_name}.{FACTORY_ATTR}() 抛错（{exc.__class__.__name__}: {exc}）——{stage} 阶段降级"
    return impl, ""


def build_components(
    segment: Any | None = None,
    classify: Any | None = None,
    *,
    allow_probe: bool = True,
) -> Components:
    """装配检测管线。

    参数
    ----
    segment / classify:
        显式注入实现（满足冻结 Protocol；测试替身走这里）。传 None 时先探测
        ``beaneye.segment`` / ``beaneye.classify`` 工厂（``allow_probe=True``），
        探测不到即降级 Null 实现。
    allow_probe:
        False 时跳过工厂探测（纯注入/纯降级模式，测试用）。
    """
    seg_impl = segment
    seg_reason = ""
    if seg_impl is None and allow_probe:
        seg_impl, seg_reason = _try_factory(SEG_PACKAGE, "segment")
    seg_box = _wrap(seg_impl, "segment", "segment:v?", seg_reason)
    if seg_box.degraded and not seg_box.reason:
        seg_box.reason = seg_reason or NullSegModel.reason

    cls_impl = classify
    cls_reason = ""
    if cls_impl is None and allow_probe:
        cls_impl, cls_reason = _try_factory(CLS_PACKAGE, "classify")
    cls_box = _wrap(cls_impl, "classify", "classify:v?", cls_reason)
    if cls_box.degraded and not cls_box.reason:
        cls_box.reason = cls_reason or NullClsModel.reason

    return Components(segment=seg_box, classify=cls_box)


# ---------------------------------------------------------------------------
# SegResult 规范化（协议不携带 side 的装配器适配）
# ---------------------------------------------------------------------------


def normalize_seg_result(raw: SegResult, *, side: str, scan_id: str) -> SegResult:
    """把实现返回的 ``SegResult`` 规范化到所处理面。

    - ``side``/``scan_id`` 不符 → ``model_copy`` 更新（契约模型不可变字段之外的适配位）；
    - 掩码 ``side`` 与 ``mask_id``（``{side}_{i:04d}``）随之重键；
    - 已一致的原样返回（尊重自行携带 side 的实现）。
    """
    needs = raw.side != side or raw.scan_id != scan_id or any(
        m.side != side for m in raw.masks
    )
    if not needs:
        return raw
    masks: list[BeanMask] = [
        m.model_copy(update={"side": side, "mask_id": f"{side}_{i:04d}"})
        if m.side != side
        else m
        for i, m in enumerate(raw.masks)
    ]
    return raw.model_copy(update={"side": side, "scan_id": scan_id, "masks": masks})
