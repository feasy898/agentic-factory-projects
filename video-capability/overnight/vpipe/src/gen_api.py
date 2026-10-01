#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_api.py — vpipe API 生成模块：MiniMax Design H3 客户端
（vpipe SPEC.md 模块 2；改造自今晚已验证的 overnight/数据/run_api_matrix.py，
 该执行器 2026-09-29 实跑 46/46 终态成功、实扣 14,280 积分，见 overnight/数据/metadata.json）。

契约: 输入=contracts/shot.schema.json 合规的镜头 JSON（--shots 传目录/*.json 或 .jsonl）；
      输出=clip mp4 + 每条终态记录（api_results 式 jsonl）+ contracts/asset_manifest 登记条目。
      不 import 任何 vpipe 兄弟模块。
DTO 白名单（D:/agent-knowledge/07-minimax-design-api.md，实测勘误已吸收）:
  - 顶层仅 backend/model_id/prompt/filename/image_paths/params/source_tool；
    多传字段逐个报 "property X should not exist"（一次列全）。
  - 参考图走【顶层 image_paths】（首图=人物参考）；params.reference_images 被静默忽略！
  - params 全字符串；漏 resolution → 500；校验发生在扣费前，可安全试参。
积分守卫: --credit-cap（默认 40000）硬上限；baseline 首跑记入 state；每条提交前查钱包，
  「已耗>上限」与「已耗+预估>上限」双重拦截，触发即 exit 3。
断点续跑: results jsonl 里已有终态的 rid 跳过（--retry-failed 可重跑失败条）。
URL 安全（发请求前校验）: 默认基址为本机授权网关 http://127.0.0.1:8001（MiniMax Design，
  免鉴权，架构既定）；--base-url 覆盖时强制 http/https 且拒绝环回/私有/保留地址，
  内网部署须显式 --allow-private / --allow-loopback 放行。

用法:
  python gen_api.py --shots shots/ --out-dir out/ --credit-cap 40000 [--dry-run] [--only S1] [--retry-failed]
  python gen_api.py make-shots --prompts ../数据/prompts.json --out-dir shots/   # 今晚矩阵→Shot 契约适配器
"""
import argparse
import datetime
import hashlib
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
SHOT_SCHEMA = HERE.parent / "contracts" / "shot.schema.json"

DEFAULT_BASE = "http://127.0.0.1:8001"          # 本机授权网关（07 手册 §一，免鉴权）
APP_EXE = r"D:\d\MiniMax Design\current\MiniMax Design.exe"
BACKEND = "minimax_v3"
SOURCE_TOOL = "hub_generate_video:vpipe:gen_api"
BASE_PARAMS = {                                  # 07 手册 §三 已验证参数集；全字符串
    "image_mode": "reference",
    "duration": "5",
    "resolution": "768P",
    "aspect_ratio": "9:16",
    "generate_audio": "true",
}
MODEL_WH = {"480P": (480, 832), "768P": (768, 1344), "2K": (1088, 1920)}
EST_PER_CLIP = 280          # 56 积分/s × 5s（/api/v1/billing/pricing 实测；无折扣保守估）
TIMEOUT = 30
POLL_INTERVAL = 15
POLL_TIMEOUT = 900
POLL_ERR_LIMIT = 5
SUBMIT_RETRY_DELAY = 20


def log(msg):
    print(f"[gen_api {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------- URL 安全校验（发请求前） ----------------
def _ip_allowed(ip, allow_private, allow_loopback):
    x = ipaddress.ip_address(ip)
    if x.is_loopback:
        return allow_loopback, "loopback"
    if x.is_private or x.is_link_local or x.is_reserved or x.is_multicast or x.is_unspecified:
        return allow_private, "private/reserved"
    return True, "global"


def validate_base_url(url, allow_private=False, allow_loopback=False):
    """http/https 白名单 + host 校验（拒绝环回/私有/保留，除非显式放行）。
    返回 (ok, reason)。默认网关 127.0.0.1 的放行发生在调用点（授权端点，非用户输入）。"""
    try:
        u = urlparse(url)
    except Exception as e:
        return False, f"URL 解析失败: {e}"
    if u.scheme not in ("http", "https"):
        return False, f"scheme 必须是 http/https，得到 {u.scheme!r}"
    if u.username or u.password:
        return False, "不允许携带 userinfo"
    host = u.hostname
    if not host:
        return False, "缺少 host"
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return False, f"host 解析失败: {e}"
    for info in infos:
        ip = info[4][0]
        # IPv6 数组尾部的 %scope 去掉
        ip = ip.split("%", 1)[0]
        ok, kind = _ip_allowed(ip, allow_private, allow_loopback)
        if not ok:
            return False, f"host {host} → {ip} 是{kind}地址（未显式放行）"
    return True, "ok"


def make_session(base_url, allow_private, allow_loopback, trusted_default=True):
    """构造已校验的 HTTP session。默认网关是架构内授权端点（trusted_default=True 放行环回）。"""
    ok, reason = validate_base_url(base_url, allow_private,
                                   allow_loopback or (trusted_default and base_url == DEFAULT_BASE))
    if not ok:
        raise ValueError(f"--base-url 校验失败: {reason}")
    import requests
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    s.base_url = base_url.rstrip("/")
    return s


# ---------------- 网关基础（run_api_matrix.py 已验证逻辑） ----------------
def health_ok(sess):
    try:
        r = sess.get(sess.base_url + "/api/health", timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def ensure_app(sess):
    if health_ok(sess):
        log("[gateway] /api/health ok")
        return True
    log("[gateway] 未响应，尝试启动 MiniMax Design ...")
    try:
        subprocess.Popen(["powershell", "-Command",
                          f"Start-Process '{APP_EXE}' -WindowStyle Minimized"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"[gateway] 启动命令失败: {e}")
    for i in range(12):
        time.sleep(10)
        if health_ok(sess):
            log(f"[gateway] 已恢复（等待 {(i + 1) * 10}s）")
            return True
    return False


def wallet_credit(sess):
    r = sess.get(sess.base_url + "/api/v1/credit/wallet", timeout=TIMEOUT)
    r.raise_for_status()
    vals = []
    for w in r.json().get("wallets") or []:
        try:
            vals.append(int(str(w.get("total_credit", "0"))))
        except Exception:
            pass
    if not vals:
        raise RuntimeError("wallet 解析失败")
    return max(vals)


def get_workspace_dir(sess):
    fallback = Path(r"D:/d/MiniMax Design Data/output_files")
    try:
        r = sess.get(sess.base_url + "/api/workspace", timeout=TIMEOUT)
        d = r.json()
        if isinstance(d, dict):
            for k in ("dir", "workspace", "workspace_dir", "output_dir"):
                if d.get(k):
                    return Path(d[k])
    except Exception:
        pass
    return fallback


# ---------------- Shot → DTO（白名单） ----------------
def validate_shot(shot):
    try:
        import jsonschema
        schema = json.loads(SHOT_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(shot, schema)
        return True, None
    except ImportError:
        miss = [k for k in ("schema_version", "shot_id", "prompt", "duration_s", "aspect")
                if k not in shot]
        return not miss, f"jsonschema 不可用退回 required 检查，缺 {miss}" if miss else None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def build_payload(shot, model_id, include_seed, refs_resolved):
    """Shot 契约 → DTO 白名单 payload。多余信息（negative_prompt 等）显式丢弃并返回忽略清单。"""
    params = dict(BASE_PARAMS)
    params["duration"] = str(int(shot["duration_s"]))
    params["aspect_ratio"] = shot["aspect"]
    if shot.get("resolution"):
        params["resolution"] = shot["resolution"]
    params["generate_audio"] = "true" if (shot.get("audio") or {}).get("generate", True) else "false"
    if include_seed:
        params["seed"] = str(shot.get("seed", 42))
    ignored = []
    if shot.get("negative_prompt"):
        ignored.append("negative_prompt(H3 无此参数)")   # 07 手册 DTO 白名单
    payload = {
        "backend": BACKEND,
        "model_id": model_id,
        "prompt": shot["prompt"][:7000],
        "filename": f"{shot['shot_id']}_{model_id.replace('MiniMax-', '')}.mp4",
        "image_paths": list(refs_resolved),
        "params": params,
        "source_tool": SOURCE_TOOL,
    }
    return payload, ignored


def probe_seed(sess, state):
    """0 成本探测 params.seed 是否被 DTO 拒绝（run_api_matrix.py:198-256 已验证逻辑）。"""
    if state.get("seed_probe"):
        return state["seed_probe"]
    payload = {"backend": BACKEND, "model_id": "MiniMax-H3",
               "prompt": "[seed-probe] DTO 白名单探测，不应产生真实生成",
               "filename": "seed_probe.mp4", "image_paths": [],
               "params": dict(BASE_PARAMS, seed="42", unknown_probe_key_zzz="1"),
               "source_tool": SOURCE_TOOL}
    r = sess.post(sess.base_url + "/api/generate/video/submit", json=payload, timeout=TIMEOUT)
    probe = {"http": r.status_code, "response": r.text[:500], "at": now()}
    if r.status_code in (200, 201):
        task_id = None
        try:
            task_id = r.json().get("task_id")
        except Exception:
            pass
        probe.update(unexpected_accepted=True, task_id=task_id, dto_rejected=False,
                     decision="send_seed_with_verify(探测意外通过，已尝试取消；扣费风险≤224)")
        try:
            if task_id:
                sess.post(sess.base_url + "/api/generation/cancel",
                          json={"task_id": task_id}, timeout=TIMEOUT)
                probe["cancel_attempted"] = True
        except Exception as e:
            probe["cancel_error"] = str(e)
    else:
        msgs = []
        try:
            m = r.json().get("message")
            msgs = m if isinstance(m, list) else [str(m)]
        except Exception:
            msgs = [r.text]
        unknown = []
        for x in msgs:
            unknown += re.findall(r"property\s+\"?(\S+?)\"?\s+should not exist", str(x))
        probe["unknown_keys"] = unknown
        probe["dto_rejected"] = "seed" in unknown
        probe["decision"] = ("omit_seed(DTO 拒绝 seed → H3 无种子控制)" if probe["dto_rejected"]
                             else "send_seed_with_verify(未知键清单不含 seed)")
    state["seed_probe"] = probe
    state["seed_send_enabled"] = not probe["dto_rejected"]
    log(f"[seed-probe] HTTP {r.status_code} unknown={probe.get('unknown_keys')} 决策={probe['decision']}")
    return probe


def poll_task(sess, task_id):
    t0 = time.time()
    errs = 0
    while time.time() - t0 < POLL_TIMEOUT:
        try:
            r = sess.get(sess.base_url + f"/api/generate/tasks/{task_id}/query", timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            errs = 0
        except Exception as e:
            errs += 1
            if errs >= POLL_ERR_LIMIT:
                return {"status": "poll_error", "error": f"{type(e).__name__}: {e}"}
            time.sleep(POLL_INTERVAL)
            continue
        if data.get("status") in ("succeeded", "failed"):
            return data
        time.sleep(POLL_INTERVAL)
    return {"status": "poll_timeout", "error": f"超过 {POLL_TIMEOUT}s 未到终态"}


# ---------------- 断点续跑 + 终态记录 ----------------
def load_done(results_file):
    done = {}
    if results_file.exists():
        for line in results_file.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("terminal"):
                done[rec.get("rid") or rec.get("id")] = rec
    return done


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ---------------- 主流程 ----------------
def run_generate(args):
    shots = load_shots(args.shots)
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        shots = [s for s in shots if s["shot_id"] in want]
    if not shots:
        log("[FATAL] 过滤后没有可跑的 Shot")
        return 1
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_file = out_dir / "api_results.jsonl"
    state_file = out_dir / "api_state.json"
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}

    try:
        sess = make_session(args.base_url, args.allow_private, args.allow_loopback)
    except ValueError as e:
        log(f"[FATAL] {e}")
        return 2
    if not ensure_app(sess):
        log("[FATAL] 网关不可用（已尝试重启）→ 按方案§4 降级：API 侧记 N/A")
        return 2

    # 积分守卫
    try:
        cur = wallet_credit(sess)
    except Exception as e:
        log(f"[FATAL] 钱包查询失败: {e}")
        return 2
    if state.get("baseline_credit") is None:
        state["baseline_credit"] = cur
    baseline = state["baseline_credit"]
    spent = baseline - cur
    log(f"[wallet] 当前={cur} baseline={baseline} 已耗={spent} 上限={args.credit_cap}")
    if spent > args.credit_cap:
        log("[STOP] 已超积分上限")
        return 3

    if not args.skip_seed_probe:
        probe_seed(sess, state)
    state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    ws_dir = get_workspace_dir(sess)
    done = load_done(results_file)
    processed = ok_cnt = fail_cnt = 0

    for shot in shots:
        sid = shot["shot_id"]
        rid = f"{sid}@{args.model}"
        prev = done.get(rid)
        if prev and (not args.retry_failed or prev.get("status") == "succeeded"):
            log(f"[skip] {rid} 已有终态 {prev['status']}")
            continue
        # 参考图：Shot.characters[].ref_image → 复制进 hub 工作区（顶层 image_paths 用相对路径）
        refs = []
        ref_fail = False
        for ch in shot.get("characters") or []:
            ref = ch.get("ref_image")
            if not ref:
                continue
            src = Path(ref)
            if not src.exists():
                src = Path(args.refs_dir) / Path(ref).name
            if not src.exists():
                append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                            "status": "reference_unavailable",
                                            "error": f"定妆照 {ref} 不可得", "at": now()})
                done[rid] = True
                ref_fail = True
                break
            dst = ws_dir / src.name
            if not dst.exists():
                shutil.copyfile(src, dst)
            refs.append(src.name)
        if ref_fail:
            continue
        # 积分守卫（每条提交前）
        try:
            cb = wallet_credit(sess)
            if baseline - cb + EST_PER_CLIP > args.credit_cap:
                log("[STOP] 预估下一条将越上限，保守停止")
                state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                return 3
        except Exception as e:
            log(f"[wallet] 查询失败（继续，不阻塞）: {e}")
            cb = None
        payload, ignored = build_payload(shot, args.model, bool(state.get("seed_send_enabled")), refs)
        if ignored:
            log(f"[dto] {rid} 忽略字段: {ignored}")
        log(f"[run] {rid} seed={shot.get('seed', 42)} seed_sent={bool(state.get('seed_send_enabled'))} refs={refs}")
        t0 = time.time()
        try:
            r = sess.post(sess.base_url + "/api/generate/video/submit", json=payload, timeout=TIMEOUT)
        except Exception as e:
            append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                        "status": "submit_error", "error": str(e)[:300], "at": now()})
            fail_cnt += 1
            continue
        if r.status_code not in (200, 201):
            append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                        "status": "submit_error",
                                        "error": f"submit_http_{r.status_code}: {r.text[:300]}",
                                        "at": now()})
            fail_cnt += 1
            continue
        try:
            task_id = r.json().get("task_id")
        except Exception:
            task_id = None
        if not task_id:
            append_jsonl(results_file, {"terminal": True, "rid": rid, "shot_id": sid,
                                        "status": "submit_error", "error": "no task_id", "at": now()})
            fail_cnt += 1
            continue
        fin = poll_task(sess, task_id)
        elapsed = round(time.time() - t0, 1)
        ca = None
        try:
            ca = wallet_credit(sess)
        except Exception:
            pass
        rec = {"terminal": True, "rid": rid, "shot_id": sid, "model": args.model,
               "backend": BACKEND, "seed": shot.get("seed", 42),
               "seed_sent": bool(state.get("seed_send_enabled")), "task_id": task_id,
               "status": fin.get("status"), "elapsed_s": elapsed,
               "credit_before": cb, "credit_after": ca,
               "credit_cost": (cb - ca) if (cb is not None and ca is not None) else None,
               "ignored_fields": ignored, "at": now()}
        if fin.get("status") == "succeeded":
            result = fin.get("result") or {}
            src = ws_dir / result.get("path", "")
            if src.exists():
                dst = out_dir / f"{rid}.mp4"
                shutil.copyfile(src, dst)
                rec.update(clip_file=str(dst), sha256=sha256_file(dst),
                           size_bytes=dst.stat().st_size,
                           probe={k: result.get(k) for k in ("width", "height", "duration", "fps")})
            ok_cnt += 1
            log(f"[ok ] {rid} -> {result.get('path')} ({elapsed}s)")
        else:
            rec["error"] = str(fin.get("error"))[:500]
            fail_cnt += 1
            log(f"[FAIL] {rid} {fin.get('status')}: {str(fin.get('error'))[:200]}")
        append_jsonl(results_file, rec)
        done[rid] = rec
        processed += 1

    log(f"[done] 本次处理 {processed}（成功 {ok_cnt}/失败 {fail_cnt}）；结果: {results_file}")
    return 0


def load_shots(spec):
    """--shots：目录(*.json) 或 .jsonl。逐条契约校验，坏条目拒绝并计数。"""
    p = Path(spec)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    shots, bad = [], []
    for f in files:
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            if f.suffix == ".jsonl":
                s_list = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            else:
                bad.append(f.name)
                continue
        else:
            s_list = [s]
        for s in s_list:
            ok, err = validate_shot(s)
            if ok:
                shots.append(s)
            else:
                bad.append(f"{f.name}: {err}")
    if bad:
        log(f"[WARN] {len(bad)} 条未过契约校验被拒: {bad[:5]}")
    return shots


# ---------------- 适配器：今晚 prompts.json → Shot 契约 JSON ----------------
def cmd_make_shots(args):
    """一次性适配器（非契约组件）：把今晚 9 轴矩阵 prompts.json 转成 Shot JSON 目录。
    字段映射：id→shot_id, axis→axis, prompt_zh→prompt, seed→seed, axis→G7 的
    reference_characters 映射 characters[].ref_image（references_api/ 本地归档）。"""
    data = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    chars = {c.get("filename"): c for c in data.get("reference_characters", [])}
    n = 0
    for p in data.get("prompts", []):
        characters = []
        for ref in p.get("references") or []:
            fn = ref["filename"]
            local = Path(args.refs_dir) / fn
            characters.append({"char_id": chars.get(fn, {}).get("char_id", Path(fn).stem),
                               "desc": chars.get(fn, {}).get("desc", ""),
                               "ref_image": str(local) if local.exists() else None})
        shot = {"schema_version": "1.0", "shot_id": p["id"], "axis": p.get("axis", "OTHER"),
                "duration_s": 5, "aspect": "9:16", "resolution": "768P",
                "prompt": p["prompt_zh"], "seed": int(p.get("seed", 42)),
                "characters": characters,
                "audio": {"generate": True},
                "engine_hint": {"preferred": "api", "model": "MiniMax-H3"}}
        (out_dir / f"{p['id']}.json").write_text(
            json.dumps(shot, ensure_ascii=False, indent=1), encoding="utf-8")
        n += 1
    log(f"[make-shots] {n} 条 Shot 契约 JSON → {out_dir}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "make-shots":
        ap = argparse.ArgumentParser(description="今晚 prompts.json → Shot 契约适配器")
        ap.add_argument("--prompts", required=True)
        ap.add_argument("--out-dir", required=True)
        ap.add_argument("--refs-dir", default="../数据/references_api")
        return cmd_make_shots(ap.parse_args(sys.argv[2:]))
    ap = argparse.ArgumentParser(description="vpipe gen_api：MiniMax Design H3 客户端")
    ap.add_argument("--shots", required=True, help="Shot 契约目录(*.json)或 .jsonl")
    ap.add_argument("--out-dir", default="./out_api")
    ap.add_argument("--refs-dir", default="../数据/references_api", help="定妆照本地归档目录")
    ap.add_argument("--model", default="MiniMax-H3")
    ap.add_argument("--credit-cap", type=int, default=40000, help="本次测试积分硬上限")
    ap.add_argument("--base-url", default=DEFAULT_BASE, help="网关基址（覆盖时强制 http/https 且拒内网/保留地址）")
    ap.add_argument("--allow-private", action="store_true", help="允许私有网段基址（内网部署显式放行）")
    ap.add_argument("--allow-loopback", action="store_true", help="允许环回基址（默认网关外的本机端口）")
    ap.add_argument("--dry-run", action="store_true", help="只构建 payload 不发 HTTP（打印第一条）")
    ap.add_argument("--skip-seed-probe", action="store_true", help="跳过 seed DTO 探测（沿用 state 结论）")
    ap.add_argument("--only", default="", help="只跑指定 shot_id，逗号分隔")
    ap.add_argument("--retry-failed", action="store_true", help="失败条目重跑")
    args = ap.parse_args()
    if args.dry_run:
        shots = load_shots(args.shots)
        if not shots:
            return 1
        payload, ignored = build_payload(shots[0], args.model, False, [])
        print(json.dumps({"note": "dry-run：未发任何 HTTP", "n_shots": len(shots),
                          "sample_payload": payload, "ignored": ignored},
                         ensure_ascii=False, indent=2))
        return 0
    return run_generate(args)


if __name__ == "__main__":
    sys.exit(main())
