"""M6 验收（mock 后端全离线；零网络零 GPU —— T10 自验收口径）。

断言集（对应自验收三项 + 支撑机制）：
  ① 角色卡注入：C3/C2 → context.json 角色卡与术语表 → 注入每次 translate 调用
    （mock 后端 last_context 探针断言）；新说话人生成暂定卡、既有卡不被覆盖；
  ② 预算候选生成：C2 时间戳 → C4 预算窗（±10%）；每句 1–5 个长短候选，
    syl/est_dur 占位估长、in-budget-first 排序、chosen 合法；
  ③ C4 出口 schema 合法：TranslationTable 强校验 + CLI validate 通过；
    (utt_id, tgt) 复合键替换（en/es 共存，重跑不重复）。
  另守：术语命中率 100%（角色名/别名/种子按 terms 渲染）；超预算句 100% 判出
  （全部候选落窗外，供 M8 换译流程触发）；local 后端 payload 契约（桩服务）；
  api 后端 env 缺失即报错（无凭据字面量，离线）。

口径注记：演示语料时长按 mock 全量变体的估长构造（系数 0.92–1.08 ∈ 预算窗，
另 2 句刻意压窗触发超预算路径）——mock 基线验证的是管线机制（预算计算/排序/
术语渲染/出口 schema），规划 §4 M6 的真实通过线（50 句 55% 命中、LLM 评分）
归 local/api 后端接通后的验收（T12+，扩展本文件）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from pipeline import contracts as C
from pipeline.m6_translate import (
    DEFAULT_SYL_RATE,
    budget_for,
    build_context,
    build_glossary,
    count_syllables,
    estimate_dur_s,
    load_syl_table,
    translate_episode,
)
from pipeline.mt_backends import (
    ApiMtBackend,
    MTContext,
    MtBackendError,
    MockMtBackend,
    LocalMtBackend,
    make_backend,
)
from pipeline.scaffold import create_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
EP = "ep01"

#: 演示语料：(文本, 说话人, 时长系数)。系数 ∈[0.92,1.08] 落预算窗；0.5x 压窗判超预算。
CORPUS: list[tuple[str, str, float]] = [
    ("你到底想怎么样？把话说清楚。", "spk0", 1.00),
    ("三年了，程氏的项目、老城的基地，哪一样不是我亲手做起来的？", "spk1", 1.05),
    ("那你就可以这样对我吗！", "spk0", 0.95),
    ("我以为你至少会信我。", "spk1", 1.00),
    ("为什么，为什么要走？", "spk0", 1.08),
    ("海南孤岛，也有明月。", "spk1", 0.92),
    ("程总，预算超了。", "spk1", 0.50),   # 刻意压窗 → 超预算路径（M8 换译触发）
    ("总裁，你到底想怎么样？", "spk0", 0.55),  # 同上（别名术语句）
    ("东坡为什么要走？", "spk1", 1.00),   # 种子术语句
]

_CAST = {
    "char_spk0": {
        "name": "程总",
        "aliases": ["总裁"],
        "gender": "m",
        "voice_ref": "05_cast/voicebank/char_spk0_ref.wav",
        "ref_dur_s": 12.0,
        "desc": "男主，世家出身，语气克制但压迫感强",
        "terms": {"en": "Master Cheng", "es": "Sr. Cheng", "ar": "السيد تشنغ"},
    },
}
_SEED = {"东坡": {"en": "Dongpo", "es": "Dongpo", "ar": "دونغبو"}}

#: 语料期望时长：按 mock 全量变体估长 × 系数构造（口径见模块 docstring）
_GAP_S = 0.6


def _expected_glossary() -> dict[str, str]:
    cast = {k: C.Character(**v) for k, v in _CAST.items()}
    return build_glossary(cast, _SEED, "en")


def _build_workspace(jobs_root: Path) -> list[C.Utterance]:
    """建 ep 工作区 + C2 事实表（时长按 mock 估长构造，见模块 docstring）。"""
    create_workspace(EP, jobs_root)
    lex = MockMtBackend()
    glossary = _expected_glossary()
    rate = DEFAULT_SYL_RATE["en"]
    utts: list[C.Utterance] = []
    t = 0.0
    for text, speaker, factor in CORPUS:
        syl = count_syllables(
            lex.translate(text, MTContext(tgt_lang="en", terms=glossary))[0].text, "en"
        )
        dur = round(syl / rate * factor, 3)
        utts.append(
            C.Utterance(
                utt_id=C.make_utt_id(EP, t),
                shot_id="s0000",
                start=round(t, 3),
                end=round(t + dur, 3),
                lang="zh",
                speaker=speaker,
                text=text,
            )
        )
        t = round(t + dur + _GAP_S, 3)
    dial = jobs_root / EP / "04_dial"
    C.dump_jsonl(dial / "utterances.jsonl", C.UtteranceTable.model_validate(utts))
    cast_path = jobs_root / EP / "05_cast" / "characters.json"
    cast_path.write_text(
        json.dumps({k: v for k, v in _CAST.items()}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (jobs_root / EP / "06_mt").mkdir(parents=True, exist_ok=True)
    (jobs_root / EP / "06_mt" / "terms_seed.json").write_text(
        json.dumps(_SEED, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return utts


@pytest.fixture()
def workspace(tmp_path: Path) -> tuple[Path, list[C.Utterance]]:
    jobs_root = tmp_path / "jobs"
    utts = _build_workspace(jobs_root)
    return jobs_root, utts


def _run_mock(jobs_root: Path, lang: str = "en") -> tuple[dict, MockMtBackend]:
    backend = MockMtBackend()
    summary = translate_episode(
        EP, lang, backend, jobs_dir=jobs_root,
        seed_path=jobs_root / EP / "06_mt" / "terms_seed.json",
    )
    return summary, backend


# ---------------------------------------------------------------------------
# ② 预算与估长原语
# ---------------------------------------------------------------------------

def test_budget_comes_from_c2_window() -> None:
    u = C.Utterance(utt_id="x", shot_id="s0", start=12.4, end=14.02, lang="zh", text="……")
    b = budget_for(u, 0.9, 1.1)
    assert b.orig_dur == 1.62 and b.lo == 1.458 and b.hi == 1.782
    with pytest.raises(ValueError):  # lo>hi 拒绝（契约校验器）
        C.Budget(orig_dur=1.0, lo=1.2, hi=1.0)


def test_syllable_counter_and_rate_table(tmp_path: Path) -> None:
    assert count_syllables("你到底想怎么样", "zh") == 7
    assert count_syllables("What do you want?", "en") >= 4
    assert count_syllables("casa", "es") == 2
    assert count_syllables("", "en") == 0
    assert estimate_dur_s(8, "en") == round(8 / DEFAULT_SYL_RATE["en"], 3)
    # 拟合表回填后覆盖占位常量（training-plan §1.3 口径；两种文件格式都收）
    t1 = tmp_path / "syl2dur.json"
    t1.write_text(json.dumps({"en": {"syl_rate": 4.8}, "es": 5.0}), encoding="utf-8")
    rates = load_syl_table(t1)
    assert rates == {"en": 4.8, "es": 5.0}
    assert estimate_dur_s(8, "en", rates) == round(8 / 4.8, 3)
    assert load_syl_table(tmp_path / "missing.json") == {}


def test_mock_backend_terms_variants_determinism() -> None:
    ctx = MTContext(tgt_lang="en", cast_summary="角色卡：- char_spk0｜程总", terms={"程总": "Master Cheng"})
    a = MockMtBackend().translate("程总，预算超了。", ctx, n_candidates=4)
    b = MockMtBackend().translate("程总，预算超了。", ctx, n_candidates=4)
    assert [d.text for d in a] == [d.text for d in b]  # 同输入恒同输出
    assert any("Master Cheng" in d.text for d in a)  # 术语按 terms 渲染
    multi = MockMtBackend().translate("为什么，为什么要走？要走。", ctx, n_candidates=5)
    assert len(multi) >= 2 and len({d.text for d in multi}) >= 2  # 长短变体去重 ≥2
    assert all(0.0 <= d.q <= 1.0 and d.src == "mock" for d in multi)


# ---------------------------------------------------------------------------
# ① 角色卡生成/校订 + context 工作纸
# ---------------------------------------------------------------------------

def test_build_context_draft_and_glossary(workspace: tuple[Path, list[C.Utterance]]) -> None:
    jobs_root, utts = workspace
    payload, merged = build_context(utts, {k: C.Character(**v) for k, v in _CAST.items()},
                                    ep=EP, lang="en", seed=_SEED)
    # 既有卡不动，新说话人生成暂定卡
    assert payload["cast"]["char_spk0"]["provisional"] is False
    assert payload["cast"]["char_spk0"]["name"] == "程总"
    assert payload["cast"]["char_spk1"]["provisional"] is True
    assert merged["char_spk1"].ref_dur_s == 0.0
    # 术语表 = C3 terms(en) ∪ 别名 ∪ 种子
    assert payload["glossary"]["程总"] == "Master Cheng"
    assert payload["glossary"]["总裁"] == "Master Cheng"  # 别名同渲染
    assert payload["glossary"]["东坡"] == "Dongpo"
    # 关系占位 + 高频专名候选（仅列出，不自动注入；单次出现的东坡不入候选）
    assert isinstance(payload["relations"], list)
    assert "为什么要" in payload["term_candidates"]
    assert "东坡" not in payload["term_candidates"]
    assert payload["stats"]["n_utt"] == len(CORPUS)


# ---------------------------------------------------------------------------
# ②③ 整集翻译主流程（角色卡注入 / 预算候选 / C4 出口 schema）
# ---------------------------------------------------------------------------

def test_translate_episode_end_to_end(workspace: tuple[Path, list[C.Utterance]]) -> None:
    jobs_root, utts = workspace
    summary, backend = _run_mock(jobs_root)

    # ① 角色卡注入：每次 translate 收到的上下文含整集角色卡与术语表
    assert backend.last_context is not None
    assert "程总" in backend.last_context.cast_summary
    assert "Master Cheng" in backend.last_context.cast_summary
    assert backend.last_context.terms.get("程总") == "Master Cheng"
    assert backend.last_context.tgt_lang == "en"

    # ③ C4 出口 schema 合法（契约强校验）且逐句有行
    rows = C.load_jsonl(jobs_root / EP / "06_mt" / "translations.jsonl",
                        C.TranslationTable).root
    assert {r.utt_id for r in rows} == {u.utt_id for u in utts}
    by_id = {r.utt_id: r for r in rows}
    for u, row in zip(utts, rows):
        assert row.tgt == "en"
        # ② 预算窗 = C2 时间窗 × ±10%（3 位小数）
        assert row.budget.orig_dur == round(u.end - u.start, 3)
        assert row.budget.lo == round((u.end - u.start) * 0.9, 3)
        assert row.budget.hi == round((u.end - u.start) * 1.1, 3)
        # 候选 1–5 条，估长 = syl/占位速率（3 位），src 留痕
        assert 1 <= len(row.candidates) <= 5
        for c in row.candidates:
            assert c.syl > 0 and c.est_dur > 0 and c.src == "mock" and 0 <= c.q <= 1
            assert c.est_dur == estimate_dur_s(c.syl, "en")
        # in-budget-first 排序：预算内优先 → q 降 → |est−orig| 升；chosen 指向首位
        key = lambda c: (0 if row.budget.lo <= c.est_dur <= row.budget.hi else 1,
                         -c.q, abs(c.est_dur - row.budget.orig_dur))
        assert list(row.candidates) == sorted(row.candidates, key=key)
        assert row.chosen == 0 and row.policy == "in-budget-first"
        # 前文滚动注入（≤2 句，取前一句已定稿译文）
        assert len(row.context) <= 2
    second = by_id[utts[1].utt_id]
    assert second.context and second.context[-1] in [
        c.text for c in by_id[utts[0].utt_id].candidates
    ]

    # ② 命中口径：语料按构造 7/9 落窗（2 句压窗判超）；超预算句 100% 判出
    assert summary["in_budget_rate"] == round(7 / len(CORPUS), 3)
    assert summary["in_budget_rate"] >= 0.55  # mock 基线（口径见模块 docstring）
    over_ids = set(summary["over_budget_utts"])
    assert over_ids == {utts[6].utt_id, utts[7].utt_id}
    for u in (utts[6], utts[7]):
        row = by_id[u.utt_id]
        assert not any(row.budget.lo <= c.est_dur <= row.budget.hi for c in row.candidates)

    # ① 术语命中率 100%：含源术语的句子，其候选含目标渲染
    assert summary["term_hit_rate"] == 1.0 and summary["term_hits"] == "3/3"

    # context.json 工作纸 + characters.json 校订（暂定卡增量合并）
    ctx_payload = json.loads((jobs_root / EP / "06_mt" / "context.json").read_text("utf-8"))
    assert ctx_payload["ep"] == EP and ctx_payload["lang"] == "en"
    assert ctx_payload["cast"]["char_spk1"]["provisional"] is True
    cast_book = C.load_model(jobs_root / EP / "05_cast" / "characters.json", C.CastBook).root
    assert cast_book["char_spk0"].name == "程总"  # 既有卡零改动
    assert cast_book["char_spk0"].terms["en"] == "Master Cheng"
    assert "char_spk1" in cast_book


def test_translations_upsert_composite_key(workspace: tuple[Path, list[C.Utterance]]) -> None:
    jobs_root, utts = workspace
    out = jobs_root / EP / "06_mt" / "translations.jsonl"
    _run_mock(jobs_root, "en")
    _run_mock(jobs_root, "es")  # 同句第二语种 → 复合键共存
    rows = C.load_jsonl(out, C.TranslationTable).root
    assert len(rows) == 2 * len(CORPUS)
    assert {r.tgt for r in rows} == {"en", "es"}
    assert len({(r.utt_id, r.tgt) for r in rows}) == 2 * len(CORPUS)
    es_row = next(r for r in rows if r.utt_id == utts[6].utt_id and r.tgt == "es")
    assert any("Sr. Cheng" in c.text for c in es_row.candidates)  # es 术语渲染
    first_run = {r.utt_id: r.candidates[0].text for r in rows if r.tgt == "en"}
    _run_mock(jobs_root, "en")  # 重跑同语种 → 按 (utt_id,tgt) 替换，不重复不串语种
    rows2 = C.load_jsonl(out, C.TranslationTable).root
    assert len(rows2) == 2 * len(CORPUS)
    assert {r.utt_id: r.candidates[0].text for r in rows2 if r.tgt == "en"} == first_run


def test_cli_mock_end_to_end_and_validate(workspace: tuple[Path, list[C.Utterance]]) -> None:
    jobs_root, _ = workspace
    env = {**os.environ, "PYTHONUTF8": "1"}
    rc = subprocess.run(
        [sys.executable, "-m", "pipeline.m6_translate", "--ep", EP,
         "--backend", "mock", "--lang", "en", "--jobs-dir", str(jobs_root)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert rc.returncode == 0, rc.stdout + rc.stderr
    assert "OK m6_translate" in rc.stdout
    out = jobs_root / EP / "06_mt" / "translations.jsonl"
    rc2 = subprocess.run(
        [sys.executable, "-m", "pipeline.cli", "validate", "translations", str(out)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert rc2.returncode == 0 and "OK C4" in rc2.stdout, rc2.stdout + rc2.stderr


# ---------------------------------------------------------------------------
# 后端装配与契约（local 客户端 payload / api env 纪律）
# ---------------------------------------------------------------------------

def test_make_backend_unknown_name() -> None:
    with pytest.raises(MtBackendError):
        make_backend("nope")


def test_api_backend_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("MT_API_BASE", "MT_API_KEY", "MT_API_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(MtBackendError) as ei:
        make_backend("api")
    assert "MT_API_BASE" in str(ei.value) and "MT_API_KEY" in str(ei.value)


def test_local_backend_payload_contract(tmp_path: Path) -> None:
    """local 客户端 ↔ :9004 服务的请求-响应口径（桩服务；T12 真服务按此实现）。"""
    seen: dict = {}

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:  # 静默
            pass

        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps({"service": "mt", "loaded": {"mt-core": True}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            n = int(self.headers.get("Content-Length", 0))
            seen.update(json.loads(self.rfile.read(n)))
            body = json.dumps({"candidates": [{"text": "what is it that you want", "q": 0.88},
                                              {"text": "what do you want", "q": 0.8}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        backend = LocalMtBackend(f"http://127.0.0.1:{srv.server_address[1]}")
        assert backend.health()["loaded"]["mt-core"] is True
        drafts = backend.translate(
            "你到底想怎么样？",
            MTContext(tgt_lang="en", cast_summary="角色卡", terms={"程氏": "the Cheng family"},
                      prev_texts=["把话说清楚。"], budget=(1.62, 1.458, 1.782)),
            n_candidates=4,
        )
    finally:
        srv.shutdown()
    # payload 与 LocalMtBackend.translate docstring 声明一一对应
    assert seen["text"] == "你到底想怎么样？" and seen["tgt"] == "en"
    assert seen["cast"] == "角色卡" and seen["terms"] == {"程氏": "the Cheng family"}
    assert seen["prev"] == ["把话说清楚。"] and seen["next"] == []
    assert seen["budget"] == {"orig_dur": 1.62, "lo": 1.458, "hi": 1.782}
    assert seen["n_candidates"] == 4
    assert [d.text for d in drafts] == ["what is it that you want", "what do you want"]
    assert drafts[0].src == "mt-core" and drafts[0].q == pytest.approx(0.88)
