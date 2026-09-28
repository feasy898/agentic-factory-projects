"""全检测层组合：规则层 + 语义层注入检测（T4.2）。

网关主链路（:mod:`gateway.pipeline` 的消息段/出站辅助面）与 ``/internal/detect``
调试面统一经 :func:`detect_full` 取全检测面结果——语义层 INJECTION 命中与规则层
findings 同表合并（span 升序），由调用方按请求统一编 fid 后进入 mask/route：
INJECTION 为 BLOCK_FLAG，脱敏面零参与，路由侧被 ``decide`` R2 原生拦截。

文件通道（filechannel）继续只走规则层 ``detect``——文档体检的注入语义属后续
任务，本模块不改变其行为。
"""
from __future__ import annotations

from recognizers.models import Finding
from recognizers.rule.detect import detect
from recognizers.semantic.adapter import get_semantic_adapter


def detect_full(text: str) -> list[Finding]:
    """规则层 + 语义层合并结果（span 升序）；fid 恒空串，由调用方按请求编号。"""
    findings = detect(text)
    findings.extend(get_semantic_adapter().detect(text))
    findings.sort(key=lambda f: (f.start, f.end, f.type.value))
    return findings
