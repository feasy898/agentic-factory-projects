"""M8 回答质量评测（T7.1）：≥50 问答对 脱敏前后双答 × LLM-judge 对比 ≥95%。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m8_quality

exit 0 = 通过（真实上游离线 = DEFERRED，如实打印不计失败——与 e2e U8 同口径）。

被测链路（与 e2e U8 同拓扑的真实上游）::

    原文腿（脱敏前）: 本 eval ──直连──► 本地真实大模型服务 :9004
    脱敏腿（脱敏后）: 本 eval ──► 网关真实链路实例 :9011（仅绑 config/app.yaml 的
                                  internet_real/govcloud_real 两个真实 profiles）
                                  ──脱敏──► :9004 ──还原──► 客户端视图
    judge:            同一 :9004 服务对两条腿的答案各打 1-10 分（同裁判同 rubric）

检查项：
1. qa-set：问答对由合成生成器（benchmark.generator.qa）seed 确定性产出——双跑
   字节级一致；规模 ≥50；seeded 结构化值独立校验位复核；期望脱敏面经真实检测面
   复核（每个 seeded 值有 MASK finding、归一化目标一致）；期望路由经真实决策矩阵
   复核；零密级/注入面（不得 403）；
2. orig-leg：脱敏前原文直答（问题/指令与脱敏腿逐字节相同），答案非空、延迟入账；
3. masked-leg：经网关真实链路脱敏→真实推理→还原——200、路由符合决策矩阵、AI 标识
   尾注、客户端零占位符形状；收尾断言上游 ring buffer 全文（本轮仅脱敏腿）bytes 级
   零 seeded 原值（每一腿都确实被脱敏的硬证据）；
4. judge：2n 次评分全部可解析为 1-10 整数（同服务同 rubric，温度 0）；
5. quality-ratio：脱敏腿均分 / 原文腿均分 ≥ thresholds.QUALITY_RATIO_MIN（0.95）；
   未达标如实报数（逐对明细+逐类分解）并 FAIL；
6. report：data/bench/quality_report.json 落盘（分数比值 + F1 + 延迟分位 + 逐对明细）。

环境变量（默认即验收口径）：M8_QUALITY_PAIRS（默认 50，低于下限时 gate 如实 FAIL）、
M8_QUALITY_SEED（默认 qa.QA_SEED）。

探针/请求纪律（与 ops/e2e_smoke 同款，mimosa SSRF 门禁口径）：一切请求目标是
编译期字面量主机 ``127.0.0.1`` + int 钳制端口（:9004 服务根来自 config/app.yaml
仓库内契约文件）；无插值 URL/无重定向跟随/无外部输入进 URL——"动态 URL 进入
服务端请求"形态结构性不存在。
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import threading
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from audit.writer import SqliteAuditWriter  # noqa: E402
from benchmark.generator import qa as qa_gen  # noqa: E402
from common.config import (  # noqa: E402
    load_app_config,
    load_dept_keys,
    load_env_file,
    resolve_secret,
)
from evals import thresholds as th  # noqa: E402
from gateway.app import create_app  # noqa: E402
from masking.mapper import RESTORE_PATTERN, SessionRegistry  # noqa: E402
from routing.engine import decide  # noqa: E402

RESULTS: list[tuple[bool, str]] = []

# ── 固定拓扑常量（编译期字面量；与 config/app.yaml / dept_keys.yaml 对齐）──────
GATEWAY_PORT = 9011              # 真实链路网关实例（:9000/:9010 留给 e2e，错开）
GATEWAY_BASE = "http://127.0.0.1"
SESSION_ID = "sess_m8_quality"
DEMO_KEY = "dk_5e6f7a8b"         # 民政局演示 key（dept_keys.yaml 只存其 sha256）
AI_LABEL = "本内容由AI生成"       # config/app.yaml ai_label

REAL_PROFILE_INTERNET = "internet_real"
REAL_PROFILE_GOVCLOUD = "govcloud_real"

ANSWER_MAX_TOKENS = 128          # 答案生成长度上限（答案要求简短）
JUDGE_MAX_TOKENS = 96            # 评分 JSON 长度上限
HEALTH_TIMEOUT_S = 5.0
CALL_TIMEOUT_S = 240.0           # 单次真实推理客户端总超时
HTTP_RETRIES = 2                 # 瞬时故障（隧道抖动/5xx）重试次数

REPORT_PATH = REPO_ROOT / "data" / "bench" / "quality_report.json"

#: 双腿共用的作答指令（逐字节相同——比较公平性前提；占位符照抄要求是
#: 「脱敏腿答案经还原回到原值」的机制说明，对原文腿无害）
ANSWER_INSTRUCTION = (
    "你是政务服务窗口助手。请只依据下面的材料回答问题，答案尽量简短。\n"
    "说明：材料中形如〔标签·编号〕的记号是敏感信息的替代码，"
    "如需在答案中引用其对应内容，请原样照抄该记号的全部字符，不要解释、不要拒答。\n"
)

JUDGE_PROMPT = """你是政务材料问答题的评分员。根据【材料】【问题】【参考答案】给【考生答案】打一个1到10的整数分。
评分标准：
- 9-10：关键信息与参考答案完全一致（编号/数字/名称逐字一致；允许标点、全半角或措辞格式差异）；
- 7-8：包含参考答案的全部关键信息且无错误，另有少量多余表述；
- 4-6：关键信息部分正确或部分缺失；
- 2-3：与问题相关但关键信息错误或大部分缺失；
- 1：拒答、编造或与问题无关。
材料：
{context}
问题：{question}
参考答案：{reference}
考生答案：{answer}
只输出一行JSON（不要输出其他内容）：{{"score": 1到10的整数, "reason": "不超过20字"}}"""


def _record(name: str, fn) -> None:
    try:
        detail = fn()
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _user_prompt(pair: qa_gen.QAPair) -> str:
    """双腿共用的 user 消息（逐字节相同）。"""
    return f"{ANSWER_INSTRUCTION}材料：\n{pair.context}\n\n问题：{pair.question}"


# ── 1. 问答对素材（合成生成器产出 + 契约复核）────────────────────────

def check_qa_set(ctx: dict[str, Any]) -> str:
    n = int(os.environ.get("M8_QUALITY_PAIRS", str(qa_gen.QA_PAIRS)))
    seed = int(os.environ.get("M8_QUALITY_SEED", str(qa_gen.QA_SEED)))
    # SHALLOW 调试口（显式 opt-in，摘要如实标注）：仅链路冒烟用，非验收口径——
    # 验收运行（默认，不设本变量）规模低于 thresholds.QUALITY_PAIRS_MIN 即 FAIL。
    shallow = os.environ.get("M8_QUALITY_ALLOW_SHALLOW") == "1"
    pairs_a = qa_gen.build_qa_pairs(seed=seed, n=n)
    pairs_b = qa_gen.build_qa_pairs(seed=seed, n=n)
    assert qa_gen.pairs_bytes(pairs_a) == qa_gen.pairs_bytes(pairs_b), \
        "same seed produced different pairs (determinism broken)"
    if len(pairs_a) < th.QUALITY_PAIRS_MIN:
        assert shallow, (
            f"pairs {len(pairs_a)} < QUALITY_PAIRS_MIN {th.QUALITY_PAIRS_MIN}"
            "（链路冒烟请显式设 M8_QUALITY_ALLOW_SHALLOW=1，验收运行不得设）")
        shallow_note = "SHALLOW(非验收口径)"
    else:
        shallow_note = ""
    kinds = Counter(p.kind for p in pairs_a)
    assert len(kinds) == min(len(pairs_a), len(qa_gen.QA_KIND_PLAN)), \
        f"kind coverage broken (round-robin plan): {dict(kinds)}"

    # seeded 值独立合法性 + 真实检测面契约（期望脱敏面/期望路由不得靠猜）
    from recognizers.models import EntityClass  # noqa: PLC0415
    from recognizers.pipeline import detect_full  # noqa: PLC0415

    bad_vals: list[str] = []
    for p in pairs_a:
        for etype, val in p.seeded:
            if not qa_gen.checksum_ok(etype, val):
                bad_vals.append(f"{p.qid}:{etype}")
    assert not bad_vals, f"seeded value checksum failures: {bad_vals[:5]}"

    upstream_for = {"INTERNET": REAL_PROFILE_INTERNET, "GOVCLOUD": REAL_PROFILE_GOVCLOUD}
    batch_min = ctx["cfg"].thresholds.batch_pii_to_govcloud
    for p in pairs_a:
        findings = detect_full(p.context + "\n" + p.question)
        assert not any(f.type in (EntityClass.CLASSIFICATION_MARK, EntityClass.INJECTION)
                       for f in findings), f"{p.qid}: 密级/注入面不得出现在素材里"
        for etype, val in p.seeded:
            hit = [f for f in findings if f.type.value == etype and f.action_hint == "MASK"
                   and (f.normalized == val or f.raw == val)]
            assert hit, f"{p.qid}: seeded {etype} 未被检测面 MASK（素材守则被破坏）: {val}"
        decision = decide(findings, upstream_for=upstream_for, batch_pii_min=batch_min)
        assert decision.route == p.expect_route, (
            f"{p.qid}: 期望路由 {p.expect_route} != 决策矩阵 {decision.route}")
        assert p.reference and p.reference.strip(), f"{p.qid}: 空参考答案"

    ctx["pairs"], ctx["seed"], ctx["n"] = pairs_a, seed, len(pairs_a)
    return (f"{len(pairs_a)} 对{shallow_note}（seed={seed}，双跑字节一致；类别 "
            f"{dict(sorted(kinds.items()))}；seeded 合法+检测面 MASK+路由契约全复核）")


# ── 真实上游环境门（与 e2e U8 同口径：离线 = DEFERRED 不计失败）───────────────

def _service_root(cfg: Any) -> str:
    by_name = {u.name: u for u in cfg.upstreams}
    base = by_name[REAL_PROFILE_INTERNET].base_url.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _service_ready(ctx: dict[str, Any]) -> tuple[bool, str]:
    root = _service_root(ctx["cfg"])
    try:
        health = httpx.get(f"{root}/health", timeout=HEALTH_TIMEOUT_S).json()
    except Exception as exc:  # noqa: BLE001 — 隧道/服务离线属环境状态
        return False, f"真实上游不可达（{root}/health: {type(exc).__name__}: {exc}）"
    if not isinstance(health, dict) or not health.get("loaded"):
        err = "" if not isinstance(health, dict) else str(health.get("error"))[:120]
        return False, f"真实上游未装载（{root} {err}）"
    ctx["root"], ctx["model"] = root, health.get("serve_model", "local-chat-8b")
    return True, f"loaded（{root}，模型 {ctx['model']}，GPU {health.get('device')}）"


# ── 请求原语（显式字面量主机 + 瞬时故障重试）────────────────────────────────

def _post_chat(client: httpx.Client, url: str, payload: dict[str, Any],
               headers: dict[str, str], *, what: str) -> httpx.Response:
    last = ""
    for attempt in range(HTTP_RETRIES + 1):
        try:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return resp
            last = f"status={resp.status_code} body={resp.text[:160]!r}"
            if resp.status_code < 500:
                break  # 4xx（拦截/参数）：非瞬时，如实失败
        except httpx.TransportError as exc:
            last = f"{type(exc).__name__}: {exc}"
        if attempt < HTTP_RETRIES:
            time.sleep(2.0 * (attempt + 1))
    raise AssertionError(f"{what}: {last}")


def _strip_ai_label(content: str, where: str) -> str:
    assert content.endswith(f"\n{AI_LABEL}"), f"{where}: AI 标识尾注缺失: {content[-40:]!r}"
    body = content[: -len(f"\n{AI_LABEL}")]
    assert body.strip(), f"{where}: 回复为空（仅标识行）"
    return body


# ── 2. 原文腿（脱敏前直答）─────────────────────────────────────────────────

def phase_orig(ctx: dict[str, Any]) -> str:
    root, model = ctx["root"], ctx["model"]
    key = resolve_secret(ctx["up_internet"].api_key_env)
    headers = {"Authorization": f"Bearer {key}"}
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=httpx.Timeout(CALL_TIMEOUT_S)) as client:
        for p in ctx["pairs"]:
            t0 = time.perf_counter()
            resp = _post_chat(client, f"{root}/v1/chat/completions", {
                "model": model,
                "messages": [{"role": "user", "content": _user_prompt(p)}],
                "temperature": 0, "max_tokens": ANSWER_MAX_TOKENS,
            }, headers, what=f"{p.qid}/orig")
            latency_ms = int((time.perf_counter() - t0) * 1000)
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            assert answer and answer.strip(), f"{p.qid}/orig: 空回复"
            out.append({"qid": p.qid, "answer": answer, "latency_ms": latency_ms,
                        "completion_tokens": data.get("usage", {}).get("completion_tokens", 0)})
    ctx["orig"] = out
    lat = sorted(r["latency_ms"] for r in out)
    return f"{len(out)} 对直答非空；延迟 mean={sum(lat) // len(lat)}ms p95={lat[int(0.95 * (len(lat) - 1))]}ms"


# ── 3. 脱敏腿（网关真实链路）───────────────────────────────────────────────

def _assert_port_free(port: int) -> None:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        if sock.connect_ex(("127.0.0.1", port)) != 0:
            return
    raise RuntimeError(f"port {port} already occupied（netstat -ano 自查），不自动清理")


def _start_real_gateway(ctx: dict[str, Any]) -> tuple[uvicorn.Server, threading.Thread, Path]:
    """真实链路独立网关实例：仅绑两个真实 profiles + 独立临时审计库（不碰 data/audit.db）。"""
    _assert_port_free(GATEWAY_PORT)
    cfg = ctx["cfg"].model_copy(deep=True)
    cfg.upstreams = [ctx["up_internet"].model_copy(deep=True),
                     ctx["up_gov"].model_copy(deep=True)]
    tmp_dir = REPO_ROOT / "tmp"
    tmp_dir.mkdir(exist_ok=True)
    audit_db = tmp_dir / "m8_quality_audit.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(audit_db) + suffix).unlink(missing_ok=True)
    app = create_app(cfg=cfg, mask_key=ctx["mask_key"], dept_key_digests=load_dept_keys(),
                     audit_store=SqliteAuditWriter(audit_db),
                     session_registry=SessionRegistry(ctx["mask_key"].encode("utf-8")))
    ctx["audit_gw"] = app.state.audit
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=GATEWAY_PORT,
        log_level="warning", log_config=None, access_log=False,
    ))
    thread = threading.Thread(target=server.run, name="anongw-m8-quality", daemon=True)
    thread.start()
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.3)
            if sock.connect_ex(("127.0.0.1", GATEWAY_PORT)) == 0:
                break
        time.sleep(0.2)
    else:
        raise RuntimeError("gateway:9011 未就绪")
    return server, thread, audit_db


def phase_masked(ctx: dict[str, Any]) -> str:
    pairs = ctx["pairs"]
    n = len(pairs)
    server, thread, audit_db = _start_real_gateway(ctx)
    client: httpx.Client | None = None
    try:
        # ring 复位：本轮之后的 /admin/text 只含脱敏腿（原文腿不进本轮断言面）
        httpx.post(f"{ctx['root']}/admin/reset", timeout=5.0)
        client = httpx.Client(base_url=f"{GATEWAY_BASE}:{GATEWAY_PORT}",
                              timeout=httpx.Timeout(CALL_TIMEOUT_S))
        auth = {"Authorization": f"Bearer {DEMO_KEY}", "x-anongw-session-id": SESSION_ID}
        out: list[dict[str, Any]] = []
        for p in pairs:
            t0 = time.perf_counter()
            resp = _post_chat(client, "/v1/chat/completions", {
                "messages": [{"role": "user", "content": _user_prompt(p)}],
                "temperature": 0, "max_tokens": ANSWER_MAX_TOKENS,
            }, auth, what=f"{p.qid}/masked")
            latency_ms = int((time.perf_counter() - t0) * 1000)
            route = resp.headers.get("x-anongw-route")
            assert route == p.expect_route, f"{p.qid}/masked: route {route} != {p.expect_route}"
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            body = _strip_ai_label(content, f"{p.qid}/masked")
            assert not RESTORE_PATTERN.search(body), \
                f"{p.qid}/masked: 占位符泄漏到客户端: {body[:120]!r}"
            out.append({"qid": p.qid, "route": route, "answer": body,
                        "latency_ms": latency_ms,
                        "completion_tokens": data.get("usage", {}).get("completion_tokens", 0)})
        ctx["masked"] = out

        # 上游 ring 全文 bytes 级零 seeded 原值：每一腿都确实被脱敏的硬证据
        blob = httpx.get(f"{ctx['root']}/admin/text", timeout=10.0).content
        records = httpx.get(f"{ctx['root']}/admin/records", timeout=10.0).json()
        assert int(records.get("count", 0)) >= n, \
            f"ring 记录 {records.get('count')} < 请求数 {n}"
        leaks = [(p.qid, etype) for p in pairs for etype, val in p.seeded
                 if val.encode("utf-8") in blob]
        assert not leaks, f"上游 ring 出现 seeded 原值（脱敏缺位）: {leaks[:5]}"

        # 审计：n 行如落库（临时库，不碰 data/audit.db）
        audit: SqliteAuditWriter = ctx["audit_gw"]
        deadline = time.monotonic() + 10.0
        while len(audit) < n and time.monotonic() < deadline:
            time.sleep(0.1)
        assert audit.flush(timeout_s=5.0) and len(audit) == n, \
            f"审计行数 {len(audit)} != {n}"

        routes = Counter(r["route"] for r in out)
        lat = sorted(r["latency_ms"] for r in out)
        return (f"{n} 腿经网关真实链路（路由 {dict(sorted(routes.items()))}，"
                f"客户端零占位符/零泄漏）；上游 ring {records.get('count')} 条全文 "
                f"{len(blob)} 字节零 seeded 原值；审计 {len(audit)} 行；"
                f"延迟 mean={sum(lat) // len(lat)}ms p95={lat[int(0.95 * (len(lat) - 1))]}ms")
    finally:
        if client is not None:
            client.close()
        server.should_exit = True
        thread.join(timeout=5.0)
        for suffix in ("", "-wal", "-shm"):
            Path(str(audit_db) + suffix).unlink(missing_ok=True)


# ── 4. judge（同服务同 rubric 双打分）───────────────────────────────────────

_SCORE_JSON_RE = re.compile(r"\{.*\}", re.S)
_SCORE_KEY_RE = re.compile(r"['\"]?score['\"]?\s*[:：]\s*(\d+)")


def _parse_score(text: str) -> int:
    m = _SCORE_JSON_RE.search(text)
    if m:
        try:
            score = int(json.loads(m.group(0))["score"])
            if 1 <= score <= 10:
                return score
        except Exception:  # noqa: BLE001 — 落到宽松解析
            pass
    m = _SCORE_KEY_RE.search(text)
    if m and 1 <= int(m.group(1)) <= 10:
        return int(m.group(1))
    raise AssertionError(f"judge 输出不可解析: {text[:160]!r}")


def _judge_one(ctx: dict[str, Any], client: httpx.Client, pair: qa_gen.QAPair,
               answer: str, where: str) -> tuple[int, int]:
    key = ctx["judge_key"]
    payload = {
        "model": ctx["model"],
        "messages": [{"role": "user", "content": JUDGE_PROMPT.format(
            context=pair.context, question=pair.question,
            reference=pair.reference, answer=answer)}],
        "temperature": 0, "max_tokens": JUDGE_MAX_TOKENS,
    }
    t0 = time.perf_counter()
    resp = _post_chat(client, f"{ctx['root']}/v1/chat/completions", payload,
                      {"Authorization": f"Bearer {key}"}, what=f"{where}/judge")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return _parse_score(resp.json()["choices"][0]["message"]["content"]), latency_ms


def phase_judge(ctx: dict[str, Any]) -> str:
    orig_by = {r["qid"]: r for r in ctx["orig"]}
    masked_by = {r["qid"]: r for r in ctx["masked"]}
    detail: list[dict[str, Any]] = []
    ctx["judge_key"] = resolve_secret(ctx["up_internet"].api_key_env)
    with httpx.Client(timeout=httpx.Timeout(CALL_TIMEOUT_S)) as client:
        for p in ctx["pairs"]:
            o, m = orig_by[p.qid], masked_by[p.qid]
            s_o, lat_o = _judge_one(ctx, client, p, o["answer"], f"{p.qid}/orig")
            s_m, lat_m = _judge_one(ctx, client, p, m["answer"], f"{p.qid}/masked")
            detail.append({
                "qid": p.qid, "kind": p.kind, "question": p.question,
                "reference": p.reference, "route": m["route"],
                "answer_orig": o["answer"], "answer_masked": m["answer"],
                "score_orig": s_o, "score_masked": s_m,
                "f1_orig": _f1(o["answer"], p.reference),
                "f1_masked": _f1(m["answer"], p.reference),
                "latency_ms_orig": o["latency_ms"], "latency_ms_masked": m["latency_ms"],
                "latency_ms_judge": lat_o + lat_m,
            })
    ctx["detail"] = detail
    return f"{len(detail) * 2} 次评分全部解析成功（1-10；温度 0 同服务同 rubric）"


# ── 5. 质量比值 + F1/延迟出数 ───────────────────────────────────────────────

def _f1(answer: str, reference: str) -> float:
    """字符级 F1（NFKC 归一 + 去空白；SQuAD 式多重集交）——脱敏前后同口径。"""
    a = [ch for ch in unicodedata.normalize("NFKC", answer) if not ch.isspace()]
    r = [ch for ch in unicodedata.normalize("NFKC", reference) if not ch.isspace()]
    if not a or not r:
        return 0.0
    common = sum((Counter(a) & Counter(r)).values())
    if common == 0:
        return 0.0
    precision, recall = common / len(a), common / len(r)
    return 2 * precision * recall / (precision + recall)


def _p95(xs: list[int]) -> int:
    s = sorted(xs)
    return s[int(0.95 * (len(s) - 1))]


def check_ratio(ctx: dict[str, Any]) -> str:
    detail: list[dict[str, Any]] = ctx["detail"]
    mean_o = sum(d["score_orig"] for d in detail) / len(detail)
    mean_m = sum(d["score_masked"] for d in detail) / len(detail)
    ratio = (mean_m / mean_o) if mean_o > 0 else 0.0
    ctx["metrics"] = {
        "orig_mean": round(mean_o, 4), "masked_mean": round(mean_m, 4),
        "ratio": round(ratio, 4),
        "f1_orig_mean": round(sum(d["f1_orig"] for d in detail) / len(detail), 4),
        "f1_masked_mean": round(sum(d["f1_masked"] for d in detail) / len(detail), 4),
        "latency_ms_orig_p95": _p95([d["latency_ms_orig"] for d in detail]),
        "latency_ms_masked_p95": _p95([d["latency_ms_masked"] for d in detail]),
    }
    print("── 质量对比（judge 1-10，同服务同 rubric；脱敏前 orig vs 脱敏后 masked）──")
    print(f"  orig  : mean={mean_o:.2f}  f1={ctx['metrics']['f1_orig_mean']:.3f}  "
          f"lat_p95={ctx['metrics']['latency_ms_orig_p95']}ms")
    print(f"  masked: mean={mean_m:.2f}  f1={ctx['metrics']['f1_masked_mean']:.3f}  "
          f"lat_p95={ctx['metrics']['latency_ms_masked_p95']}ms")
    print(f"  ratio = {ratio:.4f}（阈值 ≥ {th.QUALITY_RATIO_MIN}）")
    kinds = sorted({d["kind"] for d in detail})
    print("  ── 逐类分解 ──")
    for kind in kinds:
        rows = [d for d in detail if d["kind"] == kind]
        mo = sum(d["score_orig"] for d in rows) / len(rows)
        mm = sum(d["score_masked"] for d in rows) / len(rows)
        print(f"    {kind:<14} n={len(rows):<3} orig={mo:.2f} masked={mm:.2f} "
              f"ratio={(mm / mo if mo else 0.0):.3f}")
    worst = sorted(detail, key=lambda d: d["score_masked"] - d["score_orig"])[:5]
    for d in worst:
        print(f"    最大退化 {d['qid']}[{d['kind']}] {d['score_orig']}→{d['score_masked']} "
              f"ref={d['reference']!r} masked_ans={d['answer_masked'][:40]!r}")
    assert ratio >= th.QUALITY_RATIO_MIN, (
        f"质量比值 {ratio:.4f} < {th.QUALITY_RATIO_MIN}"
        f"（orig mean={mean_o:.3f}, masked mean={mean_m:.3f}）——如实报数，见逐对明细")
    return f"ratio={ratio:.4f} ≥ {th.QUALITY_RATIO_MIN}（orig={mean_o:.2f} masked={mean_m:.2f}）"


def check_report(ctx: dict[str, Any]) -> str:
    detail: list[dict[str, Any]] = ctx["detail"]
    assert len(detail) == ctx["n"], f"明细不完整: {len(detail)} != {ctx['n']}"
    report = {
        "task": "T7.1",
        "eval": "evals.m8_quality",
        "seed": ctx["seed"],
        "pairs": len(detail),
        "answer_model": ctx["model"],
        "judge_model": ctx["model"],
        "chain": "orig=direct llm_openai; masked=gateway real profiles(llm_openai)",
        "thresholds": {"QUALITY_PAIRS_MIN": th.QUALITY_PAIRS_MIN,
                       "QUALITY_RATIO_MIN": th.QUALITY_RATIO_MIN},
        "metrics": ctx["metrics"],
        "detail": detail,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    return f"data/bench/quality_report.json（{len(detail)} 对明细+分数/F1/延迟）"


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ctx: dict[str, Any] = {}
    load_env_file()
    ctx["cfg"] = load_app_config()
    by_name = {u.name: u for u in ctx["cfg"].upstreams}
    try:
        ctx["up_internet"] = by_name[REAL_PROFILE_INTERNET]
        ctx["up_gov"] = by_name[REAL_PROFILE_GOVCLOUD]
    except KeyError as exc:  # pragma: no cover — 配置契约缺失
        RESULTS.append((False, f"FAIL  env-profiles — config/app.yaml 缺真实 profiles: {exc}"))
        ctx["profiles_ok"] = False
    else:
        ctx["profiles_ok"] = True
        ctx["mask_key"] = resolve_secret(ctx["cfg"].mask_key_env)

    _record("qa-set(生成器双跑复现+规模+seeded 合法+检测面/路由契约)", lambda: check_qa_set(ctx))
    qa_ok = next((ok for ok, line in RESULTS if "qa-set(" in line), False)

    if qa_ok and ctx["profiles_ok"]:
        ok, why = _service_ready(ctx)
        if not ok:
            print(f"M8 QUALITY: DEFERRED — {why}（真实上游=环境依赖，与 e2e U8 同口径）")
            return 0
        print(f"[m8_quality] 真实上游就绪: {why}", flush=True)
        _record(f"orig-leg(脱敏前直答×{ctx['n']})", lambda: phase_orig(ctx))
        _record(f"masked-leg(网关真实链路×{ctx['n']}+上游 ring 零原值)", lambda: phase_masked(ctx))
        _record(f"judge(2×{ctx['n']} 评分可解析)", lambda: phase_judge(ctx))
        _record(f"quality-ratio(≥{th.QUALITY_RATIO_MIN})", lambda: check_ratio(ctx))
        _record("report(quality_report.json)", lambda: check_report(ctx))

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M8 QUALITY: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
