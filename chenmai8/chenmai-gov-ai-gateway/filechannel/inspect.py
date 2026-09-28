"""公开前体检（M6 · T3.1）：解析 → detect 全套 → FileReport（开发指令 §5.5）。

流水线（``inspect_bytes``）：

1. 大小闸：``> FILE_SIZE_MAX_BYTES``（50MB）→ :class:`FileTooLargeError`（§6 M6）；
2. 分发解析：:func:`filechannel.parsers.parse_any` → 带定位文本段；
3. **detect 全套**：逐段过规则层 ``recognizers.rule.detect``（全类别：结构化号码
   + 校验位 / 词面类 / PERSON v0）+ NER 适配器（§6 M2 接口位，P0 恒空、D4 模型
   接入后零改动生效）；语义审核（``SemanticAdapter.moderate``）不产出 Finding，
   不进 FileReport（§5.5 形状无该位面）；
4. 装配：fid 全文自增（``f_0001`` 起，§5.1「请求内自增」的文件内口径）；pdf 命中
   回填 span 的 charbox 并集 bbox，docx/xlsx 回填 location；
5. 风险分级（§5.5 字面口径）：
   - HIGH：含非白名单 SENSITIVE_ATTR，或非白名单 ID_CARD+BANK_CARD ≥ 批量线
     （config.app.thresholds.batch_pii_to_govcloud，与 §5.2「批量名单」同源）；
   - MID：含其它非白名单结构化 PII（§5.2 单个结构化 PII 名单，含 PERSON/ADDRESS）；
   - LOW：有命中但均不属上述（白名单/词面类/文号等）；NONE：零命中。
   密级标识/工作秘密属 BLOCK/ROUTE 语义（§5.1.1），不进本分级阶梯，但仍作为
   finding 呈现在报告与 summary 中。
"""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from common.config import load_app_config
from evals import thresholds as th
from filechannel.errors import FileTooLargeError, UnsupportedFileType
from filechannel.models import FileFinding, FileReport, RiskLevel
from filechannel.parsers import parse_any
from recognizers.models import EntityClass, Finding
from recognizers.ner.adapter import get_ner_adapter
from recognizers.rule.detect import detect

#: 结构化 PII（§5.2 单个结构化 PII 路由名单；MID 分级的值域）
STRUCTURED_PII_TYPES: frozenset[EntityClass] = frozenset({
    EntityClass.ID_CARD, EntityClass.PHONE_MOBILE, EntityClass.PHONE_LANDLINE,
    EntityClass.BANK_CARD, EntityClass.USCC, EntityClass.PLATE,
    EntityClass.EMAIL, EntityClass.IP, EntityClass.SECRET_KEY,
    EntityClass.DATE_BIRTH, EntityClass.PERSON, EntityClass.ADDRESS,
})

#: 批量名单判定类别（§5.2「ID_CARD/BANK_CARD 同请求 ≥3 个」）
BATCH_PII_TYPES: tuple[EntityClass, ...] = (EntityClass.ID_CARD, EntityClass.BANK_CARD)


def detect_all(text: str) -> list[Finding]:
    """detect 全套：规则层 + NER 适配器（P0 恒空；接口位，D4 零改动接入）。"""
    findings = list(detect(text))
    findings.extend(get_ner_adapter().detect(text))
    return findings


def _batch_threshold() -> int:
    """批量线：config.app.thresholds.batch_pii_to_govcloud（缺省 3）。"""
    try:
        return int(load_app_config().thresholds.batch_pii_to_govcloud)
    except Exception:  # noqa: BLE001 — 配置缺失时回退契约默认，不阻断体检
        return 3


def risk_level_of(file_findings: list[FileFinding],
                  batch_threshold: int | None = None) -> RiskLevel:
    """§5.5 风险分级（纯函数；白名单命中不参与分级）。"""
    if not file_findings:
        return "NONE"
    real = [ff for ff in file_findings if not ff.finding.whitelisted]
    if not real:
        return "LOW"  # 仅白名单/已标记豁免命中
    threshold = batch_threshold if batch_threshold is not None else _batch_threshold()
    batch = sum(1 for ff in real if ff.finding.type in BATCH_PII_TYPES)
    if any(ff.finding.type is EntityClass.SENSITIVE_ATTR for ff in real) \
            or batch >= threshold:
        return "HIGH"
    if any(ff.finding.type in STRUCTURED_PII_TYPES for ff in real):
        return "MID"
    return "LOW"


def inspect_bytes(filename: str, data: bytes, *,
                  batch_threshold: int | None = None) -> FileReport:
    """文件字节 → FileReport（§5.5；解析/检测失败抛 filechannel.errors 语义异常）。"""
    if len(data) > th.FILE_SIZE_MAX_BYTES:
        raise FileTooLargeError(
            f"file too large: {len(data)} bytes > {th.FILE_SIZE_MAX_BYTES} (≤50MB)")
    if Path(filename).suffix.lower() not in ("docx", ".docx", "xlsx", ".xlsx", "pdf", ".pdf"):
        raise UnsupportedFileType(
            f"unsupported file type: {Path(filename).suffix or '<none>'}")

    parsed = parse_any(filename, data)
    file_findings: list[FileFinding] = []
    counter = 0
    for seg in parsed.segments:
        for found in detect_all(seg.text):
            counter += 1
            found.fid = f"f_{counter:04d}"  # 文件内自增（§5.1）
            bbox = None
            if parsed.text_layer is not None:
                bbox = parsed.text_layer.union(seg.page, found.start, found.end)
            file_findings.append(FileFinding(
                page=seg.page, bbox=bbox, location=seg.location, finding=found))

    summary = Counter(ff.finding.type.value for ff in file_findings)
    sha = hashlib.sha256(data).hexdigest()
    return FileReport(
        file_id=f"file_{sha[:16]}",
        filename=filename,
        sha256=sha,
        kind=parsed.kind,
        pages=parsed.pages,
        findings=file_findings,
        risk_level=risk_level_of(file_findings, batch_threshold),
        summary=dict(sorted(summary.items())),
    )
