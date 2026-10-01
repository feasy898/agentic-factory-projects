"""M11 TemplateAgent：离线规则溯因（数据源 configs/rootcause.yaml）。

按 ``BatchResult.grading.defect_counts``（契约不变式：每粒只计最严重缺陷）
逐缺陷查根因知识表，产出三语 :class:`AgentReport`：

- causes：检出缺陷 × 知识表环节归因候选（likelihood 降序），证据句带
  粒数/占比实据；缺陷按严重度降序（高严重度缺陷排最前）；
- advice：检出缺陷的建议 + ``general`` 通用建议（去重保序）；
- citations：检出缺陷的引用 + ``general`` 引用（去重保序）；
- 好豆批（无缺陷）：causes=[]，只有 general 建议与引用。

任何部署形态（含完全断网、零外部依赖）都可用：只依赖 PyYAML + 契约模型。
耗时不随豆数增长（只按缺陷**类**展开），满足 ≤100ms 通过线。
"""

from __future__ import annotations

from beaneye.schemas import AgentReport, BatchResult, CauseItem

from .knowledge import LANGS, RootCauseKnowledge, load_rootcause

__all__ = ["AgentError", "TemplateAgent"]


class AgentError(ValueError):
    """智能体调用方式错误（如非法语言、知识表与契约不一致）。"""


class TemplateAgent:
    """离线模板溯因智能体（保底实现，也是 LLMAgent 的降级目标）。"""

    def __init__(self, knowledge: RootCauseKnowledge | None = None):
        from beaneye.taxonomy import load_taxonomy

        self.knowledge = knowledge if knowledge is not None else load_rootcause()
        self._tax = load_taxonomy()  # 缺陷三语名（taxonomy.yaml）

    # ------------------------------------------------------------------
    def explain(self, result: BatchResult, lang: str) -> AgentReport:
        if lang not in LANGS:
            raise AgentError(f"lang 必须是 {list(LANGS)} 之一，得到 {lang!r}")

        # 检出缺陷（每粒只计最严重缺陷的直方；normal 非缺陷）
        counts = {
            k: n
            for k, n in result.grading.defect_counts.items()
            if n > 0 and k != "normal"
        }
        # 缺陷严重度位次取自逐粒裁决结果（不同标准可覆盖默认序）
        rank: dict[str, int] = {}
        for b in result.beans:
            if b.final_defect == "normal":
                continue
            rank[b.final_defect] = max(rank.get(b.final_defect, 0), b.final_severity_rank)

        unknown = sorted(set(counts) - set(self.knowledge.defects))
        if unknown:
            raise AgentError(
                f"根因知识表缺少缺陷类 {unknown} 的条目（知识表与契约不一致，"
                "请检查 configs/rootcause.yaml）"
            )

        # 展示顺序：严重度降序 → 粒数降序 → key 稳定序
        order = sorted(counts, key=lambda k: (-rank.get(k, 0), -counts[k], k))

        total = result.measurements.bean_count if result.measurements.bean_count > 0 else len(result.beans)
        causes: list[CauseItem] = []
        advice: list[str] = []
        citations: list[str] = []
        for key in order:
            dk = self.knowledge.defects[key]
            name = getattr(self._tax.get(key), lang)  # 缺陷三语显示名
            for rule in dk.causes:
                causes.append(
                    CauseItem(
                        defect=key,
                        stage=rule.stage,
                        likelihood=rule.likelihood,
                        evidence_summary=dk.format_evidence(
                            rule,
                            lang,
                            count=counts[key],
                            total=total,
                            name=name,
                            stage_display=self.knowledge.stage_names,
                        ),
                    )
                )
            advice.extend(dk.advice[lang])
            citations.extend(dk.citations)

        # 通用建议/引用：所有批次都追加（好豆批即其全部输出）
        advice.extend(self.knowledge.general.advice[lang])
        citations.extend(self.knowledge.general.citations)

        return AgentReport(
            lang=lang,  # type: ignore[arg-type]
            causes=causes,
            advice=list(dict.fromkeys(advice)),
            citations=list(dict.fromkeys(citations)),
            backend="template",
        )
