#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — mcp-office-pack 配置校验器（oracle 自检）

校验 mcp.office.json：
  1. json_valid          JSON 合法可解析
  2. fields_complete     每条字段齐全（name 键/type/command 或 url/args/description/enabled/scenario/catalog{record_url,form}/doc）
  3. names_unique        name 唯一且符合命名规范
  4. no_real_secrets     密钥占位符未被真值替换（正则扫描全文 + env 值）
  5. placeholders_intact secret_env 声明的变量保持 ${VAR} 占位形态
  6. docs_exist          每个 name 在 docs/ 有对应手册，且手册含四个必备小节与目录实录 URL
  7. artifacts_exist     配置文件/docs 目录/out 目录在盘

产出 out/validate.json（全绿 = summary.all_green == true）。

用法：
  python validate.py                       # 默认校验同目录 mcp.office.json
  python validate.py --config <path> --out <path>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent

# ---------- 密钥真值识别正则（命中任意一条即判真值泄漏） ----------
SECRET_PATTERNS: list[tuple[str, str]] = [
    ("tavily_api_key",            r"tvly-[A-Za-z0-9_\-]{16,}"),
    ("openai_style_sk",           r"sk-[A-Za-z0-9_\-]{20,}"),
    ("github_token",              r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("github_fine_grained_pat",   r"github_pat_[A-Za-z0-9_]{20,}"),
    ("google_api_key",            r"AIza[0-9A-Za-z_\-]{30,}"),
    ("google_oauth_client_secret",r"GOCSPX-[A-Za-z0-9_\-]{8,}"),
    ("google_access_token",       r"ya29\."),
    ("aws_access_key_id",         r"AKIA[0-9A-Z]{16}"),
    ("slack_token",               r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    ("hex_secret_32",             r"\b[a-fA-F0-9]{32,}\b"),
    ("opaque_b64_token_43",       r"(?<![A-Za-z0-9_\-])[A-Za-z0-9_\-]{43,}(?![A-Za-z0-9_\-])"),
]

PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z][A-Z0-9_]*\}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9\-]{1,63}$")
DOC_REQUIRED_SECTIONS = ("安装前提", "配置步骤", "常用调用", "注意事项")

REQUIRED_ENTRY_FIELDS = ("type", "description", "enabled", "scenario", "doc")
REQUIRED_CATALOG_FIELDS = ("record_url", "form")


def check_json_valid(raw: bytes) -> tuple[bool, str, dict]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"JSON 解析失败: {exc}", {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        return False, "缺少非空 mcpServers 对象", {}
    return True, f"JSON 合法，mcpServers 共 {len(servers)} 条", servers


def check_fields_complete(servers: dict) -> tuple[bool, list[str]]:
    problems: list[str] = []
    for name, entry in servers.items():
        for field in REQUIRED_ENTRY_FIELDS:
            if field not in entry:
                problems.append(f"[{name}] 缺字段 {field}")
        has_cmd = isinstance(entry.get("command"), str) and entry["command"].strip()
        has_url = isinstance(entry.get("url"), str) and entry["url"].strip()
        etype = entry.get("type")
        if etype == "stdio" and not has_cmd:
            problems.append(f"[{name}] type=stdio 但缺 command")
        if etype == "http" and not has_url:
            problems.append(f"[{name}] type=http 但缺 url")
        if etype not in ("stdio", "http"):
            problems.append(f"[{name}] type 必须为 stdio 或 http，实际 {etype!r}")
        if etype == "stdio" and not isinstance(entry.get("args"), list):
            problems.append(f"[{name}] 缺 args 列表")
        if not isinstance(entry.get("env"), dict):
            problems.append(f"[{name}] 缺 env 对象")
        if not isinstance(entry.get("secret_env"), list):
            problems.append(f"[{name}] 缺 secret_env 列表（无密钥也要给空列表）")
        catalog = entry.get("catalog")
        if not isinstance(catalog, dict):
            problems.append(f"[{name}] 缺 catalog 对象")
        else:
            for field in REQUIRED_CATALOG_FIELDS:
                if not str(catalog.get(field, "")).strip():
                    problems.append(f"[{name}] catalog 缺 {field}")
            if not str(catalog.get("record_url", "")).startswith(("http://", "https://")):
                problems.append(f"[{name}] catalog.record_url 不是 URL")
    return (not problems), problems


def check_names_unique(servers: dict) -> tuple[bool, list[str]]:
    problems: list[str] = []
    seen: dict[str, int] = {}
    for name in servers:
        seen[name] = seen.get(name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            problems.append(f"name 重复: {name} ×{count}")
        if not NAME_RE.match(name):
            problems.append(f"name 不合规范 ^[a-z][a-z0-9-]$: {name}")
    return (not problems), problems


def scan_secrets(text: str, where: str) -> list[str]:
    hits: list[str] = []
    for label, pattern in SECRET_PATTERNS:
        for match in re.finditer(pattern, text):
            hits.append(f"{where}: 疑似真值密钥（{label}）于 …{match.group(0)[:12]}…")
    return hits


def check_no_real_secrets(servers: dict, raw_text: str) -> tuple[bool, list[str]]:
    hits = scan_secrets(raw_text, "全文")
    for name, entry in servers.items():
        env = entry.get("env", {})
        if isinstance(env, dict):
            for key, value in env.items():
                if isinstance(value, str) and value.strip():
                    if PLACEHOLDER_RE.match(value.strip()):
                        continue
                    hits.extend(scan_secrets(value, f"[{name}].env.{key}"))
    return (not hits), hits


def check_placeholders_intact(servers: dict) -> tuple[bool, list[str]]:
    problems: list[str] = []
    for name, entry in servers.items():
        env = entry.get("env", {})
        for key in entry.get("secret_env", []):
            value = env.get(key)
            if value is None:
                problems.append(f"[{name}] secret_env 声明了 {key} 但 env 无此键")
            elif not PLACEHOLDER_RE.match(str(value).strip()):
                problems.append(
                    f"[{name}].env.{key} 应保持占位符 ${{{key}}} 形态，实际 {str(value)[:16]}…"
                )
    return (not problems), problems


def check_docs_exist(servers: dict, docs_dir: Path) -> tuple[bool, list[str]]:
    problems: list[str] = []
    for name, entry in servers.items():
        doc_rel = entry.get("doc", f"docs/{name}.md")
        doc_path = (BASE / doc_rel).resolve()
        if not doc_path.is_file():
            problems.append(f"[{name}] 手册缺失: {doc_rel}")
            continue
        text = doc_path.read_text(encoding="utf-8")
        if len(text.strip()) < 200:
            problems.append(f"[{name}] 手册过短（<200 字符）: {doc_rel}")
        for section in DOC_REQUIRED_SECTIONS:
            if section not in text:
                problems.append(f"[{name}] 手册缺必备小节『{section}』: {doc_rel}")
        record_url = entry.get("catalog", {}).get("record_url", "")
        if record_url and record_url not in text:
            problems.append(f"[{name}] 手册未含目录实录 URL: {doc_rel}")
    return (not problems), problems


def check_artifacts(config_path: Path, docs_dir: Path, out_dir: Path) -> tuple[bool, list[str]]:
    problems: list[str] = []
    if not config_path.is_file():
        problems.append(f"配置文件不在盘: {config_path}")
    if not docs_dir.is_dir():
        problems.append(f"docs 目录不在盘: {docs_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    probe = out_dir / ".write_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    return (not problems), problems


def main() -> int:
    parser = argparse.ArgumentParser(description="mcp-office-pack 配置校验器")
    parser.add_argument("--config", default=str(BASE / "mcp.office.json"))
    parser.add_argument("--out", default=str(BASE / "out" / "validate.json"))
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    out_path = Path(args.out).resolve()
    docs_dir = config_path.parent / "docs"
    out_dir = out_path.parent
    checks: list[dict] = []

    def add(cid: str, name: str, ok: bool, problems: list[str], detail_ok: str) -> None:
        checks.append({
            "id": cid,
            "name": name,
            "pass": bool(ok),
            "detail": detail_ok if ok else "；".join(problems),
            "problems": problems,
        })

    raw_bytes = config_path.read_bytes() if config_path.is_file() else b""
    raw_text = raw_bytes.decode("utf-8", errors="replace")

    ok, detail, servers = check_json_valid(raw_bytes)
    add("json_valid", "JSON 合法", ok, [] if ok else [detail], detail)

    if servers:
        ok, problems = check_fields_complete(servers)
        add("fields_complete", "每条字段齐全",
            ok, problems, f"{len(servers)} 条全部含必备字段" if ok else "")

        ok, problems = check_names_unique(servers)
        add("names_unique", "name 唯一且合规",
            ok, problems, f"{len(servers)} 个 name 无重复且符合 ^[a-z][a-z0-9-]$" if ok else "")

        ok, hits = check_no_real_secrets(servers, raw_text)
        add("no_real_secrets", "密钥占位符未被真值替换（正则）",
            ok, hits, f"{len(SECRET_PATTERNS)} 条密钥正则扫描配置全文与全部 env 值，零命中" if ok else "")

        ok, problems = check_placeholders_intact(servers)
        add("placeholders_intact", "secret_env 占位符形态完好",
            ok, problems, "全部 secret_env 变量保持 ${VAR} 占位形态" if ok else "")

        ok, problems = check_docs_exist(servers, docs_dir)
        add("docs_exist", "每个 name 有 docs/ 手册且必备小节齐全",
            ok, problems, f"docs/ 共 {len(list(docs_dir.glob('*.md')))} 份，与配置一一对应" if ok else "")

    ok, problems = check_artifacts(config_path, docs_dir, out_dir)
    add("artifacts_exist", "产物在盘（配置/docs/out 可写）", ok, problems,
        "mcp.office.json、docs/、out/ 均在盘且可写" if ok else "")

    passed = sum(1 for c in checks if c["pass"])
    report = {
        "oracle": "mcp-office-pack",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config": str(config_path),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": passed,
            "failed": len(checks) - passed,
            "all_green": passed == len(checks) and len(checks) > 0,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for c in checks:
        mark = "PASS" if c["pass"] else "FAIL"
        print(f"[{mark}] {c['id']}: {c['detail']}")
    print(f"summary: {report['summary']}  -> {out_path}")
    return 0 if report["summary"]["all_green"] else 1


if __name__ == "__main__":
    sys.exit(main())
