# OUT.md · ab-005 / arm-a / rep1 — 完整成果

> **任务**：hot-templates 技能 · 工程性验收两项（非常规骨架交付）：
> ① 同输入（platform=dy，topic=确定性复跑主题，points=["要点甲", "要点乙", "要点丙"]）连续生成两次到两个不同输出目录，逐字节比对 `骨架.md` 与 `structure.json`；
> ② 非法 platform（bilibili）与空 topic（空白串）各触发一次生成，观察退出码 / stderr / 输出目录是否被创建。
> **方法声明**：动手前已完整读取 `package/SKILL.md` 及 `references/` 全部 5 份（dy.md、xhs.md、wx.md、video.md、frozen-tokens.md；按 SKILL.md「文档地图」，本组平台 dy 对应 dy.md 必读 + frozen-tokens.md 为逐字节比对口径权威）。生成一律走 `scripts/gen.py`（SKILL.md 权威规则 4）。
> **执行环境**：Windows / Git Bash，`python` = Python 3.12.10（本机无 `python3` 别名，`requires-bins: python3` 以 python 3.12 满足）。
> **生成日期**：2026-09-30

---

## 一、检查① 确定性复跑 → 逐字节比对 —— **PASS**

### 1.1 执行命令与 stdout（两次连跑，仅 outdir 不同）

```bash
cd skillfactory/v4/assets/hot-templates
python package/scripts/gen.py --platform dy --topic 确定性复跑主题 --points '["要点甲", "要点乙", "要点丙"]' --outdir tests/ab/ab-005/arm-a/rep1/run1
python package/scripts/gen.py --platform dy --topic 确定性复跑主题 --points '["要点甲", "要点乙", "要点丙"]' --outdir tests/ab/ab-005/arm-a/rep1/run2
```

实际输出（两行 stdout 仅 `-> <outdir>` 段不同，其余逐字符相同）：

```
OK platform=dy topic=确定性复跑主题 elements=6 open_placeholders=6 filled_from_input=4 -> tests/ab/ab-005/arm-a/rep1/run1
run1 exit=0
OK platform=dy topic=确定性复跑主题 elements=6 open_placeholders=6 filled_from_input=4 -> tests/ab/ab-005/arm-a/rep1/run2
run2 exit=0
```

成功判据三条（SKILL.md「使用步骤 3」）全部满足：exit 0 × 2；stdout 各一行 `OK platform=… topic=… elements=… open_placeholders=… filled_from_input=… -> <outdir>`；`骨架.md` 与 `structure.json` 两份文件存在且非空（2040 B / 4038 B）。

### 1.2 逐字节比对（实测）

```bash
cmp run1/骨架.md run2/骨架.md        # 无输出，exit=0 → BYTE-IDENTICAL
cmp run1/structure.json run2/structure.json   # 无输出，exit=0 → BYTE-IDENTICAL
sha256sum run1/骨架.md run2/骨架.md run1/structure.json run2/structure.json
```

| 文件 | run1 尺寸 | run2 尺寸 | run1 sha256（前 16 位） | run2 sha256（前 16 位） | cmp |
|---|---|---|---|---|---|
| `骨架.md` | 2040 B | 2040 B | `166692ba855c77fd…` | `166692ba855c77fd…`（相同） | exit 0 |
| `structure.json` | 4038 B | 4038 B | `a331cdd8689e51a7…` | `a331cdd8689e51a7…`（相同） | exit 0 |

完整 sha256：
- `166692ba855c77fdb60636126ac8bf7f06b86bfef305a24bdb6445d08613b808` = run1/骨架.md = run2/骨架.md
- `a331cdd8689e51a7675ffbf675ec1d61e02b3215309e6f8b56841888dad588d2` = run1/structure.json = run2/structure.json

**结论：两份产物逐字节一致（cmp exit 0 + sha256 两两相同），符合 gen.py 头注与 SKILL.md「同输入重跑逐字节一致」的确定性声明。**

### 1.3 产物规格核验（补充，按 SKILL.md「产物与验收」+ frozen-tokens.md 口径）

- `骨架.md`：首行 `# 抖音口播稿 · 爆款骨架`；元信息三行（主题/平台模板/卖点输入 `3 条 → 规整为 3 条（缺失补占位 0 条，超出截断 0 条）`）；每要素一节 `## <序号>. <名称>` 含 `> 写法要点：`；尾部 `## 占位符统计` 节。
- `structure.json`：顶层 **11 键**齐备（template_version/platform/platform_name/structure_name/topic/points_input_count/points_used/points_unused/element_count/elements/placeholder_stats）；每要素 **9 键**齐备；`element_count=6`；`points_used=['要点甲','要点乙','要点丙']`（3 条全填，`points_unused=[]`，`points_input_count=3`）；`platform_name=抖音口播稿`、`structure_name=3秒钩子 + 痛点 + 价值点×3 + CTA`、`template_version=1.0`。
- 编码：两文件均 **UTF-8 无 BOM、纯 LF、文件尾一个换行**（二进制探针实测：BOM=False、CRLF=False、ends_with_LF=True）。
- 统计对账：`total_open=6`（dy 满 3 卖点参考值，SKILL.md gotchas）✓；`total_filled_from_input=4`（hook_3s 记 topic + value_1..3 各记 point#i）✓；要素 id 序 `hook_3s, pain_point, value_1, value_2, value_3, cta` ✓。
- 冻结标记在文：钩子含「别划走！还在为「确定性复跑主题」反复内耗的人」✓；CTA 含「点赞收藏，评论区扣「1」」✓（frozen-tokens.md dy 表）。
- 红线：`{{ }}` 未填充模板变量残留 = 0 ✓（`【占位:…】` 开放槽位为设计内存在，共 6 处，未做任何编造填充）。

## 二、检查② 非法输入拒止 —— **PASS（两项均按预期失败）**

### 2.1 NEG-A：非法 platform=bilibili

```bash
python package/scripts/gen.py --platform bilibili --topic 确定性复跑主题 --points '["要点甲", "要点乙", "要点丙"]' --outdir tests/ab/ab-005/arm-a/rep1/neg-bilibili
```

| 观察项 | 实测 |
|---|---|
| 退出码 | **2** |
| stdout | 空（无任何输出） |
| stderr | argparse 英文报错（原文见下，已留存 `neg-bilibili.stderr`） |
| 输出目录 | 运行前不存在，运行后**仍未创建**（`[ -e … ]` → NO） |

stderr 原文：

```
usage: gen.py [-h] --platform {dy,video,wx,xhs} --topic TOPIC --points POINTS
              --outdir OUTDIR
gen.py: error: argument --platform: invalid choice: 'bilibili' (choose from dy, video, wx, xhs)
```

与 SKILL.md 输入格式表「非法值 exit 2」、失败判据「非法 platform 时为 argparse 英文报错，属预期」及 gotchas 第 3 条完全一致（gen.py:390 `choices=sorted(PLATFORMS)`）。

### 2.2 NEG-B：空 topic（空白串 `"   "`）

```bash
python package/scripts/gen.py --platform dy --topic "   " --points '["要点甲", "要点乙", "要点丙"]' --outdir tests/ab/ab-005/arm-a/rep1/neg-empty-topic
```

| 观察项 | 实测 |
|---|---|
| 退出码 | **2** |
| stdout | 空（无任何输出） |
| stderr | `[gen.py] 错误：--topic 不能为空`（中文统一失败出口，原文已留存 `neg-empty-topic.stderr`） |
| 输出目录 | 运行前不存在，运行后**仍未创建**（`[ -e … ]` → NO） |

与 SKILL.md「`--topic` strip 后非空；否则 exit 2」及失败判据「stderr 有 `[gen.py] 错误：…`，且输出目录未被创建」完全一致（gen.py:398-400 → fail() → gen.py:44-47）。

### 2.3 说明

SKILL.md 步骤 4 的「按报错修参数后定向重试一次」适用于真实使用场景；本检查目的是观察拒止行为本身，两项失败均属**预期行为**，无需修复重试。佐证（代码层）：gen.py 的 `os.makedirs` 位于全部校验之后（gen.py:409），故任一校验失败路径零目录、零文件——与上面两次实测一致。

## 三、补充验证（非 ask 指定检查，如实标注）

- `python eval/runner.py package/out oracle/out` → **exit 0**，8 case × 5 检查 **40/40 全过**，结构一致率全部 100%（阈值 90%）。注：这是**资产自带样例**的出厂验收（golden.json case 布局），证明所用引擎包自洽达标；本组 run1/run2 的输入不在该 case 布局内，故 eval 不适用于这两个目录，检查①②的判据以本文第一、二节实测为准。

## 四、产物清单（本目录）

| 文件/目录 | 说明 |
|---|---|
| `run1/骨架.md`（2040 B）、`run1/structure.json`（4038 B） | 第 1 次生成产物 |
| `run2/骨架.md`（2040 B）、`run2/structure.json`（4038 B） | 第 2 次生成产物（与 run1 逐字节一致） |
| `neg-bilibili.stderr` | NEG-A stderr 原文留存 |
| `neg-empty-topic.stderr` | NEG-B stderr 原文留存 |
| `neg-bilibili/`、`neg-empty-topic/` | **不存在**——这正是检查②的验证点 |
| `OUT.md` | 本文件 |

## 五、结论

| # | 检查 | 判据 | 结果 |
|---|---|---|---|
| ① | 同输入两次生成逐字节一致 | cmp 两文件 exit 0；sha256 两两相同 | **PASS** |
| ②a | 非法 platform=bilibili 拒止 | exit 2 + argparse 英文 stderr + 目录未创建 | **PASS** |
| ②b | 空 topic（空白串）拒止 | exit 2 + `[gen.py] 错误：--topic 不能为空` + 目录未创建 | **PASS** |

---
*ab-005 / arm-a / rep1 · 按 SKILL.md + references 方法执行 · 所有命令与输出均为 2026-09-30 本会话实测*
