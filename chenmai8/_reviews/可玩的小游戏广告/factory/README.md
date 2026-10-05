# ✅ 官方成品 · 澄迈可玩广告生产线（factory）

> **模式 M 终审通过 + 独立复核**（2026-09-30）。本仓（`feasy898/chengmai-playable-factory`，
> TS/Node 22 单栈）为**正式成品**；oracle `../repo/` 已**封存为回归参照**（只读，零新功能，
> 见其 README 顶部封存声明）。两仓关系与差分证据：**docs/diff/differential-report.md**
> （summary.pass=true、regressions=0；台账 18 项非 P 清零）；行为流差分 4 模板 × 3 seed
> 全格等价（12/12）；GATE-M3 出口门 4/4（`npm run gate:m3`）。
> 全栈决策依据：`../plan/模式M-技术选型决策.md`（其裁决优先于任何旧规划）。

**快速上手**（两步安装 + 一条命令 + 扫码）：

```bash
npm ci                                        # ① 安装（离线机用预打包 node_modules）
node pf/pf.mjs make --spec specs-eval/demo-zh.json --locales en,zh --channels applovin
# ② 全流水线：校验 → 素材管线 → 模板构建（真实可玩单 HTML）→ 渠道打包 →
#    判官自动试玩质检 → 汇总页 + 局域网二维码 + artifacts/demo-prebuilt/ 兜底
#    浏览器操作台（可选）：npm run webui 后开 http://<LAN-IP>:8788/
```

跑完用手机（同一局域网）扫控制台/汇总页上的二维码即玩；或打开
`artifacts/demo-prebuilt/index.html` 所在目录的任意静态伺服。

**演示兜底（demo-prebuilt）**：make 成功即把全部演示件整体复制进
`artifacts/demo-prebuilt/`——`index.html`/`summary.html` 汇总页、`preview/` 可玩预览、
`channels/<渠道>/<语言>/` 渠道包与质检报告、`qr.png` 二维码、`pipeline-report.json` 全量
流水线报告。该目录**纯静态、自包含、零外链**，任何静态文件服务器指向它即可重演演示；
质检不过时 make exit 1，**不产出**二维码与兜底目录（宁可失败不可假绿）。

---

TS/Node 22 单栈重写（决策：`../plan/模式M-技术选型决策.md`，其裁决优先于任何旧规划）。
oracle `../repo/` 封存只读；差分对齐在**契约层**（spec 输入 → 产物 + 质检报告 + CLI 退出码）。

## 命令

```bash
npm ci            # 安装（离线机用预打包 node_modules）
npm test          # node --test 全仓测试（含数据资产 sha 逐项校验；122 件）
npm run build     # esbuild 构建链（遍历 workspaces 包；空跑 exit 0）
npm run verify:assets   # 单独重算 REUSED-ASSETS.md 登记册

# 模块自验收（真实执行 exit 0）
npm run test:pf         # 编排 CLI（validate 同判 + make/serve 端到端）
npm run test:qacore     # 判官（unit + 浏览器 + 四模板）
npm run test:assetkit   # 素材管线 selftest（9 断言，实测降 99.24%）
npm run test:webui      # 网页壳端到端（30 断言，约 100s）
npm run webui           # 起网页操作台（node webui/app.ts，默认 0.0.0.0:8788）

# 门禁与矩阵
npm run gate:m1 / gate:m2 / gate:m3   # 批次出口门（gate-m3 = 差分终审门 4/4）
npm run matrix                        # 48 包全矩阵（4 golden×{en,zh}×6 渠道）
```

## 布局（决策 §2 树）

```
packages/   spec(M1) engine-bridge(M2) packager(M4) templates(M3×4+vendor母本) llmgw assetkit(M5·已落地)
qacore/     M8 判官（真实浏览器自动试玩质检，十项检查）
pf/         编排 CLI：node pf.mjs validate|make|serve（make 默认接线素材管线）
webui/      M10 网页壳（已落地：上传/表单 → make 任务 → 二维码+质检报告+渠道包下载）
channel-rules/  字节复用（rulesVersion 1.1.0）
specs-eval/     字节复用（golden×4 + bad×6 + demo-zh + spike-manifest + 素材）
scripts/        build.mjs / verify-reused-assets.mjs / gate_*.mjs / e2e-matrix / diff/
docs/specs/     模块资产 spec 地图（每模块 = spec + eval 双交付）
docs/diff/      差分报告（成品终审证据）
```

## 已接通（仓库内可复现，全部真实执行 exit 0）

- **一条命令全流水线**：`node pf/pf.mjs make` = 校验 → 素材管线（assetkit，`--no-assetkit`
  逃生口）→ 模板构建（三消/合成/拔针/排序四模板，真实可玩单 HTML）→ 按渠道规则库打包 →
  判官 `--autoplay` 自动试玩到胜利结束页 → 汇总页 + 局域网二维码 + 墙钟计时 +
  `artifacts/demo-prebuilt/` 兜底；质检不过即 exit 1
- **规格驱动**：PlayableSpec JSON（schema v1 + 不变式 I1–I5，`@pf/spec` 单源）；
  `node pf/pf.mjs validate`，specs-eval/bad 6 坏样本全拒且错误定位到字段路径
- **四模板全矩阵**：4 golden × {en,zh} × 6 冻结渠道 = 48 包全量构建→打包→逐包判官
  质检 0 FAIL（`npm run matrix`；gate-m2 门项）
- **六渠道打包**：AppLovin/Meta 单 HTML；Mintegral zip；Google/Unity zip；
  TikTok/Pangle zip（js-sdk 桩），各带 pack-manifest 旁车
- **素材管线（assetkit）**：压图四编码竞标（永不增大）+ ffmpeg AAC + 字体子集 + 图集；
  make 默认接线 `PF_ASSET_OPTMAP`（模板命中即内联优化产物，旁车记 `source=assetkit`）；
  selftest 实测 21,497,003B→163,548B（降 99.24%）；demo 素材 893B→402B（降 54.98%，
  与 oracle 同值）
- **网页操作台（webui）**：浏览器选模板/传 PNG/填文案（或传 spec JSON）→ make 任务 →
  状态轮询 → 二维码 + 质检报告 + 渠道包下载；match3 seed 可解性预检与 pullpin 顺序复核
  复用 `@pf/spec` 单源；端到端 selftest 30 断言
- **自动质检（qacore）**：包体上限、外网请求拦截、首点前静音、横竖屏、文案与替换素材
  上屏（CHK10）等；未实装项如实标 skip，不算通过

## 预留 / 未做（如实登记，禁止按已接通引用）

- **模板 optmap 接线缺口**：merge/pullpin/sort 三模板未接 `PF_ASSET_OPTMAP`，直读原素材
  内联——assetkit 的优化对这三模板不生效（仅 tmpl-match3 接线）。这是 oracle 原状
  （oracle 仅 tmpl-match3/build.mjs:43-61 有接线），非 factory 移植引入的回归。
- **webui sort 模板入口未开放**：模板本体在 make 层可用，但操作台表单未入表
  （oracle specgen.py:32 TEMPLATES 仅 match3/merge/pullpin，oracle README 自认
  "待 specgen 注册后开放"——factory 保持同口径）。
- **pf 占位子命令 build/pack/rules-check**：exit 2 回显"尚未实现"（两侧行为对称的占位，
  占位语义本身是契约；全流水线统一走 make）。
- **演示/golden spec 声明素材大半不存在**：golden-match3 等声明的 `assets/theme-a/*`
  （sprites×6/audio×2/bg/font）在两仓均无对应文件，仅 demo-zh 的 piece-0.png 真实存在；
  缺失素材走"回退程序化贴图"（构建脚本 design 如此，告警不失败）——已知边界，不是管线 bug。
- **qacore 两项检查未实装**：CHK02 文件数、CHK06 退出接口，各渠道报告如实记 skip。
- **MODEL-ADAPTER（llmgw）**：网关壳在 `packages/llmgw/`，无生产调用方（oracle 同状：
  离线 mock 自测过、director 未开工）。
- **AI 生成（director）、截图/录屏生成试玩、Cocos 工程接入**：未实现（oracle 同状）。

数据资产字节复用登记：**REUSED-ASSETS.md**（39 项已与 oracle 逐项 sha256 比对一致）。
开发纪律：**AGENTS.md**（可擦除语法、单栈、零上游名、数据契约零变更、坑 4/5/14/16）。
