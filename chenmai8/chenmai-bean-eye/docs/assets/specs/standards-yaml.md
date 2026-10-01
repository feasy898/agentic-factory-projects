# M9 标准引擎 spec（standards · 标准 YAML schema）

> 状态：冻结（57 用例全绿，2026-09-29 实测）。结构冻结；**三套 YAML 的阈值全部是
> `verified:false` 占位基线**（D1 原文核对未完成），核对后回填数值并置 true——那时
> passed 阻断自动解除。换标准 = 换 YAML，不改代码。
> 本页对照 `beaneye/standards/loader.py` / `engine.py` 与三份 YAML 逐行核验于 2026-09-29。

---

## 1. 文件与加载

- 目录：`configs/standards/<standard_id>.yaml`；`load_standard(id)` 按 id 或路径加载；
  **`standard` 键必须与文件名 stem 一致**；未知 id 报错并列出可用项。
- sha256 = **文件字节**的 sha256（小写 hex64）→ `GradingDecision.standard_yaml_sha`
  （判定与配置版本绑定的根）。
- 解析器 `_LineLoader`（SafeLoader 子类）：**重复键直接报错**（PyYAML 默认静默后者覆盖前者，
  对标准配置是隐患）+ 逐键行号（`LMap.line_of`）。实测坑：PyYAML 顶层映射走
  `construct_yaml_map`（注册表存函数对象），子类必须**重新 add_constructor("tag:yaml.org,2002:map")**
  才能让顶层映射也带行号——否则语义错误丢失行号。
- 错误契约：解析错误由 PyYAML mark 携带路径行号；语义错误 = `路径:行号: 问题`。

## 2. YAML schema（顶层键固定，未知键=拼写隐患即报错）

```yaml
standard: cqi_fine_robusta          # 必填；与文件 stem 一致
display: {zh: …, en: …, vi: …}      # 必填；恰三语键，非空字符串
sample_g: 350                       # 必填；正数（抽样基量 g；v0 不做粒数换算，见 §4）
count_rule: most_severe_per_bean    # 必填；most_severe_per_bean | per_side（后者可加载、evaluate 报错）
severity_order: [normal, …, black]  # 必填；taxonomy 全排列且 [0]=normal（复用 M7 校验）
defect_classes:                     # 必填；类别集合与 kind 与 taxonomy 完全一致（展示副本）
  black: {kind: primary, zh: 黑豆, en: black, vi: hat den}   # 恰 kind/zh/en/vi 四键
grades:                             # 必填；非空；**从最优到最差单调放宽**
  - name: Fine                      #   唯一（重名报错）
    primary_max: 0                  #   >=0 整数
    secondary_full_max: 5           #   >=0 整数
    sieve_min: null                 #   >=1 整数或 null（null=不设筛目条件）
    verified: false                 #   布尔（false→warnings + passed 阻断）
fail_grade: 未达 Fine               # 可选；默认"未达级"；不得与任何 grade 重名
notes: [...]                        # 可选；字符串列表
metrology:                          # 必填
  sieve_targets:
    min_screen: 13                  #   必填；>=1 整数
    verified: false                 #   可选布尔（默认 false）
  reference_lab: [55, -12, 22]      #   必填；3 个数字（loader 按 CIE 标度解析，可配 reference_lab_scale）
  reference_lab_verified: false     #   可选布尔
  delta_e_max: null                 #   必填；>=0 数字或 null（null=不判色差；作用于所有级别）
weight:                             # 必填
  model: area_linear                #   必填；area_linear | area_thickness（M8 两模型）
  g_per_mm2: 0.00042                #   必填；正数
  verified: false                   #   可选布尔
```

**单调放宽校验**（grades[i] 对 grades[i-1]）：`primary_max` 非递减、`secondary_full_max` 非递减、
`sieve_min` 非递增且 **null 只能出现在尾部**（上一级 null 后不得再设数值）。
已知瑕疵（如实记录）：YAML 的 `metrology.reference_lab` 行内注释写「0-255 标度」，loader 实际
按 CIE 解析（`[55,-12,22]` 的 a/b 负值只能是 CIE），以 loader 为准，注释待清理。

## 3. verified:false → warnings（稳定键路径）

```
verified:false @ grades[<i>](name=<name>)
verified:false @ metrology.sieve_targets(min_screen)
verified:false @ metrology.reference_lab
verified:false @ weight
```

按上述键路径收集进 `Standard.warnings` → 原样进 `GradingDecision.warnings`（契约 v1.1 增补字段）
→ M10 页脚「标准阈值核对中」角标。**三套 YAML 当前全部非空**（各 4–7 条）。

## 4. 定级流程（`StandardEngineV1.evaluate(beans, measurements)`）

1. `count_rule != most_severe_per_bean` → 报错（per_side 与契约 `BatchResult.defect_counts`
   不变式冲突，加载可过、evaluate 明确拒绝——已上报规划方）。
2. 计数复用 M7：`count_defects`（每粒只计 final_defect 一次）+ `primary_secondary_counts`。
3. 逐 grade 判定（从最优到最差，取**第一个**满足全部条件者）：
   `primary ≤ primary_max` 且 `secondary ≤ secondary_full_max` 且
   筛目（`sieve_min` 非 null 时 sieve_hist 中 `screen < sieve_min` 的粒数须为 **0**，v0 语义）
   且 色差（`delta_e_max` 非 null 时 `delta_e_mean ≤ delta_e_max`，全局条件作用于所有级别）。
4. reasons = i18n 模板键 + 数值：`"<模板键>:<k>=<v>[;<k>=<v>]*"`，键集 `[A-Za-z0-9_.]`
   （如 `grading.reason.primary_over_limit:count=1;limit=0`），M10 按 lang 查表渲染；
   未登记键原样显示。条件理由统一相对**选定级**输出（全部未达时相对最严的第一级）。
5. 全部未达 → `grade = fail_grade`、`passed=False`、追加 `grading.reason.no_grade_matched`。
6. **passed 阻断（W13）**：`warnings` 非空时即使阈值全满足 `passed=False`，grade 仍记实际
   达到的级别名（层级信息不丢），追加 `grading.reason.pass_blocked_unverified:warnings=N`
   ——阈值未经原文核对不得对外宣布「通过」。
7. **口径注明（W13）**：每份判定追加 `grading.reason.tray_count_vs_sample_g:sample_g=350;bean_count=N`
   ——计数条件按本盘粒数对比全样上限，**不是 350g 基量的符合性结论**，防止误读。

## 5. 三套标准现状

| id | display.zh | sample_g | grades（占位阈值） | 特有点 |
|---|---|---|---|---|
| `cqi_fine_robusta` | CQI 精品罗布斯塔 | 350 | Fine（0 主 + ≤5 次，无筛目） | §3.3 给定基线；fail_grade=未达 Fine |
| `nyt_604` | NY/T 604 生咖啡 | 300 | 一级（0/8/筛15）二级（2/16/筛14）三级（5/30/筛13） | 2020 版（2021-04-01 实施）；等级表未取得，命名与阈值全占位 |
| `db46_t642` | DB46/T 642 罗布斯塔生咖啡 | 300 | 特级（0/4/筛14）一级（1/8/筛13）合格（3/18/null） | 唯一启用全局色差 `delta_e_max: 10.0`（ΔE76 口径同 M8） |

三套 severity_order 当前与 taxonomy 默认序相同；换序只改 YAML（加载期校验全排列）。

## 6. eval（2026-09-29 实测）

```bash
python -m pytest tests/test_standards.py -q
# → 57 passed
# 覆盖：表驱动 26 例瑕疵组合→各级别判定（CQI 0主5次过/0主6次不过/1主不过/peaberry 不计；
#   NY/T 阈值边界+筛目降级链+全低等外；DB46 ΔE10.0 恰好达标/越限压全级）；
#   引擎横切：三 YAML 全载 + sha256=文件字节 + warnings 精确清单传递 + reasons 正则 +
#   BatchResult 不变式嵌入 + 确定性 + 8 类错误路径（未知id/解析/语义精确行号/重复键/
#   空grades/重名/非单调/越界）+ per_side 拒绝
```
