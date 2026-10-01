# OUT.md — hot-templates · ab-001 / arm-a / rep1 执行成果

- 日期：2026-09-30
- 任务：使用 hot-templates 技能生成抖音口播爆款内容骨架（platform=dy，冻结模板：3秒钩子 + 痛点 + 价值点×3 + CTA）
- 产物目录：`skillfactory/v4/assets/hot-templates/tests/ab/ab-001/arm-a/rep1/`（本目录，含 `骨架.md`、`structure.json`、本 `OUT.md`）

## 1. 输入（材料自含）

| 参数 | 值 |
|---|---|
| `--platform` | `dy` |
| `--topic` | `通勤时间管理` |
| `--points` | `["前一天晚上定好三件要事", "通勤路上只听行业播客不刷短视频", "到公司先花10分钟写当日清单"]`（恰 3 条） |
| `--outdir` | `skillfactory/v4/assets/hot-templates/tests/ab/ab-001/arm-a/rep1` |

## 2. 方法（严格按 SKILL.md）

1. 完整读取 `package/SKILL.md`（含权威规则、使用步骤、gotchas）。
2. 按 SKILL.md「文档地图」完整读取本平台必读文档 `package/references/dy.md`（全程未截断），
   以及接口常量表 `package/references/frozen-tokens.md`（占位 token / meta.beat / filled_from_input 逐字口径）。
3. 按红线第 4 条（SKILL.md:20），骨架生成走确定性渲染引擎 `package/scripts/gen.py`，
   未手写、未改写 `structure.json`；`【占位:…】` 开放槽位全部保留原样，未编造内容填充（SKILL.md:19）。

## 3. 执行命令与输出

```bash
# 卖点经 UTF-8 JSON 文件传入（内容与上表 --points 完全一致，规避 shell 内联中文转义风险）；
# gen.py 对文件路径与内联 JSON 串两种形态等价（SKILL.md:40、gen.py:52-75）
python "skillfactory/v4/assets/hot-templates/package/scripts/gen.py" \
  --platform dy --topic "通勤时间管理" \
  --points "D:/workspace/zcode研究/_tmp_ab001_arma_rep1/points.json" \
  --outdir "skillfactory/v4/assets/hot-templates/tests/ab/ab-001/arm-a/rep1"
```

stdout（一行，符合 SKILL.md:72 成功判据格式）：

```
OK platform=dy topic=通勤时间管理 elements=6 open_placeholders=6 filled_from_input=4 -> skillfactory/v4/assets/hot-templates/tests/ab/ab-001/arm-a/rep1
```

exit code = **0**。

## 4. 核验结果（本次实际执行）

### 4.1 成功判据三条（SKILL.md:72）— 全部满足

| 判据 | 结果 | 证据 |
|---|---|---|
| exit 0 | ✅ | 上节 `EXIT=0` |
| stdout 打印 OK 行 | ✅ | 上节 stdout 原文 |
| `骨架.md` 与 `structure.json` 存在且非空 | ✅ | `ls -la`：骨架.md 2123 字节、structure.json 4210 字节 |

### 4.2 确定性复跑（gen.py:13「同输入重复运行逐字节一致」）— 通过

同参数复跑至独立目录 `_tmp_ab001_arma_rep1/rerun/`，sha256 逐字节比对：

| 文件 | 首次 run sha256 | 复跑 sha256 | 一致 |
|---|---|---|---|
| 骨架.md | `528b4afb2ca06b66e5c50348c8f9d40369f3bb1ec685aedc4df7a7409c0c6aa4` | 同左 | ✅ |
| structure.json | `8df1ebaf3faa90fd5af5d104a7bd7b59624971e3130b6aae6f91403d5fffe7c7` | 同左 | ✅ |

### 4.3 结构校验（复用资产评测器 `eval/runner.py` 的检查函数，检查 1–4）— 4/4 通过

执行 `python verify_rep1.py <本目录>`（脚本 import `eval/runner.py`，以本任务输入为样例；exit 0）：

| 检查 | 结果 | detail |
|---|---|---|
| artifacts_present | ✅ | 骨架.md（927 字符）+ structure.json（3009 字符）均存在且可解析 |
| structure_json_self_consistent | ✅ | schema 与计数全部自洽（6 要素） |
| platform_template_complete | ✅ | dy 模板要素齐备（6 要素，卖点 3 条入正文/0 条截断） |
| sample_data_filled_no_template_residue | ✅ | 主题与 3 条卖点全部落位，无 `{{ }}` 残留 |

检查 5（structure_consistency_with_reference，与 oracle 参照逐项比对）**不适用、未跑**：
`oracle/out` 仅覆盖资产自带 8 个 golden case 的输入（`eval/golden.json`），与本任务自定义
topic/points 不同，逐项比对 `points_used`/`topic` 必然失配，属输入差异而非产物缺陷。

### 4.4 冻结口径核对（对照 references/frozen-tokens.md dy 表，逐项人工比对）

- 要素 id 序列：`hook_3s, pain_point, value_1..3, cta`，order 1–6 连续 ✅（frozen-tokens.md:22）
- 结构名 `3秒钩子 + 痛点 + 价值点×3 + CTA`、platform_name `抖音口播稿` ✅（frozen-tokens.md:17）
- 钩子含「别划走！还在为「通勤时间管理」反复内耗的人」、CTA 含「点赞收藏，评论区扣「1」」 ✅（SKILL.md:57）
- 4 个去重占位 token 与 dy 表逐字一致（钩子强句/痛点场景/一句话展开：怎么做效果案例/配套资料下期选题）✅
- 满 3 卖点参考值：`total_open=6`、`total_filled_from_input=4`（topic + point#1..3）✅（SKILL.md:106、frozen-tokens.md:22）
- `points_used` 长度 3 全非空、`points_unused=[]`、`points_input_count=3` ✅（dy.md:18-22）

## 5. 产物清单（本目录）

| 文件 | 说明 |
|---|---|
| `骨架.md` | 人读骨架：首行 `# 抖音口播稿 · 爆款骨架` + 元信息三行 + 6 要素各一节（含「> 写法要点：」）+ `## 占位符统计`（6 处待补写） |
| `structure.json` | 机器可读：顶层 11 键 / 每要素 9 键 / 统计 5 键，UTF-8 + LF，与 `骨架.md` 同源同构 |
| `OUT.md` | 本报告 |

## 6. 骨架全文（`骨架.md` 原样收录）

```markdown
# 抖音口播稿 · 爆款骨架

- 主题：通勤时间管理
- 平台/模板：`dy` @ v1.0（3秒钩子 + 痛点 + 价值点×3 + CTA）
- 卖点输入：3 条 → 规整为 3 条（缺失补占位 0 条，超出截断 0 条）

---

## 1. 3秒钩子（0-3s）

别划走！还在为「通勤时间管理」反复内耗的人，这条视频就是给你准备的——【占位:可替换为你的原创钩子强句，一句制造好奇或冲突】

> 写法要点：0-3秒留住人：反问+利益点，语速快、重音落在主题词

## 2. 痛点共鸣

我太懂这种痛了：【占位:痛点场景，写目标人群最扎心的一个具体瞬间】。不是你不努力，是方法从一开始就错了。

> 写法要点：说中一件事，让观众对号入座

## 3. 价值点1

第一招：前一天晚上定好三件要事。【占位:一句话展开：怎么做/效果/案例】

> 写法要点：一条卖点一句展开，信息密度拉满

## 4. 价值点2

第二招：通勤路上只听行业播客不刷短视频。【占位:一句话展开：怎么做/效果/案例】

> 写法要点：一条卖点一句展开，信息密度拉满

## 5. 价值点3

第三招：到公司先花10分钟写当日清单。【占位:一句话展开：怎么做/效果/案例】

> 写法要点：一条卖点一句展开，信息密度拉满

## 6. 行动号召（CTA）

方法就这三条，现在就去用。觉得有用就点赞收藏，评论区扣「1」，我把【占位:配套资料/下期选题】整理给你。

> 写法要点：点赞+收藏+评论三连指令，给一个扣词降低互动门槛

---

## 占位符统计

- 未填占位符（待人工/AI 补写）：**6 处**
- 已从输入填充：4 处（topic、point#1、point#2、point#3）
  - 1. 3秒钩子（0-3s）：1 处
  - 2. 痛点共鸣：1 处
  - 3. 价值点1：1 处
  - 4. 价值点2：1 处
  - 5. 价值点3：1 处
  - 6. 行动号召（CTA）：1 处

> 说明：所有 `【占位:…】` 为开放槽位，由使用者补写；`structure.json` 为机器可读的结构要素清单与占位符统计，与本文同源同构。
```

## 7. 边界说明（如实）

- 本任务交付**骨架**（结构 + 开放槽位），不做占位符内容补写、不做卖点语义改写（SKILL.md:84 边界）。
- 6 处 `【占位:…】` 为设计内开放槽位（红线，SKILL.md:85），扩写成文时由使用者按 `references/dy.md`「写法方法」补写。
- 未执行网络调用、未引入第三方依赖（gen.py 纯标准库）。
