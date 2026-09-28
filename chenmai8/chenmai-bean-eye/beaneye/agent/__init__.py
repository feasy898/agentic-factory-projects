"""M11 溯因智能体：TemplateAgent（离线规则保底）+ LLMAgent（自动降级）。

对外入口::

    from beaneye.agent import TemplateAgent, LLMAgent, make_agent

    agent = make_agent()            # auto: 配了 LLM 用 LLMAgent，否则 Template
    report = agent.explain(batch_result, lang="zh")   # -> AgentReport(backend=...)

知识表：``configs/rootcause.yaml``（12 类缺陷 × 环节归因先验 × 三语建议），
加载校验见 :mod:`beaneye.agent.knowledge`；知识库检索接口（可选增强）
见 :mod:`beaneye.kb`。LLM 与知识库都不影响主链路（评测不依赖网络）。
"""

from beaneye.schemas import RootCauseAgent

from .knowledge import (
    DEFAULT_ROOTCAUSE_PATH,
    LANGS,
    VALID_STAGES,
    CauseRule,
    DefectKnowledge,
    GeneralKnowledge,
    RootCauseConfigError,
    RootCauseKnowledge,
    load_rootcause,
)
from .llm import (
    ENV_BASE_URL,
    ENV_KEY,
    ENV_MODEL,
    LLMAgent,
    llm_config,
    llm_configured,
)
from .template import AgentError, TemplateAgent

__all__ = [
    "RootCauseAgent",
    "AgentError",
    "RootCauseConfigError",
    "TemplateAgent",
    "LLMAgent",
    "make_agent",
    "llm_config",
    "llm_configured",
    "load_rootcause",
    "RootCauseKnowledge",
    "DefectKnowledge",
    "CauseRule",
    "GeneralKnowledge",
    "DEFAULT_ROOTCAUSE_PATH",
    "LANGS",
    "VALID_STAGES",
    "ENV_BASE_URL",
    "ENV_KEY",
    "ENV_MODEL",
]


def make_agent(
    backend: str = "auto",
    *,
    knowledge: RootCauseKnowledge | None = None,
    kb: "object | None" = None,
    http_client: "object | None" = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    timeout_s: float = 20.0,
) -> RootCauseAgent:
    """构造溯因智能体（应用壳 M13 的规范入口）。

    - ``"template"``：只离线模板；
    - ``"llm"``：LLM 优先（未配置/失败时每次 explain 自动降级模板）；
    - ``"auto"``（默认）：按当前配置选择——``llm_configured()`` 为真用
      LLMAgent，否则直接 TemplateAgent。
    """
    if backend == "template":
        return TemplateAgent(knowledge)
    if backend in ("llm", "auto"):
        if backend == "auto" and not llm_configured() and not any((base_url, api_key, model)):
            return TemplateAgent(knowledge)
        return LLMAgent(
            base_url=base_url,
            api_key=api_key,
            model=model,
            knowledge=knowledge,
            kb=kb,  # type: ignore[arg-type]
            http_client=http_client,  # type: ignore[arg-type]
            timeout_s=timeout_s,
        )
    raise AgentError(f"backend 必须是 'auto'/'template'/'llm'，得到 {backend!r}")
