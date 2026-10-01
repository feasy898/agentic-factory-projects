# SKILL.md — 中文办公 Prompt 回归黄金集（package 版）使用方法

> 本目录是 `prompt-regression` 资产的**分发形态**（package 布局）：一套可独立分发的回归底座。
> 结构契约见 `../contract.md`，行为规则见 `../spec.md`；参照实现 `../oracle/` 只读，勿改。
> 本包 25 题为按 spec 独立重建（题目与 oracle 不同，域配比与质量线相同）。

## 一、包内容

| 文件 | 说明 |
|---|---|
| `golden.json` | 黄金集：25 题中文办公任务题（六域配比 6/5/3/3/4/4），每题自含材料题干 + 5 条 check，共 125 条（regex 80 / contains 8 / semantic 37） |
| `validate.py` | 结构校验器：对任意 golden.json 执行 7 项检查（load_json / schema_top / schema_items / ids_unique / domain_coverage / instruction_quality / checks_shape），契约与 oracle 一致 |
| `out/validate.json` | 本包的自校验报告（7/7 全绿的留档；含 generated_at，属校验器报告，不参与 runner 确定性输出） |

## 二、快速自校验（改任何东西之后先跑这个）

```bash
# 工作区根执行；--out 缺省即 <本目录>/out/validate.json
python skillfactory/v3/assets/prompt-regression/package/validate.py \
    --golden skillfactory/v3/assets/prompt-regression/package/golden.json
# 期望：7 项 [PASS]，ALL GREEN ✓，退出码 0
```

## 三、接入评测体系（runner 回归，4 项检查）

```bash
python skillfactory/v3/assets/prompt-regression/eval/runner.py \
    skillfactory/v3/assets/prompt-regression/package \
    skillfactory/v3/assets/prompt-regression/oracle \
    --out <回归报告存档路径>.json
# 期望：stdout 打印 JSON，ok=true，4/4 项通过，退出码 0
```

- 被测根支持三种给法（contract §1）：本目录（package 布局）→ 直接给 `package/`；含 `package/` 的父目录 → 给父目录；**报告目录** → 给 `package/out`（仅含 validate.json 时自动单层回退到父目录，`resolved_via=report-dir-parent` 留痕）。
- runner 的 4 项检查（名称冻结）：`validate_all_green` / `domain_coverage_per_spec` / `no_duplicate_vs_reference` / `sampled_checks_decidable`。全过 exit 0，任一失败 exit 1 且仍打印完整 JSON（`ok=false`）。
- 第二个参数是**参照根**：给 `oracle/`（或其父目录、或 `oracle/out`），用于跨集查重——与参照集归一化后完全相同的题必须 ≤5。自评豁免仅当被测 golden 与参照 golden 解析为同一路径；异地逐字节拷贝不豁免（25>5 判红）。

## 四、当回归底座的三种用法

1. **改动黄金集后的门槛**：任何对 golden.json 的增删改，先过 `validate.py`（结构），再过 `runner.py`（域配比/查重/抽样可判性）。两者任一非 0 退出码即回归失败，禁止合入。
2. **重建/换代的反抄袭线**：新包与 oracle 参照集比对，`identical_vs_reference` 必须 ≤5；把每次 runner `--out` 的 JSON 报告按日期存档，作为回归证据链（报告无时间戳，同参数逐字节可复现）。
3. **抽样可判性审计**：runner 用固定种子 `20260930` 抽 3 题、逐条 check 做脚本化可判性复核，结论写入输出的 `sampled_ids` 与 `samples` 字段；抽样是启发式近似，边界 case 以 `samples` 明细人工兜底。

## 五、semantic check 怎么判

runner **不调用任何模型**（E3 确定性）：`semantic` 类 check 只校验「判据是否具体可执行」（desc ≥8 字符且 ≥3 汉字）。真正的判分交给下游回归流水线的裁判模型——把被测答案与题干、`desc` 一起交给裁判，按 desc 陈述的判据打分。`contains`/`regex` 类 check 可直接脚本判定 `value` 是否命中被测答案。

## 六、红线（spec §6）

- `oracle/` 只读；演进黄金集 = 在新产物根重新生成并过 runner，永不改 oracle。
- `eval/` 只增不删：检查项与阈值只允许新增/收紧。
- 域配比 6/5/3/3/4/4、总 25 题、id/name 正则、长度阈值均为冻结项，改动即回归失败。
