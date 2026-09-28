"""M11 溯因智能体 eval。

覆盖 §4 M11 通过线：
- TemplateAgent：12 类缺陷 × zh/en/vi 三语建议齐全（加载期不变式 + 逐类
  逐语验证）、严重度排序、好豆批 general 兜底、≤100ms、JSON 往返；
- LLMAgent：无 key/配置不全自动降级 Template；httpx MockTransport 罐头
  响应验证解析路径（含 response_format 不支持→解析兜底）与全部降级路径
  （HTTP 500 / 非 JSON / 语言不一致 / 缺 causes / 连接失败 / 幻觉缺陷键）；
- 根因知识表加载校验（缺类/坏环节/坏占位符/缺语言/normal 拒绝）；
- beaneye.kb 接口：NullKnowledgeBase 离线空实现 + LLM prompt 注入检索片段。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_agent.py -q
"""

from __future__ import annotations

import itertools
import json
import time

import httpx
import pytest

from beaneye.agent import (
    AgentError,
    LLMAgent,
    RootCauseConfigError,
    TemplateAgent,
    llm_configured,
    load_rootcause,
    make_agent,
)
from beaneye.agent.knowledge import (
    DEFAULT_ROOTCAUSE_PATH,
    LANGS,
    VALID_STAGES,
)
from beaneye.kb import KbChunk, NullKnowledgeBase
from beaneye.schemas import (
    AgentReport,
    BatchResult,
    BeanMask,
    BeanObservation,
    GradingDecision,
    Measurements,
    PairedBean,
    StatsSummary,
    defect_counts_from_beans,
)
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
RANK = {k: TAX.severity_rank(k) for k in TAX.keys()}
DEFECTS = TAX.defect_keys()  # 12 类（不含 normal）
ENV_VARS = ("BEANEYE_LLM_BASE_URL", "BEANEYE_LLM_KEY", "BEANEYE_LLM_MODEL")
STANDARD_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

# ---------------------------------------------------------------------------
# 确定性 BatchResult 构造器（合成，不依赖数据集/网络）
# ---------------------------------------------------------------------------

_SEQ = itertools.count(1)


def _mask(side: str) -> BeanMask:
    mid = f"{side}_{next(_SEQ):04d}"
    return BeanMask(
        mask_id=mid,
        side=side,  # type: ignore[arg-type]
        polygon=[[10.0, 20.0], [16.0, 20.0], [16.0, 26.0], [10.0, 26.0]],
        bbox_mm=(10.0, 20.0, 16.0, 26.0),
        area_mm2=36.0,
        centroid_mm=(13.0, 23.0),
        source="oracle",
        conf=1.0,
    )


def _obs(side: str, defect: str, conf: float = 0.9) -> BeanObservation:
    m = _mask(side)
    return BeanObservation(
        obs_id=m.mask_id,
        side=side,  # type: ignore[arg-type]
        defect=defect,
        defect_conf=conf,
        severity_rank=RANK.get(defect, 5),
        crop_path=f"out/crops/scan_agent/{m.mask_id}.png",
        mask=m,
        color_lab=(52.0, -10.0, 20.0),
        eq_diameter_mm=6.0,
    )


def _make_batch(
    defects: list[str],
    *,
    n_normal: int = 8,
    agent_report: AgentReport | None = None,
    sample_id: str = "sample_agent",
) -> BatchResult:
    """缺陷豆=单面(top)观测；好豆=双面配对。defect_counts 与逐粒直方一致。"""
    beans: list[PairedBean] = []
    for d in defects:
        beans.append(
            PairedBean.from_sides(
                f"b{len(beans) + 1:04d}", _obs("top", d), None, -1.0
            )
        )
    for _ in range(n_normal):
        beans.append(
            PairedBean.from_sides(
                f"b{len(beans) + 1:04d}",
                _obs("top", "normal", 0.98),
                _obs("bottom", "normal", 0.98),
                1.5,
            )
        )
    counts = defect_counts_from_beans(beans, include_normal=True)
    # 未知键（如故意的幻觉键用例）按次缺陷计入分计，保证 BatchResult 可构造
    primary = sum(
        n
        for k, n in counts.items()
        if TAX.is_valid_key(k) and TAX.get(k).kind == "primary"
    )
    secondary = sum(
        n
        for k, n in counts.items()
        if not TAX.is_valid_key(k)
        or (TAX.get(k).kind == "secondary" and k != "normal")
    )
    grading = GradingDecision(
        standard_id="cqi_fine_robusta",
        grade="Fine" if primary == 0 else "Below Fine",
        passed=primary == 0,
        primary_count=primary,
        secondary_count=secondary,
        defect_counts=counts,
        reasons=["agent.eval.batch"],
        standard_yaml_sha=STANDARD_SHA,
    )
    measurements = Measurements(
        bean_count=len(beans),
        sieve_hist={"14": len(beans)},
        sieve_pass=True,
        eq_diameter_mm_stats=StatsSummary(min=5.2, max=7.1, mean=6.0, median=6.0),
        color_lab_mean=(52.0, -10.0, 20.0),
        delta_e_mean=3.1,
        delta_e_hist={"2-4": len(beans)},
        est_weight_g=88.2,
        weight_model="area_linear:v1",
    )
    return BatchResult(
        result_id=f"res-{next(_SEQ):04d}",
        sample_id=sample_id,
        scan_ids=["scan_agent_0001"],
        beans=beans,
        measurements=measurements,
        grading=grading,
        agent_report=agent_report,
        timings_s={"classify": 0.2},
        pipeline_versions={"classify": "rules_v0"},
    )


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _set_llm_env(monkeypatch: pytest.MonkeyPatch, **kw: str) -> None:
    values = {
        "BEANEYE_LLM_BASE_URL": "http://llm.test/v1",
        "BEANEYE_LLM_KEY": "sk-test-001",
        "BEANEYE_LLM_MODEL": "test-model",
    }
    values.update(kw)
    for var, val in values.items():
        monkeypatch.setenv(var, val)


class _Recorder:
    """MockTransport 处理器包装：记录收到的请求以便断言。"""

    def __init__(self, responder):
        self.requests: list[httpx.Request] = []
        self._responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def _chat_content(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-agent-1",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        },
    )


def _llm_json(
    lang: str = "zh",
    causes: list[dict] | None = None,
    advice: list[str] | None = None,
    citations: list[str] | None = None,
    **extra,
) -> str:
    payload = {
        "lang": lang,
        "causes": causes
        if causes is not None
        else [
            {
                "defect": "black",
                "stage": "发酵",
                "likelihood": 0.5,
                "evidence_summary": "模型判断：黑豆指向发酵过度。",
            }
        ],
        "advice": advice if advice is not None else ["模型建议：控制发酵时长。", "模型建议：干燥水分达标。"],
        "citations": citations if citations is not None else ["kb:llm-001"],
        **extra,
    }
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# TemplateAgent：12 类缺陷 × 三语齐全
# ---------------------------------------------------------------------------


class TestKnowledgeCoverage:
    def test_knowledge_covers_exactly_12_defect_classes(self):
        k = load_rootcause()
        assert set(k.defects) == set(DEFECTS)
        assert len(DEFECTS) == 12
        assert "normal" not in k.defects
        assert k.stages == VALID_STAGES == ("采摘", "发酵", "干燥", "仓储", "脱壳")

    def test_each_defect_has_three_lang_advice_and_sorted_causes(self):
        k = load_rootcause()
        for key, dk in k.defects.items():
            assert set(dk.advice) == set(LANGS), key
            for lang in LANGS:
                items = dk.advice[lang]
                assert len(items) >= 1 and all(x.strip() for x in items), (key, lang)
            liks = [c.likelihood for c in dk.causes]
            assert liks == sorted(liks, reverse=True), key
            assert all(0 < x <= 1 for x in liks), key
            assert all(c.stage in VALID_STAGES for c in dk.causes), key
            assert dk.citations, key

    def test_default_path_is_repo_config(self):
        assert DEFAULT_ROOTCAUSE_PATH.name == "rootcause.yaml"
        assert DEFAULT_ROOTCAUSE_PATH.is_file()


class TestTemplateThreeLangsAllDefects:
    @pytest.mark.parametrize("key", sorted(DEFECTS))
    @pytest.mark.parametrize("lang", LANGS)
    def test_defect_lang_report_complete(self, key: str, lang: str):
        batch = _make_batch([key, key])  # 每类 2 粒
        rep = TemplateAgent().explain(batch, lang)
        assert isinstance(rep, AgentReport)
        assert rep.backend == "template"
        assert rep.lang == lang

        causes_for = [c for c in rep.causes if c.defect == key]
        assert causes_for, f"{key}/{lang} 缺 causes"
        for c in causes_for:
            assert c.stage in VALID_STAGES
            assert 0 < c.likelihood <= 1
            assert c.evidence_summary.strip()
            assert "2" in c.evidence_summary  # {count} 已格式化
        # 证据与建议确实来自知识表（缺键即缺言）
        k = load_rootcause()
        assert rep.advice[: len(k.defects[key].advice[lang])] == list(
            k.defects[key].advice[lang]
        )
        assert list(k.defects[key].citations)[0] in rep.citations
        assert k.general.citations[0] in rep.citations

    def test_three_langs_genuinely_differ(self):
        batch = _make_batch(["black", "mold"])
        agent = TemplateAgent()
        advice = {}
        evidence = {}
        for lang in LANGS:
            rep = agent.explain(batch, lang)
            advice[lang] = rep.advice
            evidence[lang] = rep.causes[0].evidence_summary
        assert advice["zh"] != advice["en"] != advice["vi"]
        assert len({tuple(advice[l]) for l in LANGS}) == 3
        assert len(set(evidence.values())) == 3

    def test_causes_sorted_by_severity_desc(self):
        batch = _make_batch(["broken", "black", "mold"])  # black(12) 最严重
        rep = TemplateAgent().explain(batch, "zh")
        assert rep.causes[0].defect == "black"
        present = {c.defect for c in rep.causes}
        assert present == {"broken", "black", "mold"}

    def test_clean_batch_general_only(self):
        rep = TemplateAgent().explain(_make_batch([], n_normal=30), "zh")
        k = load_rootcause()
        assert rep.causes == []
        assert rep.advice == list(k.general.advice["zh"])
        assert rep.citations == list(k.general.citations)
        assert rep.backend == "template"

    def test_share_and_count_formatting(self):
        # 2 black + 8 normal = 10 粒 → 占 20.0%
        rep = TemplateAgent().explain(_make_batch(["black", "black"]), "zh")
        black_ev = [c.evidence_summary for c in rep.causes if c.defect == "black"]
        assert black_ev
        assert all("2 粒" in e and "20.0%" in e for e in black_ev)

    def test_normal_beans_not_attributed(self):
        rep = TemplateAgent().explain(_make_batch(["sour"], n_normal=50), "zh")
        assert all(c.defect != "normal" for c in rep.causes)

    def test_unknown_defect_key_raises(self):
        batch = _make_batch(["unicorn"])  # 直方里出现知识表外的键
        with pytest.raises(AgentError, match="unicorn"):
            TemplateAgent().explain(batch, "zh")

    def test_invalid_lang_raises(self):
        with pytest.raises(AgentError, match="lang"):
            TemplateAgent().explain(_make_batch(["black"]), "fr")

    def test_deterministic_output(self):
        batch = _make_batch(["black", "broken"])
        a = TemplateAgent()
        r1, r2 = a.explain(batch, "en"), a.explain(batch, "en")
        assert r1.to_json() == r2.to_json()

    def test_report_roundtrip_and_batch_embedding(self):
        batch = _make_batch(["black"])
        rep = TemplateAgent().explain(batch, "vi")
        assert AgentReport.from_json(rep.to_json()) == rep
        embedded = _make_batch(["black"], agent_report=rep)
        again = BatchResult.from_json(embedded.to_json())
        assert again.agent_report == rep
        assert again.agent_report.backend == "template"

    def test_template_speed_under_100ms(self):
        # 200 粒盘（10 缺陷粒 + 190 好豆）；耗时只随缺陷类数增长
        batch = _make_batch(
            ["black", "sour", "mold", "broken", "brocade"],
            n_normal=190,
        )
        agent = TemplateAgent()
        agent.explain(batch, "zh")  # 预热
        t0 = time.perf_counter()
        agent.explain(batch, "zh")
        dt = time.perf_counter() - t0
        assert dt < 0.1, f"TemplateAgent explain 耗时 {dt * 1000:.1f}ms ≥ 100ms"


# ---------------------------------------------------------------------------
# LLMAgent：无 key 降级 + MockTransport 解析/降级路径
# ---------------------------------------------------------------------------


class TestLLMFallbackNoNetwork:
    def test_unconfigured_degrades_to_template(self, monkeypatch):
        _clear_llm_env(monkeypatch)
        batch = _make_batch(["black", "mold"])
        llm = LLMAgent()
        rep = llm.explain(batch, "zh")
        tpl = TemplateAgent().explain(batch, "zh")
        assert rep.backend == "template"
        assert rep == tpl

    def test_partial_env_missing_key_degrades(self, monkeypatch):
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("BEANEYE_LLM_BASE_URL", "http://llm.test/v1")
        monkeypatch.setenv("BEANEYE_LLM_MODEL", "test-model")
        # key 缺失 → 未配置 → 模板
        rep = LLMAgent().explain(_make_batch(["black"]), "zh")
        assert rep.backend == "template"

    def test_empty_string_env_degrades(self, monkeypatch):
        _set_llm_env(monkeypatch, BEANEYE_LLM_KEY="   ")  # 空白 key 视同缺失
        rep = LLMAgent().explain(_make_batch(["black"]), "zh")
        assert rep.backend == "template"

    def test_invalid_lang_raises_without_network(self, monkeypatch):
        _set_llm_env(monkeypatch)
        with pytest.raises(AgentError, match="lang"):
            LLMAgent().explain(_make_batch(["black"]), "jp")

    def test_llm_configured_flag(self, monkeypatch):
        _clear_llm_env(monkeypatch)
        assert llm_configured() is False
        _set_llm_env(monkeypatch)
        assert llm_configured() is True

    def test_make_agent_backend_selection(self, monkeypatch):
        _clear_llm_env(monkeypatch)
        assert isinstance(make_agent(), TemplateAgent)
        assert isinstance(make_agent("template"), TemplateAgent)
        assert isinstance(make_agent("llm"), LLMAgent)  # 显式 llm：运行时降级
        assert isinstance(
            make_agent(base_url="http://x/v1", api_key="k", model="m"), LLMAgent
        )
        rep = make_agent("llm").explain(_make_batch(["black"]), "zh")
        assert rep.backend == "template"  # 无 mock 网络可达 → 仍落模板
        with pytest.raises(AgentError, match="backend"):
            make_agent("gpt")
        _set_llm_env(monkeypatch)
        assert isinstance(make_agent(), LLMAgent)  # auto 依据配置


class TestLLMWithMockTransport:
    def _agent(self, recorder: _Recorder, **kw) -> LLMAgent:
        client = httpx.Client(transport=httpx.MockTransport(recorder))
        return LLMAgent(http_client=client, **kw)

    def test_success_parses_canned_json(self, monkeypatch):
        _set_llm_env(monkeypatch)
        rec = _Recorder(lambda req: _chat_content(_llm_json()))
        batch = _make_batch(["black", "black", "sour"])
        rep = self._agent(rec).explain(batch, "zh")

        assert rep.backend == "llm"
        assert rep.lang == "zh"
        assert [c.defect for c in rep.causes] == ["black"]
        assert rep.causes[0].likelihood == 0.5
        assert rep.advice == ["模型建议：控制发酵时长。", "模型建议：干燥水分达标。"]
        assert rep.citations == ["kb:llm-001"]

        # 请求契约：URL / Bearer 头 / model / response_format / 提示内容
        assert len(rec.requests) == 1
        req = rec.requests[0]
        assert req.url.path == "/v1/chat/completions"
        assert req.headers["Authorization"] == "Bearer sk-test-001"
        body = rec.bodies()[0]
        assert body["model"] == "test-model"
        assert body["response_format"] == {"type": "json_object"}
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        assert "cqi_fine_robusta" in system  # 根因知识参考项带标准锚点
        assert "black" in system and "发酵" in system  # 环节先验进 prompt
        stats = json.loads(user)
        assert stats["defect_counts"] == {"black": 2, "sour": 1}
        assert stats["standard_id"] == "cqi_fine_robusta"

    def test_response_format_unsupported_falls_back_to_parse(self, monkeypatch):
        _set_llm_env(monkeypatch)

        def responder(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            if "response_format" in body:
                return httpx.Response(
                    400,
                    json={"error": {"message": "response_format is not supported"}},
                )
            fenced = "```json\n" + _llm_json() + "\n```"  # 解析兜底：剥围栏
            return _chat_content(fenced)

        rec = _Recorder(responder)
        rep = self._agent(rec).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "llm"
        assert len(rec.requests) == 2
        assert "response_format" not in rec.bodies()[1]  # 重试已去参

    def test_http_500_degrades_to_template(self, monkeypatch):
        _set_llm_env(monkeypatch)
        rec = _Recorder(lambda req: httpx.Response(500, text="boom"))
        batch = _make_batch(["black", "sour"])
        rep = self._agent(rec).explain(batch, "zh")
        tpl = TemplateAgent().explain(batch, "zh")
        assert rep.backend == "template"
        assert rep == tpl

    def test_invalid_json_degrades(self, monkeypatch):
        _set_llm_env(monkeypatch)
        rec = _Recorder(lambda req: _chat_content("这不是 JSON"))
        rep = self._agent(rec).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "template"

    def test_lang_mismatch_degrades(self, monkeypatch):
        _set_llm_env(monkeypatch)
        rec = _Recorder(lambda req: _chat_content(_llm_json(lang="zh")))
        rep = self._agent(rec).explain(_make_batch(["black"]), "en")
        assert rep.backend == "template"  # 语言不一致判失败 → 模板兜底

    def test_missing_causes_degrades(self, monkeypatch):
        _set_llm_env(monkeypatch)
        payload = json.dumps({"lang": "zh", "advice": ["x"], "citations": []}, ensure_ascii=False)
        rec = _Recorder(lambda req: _chat_content(payload))
        rep = self._agent(rec).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "template"

    def test_empty_causes_with_defects_degrades(self, monkeypatch):
        _set_llm_env(monkeypatch)
        rec = _Recorder(lambda req: _chat_content(_llm_json(causes=[])))
        rep = self._agent(rec).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "template"

    def test_empty_causes_clean_batch_is_ok(self, monkeypatch):
        _set_llm_env(monkeypatch)
        rec = _Recorder(lambda req: _chat_content(_llm_json(causes=[])))
        rep = self._agent(rec).explain(_make_batch([], n_normal=5), "zh")
        assert rep.backend == "llm"  # 好豆批允许 causes 为空

    def test_connect_error_degrades(self, monkeypatch):
        _set_llm_env(monkeypatch)

        def responder(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=req)

        rec = _Recorder(responder)
        rep = self._agent(rec).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "template"

    def test_hallucinated_defect_keys_sanitized(self, monkeypatch):
        _set_llm_env(monkeypatch)
        causes = [
            {"defect": "black", "stage": "发酵", "likelihood": 0.5, "evidence_summary": "ok"},
            {"defect": "unicorn", "stage": "发酵", "likelihood": 0.9, "evidence_summary": "x"},
            {"defect": "mold", "stage": "采摘", "likelihood": 0.4, "evidence_summary": "未检出也丢"},
        ]
        rec = _Recorder(lambda req: _chat_content(_llm_json(causes=causes)))
        rep = self._agent(rec).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "llm"
        assert [c.defect for c in rep.causes] == ["black"]  # 幻觉键被清洗

    def test_bad_stage_and_likelihood_sanitized(self, monkeypatch):
        _set_llm_env(monkeypatch)
        causes = [
            {"defect": "black", "stage": "太空", "likelihood": 0.5, "evidence_summary": "x"},
            {"defect": "black", "stage": "干燥", "likelihood": 7.5, "evidence_summary": "截断到1"},
        ]
        rec = _Recorder(lambda req: _chat_content(_llm_json(causes=causes)))
        rep = self._agent(rec).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "llm"
        assert [(c.stage, c.likelihood) for c in rep.causes] == [("干燥", 1.0)]

    def test_request_uses_env_config_and_lang_en(self, monkeypatch):
        monkeypatch.setenv("BEANEYE_LLM_BASE_URL", "http://llm.test/v1")
        monkeypatch.setenv("BEANEYE_LLM_KEY", "sk-env-9")
        monkeypatch.setenv("BEANEYE_LLM_MODEL", "env-model")
        rec = _Recorder(lambda req: _chat_content(_llm_json(lang="en")))
        rep = self._agent(rec).explain(_make_batch(["black"]), "en")
        assert rep.backend == "llm" and rep.lang == "en"
        req = rec.requests[0]
        assert req.headers["Authorization"] == "Bearer sk-env-9"
        assert json.loads(req.content)["model"] == "env-model"
        assert "English" in json.loads(req.content)["messages"][0]["content"]

    def test_kb_snippets_injected_into_prompt(self, monkeypatch):
        _set_llm_env(monkeypatch)

        class _Kb:
            def retrieve(self, query: str, k: int = 4):
                assert "black" in query
                return [
                    KbChunk(
                        chunk_id="kb:rootcause.black",
                        text="黑豆多因发酵过度或带果闷堆。",
                        source="std:cqi_fine_robusta",
                        score=0.9,
                    )
                ]

        rec = _Recorder(lambda req: _chat_content(_llm_json()))
        rep = self._agent(rec, kb=_Kb()).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "llm"
        system = json.loads(rec.requests[0].content)["messages"][0]["content"]
        assert "kb:rootcause.black" in system
        assert "黑豆多因发酵过度或带果闷堆。" in system


# ---------------------------------------------------------------------------
# 根因知识表加载校验（12 类齐全是加载期不变式）
# ---------------------------------------------------------------------------


class TestKnowledgeLoaderValidation:
    def _write(self, tmp_path, raw: dict):
        import yaml

        p = tmp_path / "rootcause_bad.yaml"
        p.write_text(
            yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8"
        )
        return p

    def _good_raw(self) -> dict:
        import yaml

        return yaml.safe_load(DEFAULT_ROOTCAUSE_PATH.read_text(encoding="utf-8"))

    def test_missing_defect_entry_rejected(self, tmp_path):
        raw = self._good_raw()
        raw["defects"].pop("black")
        with pytest.raises(RootCauseConfigError, match="black"):
            load_rootcause(self._write(tmp_path, raw))

    def test_extra_defect_entry_rejected(self, tmp_path):
        raw = self._good_raw()
        raw["defects"]["ghost"] = raw["defects"]["black"]
        with pytest.raises(RootCauseConfigError, match="ghost"):
            load_rootcause(self._write(tmp_path, raw))

    def test_normal_key_rejected(self, tmp_path):
        raw = self._good_raw()
        raw["defects"]["normal"] = raw["defects"]["black"]
        with pytest.raises(RootCauseConfigError, match="normal"):
            load_rootcause(self._write(tmp_path, raw))

    def test_bad_stage_rejected(self, tmp_path):
        raw = self._good_raw()
        raw["defects"]["black"]["causes"][0]["stage"] = "太空"
        with pytest.raises(RootCauseConfigError, match="stage"):
            load_rootcause(self._write(tmp_path, raw))

    def test_bad_likelihood_rejected(self, tmp_path):
        raw = self._good_raw()
        raw["defects"]["black"]["causes"][0]["likelihood"] = 1.5
        with pytest.raises(RootCauseConfigError, match="likelihood"):
            load_rootcause(self._write(tmp_path, raw))

    def test_advice_missing_lang_rejected(self, tmp_path):
        raw = self._good_raw()
        raw["defects"]["sour"]["advice"].pop("vi")
        with pytest.raises(RootCauseConfigError, match="advice"):
            load_rootcause(self._write(tmp_path, raw))

    def test_bad_placeholder_rejected(self, tmp_path):
        raw = self._good_raw()
        raw["evidence"]["zh"] = "检出 {bogus} 粒"
        with pytest.raises(RootCauseConfigError, match="占位符|格式化"):
            load_rootcause(self._write(tmp_path, raw))

    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(RootCauseConfigError, match="不存在"):
            load_rootcause(tmp_path / "nope.yaml")


# ---------------------------------------------------------------------------
# 知识库接口（beaneye.kb 留桩）
# ---------------------------------------------------------------------------


class TestKbInterface:
    def test_null_kb_returns_empty(self):
        kb = NullKnowledgeBase()
        assert kb.retrieve("任何查询") == []
        assert kb.retrieve("任何查询", k=0) == []

    def test_chunk_holds_citation_fields(self):
        c = KbChunk(chunk_id="kb:x.01", text="内容", source="std:demo", score=0.5)
        assert c.chunk_id and c.text and c.metadata == {}

    def test_agent_runs_with_null_kb_offline(self, monkeypatch):
        _clear_llm_env(monkeypatch)
        rep = LLMAgent(kb=NullKnowledgeBase()).explain(_make_batch(["black"]), "zh")
        assert rep.backend == "template"
