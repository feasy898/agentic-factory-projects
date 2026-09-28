"""文件通道：解析、公开前体检、彻底删除式导出、OCR。

文本层（T3.1 权威实现）：:func:`filechannel.inspect.inspect_bytes` —— 解析
（:mod:`filechannel.parsers`）→ detect 全套 → :class:`filechannel.models.FileReport`
（逐 Finding 带位置：段落号/单元格坐标/页码+bbox）。
"""
from filechannel.errors import (
    DocumentParseError,
    FileChannelError,
    FileTooLargeError,
    UnsupportedFileType,
)
from filechannel.inspect import detect_all, inspect_bytes, risk_level_of
from filechannel.models import FileFinding, FileKind, FileReport, RiskLevel
from filechannel.parsers import ParsedDocument, Segment, parse_any

__all__ = [
    "DocumentParseError",
    "FileChannelError",
    "FileFinding",
    "FileKind",
    "FileReport",
    "FileTooLargeError",
    "ParsedDocument",
    "RiskLevel",
    "Segment",
    "UnsupportedFileType",
    "detect_all",
    "inspect_bytes",
    "parse_any",
    "risk_level_of",
]
