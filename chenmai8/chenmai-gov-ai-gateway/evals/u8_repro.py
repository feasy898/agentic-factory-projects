#!/usr/bin/env python3
"""U8 GOVCLOUD 腿占位符改形复现/取证脚本（gate_final b6 一轮 FAIL 的专用复现器）。

背景（T8.4）：gate_final 七门级联中 e2e U8 GOVCLOUD 腿 6/7 轮 PASS、一轮 FAIL——
断言「占位符泄漏到客户端」命中，回复里混有还原失败的占位符残留。根因假设：真实
大模型对占位符 token 的**输出随机性改形**（反引号包裹/空白插入/换行拆开/全半角
与大小写转写/同形括号·间隔号替换）超出还原正则 ``〔标签·hex8-12〕`` 的匹配面，
还原漏配 → 改形残留直达客户端。

本脚本两模式（均用 U8 GOVCLOUD 腿**同款材料与 prompt**：低保名单 docx 正文 +
``max_tokens=192``、不设 temperature=模型默认）：

- 网关链路模式（默认）——复现 e2e U8 腿全链（真实 profiles 独立网关实例，
  非流式，与 U8 同口径），每轮对客户端最终回复做**改形容忍检测**（本脚本
  内置独立实现的检测器，不依赖被测 masking 代码——检测器与修复器同源会
  互相遮盲），捕获占位符残留实例并分类：
    * strict 命中：还原正则可见的残留（e2e 断言能抓到的泄漏）；
    * tolerant-only：还原正则不可见、但可规范化为占位符形状的残留
      （e2e 严格断言抓不到的**静默泄漏**）。
  （改形过度致形状不可辨/摘要被截断的残留无法检测——irreducible loss，超出
  还原侧可修复面。）
- 直连探针模式（``--direct``）——取证增强：本地脱敏同款材料后**绕过网关还原**
  直打 :9004，对模型原始回复枚举占位符改形形态清单（原文引用），用于在泄漏
  率低时加速收集改形样本。发送面仍全占位符（无原值出网关，红线不破）。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.u8_repro [--runs N] [--direct]

退出码：真实上游离线/未装载 → DEFERRED，exit 0（环境依赖，同 e2e U8 口径）；
网关链路模式检测到任何残留 → exit 1；零残留 → exit 0。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.generator.materials import ROSTER_MATERIAL  # noqa: E402
from common.config import load_app_config, load_dept_keys, load_env_file, resolve_secret  # noqa: E402
from masking.mapper import RESTORE_PATTERN, SessionMapper, SessionRegistry  # noqa: E402

# ── 内置改形容忍检测器（独立实现，取证口径不依赖被测修复代码）────────────
_OPEN_CLASS = "〔【〖［["
_CLOSE_CLASS = "〕】〗］]"
_SEP_CLASS = "·・•‧⋅﹒．."
_OPEN_RE = re.compile("[" + re.escape(_OPEN_CLASS) + "]")
_CLOSE_RE = re.compile("[" + re.escape(_CLOSE_CLASS) + "]")
_SEP_RE = re.compile("[" + re.escape(_SEP_CLASS) + "]")
_NOISE_RE = re.compile(r"[\s`]+")            # 空白/换行/反引号=改形噪声
_DIGEST_RE = re.compile(r"[0-9a-f]{8,12}")
_CONFUSABLE = str.maketrans({"o": "0", "i": "1", "l": "1"})  # hex 转写易混兜底
_WINDOW = 48                                  # 候选最大扫描窗（canonical ≤32 + 改形余量）


def canonical_key(inside: str) -> str | None:
    """候选括号内文本 → 规范占位符键（〔标签·hex〕）；不可规范化返回 None。"""
    compact = _NOISE_RE.sub("", inside)
    if not compact:
        return None
    parts = _SEP_RE.split(compact)
    if len(parts) != 2:
        return None
    label, digest = parts
    if not label or not digest:
        return None
    if _OPEN_RE.search(label) or _CLOSE_RE.search(label):
        return None
    digest = unicodedata.normalize("NFKC", digest).lower().translate(_CONFUSABLE)
    if not _DIGEST_RE.fullmatch(digest):
        return None
    return f"〔{label}·{digest}〕"


def tolerant_spans(text: str) -> list[tuple[int, int, str]]:
    """全部「可规范化为占位符形状」的候选 (start, end, canonical_key)（含 strict 形状）。"""
    spans: list[tuple[int, int, str]] = []
    i, n = 0, len(text)
    while i < n:
        m = _OPEN_RE.search(text, i)
        if m is None:
            break
        j = m.start()
        cm = _CLOSE_RE.search(text, j + 1, min(n, j + _WINDOW - 1))
        if cm is not None:
            key = canonical_key(text[j + 1:cm.start()])
            if key is not None:
                spans.append((j, cm.end(), key))
                i = cm.end()
                continue
        i = j + 1
    return spans


# ── U8 GOVCLOUD 腿同款请求材料 ────────────────────────────────────────
U8_REPRO_PORT = 9014                       # 独立端口（9000/9010-9013 归既有 eval）
U8_REPRO_SESSION = "sess_u8_repro_gov"     # 与 U8 腿同为固定会话（占位符会话稳定）
U8_MAX_TOKENS = 192                        # 同 e2e U8
AI_LABEL = "本内容由AI生成"                # config/app.yaml ai_label


def _material_text() -> str:
    """U8 GOVCLOUD 腿同款 prompt：低保名单 docx 夹具正文（filechannel 文本层权威解析）。"""
    from filechannel.parsers import parse_any
    from ops.e2e_smoke import MATERIALS_DIR, materialize_materials
    materialize_materials()
    path = MATERIALS_DIR / ROSTER_MATERIAL.filename
    parsed = parse_any(path.name, path.read_bytes())
    return "\n".join(seg.text for seg in parsed.segments)


def _strip_label(content: str) -> str:
    tail = f"\n{AI_LABEL}"
    return content[: -len(tail)] if content.endswith(tail) else content


def classify_remnant(content: str) -> list[tuple[str, str, str]]:
    """客户端回复 → [(类别, canonical_key, 原文引用)]；类别=strict/tolerant-only。"""
    out: list[tuple[str, str, str]] = []
    strict_spans = [(m.start(), m.end()) for m in RESTORE_PATTERN.finditer(content)]
    for start, end, key in tolerant_spans(content):
        quote = content[max(0, start - 12):min(len(content), end + 12)]
        kind = "strict" if (start, end) in strict_spans else "tolerant-only"
        out.append((kind, key, quote))
    return out


# ── 模式一：网关链路复现（默认；与 e2e U8 GOVCLOUD 腿同口径）────────────
def run_gateway_chain(runs: int) -> int:
    import gateway.app as gw_app
    from audit.writer import SqliteAuditWriter
    from ops.e2e_smoke import REAL_PROFILE_GOVCLOUD, _plain_body

    cfg = load_app_config()
    load_env_file()
    mask_key = resolve_secret(cfg.mask_key_env)
    by_name = {u.name: u for u in cfg.upstreams}
    if REAL_PROFILE_GOVCLOUD not in by_name:
        raise AssertionError(f"config/app.yaml 缺真实上游 profile: {REAL_PROFILE_GOVCLOUD}")
    gov_up = by_name[REAL_PROFILE_GOVCLOUD]
    root = gov_up.base_url.rstrip("/")
    root = root[:-3] if root.endswith("/v1") else root
    try:
        health = httpx.get(f"{root}/health", timeout=5.0).json()
    except Exception as exc:  # noqa: BLE001
        print(f"DEFERRED: 真实上游不可达（{root}/health: {type(exc).__name__}: {exc}）")
        return 0
    if not isinstance(health, dict) or not health.get("loaded"):
        print(f"DEFERRED: 真实上游未装载（{root}）")
        return 0

    cfg_real = cfg.model_copy(deep=True)
    cfg_real.upstreams = [gov_up.model_copy(deep=True)]
    db_path = REPO_ROOT / "tmp" / "u8_repro_audit.db"
    db_path.parent.mkdir(exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    app = gw_app.create_app(cfg=cfg_real, mask_key=mask_key,
                            dept_key_digests=load_dept_keys(),
                            audit_store=SqliteAuditWriter(db_path),
                            session_registry=SessionRegistry(mask_key.encode("utf-8")))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=U8_REPRO_PORT,
                                           log_level="warning", log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, name="anongw-u8-repro", daemon=True)
    thread.start()
    deadline = time.monotonic() + 60.0
    while deadline > time.monotonic():
        try:
            httpx.get(f"http://127.0.0.1:{U8_REPRO_PORT}/healthz", timeout=1.0)
            break
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    text = _material_text()
    body = _plain_body(text, model=None)
    body["max_tokens"] = U8_MAX_TOKENS
    client = httpx.Client(base_url=f"http://127.0.0.1:{U8_REPRO_PORT}",
                          timeout=httpx.Timeout(180.0))
    evidence: list[dict[str, Any]] = []
    leaks = 0
    try:
        for i in range(1, runs + 1):
            resp = client.post("/v1/chat/completions", json=body,
                               headers={"Authorization": "Bearer dk_5e6f7a8b",
                                        "x-anongw-session-id": U8_REPRO_SESSION})
            if resp.status_code != 200:
                print(f"run{i:02d}: status={resp.status_code}（上游波动，跳过）")
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            body_text = _strip_label(content)
            remnants = classify_remnant(body_text)
            evidence.append({"run": i, "content": body_text, "remnants": remnants})
            if remnants:
                leaks += 1
                print(f"run{i:02d}: LEAK — {len(remnants)} 处残留")
                for kind, key, quote in remnants:
                    print(f"    [{kind}] {key}  原文: {quote!r}")
            else:
                head = body_text[:42].replace("\n", " ")
                print(f"run{i:02d}: clean — {head!r}…")
    finally:
        client.close()
        server.should_exit = True
        thread.join(timeout=5.0)
        (REPO_ROOT / "tmp" / "u8_repro_runs.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in evidence) + "\n",
            encoding="utf-8")
    print("-" * 64)
    print(f"U8 REPRO gateway-chain: {runs} runs, {leaks} runs with placeholder remnants"
          f"（证据落盘 tmp/u8_repro_runs.jsonl）")
    return 1 if leaks else 0


# ── 模式二：直连探针（--direct；取证改形形态清单，绕过网关还原）────────
def run_direct_probe(runs: int, args_temperature: float | None = None) -> int:
    cfg = load_app_config()
    load_env_file()
    mask_key = resolve_secret(cfg.mask_key_env)
    by_name = {u.name: u for u in cfg.upstreams}
    gov_up = by_name["govcloud_real"]
    root = gov_up.base_url.rstrip("/")
    root = root[:-3] if root.endswith("/v1") else root
    health = httpx.get(f"{root}/health", timeout=5.0).json()
    if not isinstance(health, dict) or not health.get("loaded"):
        print(f"DEFERRED: 真实上游未装载（{root}）")
        return 0
    text = _material_text()
    mapper = SessionMapper(U8_REPRO_SESSION, mask_key.encode("utf-8"))
    # 直接走真实检测面（与网关 prompt 侧同源）：先 detect 再 mask
    from recognizers.pipeline import detect_full
    findings = detect_full(text)
    span_list = [(f.start, f.end, f.type, f.normalized) for f in findings
                 if f.action_hint == "MASK" and not f.whitelisted]
    masked, _entries = mapper.mask(text, span_list)
    if RESTORE_PATTERN.search(masked) is None:
        raise AssertionError("fixture broken: masked text has no placeholder")
    print(f"[direct] 上游 {root}；prompt=材料脱敏版（{len(masked)} 字，"
          f"{len(RESTORE_PATTERN.findall(masked))} 个占位符）")

    form_catalog: dict[str, dict[str, Any]] = {}
    reply_log: list[str] = []
    body = {"messages": [{"role": "user", "content": masked}], "max_tokens": U8_MAX_TOKENS}
    if args_temperature is not None:
        body["temperature"] = args_temperature  # 取证增强：高温诱发放形面（非验收口径）
    api_key = os.environ.get(gov_up.api_key_env)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=httpx.Timeout(180.0)) as client:
        for i in range(1, runs + 1):
            try:
                resp = client.post(f"{root}/v1/chat/completions", json=body, headers=headers)
            except Exception as exc:  # noqa: BLE001
                print(f"run{i:02d}: upstream error {type(exc).__name__}: {exc}")
                continue
            if resp.status_code != 200:
                print(f"run{i:02d}: status={resp.status_code}")
                continue
            content = resp.json()["choices"][0]["message"]["content"]
            reply_log.append(content)
            known = unknown = 0
            for start, end, key in tolerant_spans(content):
                quote = content[max(0, start - 10):min(len(content), end + 10)]
                raw = content[start:end]
                entry = form_catalog.setdefault(key, {"count": 0, "raw_forms": {}, "quote": quote})
                entry["count"] += 1
                entry["raw_forms"][raw] = entry["raw_forms"].get(raw, 0) + 1
                if mapper.lookup(key) is not None:
                    known += 1
                else:
                    unknown += 1
            strict_n = len(RESTORE_PATTERN.findall(content))
            print(f"run{i:02d}: shapes={len(tolerant_spans(content))} "
                  f"(strict-visible={strict_n}, known={known}, unknown={unknown})")
    print("=" * 64)
    print(f"改形形态清单（canonical key → 原始改形形态 → 出现次数；共 {len(reply_log)} 轮有效回复）")
    for key, entry in sorted(form_catalog.items(), key=lambda kv: -kv[1]["count"]):
        known = "已知" if mapper.lookup(key) is not None else "未知"
        print(f"  {key} [{known}] ×{entry['count']}")
        for raw, cnt in entry["raw_forms"].items():
            print(f"      原形 ×{cnt}: {raw!r}   上下文: {entry['quote']!r}")
    (REPO_ROOT / "tmp" / "u8_repro_direct.jsonl").write_text(
        "\n".join(json.dumps({"reply": r}, ensure_ascii=False) for r in reply_log) + "\n",
        encoding="utf-8")
    print("原始回复落盘 tmp/u8_repro_direct.jsonl")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="U8 GOVCLOUD 腿占位符改形复现/取证")
    ap.add_argument("--runs", type=int, default=20, help="调用次数（默认 20）")
    ap.add_argument("--direct", action="store_true",
                    help="直连 :9004 探针（绕过网关还原，枚举改形形态清单）")
    ap.add_argument("--temperature", type=float, default=None,
                    help="仅 --direct 取证面：高温采样的改形形态枚举（非验收口径）")
    args = ap.parse_args()
    if args.direct:
        return run_direct_probe(args.runs, args.temperature)
    return run_gateway_chain(args.runs)


if __name__ == "__main__":
    sys.exit(main())
