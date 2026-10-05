"""webui —— 最小操作界面（M10）。

- :mod:`webui.specgen`：表单字段 → PlayableSpec v1 组装器（seed/可解性/orderSolution
  全部复用 pfcore.invariants 权威实现）。
- :mod:`webui.app`：FastAPI 服务（``python -m webui.app --port 8788``）——上传 →
  后台跑 ``pfcore make`` → 状态轮询 → 二维码 + 质检报告链接；单页在 ``webui/static``。
- :mod:`webui.selftest`：httpx 端到端自验收（``python -m webui.selftest``，exit 0 为过）。
"""
