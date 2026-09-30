#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — deploy-pack 部署包校验器（oracle 验收门）

用法:
    python validate.py --pack <部署包目录> [--services asr,minutes,todo] [--out <报告.json>]
    --out 缺省: <脚本所在目录>/out/validate.json
    stdout:  逐项 [PASS]/[FAIL]/[SKIP] <name>: <detail> + 汇总行（ALL GREEN ✓ / FAILED ✗）
    退出码:  0 = 全过（SKIP 不计失败）；1 = 任一 FAIL；2 = 参数非法

七项检查（C1-C4 为验收主门；C7 仅在 C1-C4 全 PASS 时执行）:
    C1 compose_safe_load         docker-compose.yml 存在且可被 yaml.safe_load 解析
    C2 services_exact            compose 服务集与 --services 期望集完全一致（缺省 asr,minutes,todo 三服务齐全）
    C3 env_consistent            .env.example 变量集 == compose ${} 引用集（双向），
                                 且 compose 内联缺省值与 .env 值一致（防漂移）
    C4 no_hardcoded_secrets      三份产物逐行扫描：密钥名必须用 ${} 引用（不得字面量赋值）、
                                 不得出现凭据形态字面量（sk-/AKIA/ghp_/xox-/PEM/JWT/长HEX）
    C5 wiring_asr_minutes        asr.ASR_OUTPUT_DIR 与 minutes.MINUTES_INPUT_DIR 同值且 compose 双侧接线；
                                 服务集不含 asr+minutes 时 SKIP
    C6 deploy_md_three_cmds      DEPLOY.md 存在且含三命令要素（复制 env / compose up / 健康检查）
    C7 deterministic_regenerate  以包内发现的服务集重跑 gen_deploy.py，三份产物逐字节一致
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import yaml  # PyYAML，本机实测 6.0.3

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gen_deploy import CATALOG, PACK_FILES, WIRING  # noqa: E402  单一事实来源

TOOL = "validate.py"
ASSET = "skillfactory/v5/assets/deploy-pack/oracle"
DEFAULT_SERVICES = ",".join(CATALOG)

# compose ${VAR} / ${VAR:-default} 引用
REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

# ---- C4: 密钥相关模式 ------------------------------------------------------
# 密钥名令牌（对 key 归一化后做子串判断）
SECRET_KEY_TOKENS = ("apikey", "secret", "token", "password", "passwd",
                     "accesskey", "privatekey", "credential")
# 行首 key[:=]value 形态（compose environment / dotenv 赋值行）
SECRET_KEY_RE = re.compile(r"^\s*\"?([A-Za-z_][A-Za-z0-9_-]*)\"?\s*[:=]\s*(.+?)\s*$")
# 凭据形态字面量（命中所给样例均为明显假串，非可用凭据）
CRED_SHAPES = (
    ("sk-形态密钥", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("AWS-AKID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("PEM-私钥", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}")),
    ("长HEX字面量", re.compile(r"\b[0-9a-fA-F]{40,}\b")),
)
# 合法占位值（<...> / ${...} / change-me / your_* / 空）
PLACEHOLDER_VALUE_RE = re.compile(r"^(<[^>]*>|\$\{.*\}|change-?me\S*|your[_-].*)?$", re.I)


def parse_env_file(path: Path) -> dict:
    """极简 dotenv 解析：仅 KEY=VALUE 行，忽略空行与 # 注释。"""
    env = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="deploy-pack 校验器")
    ap.add_argument("--pack", required=True, help="部署包目录（含 docker-compose.yml 等）")
    ap.add_argument("--services", default=DEFAULT_SERVICES,
                    help="期望服务集，逗号分隔（缺省 %s）" % DEFAULT_SERVICES)
    ap.add_argument("--out", default=str(HERE / "out" / "validate.json"),
                    help="校验报告 JSON 输出路径")
    a = ap.parse_args(argv)

    expected = [x.strip() for x in a.services.split(",") if x.strip()]
    unknown = [s for s in expected if s not in CATALOG]
    if not expected or unknown:
        print("[VALIDATE-FAIL] 非法 --services: %r；可用: %s" % (a.services, ",".join(CATALOG)),
              file=sys.stderr)
        return 2

    pack = Path(a.pack)
    results = []

    def add(name, status, detail=""):
        results.append({"name": name, "status": status, "detail": detail})
        print("[%s] %s: %s" % (status, name, detail))

    # ---- C1 compose_safe_load ---------------------------------------------
    compose_path = pack / "docker-compose.yml"
    data = None
    found = []
    if not compose_path.is_file():
        add("C1 compose_safe_load", "FAIL", "缺文件 %s" % compose_path)
    else:
        try:
            data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("services"), dict):
                found = sorted(data["services"].keys())
                add("C1 compose_safe_load", "PASS", "safe_load 通过; services=%s" % found)
            else:
                add("C1 compose_safe_load", "FAIL",
                    "safe_load 通过但顶层缺 services 映射（got %s）" % type(data).__name__)
                data = None
        except Exception as e:
            first = str(e).splitlines()[0] if str(e) else ""
            add("C1 compose_safe_load", "FAIL",
                "yaml.safe_load 异常: %s: %s" % (type(e).__name__, first))
            data = None

    # ---- C2 services_exact --------------------------------------------------
    if data is None:
        add("C2 services_exact", "SKIP", "依赖 C1 未通过")
    else:
        missing = [s for s in expected if s not in data["services"]]
        extra = [s for s in found if s not in expected]
        ok = not missing and not extra
        add("C2 services_exact", "PASS" if ok else "FAIL",
            "期望=%s 实际=%s 缺=%s 多=%s" % (sorted(expected), found, missing, extra))

    # ---- C3 env_consistent ----------------------------------------------------
    env_path = pack / ".env.example"
    env = parse_env_file(env_path)
    if data is None:
        add("C3 env_consistent", "SKIP", "依赖 C1 未通过")
    elif not env_path.is_file():
        add("C3 env_consistent", "FAIL", "缺文件 %s" % env_path)
    else:
        refs = {}  # var -> 内联缺省值（无则 None）
        for s in iter_strings(data):
            for m in REF_RE.finditer(s):
                refs.setdefault(m.group(1), m.group(2))
        missing_in_env = sorted(set(refs) - set(env))
        unused_env = sorted(set(env) - set(refs))
        drift = ["%s(.env=%r,compose缺省=%r)" % (v, env[v], refs[v])
                 for v, d in refs.items()
                 if d is not None and v in env
                 and not PLACEHOLDER_VALUE_RE.match(env[v]) and env[v] != d]
        ok = not missing_in_env and not unused_env and not drift
        add("C3 env_consistent", "PASS" if ok else "FAIL",
            "compose引用 %d 个/.env 定义 %d 个; compose引用而.env缺=%s; .env多出=%s; 缺省值漂移=%s"
            % (len(refs), len(env), missing_in_env, unused_env, drift))

    # ---- C4 no_hardcoded_secrets ---------------------------------------------
    viol = []
    scanned = []
    for fn in PACK_FILES:
        p = pack / fn
        if not p.is_file():
            continue
        scanned.append(fn)
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if fn in ("docker-compose.yml", ".env.example"):
                m = SECRET_KEY_RE.match(line)
                if m:
                    key_norm = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
                    if any(t in key_norm for t in SECRET_KEY_TOKENS):
                        val = m.group(2).strip().strip("\"'")
                        if not val.startswith("$") and not PLACEHOLDER_VALUE_RE.match(val):
                            viol.append("%s:%d 密钥名 %s 使用字面量值" % (fn, i, m.group(1)))
            for shape_name, rx in CRED_SHAPES:
                if rx.search(line):
                    viol.append("%s:%d 凭据形态字面量(%s)" % (fn, i, shape_name))
    add("C4 no_hardcoded_secrets", "PASS" if not viol else "FAIL",
        "逐行扫描 %s; 命中 %d 处%s" % ("/".join(scanned) or "<无文件>", len(viol),
                                       ("; " + "; ".join(viol[:5])) if viol else ""))

    # ---- C5 wiring_asr_minutes -------------------------------------------------
    if data is None or "asr" not in found or "minutes" not in found:
        add("C5 wiring_asr_minutes", "SKIP", "服务集不含 asr+minutes，接线检查不适用")
    else:
        (prod_svc, prod_var), (cons_svc, cons_var) = WIRING
        problems = []
        p_val, c_val = env.get(prod_var), env.get(cons_var)
        if p_val is None:
            problems.append(".env 缺 %s" % prod_var)
        if c_val is None:
            problems.append(".env 缺 %s" % cons_var)
        if p_val is not None and c_val is not None and p_val != c_val:
            problems.append("路径不同: %s=%r vs %s=%r" % (prod_var, p_val, cons_var, c_val))
        a_env = (data["services"].get(prod_svc) or {}).get("environment") or {}
        m_env = (data["services"].get(cons_svc) or {}).get("environment") or {}
        if prod_var not in a_env:
            problems.append("compose %s.environment 未接线 %s" % (prod_svc, prod_var))
        if cons_var not in m_env:
            problems.append("compose %s.environment 未接线 %s" % (cons_svc, cons_var))
        ok = not problems
        add("C5 wiring_asr_minutes", "PASS" if ok else "FAIL",
            ("asr.%s == minutes.%s == %r" % (prod_var, cons_var, p_val)) if ok
            else "; ".join(problems))

    # ---- C6 deploy_md_three_cmds -------------------------------------------------
    md_path = pack / "DEPLOY.md"
    if not md_path.is_file():
        add("C6 deploy_md_three_cmds", "FAIL", "缺文件 %s" % md_path)
    else:
        text = md_path.read_text(encoding="utf-8")
        need = [".env.example .env", "docker compose up -d", "docker compose ps", "healthz"]
        absent = [n for n in need if n not in text]
        add("C6 deploy_md_three_cmds", "PASS" if not absent else "FAIL",
            ("三命令要素齐备（复制env/compose up/compose ps/healthz）" if not absent
             else "缺要素: %s" % absent))

    # ---- C7 deterministic_regenerate ----------------------------------------------
    first4 = [r["status"] for r in results[:4]]
    if any(s != "PASS" for s in first4):
        add("C7 deterministic_regenerate", "SKIP", "依赖 C1-C4 未全 PASS（%s）" % first4)
    else:
        tmp = Path(tempfile.mkdtemp(prefix="deploy-pack-regen-"))
        try:
            cmd = [sys.executable, str(HERE / "gen_deploy.py"),
                   "--services", ",".join(found), "--out", str(tmp)]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                add("C7 deterministic_regenerate", "FAIL",
                    "重生成 exit=%d; stderr=%s" % (r.returncode, r.stderr.strip()[:200]))
            else:
                diffs = []
                for fn in PACK_FILES:
                    b1 = (pack / fn).read_bytes() if (pack / fn).is_file() else None
                    b2 = (tmp / fn).read_bytes() if (tmp / fn).is_file() else None
                    if b1 != b2:
                        diffs.append(fn)
                extra = sorted(set(p.name for p in tmp.iterdir()) - set(PACK_FILES))
                ok = not diffs and not extra
                add("C7 deterministic_regenerate", "PASS" if ok else "FAIL",
                    ("以服务集 %r 重跑 gen_deploy.py，三份产物逐字节一致" % found) if ok
                    else ("字节差异=%s; 重生成目录多出=%s" % (diffs, extra)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---- 汇总与报告 -----------------------------------------------------------------
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_skip = sum(1 for r in results if r["status"] == "SKIP")
    verdict = "ALL GREEN" if n_fail == 0 else "FAILED"

    report = {
        "tool": TOOL,
        "asset": ASSET,
        "pack": str(pack.resolve()),
        "services_expected": sorted(expected),
        "services_found": found if data else None,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "checks": results,
        "summary": {"pass": n_pass, "fail": n_fail, "skip": n_skip},
        "verdict": verdict,
    }
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    print("[SUM] %s — %d pass / %d fail / %d skip; 报告: %s"
          % (verdict, n_pass, n_fail, n_skip, out_path))
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
