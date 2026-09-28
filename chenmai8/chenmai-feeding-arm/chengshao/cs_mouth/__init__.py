"""感知包：口部三维估计。输入 BGR 图像（+可选深度图），输出 MouthPose（base 系）。

对外入口::

    from cs_mouth import MouthEstimator, MouthPrior

    est = MouthEstimator(backend="mono", prior=MouthPrior.load())
    pose = est.from_bgr(img_bgr)            # -> cs_schema.MouthPose（base 系）

两个后端（接口契约 §3.2）：
- ``mono``  演示主路径：人脸 478 关键点 + 几何口径比判张嘴 + 先验距离缩放
  （距离固定取 prior.distance_m，横向/纵向误差 ±3–5cm，由"勺停口前 5cm +
  用户前倾取食 + 座位定位垫"设计吸收）；source="mono"。
- ``depth`` 延后保留：关键点像素查深度图反演三维（接口不变，深度图到位即用）；
  source="depth"。

命名纪律：本包只依赖 cs_schema 与第三方库，不引用任何上游参考项目名。
"""

from __future__ import annotations

from .estimator import MouthEstimator
from .prior import MouthPrior

__all__ = ["MouthEstimator", "MouthPrior"]
