"""BeanEye 数据契约（M1 · v1.0 冻结）

全链路跨模块数据只走本文件的 Pydantic v2 模型（JSON 可序列化）。

约定：
- 每个模型都带 ``to_json() / from_json()``，序列化往返必须无损。
- 不变式（如「每粒只计最严重缺陷」）在模型校验器中强制，违规即 ``ValidationError``。
- 字段名与类型为冻结契约：只增不改名；发现契约问题上报规划方，不得自行改动。
- ``defect`` 类字段的合法取值由 ``configs/taxonomy.yaml`` 定义
  （经 ``beaneye/taxonomy.py`` 加载）；本模块保持纯契约，不依赖配置文件，
  对 ``defect`` 只做字符串约束。

坐标约定：凡带 ``_mm`` 后缀的字段一律为盘面毫米坐标系（M3 标定变换后）；
``polygon`` 为 ``[x, y]`` 外轮廓顶点列表；``color_lab`` 为掩码内均值 L*a*b*，
统一 0-255 标度。
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
]

SCHEMA_VERSION = "1.0"

_SIDE = Literal["top", "bottom"]
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


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
        if self.defect == "normal" and self.severity_rank != 0:
            raise ValueError("defect=normal 时 severity_rank 必须 = 0")
        if self.defect != "normal" and self.severity_rank <= 0:
            raise ValueError(f"缺陷类 {self.defect!r} 的 severity_rank 必须 > 0（0 保留给 normal）")
        return self


# ---------------------------------------------------------------------------
# M6 配对 + M7 严重度裁决（不变式「每粒只计最严重缺陷」）
# ---------------------------------------------------------------------------


def _resolve_worst(
    top: BeanObservation | None, bottom: BeanObservation | None
) -> tuple[str, str, int]:
    """按契约裁决：rank 高者胜；平级取 conf 高者并记 worst_side="both"。

    返回 ``(worst_side, final_defect, final_severity_rank)``。
    """
    if top is None and bottom is None:
        return "none", "normal", 0
    if bottom is None:
        return "top", top.defect, top.severity_rank  # type: ignore[union-attr]
    if top is None:
        return "bottom", bottom.defect, bottom.severity_rank
    rt, rb = top.severity_rank, bottom.severity_rank
    if rt > rb:
        return "top", top.defect, rt
    if rb > rt:
        return "bottom", bottom.defect, rb
    winner = top if top.defect_conf >= bottom.defect_conf else bottom
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

    @field_validator("sieve_hist", "delta_e_hist")
    @classmethod
    def _check_hist(cls, v: dict[str, int], info) -> dict[str, int]:
        for k, n in v.items():
            if n < 0:
                raise ValueError(f"{info.field_name}[{k!r}] 计数必须 >= 0，得到 {n}")
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
        （每粒只计最严重缺陷，一粒至多计一次）。"""
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
