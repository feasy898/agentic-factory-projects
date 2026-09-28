"""NER 适配器（开发指令 §6 M2）：人名/住址等非结构化实体的模型识别入口。

P0 口径（铁律 D：MVP 识别只做规则层）：**无模型时空输出**——``detect`` 恒返回
空列表，调用方按「无 NER 命中」降级处理；接口形状（``detect(text) -> list[Finding]``）
与规则层 ``detect`` 一致，D4 训练落地后在本文件内替换为 ONNX 推理实现，
上层（gateway/filechannel）零改动。

模型挂载点（预留）：``model_path`` 指向 ONNX 模型目录（见 training-plan），
P0 仅保存路径、不做加载——有路径仍返回空列表并记一条 debug 日志，
避免「以为有模型实则没生效」的静默偏差（差异必须显式）。
"""
from __future__ import annotations

from common.logs import get_logger
from recognizers.models import Finding

log = get_logger(__name__)


class NerAdapter:
    """NER 识别适配器（P0：恒空实现，预留 ONNX 模型路径）。"""

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path
        if model_path:
            # P0 无推理内核：显式声明未加载，而不是假装可用
            log.debug("ner_adapter.model_path_ignored_p0", extra={"model_path": model_path})

    def detect(self, text: str) -> list[Finding]:
        """识别人名/住址等实体（P0：恒返回空列表）。"""
        return []


_ADAPTER: NerAdapter | None = None


def get_ner_adapter(model_path: str | None = None) -> NerAdapter:
    """进程级单例（首次以给定模型路径创建，其后忽略路径参数）。"""
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = NerAdapter(model_path)
    return _ADAPTER
