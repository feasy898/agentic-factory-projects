#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_output.py -- PostToolUse 产物落盘校验 hook（fail-closed）。

CLI 契约（contract.md §2 / spec.md §2、§3.1）：
    echo '<JSON payload>' | python hooks/validate_output.py
  - stdin   : 单个 JSON 对象；file_path 双 schema 兼容
              （顶层 file_path 优先，回落 tool_input.file_path）
  - stdout  : 恒为空（任何结局都不向模型上下文注入内容）
  - stderr  : 诊断 / 阻断原因，回传模型
  - exit 0  = 通过（或无事可做，放行）；exit 2 = 阻断
  - 任何输入下都优雅退出，绝不抛 Python Traceback

判定顺序（首条命中即终局，spec §3.1）：
    非法 JSON -> 非对象 -> 无 file_path -> 不存在 -> 非 regular file
    -> 0 字节 -> .docx/.pptx 打不开 -> 非办公后缀非严格 UTF-8 -> OK
"""
import json
import sys
from pathlib import Path

DOCX_SUFFIXES = {".docx"}
PPTX_SUFFIXES = {".pptx"}

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def emit_and_exit(code, message):
    """诊断只走 stderr；stdout 恒为空。"""
    print(message, file=sys.stderr)
    sys.exit(code)


def extract_file_path(payload):
    """顶层 file_path 优先，回落 tool_input.file_path（spec §2）。"""
    candidate = payload.get("file_path")
    if isinstance(candidate, str) and candidate.strip():
        return candidate
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        nested = tool_input.get("file_path")
        if isinstance(nested, str) and nested.strip():
            return nested
    return None


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        emit_and_exit(2, "validate_output: hook payload is not valid JSON; blocking (fail-closed).")
    if not isinstance(payload, dict):
        emit_and_exit(2, "validate_output: hook payload must be an object; blocking (fail-closed).")

    file_path = extract_file_path(payload)
    if file_path is None:
        emit_and_exit(0, "validate_output: no file_path in payload; nothing to validate.")

    path = Path(file_path)
    if not path.exists():
        emit_and_exit(2, "validate_output: file does not exist: %s" % file_path)
    if not path.is_file():
        emit_and_exit(2, "validate_output: path is not a regular file: %s" % file_path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        emit_and_exit(2, "validate_output: cannot stat %s: %s" % (file_path, exc))
    if size == 0:
        emit_and_exit(2, "validate_output: file is empty (0 bytes): %s" % file_path)

    suffix = path.suffix.lower()
    if suffix in DOCX_SUFFIXES:
        try:
            from docx import Document  # python-docx
        except ImportError:
            emit_and_exit(2, "validate_output: python-docx is not installed; cannot verify .docx: %s" % file_path)
        try:
            Document(str(path))
        except Exception as exc:
            emit_and_exit(2, "validate_output: .docx cannot be opened by python-docx (%s: %s): %s"
                          % (type(exc).__name__, exc, file_path))
    elif suffix in PPTX_SUFFIXES:
        try:
            from pptx import Presentation  # python-pptx
        except ImportError:
            emit_and_exit(2, "validate_output: python-pptx is not installed; cannot verify .pptx: %s" % file_path)
        try:
            Presentation(str(path))
        except Exception as exc:
            emit_and_exit(2, "validate_output: .pptx cannot be opened by python-pptx (%s: %s): %s"
                          % (type(exc).__name__, exc, file_path))
    else:
        try:
            data = path.read_bytes()
        except OSError as exc:
            emit_and_exit(2, "validate_output: cannot read %s: %s" % (file_path, exc))
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            emit_and_exit(2, "validate_output: file is not decodable as UTF-8 (%s): %s" % (exc, file_path))

    emit_and_exit(0, "validate_output: OK %s (%d bytes)" % (file_path, size))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # 兜底：任何意外都以 exit 2 优雅阻断（fail-closed），绝不抛 Traceback
        print("validate_output: unexpected error %s: %s; blocking (fail-closed)."
              % (type(exc).__name__, exc), file=sys.stderr)
        sys.exit(2)
