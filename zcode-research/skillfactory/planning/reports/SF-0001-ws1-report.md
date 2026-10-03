# SF-0001 · WS1 eval harness MVP 交付报告（管线验证信号）

> **本报告产出物按 PLAN §5.4 三条纪律固定命名为「管线验证信号」，不是验收结论。**
> n=1、单任务、单族、单重复——EVAL-SPEC §3.1-1/§3.2-1 明令禁止在此规模下出具验收结论。
> 报告中任何数字都**不得**被引用为资产增益证据。
>
> - 任务：SF-0001（`projects/skillfactory/tasks/`，family:any / P0）
> - 权威规格：`planning/PLAN.md` v1.1 §7 WS1（行 425）、§5.2/§5.3/§5.4、§8 O-17
> - 验收判据：`planning/TESTS.md` v1.1 §1.10 EI 组 + 负控组（AR 组属 WS7，不在本卡范围）
> - 执行：worker-minimax-r7（minimax 族），2026-10-03 19:51–20:15
> - 落盘位置：`D:\new-workspace\agent-asset\evalkit\`（**不进 afp-clone**，按 §8 O-17 两段式）

---

## 0. 一句话结论

管道建成了，四个 abort 判据逐条过，负控 8 条全红、正常臂不误报；
**但本轮最重要的产出不是「管道通了」，而是一条被跑出来的资产侧缺陷 + 一条被跑出来的装置侧缺陷**：
资产侧 = `SKILL.md` 的 INFO 行文档与工具实际输出不一致；装置侧 = 任务包的输入目录名与
参照基线不一致，导致产物轨检查 4（逐字节参照比对）对**两个臂同时判红**——
这是尺子坏了，不是模型不行（PLAN §3.6 头号判例同构）。

---

## 1. 交付物清单（对照 WS1 验收列逐项）

| WS1 要求 | 落点 | 状态 |
|---|---|---|
| `packs/sm-mapping-01` | `evalkit/packs/sm-mapping-01/`（brief / inputs / rubric / checks / out / transcript / records 六件齐） | ✅ |
| 三轨 evaluator | `evalkit/evaluators/{artifact,process,quality}_track.py` | ✅ |
| `matrix.json` | `evalkit/runs/r1-probe/matrix.json`（schema 齐 + 写-读往返过） | ✅ |
| 负控 8 条 | `evalkit/nc/run_nc.py` + `evalkit/runs/nc-20261003T200416/nc_report.json` | ✅ 9/9 |
| 「管线验证信号」报告 | 本文件 | ✅ |
| 附带（非要求但 WS4/WS5 直接要用） | `harness/`（oracle_gate / isolation_probe / pack_checks / make_arms / run_arm / freeze_device / run_all）、`evaluators/classify.py` | ✅ |

---

## 2. §5.4 四步逐步证据

### 步 0（0 模型）——绿路 / 红路 / oracle 哈希基线

| 判据 | 命令 | 实测 |
|---|---|---|
| 绿路 exit 0 | `python packs/sm-mapping-01/checks/run_check.py` | **exit 0**，4/4 检查 PASS |
| 空目录红路 exit 1 | `python packs/sm-mapping-01/checks/run_check.py <空目录> <参照>` | **exit 1**，4/4 检查 FAIL |
| oracle 树哈希存基线 | `python harness/oracle_gate.py hash --root <资产>/oracle` | 31 文件，`tree_sha256=e3086e10c9cd4f1415792333b89479536a2a96624b543215d5f6465525ceeacc` |
| 易变面三跑标定 | `... calibrate --runs 3` | `volatile=[]`，`stable=true`，冻结面 31/31 |

行尾基准显式写进哈希产物本身：`text LF-normalized (CRLF->LF) + sha256; binary raw bytes + sha256`（EI-4）。
换机时能判「基准漂移」而不是「资产变了」。

### 步 1（0 模型）——隔离实测 + R-1 装载路径分支（**本卡最关键的一条必答项**）

**R-1 结论：走「真实产品装载路径」分支成立，降级分支（prompt 注入）不适用。**

PLAN §5.2 / §9.1 R-1 预置了两条分支：headless 下若无可用装载开关 → 只能 prompt 级注入，
且 Δ 必须标注为「文档增益下限（provisional）」。实测否定了这个悲观前提：

- zcode 客户端的 skill 发现序第 4 级是 **Workspace `.zcode/skills`（从 `--cwd` 所在目录向上解析）**
  （依据：`zcode-guide:diagnosing-skills` §1，本机自带文档）；
- 因此 treatment 臂只需把资产挂到 `<臂目录>/.zcode/skills/speaker-mapping/`，
  `zcode -p --cwd <臂目录>` 就会**原生发现并装载**该 skill，无需任何 CLI 开关、无需改全局配置。

双侧机器可判定证据（`zcode -p "/skill" --json` 输出，两臂各跑一次）：

| 臂 | cwd | 技能数 | speaker-mapping |
|---|---|---|---|
| baseline | `…/runs/r1-probe/baseline` | 16 | **无** |
| treatment | `…/runs/r1-probe/treatment` | 17 | **有**（`scope=project`, `source=zcode`, 路径=臂内 `.zcode/skills/speaker-mapping/SKILL.md`） |

→ 两臂零交叉污染，**Δ 是产品装载路径的 Δ，不是文档注入下限**。R-1 从「高风险未决」降为「已解」。

隔离实测（EI-6）：

- baseline 树 walk `SKILL.md / oracle/ / eval/ / holdout/` → **零命中**（exit 0）；
- treatment 树同探针 → 命中 2（SKILL.md、map_speakers.py）——**这是探针的阳性对照**，
  证明该门不是恒真门（MT-2 阳性对照纪律），treatment 命中是设计内的。

建臂时发现并堵掉一个**真实泄漏**：资产 `package/` 目录里带着上一轮跑批遗留的
`out/`（24 个基准产物）。首版挂载把它一起递进了 treatment 臂——那等于把答案和参照物
同时交到被测手上，产物轨会全绿而增益是假的。`make_arms.py` 已加默认排除
（`out` / `eval` / `oracle` / `blind` / `.mimosa`），复跑后 treatment 树只剩
`SKILL.md` + `map_speakers.py` + `README.md`。

前置三断言（EI-7 / EI-9 / EI-20）见 `runs/r1-probe/preflight.json`：brief 逐字相同、
两臂输入树掩掉臂目录名后逐字节相同、资产名/暗示句式扫描零命中、包内无 `oracle/`。

### 步 2（4 臂）——实跑结果

| 臂 | 模型实测落点 | 产物 | 过程轨 | 产物轨 | 质量轨 | tokens | 墙钟 | infra |
|---|---|---|---|---|---|---|---|---|
| glm\|baseline\|r1 | `GLM-5.3` | 24/24 文件 | PASS | **FAIL** | unjudgeable | 719,397 | 5.8 min | false |
| glm\|treatment\|r1 | `GLM-5.3` | 24/24 文件 | PASS | **FAIL** | unjudgeable | 559,233 | 6.7 min | false |

`session.directory == 臂目录` 两侧均 `true`，`model_usage` 可 join（EI-0 第 0 号门绿）。

**矩阵只有一列，不是四臂——原因见 §4.1（O-6 实测落点 + headless 无模型目录）。**

### 步 3（0 模型）——三轨 + 看板 + 哈希终检

- 产物轨：两臂均 4 检查中 **3 PASS / 1 FAIL**（失败项恒为 `reference_agreement_100pct`）；
- 过程轨：两臂四断言**全绿**（命令面 / 退出码面 / 引引面 / 禁止面），`tool_usage` 分别 22 / 12 行；
- 质量轨：两臂 `unjudgeable`（见 §4.2，**不出分**）；
- `matrix.json`：必填键齐 + 写-读往返过（EI-21/AG-15），`delta_vs_prev=null`（首轮无 A_old，AG-4）；
- **oracle 哈希终检：`unchanged=true`，参照区跑批前后逐字节一致**（PLAN §3.3 硬不变量 2 过）。

---

## 3. 负控：管道正确 = 负控全红 + 正常臂不误报

`python nc/run_nc.py` → **9/9 成立**（8 条负控 + 1 条阴性对照）。

| id | 植入 | 判定 | 抓它的断言 |
|---|---|---|---|
| NC-1 | 在 oracle 副本下原地跑生成器（复刻 K-3 D3 真事故） | 红 ✅ | oracle 哈希门（树哈希变化 + changed_paths 非空） |
| NC-2 | `--store` 指向 `oracle/out/_work/store.json` 后加词（复刻 D4） | 红 ✅ | 禁止面（oracle + 写动作共现） |
| NC-3 | 用绝对路径 `--out` 产出（复刻 D2） | 红 ✅ | 检查 4 判败（路径回显差异未被静默放过） |
| NC-4 | 漏/错 CLI 参数（输入不存在，复刻 D1） | 红 ✅ | 退出码面（exit 2，落在 expect∈{0,2}） |
| NC-5 | 注入一次 rate_limited 后成功 | ✅ | 分类器落「重试后成功」，**未**标 infra |
| NC-6 | 注入连续 2 次 stream_idle_timeout | ✅ | **该臂作废**（不是该 run 剔除，粒度独立断言） |
| NC-7 | 3 族全绿 + 1 族全崩 | ✅ | 3 族出结论 + 1 族 unjudgeable，**无「整轮无效」** |
| NC-8 | 人为把某臂产物做坏 | ✅ | 落**被测失败**桶（防「一切都是 infra」） |
| NC-CTRL | 无植入（绿路自校验） | 不误报 ✅ | 判分器 exit 0、4/4 PASS |

**破坏性实验的纪律**：NC-1 的原地重跑只在 oracle 的**独立副本**上做，harness 自己不碰真参照区。
跑完 NC 全组后复核真参照区：`unchanged=true`（31 文件，哈希与基线一致）。
理由：K-3 彩排 D3 已经真清空过一次参照区——harness 自己不能再犯一次。

---

## 4. 本轮跑出来的缺陷（本卡的真正产出）

### 4.1 【装置/通道·高】模型钉版落空：headless 只能跑通一族，O-6 落点与文档声称不符

- 事实：zcode headless `-p` **无 `--model` 选项**；`/model` 是客户端选择器、不经模型处理；
  实测两臂 `model_usage.model_id` 均为 **`GLM-5.3`**，
  当前账户 `account:bigmodel-individual-coding-plan/GLM-5.3`。
- 与规格的偏差：O-6 的建议默认是「保持钉 **GLM-5.3-Flash**；若只能 GLM-5.3 则 bump evalbench 版本、旧基线作废」。
  实测落到 GLM-5.3 → **触发该条款**。本轮已按「管线验证信号」口径处理（不出 Δ），但版本与基线作废的
  正式动作留给 planner 裁定。
- 后果：MVP 计划的「2 族」矩阵退化为 **1 族**。MiniMax 通道在本拓扑下不可达：
  桌面/CLI 是两套 provider 配置体系，v2 minimax provider 不在 headless 读取的配置里；
  工作流钉版又依赖「有模型目录的宿主会话」（本类会话即 `model_catalog_unavailable`）。
- **这是「怎么做」的技术决断（L1/L2，非 L3），不升级 owner**，交 planner 转后续任务卡。
  建议方向二选一：(a) 为 headless 跑批单独钉一份 provider 配置并写进 evalkit 文档；
  (b) 接受 MVP 阶段单族，把跨族比较整体推到 WS5 前用工作流拓扑做（R-2 专项实测）。

### 4.2 【装置·中】任务包输入目录名与参照基线不一致 → 产物轨检查 4 对两臂同时判红

现象：两臂产物轨都是 3 PASS / 1 FAIL，失败项恒为 `reference_agreement_100pct`。

根因（本卡亲手复现的完整链条）：

1. **9 个映射产物 `.txt` 在两臂都与参照逐字节相同（9/9）**——模型行为完全正确；
2. 差异只在**两处路径回显**：
   - `discover__normal.json` 的 `transcript` 字段：臂产出 `../inputs/normal.txt`，
     参照基线是 `fixtures\normal.txt`；
   - stderr 的 INFO 行：臂产出 `INFO: 写出 normal__m_full.txt（共 10 行，替换 10 处，未映射 0 种）`，
     参照基线是 `INFO: 写出 out\normal__m_full.txt（共 10 行，替换标签 10 处，未映射标签 0 种）`；
3. 臂之所以产出这两种回显，是因为**任务包把黄金输入放在 `inputs/`**，
   而参照基线是在 `oracle/` 下以 `--transcript fixtures/normal.txt` 生成的；
   contract.md §3 要求「在 `oracle/` 目录为 cwd、用相对路径运行」——臂树里没有 `fixtures/` 这一层。

判定：**这是题面/装置缺陷，不是模型失败，也不是资产失败。**
依据 PLAN §3.1 的分层语义：L1 层逐字节比对的前提是「被测与参照同形态」；
本任务包不满足该前提，属「因实现路径不同扣分」，正是 §3.1 明令在 L2/L3 禁止、在 L1 才成立的判据。
参照物：本仓 `v5/eval-round-20261001/scorecard.md` 一轮 3 个 FAIL **3/3 全部诊断为 bench 侧问题**。

两种修法（供 planner 选，本卡未擅自改题面）：

- **修法 A（推荐，零改资产）**：任务包把黄金输入目录由 `inputs/` 改名为 `fixtures/`，
  并在 brief 里要求**以臂根为 cwd、`--out "out/…"`、`--transcript "fixtures/…"`** 运行。
  届时两处回显与基线逐字节一致，检查 4 可真实通过。改动只在 `packs/` 内，资产树零改动。
- **修法 B**：在任务包薄封套里对回显做对称归一（沿用 contract v1.1 A-2 条款已有的
  「`\\`→`/` 对称归一」先例，扩展到目录名）。判分逻辑仍在资产树，装置侧只做归一，钉版可查。

按 PLAN §3.6，**本轮两臂的数字不得用于任何引用**（题面缺陷率 2/2 = 100% > 10% 门限，
分子分母都取自本卡 2 个臂，均为本卡自产、非全量轮次统计，仅作本卡定性判断用）。

### 4.3 【资产·中】`SKILL.md` 的 INFO 行文档与工具实际输出不一致（D5 类缺陷）

- `package/SKILL.md:54` 写：`INFO: 写出 …（共 N 行，替换 X 处，未映射 Y 种）`
- 工具实际输出：`INFO: 写出 out/<file>（共 10 行，替换标签 10 处，未映射标签 0 种）`

即 SKILL.md 漏了「标签」二字，且未体现 `--out` 路径回显。两臂的 stderr 都照 SKILL.md 的写法走了
（baseline 是被我写进 brief 的同一句带偏的，treatment 是读了 SKILL.md）——
**文档错一字，两条独立路径同时踩中**，属可判定缺陷而非口味问题。

处置建议：修 `package/SKILL.md:54` 的 INFO 行示例（属资产内容修复，**不在 WS1 授权范围**，
WS1 只跑不改资产——PLAN §5.4 三条纪律「不改任何既有文件」），
建议 planner 开卡进 backlog，或并入 WS2（build.py + 文档一致性同批处理）。

### 4.4 【装置·低】三处实现级事故与坑（已在本装置内修掉，记账备查）

1. `zcode` 在 Git Bash 里是 npm 的 **sh shim**，Windows CreateProcess 不能直接 exec
   （实测 `WinError 2`）；`run_arm.py` 改为 `.cmd` shim → `node + zcode.js` 两级解析。
2. Git Bash 的 MSYS 路径转换会把 `/skill` 改写成 `C:/Program Files/Git/skill`
   （PLAN R-7 同族坑，本卡再次实测命中）；一切 spawn 子进程的脚本透传 `MSYS_NO_PATHCONV=1`。
3. `checks/run_check.py` 首版把 evalkit 根算错一层，导致找不到原版 runner；
   修正后并改为**相对 evalkit 的平级定位**（evalkit 与 afp-clone 平级），整目录搬迁后不改代码。

### 4.5 隔离探针是**跑批前**门：跑批后误报属设计内，别当泄漏（已实测确认）

跑完两臂后再跑 `isolation_probe.py <baseline 树>` 会 **exit 1**（命中 `map_speakers.py`），
**这是误报，不是泄漏**，已用内容比对排除：

| 文件 | sha256（前 16） | 行/字节 |
|---|---|---|
| baseline 臂自写脚本 | `4436735be4e6a087` | 227 行 / 7348 B |
| treatment 臂脚本 | `13bcedcda2b1e8aa` | — |
| 资产 `package/map_speakers.py` | `f6c7974996a6dbfc` | 209 行 / 8769 B |
| 资产 `oracle/map_speakers.py` | `b2ad9a6a79107039` | — |

三者互不相同 → baseline 臂是**自己写的**脚本（brief 明确要求自写），
且 baseline 树内 `SKILL.md` / `contract.md` / `spec.md` **零命中** → 隔离成立。

原因：探针按 EI-6 的定义是**跑批前置**门（PLAN §5.4 步 1）；跑批后臂按设计会在自己树里生成
scratch 脚本（§3.3「臂要跑生成器必须先复制到自己的 scratch 副本」），必然命中黑名单。

**用法纪律**：探针只在建臂后、开跑前跑；跑批后的完整性检查用**内容比对**
（臂内文件 sha256 vs 资产树 sha256），不要用文件存在性探针。

### 4.6 一条被装置自己抓到的漂移（证据：钉版门不是橡皮图章）

在首轮 freeze 之后新增了 `harness/run_all.py`，`freeze_device.py verify` 随即判红
（`new_file harness/run_all.py`），重新 freeze 后 14 个关键文件 sha256 全对。
这正是 EI-23 门存在的意义：改判分器/阈值凑绿必须先被自己抓到。

---

## 5. 自测结果（逐条对 WS1 验收门）

| 验收门（PLAN §7 WS1 验收列 / TESTS M1 门） | 结果 | 证据 |
|---|---|---|
| §5.4 四步全过 | ✅ | §2 逐步命令与输出 |
| oracle 哈希前后一致 | ✅ | `unchanged=true`，31 文件 |
| R-1 装载路径分支已定并写入报告 | ✅ | §2 步 1，双侧 `/skill` 机器可判定 diff |
| NC-1..NC-8 全红 | ✅ | 9/9（§3） |
| 正常臂不误报 | ✅ | NC-CTRL 绿路 4/4 PASS 不误报；两臂过程轨无假红 |
| EI-0 第 0 号门 | ✅ | session.directory==臂目录 + model_usage 可 join |
| runner 零改动 | ✅ | 判分逻辑只在资产树；薄封套 import 透传；`judge_sha256` 钉版 |
| 不更新 REGISTRY / 不进 baseline | ✅ | 本卡只新增 `evalkit/` 与 `runs/` |
| 密钥零落盘 | ✅ | 全程未取凭据；模型调用走既有 zcode 账户；报告/journal 无 token |

**未达成项（如实记）**：
- 计划 4 臂，实到 2 臂（单族），原因 §4.1；
- 产物轨未绿，原因 §4.2（装置缺陷），非模型/资产失败；
- 质量轨 `unjudgeable`，无跨族裁判（O-7），**不出分**。

---

## 6. 给下一个人的命令级交接

```bash
cd D:/new-workspace/agent-asset/evalkit

# 0) 先读这两份，别读代码就先跑
#    README.md（装置用法与三条硬纪律）  与  本报告 §4（三处缺陷的完整链条）

# 1) 复跑本轮全流程（新建 run-id，臂树已存在会拒绝覆盖）
python harness/run_all.py --run-id r2

# 2) 若按 §4.2 修法 A 改了题面：改 packs/sm-mapping-01/inputs → fixtures/ 后
#    记得 bump evalbench 版本（--evalbench-version），旧 baseline 作废（O-6 条款）

# 3) 装置自检永远先跑、最后再跑一次
python harness/freeze_device.py verify
```

## 7. 建议 planner 后续处理（按优先级）

1. **裁定 §4.2 修法 A/B**，并按 PLAN §3.6 留档（题号/旧文本/新文本/缺陷类型/判定人）+ bump bench 版本；
2. **开卡修 §4.3**（`SKILL.md:54` INFO 行），建议并入 WS2 同批；
3. **开卡处理 §4.1**（headless 单族限制），WS5 前必须解决，否则 §5.1 四族矩阵落空；
4. **O-6 正式裁定**：实测落点 GLM-5.3 ≠ 文档声称 GLM-5.3-Flash，按条款 bump evalbench 版本、旧基线作废；
5. WS1 已达「管道验证通过」，按 §8 O-17 可考虑把 evalkit 升格 `skillfactory/v6/`（升格时机由 planner 定，
   本卡未擅自升格——PLAN 说「通过后升格」，但「通过」的判据属 M1 阶段门，planner 汇总时定）。

> 本卡严格遵守：只读认领项目文件、holdout 零读、封存区零触碰、oracle 不入任务包、密钥零落盘、
> 不改任何既有资产文件（只新增 `evalkit/` 与 `planning/reports/`）。
