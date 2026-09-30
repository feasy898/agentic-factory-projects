# M7 严重度裁决 spec（severity · 裁决规则）

> 状态：冻结（83 用例全绿；2026-09-30 回炉复跑 `tests/test_severity.py` 83 passed 实测）。
> 本页对照 `beaneye/severity/adjudicate.py` 与契约 `beaneye/schemas.py`（`_resolve_worst` /
> `defect_is_countable`）逐行核验于 2026-09-29；2026-09-30 回炉复核，补齐六项缺口：
> 逐类 primary/secondary 与 counts_as_defect 全表（§2）、「按序查 rank 而非缓存」显式化（§3）、
> worst_detail 双 None 分支取值（§1 #1）、未知类构造期拒绝（§1 末）、pairing_cost 两口径
> 强制（§3 末）、include_normal 缺省（§4）。
> 定位：「每粒只计最严重缺陷」这句契约的唯一执行者——契约校验器与裁决器共用同一套规则，
> 两侧人工保持逐位一致。

---

## 1. 裁决规则（`worst(top, bottom, severity_order) -> (final_defect, worst_side)`）

按优先级自上而下，第一条命中即返回：

| # | 条件 | 裁决 |
|---|---|---|
| 1 | 两面皆 None | `("normal", "none")`，rank 0；明细版全字段取值 `WorstResult(final_defect="normal", worst_side="none", final_severity_rank=0, winner_side="none", winner_conf=None, tie=False)`（adjudicate.py:185-186，2026-09-30 实测） |
| 2 | 仅一面有观测 | 取该面：`final_defect`=该面 defect，`worst_side`=该面 |
| 3 | 两面都有，**且存在可计缺陷面**（`counts_as_defect=true`） | **只在可计面之间裁决**；非可计面（peaberry 标注）保留在字段里但不参与最终缺陷 |
| 4 | 两面都有，皆非可计缺陷/normal | 退回全量比较（peaberry 标注语义不丢失） |
| 5 | 可计面之间（或全量）：rank 不等 | rank 高者胜，`worst_side`=胜面 |
| 6 | rank 相等（同序位=同缺陷） | 取 `defect_conf` 高者并记 `worst_side="both"`；**conf 完全相等偏向 top**（与契约逐位一致） |

**W13 修复的语义坑（peaberry 吞次缺陷）**：peaberry 在 taxonomy 中 `counts_as_defect=false`
（计量不计缺陷、仅标注保留）。若不把它从比较中剔除，一面 peaberry（rank 5）会「吞掉」
另一面 broken（rank 1）等可计缺陷——final_defect=peaberry 又不计缺陷，这粒豆就从缺陷
统计里消失了。规则 #3 即堵此洞：存在可计面时只在可计面间裁决。

**未知类构造期拒绝**：`defect_is_countable`（schemas.py）是唯一可计判据，M7 与契约共用，
未知类别（不在 taxonomy）一律 False（schemas.py:81-91）——这是纵深防御而非放行入口：
`BeanObservation` 构造期即校验 defect 必须在 taxonomy（schemas.py:205-210，违规
ValidationError），溯因侧 `CauseItem.defect` 同（schemas.py:462-469），合法链路不可能把
未知类送进裁决。`SeverityOrder.rank` 对不在序中的类别同样拒绝（SeverityError，
adjudicate.py:123-131）。

## 2. 逐类 primary/secondary 归属与 counts_as_defect 全表（13 类）

唯一权威 = 契约附件 `configs/taxonomy.yaml`（v1.0 冻结，`classes` 节）；下表为 2026-09-30
对照该文件并与加载器实读（`load_taxonomy()` 逐类打印）核对一致的快照。
`primary_secondary_counts`（即 `GradingDecision.primary_count/secondary_count` 的口径）
按 `kind` 归属、且只计 `counts_as_defect=true` 的类：

| key | kind | counts_as_defect | 中文名 |
|---|---|---|---|
| normal | normal | false | 好豆 |
| broken | secondary | true | 破碎 |
| faded | secondary | true | 褪色/白化 |
| brocade | secondary | true | 花脸 |
| immature | secondary | true | 未熟 |
| peaberry | secondary | **false** | 花豆/胡椒粒豆 |
| shell | secondary | true | 贝壳豆 |
| elephant | secondary | true | 象豆 |
| insect | primary | true | 虫蛀 |
| dried | primary | true | 干瘪/僵豆 |
| sour | primary | true | 酸豆 |
| mold | primary | true | 霉豆 |
| black | primary | true | 黑豆 |

合计：primary **5** 类（insect/dried/sour/mold/black）+ secondary **可计 6** 类（peaberry
`counts_as_defect=false` 剔除）+ normal 1 类。
**归类/可计性变更 = taxonomy 契约变更**，必须走 CONTRACTS「版本与变更流程」并同步本表；
本表与 YAML 冲突时以 YAML 为准（表只是快照）。

## 3. severity_order（可换序的根）

- **默认序**：`configs/taxonomy.yaml` 的 `severity_order`——
  `[normal, broken, faded, brocade, immature, peaberry, shell, elephant, insect, dried, sour, mold, black]`，
  下标即 `severity_rank`（0=normal，越大越严重）。
- **标准覆盖序**：标准 YAML 的 `severity_order`（不同标准可不同）；`SeverityOrder.from_standard_yaml`
  要求**恰好覆盖 taxonomy 全部类别**（`ensure_covers_taxonomy`，缺失/未知都报错）。
- **构造即校验**：非空、无重复、`[0]` 必须是 normal（0=normal 是契约，缺陷类 rank 必须 >0，
  `BeanObservation` 构造期同样强制）。
- **按序查 rank，不做缓存**：`SeverityOrder.rank()` 每次调用现场 `keys.index()` 线性查找
  （adjudicate.py:123-131），`Taxonomy.severity_rank` 的索引 property 每次访问重算
  （taxonomy.py:146-148）——没有预计算 rank 表、没有跨调用缓存，序一换 rank 立即随新序。
  唯一的「持久」rank 是 `BeanObservation.severity_rank` 冻结存储字段（**存储，不是缓存**）：
  契约校验器 `_resolve_worst` 比较的就是该字段（schemas.py:257），而 M7 明细版按当前序现查
  （adjudicate.py:211）——两者一致的前提是存储字段与生效序一致，故换序后必须先过
  `rebase_observation` 改写（下条）。
- **换序衔接**：`rebase_observation` 把已有观测的 `severity_rank` 改写为当前序位次后，
  `PairedBean` 不变式在任意标准序下仍成立（`adjudicate_pairs` 即「rebase + 裁决 + 契约构造」
  的一条龙入口）。
- **pairing_cost 两口径强制**：`adjudicate_pairs`/`PairedBean` 校验器强制（schemas.py:290-300）——
  单面（恰一面 None）与双 None 占位记录必须**恰为 -1**；双面齐全必须 **>=0**（mm 距离），
  传 -1 或任何负值即 ValidationError。两口径之间没有中间地带。

### 3.1 基础设施 pin（2026-09-30 钉死：83 例测试未覆盖、重生成须逐条照抄的实现细节）

1. **`load_taxonomy` 缺省路径 = 包父目录/`configs/taxonomy.yaml`**：
   `DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "configs" /
   "taxonomy.yaml"`（taxonomy.py:28，即 beaneye 包父目录=仓库根）；
   `load_taxonomy(path=None)` 即用它（taxonomy.py:172-174），文件缺失抛 `TaxonomyError`。
2. **异常族一律 `ValueError` 子类**：`TaxonomyError(ValueError)`（taxonomy.py:41）、
   `SeverityError(ValueError)`（adjudicate.py:48）；契约侧 `ValidationError` 是 pydantic 的
   （本仓 venv pydantic 2.13.5 实测 MRO 含 `ValueError`）——捕获侧可统一
   `except ValueError` 兜住三类。
3. **`SeverityOrder.source` 恰三取值**（adjudicate.py:66,85,102-103）：直构缺省串 =
   **`"explicit"`**；`from_taxonomy` → `"taxonomy:<source_path>"`；`from_standard_yaml` →
   `"standard:<id>"`，标准 YAML **缺 `standard` 键回退文件名 stem**（`raw.get("standard")
   or p.stem`）。【重生成差异登记】二轮重生成件直构缺省用了 `"taxonomy:default"`、缺
   `standard` 键回退空串——与仓内实现不符且不被测试覆盖，重生成/复刻必须以本仓三值为准。
4. **`worst_detail` 单面分支明细 = 『胜出面 + tie=False』**：仅 bottom 有观测 →
   `WorstResult(top.defect, "top", rank, winner_side="top", winner_conf=top.defect_conf,
   tie=False)`；仅 top 有观测 → 对称取 bottom（adjudicate.py:187-199）。
5. **`adjudicate_pairs` 无论何种序都先 rebase 再构造**：逐对对两面各调
   `rebase_observation` 后才构造 `PairedBean`（adjudicate.py:256-267）；缺省 taxonomy 序下
   存储 rank 已与序一致，rebase 恒等（同 rank 原样返回，adjudicate.py:240-246）、
   不可观测。

## 4. 计数规则（CQI `most_severe_per_bean`，一粒只计一次）

| 函数 | 口径 |
|---|---|
| `count_defects(beans, *, include_normal=False)` | 每粒按 `final_defect` 计一次的直方；**include_normal 缺省 = False，normal 不入直方**（好豆不是缺陷）。**独立实现**，与契约 `schemas.defect_counts_from_beans`（缺省同为 False）交叉验证（tests/test_severity.py 锁定一致性，含 include_normal 两口径） |
| `effective_defect_counts(beans)` | 再剔除 `counts_as_defect=false` 的类（peaberry 不入缺陷直方） |
| `primary_secondary_counts(beans)` | 主/次分计（`GradingDecision.primary_count/secondary_count` 的口径）：按 §2 表 `kind` 归属、只计 `counts_as_defect=true`；peaberry 不计入 |

**include_normal 缺省口径（两处实现一致）**：缺省直方**不含 normal 键**——M9 引擎写进
`GradingDecision.defect_counts` 的就是这份（engine.py:117 `count_defects(beans)`）。
`BatchResult` 不变式校验时内部另取 `include_normal=True` 全直方比对（schemas.py:530-542）：
**非 normal 键双向强制**（缺键/计数不符均 ValidationError）；**normal 键可省**（2026-09-30
实测探针：3 豆含 1 normal、defect_counts 无 normal 键 → 校验通过），**写了则必校**（错数
即拒，同日探针实测）。

M9 引擎直接复用这三个函数（不再另写计数），保证「引擎计数 = 契约计数」。

## 5. 契约双侧一致性（为什么两处实现不是坏味道）

契约侧 `_resolve_worst`（schemas.py）在 `PairedBean` 校验器里**每次构造都重跑**——任何来源
（M6 配对、测试 fixture、手工构造）写入的 `final_*` 字段与两面观测不一致立即 `ValidationError`。
M7 侧 `SeverityAdjudicator.worst_detail` 提供明细版（多返回 `winner_side/winner_conf/tie`，
供展示与调试），核心规则逐位相同且共用 `defect_is_countable`。**改动任何一侧的裁决规则 =
破坏契约**，必须两侧同步 + 三道门复跑。

## 6. eval

```bash
python -m pytest tests/test_severity.py -q
# → 83 passed（2026-09-30 回炉复跑实测；2026-09-29 首测同值）
# 覆盖：表驱动 22 例（单缺陷/多缺陷/临界序/并列/单面/normal-vs-缺陷，含双 None 分支取值）、
#   自定义序翻转/rebase、标准 YAML 读取与部分覆盖拒绝、非法序/未知类拒绝、
#   count_defects vs 契约直方交叉验证（include_normal 两种口径）、
#   peaberry 吞次缺陷回归（W13）
```
