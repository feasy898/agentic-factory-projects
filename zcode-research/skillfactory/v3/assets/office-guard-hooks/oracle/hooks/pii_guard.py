#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pii_guard.py -- Claude Code PostToolUse hook: PII regex scan for text artifacts.

Reads one JSON object from stdin; file to scan resolved from
payload["file_path"] or payload["tool_input"]["file_path"].

Rules (regex only, digit-boundary lookarounds to avoid in-run false hits):
  CN mobile phone : (?<!\\d)1[3-9]\\d{9}(?!\\d)
  CN 18-digit ID  : (?<!\\d)\\d{17}[\\dXx](?!\\d)

Exit-code semantics (Claude Code hook contract):
  exit 0  -> no hit (or nothing scannable)
  exit 2  -> block; stderr lists each hit as "<path>:<line>: [kind] <masked>"
             so line numbers are reported without echoing full PII back.

Scope decisions (deliberate, keep single responsibility):
  - .docx/.pptx/.xlsx/.zip binaries are skipped (exit 0), this hook only
    scans text-class files; structural problems belong to validate_output.
  - non-UTF-8-decodable text -> not scannable, warn on stderr, exit 0.
  - missing file_path / missing file -> nothing to scan, exit 0 (existence
    checks belong to validate_output).
"""
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".html", ".htm",
    ".xml", ".yaml", ".yml", ".toml", ".ini", ".log", ".py", ".js", ".ts",
    ".rst", ".tex", ".srt", ".vtt",
}
BINARY_SKIP_EXTS = {".docx", ".pptx", ".xlsx", ".zip", ".pdf", ".png",
                    ".jpg", ".jpeg", ".gif", ".exe", ".dll"}


def mask_phone(m: str) -> str:
    return m[:3] + "****" + m[-4:]


def mask_id(m: str) -> str:
    return m[:4] + "*" * (len(m) - 8) + m[-4:]


def get_file_path(payload: dict):
    fp = payload.get("file_path")
    if not fp:
        ti = payload.get("tool_input") or {}
        if isinstance(ti, dict):
            fp = ti.get("file_path")
    return fp


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print("[pii_guard] FAIL: stdin is not valid JSON: %s" % e, file=sys.stderr)
        sys.exit(2)
    if not isinstance(payload, dict):
        print("[pii_guard] FAIL: stdin JSON must be an object", file=sys.stderr)
        sys.exit(2)

    fp = get_file_path(payload)
    if not fp:
        print("[pii_guard] no file_path in payload; nothing to scan, exit 0",
              file=sys.stderr)
        sys.exit(0)
    path = Path(fp)
    if not path.is_file():
        print("[pii_guard] path not a scannable file (%s); nothing to scan, exit 0"
              % path, file=sys.stderr)
        sys.exit(0)

    ext = path.suffix.lower()
    if ext in BINARY_SKIP_EXTS:
        print("[pii_guard] skipped binary/office file %s, exit 0" % path.name,
              file=sys.stderr)
        sys.exit(0)

    data = path.read_bytes()
    if not data:
        print("[pii_guard] empty file %s; nothing to scan, exit 0" % path.name,
              file=sys.stderr)
        sys.exit(0)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        print("[pii_guard] WARNING: %s is not UTF-8 text (byte %d); "
              "not scanned, exit 0 (structure issues are validate_output's job)"
              % (path.name, e.start), file=sys.stderr)
        sys.exit(0)

    hits = []  # (line_no, kind, original, masked)
    for line_no, line in enumerate(text.splitlines(), 1):
        for m in PHONE_RE.finditer(line):
            hits.append((line_no, "phone", m.group(0), mask_phone(m.group(0))))
        for m in ID_RE.finditer(line):
            hits.append((line_no, "cn-id", m.group(0), mask_id(m.group(0))))

    if hits:
        hits.sort(key=lambda h: (h[0], h[1]))
        print("[pii_guard] BLOCK: %d PII hit(s) in %s:"
              % (len(hits), path), file=sys.stderr)
        for line_no, kind, _orig, masked in hits:
            print("  %s:%d: [%s] %s" % (path, line_no, kind, masked),
                  file=sys.stderr)
        sys.exit(2)

    print("[pii_guard] OK %s: no PII hits (%d lines scanned)"
          % (path.name, text.count("\n") + (0 if text.endswith("\n") or not text else 1)),
          file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
