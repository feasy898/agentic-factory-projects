# M7 严重度裁决 spec（severity · 裁决规则）

> 状态：冻结（83 用例全绿，2026-09-29 实测）。
> 本页对照 `beaneye/severity/adjudicate.py` 与契约 `beaneye/schemas.py`（`_resolve_worst` /
> `defect_is_countable`）逐行核验于 2026-09-29。
> 定位：「每粒只计最严重缺陷」这句契约的唯一执行者——契约校验器与裁决器共用同一套规则，
> 两侧人工保持逐位一致。

---

## 1. 裁决规则（`worst(top, bottom, severity_order) -> (final_defect, worst_side)`）

按优先级自上而下，第一条命中即返回：

| # | 条件 | 裁决 |
|---|---|---|
| 1 | 两面皆 None | `("normal", "none")`，rank 0 |
| 2 | 仅一面有观测 | 取该面：`final_defect`=该面 defect，`worst_side`=该面 |
| 3 | 两面都有，**且存在可计缺陷面**（`counts_as_defect=true`） | **只在可计面之间裁决**；非可计面（peaberry 标注）保留在字段里但不参与最终缺陷 |
| 4 | 两面都有，皆非可计缺陷/normal | 退回全量比较（peaberry 标注语义不丢失） |
| 5 | 可计面之间（或全量）：rank 不等 | rank 高者胜，`worst_side`=胜面 |
| 6 | rank 相等（同序位=同缺陷） | 取 `defect_conf` 高者并记 `worst_side="both"`；**conf 完全相等偏向 top**（与契约逐位一致） |

**W13 修复的语义坑（peaberry 吞次缺陷）**：peaberry 在 taxonomy 中 `counts_as_defect=false`
（计量不计缺陷、仅标注保留）。若不把它从比较中剔除，一面 peaberry（rank 5）会「吞掉」
另一面 broken（rank 1）等可计缺陷——final_defect=peaberry 又不计缺陷，这粒豆就从缺陷
统计里消失了。规则 #3 即堵此洞：存在可计面时只在可计面间裁决。
`defect_is_countable`（schemas.py）是唯一判据，M7 与契约共用；未知类别（不在 taxonomy）
一律 False。

## 2. severity_order（可换序的根）

- **默认序**：`configs/taxonomy.yaml` 的 `severity_order`——
  `[normal, broken, faded, brocade, immature, peaberry, shell, elephant, insect, dried, sour, mold, black]`，
  下标即 `severity_rank`（0=normal，越大越严重）。
- **标准覆盖序**：标准 YAML 的 `severity_order`（不同标准可不同）；`SeverityOrder.from_standard_yaml`
  要求**恰好覆盖 taxonomy 全部类别**（`ensure_covers_taxonomy`，缺失/未知都报错）。
- **构造即校验**：非空、无重复、`[0]` 必须是 normal（0=normal 是契约，缺陷类 rank 必须 >0，
  `BeanObservation` 构造期同样强制）。
- **换序衔接**：`rebase_observation` 把已有观测的 `severity_rank` 改写为当前序位次后，
  `PairedBean` 不变式在任意标准序下仍成立（`adjudicate_pairs` 即「rebase + 裁决 + 契约构造」
  的一条龙入口）。

## 3. 计数规则（CQI `most_severe_per_bean`，一粒只计一次）

| 函数 | 口径 |
|---|---|
| `count_defects(beans)` | 每粒按 `final_defect` 计一次的直方（normal 不计）。**独立实现**，与契约 `schemas.defect_counts_from_beans` 交叉验证（tests/test_severity.py 锁定一致性） |
| `effective_defect_counts(beans)` | 再剔除 `counts_as_defect=false` 的类（peaberry 不入缺陷直方） |
| `primary_secondary_counts(beans)` | 主/次分计（`GradingDecision.primary_count/secondary_count` 的口径）；peaberry 不计入 |

M9 引擎直接复用这三个函数（不再另写计数），保证「引擎计数 = 契约计数」。

## 4. 契约双侧一致性（为什么两处实现不是坏味道）

契约侧 `_resolve_worst`（schemas.py）在 `PairedBean` 校验器里**每次构造都重跑**——任何来源
（M6 配对、测试 fixture、手工构造）写入的 `final_*` 字段与两面观测不一致立即 `ValidationError`。
M7 侧 `SeverityAdjudicator.worst_detail` 提供明细版（多返回 `winner_side/winner_conf/tie`，
供展示与调试），核心规则逐位相同且共用 `defect_is_countable`。**改动任何一侧的裁决规则 =
 破坏契约**，必须两侧同步 + 三道门复跑。

## 5. eval

```bash
python -m pytest tests/test_severity.py -q
# → 83 passed（2026-09-29 实测）
# 覆盖：表驱动 22 例（单缺陷/多缺陷/临界序/并列/单面/normal-vs-缺陷）、自定义序翻转/rebase、
#   标准 YAML 读取与部分覆盖拒绝、非法序/未知类拒绝、count_defects vs 契约直方交叉验证、
#   peaberry 吞次缺陷回归（W13）
```
