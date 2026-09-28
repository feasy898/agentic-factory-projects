"""标准引擎（M9 · YAML → 定级判定，换标准不改代码）。

实现冻结契约 ``beaneye.schemas.StandardEngine`` Protocol::

    evaluate(beans: list[PairedBean], measurements: Measurements) -> GradingDecision

判定流程（开发指令 §4 M9 spec）：
1. 按 ``count_rule`` 计数——v1 仅实现 ``most_severe_per_bean``（每粒只按
   ``final_defect`` 计一次，复用 W7 已与契约交叉验证的
   ``severity.count_defects`` / ``severity.primary_secondary_counts``；
   ``per_side`` 计数与契约 ``BatchResult.defect_counts`` 不变式冲突，
   显式抛 :class:`StandardsError`）；
2. 主/次缺陷分计（peaberry 计量不计缺陷，见 configs/taxonomy.yaml）；
3. 逐 grade 判定（grades 从最优到最差，取第一个满足全部条件者）：
   主缺陷数 ≤ primary_max、次缺陷数 ≤ secondary_full_max、
   筛目条件（grade.sieve_min 非 null 时，sieve_hist 中 screen < sieve_min
   的粒数须为 0，v0 语义待原文核对）、全局色差条件
   （metrology.delta_e_max 非 null 时 delta_e_mean ≤ 该值）；
4. 生成 reasons（i18n 模板键 + 数值），格式::

       "<模板键>:<k>=<v>[;<k>=<v>]*"

   模板键字符集 ``[A-Za-z0-9_.]``，M10 按 lang 查表渲染三语文本；
5. 输出 GradingDecision（含文件 sha256 与 verified:false warnings）。
全部 grade 未达时 grade = 标准 YAML 的 fail_grade、passed=False。
"""

from __future__ import annotations

from beaneye.schemas import GradingDecision, Measurements, PairedBean, StandardEngine
from beaneye.severity import (
    CQI_COUNT_RULE,
    count_defects,
    primary_secondary_counts,
)
from beaneye.standards.loader import (
    DEFAULT_STANDARDS_DIR,
    GradeRule,
    LMap,  # noqa: F401  (re-export 便利)
    Standard,
    StandardsError,
    load_standard,
    list_standards,
)

__all__ = [
    "StandardsError",
    "StandardEngineV1",
    "load_engine",
    "load_standard",
    "list_standards",
    "DEFAULT_STANDARDS_DIR",
]


def _reason(key: str, **kv: object) -> str:
    """拼一条 reason：``模板键:k=v;k=v``（模板键 [A-Za-z0-9_.]，数值 str 化）。"""
    payload = ";".join(f"{k}={v}" for k, v in kv.items())
    return f"{key}:{payload}" if payload else key


def _below_sieve_count(standard: Standard, measurements: Measurements, sieve_min: int) -> int:
    """sieve_hist 中 screen < sieve_min 的粒数（键必须是目数整数字符串）。"""
    total = 0
    for key, n in measurements.sieve_hist.items():
        try:
            screen = int(key)
        except (TypeError, ValueError):
            raise StandardsError(
                f"sieve_hist 键 {key!r} 不是目数整数字符串"
                f"（standard={standard.standard_id}, 文件={standard.path}）"
            ) from None
        if screen < sieve_min:
            total += int(n)
    return total


class StandardEngineV1:
    """YAML 标准引擎 v1：配置驱动定级（换标准 = 换 YAML，不改代码）。

    满足冻结契约 ``StandardEngine`` Protocol；``Standard`` 来自
    :func:`beaneye.standards.load_standard`。
    """

    def __init__(self, standard: Standard):
        self.standard = standard

    @classmethod
    def load(cls, target: str) -> "StandardEngineV1":
        """按 id/路径加载标准并构造引擎（load_standard(id) 的便捷入口）。"""
        return cls(load_standard(target))

    # -- 定级 ----------------------------------------------------------------
    def evaluate(
        self, beans: list[PairedBean], measurements: Measurements
    ) -> GradingDecision:
        std = self.standard
        if std.count_rule != CQI_COUNT_RULE:
            raise StandardsError(
                f"count_rule={std.count_rule!r} 暂不支持：v1 仅实现 {CQI_COUNT_RULE!r}"
                "（每粒只计最严重缺陷；per_side 计数与契约 BatchResult.defect_counts"
                f" 不变式冲突）standard={std.standard_id}, 文件={std.path}"
            )

        hist = count_defects(beans)  # 每粒只计一次（W7 实现，与契约交叉验证）
        primary, secondary = primary_secondary_counts(beans)
        de_max = std.metrology.delta_e_max

        def conditions(g: GradeRule) -> tuple[bool, int]:
            """返回 (该级全部条件是否满足, 低于筛目下限的粒数)。"""
            ok_p = primary <= g.primary_max
            ok_s = secondary <= g.secondary_full_max
            below = (
                _below_sieve_count(std, measurements, g.sieve_min) if g.sieve_min is not None else 0
            )
            ok_sv = g.sieve_min is None or below == 0
            ok_de = de_max is None or measurements.delta_e_mean <= de_max
            return (ok_p and ok_s and ok_sv and ok_de), below

        chosen: GradeRule | None = None
        below_ref = 0
        for g in std.grades:
            ok, below = conditions(g)
            if ok:
                chosen = g
                below_ref = below
                break
        # 条件理由统一相对「选定级；全部未达时相对最严的第一级」输出
        ref = chosen if chosen is not None else std.grades[0]
        if chosen is None:
            below_ref = _below_sieve_count(std, measurements, ref.sieve_min) if ref.sieve_min is not None else 0

        reasons: list[str] = []
        reasons.append(
            _reason(
                "grading.reason.primary_within_limit" if primary <= ref.primary_max else "grading.reason.primary_over_limit",
                count=primary,
                limit=ref.primary_max,
            )
        )
        reasons.append(
            _reason(
                "grading.reason.secondary_within_limit"
                if secondary <= ref.secondary_full_max
                else "grading.reason.secondary_over_limit",
                count=secondary,
                limit=ref.secondary_full_max,
            )
        )
        if ref.sieve_min is not None:
            reasons.append(
                _reason(
                    "grading.reason.sieve_ok" if below_ref == 0 else "grading.reason.sieve_below_min",
                    sieve_min=ref.sieve_min,
                    below=below_ref,
                )
            )
        if de_max is not None:
            reasons.append(
                _reason(
                    "grading.reason.delta_e_ok"
                    if measurements.delta_e_mean <= de_max
                    else "grading.reason.delta_e_over",
                    delta_e=measurements.delta_e_mean,
                    limit=de_max,
                )
            )

        if chosen is not None:
            passed = True
            grade = chosen.name
            reasons.append(_reason("grading.reason.grade_selected", grade=chosen.name, index=chosen.index))
        else:
            passed = False
            grade = std.fail_grade
            reasons.append(
                _reason("grading.reason.no_grade_matched", grades=len(std.grades), fail_grade=std.fail_grade)
            )

        return GradingDecision(
            standard_id=std.standard_id,
            grade=grade,
            passed=passed,
            primary_count=primary,
            secondary_count=secondary,
            defect_counts=hist,
            reasons=reasons,
            warnings=list(std.warnings),
            standard_yaml_sha=std.sha256,
        )


def load_engine(target: str) -> StandardEngineV1:
    """load_standard(id) + StandardEngineV1 的组合便捷入口。"""
    return StandardEngineV1(load_standard(target))


# 协议一致性：StandardEngineV1 必须可赋给冻结契约 StandardEngine
_engine_protocol_check: type[StandardEngine] = StandardEngineV1  # type: ignore[assignment]
