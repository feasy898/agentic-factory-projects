#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pii_guard.py -- PostToolUse 文本产物 PII 扫描 hook（对不可扫对象 fail-open）。

CLI 契约（contract.md §2 / spec.md §2、§3.2）：
    echo '<JSON payload>' | python hooks/pii_guard.py
  - stdin   : 单个 JSON 对象；file_path 双 schema 兼容
              （顶层 file_path 优先，回落 tool_input.file_path）
  - stdout  : 恒为空；stderr : 诊断 / 阻断原因
  - exit 0  = 放行（含一切"不可扫"情形）；exit 2 = 命中 PII（或 payload 非法）
  - 任何输入下都优雅退出，绝不抛 Python Traceback

判定顺序（spec §3.2 表序）：
    非法/非对象 JSON -> 无 file_path -> 缺失/非 regular file -> 二进制跳过后缀
    -> 0 字节 -> 非 UTF-8 -> 逐行正则扫描 -> 命中 exit 2 / 干净 exit 0

PII 口径（spec R2.7/R2.9）：
    手机   (?<!\\d)1[3-9]\\d{9}(?!\\d)      脱敏 = 前3位 + **** + 后4位
    身份证 (?<!\\d)\\d{17}[\\dXx](?!\\d)   脱敏 = 前4位 + *(len-8) + 后4位
    数字边界 lookaround 保证 18 位身份证不会被手机号规则二次命中；
    命中输出按（行号, 类别, 列位置）排序，且绝不回显完整 PII。
"""
import json
import re
import sys
from pathlib import Path

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
CN_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

# 二进制 / office 跳过集合（spec R2.4）：结构问题归 validate_output，这里一律放行
SKIP_SUFFIXES = {".docx", ".pptx", ".xlsx", ".zip", ".pdf",
                 ".png", ".jpg", ".jpeg", ".gif", ".exe", ".dll"}

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


def mask_phone(digits):
    """手机号脱敏：前 3 位 + **** + 后 4 位。"""
    return digits[:3] + "****" + digits[-4:]


def mask_cn_id(digits):
    """身份证脱敏：前 4 位 + *×(len-8) + 后 4 位。"""
    return digits[:4] + "*" * (len(digits) - 8) + digits[-4:]


def scan(text):
    """逐行扫描，返回 [(行号, 类别, 起始列, 脱敏串)]，按（行号, 类别, 列）排序。"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in PHONE_RE.finditer(line):
            hits.append((lineno, "phone", m.start(), mask_phone(m.group(0))))
        for m in CN_ID_RE.finditer(line):
            hits.append((lineno, "cn-id", m.start(), mask_cn_id(m.group(0))))
    hits.sort(key=lambda h: (h[0], h[1], h[2]))
    return hits


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        emit_and_exit(2, "pii_guard: FAIL: hook payload is not valid JSON; blocking.")
    if not isinstance(payload, dict):
        emit_and_exit(2, "pii_guard: FAIL: hook payload must be an object; blocking.")

    file_path = extract_file_path(payload)
    if file_path is None:
        emit_and_exit(0, "pii_guard: no file_path in payload; nothing to scan.")

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        emit_and_exit(0, "pii_guard: not a scannable file: %s (existence/structure belong to validate_output)" % file_path)

    if path.suffix.lower() in SKIP_SUFFIXES:
        emit_and_exit(0, "pii_guard: skipped (binary/office format): %s" % file_path)

    try:
        size = path.stat().st_size
    except OSError:
        emit_and_exit(0, "pii_guard: not a scannable file (stat failed): %s" % file_path)
    if size == 0:
        emit_and_exit(0, "pii_guard: empty file, nothing to scan: %s" % file_path)

    try:
        data = path.read_bytes()
    except OSError:
        emit_and_exit(0, "pii_guard: WARNING: cannot read %s; not scanned." % file_path)
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        emit_and_exit(0, "pii_guard: WARNING: %s is not decodable as UTF-8; not scanned "
                         "(encoding issues belong to validate_output)" % file_path)

    hits = scan(text)
    if hits:
        for lineno, category, _start, masked in hits:
            print("  %s:%d: [%s] %s" % (file_path, lineno, category, masked), file=sys.stderr)
        emit_and_exit(2, "pii_guard: FAIL: %d PII hit(s) in %s; blocking." % (len(hits), file_path))

    emit_and_exit(0, "pii_guard: OK: no PII detected in %s." % file_path)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # 兜底：护栏自身异常时 fail-open 放行并说明，绝不抛 Traceback
        print("pii_guard: WARNING: unexpected error %s: %s; failing open (not scanned)."
              % (type(exc).__name__, exc), file=sys.stderr)
        sys.exit(0)
