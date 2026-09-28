"""感知包：口部三维估计。输入 BGR 图像（+可选深度图），输出 MouthPose（base 系）。

mono 后端 = 人脸关键点 + 先验距离缩放（source="mono"）；
depth 后端 = 关键点查深度相机像素。
"""
