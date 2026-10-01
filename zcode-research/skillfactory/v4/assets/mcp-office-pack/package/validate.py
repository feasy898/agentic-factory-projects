#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mcp-office-pack 自校验器（validate.py）。

行为规格：spec.md §6（C1–C4）。
  C1 七项检查，id 固定（本实现各项语义）：
    json_valid            配置在盘、UTF-8 可解析、顶层为对象、mcpServers 非空对象、_meta 元数据齐备
    fields_complete       每条 entry 必备字段与约束（spec §3.2 字段表）：type/command/args/url/env/
                          secret_env/description/enabled/scenario/catalog(record_url+form)/doc
    names_unique          name 匹配 ^[a-z][a-z0-9\\-]{1,63}$ 且在 mcpServers 内唯一（spec §3.3）
    no_real_secrets       配置全文 + 全部 env 值零真值：11 条密钥正则族逐一扫描（spec §3.4/§6 C1）
    placeholders_intact   secret_env 声明的每个键存在于 env 且值保持 ${VAR_NAME} 占位形态（spec §3.4）
    docs_exist            D1 双向一一对应：每条 entry 的 doc 文件在盘；docs/ 下每个 .md 恰被一条
                          entry 引用（无缺失、无孤儿、无重复引用）（spec §5 D1）
    artifacts_exist       手册产物质量线：每份手册含「安装前提/配置步骤/常用调用/注意事项」四小节、
                          非空白字符 ≥200、正文含本条 catalog.record_url（spec §5 D2/D3）
  C2 产物：写 out/validate.json（contract §3 schema）。
  C3 退出码：全绿 0，任一失败 1。
  C4 参数：--config/--out 缺省相对本脚本所在目录（BASE）定位，不依赖调用方 cwd。

确定性：对同一包根重复运行，除 generated_at 时间戳外判定结果一致（contract §3）。
用法：裸跑 `python validate.py` 即可（无需参数）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent

CONFIG_NAME = "mcp.office.json"
DOCS_DIR = "docs"

# spec §6 C1：七个必备 check id（固定，防「零检查假绿」由 summary 自洽性保证）
REQUIRED_ORDER = (
    "json_valid", "fields_complete", "names_unique", "no_real_secrets",
    "placeholders_intact", "docs_exist", "artifacts_exist",
)

# spec §3.4/§6 C1：11 条密钥真值正则族（id, 说明, 正则）
SECRET_PATTERNS = (
    ("tavily_api_key",       r"tvly-[A-Za-z0-9_\-]{8,}"),
    ("openai_like",          r"sk-[A-Za-z0-9_\-]{16,}"),
    ("github_token",         r"gh[pousr]_[A-Za-z0-9]{16,}"),
    ("github_pat",           r"github_pat_[A-Za-z0-9_]{16,}"),
    ("google_api_key",       r"AIza[0-9A-Za-z_\-]{20,}"),
    ("google_oauth_secret",  r"GOCSPX-[A-Za-z0-9_\-]{16,}"),
    ("google_access_token",  r"ya29\.[0-9A-Za-z_\-]{20,}"),
    ("aws_access_key_id",    r"AKIA[0-9A-Z]{12,}"),
    ("slack_token",          r"xox[baprs]-[A-Za-z0-9\-]{8,}"),
    ("hex32_plus",           r"\b[0-9a-fA-F]{32,}\b"),
    ("b64_43_plus",          r"\b[A-Za-z0-9+/]{43,}={0,2}\b"),
)

PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z][A-Z0-9_]*\}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9\-]{1,63}$")
URL_RE = re.compile(r"^https?://\S+$")

DOC_SECTIONS = ("安装前提", "配置步骤", "常用调用", "注意事项")
MIN_DOC_NONWS_CHARS = 200
META_KEYS = ("pack", "version", "target", "comment",
             "placeholder_policy", "catalog_source", "scenario_scope")


# ---------------------------------------------------------------- 基础工具

def rel_posix(p: Path, base: Path) -> str:
    try:
        return p.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        return p.as_posix()


def read_text_utf8(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def load_config(cfg_path: Path):
    """返回 (data, raw_text, err)。"""
    if not cfg_path.is_file():
        return None, None, "配置不在盘: %s" % rel_posix(cfg_path, BASE)
    raw, err = read_text_utf8(cfg_path)
    if err:
        return None, None, "配置不可读（UTF-8）: %s" % err
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        return None, raw, "JSON 解析失败: %s" % e
    if not isinstance(data, dict):
        return None, raw, "顶层不是 JSON 对象"
    return data, raw, None


def servers_of(data):
    if not isinstance(data, dict):
        return None, "配置不可解析"
    sv = data.get("mcpServers")
    if not isinstance(sv, dict) or not sv:
        return None, "mcpServers 缺失或非空对象要求不满足"
    return sv, None


def doc_rel_of(name: str, entry: dict) -> str:
    doc = entry.get("doc") if isinstance(entry, dict) else None
    rel = doc if isinstance(doc, str) and doc.strip() else "%s/%s.md" % (DOCS_DIR, name)
    return Path(rel).as_posix()


class Check:
    """单个 check 的累积器。"""

    def __init__(self, cid: str, name: str):
        self.id, self.name, self.problems = cid, name, []
        self.notes: list[str] = []

    def add(self, problem: str) -> None:
        self.problems.append(problem)

    def note(self, text: str) -> None:
        self.notes.append(text)

    def emit(self) -> dict:
        passed = not self.problems
        detail = ("；".join(self.notes) if self.notes else
                  ("；".join(self.problems[:6]) if self.problems else "通过"))
        if not passed and self.notes:
            detail = "；".join(self.problems[:6])
        return {"id": self.id, "name": self.name, "pass": passed,
                "detail": detail, "problems": list(self.problems)}


# ---------------------------------------------------------------- C1 各检查

def check_json_valid(data, err) -> Check:
    c = Check("json_valid", "配置 JSON 可解析且结构顶层合法（spec §3.1）")
    if err:
        c.add(err)
        return c
    c.note("mcpServers 为对象")
    meta = data.get("_meta")
    if not isinstance(meta, dict):
        c.add("包级元数据 _meta 缺失或非对象（spec §3.1）")
    else:
        missing = []
        for k in META_KEYS:
            v = meta.get(k)
            ok = (isinstance(v, str) and v.strip()) or \
                 (k == "scenario_scope" and isinstance(v, list) and v)
            if not ok:
                missing.append(k)
        if missing:
            c.add("_meta 缺必备键或不合法: %s" % ", ".join(missing))
        else:
            c.note("_meta 元数据 7 键齐备（pack=%s version=%s）"
                   % (meta.get("pack"), meta.get("version")))
    return c


def check_fields_complete(servers, err) -> Check:
    c = Check("fields_complete", "逐条 entry 必备字段与约束（spec §3.2 字段表）")
    if servers is None:
        c.add(err or "配置不可解析，无法核验字段")
        return c
    for name, entry in servers.items():
        where = "entry[%s]" % name
        if not isinstance(entry, dict):
            c.add("%s 不是对象" % where)
            continue
        typ = entry.get("type")
        if typ not in ("stdio", "http"):
            c.add("%s.type 必须为 stdio|http，实测 %r" % (where, typ))
        elif typ == "stdio":
            if not (isinstance(entry.get("command"), str) and entry["command"].strip()):
                c.add("%s.command 缺失或非空字符串要求不满足（stdio）" % where)
            if not (isinstance(entry.get("args"), list)
                    and all(isinstance(a, str) for a in entry["args"])):
                c.add("%s.args 必须为字符串数组（stdio）" % where)
        else:
            url = entry.get("url")
            if not (isinstance(url, str) and URL_RE.match(url.strip())):
                c.add("%s.url 缺失或非 http/https URL（http）" % where)
        env = entry.get("env")
        if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
            c.add("%s.env 必须为字符串值对象" % where)
        se = entry.get("secret_env")
        if not isinstance(se, list) or not all(isinstance(k, str) for k in se):
            c.add("%s.secret_env 必须为字符串数组" % where)
        if not (isinstance(entry.get("description"), str) and entry["description"].strip()):
            c.add("%s.description 缺失或空" % where)
        if not isinstance(entry.get("enabled"), bool):
            c.add("%s.enabled 必须为布尔" % where)
        if not (isinstance(entry.get("scenario"), str) and entry["scenario"].strip()):
            c.add("%s.scenario 缺失或空" % where)
        cat = entry.get("catalog")
        if not isinstance(cat, dict):
            c.add("%s.catalog 缺失或非对象" % where)
        else:
            ru = cat.get("record_url")
            if not (isinstance(ru, str) and URL_RE.match(ru.strip())):
                c.add("%s.catalog.record_url 必须为 http/https URL" % where)
            if not (isinstance(cat.get("form"), str) and cat["form"].strip()):
                c.add("%s.catalog.form 缺失或空（形态注记必备）" % where)
        doc = entry.get("doc")
        if doc is not None and not (isinstance(doc, str) and doc.strip()):
            c.add("%s.doc 若给出必须为非空字符串" % where)
    c.note("%d 条 entry 字段逐条核验完成" % len(servers))
    return c


def check_names_unique(servers, err) -> Check:
    c = Check("names_unique", "name 合法且唯一（spec §3.3）")
    if servers is None:
        c.add(err or "配置不可解析，无法核验 name")
        return c
    seen: dict[str, int] = {}
    for name in servers:
        if not NAME_RE.match(str(name)):
            c.add("name 不匹配 ^[a-z][a-z0-9\\-]{1,63}$: %r" % name)
        seen[str(name)] = seen.get(str(name), 0) + 1
    dup = sorted(n for n, k in seen.items() if k > 1)
    if dup:
        c.add("name 重复: %s" % ", ".join(dup))
    c.note("%d 个 name 全部合法唯一" % len(servers))
    return c


def check_no_real_secrets(raw, servers, err) -> Check:
    c = Check("no_real_secrets", "密钥零真值：11 条正则族扫配置全文 + 全部 env 值（spec §3.4）")
    if raw is None:
        c.add(err or "配置不可读，无法扫描")
        return c
    haystacks = [("config全文", raw)]
    if servers:
        for name, entry in servers.items():
            if isinstance(entry, dict) and isinstance(entry.get("env"), dict):
                for k, v in entry["env"].items():
                    haystacks.append(("env[%s].%s" % (name, k), v))
    hits = []
    for hay_name, text in haystacks:
        for fam, pat in SECRET_PATTERNS:
            m = re.search(pat, text)
            if m:
                frag = m.group(0)
                shown = (frag[:6] + "…") if len(frag) > 6 else frag
                hits.append("%s 命中 %s（%s…）" % (hay_name, fam, shown))
    if hits:
        for h in hits[:8]:
            c.add(h)
    else:
        c.note("11 条正则族 × %d 个扫描面全部未命中" % len(haystacks))
    return c


def check_placeholders_intact(servers, err) -> Check:
    c = Check("placeholders_intact", "secret_env 声明键保持 ${VAR} 占位形态（spec §3.4）")
    if servers is None:
        c.add(err or "配置不可解析，无法核验占位符")
        return c
    declared = 0
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        env = entry.get("env") if isinstance(entry.get("env"), dict) else {}
        se = entry.get("secret_env") if isinstance(entry.get("secret_env"), list) else []
        for key in se:
            declared += 1
            where = "entry[%s].env.%s" % (name, key)
            if key not in env:
                c.add("%s 已声明 secret_env 但 env 中缺失" % where)
            elif not (isinstance(env[key], str) and PLACEHOLDER_RE.match(env[key])):
                c.add("%s 值不是 ${VAR_NAME} 占位形态" % where)
    if declared:
        c.note("secret_env 共声明 %d 个密钥键，全部保持占位形态" % declared
               if not c.problems else "")
    else:
        c.note("secret_env 无密钥声明（全部空列表，合法）")
    return c


def check_docs_exist(servers, err) -> Check:
    c = Check("docs_exist", "D1 手册与条目双向一一对应（spec §5 D1）")
    if servers is None:
        c.add(err or "配置不可解析，无法核对手册对应")
        return c
    used = {name: doc_rel_of(name, entry if isinstance(entry, dict) else {})
            for name, entry in servers.items()}
    missing = sorted({rel for rel in used.values() if not (BASE / rel).is_file()})
    docs_dir = BASE / DOCS_DIR
    on_disk: set[str] = set()
    if docs_dir.is_dir():
        on_disk = {rel_posix(p, BASE) for p in docs_dir.rglob("*.md")}
    orphan = sorted(on_disk - set(used.values()))
    dup = sorted({rel for rel in used.values()
                  if list(used.values()).count(rel) > 1})
    if missing:
        c.add("条目手册缺失: %s" % ", ".join(missing))
    if orphan:
        c.add("docs/ 存在孤儿手册（无对应条目）: %s" % ", ".join(orphan))
    if dup:
        c.add("手册被多条条目重复引用: %s" % ", ".join(dup))
    if not c.problems:
        c.note("%d 条 entry ↔ %d 份手册，双向一一对应" % (len(servers), len(on_disk)))
    return c


def check_artifacts_exist(servers, err) -> Check:
    c = Check("artifacts_exist", "手册产物质量线：D2 四小节+正文长度，D3 含目录实录 URL（spec §5）")
    if servers is None:
        c.add(err or "配置不可解析，无法核对手册产物")
        return c
    checked = 0
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        rel = doc_rel_of(name, entry)
        text, rerr = read_text_utf8(BASE / rel)
        if rerr:
            c.add("手册不可读: %s（%s）" % (rel, rerr))
            continue
        checked += 1
        absent = [s for s in DOC_SECTIONS if s not in text]
        if absent:
            c.add("%s 缺必备小节: %s" % (rel, "、".join(absent)))
        nonws = len(re.sub(r"\s+", "", text))
        if nonws < MIN_DOC_NONWS_CHARS:
            c.add("%s 正文过短（非空白字符 %d < %d）" % (rel, nonws, MIN_DOC_NONWS_CHARS))
        cat = entry.get("catalog") if isinstance(entry.get("catalog"), dict) else {}
        ru = cat.get("record_url")
        if isinstance(ru, str) and ru.strip() and ru.strip() not in text:
            c.add("%s 未含本条 catalog.record_url（D3）" % rel)
    if not c.problems:
        c.note("%d 份手册四小节/长度≥%d/record_url 全部达标" % (checked, MIN_DOC_NONWS_CHARS))
    return c


# ---------------------------------------------------------------- 主流程

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mcp-office-pack 自校验器（spec §6）")
    ap.add_argument("--config", default=None,
                    help="配置路径（缺省 %s，相对本脚本目录）" % CONFIG_NAME)
    ap.add_argument("--out", default=None,
                    help="报告输出路径（缺省 out/validate.json，相对本脚本目录）")
    args = ap.parse_args(argv)

    cfg_path = Path(args.config) if args.config else BASE / CONFIG_NAME
    if not cfg_path.is_absolute():
        cfg_path = BASE / cfg_path
    out_path = Path(args.out) if args.out else BASE / "out" / "validate.json"
    if not out_path.is_absolute():
        out_path = BASE / out_path

    data, raw, err = load_config(cfg_path)
    servers, serr = servers_of(data)
    if servers is None:
        serr = serr or err

    checks = [
        check_json_valid(data, err).emit(),
        check_fields_complete(servers, serr).emit(),
        check_names_unique(servers, serr).emit(),
        check_no_real_secrets(raw, servers, err).emit(),
        check_placeholders_intact(servers, serr).emit(),
        check_docs_exist(servers, serr).emit(),
        check_artifacts_exist(servers, serr).emit(),
    ]
    total = len(checks)
    passed = sum(1 for x in checks if x["pass"])
    failed = total - passed
    all_green = failed == 0 and total > 0
    report = {
        "oracle": {
            "asset": "mcp-office-pack",
            "reference": "skillfactory/v4/assets/mcp-office-pack/oracle",
            "spec": "spec.md v1.0（2026-09-30）",
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config": rel_posix(cfg_path, BASE),
        "checks": checks,
        "summary": {"total": total, "passed": passed, "failed": failed,
                    "all_green": all_green},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    for x in checks:
        print("[%s] %-20s %s" % ("PASS" if x["pass"] else "FAIL", x["id"], x["detail"]))
    print("summary: %d/%d passed, all_green=%s → %s"
          % (passed, total, all_green, rel_posix(out_path, BASE)))
    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
