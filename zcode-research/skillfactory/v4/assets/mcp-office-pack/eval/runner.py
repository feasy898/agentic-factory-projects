#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eval/runner.py — 办公 MCP 配置包（mcp-office-pack）确定性评测 runner

用法：
  python eval/runner.py <被测包根> <参照包根>
  python eval/runner.py package oracle        # 常规评测
  python eval/runner.py oracle oracle         # 自校验（应全过、exit 0）
  python eval/runner.py oracle/out oracle/out # 同上：包根下的 out/ 等子目录自动上溯一级到包根
  python eval/runner.py <空目录> oracle      # 红检（应报失败、exit 1）
  python eval/runner.py                       # 无参数 = 写死默认 oracle oracle

包根定义（contract §1）：直接含 mcp.office.json、validate.py、docs/ 的目录。

检查项（checks 数组，元素 {name, pass, detail}；name 冻结，contract §4）：
  1. package_validate_all_green        裸跑 <被测根>/validate.py exit 0，且 out/validate.json
                                       summary.all_green==true、summary 与 checks 计数自洽、
                                       七个必备 id（spec §6 C1）齐全且全部 pass
  2. config_json_valid                 mcp.office.json 可解析且 mcpServers 非空对象
  3. scenario_coverage_matrix          按 spec §4 S2 冻结规则，六格（文件/Excel/Word/PPT/
                                       浏览器/搜索）每格 ≥1 条
  4. docs_one_to_one                   spec §5 D1：每条 entry 的 doc 存在，且 docs/ 下每个
                                       .md 恰被一条 entry 引用（无缺失、无孤儿）
  5. coverage_equivalent_to_reference  参照覆盖槽位集合 ⊆ 被测覆盖槽位集合（spec §4 S3；
                                       条目与参照重合不做要求）

输出：单个 JSON {"ok","tested","reference","checks":[...]}；全部通过 exit 0，任一失败 exit 1。
确定性：本脚本无时间/随机源，同一输入两次运行输出一致；不 import 参照/被测包的任何 Python 模块，
唯一例外是按 contract §2 以 subprocess 裸跑被测包自带的 validate.py（超时 120s 按失败）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ASSET_ROOT = Path(__file__).resolve().parent.parent          # .../mcp-office-pack
DEFAULT_ROOT = ASSET_ROOT / "oracle"                         # 写死默认（contract §4）

CONFIG_NAME = "mcp.office.json"
VALIDATOR_NAME = "validate.py"
VALIDATE_REPORT = Path("out") / "validate.json"
VALIDATE_TIMEOUT_S = 120

# spec §6 C1：validate.py 七个必备 check id（要求齐全且全部 pass，防「零检查假绿」）
REQUIRED_VALIDATE_IDS = (
    "json_valid", "fields_complete", "names_unique", "no_real_secrets",
    "placeholders_intact", "docs_exist", "artifacts_exist",
)

# spec §4 S1：六格固定槽位（冻结顺序，仅用于 detail 展示）
CANONICAL_SLOTS = ("文件", "Excel", "Word", "PPT", "浏览器", "搜索")

# spec §4 S2：槽位判定规则（冻结）——scenario 子串（原样）与 name 子串（小写化）
SLOT_RULES = {
    "文件":  {"scenario": ("文件",), "name": ("file",)},
    "Excel": {"scenario": ("Excel",), "name": ("excel",)},
    "Word":  {"scenario": ("Word",), "name": ("word",)},
    "PPT":   {"scenario": ("PPT", "PowerPoint", "幻灯片"),
              "name": ("powerpoint", "ppt", "slide")},
    "浏览器": {"scenario": ("浏览器",),
              "name": ("playwright", "browser", "puppeteer")},
    "搜索":  {"scenario": ("搜索",), "name": ("search", "tavily")},
}


# ---------------------------------------------------------------- 基础工具

def slots_of(name: str, entry: dict) -> set:
    """spec §4 S2：对 entry 的 (name, scenario) 按冻结关键词规则计算覆盖槽位集合。"""
    nl = (name or "").lower()
    sc = entry.get("scenario") if isinstance(entry, dict) else None
    sc = sc if isinstance(sc, str) else ""
    got = set()
    for slot, rule in SLOT_RULES.items():
        if any(k in sc for k in rule["scenario"]) or any(k in nl for k in rule["name"]):
            got.add(slot)
    return got


def load_config(root: Path):
    """返回 (servers, err)；servers = mcpServers dict，失败时 (None, 原因)。"""
    cfg_path = root / CONFIG_NAME
    if not cfg_path.is_file():
        return None, "配置不在盘: %s" % cfg_path
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, "JSON 解析失败: %s" % e
    if not isinstance(data, dict):
        return None, "顶层不是 JSON 对象"
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        return None, "mcpServers 缺失或非空对象要求不满足"
    return servers, None


def doc_rel_of(name: str, entry: dict) -> str:
    """spec §5 D1：entry 手册相对路径（doc 字段缺省 docs/<name>.md）。"""
    doc = entry.get("doc") if isinstance(entry, dict) else None
    return Path(doc if isinstance(doc, str) and doc.strip() else "docs/%s" % name).as_posix()


# ---------------------------------------------------------------- 检查 1

def check_validate_all_green(root: Path, checks: list) -> None:
    """裸跑被测包自带 validate.py 并核对 out/validate.json（spec §9 第 1 条 / contract §4 #1）。"""
    name = "package_validate_all_green"
    validate_py = root / VALIDATOR_NAME
    if not root.is_dir():
        checks.append({"name": name, "pass": False, "detail": "被测包根不在盘: %s" % root})
        return
    if not validate_py.is_file():
        checks.append({"name": name, "pass": False,
                       "detail": "%s 不在盘（contract §1 必备）" % validate_py})
        return
    try:
        proc = subprocess.run(
            [sys.executable, str(validate_py)],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=VALIDATE_TIMEOUT_S,
        )
        exit_code, tail = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        checks.append({"name": name, "pass": False,
                       "detail": "validate.py 运行超时（>%ds）" % VALIDATE_TIMEOUT_S})
        return
    except Exception as e:  # noqa: BLE001
        checks.append({"name": name, "pass": False,
                       "detail": "validate.py 启动失败: %s" % e})
        return

    problems = []
    if exit_code != 0:
        problems.append("exit=%d（要求 0）" % exit_code)
    report_path = root / VALIDATE_REPORT
    summary, ids_ok = None, {}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            problems.append("out/validate.json 顶层不是 JSON 对象")
        else:
            summary = report.get("summary")
            run_checks = report.get("checks")
            if not isinstance(run_checks, list) or not run_checks:
                problems.append("checks 缺失或为空（零检查不允许判绿）")
            else:
                by_id = {c.get("id"): c for c in run_checks if isinstance(c, dict)}
                for cid in REQUIRED_VALIDATE_IDS:
                    item = by_id.get(cid)
                    ids_ok[cid] = bool(item) and item.get("pass") is True
                    if item is None:
                        problems.append("缺必备 check id: %s" % cid)
                    elif item.get("pass") is not True:
                        problems.append("check %s 未通过: %s"
                                        % (cid, str(item.get("detail"))[:80]))
                if not isinstance(summary, dict):
                    problems.append("summary 缺失或非对象")
                else:
                    total = summary.get("total")
                    passed, failed = summary.get("passed"), summary.get("failed")
                    passed_cnt = sum(1 for c in run_checks if isinstance(c, dict)
                                     and c.get("pass") is True)
                    if total != len(run_checks) or passed != passed_cnt \
                            or failed != len(run_checks) - passed_cnt:
                        problems.append("summary 计数与 checks 不自洽: %r" % summary)
                    elif summary.get("all_green") is not True:
                        bad = [str(c.get("id")) for c in run_checks
                               if isinstance(c, dict) and c.get("pass") is not True]
                        problems.append("summary.all_green != true（未过: %s）" % ", ".join(bad[:5]))
    except Exception as e:  # noqa: BLE001
        problems.append("out/validate.json 不可读/不可解析: %s" % e)
    if problems:
        checks.append({"name": name, "pass": False,
                       "detail": "；".join(problems[:6])
                       + ("；输出尾段: %s" % tail.strip()[-160:] if tail.strip() and exit_code != 0 else "")})
    else:
        checks.append({"name": name, "pass": True,
                       "detail": "validate.py exit=0；out/validate.json all_green=true，"
                                 "%d 个必备 id 齐全且全部 pass" % len(REQUIRED_VALIDATE_IDS)})


# ---------------------------------------------------------------- 检查 2/3/4/5

def check_config(root: Path, checks: list):
    """检查 2：配置可解析。返回 servers dict（失败时 None）。"""
    servers, err = load_config(root)
    if servers is None:
        checks.append({"name": "config_json_valid", "pass": False,
                       "detail": "%s/mcp.office.json: %s" % (root, err)})
    else:
        checks.append({"name": "config_json_valid", "pass": True,
                       "detail": "mcpServers 共 %d 条" % len(servers)})
    return servers


def check_coverage_matrix(servers, checks: list) -> set:
    """检查 3：六格矩阵每格 ≥1（spec §4 S1/S2）。返回被测覆盖槽位集合。"""
    name = "scenario_coverage_matrix"
    if servers is None:
        checks.append({"name": name, "pass": False, "detail": "配置不可解析，无法计算槽位"})
        return set()
    per_slot = {slot: [] for slot in CANONICAL_SLOTS}
    for cname, entry in servers.items():
        for slot in slots_of(cname, entry if isinstance(entry, dict) else {}):
            per_slot[slot].append(cname)
    empty = [s for s in CANONICAL_SLOTS if not per_slot[s]]
    detail = "；".join("%s×%d(%s)" % (s, len(per_slot[s]), ",".join(per_slot[s]) or "—")
                       for s in CANONICAL_SLOTS)
    checks.append({"name": name, "pass": not empty,
                   "detail": ("六格齐全: " + detail) if not empty
                   else ("槽位缺失 %s；%s" % (empty, detail))})
    return {s for s in CANONICAL_SLOTS if per_slot[s]}


def check_docs_one_to_one(root: Path, servers, checks: list) -> None:
    """检查 4：手册与条目一一对应（spec §5 D1，双向）。"""
    name = "docs_one_to_one"
    if servers is None:
        checks.append({"name": name, "pass": False, "detail": "配置不可解析，无法核对对应关系"})
        return
    referenced = {cname: doc_rel_of(cname, entry if isinstance(entry, dict) else {})
                  for cname, entry in servers.items()}
    docs_dir = root / "docs"
    on_disk = set()
    if docs_dir.is_dir():
        on_disk = {p.relative_to(root).as_posix() for p in docs_dir.rglob("*.md")}
    used = set(referenced.values())
    missing = sorted({rel for rel in used
                      if not (root / rel).is_file()})
    orphan = sorted(on_disk - used)
    duplicate = sorted({rel for rel in used
                        if list(referenced.values()).count(rel) > 1})
    problems = []
    if missing:
        problems.append("条目手册缺失: %s" % ", ".join(missing))
    if orphan:
        problems.append("docs/ 存在孤儿手册（无对应条目）: %s" % ", ".join(orphan))
    if duplicate:
        problems.append("手册被多条条目重复引用: %s" % ", ".join(duplicate))
    checks.append({"name": name, "pass": not problems,
                   "detail": ("%d 条 entry ↔ %d 份手册，双向一一对应"
                              % (len(servers), len(on_disk))) if not problems
                   else "；".join(problems[:4])})


def check_coverage_equivalence(ref_servers, tested_slots: set, checks: list) -> None:
    """检查 5：参照覆盖槽位集合 ⊆ 被测覆盖槽位集合（spec §4 S3）。"""
    name = "coverage_equivalent_to_reference"
    if ref_servers is None:
        checks.append({"name": name, "pass": False,
                       "detail": "参照配置不可解析，无法比对等价性"})
        return
    ref_slots = set()
    for rname, entry in ref_servers.items():
        ref_slots |= slots_of(rname, entry if isinstance(entry, dict) else {})
    lacking = sorted(ref_slots - tested_slots)
    checks.append({"name": name, "pass": not lacking,
                   "detail": ("参照槽位 %s ⊆ 被测槽位 %s（条目重合不做要求）"
                              % (sorted(ref_slots) or "∅", sorted(tested_slots) or "∅"))
                   if not lacking else "被测缺参照槽位: %s" % lacking})


# ---------------------------------------------------------------- 主流程

def resolve_pack_root(path: Path) -> Path:
    """包根别名（contract §2）：本资产产物 out/ 在包根之内，参数给到包根下的子目录
    （如 oracle/out）时，若其**父目录**是包根（含 mcp.office.json）则上溯一级；
    仅此一级，不递归——空目录/无关目录保持原样照常判红。"""
    if (path / CONFIG_NAME).is_file():
        return path
    if (path.parent / CONFIG_NAME).is_file():
        return path.parent
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="mcp-office-pack 确定性评测 runner")
    ap.add_argument("tested", nargs="?", default=None,
                    help="被测包根（默认写死: %s）" % DEFAULT_ROOT)
    ap.add_argument("reference", nargs="?", default=None,
                    help="参照包根（默认写死: %s）" % DEFAULT_ROOT)
    args = ap.parse_args(argv)

    tested_root = resolve_pack_root(Path(args.tested).resolve() if args.tested else DEFAULT_ROOT)
    ref_root = resolve_pack_root(Path(args.reference).resolve() if args.reference else DEFAULT_ROOT)
    checks: list[dict] = []

    # 1) 被测包自带校验器全绿
    check_validate_all_green(tested_root, checks)

    # 2) 配置可解析（后续检查的前提）
    servers = check_config(tested_root, checks)

    # 3) 场景覆盖矩阵
    tested_slots = check_coverage_matrix(servers, checks)

    # 4) 手册与配置条目一一对应
    check_docs_one_to_one(tested_root, servers, checks)

    # 5) 与参照的场景覆盖等价（条目重合不做要求）
    ref_servers, _ref_err = load_config(ref_root)
    check_coverage_equivalence(ref_servers, tested_slots, checks)

    ok = all(c["pass"] for c in checks)
    print(json.dumps({"ok": ok, "tested": str(tested_root), "reference": str(ref_root),
                      "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
