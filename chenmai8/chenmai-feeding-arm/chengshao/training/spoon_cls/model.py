"""勺上分类器模型定义（延后资产；torch 环境）。

MobileNetV3-Small 预训练干 + 2 层 MLP 头（training-plan §3）。接口：
``build_model(cfg) -> nn.Module``，forward 输入 ``(B,3,224,224)``、输出
has_food 概率（sigmoid）——与 export_onnx.py 的导出契约一致。

真实训练循环在 GPU 机按 runbook_gpu.md 驱动（本仓库只冻结模型结构与
导出接口；开发指令 §10.3：本机禁止真实训练）。
"""

from __future__ import annotations

import torch
from torch import nn


def build_model(cfg: dict) -> nn.Module:
    """由 config/spoon_cls.json 的 model 段构建分类器（输出 = has_food 概率）。"""
    import torchvision

    m = cfg["model"]
    if m["backbone"] != "mobilenet_v3_small":
        raise ValueError(f"未声明的 backbone：{m['backbone']!r}")
    weights = (
        torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
        if m.get("pretrained", True) else None
    )
    backbone = torchvision.models.mobilenet_v3_small(weights=weights)
    in_feat = backbone.classifier[-1].in_features
    backbone.classifier = nn.Identity()
    hidden = int(m["head_hidden"])
    dropout = float(m.get("dropout", 0.2))
    head = nn.Sequential(
        nn.Linear(in_feat, hidden), nn.ReLU(inplace=True), nn.Dropout(dropout),
        nn.Linear(hidden, 1),
    )
    return nn.Sequential(backbone, head, nn.Sigmoid())


def decision(prob: float, threshold: float) -> int:
    """has_food 判定（阈值向漏检偏置：threshold < 0.5，宁可重舀）。"""
    return 1 if prob >= threshold else 0
