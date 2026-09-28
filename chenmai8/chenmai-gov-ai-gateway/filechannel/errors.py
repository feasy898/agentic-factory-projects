"""文件通道异常层次（开发指令 §6 M6「大小限制 ≤50MB，超限报错」等边界）。

HTTP 层（/v1/files/*，后续任务接线）按类型映射：
- :class:`FileTooLargeError`      → 413（FILE_SIZE_MAX_BYTES，阈值在 evals.thresholds）；
- :class:`UnsupportedFileType`    → 400（扩展名不在 docx/xlsx/pdf 支持面）；
- :class:`DocumentParseError`     → 422（文件损坏/畸形，解析库抛错——绝不 500 崩网关，
  风险表 §11.8「畸形输入打崩网关」的文件侧防线）。
"""
from __future__ import annotations


class FileChannelError(ValueError):
    """文件通道异常基类（ValueError 子类，便于调用方统一捕获）。"""


class FileTooLargeError(FileChannelError):
    """文件超过大小上限（§6 M6：≤50MB）。"""


class UnsupportedFileType(FileChannelError):
    """扩展名不属于文本层支持面（docx/xlsx/pdf）。"""


class DocumentParseError(FileChannelError):
    """文档损坏或畸形，解析失败（原始异常挂在 ``__cause__`` 供日志）。"""
