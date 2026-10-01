"""M11 LLMAgent：OpenAI 兼容 ChatCompletions 溯因后端（env 驱动）。

配置（环境变量，全部就位才算已配置）::

    BEANEYE_LLM_BASE_URL   如 https://host/v1（内部拼 /chat/completions）
    BEANEYE_LLM_KEY        Bearer 令牌
    BEANEYE_LLM_MODEL      模型名

行为契约（§4 M11）：

- **无 key / 配置不全 → 自动降级** TemplateAgent，``report.backend="template"``；
- system prompt 内嵌：输出 JSON schema 约定 + 标准 YAML 摘要 + 根因知识表
  参考项 + 知识库（``beaneye.kb``）检索片段；user 消息为整盘统计 JSON；
- 输出强制 JSON（``response_format=json_object``）；服务端不支持该参数时
  去掉参数重试一次，走**解析兜底**（剥 ```json 围栏 / 截取首尾花括号）；
- **任何失败**（网络/HTTP/解析/校验）都自动降级 TemplateAgent，并以
  ``report.backend="template"`` 标注——LLM 永不影响主链路；
- LLM 输出做严格净化后才进 AgentReport：lang 必须与请求一致、
  causes 只保留「本次检出且 taxonomy 合法」的缺陷、stage 只取加工五环节、
  likelihood 截断到 [0,1]、advice 非空；检出缺陷却给不出有效 causes 时判失败。

``http_client`` 可注入 httpx.Client（评测用 MockTransport，生产可复用连接池）。
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import httpx

from beaneye.kb import KnowledgeBase
from beaneye.schemas import AgentReport, BatchResult, CauseItem

from .knowledge import LANGS, VALID_STAGES, RootCauseKnowledge, load_rootcause
from .template import AgentError, TemplateAgent

ENV_BASE_URL = "BEANEYE_LLM_BASE_URL"
ENV_KEY = "BEANEYE_LLM_KEY"
ENV_MODEL = "BEANEYE_LLM_MODEL"

REPO_ROOT = Path(__file__).resolve().parents[2]

__all__ = [
    "ENV_BASE_URL",
    "ENV_KEY",
    "ENV_MODEL",
    "LLMAgent",
    "llm_config",
    "llm_configured",
]


def llm_config() -> dict[str, str] | None:
    """读取 LLM 配置；base_url/key/model 任一缺失即返回 None（未配置）。"""
    cfg = {
        "base_url": (os.environ.get(ENV_BASE_URL) or "").strip().rstrip("/"),
        "api_key": (os.environ.get(ENV_KEY) or "").strip(),
        "model": (os.environ.get(ENV_MODEL) or "").strip(),
    }
    if all(cfg.values()):
        return cfg
    return None


def llm_configured() -> bool:
    """LLM 后端是否已配置（未配置时 LLMAgent 每次都直接走 Template）。"""
    return llm_config() is not None


_FENCE_RE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$")


class LLMAgent:
    """LLM 溯因智能体：可用时增强、任何失败自动落回模板保底。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        *,
        knowledge: RootCauseKnowledge | None = None,
        kb: KnowledgeBase | None = None,
        http_client: httpx.Client | None = None,
        timeout_s: float = 20.0,
        temperature: float = 0.2,
    ):
        from beaneye.taxonomy import load_taxonomy

        self._overrides = {
            k: v for k, v in (("base_url", base_url), ("api_key", api_key), ("model", model)) if v
        }
        self._fallback = TemplateAgent(knowledge)
        self.knowledge = knowledge if knowledge is not None else self._fallback.knowledge
        self._tax = load_taxonomy()
        self._kb = kb
        self._http_client = http_client
        self._timeout_s = timeout_s
        self._temperature = temperature

    # ------------------------------------------------------------------
    def explain(self, result: BatchResult, lang: str) -> AgentReport:
        # 调用方式错误（非法语言）直接抛出，不做静默降级
        if lang not in LANGS:
            raise AgentError(f"lang 必须是 {list(LANGS)} 之一，得到 {lang!r}")
        cfg = self._config()
        if cfg is None:  # 未配置（无 key）→ 自动降级
            return self._fallback.explain(result, lang)
        try:
            return self._explain_llm(result, lang, cfg)
        except Exception:  # noqa: BLE001 —— 任何失败都降级 Template 并标注 backend
            return self._fallback.explain(result, lang)

    # ------------------------------------------------------------------
    def _config(self) -> dict[str, str] | None:
        env = llm_config() or {}
        merged = {**env, **self._overrides}
        if all(merged.get(k) for k in ("base_url", "api_key", "model")):
            return merged
        return None

    def _explain_llm(self, result: BatchResult, lang: str, cfg: dict[str, str]) -> AgentReport:
        stats = self._stats_payload(result)
        messages = [
            {"role": "system", "content": self._system_prompt(result, lang, stats)},
            {"role": "user", "content": json.dumps(stats, ensure_ascii=False)},
        ]
        url = cfg["base_url"] + "/chat/completions"
        headers = {"Authorization": f"Bearer {cfg['api_key']}"}

        use_response_format = True
        own_client = self._http_client is None
        client = self._http_client or httpx.Client(timeout=self._timeout_s)
        try:
            for _attempt in range(2):  # 最多一次「去掉 response_format」重试
                body: dict[str, Any] = {
                    "model": cfg["model"],
                    "messages": messages,
                    "temperature": self._temperature,
                }
                if use_response_format:
                    body["response_format"] = {"type": "json_object"}
                resp = client.post(url, json=body, headers=headers)
                if resp.status_code >= 400:
                    # response_format 不被支持 → 去参重试，走解析兜底
                    if use_response_format and "response_format" in resp.text:
                        use_response_format = False
                        continue
                    raise AgentError(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._sanitize(_extract_json(content), lang, result)
        finally:
            if own_client:
                client.close()
        raise AgentError("LLM 请求重试次数耗尽")  # pragma: no cover

    # ------------------------------------------------------------------
    def _stats_payload(self, result: BatchResult) -> dict[str, Any]:
        m, g = result.measurements, result.grading
        return {
            "sample_id": result.sample_id,
            "standard_id": g.standard_id,
            "grade": g.grade,
            "passed": g.passed,
            "bean_count": m.bean_count,
            "defect_counts": {
                k: n for k, n in g.defect_counts.items() if k != "normal" and n > 0
            },
            "sieve_pass": m.sieve_pass,
            "sieve_hist": m.sieve_hist,
            "delta_e_mean": round(m.delta_e_mean, 2),
            "est_weight_g": round(m.est_weight_g, 1),
        }

    def _standard_summary(self, standard_id: str) -> dict[str, Any] | None:
        """标准 YAML 摘要（standards 引擎落地后自动带上；缺文件时省略）。"""
        path = REPO_ROOT / "configs" / "standards" / f"{standard_id}.yaml"
        if not path.is_file():
            return None
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:  # noqa: BLE001 —— 摘要失败不影响主流程
            return None

    def _kb_snippets(self, query: str) -> list[str]:
        if self._kb is None:
            return []
        try:
            chunks = self._kb.retrieve(query, k=4)
        except Exception:  # noqa: BLE001 —— 检索失败不阻塞
            return []
        return [f"- [{c.chunk_id}] {c.text}" for c in chunks]

    def _system_prompt(self, result: BatchResult, lang: str, stats: dict[str, Any]) -> str:
        present = sorted(
            (k for k, n in result.grading.defect_counts.items() if k != "normal" and n > 0),
            key=lambda k: -max(
                (b.final_severity_rank for b in result.beans if b.final_defect == k),
                default=0,
            ),
        )
        reference = []
        for key in present:
            dk = self.knowledge.defects.get(key)
            if dk is None:
                continue
            reference.append(
                {
                    "defect": key,
                    "stage_priors": [
                        {"stage": r.stage, "likelihood": r.likelihood} for r in dk.causes
                    ],
                    "advice_candidates": list(dk.advice[lang]),
                    "citations": list(dk.citations),
                }
            )
        lang_name = {"zh": "中文", "en": "English", "vi": "Tieng Viet (khong dau)"}[lang]
        parts = [
            "你是生豆质检溯因助手：根据整盘检测结果给出加工环节归因与改进建议。",
            "输出要求（必须严格遵守）:",
            "1. 只输出一个 JSON 对象，不要多余文字，字段: "
            '{"lang": ..., "causes": [...], "advice": [...], "citations": [...]}。',
            '2. causes 元素形如 {"defect": ..., "stage": ..., "likelihood": ..., '
            '"evidence_summary": ...}; defect 只能取检出统计中出现的缺陷键; '
            f"stage 只能取 {'/'.join(VALID_STAGES)}; likelihood 在 0-1 之间。",
            f"3. 所有文字用{lang_name}书写, 且 lang 字段固定为 \"{lang}\"。",
            "4. advice 给 3-8 条可执行改进建议; citations 优先引用参考项给定的条目。",
            f"根因知识参考项: {json.dumps(reference, ensure_ascii=False)}",
        ]
        std = self._standard_summary(stats.get("standard_id", ""))
        if std is not None:
            parts.append(f"标准摘要: {json.dumps(std, ensure_ascii=False)}")
        snippets = self._kb_snippets(
            stats.get("standard_id", "") + " " + " ".join(present)
        )
        if snippets:
            parts.append("知识库检索片段:\n" + "\n".join(snippets))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    def _sanitize(self, raw: Any, lang: str, result: BatchResult) -> AgentReport:
        """LLM 输出净化：不符合约定即抛错（由 explain 捕获后降级模板）。"""
        if not isinstance(raw, dict):
            raise AgentError("LLM 输出不是 JSON 对象")
        if raw.get("lang") != lang:
            raise AgentError(f"LLM 返回语言 {raw.get('lang')!r} 与请求 {lang!r} 不一致")

        present = {
            k for k, n in result.grading.defect_counts.items() if k != "normal" and n > 0
        }
        valid_keys = set(self._tax.keys())
        stages = set(self.knowledge.stages)

        causes: list[CauseItem] = []
        raw_causes = raw.get("causes")
        if not isinstance(raw_causes, list):
            raise AgentError("LLM 输出缺少 causes 列表")
        for item in raw_causes:
            if not isinstance(item, dict):
                continue
            defect = item.get("defect")
            stage = item.get("stage")
            # 只保留「本次检出 + taxonomy 合法」的缺陷；幻觉缺陷一律丢弃
            if defect not in present or defect not in valid_keys:
                continue
            if stage not in stages:
                continue
            lik = item.get("likelihood")
            if not isinstance(lik, (int, float)) or isinstance(lik, bool):
                continue
            lik = min(1.0, max(0.0, float(lik)))
            if not math.isfinite(lik):
                continue
            evidence = item.get("evidence_summary")
            if not isinstance(evidence, str) or not evidence.strip():
                continue
            causes.append(
                CauseItem(
                    defect=defect,
                    stage=stage,  # type: ignore[arg-type]
                    likelihood=lik,
                    evidence_summary=evidence.strip(),
                )
            )
        # 检出了缺陷却给不出任何有效归因 → 判失败（降级模板兜底）
        if present and not causes:
            raise AgentError("LLM 未给出任何有效 causes")

        advice_raw = raw.get("advice")
        if not isinstance(advice_raw, list):
            raise AgentError("LLM 输出缺少 advice 列表")
        advice = [a.strip() for a in advice_raw if isinstance(a, str) and a.strip()]
        if not advice:
            raise AgentError("LLM advice 为空")

        citations_raw = raw.get("citations", [])
        citations = [c.strip() for c in citations_raw if isinstance(c, str) and c.strip()]

        return AgentReport(
            lang=lang,  # type: ignore[arg-type]
            causes=causes,
            advice=advice,
            citations=citations,
            backend="llm",
        )


def _extract_json(content: str) -> Any:
    """解析兜底：剥 markdown 围栏，截取首 ``{`` 到末 ``}``，再 JSON 解析。"""
    text = _FENCE_RE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AgentError(f"LLM 输出中找不到 JSON 对象: {content[:120]!r}")
    return json.loads(text[start : end + 1])
