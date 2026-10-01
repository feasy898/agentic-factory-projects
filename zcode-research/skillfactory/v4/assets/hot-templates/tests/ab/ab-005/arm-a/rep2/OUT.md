# OUT.md — hot-templates · ab-005 / arm-a / rep2 执行成果

- 日期：2026-09-30
- 任务：hot-templates 两项工程性验收——① 同输入两次生成到两个不同输出目录，逐字节比对 `骨架.md` 与 `structure.json`；② 非法 platform 与空 topic 各触发一次，观察退出码 / stderr / 输出目录是否被创建（不要求常规骨架交付目录）
- 产物目录：`skillfactory/v4/assets/hot-templates/tests/ab/ab-005/arm-a/rep2/`（本目录）
- 环境：Windows x64（windev-01），Python 3.12.10，Git Bash；执行目录=技能根 `skillfactory/v4/assets/hot-templates`（gen.py 不假设运行位置，SKILL.md:66）

## 0. 方法（严格按 SKILL.md）

1. 完整读取 `package/SKILL.md`（权威规则、输入格式、成功/失败判据、gotchas，未截断）。
2. 完整读取 `package/references/` 全部 5 份：`dy.md`（本任务平台必读）、`frozen-tokens.md`（逐字节比对口径的接口常量表，SKILL.md:61）、`xhs.md`、`wx.md`、`video.md`。
3. 按红线第 4 条（SKILL.md:20），生成一律走确定性渲染引擎 `package/scripts/gen.py`，未手写/改写任何产物；错误行为按 SKILL.md:38-39、:41、:73、:102 的口径核对。

## 1. 验收 ①：同输入两次生成 → 逐字节比对

### 1.1 输入（两次完全相同，字面一致）

| 参数 | 值 |
|---|---|
| `--platform` | `dy` |
| `--topic` | `早起时间管理`（确定性复跑主题，固定字面串） |
| `--points` | `["要点甲","要点乙","要点丙"]`（内联 JSON 串，恰 3 条） |
| `--outdir`（第 1 次） | `tests/ab/ab-005/arm-a/rep2/run1` |
| `--outdir`（第 2 次） | `tests/ab/ab-005/arm-a/rep2/run2` |

### 1.2 执行命令与原始输出（实际执行，cwd=技能根）

```bash
# 第 1 次
python package/scripts/gen.py --platform dy --topic "早起时间管理" --points '["要点甲","要点乙","要点丙"]' --outdir tests/ab/ab-005/arm-a/rep2/run1
# → stdout: OK platform=dy topic=早起时间管理 elements=6 open_placeholders=6 filled_from_input=4 -> tests/ab/ab-005/arm-a/rep2/run1   EXIT=0

# 第 2 次（仅 --outdir 不同，其余逐字相同）
python package/scripts/gen.py --platform dy --topic "早起时间管理" --points '["要点甲","要点乙","要点丙"]' --outdir tests/ab/ab-005/arm-a/rep2/run2
# → stdout: OK platform=dy topic=早起时间管理 elements=6 open_placeholders=6 filled_from_input=4 -> tests/ab/ab-005/arm-a/rep2/run2   EXIT=0
```

两次均满足成功判据三条（SKILL.md:72）：exit 0 ✅；stdout 一行 OK 行 ✅；两份产物存在且非空（见 1.3）✅。
`open_placeholders=6` 与冻结参考值一致（满 3 卖点 dy=6，SKILL.md:106、frozen-tokens.md:22）；`filled_from_input=4` = topic + point#1..3（dy.md:15）。

### 1.3 逐字节比对结果 — **PASS（全部一致）**

两目录各恰含 `骨架.md` 与 `structure.json` 两个文件（`ls -la` 实测，无多余文件）。

| 文件 | run1 大小 | run2 大小 | run1 sha256 | run2 sha256 | `cmp`（逐字节） | `diff -q` |
|---|---|---|---|---|---|---|
| `骨架.md` | 2034 B | 2034 B | `c65ac69290717fac0024173336e1d62a846454e0dac0883431a9e9530ce4e4cb` | 同左 | exit 0（无差异输出） | exit 0 |
| `structure.json` | 4032 B | 4032 B | `8d09f290eeab2f30f6cbe3a33de432fe1331770e30bd70e281f52073e88f8729` | 同左 | exit 0（无差异输出） | exit 0 |

比对命令（cwd=rep2，实际执行）：`cmp run1/骨架.md run2/骨架.md`、`cmp run1/structure.json run2/structure.json`（cmp 即逐字节比较，一致时静默 exit 0）、`sha256sum`、`stat -c "%n %s bytes"`、`diff -q`。
**结论：同输入重跑逐字节一致，符合 gen.py:13-14 的确定性声明与 SKILL.md:79「同输入重跑逐字节一致」（UTF-8/LF、固定写序，gen.py:412-416）。**

### 1.4 产物冻结口径交叉核对（对照 references 实测，非仅依赖一致性）

| 口径 | 冻结依据 | 实测 |
|---|---|---|
| 首行 `# 抖音口播稿 · 爆款骨架` | SKILL.md:78、dy.md:16 | ✅ 一致 |
| platform_name=`抖音口播稿`、structure_name=`3秒钩子 + 痛点 + 价值点×3 + CTA`、template_version=`1.0` | frozen-tokens.md:13-17 | ✅ 一致 |
| 要素 id 序列 `hook_3s, pain_point, value_1..3, cta`（6 个，order 1-6） | dy.md:7、SKILL.md:52 | ✅ 一致 |
| `points_used=['要点甲','要点乙','要点丙']`（恒长 3）、`points_input_count=3`、`points_unused=[]` | dy.md:20-22 | ✅ 一致 |
| `total_open=6`；by_element 各 1 处 | SKILL.md:106、frozen-tokens.md:22 | ✅ 一致 |
| 去重 token 恰 4 个：`可替换为你的原创钩子强句，一句制造好奇或冲突`／`痛点场景，写目标人群最扎心的一个具体瞬间`／`一句话展开：怎么做/效果/案例`（出现 3 次去重为 1）／`配套资料/下期选题` | frozen-tokens.md:22-29 | ✅ 一致 |
| `filled_slots=['topic','point#1','point#2','point#3']` | dy.md:15、frozen-tokens.md:26-29 | ✅ 一致 |
| 冻结标记：钩子含「别划走！还在为「早起时间管理」反复内耗的人」、CTA 含「点赞收藏，评论区扣「1」」、价值点以「第一/二/三招：」起 | SKILL.md:57、dy.md:11-12 | ✅ 一致 |

## 2. 验收 ②：非法输入触发

两次触发均观察三项：退出码、stderr 全文、输出目录是否被创建（`test -d` 实测）。stdout 以重定向捕获（`>…stdout 2>…stderr`），原始捕获文件保留在本目录作证据。

### 2.1 非法 platform = `bilibili` — **行为符合预期（PASS）**

命令（cwd=rep2，实际执行）：

```bash
python ../../../../../package/scripts/gen.py --platform bilibili --topic "早起时间管理" --points '["要点甲","要点乙","要点丙"]' --outdir err-platform >err-platform.stdout 2>err-platform.stderr
```

| 观察项 | 实测 | 判定 |
|---|---|---|
| 退出码 | **2** | ✅ 符合 SKILL.md:38「非法值 exit 2」、:73 失败判据 |
| stdout | 空（`err-platform.stdout` = 0 字节） | ✅ 无 OK 行 |
| stderr 全文 | 见下（`err-platform.stderr` = 207 字节） | ✅ argparse 英文报错，属预期（SKILL.md:73、gotcha SKILL.md:102） |
| 输出目录 `err-platform` | **未创建**（`test -d` exit 1） | ✅ 符合 SKILL.md:41、:73「不建目录」 |

stderr 原文（逐字）：

```
usage: gen.py [-h] --platform {dy,video,wx,xhs} --topic TOPIC --points POINTS
              --outdir OUTDIR
gen.py: error: argument --platform: invalid choice: 'bilibili' (choose from dy, video, wx, xhs)
```

细节：choices 显示顺序为 `dy, video, wx, xhs`（字典序），源于 gen.py:390 `choices=sorted(PLATFORMS)`；platform 校验发生在 argparse 解析期（早于 topic/points 校验与任何文件写入）。

### 2.2 空 topic（空白串 `"   "`，3 个空格）— **行为符合预期（PASS）**

命令（cwd=rep2，实际执行）：

```bash
python ../../../../../package/scripts/gen.py --platform dy --topic "   " --points '["要点甲","要点乙","要点丙"]' --outdir err-topic >err-topic.stdout 2>err-topic.stderr
```

| 观察项 | 实测 | 判定 |
|---|---|---|
| 退出码 | **2** | ✅ 符合 SKILL.md:39「strip 后非空，否则 exit 2」、:73 |
| stdout | 空（`err-topic.stdout` = 0 字节） | ✅ 无 OK 行 |
| stderr 全文 | `[gen.py] 错误：--topic 不能为空`（`err-topic.stderr` = 40 字节） | ✅ 引擎统一中文报错格式（gen.py:46），检查点在 gen.py:398-400 |
| 输出目录 `err-topic` | **未创建**（`test -d` exit 1） | ✅ 零产物零目录 |

细节：该次 platform 为合法 `dy`，argparse 通过后由引擎自身的 topic 校验拒绝；`err-topic.stderr` 末字节为 CRLF（`\r\n`），是 Windows 下 stderr 重定向的换行翻译，内容本身逐字如上（hex 抽查 `[ g e n . p y ]` + `错误` UTF-8 字节序一致）。

### 2.3 「不建目录」的机理佐证

`os.makedirs(args.outdir)` 位于 gen.py:409，**在全部参数校验与内容构建之后**才执行；两条失败路径（argparse 解析期、引擎校验期）均在到达该行前退出（gen.py:44-47 `fail()` 统一出口，其注释亦言明「此时未建目录/未写文件」）。本次实测与代码路径一致。

## 3. rep2 目录最终清单（实测）

| 条目 | 说明 |
|---|---|
| `OUT.md` | 本成果文件 |
| `run1/骨架.md`（2034 B）、`run1/structure.json`（4032 B） | 验收① 第 1 次生成产物 |
| `run2/骨架.md`（2034 B）、`run2/structure.json`（4032 B） | 验收① 第 2 次生成产物（与 run1 逐字节一致） |
| `err-platform.stdout`（0 B）/ `err-platform.stderr`（207 B） | 验收②-1 原始捕获（非法 platform） |
| `err-topic.stdout`（0 B）/ `err-topic.stderr`（40 B） | 验收②-2 原始捕获（空 topic） |
| `err-platform/`、`err-topic/` 目录 | **不存在**（失败不建目录的实证） |

## 4. 结论

1. **验收 ① 通过**：完全相同输入（dy / 早起时间管理 / 三要点）连续两次生成到 `run1`、`run2` 两个不同目录，`骨架.md` 与 `structure.json` 经 `cmp` 逐字节比对 + sha256 + 大小三重核验全部一致（sha256 见 §1.3），产物冻结口径与 references 全部吻合（§1.4）。确定性成立。
2. **验收 ② 通过**：非法 platform=`bilibili` → exit 2、argparse 英文 `invalid choice`（预期，SKILL.md:102）、目录未创建；空 topic=`"   "` → exit 2、stderr `[gen.py] 错误：--topic 不能为空`、目录未创建。两种失败均 stdout 无输出、零产物零目录，与 SKILL.md:41/:73 及 gen.py 实现完全一致。
