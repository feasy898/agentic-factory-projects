# agent-asset 能力基线（正式版 · 2026-10-03）

> 本文件是 agent-asset 工作区的正式能力基线，由「三模型族独立盘点 → 三模型族交叉审校（分歧实测仲裁）→ 合并」三阶段方法产出，合并者为 GLM-5.3。
> 引用标记：〔1〕=1-inventory-glm5.3-flash.md（盘点员 GLM-F）；〔2〕=2-inventory-minimax-m3.1-flash.md（MM-F）；〔3〕=3-inventory-step-router-v1.md（SRV1）；〔4〕=4-synthesis-glm5.3-flash.md（审校员 X-GLMF）；〔5〕=5-synthesis-minimax-m3.1-flash.md（X-MMF）；〔6〕=6-synthesis-step-router-v1.md（X-SRV）。「合并者观察」=本合并会话的只读查证（仅两处，见 §6/§7）。

> **⚠️ 范围声明（2026-10-03 用户指令更新，优先级高于本文其余内容）**：本工作区（D:\new-workspace\agent-asset）当前**只负责 `afp-clone/zcode-research` 的 skill-factory 产线**。monorepo 中其余项目——peidian-agent、qw-arena2、ohos-tailscale、video-capability、chenmai8、xuexing-agent——与本工作区无关，**一律封存**：只读保留，不纳入本工作区的任何规划与开发，不修改，更不删除（它们正在其他工作区文件夹里推进）。本文档关于这些项目的章节仅作 2026-10-03 盘点时的历史记录，不再是本工作区的行动对象。后续一切规划与开发仅围绕 skillfactory 资产产线展开。

---

## 0. 文档目的与方法学

### 0.1 目的

建立整个 agent-asset 工作区的**正式基线认知**：不只记录静态建设了什么，重点回答三个问题——**现在真实能做什么、哪些经过了实际测试验证、以什么证据**。后续任何接手者、审计者或 agent 以本文件为出发点，而不是以 README 的自述为出发点。

### 0.2 方法学（三阶段）

1. **独立盘点**：三名互不通信的盘点员（GLM-5.3-Flash / MiniMax-M3.1-Flash / Step Router v1）各自对同一工作区做命令级实测，产出三份独立报告〔1〕〔2〕〔3〕。
2. **交叉审校**：三名同样互不通信的新审校员（同三模型族）对三份盘点做高置信共识提取、分歧实测仲裁（全部以亲手重跑命令裁定）、盲区补验，产出三份审校报告〔4〕〔5〕〔6〕。
3. **合并**：以审校阶段的高置信共识为骨架（注明几方一致），分歧按仲裁结果落笔，仍悬而未决的进「存疑区」（§6）。

### 0.3 证据等级定义

| 等级 | 含义 |
|---|---|
| **A** | 本次（盘点或审校会话中）实测通过，附命令与输出摘录 |
| **B** | 本机留档证据存在但未重跑（文件/留档/reflog 可核） |
| **C** | 仅文档声称，未经任何一方复现 |
| **D** | 实测发现失效或与声称矛盾（即「A-否」：实测行为本身是 A 级事实，但对声称的判定为否） |

### 0.4 审校备注：口径取舍（三份审校间出入的处理）

三份审校之间有口径出入的，一律以**给出了更深实测证据的一方**为准：

1. **标签总数 = 12**。〔4〕§2-F 与〔5〕E1 两份审校独立实测 `git tag | wc -l` = 12 一致（chengmai-feeding-arm/×8 + chengmai-playable-factory/clean-room-v0 + classroom-v0.1 + xuexing-agent/×2）；盘点阶段〔1〕〔3〕写 13 属口误（〔1〕自己只列出 11 个）。另〔5〕B5 指出 README:58 的标签枚举漏列 classroom-v0.1。
2. **工作树脏项 17 = 10 条跟踪符号链接 + 7 条 untracked**。〔4〕§2-E 以 `git status --porcelain -z` + `git ls-files -s -z` 全量 -z 级比对精确裁定（6 D + 4 T，10/10 全部 mode 120000）；〔5〕E2 独立得出同构结论（10 条 + 7 条，D/T 细分为 5+5，与〔4〕差 1 条不影响定性）；〔6〕仍沿用盘点阶段的「9 符号链接 + 8 untracked」旧口径，不采。根因 `core.symlinks=false`（Windows 检出），**不是内容被改**。
3. **peidian 数字规范口径**：YAML 声明 m0–m7 = **233**、实跑 **182**、记账分母 **184**（= 182 + 2 条 m1/m6 模块级 SPEC_DRIFT 记录）、**51** 例因 m1/m6 整模块中止从未执行。〔4〕§2-A-1 与〔5〕D1 两份审校逐文件计数一致；〔3〕「当前 HEAD 仅 184 条用例」为口径误读，不采。
4. **ohos 280/280 必须带「npm install 之后」前提**。未安装态为 78 tests / 50 pass / 28 fail，全部 ERR_MODULE_NOT_FOUND（〔1〕〔3〕两方独立对照实验一致），**非代码缺陷**；当前 node_modules 已在盘（〔5〕B6），未安装态已不可复现。
5. **本地与 origin 分叉的成因**：〔5〕§6.4-3 仍持「与 10-01 历史重写相容」旧说；〔4〕§2-A-4 逐条列出 25 个 origin 独有提交全部为 10-02/10-03 日期（他机并行工作），并有 reflog `0ab1c25` 证明本仓 10-01 20:37:43 自 GitHub 克隆——以〔4〕为准。
6. **c025efe 修复线的发现深度**：〔6〕§2.1-4 已发现 c025efe 修复未并入 main；〔4〕§4-1 更进一步在 origin/main 尖端重算得 m1/m6 双 MATCH=True——双层结论采〔4〕的深度。
7. **safe_rel 样本数**（7 恶/3 善 vs 6 恶/2 善）：样本集不同非分歧（〔5〕D2），总文统一表述为「恶意路径变体全拒、正常相对路径放行」。
8. **Mimosa hook 活性**：〔5〕自己未复现拦截、改用 hook-state 状态文件举证；〔4〕当场复现了拦截。两条独立 A 级路径互补，综合定 A。

### 0.5 时效边界与环境锚点

- **远端状态钉死于 2026-10-03 10:18**（`.git/FETCH_HEAD` mtime，当天最后一次成功 fetch）。此后 github.com 经 hk-gateway 代理（socks5h://100.64.0.3:7864，见 `C:/Users/Administrator/.gitconfig`）不可达：〔1〕fetch、〔4〕ls-remote、〔5〕ls-remote 三次独立实测均 21s 代理超时。**一切远端（GitHub）现状均无法在线核实**，本基线中关于 origin 的结论全部基于本地缓存引用与本地对象库（离线可验）。
- 本机工具链（主 agent 独立核实的锚点）：Python 3.12.10 / Node v22.23.2 / npm 10.9.8 / pytest 9.1.1 / git 2.55.0（2.55.0.windows.5）/ ffmpeg 6.1.1；两份 nightshift2.bundle SHA256 相同（`f04b6c5db190d0129dbce49db0dc0287dafbae0e45dae0ab5c63df29fb7882c2`），`git bundle list-heads` 均仅 `refs/heads/main=169fd8eb`。
- 本基线描述的是 **2026-10-03 盘点/审校会话时点**的工作区状态；ohos node_modules 已入盘、peidian runtime/ 评测产物等运行时态已随盘点改变（见 §7）。

---

## 1. 一句话定位与组件清单

**一句话定位**：这是「一人软件工厂」monorepo `agentic-factory-projects`（GitHub: feasy898/agentic-factory-projects）的本机副本 `afp-clone/`，核心资产不是产品本身，而是**「规格（SPEC）+ 确定性评测（EVAL）+ 门禁」的方法论**——每个项目把「什么是好的」冻结成可执行评测，验收靠跑测试而不是靠人读文档。该评测方法论经三个模型族独立实测确认**真实、可复现、红路正确 fail-closed**（本工作区最值钱的资产）；7 个项目中 **4 个当前可全绿**（qw-arena2、xuexing-agent、ohos 主门[需 npm install]、skillfactory 评测体系），peidian 本地线门禁红但远端缓存线已有修复，video 与 chenmai8 需重建环境。〔1〕〔2〕〔3〕执行摘要 + 〔4〕§1-16 + 〔5〕C20 + 〔6〕结论一致。

| 组件 | 角色 | 关键事实（等级） |
|---|---|---|
| `afp-clone/`（根符号链接 `agentic-factory-projects` 指向它） | monorepo 主仓 | HEAD=`18f6ead`（2026-10-03 11:04:36，R11 收口台账），477 提交（首提交 d0d0e7c 2026-09-25），本地 main + `origin/wip/gov-gateway-review-person-v0`，12 标签，origin 缓存线 10 ahead/25 behind（A，〔1〕§4.1/〔4〕/〔5〕C1） |
| ├ `qw-arena2/` | 千问 AI Arena 参赛 agent（智能选购顾问 v0.5.2） | 469 测试全绿（A） |
| ├ `xuexing-agent/` | 学情诊断 Agent（确定性内核+LLM 薄壳，契约驱动） | 709+2sk 全绿 + 三件套（A） |
| ├ `peidian-agent/` | 园区配电运维 agent（两票制红线+仿真评测） | 本地线门禁 182/184 FAIL / origin 线已修复（双层，§3.3） |
| ├ `ohos-tailscale/` | 鸿蒙 Tailscale 兼容客户端（纯 TS 协议库 8 包 + ArkTS 壳） | 主门全绿（需 npm install）；bridge 门 11/13 |
| ├ `video-capability/` | AI 营销视频生产流水线（vpipe） | 本环境不可执行（素材不入仓）；安全修复实测有效 |
| ├ `zcode-research/` | skill 资产工厂（skillfactory v1–v5 + 研究线归档） | v5 评测体系存活（A）；REGISTRY.md 18 资产/可分发 3（〔3〕） |
| ├ `chenmai8/` | 参赛项目群（6 子仓 + `_交付/`、`plan--*`、`specs-eval/` 支撑层） | 代码全量在库（A）；门禁需重建环境 |
| ├ `SECURITY-NOTES.md` | 推送前扫描 12 处 high 分诊台账（1 真实已修 + 11 误报） | B（§4） |
| ├ `nightshift2.bundle`（根 + 仓内双份） | 完整历史 git bundle（71,807,830 字节） | 双份逐字节一致；头=169fd8eb=HEAD 父提交（A） |
| 根目录 4 份 eval JSON（dp/hw/sm/zctlmcp） | skillfactory v5 资产评测本机运行留档 | B（SM 已 A 复现；hw 非纯 JSON，§7） |
| `.mimosa/`（根 + 仓内两套） | Mimosa 安全 hook 的报告/历史/台账/hook 状态 | hook 现行活跃（A，§4） |
| `.zcode/`（根 + 仓内） | 主 agent 四阶段推进计划、3 份盘点 workflow 草稿、5+1 个 workflow 运行脚本 | B |
| `baseline-inventory/` | 三盘点 + 三审校共六份报告（本基线的输入） | — |

---

## 2. 真实能力总表（核心）

状态：✅ = 可复现可用；⚠️ = 带条件可用 / 证据有缺口；🔴 = 当前红或不可用。每条证据均为「命令 + 输出摘录」或「文件:行号」的浓缩，全文见各项目基线卡与所引文件。

| # | 能力 | 组件 | 状态 | 等级 | 验证方式与关键证据 |
|---|---|---|---|---|---|
| 1 | 仓库骨架与历史完整性（HEAD/477 提交/12 标签/完整谱系） | afp-clone | ✅ | A | 3 盘点 + 3 审校独立实测：`git log -1` → `18f6ead… 2026-10-03 11:04:36`；`git rev-list --count HEAD` → 477；`git tag \| wc -l` → 12（〔4〕§2-F、〔5〕E1） |
| 2 | 工作树状态判定（17 项脏 = 10 符号链接平台伪差 + 7 untracked，无源码改动） | afp-clone | ✅ | A | `git status --porcelain -z` + `git ls-files -s -z`：10/10 mode 120000、磁盘上实为普通目录、`core.symlinks=false`（〔4〕§2-E -z 级裁定；〔5〕E2 独立复核） |
| 3 | 全量单测 469 用例可复现全绿 | qw-arena2 | ✅ | A | `python -m pytest tests -q` → `469 passed`，exit 0；五次独立运行 17.62–22.14s（〔1〕〔2〕〔3〕〔4〕C2 复跑、〔5〕C2 复跑） |
| 4 | agent 版本自检 | qw-arena2 | ✅ | A | `python agent/agent.py --version` → `0.5.2`（〔1〕〔2〕实测；〔3〕未单独跑） |
| 5 | mock 全链 e2e（确定性校验） | qw-arena2 | ✅ | A | `python tools/e2e_mock.py` → `三份产物齐全=True`，exit 0，~1s（〔1〕〔2〕实测；〔3〕未跑） |
| 6 | 打包产物 e2e | qw-arena2 | ⚠️ | D（环境性） | `python tools/e2e_mock_packaged.py` → 真实 exit=1 `被测产物不存在：…dist\agent\agent.py（先运行 tools/package.py）`；dist 未构建未入库，需先打包（〔1〕4.3-4、〔5〕U4 两方独立实测） |
| 7 | 全量单测 709+2skipped 可复现全绿 | xuexing-agent | ✅ | A | `python -m pytest` → `709 passed, 2 skipped`，exit 0；五次独立运行 4.82–11.24s（〔1〕〔2〕〔3〕〔4〕C3、〔5〕C3） |
| 8 | 知识库校验 + 契约测试 + 凭据零入库三件套 | xuexing-agent | ✅ | A | `validate_knowledge.py` → `VALIDATION OK: 189 kps, 810 items, 343 misconceptions (58 exempt), 52 archetypes, 810/810 dual-agent-verified`；`run_contract.py` exit 0；`git ls-files \| grep -i '\.env$'` → 空（〔1〕〔2〕均 A；〔4〕C3 采纳） |
| 9 | 评测门禁（**本地 main @18f6ead**） | peidian-agent | 🔴 | D | `python run_evals.py --module all` → `EVALS mode=all isolation=OK modules=6/8 pending=0 cases=182/184 failed=2 skipped=0 result=FAIL`，真实 exit=1；六次独立运行逐位复现（〔1〕〔2〕〔3〕〔4〕C4、〔5〕C4、〔6〕§2.1）。四口径：声明 233 / 实跑 182 / 记账 184 / 51 例未执行（§3.3） |
| 10 | spec_hash 修复线（**origin/main 缓存线**，c025efe） | peidian-agent | ⚠️ | A（哈希自洽）+B（门禁全绿为提交自述） | c025efe（10-02 01:56，他机 bot）把 m1/m6 重登记为 673df3dd/78c16232；〔4〕在 origin/main 尖端重算**双 MATCH=True**（离线可验）；门禁在远端线的实跑输出未在线验证（网络不可达）——**修复路径=合并远端线，不是本地重算回写**（§3.3，任务书裁定的审校阶段改写结论 a） |
| 11 | 副门：隔离扫描 + ParkDSL | peidian-agent | ✅ | A | `scripts/ci_isolation.py` → `ISOLATION OK: pattern='PARK-002\|TARIFF-2026B\|OP-1[0-9]' zero hits`；`dsl/tests/run_tests.py` → `TOTAL cases=15 failed=0 RESULT: PASS`（〔2〕〔3〕直接实测、〔5〕C17 复跑；〔1〕由门禁前置步读到 isolation=OK） |
| 12 | 主门 npm test 280/280（**前提：npm install 之后**） | ohos-tailscale | ✅ | A | `npm install`（3–7.6s）后 `npm test` → `# tests 280 # pass 280 # fail 0`，exit 0（〔1〕〔2〕〔5〕C11）；未装态 78 tests/50 pass/28 fail 全 ERR_MODULE_NOT_FOUND，非代码缺陷（〔1〕〔3〕对照实验）；node_modules 已在盘（〔5〕B6） |
| 13 | typecheck + typecheck:bridge | ohos-tailscale | ✅ | A | `npm run typecheck` → exit 0；`npm run typecheck:bridge` → exit 0（〔5〕B3 补验，脚本覆盖率补齐为 5/5） |
| 14 | ArkTS 壳机检 | ohos-tailscale | ✅ | A | `npm run validate:shell` → `summary: 54 passed, 0 failed`，exit 0（〔1〕〔2〕〔6〕盲区补验） |
| 15 | bridge 集成门 test:bridge | ohos-tailscale | 🔴 | A（实测 11/13）/ D（与 13/13 声称矛盾） | `npm run test:bridge` → `# tests 13 # pass 11 # fail 2`，exit 1；2 失败 = disco-netcheck.test.ts 的 STUN 映射（:79）与 Ping→Pong（:125）断言，actual `[203,0,113,10]` vs expected `[156,238,240,81]`（〔1〕〔2〕〔4〕〔5〕C13、〔6〕§2.2）。根因=10-01 公开脱敏漏洗字节数组形态（§3.4、§4.5，任务书裁定的审校阶段改写结论 b） |
| 16 | v3 自检 | video-capability | 🔴 | A（exit 2 实测）+C（对声称不作判断） | `python overnight/vpipe/tests/run_v3_checks.py` → `素材缺失: …avatar_out\dh_stepfun_720p.mp4（dh素材）`，真实 exit=2（四方复现）；`git ls-files -- "overnight/数据"` → 0；脚本自述 2=环境问题未执行，A–E 断言零执行 |
| 17 | vpipe 代码与配置可加载（降级验证） | video-capability | ⚠️ | A | `import qc_orch_v2` OK；`--help` 正常；`thresholds.yaml` 9898 字节在位；ffmpeg 6.1.1 在位（〔2〕〔3〕） |
| 18 | prefetch_model.py 安全修复（safe_rel + https 守卫） | video-capability | ✅ | A | 恶意路径变体全拒（`../evil` `/etc/passwd` `C:/win` `a/../../b` `''` `..` `../../etc/shadow` `x/../y`）、正常相对路径放行、`http://` 端点被拒（`仅允许 https 端点（防 SSRF/明文劫持）`）；代码锚点 prefetch_model.py:44-45（https）、:53-67（safe_rel）（〔1〕〔2〕〔4〕C14、〔5〕C16 多方实测） |
| 19 | skillfactory v5 四资产评测 runner 全绿 | zcode-research | ✅ | A | deploy-pack 4/4、speaker-mapping 4/4（12/12 参照一致）、hotwords 4/4（54 文件一致率 1.0）、zctl-mcp 7/7（4 工具契约 + 变更类零暴露），全部 exit 0（〔1〕〔2〕〔3〕三方全部或部分重跑 + 〔4〕C9、〔5〕C9 复跑） |
| 20 | 评测红路 fail-closed（exit 1） | zcode-research | ✅ | A | 缺失目录 → `FAILED ✗（0/4）` exit 1（〔2〕〔4〕C10、〔5〕C10）；篡改副本 → exit 1，精确报 `empty__m_empty.txt: 第8行 期望='<缺行>' 实测=''`（〔1〕4.8-2） |
| 21 | 归档「学员产物」可复评（留档非 oracle 自说自话） | zcode-research | ✅ | A | deploy-pack `out/student_pack1` 对 oracle → exit 0（〔2〕4.4）；speaker-mapping `out/student_run1` → exit 0 4/4（〔1〕）；〔5〕U11 未复现、方向一致 |
| 22 | 根目录 4 份 eval JSON 留档可信（绝对路径锚定本工作区） | 工作区根 | ⚠️ | B（SM 已 A 复现） | 四份 JSON 的 candidate/reference 均解析到 `D:\new-workspace\agent-asset\afp-clone\…`；数字与三方重跑逐项吻合（4/4、4/4、4/4、7/7）；**hw_student_eval.json 非纯 JSON**，`json.load` 抛 `Expecting value: line 1 column 2`（〔2〕〔4〕、〔5〕U1） |
| 23 | 六子仓代码全量在库 | chenmai8 | ✅ | A | 6 子目录齐 + README 在 + 门禁脚本在位（gate_g1.py/gate_d4.py/gate:m3）；文件数 134/6242/233/161/19748/215 被〔5〕U2 逐位复核吻合 |
| 24 | 六仓一键门禁（**需重建环境**） | chenmai8 | ⚠️ | A（fail-closed 拒跑行为）/ C（09-30 基线数字） | `gate_g1.py` → `[FAIL] 未找到 .venv 解释器`；`gate_d4.py` → FAIL 3/4（中性名扫描 PASS：124 文件×23 模式 0 命中）；`gate:m3` → FAIL 第 4 门差分证据缺失（唯一不因 .venv 阻断）；playable-ads 无 test 脚本；README 自述「当前环境未重建，门禁不能开箱即跑」（§3.7） |
| 25 | git bundle 完整快照（兼灾备种子） | nightshift2.bundle | ✅ | A（事实）/ B（角色为推断） | `git bundle verify` → okay + `records a complete history`；双份 SHA256 一致（主 agent 锚点 + 三方）；唯一 head `169fd8eb` = HEAD 直接父提交（差 1 提交、1 行 worklog.md）；10-03 10:49–10:51 落盘。角色「推送前置物/离线传输载体」为三方同构**推断**（远端不可达无法验证推送本体） |
| 26 | Mimosa hook 活体执法 | .mimosa | ✅ | A | 〔4〕当场复现：同型 Bash 重定向被 PreToolUse 拦截（`Mimosa 拒绝了通过 Bash 直接写入 …runner.py 的操作`），hook-state mtime 实时更新；〔5〕以状态文件举证：本会话 hook-state `bashMutation:true`、mtime 实时变化，两份盘点报告落盘均有 hook-status `outcome=clear/coverage=complete/findingCount=0` 记录 |
| 27 | 「扫描→人工污点流分诊→修复留痕」闭环 | afp-clone 安全链 | ⚠️ | B（分诊台账）/ A（修复复验 + 10:45 干净复扫） | SECURITY-NOTES.md:3 记录 12 high = 1 真实（prefetch_model.py 路径穿越×4+SSRF×1）+ 11 误报（逐条污点流理由）；修复行为实测有效（行 18）；hook-status 10:45 对该文件 `outcome=clear, coverage=complete, findingCount=0`（§4）。**12 处原始扫描报告不在盘内**，无法独立核对 |
| 28 | GitHub 远端同步（fetch/push） | afp-clone | 🔴 | A（不可达实测） | 三次独立 21s 代理超时（〔1〕fetch / 〔4〕/〔5〕ls-remote）；10:18 最后成功 fetch 后断（X-MMF：10:18 尚通、13:35 已断）；本地 10 ahead/25 behind；R11「两波推送」仅提交自述（B） |
| 29 | 工作流驱动的多 agent 并行盘点/审校产线 | .zcode | ⚠️ | B | `workflow-drafts/` 三份盘点编排脚本在位；`workflow-runs/` 根 5 个 + 仓内 1 个（10-02 两个 46KB 生产 run；10-03 12:55 起并行盘点 run）；本轮六份文档本身即该产线产物（存在性 A，脚本内容按红线未读，〔5〕U12） |

**计数：总表 29 行；✅ 18 条、⚠️ 7 条、🔴 4 条。**

---

## 3. 逐项目基线卡

### 3.1 qw-arena2（千问 AI Arena 参赛 agent，v0.5.2）

- **全量单测**：`python -m pytest tests -q` → **469 passed**，exit 0，~18–22s。五次独立运行（三盘点 + 两审校）数字逐位一致。等级 A，3/3 + 审校复跑。
- **版本自检**：`python agent/agent.py --version` → `0.5.2`，与 README G0-2 一致。A。
- **mock e2e**：`python tools/e2e_mock.py` → `agent 退出码=0；evaluate 退出码=0；三份产物齐全=True`，exit 0，~1s。A（〔1〕〔2〕）。
- **打包 e2e**：`e2e_mock_packaged.py` 真实 exit=1（`dist\agent\agent.py` 不存在），需先跑 `tools/package.py`——README 把打包链写为构建步骤，非缺陷，但「开箱全绿」对 G0-3 后半不成立。D（环境性）。
- **真链评估未验证**：`tools/local_eval.py` 需 `DASHSCOPE_API_KEY`，本机未配置；README 声称 6/6/100%/0 保持 C 级（〔3〕），入 §6 存疑。
- 使用注意：pytest.ini 已含 `addopts=-q`，命令行再加 `-q` 会变 `-qq` 吞掉汇总行（〔1〕坑存档）。

### 3.2 xuexing-agent（学情诊断，确定性内核 + LLM 薄壳）

- **全量单测**：`python -m pytest` → **709 passed, 2 skipped**，exit 0，~5–11s。五次独立运行逐位一致。A。
- **三件套**：`tools/validate_knowledge.py` → `VALIDATION OK: 189 kps, 810 items, 343 misconceptions (>= 2 per kp or exempt, 58 exempt), 52 archetypes, schema v2 source ok, 810/810 items dual-agent-verified`；`tools/run_contract.py` exit 0；`git ls-files | grep -i '\.env$'` → 空。A（〔1〕〔2〕均实测）。
- 残留物：根目录 `%TEMP%joint_gate_out.txt`（405B，Windows 重定向事故产物，README 已知问题 5 自认，可删）——见 §7。

### 3.3 peidian-agent（园区配电运维 agent）——本地线 vs origin 线双层结论

**【本地 main @18f6ead：门禁红（D 级，六次独立复现）】**

- 命令：`python run_evals.py --module all` → `EVALS mode=all isolation=OK modules=6/8 pending=0 cases=182/184 failed=2 skipped=0 result=FAIL`，真实 exit=1。m0=49、m2=30、m3=30、m4=19、m5=27、m7=27 全过；m1/m6 SPEC_DRIFT。
- **四口径规范表**（〔4〕§2-A-1、〔5〕D1 两份审校逐文件计数一致）：

| 口径 | 值 | 含义 |
|---|---|---|
| YAML 声明用例总数（m0–m7） | **233** = 49+30+30+30+19+27+21+27 | README「233/233」的分母；m8=7、m9=8 为后加套件不在 `--module all` 活跃集 |
| 实际执行且通过 | **182** | 6 个模块（m0/m2/m3/m4/m5/m7）实跑全过 |
| 门禁记账分母 | **184** = 182 + 2 | 2 = m1/m6 的模块级 SPEC_DRIFT 记录 |
| 从未执行 | **51** = 30(m1) + 21(m6) | spec_hash 漂移导致两模块在跑任何用例前整体中止（modules=6/8） |

- **根因（git blob 级铁证）**：m1 声明 `0b5be472…` vs 重算 `673df3dd…`；m6 声明 `f90a3d34…` vs 重算 `78c16232…`。spec_ref 四文件（specs-v2/M1-agent-core.md、specs-v2/00-ontology.md、specs-v2/01-contracts.md、specs/ADDENDUM.md）做 blob 拼接 hash：`6cdabbb^`=7708b52e…、`6cdabbb`=HEAD=工作树=673df3dd…、LF→CRLF 变换重算=516babd2…，**声明值不匹配任何已提交状态**（〔1〕4.5-4 首证；〔4〕全 477 提交枚举复核：4 个 spec 文件在全部历史中仅 2 种真实共存字节组合；〔6〕§2.1 独立重算同值）。`6cdabbb`（09-29 20:22）提交信息自述「本轮实跑 233/233 PASS」，与其自己提交的字节自相矛盾。已排除 Windows CRLF 检出漂移假设（core.autocrlf=false、文件均 LF）。
- **并发警告**：门禁 `runtime/` 状态不支持并发实跑——〔1〕首跑 m7 出现「任务已存在」×2，系与并行盘点员同时跑门禁互相覆盖 `runtime/eval_results.json` 所致，错峰后消失（〔5〕§3 佐证：其运行时单写者无污染；机制实证：`src/m2_information/__init__.py:170 raise ValueError(f"任务已存在: {task_id}")` + `runtime/{m2_eval,m3_eval,m7_eval,runs}` 共享状态目录；`runtime/` 被 peidian-agent/.gitignore:2 忽略，并发不脏工作树但污染结果）。多 agent 验收同一仓必须错峰或隔离 runtime 输出目录。

**【origin/main 缓存线（03e5a526）：修复已存在（审校阶段改写结论，任务书特别裁定 a）】**

- 提交 `c025efe`（2026-10-02 01:56，作者 `agent:windev-01[bot]`，即另一台机器）提交信息写明：「**core.autocrlf=true 致全树 CRLF、登记口径=CRLF 字节**：LF 归一 338 文件……test_m1/test_m6 spec_hash 按 01 v2 §6 重登记……M1-agent-core.md 冻结后内容漂移登记为 R-2」——终审根因：**登记口径为 CRLF 字节 + 内容漂移双重原因**，这解释了为何单纯 CRLF 变换重算也对不上。〔4〕§2-A-2。
- `git show c025efe -- peidian-agent/tests/test_m1.yaml`：声明值 `-0b5be472… +673df3dd…`——正是从已提交字节重算出的值；〔4〕在 origin/main 尖端重算：**m1/m6 declared==recomputed 双 MATCH=True**（673df3dd / 78c16232）。该修复完整存在于本地对象库，**离线可验**；门禁在远端线的实跑输出未在线验证（网络不可达），但按 c025efe 提交自述门禁恢复 233/233 PASS。
- **分叉定性（修正盘点阶段推断）**：本地 main 与 origin 线 **10 ahead / 25 behind**；25 个 origin 独有提交全部为 10-02/10-03 日期（bean-eye 批处理、硬件交接 docs、peidian 修复、arena 骨架），是**克隆之后另一台机器的并行工作，与 10-01 filter-repo 历史重写无关**（〔4〕§2-A-4 逐条列出，修正〔1〕的「与重写相容」说）；reflog `0ab1c25` 证明 afp-clone 于 10-01 20:37:43 自 GitHub 克隆，本地线从克隆时刻起与远端各自演进。
- **结论**：门禁红的修复路径 = **合并远端线**（或 cherry-pick c025efe 的 tests/test_m1.yaml、test_m6.yaml 重登记 + .gitattributes），**不是本地重算回写**。「233/233 带病数字」的说法对本地线成立、对远端线不成立——该数字在 origin 线上哈希自洽、站得住。〔6〕§2.1-4 独立发现 c025efe 未并入 main，〔4〕补足尖端验证。
- **副门（两线均绿）**：`scripts/ci_isolation.py` → `ISOLATION OK … zero hits`（holdout 零命中）；`dsl/tests/run_tests.py` → ParkDSL 15/15 PASS。A。

### 3.4 ohos-tailscale（鸿蒙 Tailscale 兼容客户端，纯 TS 协议库 8 包 + ArkTS 壳）

- **主门（前提：`npm install` 之后）**：安装 3–7.6s（workspaces 建立 8 条 `@ohos-tailscale/*` 链接 + tweetnacl）→ `npm test` → **`# tests 280 # pass 280 # fail 0`**，exit 0（Node 22 原生类型剥离直跑 .ts，零构建）。**未安装态为 78 tests / 50 pass / 28 fail，28 个失败文件全为 ERR_MODULE_NOT_FOUND——纯缺依赖，非代码缺陷**（〔1〕〔3〕两方独立对照一致）。**当前 node_modules 已在盘**（被 ohos-tailscale/.gitignore:2 忽略，不脏工作树，但未安装态已不可复现——基线留档必须写明 280/280 是安装后态）。
- **typecheck**：exit 0（tsc --noEmit 静默）。**typecheck:bridge**：exit 0（〔5〕B3 补验后脚本覆盖 5/5）。
- **壳机检**：`npm run validate:shell` → 54 passed / 0 failed。A。
- **bridge 门 11/13（D，根因已闭合——审校阶段改写结论，任务书特别裁定 b）**：`npm run test:bridge` → 2 失败 = `app/bridge/test/disco-netcheck.test.ts` 的 STUN 映射回填（:79）与 disco Ping→Pong（:125），均为 `actual: [203, 0, 113, 10]` vs `expected: [156, 238, 240, 81]`。完整因果链：
  1. **机制（MM-F 说对）**：夹具端 `bus.bind({natPublic: '203.0.113.10:41037'})`（:65、:103），`app/bridge/src/mock-udp-bus.ts:190`（〔6〕引 :188）MockStunServer 原样回显 `pkt.from`，故 actual=203.0.113.10 自洽、断言过时；输入全为硬编码常量，**与平台无关，Linux 上同样失败**。被测代码没错，错的是断言。
  2. **因果（GLM-F 说对，X-MMF 补全为「漏洗」）**：10-01 公开脱敏 filter-repo 把字符串形态 `156.238.240.81` 洗成 `203.0.113.10`（点分形态 `git grep "156.238"` 全仓零命中），但**漏洗字节数组形态** `new Uint8Array([156, 238, 240, 81])`（:79、:125 两处），制造不对称断言语义。
  3. **曾自洽的证据**：`ohos-tailscale/worklog.md:23` 记录该测试编写时实跑 `13 pass/0 fail EXIT=0`；`git log --all -S '156, 238, 240, 81'` 与 `-S '203.0.113.10'` 均只命中文件诞生提交 `360bc87`（10-01 04:38）后未再变。边界注记：脱敏前的原始 blob 不在本盘任何对象中（本仓 10-01 20:37 克隆自重写后的 GitHub），故 filter-repo 精确改写了哪些行无法字节级直证，以上为三源互洽（worklog 实跑记录 + PUBLIC-SCRUB-NOTE 自述 + 现存字节形态）的高置信重建。
  4. **修复**：把两处断言改成 `[203, 0, 113, 10]`，**同时修复测试与完成脱敏**（一石二鸟，见 §4.5 与 §8）。
- **app/ ArkTS 壳从未编译**（无 DevEco 工具链、GPU 机不可编译、huawei 登录墙）：C 级，README 已知问题 1 自述（〔3〕、〔5〕U10）。

### 3.5 video-capability（AI 营销视频生产流水线 vpipe）

- **v3 自检本环境不可执行**：`python overnight/vpipe/tests/run_v3_checks.py` → `素材缺失: …overnight\数据\avatar_out\dh_stepfun_720p.mp4（dh素材）`，真实 exit=2；脚本头部自述 `0=全部通过 1=有失败 2=环境问题（ffmpeg/素材缺失，未执行）`，按设计 fail-fast；`git ls-files -- "overnight/数据"` = 0，素材数据集（77G 模型 + 金标 40 条）从未入库（README 已自述运行时依赖不在仓内）。**A–E 全部断言一条未执行，对其「ALL PASS/1m33s」声称不作任何肯定或否定判断**。四方独立复现 exit 2。等级 A（实测）+ C（声称不判断）。
- **降级验证**：`qc_orch_v2` 可 import、`--help` 正常、`thresholds.yaml`（9898 字节）在位；ffmpeg 6.1.1 在位——缺的只是素材与模型。A。
- **安全修复实测有效**：见 §4.3。

### 3.6 zcode-research（skill 资产工厂：skillfactory v5 评测体系 + 四份根目录留档）

- **评测口径**：runner 比对的是「产物根目录」（`run_all.py` 产出的 `out/`，含 manifest.json + 步骤快照）对 `oracle/out` 参照物——**评的是产物一致性，不是源码单测**（〔2〕口径提示，〔5〕U 采纳）。
- **四资产全绿（3/3 盘点 + 审校复跑，A）**：deploy-pack 4/4（三文件文本一致率 100%）、speaker-mapping 4/4（12/12 参照一致）、hotwords 4/4 ALL GREEN（54/54 文件一致率 1.0；四项检查=脚本序列一致/重复添加被拒/funasr 导出格式/参照 100% 一致）、zctl-mcp 7/7（零参数自评；工具集恰等 4 个、变更类工具零暴露）。
- **红路 fail-closed（A）**：指向不存在产物 → `FAILED ✗（0/4）` exit 1（〔2〕〔4〕〔5〕）；篡改副本（〔1〕独立方法）→ exit 1，`replacement_line_by_line` 与 `reference_agreement_100pct` 两项 fail，精确报 `empty__m_empty.txt: 第8行 期望='<缺行>' 实测=''`。技术注记：`discover__empty.stderr.txt` 不在逐字节比对面（比对面=3 discover JSON + 9 转写 txt），篡改它不触发 fail——如实记录的边界。
- **归档学员产物可复评（A）**：deploy-pack `out/student_pack1` 与 speaker-mapping `out/student_run1` 对 oracle 均 exit 0——留档不是 oracle 自说自话。
- **四份根目录 eval JSON（B，SM 已 A 复现）**：dp=deploy-pack 4/4、hw=hotwords 4/4、sm=speaker-mapping 4/4、zctlmcp=zctl-mcp 7/7；数字与三方重跑逐项吻合；candidate/reference 绝对路径锚定 `D:\new-workspace\agent-asset\afp-clone\…`（证明留档就是在本机对着这些产物跑出来的）。**注意：hw_student_eval.json 非纯 JSON**——stdout 全量捕获（4 行 `[PASS]` 日志 + 分隔线 + 尾部 JSON 块），`json.load` 抛 `Expecting value: line 1 column 2`；另三份纯 JSON（〔2〕4.4、〔5〕U1、〔4〕§3 复核）。
- REGISTRY.md：18 资产 / 可分发 3（〔3〕§2）。worklog.md:24 记录 R11 收口闭环。**第 5 个在库资产 acceptor-agent 未被任何一方评测**（合并者观察，见 §6）。

### 3.7 chenmai8（参赛项目群，6 子仓 + 交付支撑层）

- **代码全量在库（A）**：chenmai-bean-eye / chenmai-drama-dub / chenmai-feeding-arm / chenmai-gov-ai-gateway / chenmai-playable-ads / chenmai-playable-factory 六目录齐，加 `_交付/`、`plan--*/`、`specs-eval/` 支撑层；各仓 README 在位；文件数 134/6242/233/161/19748/215（〔2〕首报、〔5〕U2 逐位复核）。
- **门禁 fail-closed 拒跑（A，行为层）——逐仓实测**：

| 子仓 | 声称基线（09-30，C 级） | 本次实测 | 阻断原因 |
|---|---|---|---|
| chenmai-feeding-arm | gate_g1 8/8 | `[FAIL] 未找到 .venv 解释器`（三方全跑同输出） | 缺 .venv |
| chenmai-bean-eye | gate_d4 4/4 | `GATE D4: FAIL (3/4)`；④ 中性名扫描 PASS（124 个跟踪文本文件 × 23 模式，命中 0） | 缺 .venv（〔3〕独家、〔4〕〔5〕复跑确认） |
| chenmai-playable-factory | gate:m3 4/4 + 122 tests | `GATE-M3: FAIL`（墙钟 14s）；第 4 门 `artifacts/diff/d4-autoplay-streams.json` 不存在；[4/4] 中性名扫描 PASS（215 文件 × 5 词，0 命中） | **差分证据缺失——六仓中唯一不因 .venv 阻断的例外**（需先跑 `node scripts/diff/d4-autoplay-streams.mjs`） |
| chenmai-playable-ads | phase 门 6/6 | `package.json` scripts 为空对象，无 test 脚本 | 门禁入口不在 package.json（〔3〕〔5〕U9） |
| chenmai-gov-ai-gateway | gate_final 9/9 | 未找到 gate_final 入口脚本 | 需 ≥90 分钟 + 三条服务隧道（〔3〕，〔4〕§2-H-4 未复核维持原判） |
| chenmai-drama-dub | gate_b4 6/6 | 未运行 | 需 GPU + ffmpeg + 本地推理服务 |

- README 自述「当前环境未重建，门禁不能开箱即跑」——诚实声明，**基线保留 09-30 数字但全部标注 C（未复现）**。重建指引在各仓 README 正文（gov-gateway 用 constraints.txt、drama-dub 需 ffmpeg+推理端口）；独立 REGENERATE 文件两层深度内无命中（〔1〕4.9-3）。

---

## 4. 安全能力基线

### 4.1 Mimosa 扫描设施：hook 现行活跃（A 级，当场复现 + 状态文件双路举证）

- **活体拦截复现**：〔1〕盘点会话中一次 Bash 重定向被 Mimosa PreToolUse 拦截（`Mimosa 拒绝了通过 Bash 直接写入 eval/runner.py 的操作`，对只读复验命令的误判）；〔4〕审校以同型命令**当场复现**拦截，且 `.mimosa/hook-state/` mtime 实时更新（13:48–13:52）。〔5〕自己未复现拦截，改用状态文件独立举证：其自身会话的 hook-state（sess_dwf-dwfrun-fc74f056…）`bashMutation:true`、mtime 13:31:05 实时变化；同目录另有 3 个并行盘点/审校会话的 hook-state。两份盘点报告的落盘本身各有 hook-status 记录（dwfrun-1095ea25 →〔2〕、dwfrun-56c4fa86 →〔1〕，均 `outcome=clear / coverage=complete / findingCount=0`）。
- **已知局限**：hook 存在误伤只读操作的可改进点（〔1〕独家观察，〔5〕标 B 未复现；〔4〕复现成立）。
- **深度扫描通道**：`~/.mimosa/security-scans/` 仅 2026-09-28/29/30 的其他 project-* 扫描（7 项目目录 80 文件）；`~/.mimosa/security-scan-jobs/` 11 个 job 最新 2026-09-29 12:20（〔5〕B4 加查）——**10-03 的 12-high 扫描未走深度扫描归档通道**。
- **留档 run 状态**：两级 `.mimosa/history/` 共 4 个 run（root 2 + 仓内 2；〔3〕报 2 为漏读仓内，〔5〕D4 裁定 4），全部 `runStatus=inconclusive`、`findings.total=0`、coverage partial；10-03 03:15Z 那次 errors 含 `scanner_failed: spawnSync node.exe ETIMEDOUT`（对象恰是 prefetch_model.py）+ `project_check_failed`，`scanned_files: 0`、`captured_files: 2851`（report 文件）、`evidenceBoundary=static_only`。

### 4.2 SECURITY-NOTES 分诊与 12-high 原始报告缺失

- `afp-clone/SECURITY-NOTES.md:3`：`> 2026-10-03，zcode-nightshift。触发：Mimosa git-push 前扫描报 12 处 high。`分诊结论：**1 处真实**（video-capability `prefetch_model.py` 路径穿越 ×4 + SSRF ×1，已修）+ **11 处误报**（逐条给出无污点流理由，方法论=「不信模式匹配结论」）。等级 B（文字台账）。
- **原始 findings 报告不在盘内任何位置**（`.mimosa/` 两级、`~/.mimosa/security-scans/`、`~/.mimosa/security-scan-jobs/` 均无 10-03 产物）——「12 处」的机器原始清单**永久不可独立核对**（〔1〕〔2〕深查、〔4〕§4-2 加深、〔5〕§2.4 加查第三归档根，三方一致）。「不在盘内」≠「未运行」，该清单属前者。

### 4.3 safe_rel / https 守卫修复实测（A）

- 代码锚点：`prefetch_model.py:44-45`（非 https scheme → raise，SSRF/明文劫持守卫）、`:53 def safe_rel`、`:58` 拒绝 isabs/盘符/`..`/空段、`:63` realpath 包含性断言（commonpath）。
- 行为实测（多方独立）：恶意路径变体全拒——`../evil`、`/etc/passwd`、`C:/win`、`a/../../b`、`''`、`..`、`../../etc/shadow`、`x/../y`；正常相对路径（`model.safetensors`、`sub/dir/f.bin`）正确放行；`http://` 端点被拒（消息：`仅允许 https 端点（防 SSRF/明文劫持）`）；`--help` exit 0。〔1〕7恶/3善、〔2〕6恶/2善、〔4〕含 `x/../y` 复跑、〔5〕含 `../../etc/shadow` 复跑——样本集不同，结论方向完全一致。

### 4.4 10:45 全覆盖干净复扫记录（部分弥补证据链缺口）

〔4〕§4-2 新发现：`.mimosa/hook-status/sess_cad6cf65-…-16331c4390.json`（recordedAt 2026-10-03T02:45:35Z = 本地 10:45，即安全分诊提交 169fd8e 前 3 分钟）：`event=PostToolUse, toolName=Edit, file=…/prefetch_model.py, outcome=clear, coverage=complete, findingCount=0`——**修复提交前，hook 对该文件完成过一次全覆盖扫描且零 findings**；且 task-review 的 diff 面恰为修复行（ranges 43-45/53-67/170/207-208）。终判：修复动作有机器复扫背书；但「12 处」原始清单仍只有 SECURITY-NOTES.md 一纸留痕。

### 4.5 真实 IP 残留风险（公开仓，审校阶段改写结论，任务书特别裁定 b）

- **事实**：hk-gateway 真实出口 IP `156.238.240.81`（归属见 `D:\AGENTS.md` 机器表）以**字节数组** `new Uint8Array([156, 238, 240, 81])` 形式残留在公开仓测试文件两处：`ohos-tailscale/app/bridge/test/disco-netcheck.test.ts:79` 与 `:125`。
- **点分形态已被清掉**：`git grep "156.238"` 全仓零命中（10-01 filter-repo 公开脱敏的成果）；字节数组形态文本替换不可达，漏洗。`docs/oracle/protocol-notes.md:200` 亦自证 `203.0.113.10:41037`「中的公网地址正是 hk-gateway 的公网 IP」。
- **声明被证伪**：`PUBLIC-SCRUB-NOTE.md` §3 声称「测试夹具中的地址已随上表一并示例化（app/bridge/test/、packages/*/test/）」，而 §2 映射表只登记了字符串形态——对字节表示形态的清洗承诺未达成。
- **双重影响**：这同时是 bridge 门 11/13 的根因（§3.4：夹具端被洗成 203.0.113.10、断言端没洗，不对称断言）。**修复动作：把两处断言改成 `[203, 0, 113, 10]`，一次提交同时修复测试与完成脱敏**，并回写 PUBLIC-SCRUB-NOTE.md §3 的不实承诺。溯源：`git log --all -S "156, 238, 240, 81"` 仅命中诞生提交 `360bc87`（10-01 04:38）；该提交是否为 filter-repo 重写产物无法判定（`.git/filter-repo/` 无残留、author=committer 时间戳无重写特征）——悬而未决但不影响裁定（〔5〕§2.1 附注）。
- 定性：不是可利用漏洞，是**公开清洗的覆盖面审计缺口**+真实基础设施信息暴露，应作为待办项与断言修复同批处理（〔5〕B2 口径）。

---

## 5. 与 README 声称的出入清单（声称 vs 实测 vs 裁定）

| # | README/文档声称 | 实测 | 裁定 |
|---|---|---|---|
| 1 | peidian「评测门禁 233/233 PASS exit 0（本轮实跑）」（README/TASK/worklog 10 余处） | 本地 main@18f6ead：182/184 FAIL，exit 1，m1/m6 SPEC_DRIFT，51 例未执行 | **本地线不成立（D）**；但 origin/main 缓存线 c025efe 已重登记且哈希自洽——「带病数字」降级为「本地线过期」，修复路径=合并远端线（§3.3） |
| 2 | ohos「bridge 13 pass / 0 fail」 | 11/13，exit 1 | **不成立（D）**；根因=公开脱敏漏洗字节数组形态的不对称断言，平台无关；修复=断言改 [203,0,113,10] |
| 3 | ohos「npm test 280 pass / 0 fail」 | 安装依赖后 280/280 属实；未装态 78/50/28 | **成立但必须带前提**（npm install）；未装态失败非代码缺陷；「开箱即跑」表述不准确 |
| 4 | video「v3 自检 ALL PASS / EXIT=0（1m33s）」 | exit 2 素材缺失，A–E 断言零执行 | **本环境不可验证**；README 已自述 77G 模型/金标不在仓内，属环境不完整而非虚假声称，但基线不得写「已验证」 |
| 5 | chenmai8 各仓门禁数字（8/8、4/4、122 tests、9/9、6/6） | 六仓全部拒跑/未验证 | README 已诚实声明环境未重建；数字全部 C 级保留但注明未复现 |
| 6 | qw「G0-3 e2e 全链」 | mock e2e 过；packaged e2e exit 1（dist 未构建） | 前半成立、后半需先打包，「开箱全绿」不成立（环境性，非缺陷） |
| 7 | README:58 标签清单 | 实测 12 个标签 | README 枚举漏 `classroom-v0.1`（〔5〕B5）；盘点阶段「13」为口误，实为 12 |
| 8 | 整体「全绿」基调 | 7 项目中 4 个当前可全绿 | **偏乐观**（3 盘点 + 3 审校独立同判）；按本基线 §2 分档修正 |

---

## 6. 存疑与未验证清单

1. **GitHub 远端实况**：三次独立 21s 代理超时（fetch/ls-remote ×2），远端现状无法在线核实；本地 10 ahead/25 behind；R11 台账「两波推送」仅提交自述（B），无机器可核验证据；origin/main 缓存线（03e5a526）上的门禁实跑输出同样未在线验证（仅哈希自洽 + c025efe 提交自述）。
2. **chenmai8 六仓门禁数字**：8/8、4/4、122 tests、9/9、6/6 全部为 09-30 日志声称，本次一条未复现（C）。
3. **qw-arena2 真链评估**：`local_eval.py` 需 `DASHSCOPE_API_KEY`，本机未配置；声称 6/6/100%/0 为 C。
4. **ohos app/ ArkTS 壳编译**：从未编译（需 DevEco 工具链），C 级文档声称。
5. **peidian spec_hash 声明值 `0b5be472…`/`f90a3d34…` 对应哪一刻的字节**：漂移发生在某次未提交的工作树时刻，库内无证据可还原，三方宣告不可还原（〔4〕§2-H-3、〔5〕§2.5-1）。
6. **`360bc87` 是否为 filter-repo 重写产物**：无 commit-map 残留、时间戳无重写特征，不可判定（〔5〕§2.1 附注）。
7. **12 处 high 的原始条目**：报告不在盘内，永久不可核验（§4.2）。
8. **peidian m7 并发污染事件本身不可重放**：机制已 A 级证实（§3.3），当次现象 B 级。
9. **acceptor-agent 资产（合并者只读观察）**：`zcode-research/skillfactory/v5/assets/acceptor-agent/` 为第 5 个在库资产（`git ls-files` 见 13 个跟踪文件：blind/sample1、sample2 各 3 件、contract.md、eval/runner.py、oracle/expectations.json、package/agent.md、example-verdict.json、schema/verdict.schema.json、spec.md）——六份输入均未评测它，REGISTRY 台账口径未核；本基线对其能力不作任何判断。
10. **hw_student_eval.json 之外的三份 JSON 未做逐字段 diff 复核**（仅字段/数字吻合 + 绝对路径锚定）；10-02 46KB 生产 workflow 的脚本正文按红线未读（〔4〕§4-4）。

---

## 7. 已知失效 / 残留物 / 风险清单

1. **NUL 保留名文件（双侧问题）**：`zcode-research/skillfactory/v5/assets/deploy-pack/package/NUL`——本地磁盘残留（1698 字节，mtime 10-02 00:15，untracked，内容为 validate.py 评估留档 JSON「ALL GREEN pass 7 fail 0」，磁盘 sha256 `aab92ece…` 与 `100a9c2^` 的 blob 逐字节相同）；本地线 `100a9c2`（10-03 10:21「清除 NUL」）**只清了索引、磁盘未清**；**origin/main 线仍跟踪该路径**（blob 25ab5fc）——任何从 GitHub 新克隆仍会拿到该损坏路径。机制（〔5〕B1 临时仓复现）：Windows 保留名使 git 无法按路径读写（`git add` → `error: short read while indexing NUL / failed to insert into database`；`git rm` exit=128），故「git 层面删除」永远清不掉磁盘本体。origin 独有提交 b228a92/8a4a55b 记载了「NUL 提交管线」（他机专门管线入库保留名文件）。处置需非 git 路径：PowerShell `Remove-Item -LiteralPath '\\?\D:\...\NUL'`。
2. **根目录 NUL（合并者只读观察）**：`D:\new-workspace\agent-asset\NUL`（102 字节，mtime 10-03 13:39）——六份输入未提及，时点落在盘点/审校会话期间，性质同类（重定向事故产物），处置同上。
3. **`%TEMP%joint_gate_out.txt`**：xuexing-agent 根目录，405B，10-02 00:15，Windows 重定向事故产物，README 已知问题 5 自认，可删（〔2〕、〔4〕、〔5〕U3 三方确认）。
4. **hw_student_eval.json 非纯 JSON**：stdout 全量捕获（`[PASS]` 行 + 尾部 JSON），下游 `json.load` 会炸；另三份纯 JSON（§3.6）。
5. **符号链接平台伪差**：工作树 17 项脏 = 10 条跟踪符号链接（mode 120000，`core.symlinks=false`，磁盘上实为普通目录）+ 7 untracked；根目录 `agentic-factory-projects` 符号链接本身也是易碎点。**`git status` 非空 ≠ 有人改了代码**——基线检查脚本不得据此误判（〔2〕建议、〔4〕§2-E、〔5〕E2 一致采纳）。
6. **peidian 门禁不支持并发实跑**：runtime/ 共享状态（§3.3）；多 agent 同时验收同一仓会互相污染结果（不脏工作树但污染结果）。
7. **node_modules 已入盘改变可复现态**：ohos 280/280 的对照态（78/50/28）已不可复现；留档必须写明「280/280 是安装后态，且安装态现已在盘」（〔5〕B6）。
8. **真实 IP 字节数组残留**：§4.5（公开仓两处 + 清洗声明被证伪）——在公开仓上，这比测试变绿更重要（〔5〕§6.4-2）。
9. **测量方法坑（过程留档）**：Git Bash 中 `$?` 取管道尾命令退出码，测真实退出码必须无管道重定向留档后读（〔1〕首日两处返工教训）；pytest 命令行重复 `-q` 吞汇总行（§3.1）。
10. **计数勘误留档**：盘点阶段的「13 标签」「9 符号链接」「184 条用例」「两次扫描 run」均已被审校正为 12 / 10 / 记账分母 184（YAML 233）/ 4 runs（§0.4）。

---

## 8. 修复路径与基线维护建议

1. **peidian 门禁恢复（第一优先）**：合并 origin/main（或 cherry-pick c025efe 的 `tests/test_m1.yaml`、`test_m6.yaml` 重登记 + `.gitattributes`），**不是本地重算回写**；合并前梳理 10 ahead/25 behind 分叉（25 个 origin 独有提交为他机 10-02/10-03 并行工作）；网络恢复后在线验证远端线门禁实跑输出。
2. **bridge 断言修复 + 脱敏收尾（一次提交两件事）**：`disco-netcheck.test.ts:79/:125` 断言改 `new Uint8Array([203, 0, 113, 10])`；同步回写 PUBLIC-SCRUB-NOTE.md §3 的不实承诺（补记字节数组形态的清洗口径），并对全仓做一次字节数组形态 IP 复查。
3. **NUL 双侧清理**：本地用 PowerShell `Remove-Item -LiteralPath '\\?\D:\...\NUL'`（非 git 路径；deploy-pack 与根目录两处）；远端线需在新提交中删除该跟踪路径并随下次推送落地。
4. **hw JSON 留档格式**：重导出为纯 JSON，或改名 `.log`/加解析说明——任何下游工具按 JSON 解析四份文件会在第二份上炸。
5. **杂项清理**：删除 `%TEMP%joint_gate_out.txt`；README:58 补列 `classroom-v0.1`；README 的 peidian/ohos/video/chenmai8 段按 §5 出入清单修订（尤其给 ohos npm test 加 npm install 前提、peidian 注明本地线状态与修复线）。
6. **网络恢复后**：`git fetch` / `ls-remote` 核实远端实况与「两波推送」是否落库；确认 hk-gateway socks5 代理（socks5h://100.64.0.3:7864）恢复后按 owner 决定推送本地 10 个提交。
7. **基线复跑口径（硬规矩，照抄自审校建议）**：任何数字必须带命令 + exit code，且**前置条件与命令同框**（ohos 的 npm install、chenmai8 的 .venv、video 的 77G 素材+金标）；「声称 vs 实测」成对出现并给失败机制；「不在盘内」与「未运行」分开表述；推断与事实分层（bundle 的「推送载体」角色是推断，须与 A 级的「169fd8eb=HEAD 父提交」分开写）；多 agent 并发验收必须错峰或隔离 runtime；`git status` 非空不判为改代码。
8. **多 agent 协作纪律**（本次实证教训）：同一门禁的 runtime/ 状态不支持并发（peidian m7 实证）；后续盘点/验收类多 agent 任务应编排错峰，或为每个 agent 分配隔离的运行时输出目录。

---

## 9. 附录：六份输入文件索引与方法学统计

### 9.1 文件索引

| 文件 | 作者（模型族·角色） | 结构与覆盖 |
|---|---|---|
| `baseline-inventory/1-inventory-glm5.3-flash.md` | GLM-F（GLM-5.3-Flash · 盘点） | 能力矩阵 + 实测记录 10 小节（仓库状态/环境/7 项目/安全痕迹）+ 分歧存疑 8 条 + 基线建议 + bundle 定性；独家：npm install 对照实验、spec_hash blob 级考古、Mimosa hook 活体观察、红路篡改副本法、并发互踩教训 |
| `baseline-inventory/2-inventory-minimax-m3.1-flash.md` | MM-F（MiniMax-M3.1-Flash · 盘点） | 能力矩阵 + 实测 6 小节 + 分歧 6 组 + 基线建议；独家：peidian 四口径首报、真实 IP 硬编码发现、NUL 未清发现、hw JSON 非纯 JSON、学员产物复评、bridge 平台无关性论证 |
| `baseline-inventory/3-inventory-step-router-v1.md` | SRV1（Step Router v1 · 盘点） | 能力矩阵 + 实测 8 小节 + 声称对照表 + 建议；覆盖最广的 chenmai8 逐仓降级验证（bean-eye gate_d4 3/4、playable-factory 第 4 门、playable-ads 无脚本）；未装依赖态 npm test 归因 |
| `baseline-inventory/4-synthesis-glm5.3-flash.md` | X-GLMF（GLM-5.3-Flash · 审校） | 高置信共识 16 条 + 仲裁 A–H 8 组（含悬而未决 4）+ 独家复核 12 条（另 4 条降级/修正）+ 盲区补验 4 项；**独家改写：origin/main 缓存线 c025efe 双 MATCH 验证、25 提交逐条列定性多机并行、工作树 -z 级 10+7 精确裁定、10:45 hook-status 干净复扫** |
| `baseline-inventory/5-synthesis-minimax-m3.1-flash.md` | X-MMF（MiniMax-M3.1-Flash · 审校） | 共识 C1–C20 + 19 条候选分歧仲裁（真分歧 1/口径 6/计数 3/一致矛盾 9；悬而未决 4）+ 复跑确认 7 项 + 盲区补验 B1–B6 + 独家 U1–U12（另 8 条修正）；**独家：NUL 破坏性机制临时仓复现、字节数组残留第二处（:125）、typecheck:bridge 补验、security-scan-jobs 第三归档根加查、hook 活性状态文件举证法** |
| `baseline-inventory/6-synthesis-step-router-v1.md` | X-SRV（Step Router v1 · 审校） | 共识 10 条 + 仲裁 5 组 + 独家复核 5 条 + 盲区补验 2 项（typecheck/validate:shell 提升为 A）；独立重算 spec_hash 同值、独立发现 c025efe 未并入 main |

### 9.2 方法学统计

- 独立盘点阶段：三模型族互不通信，各自完成命令级实测；对同一命令的多方输出（qw 469、xuexing 709+2、peidian 182/184 FAIL、video exit 2、gate_g1 拒跑、四 runner 全绿）构成天然的重复测量。
- 交叉审校阶段：三审校员对三份盘点做共识提取（〔4〕16 条 / 〔5〕20 条 / 〔6〕10 条，交集构成本基线骨架）、分歧实测仲裁（全部以亲手重跑裁定，零「引用即采纳」）、盲区补验（〔4〕4 项 / 〔5〕6 项 / 〔6〕2 项）。
- 合并阶段（本文件）：骨架 = 高置信共识（注明几方一致）；分歧 = 按仲裁落笔；三审校口径出入按「更深实测证据优先」取舍（§0.4 共 8 条，含任务书点名的 4 条）；悬而未决进 §6；两条审校阶段改写结论（peidian origin 线、IP 字节数组残留）完整保留于 §3.3/§3.4/§4.5。

### 9.3 三方一致性矩阵概览（盘点口径 → 审校裁定）

| 事实/能力 | GLM-F〔1〕 | MM-F〔2〕 | SRV1〔3〕 | 审校裁定 |
|---|---|---|---|---|
| qw-arena2 469 passed | A | A | A | 一致，A（〔4〕〔5〕复跑） |
| xuexing 709+2sk | A | A | A | 一致，A（复跑） |
| xuexing 三件套 | A | A | 未跑 | A（两方独立 A，〔4〕采纳） |
| peidian 门禁 | D 182/184 | D | D（口径误读 184 用例） | FAIL 属实；口径修正为 233/182/184/51；origin 线已修复（〔4〕深度） |
| peidian 副门 | A（经门禁输出） | A | A | A（〔5〕C17 直接复跑） |
| ohos npm test | A（装后 280） | A（装后 280） | D（未装 78/50/28） | 装后 A；未装态非缺陷（对照闭环） |
| ohos typecheck/shell | A | A | 阻断 | A（〔6〕补验） |
| ohos test:bridge | D 11/13 | D 11/13 | 未跑 | 实测 11/13（A）；双根因闭合（清洗漏洗字节数组） |
| video v3 | D | C（不表态） | D 阻断 | exit 2 一致；对声称不作判断 |
| skillfactory 四 runner | A（SM） | A（4 资产） | A（4 资产） | A（复跑） |
| 红路 fail-closed | A（篡改法） | A（缺失法） | 未跑 | A（〔4〕〔5〕复跑） |
| chenmai8 在库/拒跑 | A | A | A | A |
| 标签数 | 13（误） | 12 | 13（误） | **12**（〔4〕〔5〕实测） |
| 工作树构成 | 9 symlink | 9 symlink | 5D/7M/6?? | **10 symlink + 7 untracked**（〔4〕-z 级、〔5〕独立复核） |
| bundle 关系/一致性 | A | A | A | A；角色「推送载体」为推断（B） |
| 12-high 证据链 | B（缺失） | B（缺失） | B（引用） | B；原始报告永久不可核验；10:45 复扫补强 |
| Mimosa hook 活性 | A（被拦截） | 未复现 | 引用 | A（〔4〕复现拦截 + 〔5〕状态文件） |
| GitHub 远端 | 不可达 | 不可达 | 不可达 | 不可达（钉死 10:18） |
| 总判断「全绿偏乐观」 | 是 | 是 | 是 | 三方 + 三审校独立同判 |

---

*本基线由合并者（GLM-5.3）于 2026-10-03 依据六份输入文件与主 agent 核实锚点写成；除 BASELINE.md 外未新建/修改任何文件，未 commit/push，未外发数据。事实边界：六份输入 + 主 agent 锚点 + 合并者两处只读观察（根目录 NUL、acceptor-agent 在库），无其他新增主张。*
