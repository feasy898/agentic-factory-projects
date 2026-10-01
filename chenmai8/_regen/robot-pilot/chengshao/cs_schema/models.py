"""契约模型（重生成最小切片：SpoonCheck）。

基类纪律与 cs_schema spec §2 一致（models.py:33-40 的对外行为）：
- extra="forbid"：未声明字段拒绝（拼写漂移同样拒绝）；
- allow_inf_nan=False：NaN/Inf 拒绝；
- validate_assignment=True：属性赋值同样过校验。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _ContractModel(BaseModel):
    """全部契约模型的统一基类（见 cs_schema spec §2 模型表）。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class SpoonCheck(_ContractModel):
    """勺上食物检查结果（cs_food 感知输出 → 黑板）。"""

    ts_ns: int = Field(ge=0, description="采集时间戳（纳秒，一律纳秒）")
    has_food: bool = Field(description="勺上是否有食物（阈值偏保守：宁可重舀，不空勺到口）")
    score: float = Field(ge=0.0, le=1.0, description="食物掩码占比（0-1）")
    cam_ref: str = Field(min_length=1, description="来源相机引用（缺省 wrist_cam）")
