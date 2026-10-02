"""BeanEye 数据契约（M1 · v1.0 冻结）

全链路跨模块数据只走本文件的 Pydantic v2 模型（JSON 可序列化）。

约定：
- 每个模型都带 ``to_json() / from_json()``，序列化往返必须无损。
- 不变式（如「每粒只计最严重缺陷」）在模型校验器中强制，违规即 ``ValidationError``。
- 字段名与类型为冻结契约：只增不改名；发现契约问题上报规划方，不得自行改动。
- ``defect`` 类字段的合法取值由 ``configs/taxonomy.yaml`` 定义
  （经 ``beaneye/taxonomy.py`` 加载）。W13 修复：构造期校验 defect 必须在
  taxonomy 中（原「纯字符串约束」放行了盘外类别）；taxonomy 在首次构造
  时惰性加载并缓存。注意：契约因此对 ``configs/taxonomy.yaml`` 有运行期
  依赖（该文件是契约附件 v1.0 的一部分，随仓分发）。

坐标约定：凡带 ``_mm`` 后缀的字段一律为盘面毫米坐标系（M3 标定变换后）；
``polygon`` 为 ``[x, y]`` 外轮廓顶点列表；``color_lab`` 为掩码内均值 L*a*b*，
**单一 Lab 标度 = OpenCV 8-bit LAB（lab8）**：三通道一律 0-255
（L*255/100，a/b 各 +128；CIE 量纲须先经 metrology 的仿射互转），构造期
拒绝越界——CIE 值（a/b 可负）混入会把 ΔE 直接放大（W13 修复，钉死标度）。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:  # 仅供类型标注；契约模块运行时不依赖 numpy
    import numpy as np

__all__ = [
    "SCHEMA_VERSION",
    "BeanEyeBaseModel",
    "BeanMask",
    "SegResult",
    "BeanObservation",
    "PairedBean",
    "TrayScan",
    "CalibResult",
    "StatsSummary",
    "Measurements",
    "GradingDecision",
    "PremiumDecision",
    "BatchResult",
    "CauseItem",
    "AgentReport",
    "PassportReport",
    "SegModel",
    "ClsModel",
    "StandardEngine",
    "RootCauseAgent",
    "CameraSource",
    "defect_counts_from_beans",
    "defect_is_countable",
]

SCHEMA_VERSION = "1.0"

_SIDE = Literal["top", "bottom"]
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_LAB8_MAX = 255.0  # lab8 单一标度：三通道一律 [0, 255]


# ---------------------------------------------------------------------------
# taxonomy 惰性加载（W13 修复：defect 构造期校验 + 可计性裁决的唯一依据）
# ---------------------------------------------------------------------------

_TAXONOMY_CACHE: object | None = None


def _taxonomy():
    """加载并缓存 configs/taxonomy.yaml（首次构造契约模型时才读盘）。"""
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is None:
        from beaneye.taxonomy import load_taxonomy

        _TAXONOMY_CACHE = load_taxonomy()
    return _TAXONOMY_CACHE


def defect_is_countable(defect: str) -> bool:
    """该缺陷类是否计入缺陷计数（taxonomy ``counts_as_defect``）。

    未知类别（不在 taxonomy 中）一律 False——不得参与「最严重缺陷」的
    可计比较。W13 起供 ``_resolve_worst`` 与 severity 裁决共用，保证
    契约校验器与 M7 裁决器逐位一致。
    """
    tax = _taxonomy()
    if not tax.is_valid_key(defect):  # type: ignore[attr-defined]
        return False
    return bool(tax.get(defect).counts_as_defect)  # type: ignore[attr-defined]


class BeanEyeBaseModel(BaseModel):
    """全部契约模型的公共基类：JSON 往返 + 严格字段（多余字段报错）。"""

    model_config = ConfigDict(extra="forbid")

    def to_json(self, *, indent: int | None = None) -> str:
        """序列化为 JSON 字符串（无损、字段序稳定）。"""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, data: str | bytes) -> Self:
        """从 JSON 字符串/字节反序列化；非法输入抛 ``ValidationError``。"""
        return cls.model_validate_json(data)


# ---------------------------------------------------------------------------
# M3 标定
# ---------------------------------------------------------------------------


class CalibResult(BeanEyeBaseModel):
    """ArUco 标定结果：原图像素 → 盘面毫米的单应变换。"""

    px_per_mm: float = Field(gt=0)
    H_top: list[list[float]]  # 3x3 单应: 原图px → 盘面mm
    H_bottom: list[list[float]]
    marker_ids: list[int]  # 期望 [0,1,2,3] 四角（顺序为角位序，可任意排列）
    reproj_err_px: float = Field(ge=0)

    @field_validator("H_top", "H_bottom")
    @classmethod
    def _check_homography(cls, v: list[list[float]], info) -> list[list[float]]:
        if len(v) != 3 or any(len(row) != 3 for row in v):
            raise ValueError(f"{info.field_name} 必须是 3x3 单应矩阵")
        return v

    @model_validator(mode="after")
    def _check_markers(self) -> Self:
        if sorted(self.marker_ids) != [0, 1, 2, 3]:
            raise ValueError(f"marker_ids 必须恰为四角 [0,1,2,3]，得到 {self.marker_ids}")
        return self


# ---------------------------------------------------------------------------
# M4 分割
# ---------------------------------------------------------------------------


class BeanMask(BeanEyeBaseModel):
    """单面单粒豆的几何掩码（盘面毫米坐标系）。"""

    mask_id: str = Field(min_length=1)  # 面内唯一, 如 "top_017"
    side: _SIDE
    polygon: list[list[float]]  # [x,y] 外轮廓（盘面 mm）
    bbox_mm: tuple[float, float, float, float]  # x0,y0,x1,y1 mm
    area_mm2: float = Field(ge=0)
    centroid_mm: tuple[float, float]
    source: Literal["oracle", "classic", "nn"]
    conf: float = Field(default=1.0, ge=0, le=1)  # classic/nn 0-1; oracle=1.0

    @field_validator("polygon")
    @classmethod
    def _check_polygon(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) == 0:
            raise ValueError("polygon 不能为空")
        for i, p in enumerate(v):
            if len(p) != 2:
                raise ValueError(f"polygon[{i}] 必须是 [x, y] 两个坐标，得到 {len(p)} 个")
        return v

    @model_validator(mode="after")
    def _check_geometry(self) -> Self:
        x0, y0, x1, y1 = self.bbox_mm
        if x0 > x1 or y0 > y1:
            raise ValueError(f"bbox_mm 必须满足 x0<=x1 且 y0<=y1，得到 {self.bbox_mm}")
        if self.source == "oracle" and self.conf != 1.0:
            raise ValueError("source=oracle 时 conf 必须 = 1.0")
        return self


class SegResult(BeanEyeBaseModel):
    """单面整盘分割结果。"""

    scan_id: str = Field(min_length=1)
    side: _SIDE
    masks: list[BeanMask]
    runtime_s: float = Field(ge=0)


# ---------------------------------------------------------------------------
# M5 分类
# ---------------------------------------------------------------------------


class BeanObservation(BeanEyeBaseModel):
    """单面单粒豆的观测记录（几何 + 类别 + 证据），obs_id = mask_id。"""

    obs_id: str = Field(min_length=1)  # = mask_id
    side: _SIDE
    defect: str = Field(min_length=1)  # taxonomy key, "normal" 无缺陷
    defect_conf: float = Field(ge=0, le=1)
    severity_rank: int = Field(ge=0)  # 0=normal 越大越严重, 取自 taxonomy/标准YAML
    crop_path: str = Field(min_length=1)  # 掩码裁剪 RGBA PNG 证据
    mask: BeanMask
    color_lab: tuple[float, float, float]  # 掩码内均值 L*a*b*（0-255 标度）
    eq_diameter_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_observation(self) -> Self:
        if self.obs_id != self.mask.mask_id:
            raise ValueError(f"obs_id({self.obs_id!r}) 必须等于 mask.mask_id({self.mask.mask_id!r})")
        # W13 修复：defect 必须是 taxonomy 合法类别（原仅非空字符串约束）
        _tax = _taxonomy()
        if not _tax.is_valid_key(self.defect):
            raise ValueError(
                f"defect {self.defect!r} 不在 taxonomy 中；合法取值: {_tax.keys()}"
            )
        if self.side != self.mask.side:
            raise ValueError(
                f"side({self.side!r}) 必须与 mask.side({self.mask.side!r}) 一致"
            )
        if self.defect == "normal" and self.severity_rank != 0:
            raise ValueError("defect=normal 时 severity_rank 必须 = 0")
        if self.defect != "normal" and self.severity_rank <= 0:
            raise ValueError(f"缺陷类 {self.defect!r} 的 severity_rank 必须 > 0（0 保留给 normal）")
        # W13 修复：单一 Lab 标度 = lab8（OpenCV 8-bit），三通道一律 [0,255]；
        # CIE 量纲（a/b 可负）混入会放大 ΔE，构造期拒绝
        for i, c in enumerate(self.color_lab):
            if not (0.0 <= c <= _LAB8_MAX):
                raise ValueError(
                    f"color_lab[{i}]={c} 越界：单一 lab8 标度要求三通道 ∈ [0,255]"
                    "（CIE 量纲请先经 metrology 仿射互转）"
                )
        return self


# ---------------------------------------------------------------------------
# M6 配对 + M7 严重度裁决（不变式「每粒只计最严重缺陷」）
# ---------------------------------------------------------------------------


def _resolve_worst(
    top: BeanObservation | None, bottom: BeanObservation | None
) -> tuple[str, str, int]:
    """按契约裁决：rank 高者胜；平级取 conf 高者并记 worst_side="both"。

    W13 修复（peaberry 吞次缺陷）：**非缺陷类（counts_as_defect=false，
    如 peaberry）不参与「最严重缺陷」比较**——若存在可计缺陷面，只在可计
    面之间裁决（另一面的非缺陷观测保留在字段里，仅不作最终缺陷）；两面
    皆为非缺陷/normal 时退回全量比较（peaberry 标注语义不丢失）。

    返回 ``(worst_side, final_defect, final_severity_rank)``。
    """
    if top is None and bottom is None:
        return "none", "normal", 0
    sides = [s for s in (top, bottom) if s is not None]
    countable = [s for s in sides if defect_is_countable(s.defect)]
    pool = countable or sides  # 全为非缺陷/normal → 保留原裁决（标注不丢）
    if len(pool) == 1:
        s = pool[0]
        side_name = "top" if s is top else "bottom"
        return side_name, s.defect, s.severity_rank
    a, b = pool  # len(pool)==2：两面都在且（或不含可计面时）走全量比较
    ra, rb = a.severity_rank, b.severity_rank
    if ra > rb:
        return ("top" if a is top else "bottom"), a.defect, ra
    if rb > ra:
        return ("top" if b is top else "bottom"), b.defect, rb
    winner = a if a.defect_conf >= b.defect_conf else b
    return "both", winner.defect, winner.severity_rank


class PairedBean(BeanEyeBaseModel):
    """上下配对后的一粒豆；final_* 字段携带「每粒只计最严重缺陷」的裁决结果。"""

    bean_id: str = Field(min_length=1)  # "b0001"
    top: BeanObservation | None
    bottom: BeanObservation | None
    pairing_cost: float  # mm 距离; 单面= -1
    worst_side: Literal["top", "bottom", "both", "none"]
    final_defect: str  # 两面中 severity_rank 最高者; 同级取 conf 高
    final_severity_rank: int

    @model_validator(mode="after")
    def _check_worst(self) -> Self:
        want_side, want_defect, want_rank = _resolve_worst(self.top, self.bottom)
        if (self.worst_side, self.final_defect, self.final_severity_rank) != (
            want_side,
            want_defect,
            want_rank,
        ):
            raise ValueError(
                "final_* 与两面观测不一致（契约：severity_rank 高者胜，平级取 conf 高者并记 "
                f"worst_side=both）。期望 {(want_side, want_defect, want_rank)}，"
                f"得到 {(self.worst_side, self.final_defect, self.final_severity_rank)}"
            )
        single = (self.top is None) != (self.bottom is None)
        if single and self.pairing_cost != -1:
            raise ValueError(f"单面豆 pairing_cost 必须 = -1，得到 {self.pairing_cost}")
        if self.top is None and self.bottom is None and self.pairing_cost != -1:
            raise ValueError("两面皆空的占位记录 pairing_cost 必须 = -1")
        # W13 修复：双面配对代价必须为非负距离（-1 保留给单面/占位）
        if not single and self.top is not None and self.pairing_cost < 0:
            raise ValueError(
                f"双面豆 pairing_cost 必须 >= 0（mm 距离），得到 {self.pairing_cost}；"
                "-1 只保留给单面/占位记录"
            )
        return self

    @classmethod
    def from_sides(
        cls,
        bean_id: str,
        top: BeanObservation | None,
        bottom: BeanObservation | None,
        pairing_cost: float,
    ) -> PairedBean:
        """按契约裁决规则构造（M6/M7 的规范入口，保证不变式成立）。"""
        worst_side, final_defect, final_rank = _resolve_worst(top, bottom)
        return cls(
            bean_id=bean_id,
            top=top,
            bottom=bottom,
            pairing_cost=pairing_cost,
            worst_side=worst_side,  # type: ignore[arg-type]
            final_defect=final_defect,
            final_severity_rank=final_rank,
        )


def defect_counts_from_beans(
    beans: list[PairedBean], *, include_normal: bool = False
) -> dict[str, int]:
    """每粒只按 final_defect 计一次的标准缺陷直方（M9 计数的规范实现）。

    ``include_normal=False`` 时不含 "normal"（好豆不是缺陷）。
    """
    hist: dict[str, int] = {}
    for b in beans:
        key = b.final_defect
        if key == "normal" and not include_normal:
            continue
        hist[key] = hist.get(key, 0) + 1
    return hist


# ---------------------------------------------------------------------------
# M2 采集
# ---------------------------------------------------------------------------


class TrayScan(BeanEyeBaseModel):
    """一次整盘双面采集（真实拍摄或合成）。"""

    scan_id: str = Field(min_length=1)
    sample_id: str = Field(min_length=1)
    tray_id: str = Field(min_length=1)
    top_image: str = Field(min_length=1)  # 相对路径
    bottom_image: str = Field(min_length=1)  # 相对路径
    calibration: CalibResult | None
    captured_at: str  # ISO8601
    source: Literal["mock", "usb", "synth"]

    @field_validator("captured_at")
    @classmethod
    def _check_iso8601(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"captured_at 必须是 ISO8601 字符串，得到 {v!r}") from e
        return v


# ---------------------------------------------------------------------------
# M8 计量
# ---------------------------------------------------------------------------


class StatsSummary(BeanEyeBaseModel):
    """等效直径统计（mm）。"""

    min: float
    max: float
    mean: float
    median: float


class Measurements(BeanEyeBaseModel):
    """整盘计量：粒数 / 目数分布 / 色差 / 估重。"""

    bean_count: int = Field(ge=0)
    sieve_hist: dict[str, int]  # {"16":320,"15":80,...} 目数→粒数
    sieve_pass: bool | None  # 对照标准
    eq_diameter_mm_stats: StatsSummary
    color_lab_mean: tuple[float, float, float]
    delta_e_mean: float = Field(ge=0)  # vs 标准YAML的 reference_lab（CIE76）
    delta_e_hist: dict[str, int]  # 分桶 ["0-2","2-4",...]
    est_weight_g: float = Field(ge=0)
    weight_model: str = Field(min_length=1)  # "area_linear:v1"
    # 轨2 大中小筛段（v1.2 增补，契约只增不改名；W13 warnings 先例）：
    # 大(≥17目)/中(15-16)/小(≤14)，口径与来源见 configs/size_bands.yaml；
    # hist 与 sieve_hist 同源同舍入（aggregate_sieve_hist 聚合恒一致），
    # frac 为 0-1 占比（总和 1；空盘或筛段配置不可用时为空映射）。
    size_band_hist: dict[str, int] = Field(default_factory=dict)  # 筛段 key → 粒数
    size_band_frac: dict[str, float] = Field(default_factory=dict)  # 筛段 key → 占比(0-1)

    @field_validator("sieve_hist", "delta_e_hist", "size_band_hist")
    @classmethod
    def _check_hist(cls, v: dict[str, int], info) -> dict[str, int]:
        for k, n in v.items():
            if n < 0:
                raise ValueError(f"{info.field_name}[{k!r}] 计数必须 >= 0，得到 {n}")
        return v

    @field_validator("color_lab_mean")
    @classmethod
    def _check_lab8(cls, v: tuple[float, float, float]) -> tuple[float, float, float]:
        """W13 修复：与逐粒 color_lab 同一 lab8 标度，三通道 ∈ [0,255]。"""
        for i, c in enumerate(v):
            if not (0.0 <= c <= _LAB8_MAX):
                raise ValueError(
                    f"color_lab_mean[{i}]={c} 越界：单一 lab8 标度要求三通道 ∈ [0,255]"
                    "（CIE 量纲请先经 metrology 仿射互转）"
                )
        return v


# ---------------------------------------------------------------------------
# M9 定级
# ---------------------------------------------------------------------------


class GradingDecision(BeanEyeBaseModel):
    """标准引擎定级结论。"""

    standard_id: str = Field(min_length=1)  # cqi_fine_robusta | nyt_604 | db46_t642
    grade: str = Field(min_length=1)  # 如 "Fine" / "一级" / "合格"
    passed: bool
    primary_count: int = Field(ge=0)
    secondary_count: int = Field(ge=0)
    defect_counts: dict[str, int]  # taxonomy key → 粒数(每粒只计一次)
    reasons: list[str]  # 人读判定理由(三语模板键)
    # v1.1 增补（契约只增不改名）：标准 YAML 的 verified:false 等核对告警，
    # M10 护照页脚"标准阈值核对中"角标引用（开发指令 M9/M10 spec 命名了
    # GradingDecision.warnings 但 v1.0 冻结版缺失，2026-09-28 W9 增补）。
    warnings: list[str] = Field(default_factory=list)
    standard_yaml_sha: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("defect_counts")
    @classmethod
    def _check_counts(cls, v: dict[str, int]) -> dict[str, int]:
        for k, n in v.items():
            if n < 0:
                raise ValueError(f"defect_counts[{k!r}] 必须 >= 0，得到 {n}")
        return v


# ---------------------------------------------------------------------------
# 轨3 精品/普通判定层（v1.2 增补，契约只增不改名；W13 warnings 先例）
# ---------------------------------------------------------------------------


class PremiumDecision(BeanEyeBaseModel):
    """精品（premium）/ 普通（commercial）判定结论。

    判定口径（轨3 spec）：精品 = 严重缺陷（主缺陷）0 粒 **且** 一般缺陷
    （次缺陷）等效粒数 ≤5（CQI Fine Robusta 口径，v0 1 粒 = 1 等效）；
    其余判普通。与定级（GradingDecision）解耦：本层是**贸易口径的分层
    参考**，不改变标准的法定等级结论。``grade_legal_db46`` 在传入 DB46
    法定表时附带给出其法定理化等级（"DB46 口径同时给出其法定等级"）。

    ``reasons`` 沿用引擎模板键格式 ``"<模板键>:<k>=<v>[;<k>=<v>]*"``（键
    字符集 [A-Za-z0-9_.]）；``warnings`` 沿用 GradingDecision.warnings 机制
    （阈值/配置未核对时透传，M10 页脚角标同源）。``moisture_pct`` 为水分
    占位（管线 v0 无水分计，恒 None；DB46 口径仅在提供时参与水分享核）。
    """

    standard_id: str = Field(min_length=1)  # 精品阈值所依据的标准 id（缺省 cqi_fine_robusta）
    verdict: Literal["premium", "commercial"]
    primary_count: int = Field(ge=0)  # 严重缺陷（主缺陷）粒数
    secondary_count: int = Field(ge=0)  # 一般缺陷（次缺陷）计数
    secondary_equiv_count: float = Field(ge=0)  # 一般缺陷等效粒数（v0 CQI 口径 1:1 = 计数）
    primary_limit: int = Field(ge=0)  # 本判定采用的主缺陷上限（0）
    secondary_equiv_limit: float = Field(gt=0)  # 本判定采用的次缺陷等效上限（5）
    size_band_hist: dict[str, int]  # 大中小直方（筛段 key → 粒数；key 来自 configs/size_bands.yaml）
    size_band_frac: dict[str, float]  # 大中小占比（0-1，总和 1；空盘全 0）
    bean_count: int = Field(ge=0)
    moisture_pct: float | None = None  # 水分占位（g/100g）；None = 未测
    grade_legal_db46: str | None = None  # DB46/T 642 法定理化等级（如"理化一级"；未计算为 None）
    reasons: list[str]  # 人读判定理由（三语模板键，同 GradingDecision 格式）
    warnings: list[str] = Field(default_factory=list)

    @field_validator("size_band_hist", "size_band_frac")
    @classmethod
    def _check_size_band(cls, v: dict, info) -> dict:
        for k, n in v.items():
            if isinstance(n, bool):
                continue
            if isinstance(n, int) and n < 0:
                raise ValueError(f"{info.field_name}[{k!r}] 计数必须 >= 0，得到 {n}")
            if isinstance(n, float) and n < 0.0:
                raise ValueError(f"{info.field_name}[{k!r}] 占比必须 >= 0，得到 {n}")
        return v


# ---------------------------------------------------------------------------
# M11 溯因智能体
# ---------------------------------------------------------------------------


class CauseItem(BeanEyeBaseModel):
    """单条溯因：缺陷 → 加工环节归因。

    ``stage`` 规范取值（中文环节名，与根因知识表一致）：
    采摘 / 发酵 / 干燥 / 仓储 / 脱壳。
    """

    defect: str = Field(min_length=1)  # taxonomy key
    stage: str = Field(min_length=1)  # 采摘/发酵/干燥/仓储/脱壳
    likelihood: float  # 先验/后验强度
    evidence_summary: str = Field(min_length=1)

    @field_validator("defect")
    @classmethod
    def _check_defect_in_taxonomy(cls, v: str) -> str:
        """W13 修复：溯因对象必须是 taxonomy 合法类别（LLM 输出已在上游清洗）。"""
        _tax = _taxonomy()
        if not _tax.is_valid_key(v):
            raise ValueError(f"溯因 defect {v!r} 不在 taxonomy 中；合法取值: {_tax.keys()}")
        return v


class AgentReport(BeanEyeBaseModel):
    """溯因智能体输出（模板或 LLM 后端）。"""

    lang: Literal["zh", "en", "vi"]
    causes: list[CauseItem]
    advice: list[str]
    citations: list[str]  # 标准条目号/知识库chunk id
    backend: Literal["template", "llm"]


# ---------------------------------------------------------------------------
# M10 质量护照
# ---------------------------------------------------------------------------


class PassportReport(BeanEyeBaseModel):
    """三语质量护照的产物登记（与 BatchResult.result_id 绑定）。"""

    report_id: str = Field(min_length=1)  # 与 result_id 绑定
    langs: list[Literal["zh", "en", "vi"]] = Field(min_length=1)
    html_paths: dict[str, str]
    qr_payload: str = Field(min_length=1)  # verify URL + report_id + sha256(BatchResult json)
    sha256: str = Field(pattern=_SHA256_PATTERN)  # BatchResult 规范化 JSON 的 sha256

    @model_validator(mode="after")
    def _check_langs(self) -> Self:
        if len(set(self.langs)) != len(self.langs):
            raise ValueError(f"langs 不得重复，得到 {self.langs}")
        return self


# ---------------------------------------------------------------------------
# 整盘结果
# ---------------------------------------------------------------------------


class BatchResult(BeanEyeBaseModel):
    """全链路终点：一盘样品的完整结果（护照/智能体/API 都以它为源）。"""

    result_id: str = Field(min_length=1)  # uuid4
    sample_id: str = Field(min_length=1)
    scan_ids: list[str]
    beans: list[PairedBean]
    measurements: Measurements
    grading: GradingDecision
    agent_report: AgentReport | None
    timings_s: dict[str, float]  # 各阶段耗时
    pipeline_versions: dict[str, str]  # {"segment":"classic","classify":"rules_v0",...}

    @model_validator(mode="after")
    def _check_defect_counts_consistent(self) -> Self:
        """不变式：grading.defect_counts 必须与逐粒 final_defect 直方一致
        （每粒只计最严重缺陷，一粒至多计一次）。

        W13 修复补强：primary_count / secondary_count 必须与豆列表按 taxonomy
        主/次归属（counts_as_defect=true）的分计一致；measurements.bean_count
        必须等于豆列表长度（托盘粒数口径）。
        """
        hist = defect_counts_from_beans(self.beans, include_normal=True)
        for key, n in self.grading.defect_counts.items():
            actual = hist.get(key, 0)
            if actual != n:
                raise ValueError(
                    f"defect_counts[{key!r}]={n} 与逐粒 final_defect 直方(={actual})不一致："
                    "每粒只计最严重缺陷，一粒至多计一次"
                )
        for key in hist:
            if key != "normal" and key not in self.grading.defect_counts:
                raise ValueError(
                    f"存在 final_defect={key!r} 的豆但 defect_counts 缺失该键"
                )
        # ---- W13：主/次分计与豆列表一致（peaberry 等 counts_as_defect=false 不计）----
        _tax = _taxonomy()
        primary = 0
        secondary = 0
        for b in self.beans:
            if not _tax.is_valid_key(b.final_defect):
                continue  # 盘外类别不参与主/次分计（计数一致性由 defect_counts 校验兜住）
            dc = _tax.get(b.final_defect)
            if not dc.counts_as_defect:
                continue
            if dc.kind == "primary":
                primary += 1
            elif dc.kind == "secondary":
                secondary += 1
        if self.grading.primary_count != primary or self.grading.secondary_count != secondary:
            raise ValueError(
                f"primary_count/secondary_count({self.grading.primary_count}/"
                f"{self.grading.secondary_count}) 与豆列表按 taxonomy 主/次归属的分计"
                f"({primary}/{secondary})不一致"
            )
        # ---- W13：bean_count 与豆列表一致 ----
        if self.measurements.bean_count != len(self.beans):
            raise ValueError(
                f"measurements.bean_count({self.measurements.bean_count}) 与豆列表长度"
                f"({len(self.beans)})不一致（bean_count=本盘粒数口径）"
            )
        return self


# ---------------------------------------------------------------------------
# §3.2 接口 Protocol（模型可替换的关键：oracle → classic → NN）
# ---------------------------------------------------------------------------


class SegModel(Protocol):
    """分割模型接口：整盘 RGB 图 + 采集上下文 → 单面分割结果。"""

    def predict(self, img_rgb: "np.ndarray", scan: TrayScan) -> SegResult: ...


class ClsModel(Protocol):
    """分类模型接口：单粒 RGBA crop + 掩码 → (defect, conf, severity_rank)。"""

    def classify(
        self, crop_rgba: "np.ndarray", mask: BeanMask
    ) -> tuple[str, float, int]: ...


class StandardEngine(Protocol):
    """标准引擎接口：逐粒结果 + 计量 → 定级结论。"""

    def evaluate(
        self, beans: list[PairedBean], measurements: Measurements
    ) -> GradingDecision: ...


class RootCauseAgent(Protocol):
    """溯因智能体接口。"""

    def explain(self, result: BatchResult, lang: str) -> AgentReport: ...


class CameraSource(Protocol):
    """采集源接口：Mock / USB / 合成。"""

    def capture_pair(self, sample_id: str, tray_id: str) -> TrayScan: ...
