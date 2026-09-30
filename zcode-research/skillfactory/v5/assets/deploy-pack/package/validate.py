#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — 三服务部署包校验器（C1-C7，契约同 oracle）

用法（spec.md §3 R3 冻结）：
    python validate.py --pack <部署包目录> [--services asr,minutes,todo] [--out <报告.json>]

    --pack      部署包目录（应含 docker-compose.yml / .env.example / DEPLOY.md 三件套）
    --services  期望服务集（逗号分隔）；缺省 = CATALOG 目录序三服务（canonical 口径）
    --out       校验报告输出路径（JSON，UTF-8 / LF）；缺省仅打印 stdout

七项检查（spec §2.1；oracle 判绿唯一口径）：
    C1 compose_safe_load         docker-compose.yml 可 yaml.safe_load 且顶层含 services 映射
    C2 services_exact            服务集与期望恰等（缺省期望 = CATALOG 三服务）
    C3 env_consistent            .env.example 变量集与 compose ${} 引用集双向一致 + 内联缺省不漂移
    C4 no_hardcoded_secrets      密钥名必须 ${} 引用 + 凭据形态字面量扫描
    C5 wiring_asr_minutes        asr→minutes 接线双侧同值且 compose 双侧接线（服务集不含 asr+minutes 时 SKIP）
    C6 deploy_md_three_cmds      DEPLOY.md 三命令要素（cp .env.example .env → docker compose up -d →
                                 docker compose ps）+ 逐服务 curl /healthz
    C7 deterministic_regenerate  以包内发现的服务集重跑 gen_deploy.py，三份产物逐字节比对
                                 （仅在 C1-C4 全 PASS 时执行）

verdict：ALL GREEN / FAILED。退出码：0=全过（SKIP 不计失败）；1=有 FAIL；2=参数非法。
"""

from __future__ import annotations

import argparse
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

ASSET = "skillfactory/v5/assets/deploy-pack/package"

EXPECTED_SERVICES = ("asr", "minutes", "todo")   # = CATALOG 键序（目录序）
PACK_FILES = ("docker-compose.yml", ".env.example", "DEPLOY.md")
REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")  # spec 附录 A.1
REGEN_TIMEOUT_S = 120

# C4 模式表：密钥形态变量名（命中者的 compose 取值必须是 ${} 引用）
SECRET_NAME_RE = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key"
    r"|secret[_-]?key|private[_-]?key|credential|auth[_-]?)")
# C4 模式表：凭据形态字面量（常见密钥前缀 + 超长随机串）
CRED_LITERAL_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[bpars]-[A-Za-z0-9-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b[A-Za-z0-9+/]{48,}={0,2}\b)")


# ---------------------------------------------------------------- 基础工具
def read_text(path):
    """读文件文本：容忍 BOM，统一 \r\n|\r → \n。失败返回 (None, 原因)。"""
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


def parse_env_text(text):
    """极简 dotenv：仅 KEY=VALUE 行，忽略空行与 # 注释。"""
    env = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def iter_strings(node):
    """递归展开 YAML 结构中的全部字符串标量。"""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from iter_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_strings(v)


def catalog_order(names):
    """把服务名按 CATALOG 目录序排列（忽略未知名，保持去重）。"""
    uniq = list(dict.fromkeys(names))
    return [s for s in EXPECTED_SERVICES if s in uniq]


def find_gen_deploy(start):
    """定位 gen_deploy.py：从 start 沿祖先链向上找；回退本脚本同目录。返回绝对路径或 None。"""
    d = os.path.abspath(start)
    while True:
        p = os.path.join(d, "gen_deploy.py")
        if os.path.isfile(p):
            return p
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    fb = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_deploy.py")
    return fb if os.path.isfile(fb) else None


# ---------------------------------------------------------------- 七项检查
def c1_compose_safe_load(pack, checks):
    """C1：compose 可被 yaml.safe_load 解析且顶层含 services 映射。返回 (doc, services) 或 (None, None)。"""
    entry = {"name": "compose_safe_load", "status": "FAIL"}
    checks.append(entry)
    text, err = read_text(os.path.join(pack, PACK_FILES[0]))
    if err:
        entry["detail"] = err
        return None, None
    try:
        import yaml  # PyYAML
    except ImportError as exc:
        entry["detail"] = "PyYAML 导入失败（校验依赖 PyYAML）: %s" % exc
        return None, None
    try:
        doc = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001  yaml 任何解析异常都判败
        first = str(exc).splitlines()[0] if str(exc) else ""
        entry["detail"] = "yaml.safe_load 异常: %s: %s" % (type(exc).__name__, first)
        return None, None
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        entry["detail"] = ("safe_load 通过但顶层缺 services 映射（got %s）"
                           % type(doc).__name__)
        return None, None
    services = catalog_order(doc["services"].keys())
    entry["status"] = "PASS"
    entry["detail"] = "yaml.safe_load 通过；顶层含 services 映射；服务=%s" % services
    return doc, services


def c2_services_exact(services, expected, checks):
    """C2：服务集与期望恰等（缺或多均败）。"""
    entry = {"name": "services_exact", "status": "FAIL"}
    checks.append(entry)
    if services is None:
        entry["status"] = "SKIP"
        entry["detail"] = "依赖 C1：compose 未成功解析，无法提取服务集"
        return
    found = catalog_order(services)
    missing = [s for s in expected if s not in found]
    extra = [s for s in found if s not in expected]
    if not missing and not extra:
        entry["status"] = "PASS"
        entry["detail"] = "服务集恰为 %s（期望 %s）" % (found, list(expected))
    else:
        entry["detail"] = "服务集=%s 期望=%s 缺=%s 多=%s" % (found, list(expected), missing, extra)


def c3_env_consistent(pack, doc, checks):
    """C3：.env 变量集 == compose ${} 引用集（双向）+ 内联缺省值不漂移。"""
    entry = {"name": "env_consistent", "status": "FAIL"}
    checks.append(entry)
    if doc is None:
        entry["status"] = "SKIP"
        entry["detail"] = "依赖 C1：compose 未成功解析，无法提取 ${} 引用集"
        return
    text, err = read_text(os.path.join(pack, PACK_FILES[1]))
    if err:
        entry["detail"] = err
        return
    env = parse_env_text(text)
    refs = {}   # var -> 首个内联缺省值（无缺省记 None）
    for s in iter_strings(doc):
        for m in REF_RE.finditer(s):
            refs.setdefault(m.group(1), m.group(2))
    missing_in_env = sorted(set(refs) - set(env))
    unused_env = sorted(set(env) - set(refs))
    drift = []
    for var, default in refs.items():
        if default is not None and var in env and env[var] != default:
            drift.append("%s(compose缺省=%r, .env=%r)" % (var, default, env[var]))
    if not missing_in_env and not unused_env and not drift:
        entry["status"] = "PASS"
        entry["detail"] = ("compose引用 %d 个/.env 定义 %d 个; 双向一致; 内联缺省无漂移"
                           % (len(refs), len(env)))
    else:
        entry["detail"] = ("compose引用 %d 个/.env 定义 %d 个; compose引用而.env缺=%s; "
                           ".env多出=%s; 内联缺省漂移=%s"
                           % (len(refs), len(env), missing_in_env, unused_env, drift))


def c4_no_hardcoded_secrets(pack, doc, checks):
    """C4：密钥名必须 ${} 引用 + 凭据形态字面量扫描（compose 与 .env 全文）。"""
    entry = {"name": "no_hardcoded_secrets", "status": "FAIL"}
    checks.append(entry)
    if doc is None:
        entry["status"] = "SKIP"
        entry["detail"] = "依赖 C1：compose 未成功解析，无法扫描取值"
        return
    problems = []
    services = doc.get("services") or {}
    for svc, cfg in services.items():
        envcfg = cfg.get("environment") if isinstance(cfg, dict) else None
        pairs = []
        if isinstance(envcfg, dict):
            pairs = list(envcfg.items())
        elif isinstance(envcfg, list):
            for it in envcfg:
                if isinstance(it, str) and "=" in it:
                    k, v = it.split("=", 1)
                    pairs.append((k.strip(), v.strip()))
        for k, v in pairs:
            if SECRET_NAME_RE.search(str(k)) and not REF_RE.match(str(v)):
                problems.append("compose %s.environment.%s 为字面量（须 ${} 引用）" % (svc, k))
    for fn in PACK_FILES[:2]:
        text, err = read_text(os.path.join(pack, fn))
        if err:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for m in CRED_LITERAL_RE.finditer(line):
                problems.append("%s:%d 命中凭据形态字面量（%s…）" % (fn, i, m.group(0)[:12]))
    if not problems:
        entry["status"] = "PASS"
        entry["detail"] = "无密钥名字面量、无凭据形态字面量（compose + .env 全文扫描）"
    else:
        entry["detail"] = "; ".join(problems[:5]) + ("（共 %d 处）" % len(problems) if len(problems) > 5 else "")


def c5_wiring(pack, doc, services, expected, checks):
    """C5：asr→minutes 接线双侧同值且 compose 双侧接线；服务集不含 asr+minutes 时 SKIP。"""
    entry = {"name": "wiring_asr_minutes", "status": "FAIL",
             "wiring": "asr.ASR_OUTPUT_DIR == minutes.MINUTES_INPUT_DIR"}
    checks.append(entry)
    pack_set = set(services or [])
    if not ({"asr", "minutes"} <= pack_set) or not ({"asr", "minutes"} <= set(expected)):
        entry["status"] = "SKIP"
        entry["detail"] = ("服务集不含 asr+minutes（pack=%s, expected=%s），接线检查不适用"
                           % (sorted(pack_set), list(expected)))
        return
    env = {}
    text, err = read_text(os.path.join(pack, PACK_FILES[1]))
    if not err:
        env = parse_env_text(text)
    a_val = env.get("ASR_OUTPUT_DIR")
    m_val = env.get("MINUTES_INPUT_DIR")
    refs = set()
    if doc is not None:
        for s in iter_strings(doc):
            for m in REF_RE.finditer(s):
                refs.add(m.group(1))
    problems = []
    if a_val is None or m_val is None:
        problems.append(".env 缺 ASR_OUTPUT_DIR 或 MINUTES_INPUT_DIR")
    elif a_val != m_val:
        problems.append("接线两侧不同值: asr.ASR_OUTPUT_DIR=%r vs minutes.MINUTES_INPUT_DIR=%r"
                        % (a_val, m_val))
    for var in ("ASR_OUTPUT_DIR", "MINUTES_INPUT_DIR"):
        if var not in refs:
            problems.append("compose 未接线 %s（须以 ${%s:-…} 引用）" % (var, var))
    if not problems:
        entry["status"] = "PASS"
        entry["detail"] = ("接线成立：两侧同值 %r 且 compose 双侧均以 ${} 引用" % a_val)
    else:
        entry["detail"] = "; ".join(problems)


def c6_deploy_md(pack, services, checks):
    """C6：DEPLOY.md 三命令要素 + 逐服务 curl /healthz 要素。"""
    entry = {"name": "deploy_md_three_cmds", "status": "FAIL"}
    checks.append(entry)
    text, err = read_text(os.path.join(pack, PACK_FILES[2]))
    if err:
        entry["detail"] = err
        return
    required = ["cp .env.example .env", "docker compose up -d", "docker compose ps"]
    missing = [s for s in required if s not in text]
    if "/healthz" not in text or "curl" not in text:
        missing.append("逐服务 curl /healthz 要素")
    if not missing:
        entry["status"] = "PASS"
        entry["detail"] = "三命令要素齐全 + 含 curl /healthz 健康检查要素"
    else:
        entry["detail"] = "缺要素: %s" % "; ".join(missing)


def c7_deterministic_regen(pack, services, c1to4_pass, checks):
    """C7：以包内发现的服务集重跑 gen_deploy.py，三份产物逐字节比对（仅 C1-C4 全 PASS 时执行）。"""
    entry = {"name": "deterministic_regenerate", "status": "FAIL"}
    checks.append(entry)
    if not c1to4_pass:
        entry["status"] = "SKIP"
        entry["detail"] = "C1-C4 未全 PASS，按契约跳过重生成比对"
        return
    gen = find_gen_deploy(pack)
    if gen is None:
        entry["detail"] = ("未定位到 gen_deploy.py（已从包目录沿祖先链向上查找，"
                           "并回退校验器同目录）；无法复核确定性")
        return
    svc_csv = ",".join(catalog_order(services or []))
    tmp = tempfile.mkdtemp(prefix="deploy-pack-regen-")
    try:
        cmd = [sys.executable, gen, "--services", svc_csv, "--out", tmp]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=REGEN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            entry["detail"] = "gen_deploy.py 重跑超时（>%ds）" % REGEN_TIMEOUT_S
            return
        if r.returncode != 0:
            entry["detail"] = ("重跑失败: exit=%d; stderr=%s"
                               % (r.returncode, r.stderr.strip()[:200]))
            return
        diffs = []
        for fn in PACK_FILES:
            a = os.path.join(pack, fn)
            b = os.path.join(tmp, fn)
            ra, ea = read_text(a)
            rb, eb = read_text(b)
            if ea or eb:
                diffs.append("%s（%s）" % (fn, ea or eb))
                continue
            with open(a, "rb") as f:
                ba = f.read()
            with open(b, "rb") as f:
                bb = f.read()
            if ba != bb:
                la, lb = ra.splitlines(), rb.splitlines()
                first = next((i + 1 for i, (x, y) in enumerate(zip(la, lb)) if x != y),
                             min(len(la), len(lb)) + 1)
                diffs.append("%s（首个差异行 #%d）" % (fn, first))
        if not diffs:
            entry["status"] = "PASS"
            entry["detail"] = ("以服务集 [%s] 重跑 gen_deploy.py，三件套逐字节一致（确定性成立）"
                               % svc_csv)
        else:
            entry["detail"] = "重生成产物与包不一致: %s" % "; ".join(diffs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(description="三服务部署包校验器（C1-C7）")
    ap.add_argument("--pack", required=True, help="部署包目录（含三件套）")
    ap.add_argument("--services", default=",".join(EXPECTED_SERVICES),
                    help="期望服务集（缺省 = CATALOG 目录序三服务）")
    ap.add_argument("--out", default=None, help="校验报告 JSON 输出路径")
    args = ap.parse_args(argv)

    pack = os.path.abspath(args.pack)
    if not os.path.isdir(pack):
        print("[VALIDATE-FAIL] --pack 不是目录: %s" % pack, file=sys.stderr)
        return 2
    items = [p.strip() for p in (args.services or "").split(",") if p.strip()]
    unknown = [p for p in items if p not in EXPECTED_SERVICES]
    if not items or unknown:
        print("[VALIDATE-FAIL] 非法 --services: '%s'（未知: %s），可用值: %s"
              % (args.services, ", ".join(unknown) or "空", ", ".join(EXPECTED_SERVICES)),
              file=sys.stderr)
        return 2
    expected = catalog_order(items)

    checks = []
    doc, services = c1_compose_safe_load(pack, checks)
    c2_services_exact(services, expected, checks)
    c3_env_consistent(pack, doc, checks)
    c4_no_hardcoded_secrets(pack, doc, checks)
    c1to4_pass = all(c["status"] == "PASS" for c in checks[:4])
    c5_wiring(pack, doc, services, expected, checks)
    c6_deploy_md(pack, expected, checks)
    c7_deterministic_regen(pack, services, c1to4_pass, checks)

    n_pass = sum(1 for c in checks if c["status"] == "PASS")
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    n_skip = sum(1 for c in checks if c["status"] == "SKIP")
    verdict = "ALL GREEN" if n_fail == 0 else "FAILED"
    report = {
        "tool": "validate.py",
        "asset": ASSET,
        "pack": pack,
        "expected_services": expected,
        "verdict": verdict,
        "summary": {"pass": n_pass, "fail": n_fail, "skip": n_skip},
        "checks": checks,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out_path = os.path.abspath(args.out)
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
