#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_output.py -- Claude Code PostToolUse hook: artifact file validation.

Reads one JSON object from stdin (Claude Code hook protocol). Recognized fields:
  {"hook_event_name": "PostToolUse", "tool_name": "Write",
   "file_path": "..."}                       # simplified schema (this oracle)
  {"tool_input": {"file_path": "..."}}       # real Claude Code schema (also honored)

Checks, in order (first failure wins):
  1. file_path present; file exists and is a regular file
  2. file is non-empty
  3. text-class files: bytes strictly decodable as UTF-8
  4. .docx: openable by python-docx /  .pptx: openable by python-pptx

Exit-code semantics (Claude Code hook contract):
  exit 0  -> pass
  exit 2  -> block; stderr reason is fed back to the model
  (other non-zero codes mean "non-blocking error" in Claude Code; unused here)

Design rule: no file_path in payload -> nothing to validate -> exit 0 (with a
stderr note), so this hook can safely sit on a matcher like "Write|Edit".
"""
import json
import sys
from pathlib import Path

# Piped stdout/stderr on Windows defaults to the locale codepage; force UTF-8
# so non-ASCII paths/messages never crash the hook itself.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def fail(msg: str) -> None:
    print("[validate_output] FAIL: " + msg, file=sys.stderr)
    sys.exit(2)


def get_file_path(payload: dict):
    """Accept both top-level file_path and tool_input.file_path."""
    fp = payload.get("file_path")
    if not fp:
        ti = payload.get("tool_input") or {}
        if isinstance(ti, dict):
            fp = ti.get("file_path")
    return fp


def check_docx(path: Path) -> None:
    try:
        from docx import Document
    except ImportError as e:
        fail("python-docx not installed, cannot validate .docx (%s)" % e)
    try:
        doc = Document(str(path))
        _ = len(doc.paragraphs)  # force package parse
    except Exception as e:
        fail(".docx cannot be opened by python-docx: %s: %s" % (type(e).__name__, e))


def check_pptx(path: Path) -> None:
    try:
        from pptx import Presentation
    except ImportError as e:
        fail("python-pptx not installed, cannot validate .pptx (%s)" % e)
    try:
        prs = Presentation(str(path))
        _ = len(prs.slides)  # force package parse
    except Exception as e:
        fail(".pptx cannot be opened by python-pptx: %s: %s" % (type(e).__name__, e))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        fail("stdin is not valid JSON: %s" % e)
    if not isinstance(payload, dict):
        fail("stdin JSON must be an object")

    tool_name = payload.get("tool_name", "?")
    fp = get_file_path(payload)
    if not fp:
        print("[validate_output] no file_path in payload (tool_name=%s); "
              "nothing to validate, exit 0" % tool_name, file=sys.stderr)
        sys.exit(0)

    path = Path(fp)
    if not path.exists():
        fail("file does not exist: %s (tool_name=%s)" % (path, tool_name))
    if not path.is_file():
        fail("path is not a regular file: %s" % path)

    size = path.stat().st_size
    if size == 0:
        fail("file is empty (0 bytes): %s" % path)

    ext = path.suffix.lower()
    if ext == ".docx":
        check_docx(path)
    elif ext == ".pptx":
        check_pptx(path)
    else:
        data = path.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            fail("not decodable as UTF-8 (%d bytes; bad byte range %d:%s)"
                 % (size, e.start, e.end))

    # Diagnostics go to stderr only; stdout stays empty in both outcomes so the
    # hook never injects unexpected content into the model context.
    print("[validate_output] OK %s (%d bytes, ext=%s)" % (path.name, size, ext or "none"),
          file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
