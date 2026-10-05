"""BeanEye 重生成试验包（M7 severity 自包含单元：taxonomy 序裁决 + CQI 计数）。

本包只凭 docs/assets（spec + CONTRACTS）与冻结测试从零实现；
不 import 任何原仓实现。模块面：

- ``beaneye.taxonomy``  缺陷分类体系加载（configs/taxonomy.yaml 唯一数据源）
- ``beaneye.schemas``   契约最小面（BeanMask / BeanObservation / PairedBean / 计数）
- ``beaneye.severity``  M7 严重度裁决 + CQI 计数（本次重生成目标模块）
"""
