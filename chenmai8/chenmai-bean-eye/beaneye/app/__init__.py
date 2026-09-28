"""BeanEye · 应用壳（M13，beaneye.app）。

FastAPI 端点 + 单页演示 UI + 全链路管线装配：

- :func:`create_app` —— 应用工厂（``data_root`` / 检测组件注入 / 降级探测）；
- :func:`run` —— 本机起服务（``python -m beaneye.app``，默认 127.0.0.1:8600）；
- :mod:`beaneye.app.pipeline` —— 整盘图 → 定级 → 护照 的全链路装配；
- :mod:`beaneye.app.components` —— SegModel/ClsModel 装配与**显式降级**
  （识别模型缺位时空检出继续全链路，响应注明 degraded）；
- :mod:`beaneye.app.store` —— 进程内作业队列（ThreadPoolExecutor）与结果存储。

识别模型（``beaneye.segment`` / ``beaneye.classify``）与合成引擎
（``beaneye.synth``）尚未落地：缺省装配走显式降级路径，端到端用上传的
合成整盘图或内置确定性模拟源驱动（作业与结果均注明降级阶段与原因）。
"""

from beaneye.app.components import (
    ComponentBox,
    ComponentError,
    Components,
    NullClsModel,
    NullSegModel,
    build_components,
)
from beaneye.app.pipeline import (
    PipelineOutcome,
    PipelineRequest,
    PipelineStageError,
    STAGE_ORDER,
    run_pipeline,
)
from beaneye.app.store import AppStore, JobRecord, ResultRecord

__all__ = [
    "create_app",
    "run",
    "DEFAULT_DATA_ROOT",
    "DEMO_HTML_PATH",
    "ComponentBox",
    "ComponentError",
    "Components",
    "NullSegModel",
    "NullClsModel",
    "build_components",
    "PipelineRequest",
    "PipelineOutcome",
    "PipelineStageError",
    "STAGE_ORDER",
    "run_pipeline",
    "AppStore",
    "JobRecord",
    "ResultRecord",
]


def create_app(*, data_root=None, segment=None, classify=None, agent=None,
               allow_probe: bool = True, langs=("zh", "en", "vi"), max_workers: int = 2):
    """FastAPI 应用工厂（薄转发到 :mod:`beaneye.app.main`，避免包导入即拉起 Web 栈）。"""
    from beaneye.app.main import create_app as _create

    return _create(
        data_root=data_root,
        segment=segment,
        classify=classify,
        agent=agent,
        allow_probe=allow_probe,
        langs=langs,
        max_workers=max_workers,
    )


def run(*, host: str = "127.0.0.1", port: int = 8600, data_root=None, **kwargs):
    """本机起服务的演示入口。"""
    from beaneye.app.main import run as _run

    _run(host=host, port=port, data_root=data_root, **kwargs)


def main() -> None:  # python -m beaneye.app
    run()


if __name__ == "__main__":
    main()
