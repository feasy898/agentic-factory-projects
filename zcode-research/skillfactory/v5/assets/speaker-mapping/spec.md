# spec.md — 说话人标签映射工具（speaker-mapping）资产规格

> 资产根：`skillfactory/v5/assets/speaker-mapping/`
> 规格依据：oracle 参照实现 `oracle/map_speakers.py`（184 行，逐行读过）+ 12 次实跑产物
> `oracle/out/`（24 个文件），以及本次会话（2026-09-30）的复现实验与探针（见 §2.3）。
> 本规格逐条可判定：每条规则都给出「判定方法」，`eval/runner.py` 据此机械化判分。
> 增补条款 A-1：eval 逐字节比对的常量全文列于附录 A。

---

## 1. 目标

把「把转写稿中的说话人标签替换为人名 / 扫描转写稿生成说话人清单与草稿映射」的
oracle 行为固化为软件资产：

| 文件 | 角色 |
|---|---|
| `oracle/map_speakers.py` | 参照实现（CLI，行为在 §3 冻结，184 行） |
| `oracle/fixtures/` | 3 份转写稿 + 3 份映射 JSON（§2.1，判分输入基准） |
| `oracle/out/` | 12 次实跑的全部产物（评测参照产物，只读） |
| `spec.md` / `contract.md` | 规格（本文）与接口契约 |
| `eval/runner.py` | 确定性评测器：判「一份 map_speakers 产物集」是否合格（§5） |

工具处理的对象是 **说话人分离（diarization）产出的转写稿**；eval 的对象是
**map_speakers 的产物集**（9 个映射产物 + 9 个 stderr 存档 + 3 个 discover JSON）。

## 2. oracle 实测基线（本规格的证据）

### 2.1 fixtures（6 个文件，字节事实实测）

| 文件 | 内容 | 字节事实 |
|---|---|---|
| `normal.txt` | 3 说话人 10 条：00×4 / 01×3 / 02×3 | 938 B，10 行，LF 行尾，无 BOM |
| `partial.txt` | 4 说话人 10 条：00×3 / 03×3 / 01×2 / 02×2（03 插队，考验首次出现排序） | 774 B，10 行，LF，无 BOM |
| `empty.txt` | 无标签 7 行（含 2 条仅时间戳无标签行） | 323 B，LF，无 BOM |
| `m_full.json` | 00→王总，01→李工，02→赵秘书 | 84 B，首字节 `{\n`（无 BOM） |
| `m_partial.json` | 仅 00/01 两键 | 55 B |
| `m_empty.json` | `{}` | 3 B（`{}\n`） |

### 2.2 12 次实跑产物（`oracle/out/`，24 个文件）

- 9 个映射产物 `{normal,partial,empty}__{m_full,m_partial,m_empty}.txt`
- 9 个 stderr 警告存档同名 `.stderr.txt`
- 3 个 `discover__{normal,partial,empty}.json` + 3 个对应 `.stderr.txt`
- 12 次实跑全部 exit=0。
- （oracle 交接 notes 写「共 27 个文件」，实测 `ls -1 | wc -l` = **24**，以实测为准。）

### 2.3 本次会话复现实验与探针（2026-09-30，全部实跑）

1. **全量复现**：在临时目录按 contract.md §3 约定重跑全部 12 条命令，12/12 exit=0；
   9 个映射产物 + 3 个 discover JSON 共 **12 个主产物与 `oracle/out/` 逐字节一致**；
   12 个 stderr 存档的 **WARNING 行 12/12 一致**，唯一差异是 INFO 行里 `--out` 的
   回显路径（调用方传什么就回显什么，属调用相关，非不确定性）。
2. **幂等**：对已映射产物 `out/normal__m_full.txt` 再跑一次 m_full 映射 → 输出与
   输入逐字节一致，exit=0（中文名不匹配标签正则，故幂等）。
3. **字节恒等**：normal+m_empty、partial+m_empty、empty×3 份映射共 5 组输出与对应
   输入 fixture 逐字节一致（938/774/323 B 各自相等）。
4. **discover 与 grep 交叉核对**：`grep -c "^\[.*\] SPEAKER_XX:"` 实测 normal
   00=4/01=3/02=3、partial 00=3/03=3/01=2/02=2、empty 全 0，与 discover 统计完全一致。
5. **CRLF 探针**：CRLF 转写稿经映射后 3 处 `\r\n` 全保留，标签正常替换。
6. **全角冒号探针**：`[00:00:01] SPEAKER_00：全角冒号行。` → 替换为
   `[00:00:01] 王总：全角冒号行。`（全角冒号保留）。
7. **行首锚定探针**：`半角冒号行 [00:00:02] SPEAKER_01:ok`（时间戳不在行首）→
   **不识别**为标签，SPEAKER_01 走未映射警告分支。
8. **退出码探针**：转写稿不存在 → exit 2；映射文件不存在 → exit 2；映射非 JSON →
   **exit 1**；缺 `--mapping` 参数 → exit 2（argparse）；映射模式缺 `--out` → exit 2。
9. **已知限制实测**：`Note: this is an English line.` 被 `--discover` 计为 1 个
   标签（英文冒号行同样命中标签正则）。

## 3. oracle 行为规则（逐条可判定）

### R1 CLI 与两种模式（map_speakers.py:160-180）
`python map_speakers.py --transcript T.txt --mapping m.json --out O.txt`（映射模式）
`python map_speakers.py --discover --transcript T.txt [--out draft.json]`（扫描模式）
- `--transcript` 必填；映射模式还需 `--mapping` 与 `--out`（缺则 argparse exit 2）。
- `--discover` 缺省打印 stdout（此时 stderr 为空，无 INFO 行，实测 0 字节）；`--out` 时写文件并打 INFO。
- 判定：跑命令看退出码、stdout/stderr、产物。

### R2 标签判定（LABEL_RE 冻结，map_speakers.py:40-44）
```
^(?P<pre>\s*(?:\[[^\]]*\]\s*)?)(?P<label>[A-Za-z_][A-Za-z0-9_\-]*)(?P<sep>\s*[:：]\s*)
```
- **行首锚定**：可选先出现一个 `[...]` 方括号段（时间戳）及后随空白；正文中段的
  `SPEAKER_xx:` 不算（探针 7 实测）。
- 标签 token：ASCII 字母/下划线开头，仅含字母数字下划点横杠；中文名不匹配 → 幂等。
- 冒号：半角 `:` 或全角 `：`（探针 6 实测），sep 含其后空白。
- 判定：§2.3 探针 6/7 + fixtures 实跑。

### R3 替换不变式（映射模式，map_speakers.py:91-109）
- 只替换 `label` span 本身（:99 `body[:m.start("label")] + name + body[m.end("label"):]`）；
  pre（时间戳）、sep（冒号及空白）、正文**逐字节不动**。
- 未映射标签原样保留（:103）。
- 行数不变；行尾 `\r\n`/`\n`/无 按原文保留（`_split_eol` :49-52，探针 5 实测 CRLF）。
- 读取用 `utf-8-sig` 容忍 BOM 并保留原始行尾（:56）；写出 UTF-8。
- 判定：eval 检查 1 逐字节期望比对（附录 A.1 常量）；空映射输出 ≡ 输入（§2.3 探针 3）。

### R4 未映射标签警告（map_speakers.py:111-113）
每行 `[map_speakers.py] WARNING: 未映射说话人标签 "<label>"，出现 <N> 次，已原样保留`
打 stderr，**按 label 汇总**（一次一条，N=出现次数）。9 组期望见附录 A.2。
- 判定：eval 检查 2 解析 stderr 存档比对 (label, N) 集合。

### R5 映射键未出现警告（map_speakers.py:114-116）
映射文件中非空值键若在转写稿中未出现 → `WARNING: 映射键 "<label>" 在转写稿中未出现`。
仅 empty 转写稿触发：m_full 3 条、m_partial 2 条、m_empty 0 条（附录 A.2）。
- 判定：同 eval 检查 2。

### R6 退出码（实测口径，与 docstring 有偏差，以实测为准）
- `0` = 成功（含「有未映射标签仅警告」）。
- `2` = `--transcript`/`--mapping` 文件不存在（:78-83）、argparse 参数错误。
- `1` = 映射文件不是合法 JSON / 顶层非对象（:64-66 `raise SystemExit(str)` 语义）。
  **docstring（:26）写「2 输入/JSON 错误」，实测坏 JSON 为 1** —— 本条按实测冻结。
- 判定：§2.3 探针 8。

### R7 --discover 输出 schema（map_speakers.py:134-141，冻结）
```json
{"transcript": "<--transcript 原样回显>", "total_utterances": <int>,
 "speakers": [{"label": "...", "utterances": <int>}...], "draft_mapping": {"<label>": ""}}
```
- `speakers` 按**首次出现顺序**（partial 中 SPEAKER_03 排第 2，判分要点）。
- `draft_mapping` 每个 label 映射空字符串，可直接填名后回喂 `--mapping`
  （空字符串值视为未映射，:67/:97）。
- `transcript` 字段回显调用路径 → 字节级比对 discover JSON 要求按 contract.md §3
  约定（cwd=oracle、相对路径）产出。
- 判定：eval 检查 3（统计与结构）+ 检查 4（与参照逐字节）。

### R8 确定性与幂等
同一输入 + 同一映射重复运行（除 `--out` 路径回显进 stderr INFO / discover transcript
字段外）产物逐字节一致（§2.3 实验 1）；已映射稿重跑幂等（实验 2）。
**本工具必须确定性 —— eval 检查 4 要求与参照产物 12/12 逐字节一致，无容差。**
- 判定：eval 检查 4。

### R9 INFO 行（stderr，非判分锚点）
映射模式：`[map_speakers.py] INFO: 写出 <out>（共 N 行，替换标签 X 处，未映射标签 Y 种）`；
discover `--out` 模式：`[map_speakers.py] INFO: 发现 N 个说话人标签 / M 条发言，草稿映射已写出 <out>`。
- 判定：仅人工核对；eval 不比对 INFO（含路径回显）。

### R10 已知限制（记录，不判分）
- 英文冒号行（如 `Note: ...`）命中标签正则，会被映射/ discover 计为标签（探针 9）；
  fixtures 未含此形态。
- 标签 token 仅 ASCII；中文名标签不支持（即 R2 幂等性的来源）。
- 平台口径：win32 + Python 3.12.10 实测；标准库实现，无第三方依赖。

## 4. 边界与非目标

- 不做说话人分离本身、不做音频处理；输入约定是已含 `标签:` 行的文本转写稿。
- 不重排/不合并发言；一行至多一个标签（行首那个）。
- eval 判「产物集」，不重跑 map_speakers、不读 fixtures（期望全部固化为常量）。
- stderr 的 INFO 行含路径回显，不作为字节级判分对象；WARNING 行无路径，参与判分。
- `oracle/out/` 只读；重跑工具时产物写到别处。

## 5. eval/runner.py 判分规则（写死在工具内）

- **产物根布局**（被测与参照同构，平铺 24 文件）：9 个映射产物 + 9 个 stderr 存档 +
  3 个 discover JSON + 3 个 discover stderr（后者不判分，但属布局）。
- **CLI**：`python eval/runner.py [<被测产物根> <参照产物根>]`；零参数时两者均取内置
  缺省 `<runner 目录>/../oracle/out`（自校验应全过）；参数个数非 0/2 → 用法错误 exit 2。
- **固定 4 项检查**（全部通过 exit 0 并打印 JSON；任一失败 exit 1）：
  1. `replacement_line_by_line` — 9 个映射产物逐字节等于期望常量（附录 A.1 全文）。
  2. `unmapped_warnings` — 9 个 stderr 存档的 WARNING 集合与附录 A.2/A.3 期望一致
     （未映射标签×次数；empty 组另查「映射键未出现」；出现无法识别的 WARNING 行判败）。
  3. `discover_stats` — 3 个 discover JSON 的 speakers 清单（含首次出现顺序）、
     total_utterances、draft_mapping、transcript 字段形态正确（附录 A.3）。
  4. `reference_agreement_100pct` — 12 个主产物（9 txt + 3 json）与参照产物逐字节
     一致，要求 **12/12（100%，无容差）**；参照缺失/损坏判败。
- **输出**：stdout 打印 `{"ok": bool, "summary": {total, pass, fail, tested_root,
  reference_root}, "checks": [{name, pass, detail}]}`；无时间戳，同输入同输出。
- **退出码**：0 = 全过；1 = 任一检查失败（含空目录/产物缺失）；2 = 用法错误。

---

## 附录 A：期望常量全文（增补条款 A-1）

### A.1 9 个映射产物期望全文（eval 检查 1 的逐字节常量；UTF-8 / LF / 结尾带换行）

#### A.1.1 `normal__m_full.txt`（907 B）

```
[00:00:05] 王总: 各位下午好，现在开始本周的项目例会，先同步一下进度。
[00:00:18] 李工: 好的。本周我们完成了用户调研，回收有效问卷 412 份。
[00:00:31] 赵秘书: 我补充一下，问卷的交叉分析报告已经放到共享目录了。
[00:00:47] 王总: 很好。下一个议题是新版本的排期，还有两个模块没有联调。
[00:01:03] 李工: 支付模块这边还差对账接口，我预计周四可以提测。
[00:01:20] 赵秘书: 消息推送模块的压测结果出来了，P99 延迟 230 毫秒，达标。
[00:01:38] 王总: 那就按这个节奏推进。风险方面有什么要提前报备的吗？
[00:01:52] 李工: 有一个：第三方短信通道月底要涨价，预算需要追加 2000 元。
[00:02:07] 赵秘书: 这笔我记到下周的评审议程里了。
[00:02:15] 王总: 好，今天的会就到这里，散会。
```

#### A.1.2 `normal__m_partial.txt`（910 B；SPEAKER_02 三行原样保留）

```
[00:00:05] 王总: 各位下午好，现在开始本周的项目例会，先同步一下进度。
[00:00:18] 李工: 好的。本周我们完成了用户调研，回收有效问卷 412 份。
[00:00:31] SPEAKER_02: 我补充一下，问卷的交叉分析报告已经放到共享目录了。
[00:00:47] 王总: 很好。下一个议题是新版本的排期，还有两个模块没有联调。
[00:01:03] 李工: 支付模块这边还差对账接口，我预计周四可以提测。
[00:01:20] SPEAKER_02: 消息推送模块的压测结果出来了，P99 延迟 230 毫秒，达标。
[00:01:38] 王总: 那就按这个节奏推进。风险方面有什么要提前报备的吗？
[00:01:52] 李工: 有一个：第三方短信通道月底要涨价，预算需要追加 2000 元。
[00:02:07] SPEAKER_02: 这笔我记到下周的评审议程里了。
[00:02:15] 王总: 好，今天的会就到这里，散会。
```

#### A.1.3 `normal__m_empty.txt`（938 B ≡ `fixtures/normal.txt` 逐字节）

```
[00:00:05] SPEAKER_00: 各位下午好，现在开始本周的项目例会，先同步一下进度。
[00:00:18] SPEAKER_01: 好的。本周我们完成了用户调研，回收有效问卷 412 份。
[00:00:31] SPEAKER_02: 我补充一下，问卷的交叉分析报告已经放到共享目录了。
[00:00:47] SPEAKER_00: 很好。下一个议题是新版本的排期，还有两个模块没有联调。
[00:01:03] SPEAKER_01: 支付模块这边还差对账接口，我预计周四可以提测。
[00:01:20] SPEAKER_02: 消息推送模块的压测结果出来了，P99 延迟 230 毫秒，达标。
[00:01:38] SPEAKER_00: 那就按这个节奏推进。风险方面有什么要提前报备的吗？
[00:01:52] SPEAKER_01: 有一个：第三方短信通道月底要涨价，预算需要追加 2000 元。
[00:02:07] SPEAKER_02: 这笔我记到下周的评审议程里了。
[00:02:15] SPEAKER_00: 好，今天的会就到这里，散会。
```

#### A.1.4 `partial__m_full.txt`（752 B；SPEAKER_03 三行原样保留）

```
[00:00:04] 王总: 现在开始验收评审，请各位对照清单过一遍。
[00:00:19] SPEAKER_03: 大家好，我是新来的测试负责人，今天旁听加补位。
[00:00:33] 李工: 第一项，登录模块的回归用例 86 条全部通过。
[00:00:48] 赵秘书: 性能基线也复测了，和上周比没有回退。
[00:01:02] SPEAKER_03: 我这边发现一个低概率的空指针，已经提了缺陷单 BUG-1042。
[00:01:17] 王总: 严重级别评的什么？
[00:01:25] SPEAKER_03: P2，触发路径需要连续快速切换账号，建议下个迭代修。
[00:01:40] 李工: 同意，我排进迭代 14。
[00:01:52] 赵秘书: 那验收结论就是有条件通过，遗留一项 P2。
[00:02:03] 王总: 记录在案，散会。
```

#### A.1.5 `partial__m_partial.txt`（754 B；SPEAKER_03×3 与 SPEAKER_02×2 原样保留）

```
[00:00:04] 王总: 现在开始验收评审，请各位对照清单过一遍。
[00:00:19] SPEAKER_03: 大家好，我是新来的测试负责人，今天旁听加补位。
[00:00:33] 李工: 第一项，登录模块的回归用例 86 条全部通过。
[00:00:48] SPEAKER_02: 性能基线也复测了，和上周比没有回退。
[00:01:02] SPEAKER_03: 我这边发现一个低概率的空指针，已经提了缺陷单 BUG-1042。
[00:01:17] 王总: 严重级别评的什么？
[00:01:25] SPEAKER_03: P2，触发路径需要连续快速切换账号，建议下个迭代修。
[00:01:40] 李工: 同意，我排进迭代 14。
[00:01:52] SPEAKER_02: 那验收结论就是有条件通过，遗留一项 P2。
[00:02:03] 王总: 记录在案，散会。
```

#### A.1.6 `partial__m_empty.txt`（774 B ≡ `fixtures/partial.txt` 逐字节）

```
[00:00:04] SPEAKER_00: 现在开始验收评审，请各位对照清单过一遍。
[00:00:19] SPEAKER_03: 大家好，我是新来的测试负责人，今天旁听加补位。
[00:00:33] SPEAKER_01: 第一项，登录模块的回归用例 86 条全部通过。
[00:00:48] SPEAKER_02: 性能基线也复测了，和上周比没有回退。
[00:01:02] SPEAKER_03: 我这边发现一个低概率的空指针，已经提了缺陷单 BUG-1042。
[00:01:17] SPEAKER_00: 严重级别评的什么？
[00:01:25] SPEAKER_03: P2，触发路径需要连续快速切换账号，建议下个迭代修。
[00:01:40] SPEAKER_01: 同意，我排进迭代 14。
[00:01:52] SPEAKER_02: 那验收结论就是有条件通过，遗留一项 P2。
[00:02:03] SPEAKER_00: 记录在案，散会。
```

#### A.1.7 `empty__m_full.txt`（323 B ≡ `fixtures/empty.txt` 逐字节，0 警告输出）

```
会议纪要（口述整理稿）

本节为自由口述片段，未经过说话人分离处理。
[00:00:02] 会议在下午三点开始，地点是三号会议室。
全体与会人员先签署了保密协议，随后进入正题。
[00:01:30] 随后进入自由讨论环节，没有指定发言顺序。
记录完毕。
```

#### A.1.8 `empty__m_partial.txt`（323 B ≡ `fixtures/empty.txt` 逐字节）

同 A.1.7 全文。

#### A.1.9 `empty__m_empty.txt`（323 B ≡ `fixtures/empty.txt` 逐字节）

同 A.1.7 全文。

### A.2 期望警告表（eval 检查 2；未映射标签 → 出现次数）

| stderr 存档 | 未映射标签警告 | 映射键未出现警告 |
|---|---|---|
| normal__m_full | （无） | （无） |
| normal__m_partial | SPEAKER_02×3 | （无） |
| normal__m_empty | SPEAKER_00×4, SPEAKER_01×3, SPEAKER_02×3 | （无） |
| partial__m_full | SPEAKER_03×3 | （无） |
| partial__m_partial | SPEAKER_03×3, SPEAKER_02×2 | （无） |
| partial__m_empty | SPEAKER_00×3, SPEAKER_03×3, SPEAKER_01×2, SPEAKER_02×2 | （无） |
| empty__m_full | （无） | SPEAKER_00, SPEAKER_01, SPEAKER_02 |
| empty__m_partial | （无） | SPEAKER_00, SPEAKER_01 |
| empty__m_empty | （无） | （无） |

警告行格式（R4/R5）：`[map_speakers.py] WARNING: 未映射说话人标签 "X"，出现 N 次，已原样保留`
/ `[map_speakers.py] WARNING: 映射键 "X" 在转写稿中未出现`。

### A.3 discover 期望统计（eval 检查 3；speakers 顺序 = 首次出现顺序）

| discover JSON | total_utterances | speakers | draft_mapping |
|---|---|---|---|
| discover__normal.json | 10 | SPEAKER_00×4, SPEAKER_01×3, SPEAKER_02×3 | 3 键，值均为 "" |
| discover__partial.json | 10 | SPEAKER_00×3, **SPEAKER_03×3**, SPEAKER_01×2, SPEAKER_02×2 | 4 键，值均为 "" |
| discover__empty.json | 0 | （空数组） | （空对象） |

### A.4 参照 discover JSON 全文（eval 检查 4 的字节级参照即 `oracle/out/` 实文件；此处转录供审计。

注意 `transcript` 字段回显调用路径，按 contract.md §3 约定产出时如下）

```json
// discover__normal.json
{
  "transcript": "fixtures\\normal.txt",
  "total_utterances": 10,
  "speakers": [
    {"label": "SPEAKER_00", "utterances": 4},
    {"label": "SPEAKER_01", "utterances": 3},
    {"label": "SPEAKER_02", "utterances": 3}
  ],
  "draft_mapping": {"SPEAKER_00": "", "SPEAKER_01": "", "SPEAKER_02": ""}
}

// discover__partial.json
{
  "transcript": "fixtures\\partial.txt",
  "total_utterances": 10,
  "speakers": [
    {"label": "SPEAKER_00", "utterances": 3},
    {"label": "SPEAKER_03", "utterances": 3},
    {"label": "SPEAKER_01", "utterances": 2},
    {"label": "SPEAKER_02", "utterances": 2}
  ],
  "draft_mapping": {"SPEAKER_00": "", "SPEAKER_03": "", "SPEAKER_01": "", "SPEAKER_02": ""}
}

// discover__empty.json
{
  "transcript": "fixtures\\empty.txt",
  "total_utterances": 0,
  "speakers": [],
  "draft_mapping": {}
}
```
