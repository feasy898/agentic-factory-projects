# 模式 M 技术选型决策记录（可玩广告生产线 · 全新实现）

> 日期：2026-09-29。决策人：GLM-5.3 规划层（模式 M 总设计师）。
> 依据：docs/assets/（manifest+CONTRACTS+12 spec，唯一规格源）、REGENERATE.md 再生 SOP、
> _reviews/playable-ads-holistic.md、开发指令.md §0。本文件在 git 外（plan/），是后续批次的执行依据。
> 立场：原实现（repo/，Python+TS 双栈）自本决策起**封存为 oracle**，只读；差分期间发现的 spec 缺口
> 仍按资产流程回填 docs/assets（资产包是活资产，服务新实现）。

## 0. 裁决摘要

**单一 TypeScript/Node 22 栈**，全部产品代码一种语言；数据资产（schema JSON、规则库、specs-eval、
vendor 引擎 bundle）字节级复用；冻结 eval 尽量原样复用（JS 侧测试可原封），Python 侧 eval 按"语义冻结、
宿主移植"重宿主为 node:test。oracle 差分对齐在**契约层**：PlayableSpec 输入 → 产物 + 质检报告 + CLI
退出码输出。新实现落位 `D:\workspace\澄迈8项目\可玩的小游戏广告\factory\`（新 git 仓，与 repo/ 平级）。

---

## 1. 语言与运行时裁决

### 1.1 候选评估

| 候选 | 演示链路复杂度 | 依赖面 | 与冻结 eval 兼容代价 | 代理可维护性 | 风险 | 裁决 |
|---|---|---|---|---|---|---|
| (a) 全 TS/Node 22 单栈 | **最低**：一次 `npm ci` + `npx playwright install chromium`，无 venv/pip/可编辑安装/.pth（REGENERATE §1 全套双环境消失）；断网机用预打包 node_modules + ms-playwright 缓存目录拷贝 | npm devDeps 沿用（ajv/esbuild/sharp/jsdom/c8）；新增仅 pngjs 或 sharp 直读像素、qrcode、subset-font(harfbuzzjs)；Node 22 自带 fetch/test | **最低**：冻结 JS 测试（ajv-check、packager 46 断言、桥 26 用例、logic-test 数值向量）原样复用；Python 侧 eval（pfcore validate 语义、qacore 报告形状、MUT 构造算法、三门）按语义移植 | **最高**：与模板/桥同语言；直接消灭"双语言镜像"这一最大 bug 类（第三波再生的 2 个真 bug 均属此类） | 中：qacore 图像方差跨实现漂移、模板重写 RNG 漂移（有冻结数值向量兜底） | **采纳** |
| (b) 全 Python | 产物必须是浏览器 JS：玩法逻辑要么字符串拼 JS（不可校验）、要么 Pyodide/wasm（运行时 ≥6MB，meta 3MB 线当场爆）| 双倍糟：既留 Node（vendor bundle/esbuild）又留 Python | vendor bundle 与 qc 钩子全是 JS 生态，Python 侧只能当生成器，等于换汤不换药 | 差：生成 JS 字符串无法用类型系统约束 | **结构性不可行**，一票否决 | 拒 |
| (c) Rust/Go 重写 | 产物仍须 JS（canvas/引擎/DOM），Rust→wasm 需胶水层且引擎不可替换；Playwright 无官方 Go 驱动，qacore 得再嵌一层运行时 | wasm 工具链 + 演示机编译环境，离线部署最重 | 规则卡的 JS 数值语义（Math.round 向 +∞、`>>>0`/imul、f64）需逐条复刻，冻结算例反而是唯一护栏 | **差**：Flash 子代理对 TS 熟练度最高，Rust 借用检查/编译循环拖垮迭代 | 高、收益零 | 拒 |
| (d) 维持双栈原样再生（保守基线） | 中：双环境安装是今天演示机最脆的一环（坑 9/10/16 全在 Python 侧 glue） | 不变 | **零**（冻结测试逐字复跑）——差分风险最小 | 差：痛点 8（可解性双实现+随机流分叉）永久化，每加一玩法改三处 | 低，但违背目的 | 拒（见 1.2） |

### 1.2 裁决理由（从目的出发）

1. **产物语言锁定 JS**：渠道包 = 单 HTML 内联 JS；引擎 vendor bundle（中性名，版本锚 3.88.2，~1.2MB）
   是字节复用资产。运行时语言没有第二个选项，问题只是"工具链语言跟不跟着单化"。
2. **资产可持续再生**：spec-contract §5 已把"可解性单一真源（模板导出 check(spec)，校验器调用）"写成
   冻结 spec 的**目标形态**——单栈让该目标从"子进程桥"降为进程内函数调用，双镜像、LCG/mulberry32
   分叉、每玩法改三处，三个结构性负债一次清零。这是本次重写最有价值的一笔。
3. **5 分钟演示 + 断网可跑**：单运行时把演示机安装从"venv+pip 钉版+playwright pip+可编辑安装"缩到
   两条命令；坑清单（REGENERATE §7 坑 1/9/10/16）里 4 条属 Python 环境 glue，直接消失。
4. **48 包 ≤20min**：oracle 全量 422.8s（串行）。Node Playwright 天然多 context 并行，预declare 见 §3.4 P3。
5. **评委/法务红线不受影响**：公开仓词表扫描照跑；新增 npm 依赖名均不在红线词表
   （红线针对投放域上游：smoud/cocos/OpenGame/GameCoder/Kenney/Noto/Qwen/Phaser/PixiJS）。
6. Bun/Den 不选：Playwright、esbuild、jsdom、c8 的锚定生态是 Node 22；演示机离线装 Node msi 最稳。

---

## 2. 架构映射表（资产 → 新实现）

新树 `factory/`（模块 ID 沿用资产编号，便于追溯）：

```
factory/
├─ packages/
│  ├─ spec/            # M1 单源校验器：schema JSON（字节复用）+ ajv + invariants(TS 单份)
│  │                   #   + 模板 check(spec) 进程内注册制（P1）
│  ├─ engine-bridge/   # M2 运行时桥（同构重实现，契约逐条对齐）
│  ├─ packager/        # M4 打包器（同构重实现；zip 交叉验证去 venv 化，P5）
│  ├─ templates/       # M3 ×4（按规则卡+各模板 README 重实现；vendor bundle 字节复用）
│  ├─ llmgw/           # 模型适配（Node fetch 单库，env 契约逐条对齐；director/repair-loop 仍 deferred）
│  └─ assetkit/        # M5 素材管线（sharp + ffmpeg spawn + subset-font）
├─ qacore/             # M8 判官：Node + Playwright + sharp/pngjs（探针/自动试玩/检查项/报告逐项对齐）
├─ pf/                 # 编排 CLI：validate / make / serve（子命令、旗标、退出码、产物树全对齐）
├─ webui/              # 网页壳：node:http 单进程（API 形状对齐；multipart 最小解析器）
├─ channel-rules/      # 字节复用（数据资产）
├─ specs-eval/         # 字节复用（golden×4 + bad×6 + demo-zh + spike-manifest）
└─ scripts/            # gate_phase0/1/2.mjs + e2e_matrix.mjs + finalize_demo_prebuilt.mjs + diff/ 差分 harness
```

### 2.1 模块级映射与 eval 处置

| 资产模块 | 新实现 | 复用冻结 eval | 需重写/适配的 eval 技术点 |
|---|---|---|---|
| M1-spec | packages/spec（单源） | golden/bad/demo-zh 11 件**字节复用**；`ajv-check.mjs` 原样；错误码集、校验次序、I1–I5 语义照抄 | Python CLI → `node pf.mjs validate`（退出码 0/1、`$.` 路径正则、glob 语义全同；stdout 人读格式不锁字节——spec-contract §2.5 已声明门禁只断言 exit+路径）；pydantic 表示层→TS 类型；双镜像废除（P1）；logic-test 中"Python 权威侧回填期望"步骤删除（单源后无权威侧） |
| M2-engine-bridge | packages/engine-bridge | **26 用例 + coverage≥80% + tsc strict 原样复用**（本就冻结 JS） | 无（env 前置：包内相对 coverage include 纪律照抄，防"空过"坑 16） |
| M3-templates ×4 | packages/templates ×4 | 各包 `tests/logic-test.ts` 数值向量**原样复用**（规则卡 §12 算例、LCG 三自由度算例、mulberry32 向量）；门禁"构建+autoplay≤45s"语义照抄 | vendor `engine.js` 字节复用（资产非实现）；构建脚本形态照抄（esbuild iife/escapeForInlineScript/PF_SPEC/PF_LOCALE/PF_ASSETS/.assets.json 旁车） |
| M4-packager | packages/packager | 46 断言自验收**原样复用**（负向 3 条、字节可复现、结构/外链/MRAID 正则） | python zipfile 交叉验证断言 → 系统 bsdtar（Windows 自带 `tar.exe`）独立解包复核，保"独立读取器"意图，SKIP 语义废除（P5）；esbuild 仍为根 devDep |
| M8-qacore | qacore/（Node） | mini.html 夹具复用；MUT-01/02/04 构造算法**逐条照搬**（恰命中断言）；报告 JSON 字段=pipeline-contract §4 逐字段 | py+playwright→node playwright（1.63.x 同版号线，批次 1 钉版核实同一 chromium build）；Pillow 方差→sharp/pngjs 同判定复算（先跑 20 截图语料对照，见 R1）；探针 PROBE_JS、手势表、魔法数字表逐字照抄；zip 解包质检语义照抄 |
| MODEL-ADAPTER(llmgw) | packages/llmgw | selftest 6 项 mock 语义移植（node:http 起 mock 服务）；零厂商端点扫描照跑 | urllib→fetch；SSRF 防线（双处校验、allow_local 仅回环）逐条移植；env 默认值表（30s/2 次/0.8s/8s 封顶）逐字对齐 |
| ORCHESTRATOR(pfcore) | pf/ | make 产物树、退出码、计时口径（make 墙钟 + spec mtime 口径）、二维码 LAN IP 段优先级、serve 契约逐条对齐 | CLI 从 `python -m pfcore` → `node pf.mjs`；demo-prebuilt/.demo-serve.json/8618 顺延/TCP-only 健康检查全保 |
| M10-webui | webui/ | selftest 语义移植（health/meta/build/jobs/qr/静态/负向 400；质检是裁判） | FastAPI→node:http；multipart 自写最小解析器并加负向测试；防 SSRF 纪律照抄（零出站请求） |
| M5-assetkit | packages/assetkit | selftest 8 断言语义移植（降幅≥30% 门、WAV→AAC、字体子集 ≤40KB、图集不重叠、optmap 一一对应） | fonttools→subset-font(harfbuzzjs)；cmap 复核改 fontkit；ffmpeg 继续外部进程 |
| EVAL-gate×3 | scripts/gate_*.mjs | 6/4/5 门项**逐项移植**，断言内容不改（先清后跑、skip 不算过、48 包对账 totals） | 宿主 py→mjs；子进程统一 `PYTHONUTF8` 项删除；中性名扫描词表照抄 |
| 数据资产 | — | **字节级复用**：playable-spec.schema.json、channel-rules.json（rulesVersion 1.1.0）、specs-eval/ 全部、vendor 引擎 bundle、桥/packager 冻结测试文件、mini.html 夹具 | 无 |

### 2.2 契约处置声明

- **数据契约零变更**：specVersion 恒 1.0.0、rulesVersion 1.1.0、schema 文本、规则库数值、报告字段、
  退出码、目录形状、二维码内容规则全部不动。变的只是**实现宿主**——这是差分能成立的前提。
- **实现契约一项变更（P1，预declare）**：C1"双侧实现（Python 权威+JS 镜像）"改为单侧。此变更即
  spec-contract §5 冻结文本中的目标形态，模式 M 授权本决策作为 owner 批准记录；CONTRACTS 版本锚
  与痛点 8 回填由批次 3 执行（`contract-change:` 单独 commit，资产包同步）。
- CLI 表面名迁移表（eval 重宿主台账）：`python -m pfcore`→`node pf.mjs`；`python -m qacore`→
  `node qacore/cli.mjs`；`python -m llmgw.selftest`→`node packages/llmgw/selftest.mjs`；
  `python -m webui.selftest`→`node webui/selftest.mjs`；`python scripts/gate_*.py`→`node scripts/gate_*.mjs`。
  子命令、旗标、退出码、报告路径规则一律同名。

---

## 3. oracle 差分测试计划

### 3.1 对齐层：契约层差分（输入→可观察输出）

- **对齐点**：PlayableSpec 输入（specs-eval 11 件字节复用）→ 产物（渠道包目录/字节结构/pack-manifest）
  + 质检报告 report.json（逐 CHK）+ CLI 可观察输出（退出码/stdout 裁定行/路径正则命中）。
- **不对齐点**：源码内部结构、HTML 字节逐位（模板重写必然不同）、截图像素、variance 原始值（容差内）、
  墙钟绝对值（只对预算断言）。逻辑层等价性由**冻结数值向量**承担字节级强等（这层必须逐位相等）。
- oracle 调用方式：diff harness（factory/scripts/diff/）以子进程驱动 repo/ 的冻结 CLI 入口
  （venv python 保留在本机仅作 oracle 参照，不是产品依赖）。repo/ 全程只读。

### 3.2 差分维度

| # | 维度 | 判等标准 |
|---|---|---|
| F1 | 校验裁定 | 11 件（golden×4+bad×6+demo-zh）：exit code 全等 + issue 集 {path,code} 集合相等（消息人读不锁） |
| F2 | 打包产物 | 目录形状/文件数/manifest 字段语义全等；单 HTML：零外链、mraid 注入、大小线相等判定；zip：条目集与顺序精确相等、实现内两次构建字节一致；独立解包交叉验证过（tar） |
| F3 | 质检报告逐项 | 交叉三判（见 3.3）：逐 CHK 的 pass/fail/skip 状态全等；facts 键集合相等；load_ms/endMs 等数值同量级 |
| F4 | 自动试玩行为流 | 事件序 ready→start→first→end(win=true) 等价；gestures>0；pf:end ≤45s；reachedState=end；endScreenVisible=true；CHK10 文案命中集与 asset_audit.replaced 集相等 |
| F5 | 变异门 | MUT-01/02/04 构造算法照搬，新判官各 exit 1 且 fail 集恰为 {期望 CHK}（3/3 恰命中） |
| F6 | 数值向量（逻辑层强等） | 规则卡 §12 全部算例 + LCG 三自由度算例 + mulberry32/deriveRng 向量 + FNV 形状调色板表逐条复算全等 |
| F7 | CLI 退出码契约 | validate/make/serve/qacore/packager 全家 0/1/2 语义与 oracle 相同输入下相同 |

### 3.3 交叉质检矩阵（F3 的执行方式）

```
设 O=oracle 实现，N=新实现，A=oracle 产物，B=新产物（同 spec×channel×locale）
判等：qacore_N(A) ≡ qacore_O(A)（逐 CHK）   —— 新判官须复现 oracle 判定
且    qacore_N(B) ≡ qacore_O(B)（逐 CHK）   —— 新产物在两判官下同判
且    qacore_N(B) 全 pass（四模板 golden × 六渠道 × {en,zh}）
矩阵规模：先 match3×{en,zh}×7 渠道（14 格）全跑；merge/pullpin/sort 各抽 en×{preview,applovin,meta,mintegral} 抽查后全量
```

### 3.4 "目的性提升"预declare 清单（之外的任何差异=差分失败）

| # | 提升 | 判定标准（可检验） |
|---|---|---|
| P1 | 可解性单一真源：模板包导出 check(spec)，校验器进程内调用；双镜像废除 | F1 全等不受影响；演示性检查：新增第 5 玩法只改模板包一处（登记演示步骤）；spec-contract §5 目标形态条款即授权 |
| P2 | 单运行时：产品零 Python | 干净 Windows 机两步安装（npm ci 离线包 + playwright install chromium）后 gate 三门全绿；断网复装通过 |
| P3 | 全矩阵并行质检（Playwright 多 context） | 48 包 0 FAIL 且墙钟 ≤250s（oracle 422.8s）；逐格报告与串行复跑一致（抽 4 格重跑对账）；并行失败自动降级串行重判 |
| P4 | 报告 schema 化（不改字段） | report.schema.json 新增；对 oracle 产出的全部现存报告 validate 通过（字段零增删） |
| P5 | zip 交叉验证去 venv 化 | 独立读取器=系统 tar；断言语义保持（条目名/入口引用/CRC）；SKIP 分支删除后断言总数恒定 |
| P6 | make 提速（去 Python 子进程开销 + 模板构建缓存） | make 墙钟 ≤ oracle 留档 28.9s（非劣）；>28.9s 即按 oracle 口径登记，不阻塞 |

### 3.5 通过线定义

- **硬线 D1–D9（任一不过=差分失败，对应槽位回退）**：
  D1 F1 校验 11/11 全等；D2 packager 冻结 46 断言全过（含负向 3）；D3 桥 26 用例+coverage≥80%+tsc；
  D4 F6 数值向量全等；D5 交叉质检矩阵按 3.3 规模全等且新产物全 pass；D6 F5 变异 3/3 恰命中；
  D7 e2e 全量 48 包 0 FAIL 且 ≤1200s；D8 gate_phase0/1/2.mjs 三门全绿；D9 make 产 demo-prebuilt
  + 二维码 TCP 可扫 + finalize 脚本过。
- **提升线 P1–P6**：未达标各自降级处理（P3 退串行非劣 ≤420s；P6 仅登记），不阻塞成品；
  硬线不允许降级。
- 差分证据全部落 `factory/artifacts/diff/`（oracle 与新实现报告成对留存），台账写
  `plan/模式M-差分台账.md`（git 外）。

---

## 4. 风险与回退

| # | 风险 | 缓解 / 回退 |
|---|---|---|
| R1 | 图像方差跨实现漂移（Pillow BICUBIC+L 转换 vs sharp） | 批次 2 先跑 20 张截图语料：两实现 variance 差值分布与状态一致性；状态必须全等，数值容差声明写入 qacore spec（回填资产包）；状态冲突以 oracle 判定为准并回炉算法 |
| R2 | Node/Python playwright 浏览器构建不同 | 批次 1 钉版核实 1.63.x 同 chromium build；不同则把浏览器 build 号钉到 oracle 同款写入 spec |
| R3 | 模板重写 RNG/语义漂移 | 冻结数值向量即为此设（第三波已实证抓真 bug）；纪律=先逻辑包过 F6，再接渲染，再过 qacore |
| R4 | qacore 移植不达 D5/D6 且两轮未收敛 | 该槽位回退 oracle qacore（python），pf 编排按 CLI 契约调用；台账登记"P2 单运行时主张降级"；不阻塞其余模块 |
| R5 | 任一新模块卡硬线 | **模块级回退规则**：经契约边界（CLI/退出码/JSON 形状）换回 oracle 对应模块混线运行；混合线必须过全部门禁；差异逐条登记台账（模块/维度/差异/理由/复核日期）；模板/qacore 之外模块禁止混线（要么新要么 oracle，不发明第三实现） |
| R6 | 工期收敛不及预期 | 砍序=开发指令 §11：先 match3×六渠道×{en,zh} 全链过 D1–D9，merge/pullpin/sort 作为增量（oracle 模板槽位暂顶，台账登记） |
| R7 | vendor bundle 复用的法务面 | bundle 已中性化且 grep 零命中，字节复用不引入新名字；批次 3 重跑词表扫描（含新增 npm 依赖名单独核对） |
| R8 | Node 22 类型剥离坑（构造器参数属性等） | 沿用可擦除语法纪律（坑 5 成文条款照抄进新仓 AGENTS/README） |

---

## 5. 实施批次建议（Flash 子代理工作流，每批带硬出口门）

### 批次 1「地基与无浏览器模块」（估 1 天代理量）
任务：factory 脚手架 + 数据资产字节复用拷贝（specs-eval/channel-rules/schema/vendor bundle/冻结 JS 测试）
→ M1 单源校验器（ajv+invariants+check 注册制）→ M2 桥重实现 → M4 打包器（tar 交叉验证）→
llmgw → playwright 钉版核实（R2）。
**出口门**：D1+D2+D3+D4 全绿；`node pf.mjs validate` 与 oracle 对 11 件同判；差分 harness 骨架就位。

### 批次 2「判官与模板」（估 1.5 天代理量，最大风险批）
任务：qacore Node 移植（探针/手势/十项检查/报告逐字段）→ R1 方差语料对照 → 交叉质检 harness
→ 四模板按规则卡重实现（match3 先行过全链，merge/pullpin/sort 依 logic-test 数值向量推进）→ MUT 移植。
**出口门**：D5+D6 全绿；MUT 3/3 恰命中；match3×7 渠道×{en,zh} 交叉矩阵全等。

### 批次 3「编排与成品」（估 1 天代理量）
任务：pf CLI（validate/make/serve）→ webui + assetkit → gate 三门 + e2e_matrix 移植 → 48 包全量
（含 P3 并行）→ demo-prebuilt/finalize → 差异台账定稿 + CONTRACTS 痛点 8 回填（contract-change commit）
→ 法务词表扫描 → 干净机安装演练（P2 验证）。
**出口门**：D7+D8+D9 全绿；台账闭合（每个非 P 清单差异要么修复要么走 R5 回退登记）。

每批结束动作：跑当批出口门 → 更新 manifest.md 状态列 → 差分证据归档 → 台账回填；连续两次出口门
失败触发 R5 模块级回退评估，不得静默放宽断言（bad 样本属规格，永不改期望）。
