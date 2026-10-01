"""契约模型（依 cs_schema.md §2：全部继承 _ContractModel）。

基类统一施加（spec §2）：extra="forbid"（未声明字段拒绝）、allow_inf_nan=False
（NaN/Inf 拒绝）、validate_assignment=True（属性赋值同样过校验）。

SpoonCheck 字段要点（spec §2 模型表）：ts_ns, has_food, score∈[0,1],
cam_ref（非空串）；无跨字段不变式。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _ContractModel(BaseModel):
    """契约基类：冻结纪律（extra=forbid / NaN-Inf 拒绝 / 赋值校验）。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class SpoonCheck(_ContractModel):
    """勺上食物检查结果（感知层 → 黑板/喂食决策）。"""

    ts_ns: int = Field(ge=0)  # 纳秒时间戳（契约约定：时间一律纳秒）
    has_food: bool
    score: float = Field(ge=0.0, le=1.0)
    cam_ref: str = Field(min_length=1)  # 非空相机引用
