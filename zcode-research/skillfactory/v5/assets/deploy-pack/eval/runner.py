#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runner.py — deploy-pack（三服务部署包）资产确定性评测器（无随机/无网络/无时间戳）

用法：
    python skillfactory/v5/assets/deploy-pack/eval/runner.py <被测产物根> <参照产物根> [--out <path>]

    例：python eval/runner.py oracle/out oracle/out           # 自评（应 exit 0）
        python eval/runner.py oracle/out/pack-canonical oracle/out
        python eval/runner.py <被测 pack 目录> <参照 pack 目录>

产物根解析（被测与参照同构，contract.md §3）：
    <root>/docker-compose.yml 存在                  → direct（root 即 pack 目录）
    <root>/pack-canonical/docker-compose.yml 存在   → pack-canonical
    <root>/out/pack-canonical/docker-compose.yml 存在 → parent-out
    pack 目录 = 含 docker-compose.yml 的部署包目录（三件套完整性与否由检查项判定）

固定 4 项检查（名称冻结，恒 4 项齐全，见 contract.md §4 / spec.md §5）：
  1. compose_yaml_three_services     生成 compose 可被 yaml.safe_load 解析，服务集恰为 asr,minutes,todo
  2. env_compose_vars_consistent     .env.example 变量集 == compose ${} 引用集（双向）
  3. validate_all_green              以参照侧定位的 oracle validate.py（缺省三服务口径）实跑被测包，
                                     退出码 0 且 verdict=ALL GREEN
  4. reference_text_agreement_90pct  与参照 pack 三文件文本一致率 ≥ 0.90
                                     （行级 difflib、CRLF 归一、BOM 容忍、行位加权聚合）

全过 → stdout 打印单一 JSON(ok=true) 且退出码 0；任一失败 → ok=false 且退出码 1；
用法错误由 argparse 退出码 2。输出不含时间戳；同参数重复运行 stdout 逐字节一致。
被测/参照/oracle 任何文件都不被本评测器修改（临时报告写系统临时目录并清理）。
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ASSET = "skillfactory/v5/assets/deploy-pack/eval"

# ---------------------------------------------------------------- 冻结常量
# 与 spec.md 附录 A（增补条款 A-1）一致；修改须先改 spec.md/contract.md 并升版本号。
EXPECTED_SERVICES = ("asr", "minutes", "todo")   # canonical 三服务（= gen_deploy.py CATALOG 键序）
PACK_FILES = ("docker-compose.yml", ".env.example", "DEPLOY.md")  # = gen_deploy.py:72 PACK_FILES
TEXT_AGREEMENT_MIN = 0.90                        # 检查 4 阈值（ask 冻结：≥90%）
VALIDATE_TIMEOUT_S = 120                         # 检查 3 子进程上限（秒）
# compose ${VAR} / ${VAR:-default} 引用（与 oracle validate.py:52 REF_RE 同口径）
REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


# ---------------------------------------------------------------- 基础工具
def read_text(path):
    """读文件文本：容忍 BOM，统一 \\r\\n|\\r → \\n。失败返回 (None, 原因)。"""
    if not os.path.isfile(path):
        return None, "缺文件 %s" % path
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        return None, "无法读取 %s (%s)" % (path, exc)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return None, "非 UTF-8: %s (%s)" % (path, exc)
    return text.replace("\r\n", "\n").replace("\r", "\n"), None


def resolve_pack(root):
    """产物根解析：direct → pack-canonical → parent-out；都不命中 → (None, "none")。"""
    root = os.path.abspath(root)
    for sub, via in ((root, "direct"),
                     (os.path.join(root, "pack-canonical"), "pack-canonical"),
                     (os.path.join(root, "out", "pack-canonical"), "parent-out")):
        if os.path.isfile(os.path.join(sub, PACK_FILES[0])):
            return sub, via
    return None, "none"


def find_oracle_dir(start):
    """定位 oracle 目录（同时含 validate.py 与 gen_deploy.py）：
    从 start 沿祖先链向上找；找不到回退 runner 同级 ../oracle。返回 (dir, via)。"""
    d = os.path.abspath(start)
    while True:
        if (os.path.isfile(os.path.join(d, "validate.py"))
                and os.path.isfile(os.path.join(d, "gen_deploy.py"))):
            return d, "reference-ancestor(%s)" % d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    fb = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "oracle"))
    if (os.path.isfile(os.path.join(fb, "validate.py"))
            and os.path.isfile(os.path.join(fb, "gen_deploy.py"))):
        return fb, "runner-relative(%s)" % fb
    return None, "none"


def parse_env_text(text):
    """极简 dotenv：仅 KEY=VALUE 行，忽略空行与 # 注释（与 oracle validate.py parse_env_file 同口径）。"""
    env = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def iter_strings(node):
    """递归展开 YAML 结构中的全部字符串标量（与 oracle validate.py iter_strings 同口径）。"""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from iter_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_strings(v)


# ---------------------------------------------------------------- 检查 1
def check1_compose(pack, checks):
    """C1：compose 可被 yaml.safe_load 解析且服务集恰为 canonical 三服务。返回解析出的 YAML doc 或 None。"""
    name = "compose_yaml_three_services"
    text, err = read_text(os.path.join(pack, PACK_FILES[0]))
    if err:
        checks.append({"name": name, "passed": False, "detail": err})
        return None
    try:
        import yaml  # PyYAML（本机实测 6.0.3）
    except ImportError as exc:
        checks.append({"name": name, "passed": False,
                       "detail": "PyYAML 导入失败（评测依赖 PyYAML）: %s" % exc})
        return None
    try:
        doc = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001  yaml 任何解析异常都判败
        first = str(exc).splitlines()[0] if str(exc) else ""
        checks.append({"name": name, "passed": False,
                       "detail": "yaml.safe_load 异常: %s: %s" % (type(exc).__name__, first)})
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        checks.append({"name": name, "passed": False,
                       "detail": "safe_load 通过但顶层缺 services 映射（got %s）"
                                 % type(doc).__name__})
        return None
    found = sorted(doc["services"].keys())
    missing = [s for s in EXPECTED_SERVICES if s not in doc["services"]]
    extra = [s for s in found if s not in EXPECTED_SERVICES]
    ok = not missing and not extra
    checks.append({"name": name, "passed": ok,
                   "detail": ("safe_load 通过; 服务集恰为 %s（三服务齐全且无多余）"
                              % (list(EXPECTED_SERVICES),)) if ok
                   else "safe_load 通过; 服务集=%s 缺=%s 多=%s" % (found, missing, extra)})
    return doc


# ---------------------------------------------------------------- 检查 2
def check2_env(pack, doc, checks):
    """C2：.env.example 变量集 == compose ${} 引用集（双向）。内联缺省值漂移由 oracle C3 把关。"""
    name = "env_compose_vars_consistent"
    if doc is None:
        checks.append({"name": name, "passed": False,
                       "detail": "依赖第 1 项：compose 未成功解析，无法提取 ${} 引用集"})
        return
    text, err = read_text(os.path.join(pack, PACK_FILES[1]))
    if err:
        checks.append({"name": name, "passed": False, "detail": err})
        return
    env = parse_env_text(text)
    refs = set()
    for s in iter_strings(doc):
        for m in REF_RE.finditer(s):
            refs.add(m.group(1))
    missing_in_env = sorted(refs - set(env))
    unused_env = sorted(set(env) - refs)
    ok = not missing_in_env and not unused_env
    checks.append({"name": name, "passed": ok,
                   "detail": ("compose引用 %d 个/.env 定义 %d 个; 双向一致"
                              % (len(refs), len(env))) if ok
                   else "compose引用 %d 个/.env 定义 %d 个; compose引用而.env缺=%s; .env多出=%s"
                        % (len(refs), len(env), missing_in_env, unused_env)})


# ---------------------------------------------------------------- 检查 3
def check3_validate(pack, oracle_dir, oracle_via, checks):
    """C3：以 oracle validate.py（缺省服务集 = canonical 三服务）实跑被测包，判全绿。"""
    name = "validate_all_green"
    entry = {"name": name, "passed": False,
             "oracle_resolved": oracle_dir, "oracle_resolved_via": oracle_via}
    checks.append(entry)
    if oracle_dir is None:
        entry["detail"] = ("未定位到 oracle（需同时含 validate.py 与 gen_deploy.py；"
                           "已尝试参照侧祖先链与 runner 同级 ../oracle）")
        return
    tmp = tempfile.mkdtemp(prefix="deploy-pack-eval-")
    try:
        report_path = os.path.join(tmp, "validate-report.json")
        cmd = [sys.executable, os.path.join(oracle_dir, "validate.py"),
               "--pack", pack, "--out", report_path]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=VALIDATE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            entry["detail"] = "validate.py 实跑超时（>%ds）" % VALIDATE_TIMEOUT_S
            return
        rep = None
        if os.path.isfile(report_path):
            try:
                with open(report_path, "rb") as f:
                    rep = json.loads(f.read().decode("utf-8-sig"))
            except (OSError, UnicodeDecodeError, ValueError):
                rep = None
        if r.returncode != 0:
            fails = []
            if isinstance(rep, dict):
                fails = [c.get("name") for c in rep.get("checks", []) if c.get("status") == "FAIL"]
            entry["detail"] = ("oracle validate.py exit=%d（须 0）; FAIL 项=%s%s"
                               % (r.returncode, fails,
                                  ("; stderr=%s" % r.stderr.strip()[:160]) if not fails else ""))
            return
        if not isinstance(rep, dict):
            entry["detail"] = "validate.py exit=0 但报告 JSON 不可读（%s）" % report_path
            return
        summary = rep.get("summary") if isinstance(rep.get("summary"), dict) else {}
        verdict = rep.get("verdict")
        ok = (verdict == "ALL GREEN") and (summary.get("fail") == 0)
        entry["passed"] = ok
        entry["detail"] = (("oracle validate.py 全绿: verdict=%s, %s pass / %s fail / %s skip")
                           % (verdict, summary.get("pass"), summary.get("fail"),
                              summary.get("skip"))) if ok else \
            ("oracle validate.py 非全绿: verdict=%r, summary=%s" % (verdict, summary))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 检查 4
def check4_agreement(cand_pack, ref_pack, checks):
    """C4：与参照 pack 三文件文本一致率 ≥ 0.90（行级 difflib，CRLF 归一，行位加权聚合）。"""
    name = "reference_text_agreement_90pct"
    per_file = []
    ref_problems = []
    total_matched2 = 0   # Σ 2·matched（matched=该文件匹配行数）
    total_len = 0        # Σ (len_ref + len_cand)
    for fn in PACK_FILES:
        rtext, rerr = read_text(os.path.join(ref_pack, fn))
        ctext, cerr = read_text(os.path.join(cand_pack, fn))
        if rerr:
            ref_problems.append("参照侧 %s: %s" % (fn, rerr))
            continue
        ref_lines = rtext.splitlines()
        if cerr:
            # 被测缺文件/不可读：记 0 匹配（计入分母的参照行数），不掩盖
            per_file.append({"file": fn, "ref_lines": len(ref_lines), "cand_lines": 0,
                             "matched": 0, "note": cerr})
            total_len += len(ref_lines)
            continue
        cand_lines = ctext.splitlines()
        sm = difflib.SequenceMatcher(None, ref_lines, cand_lines, autojunk=False)
        matched = sum(b.size for b in sm.get_matching_blocks())
        per_file.append({"file": fn, "ref_lines": len(ref_lines),
                         "cand_lines": len(cand_lines), "matched": matched})
        total_matched2 += 2 * matched
        total_len += len(ref_lines) + len(cand_lines)
    if ref_problems:
        checks.append({"name": name, "passed": False,
                       "detail": "参照产物不完整，无法计算一致率: " + "; ".join(ref_problems)})
        return
    rate_raw = (total_matched2 / total_len) if total_len else 0.0
    rate = round(rate_raw, 4)
    ok = rate_raw >= TEXT_AGREEMENT_MIN
    missing = [p["file"] for p in per_file if p.get("note")]
    detail = ("与参照 pack 三文件文本一致率 %.2f%%（%d/%d 行位匹配，阈值 %.0f%%；"
              "行级 difflib、CRLF 归一、BOM 容忍）"
              % (rate * 100, total_matched2, total_len, TEXT_AGREEMENT_MIN * 100))
    if missing:
        detail += "；被测缺文件: %s" % "、".join(missing)
    checks.append({"name": name, "passed": ok, "detail": detail,
                   "text_agreement_rate": rate, "threshold": TEXT_AGREEMENT_MIN,
                   "per_file": per_file})


# ---------------------------------------------------------------- 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(description="deploy-pack 资产确定性评测器")
    ap.add_argument("candidate", help="被测产物根（pack 目录，或含 pack-canonical/ 的产物根）")
    ap.add_argument("reference", help="参照产物根（oracle/out 或其 pack 目录）")
    ap.add_argument("--out", default=None, help="评测报告输出路径（缺省仅打印 stdout）")
    args = ap.parse_args(argv)

    cand_pack, cand_via = resolve_pack(args.candidate)
    ref_pack, ref_via = resolve_pack(args.reference)
    oracle_dir, oracle_via = find_oracle_dir(ref_pack if ref_pack else args.reference)

    checks = []
    doc = None
    if cand_pack is None:
        pre = ("前置失败：被测产物根未解析出 pack（已尝试 <root>/docker-compose.yml、"
               "<root>/pack-canonical/docker-compose.yml、<root>/out/pack-canonical/docker-compose.yml）: %s"
               % args.candidate)
        checks.append({"name": "compose_yaml_three_services", "passed": False, "detail": pre})
        checks.append({"name": "env_compose_vars_consistent", "passed": False,
                       "detail": "前置失败：被测产物根未解析（见第 1 项）"})
        checks.append({"name": "validate_all_green", "passed": False,
                       "detail": "前置失败：被测产物根未解析（见第 1 项）",
                       "oracle_resolved": oracle_dir, "oracle_resolved_via": oracle_via})
        checks.append({"name": "reference_text_agreement_90pct", "passed": False,
                       "detail": "前置失败：被测产物根未解析（见第 1 项）"})
    else:
        doc = check1_compose(cand_pack, checks)
        check2_env(cand_pack, doc, checks)
        check3_validate(cand_pack, oracle_dir, oracle_via, checks)
        if ref_pack is None:
            checks.append({"name": "reference_text_agreement_90pct", "passed": False,
                           "detail": ("前置失败：参照产物根未解析出 pack（已尝试 direct/pack-canonical/"
                                      "parent-out 三级）: %s" % args.reference)})
        else:
            check4_agreement(cand_pack, ref_pack, checks)

    n_ok = sum(1 for c in checks if c["passed"])
    all_ok = n_ok == len(checks) and len(checks) == 4
    rate = next((c.get("text_agreement_rate") for c in checks
                 if c["name"] == "reference_text_agreement_90pct"
                 and isinstance(c.get("text_agreement_rate"), (int, float))), None)
    self_eval = bool(cand_pack and ref_pack
                     and os.path.abspath(cand_pack) == os.path.abspath(ref_pack))
    result = {
        "tool": "runner.py",
        "asset": ASSET,
        "candidate": args.candidate,
        "reference": args.reference,
        "candidate_resolved": cand_pack,
        "candidate_resolved_via": cand_via,
        "reference_resolved": ref_pack,
        "reference_resolved_via": ref_via,
        "oracle_resolved": oracle_dir,
        "oracle_resolved_via": oracle_via,
        "self_eval": self_eval,
        "ok": all_ok,
        "summary": {
            "checks": {"total": len(checks), "passed": n_ok, "failed": len(checks) - n_ok},
            "text_agreement_rate": rate,
        },
        "checks": checks,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out_path = os.path.abspath(args.out)
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
