"""分拣线 · SortPlanner：一帧逐粒检测结果 → 严重度降序抓取队列。

排序契约（简报冻结）：

- 按 taxonomy 严重度（``taxonomy.severity_rank``）**降序**——最严重的先抓；
- 平级确定性次序：面积大者先、再按 target_id 字典序（同盘可复现）；
- ``normal`` 不参与分拣（severity_rank=0，好豆留在原位）；其余类别
  （含 peaberry 这类不计缺陷的标注类）一律入队，各自映射到分级盒；
- 缺陷类别 → 分级盒桌面坐标的映射读 configs/sort.yaml ``bins`` 节
  （未登记类别走 ``default`` 兜底盒）；
- 工作空间前置校验：目标/分级盒超出包络不阻塞全盘作业，而是**显式记入
  ``SortPlan.skipped``**（含原因），由 Session 事件日志如实透出。

数据契约：本模块模型继承 ``beaneye.schemas.BeanEyeBaseModel``（Pydantic v2，
JSON 往返无损），与质检线契约同一风格；仅新增、不改质检线任何冻结字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from pydantic import Field

from beaneye.schemas import BeanEyeBaseModel, BeanObservation
from beaneye.sort.config import SortConfig, WorkspaceBounds
from beaneye.sort.frame import FrameToTable
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "PlannerError",
    "SortTarget",
    "SkippedTarget",
    "PickStep",
    "SortPlan",
    "SortPlanner",
    "targets_from_observations",
]


class PlannerError(ValueError):
    """规划失败（未知类别 / 映射缺失 / 目标点非法）。"""


class SortTarget(BeanEyeBaseModel):
    """一粒待分拣目标（一帧检测结果；坐标为桌面 mm）。"""

    target_id: str = Field(min_length=1)          # 检出 id（如 mask_id）
    defect: str = Field(min_length=1)             # taxonomy key
    severity_rank: int = Field(ge=0)              # taxonomy.severity_rank
    x_mm: float
    y_mm: float
    area_mm2: float = Field(gt=0)
    conf: float = Field(default=1.0, ge=0, le=1)  # 分类置信度（透传记录）


class SkippedTarget(BeanEyeBaseModel):
    """被跳过的目标（附机器可读原因，事件日志如实透出）。"""

    target: SortTarget
    reason: str = Field(min_length=1)


class PickStep(BeanEyeBaseModel):
    """单步抓取指令（Session 逐步执行；坐标全部桌面 mm）。"""

    order: int = Field(ge=1)
    target: SortTarget
    bin_name: str                                 # 分级盒名（=bins key 或 "default"）
    pick_x_mm: float
    pick_y_mm: float
    pick_z_mm: float                              # 抓取面高度
    travel_z_mm: float                            # 巡航安全高度
    bin_x_mm: float
    bin_y_mm: float


class SortPlan(BeanEyeBaseModel):
    """一次分拣计划（可 JSON 导出 / render 画图 / Session 逐步执行）。"""

    created_at: str
    steps: list[PickStep]
    skipped: list[SkippedTarget] = Field(default_factory=list)

    def per_bin_counts(self) -> dict[str, int]:
        """分级盒 → 计划粒数（汇总口径）。"""
        hist: dict[str, int] = {}
        for s in self.steps:
            hist[s.bin_name] = hist.get(s.bin_name, 0) + 1
        return hist


class SortPlanner:
    """抓取队列规划器（severity 降序 + 分级盒映射 + 工作空间前置校验）。"""

    def __init__(
        self,
        config: SortConfig,
        *,
        taxonomy: Taxonomy | None = None,
        workspace: WorkspaceBounds | None = None,
    ) -> None:
        """``workspace`` 缺省用 config.workspace；注入覆盖用于仿真放大包络。"""
        self._config = config
        self._tax = taxonomy if taxonomy is not None else load_taxonomy()
        self._workspace = workspace if workspace is not None else config.workspace

    @property
    def workspace(self) -> WorkspaceBounds:
        return self._workspace

    def plan(self, targets: Sequence[SortTarget]) -> SortPlan:
        """生成抓取计划：severity 降序入队 + 逐粒映射分级盒 + 可达性预检。"""
        # 1) 过滤 normal + 未知类别校验
        queue: list[SortTarget] = []
        for t in targets:
            if not self._tax.is_valid_key(t.defect):
                raise PlannerError(
                    f"目标 {t.target_id!r} 的缺陷类别 {t.defect!r} 不在 taxonomy 中；"
                    f"合法取值: {self._tax.keys()}"
                )
            if self._tax.severity_rank(t.defect) != t.severity_rank:
                raise PlannerError(
                    f"目标 {t.target_id!r} severity_rank={t.severity_rank} 与 taxonomy "
                    f"不一致（{t.defect} 应为 {self._tax.severity_rank(t.defect)}）——"
                    "排序契约以 taxonomy 为唯一依据"
                )
            if t.defect == "normal":
                continue  # 好豆不分拣
            queue.append(t)

        # 2) severity 降序；平级：面积大者先，再 target_id 字典序（确定性）
        queue.sort(key=lambda t: (-t.severity_rank, -t.area_mm2, t.target_id))

        # 3) 逐粒映射分级盒 + 工作空间前置校验
        steps: list[PickStep] = []
        skipped: list[SkippedTarget] = []
        for i, t in enumerate(queue, start=1):
            reason = self._unreachable_reason(t)
            if reason is not None:
                skipped.append(SkippedTarget(target=t, reason=reason))
                continue
            bin_name, (bx, by) = self._bin_for(t.defect)
            steps.append(
                PickStep(
                    order=len(steps) + 1,
                    target=t,
                    bin_name=bin_name,
                    pick_x_mm=t.x_mm,
                    pick_y_mm=t.y_mm,
                    pick_z_mm=self._config.pick.pick_z_mm,
                    travel_z_mm=self._config.pick.travel_z_mm,
                    bin_x_mm=bx,
                    bin_y_mm=by,
                )
            )
        return SortPlan(
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            steps=steps,
            skipped=skipped,
        )

    # ---- 内部 -----------------------------------------------------------------

    def _bin_for(self, defect: str) -> tuple[str, tuple[float, float]]:
        """缺陷类别 → 分级盒；未登记类别走 default 兜底盒。"""
        bins = self._config.bins_mm
        if defect in bins:
            return defect, bins[defect]
        return "default", bins["default"]

    def _unreachable_reason(self, t: SortTarget) -> str | None:
        """前置可达性检查（抓取点与目标分级盒都要在包络内）；通过返回 None。"""
        z_travel = self._config.pick.travel_z_mm
        if not (self._workspace.contains(t.x_mm, t.y_mm, 0.0)
                and self._workspace.contains(t.x_mm, t.y_mm, z_travel)):
            return (
                f"抓取点 ({t.x_mm:.1f}, {t.y_mm:.1f}) 超出工作空间包络 "
                f"x[{self._workspace.x_min_mm}, {self._workspace.x_max_mm}] "
                f"y[{self._workspace.y_min_mm}, {self._workspace.y_max_mm}]"
            )
        bin_name, (bx, by) = self._bin_for(t.defect)
        if not self._workspace.contains(bx, by, z_travel):
            return (
                f"分级盒 {bin_name} ({bx:.1f}, {by:.1f}) 超出工作空间包络 "
                f"x[{self._workspace.x_min_mm}, {self._workspace.x_max_mm}] "
                f"y[{self._workspace.y_min_mm}, {self._workspace.y_max_mm}]"
            )
        return None


def targets_from_observations(
    observations: Sequence[BeanObservation],
    mapper: FrameToTable,
    *,
    taxonomy: Taxonomy | None = None,
) -> list[SortTarget]:
    """质检线逐粒观测（托盘 mm）→ 分拣目标（桌面 mm）。

    质心经 ``mapper.tray_to_table_mm`` 映射；severity_rank 直接沿用观测里
    已裁决的值（与 taxonomy 校验在 SortPlanner.plan 兜底一致）。
    """
    tax = taxonomy if taxonomy is not None else load_taxonomy()
    out: list[SortTarget] = []
    for o in observations:
        if not tax.is_valid_key(o.defect):
            raise PlannerError(
                f"观测 {o.obs_id!r} 的缺陷类别 {o.defect!r} 不在 taxonomy 中"
            )
        x, y = (float(v) for v in mapper.tray_to_table_mm(list(o.mask.centroid_mm)))
        out.append(
            SortTarget(
                target_id=o.obs_id,
                defect=o.defect,
                severity_rank=o.severity_rank,
                x_mm=x,
                y_mm=y,
                area_mm2=o.mask.area_mm2,
                conf=o.defect_conf,
            )
        )
    return out
