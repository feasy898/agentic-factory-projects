# 资产包总表（manifest）

> 本表按**逻辑模块**组织。已冻结的代码结构不动，物理位置逐行标注。
> 每模块一行：模块ID / 名称 / 语言形态 / 职责 / 冻结契约 / 依赖 / eval 命令与通过线 / 重生成顺序位 / 状态。
> 详细契约汇总见 [CONTRACTS.md](CONTRACTS.md)；整仓再生手册见 [REGENERATE.md](REGENERATE.md)；逐模块 spec 在 [specs/](specs/)。
> 所有 eval 命令在仓库根执行，均已在 2026-09-28/29 分批实测通过。

## 状态图例

| 状态 | 含义 |
|---|---|
| `frozen` | 已实现且验收全绿；契约冻结，改动视为破坏契约 |
| `frozen-prototype` | 雏形已冻结可复验；全量（其余检查项/变异测试）在后续里程碑 |
| `partial` | 部分子命令 frozen，其余为占位（占位语义 = exit 2） |
| `planned` | 未开工；有 spec 草案或明确开工前置 |
| `deferred` | 明确暂缓；只有边界说明页，**不写可重生 spec** |

## 核心模块（5）

| 模块ID | 名称 | 语言/形态 | 职责（一句话） | 冻结契约 | 依赖 | eval 命令 → 通过线 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|---|---|
| `M1-spec` | 规格（PlayableSpec v1 + 双侧校验器） | JSON Schema draft 2020-12 + TS 类型 + Python（jsonschema/pydantic）+ JS（ajv） | 一份 JSON 描述玩法/素材/流程/文案/渠道/质检预算，校验错误定位到字段路径 | `packages/spec/playable-spec.schema.json`（specVersion 恒 1.0.0）+ 五条不变式 I1–I5 + 错误形状 `{path,message,code}` | — | `python/.venv/Scripts/python.exe -m pfcore validate specs-eval/golden-match3.json` → exit 0；`... validate "specs-eval/bad/*.json"` → 6 个全 exit 1 且含 `$.` 路径；`node packages/spec/test/ajv-check.mjs` → exit 0 | 1 | frozen | [spec-contract](specs/spec-contract.md) |
| `M2-engine-bridge` | 运行时桥 | TS（零 npm 运行时依赖） | window.PF + 5 个 pf:* 事件 + 6 渠道退出路由 + 首交互前强制静音与平台音量跟随 | window.PF 成员表；事件 detail 表；退出路由表（mraid.open / FbPlayableAd.onComplete / ExitApi.exit / openAppStore / window.open 回退） | — | `node packages/engine-bridge/test/run.mjs` → 26 用例全过；`npm run coverage -w @pf/engine-bridge` → 行覆盖 ≥80% | 2 | frozen | [engine-bridge](specs/engine-bridge.md) |
| `M3-templates` | 模板插件（四模板：match3/merge/pullpin/sort） | TS + 渲染引擎 vendor bundle（单 IIFE） | spec 驱动渲染可玩广告：教程→游玩→结束页 + attract + `__PF_QC__` 真实最优步 | 构建内联 `window.PF_SPEC`+`PF_LOCALE`+`PF_ASSETS`；QC 钩子 `hint()/state()/endScreenVisible()/texts()/textStates()/assets()`；各玩法精确定义 = 规则卡 / 各模板 README | M2, M1 | `node packages/templates/tmpl-match3/build.mjs --spec specs-eval/golden-match3.json --out artifacts/preview/match3.html` → exit 0；`python/.venv/Scripts/python.exe -m qacore run artifacts/preview/match3.html --channel preview --autoplay` → exit 0 且 pf:end ≤45000ms；merge/pullpin/sort 同形态（`specs-eval/golden-{merge,pullpin,sort}.json`） | 5 | frozen（四模板） | [templates](specs/templates.md) · [match3 规则卡](specs/match3-rules-card.md) |
| `M4-packager` | 打包器 | Node ESM CLI（零第三方运行时依赖） | dist + spec + 规则库 → 渠道包：单 HTML 全内联或规则声明 zip；强制零外链/大小/结构，宁失败不出超规包 | 输出 `<out>/<projectId>/<channel>/<locale>/`；白名单外零外链；字节可复现（固定 zip 时间戳）；`pack-manifest.json` 旁车 | M1, 规则库 | `node packages/packager/test/run.mjs` → 全部断言过（三渠道 + zipfile 交叉验证 + 可复现 + 负向 3 条全拒） | 4 | frozen | [packager](specs/packager.md) |
| `M8-qacore` | 质检器 | Python + Playwright + Pillow | 无头唯一裁判：本地伺服、双视口、请求拦截、真实指针自动试玩到结束页，report.json，FAIL 即 exit 1 | CHK01/03/04/05/07/08/09/10 实装判定（CHK10=指定文案与替换素材上屏，2026-09-29）；报告字段清单；魔法数字表（方差 30 / 64×64 / 拖拽 44px×4 步 / 视口 390×844） | M1, 规则库, M3 | `python/.venv/Scripts/python.exe -m qacore run python/qacore/tests/fixtures/mini.html --channel preview` → exit 0；`... run artifacts/preview/match3.html --channel preview --autoplay` → exit 0 且 pf:end ≤45s；`python -m pfcore make --spec specs-eval/demo-zh.json` → exit 0 且 CHK10 pass（中文文案命中+piece-0 像素对账） | 7 | frozen-prototype（**正在收紧中，以 eval 为最终真源**） | [qacore](specs/qacore.md) |

## 合并逻辑模块（2）

| 模块ID | 名称 | 组成 | 职责（一句话） | 依赖 | eval 命令 → 通过线 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|---|
| `MODEL-ADAPTER` | 模型适配器（原 M6+M7+M11） | llmgw 单库（frozen）+ director（暂缓）+ repair-loop（暂缓） | chat-completions 通用客户端：超时/重试/降级/图片/JSON 模式，全 env 驱动零厂商硬编码；两个调用方暂缓 | — | `python/.venv/Scripts/python.exe -m llmgw.selftest` → 6 项 mock 全过 SELFTEST PASS；零厂商端点硬编码 | 6 | llmgw frozen（**正在收紧中**）；director/repair-loop deferred | [model-adapter](specs/model-adapter.md) · [llmgw](specs/llmgw.md) |
| `ORCHESTRATOR` | 编排器（原 M9+M10） | pfcore CLI（主体）+ webui 操作界面 | 一条命令串联 校验→构建→打包→质检→汇总/二维码；网页只是上传与二维码壳 | M1, M3, M4, M8, M5 | `python/.venv/Scripts/python.exe -m pfcore validate specs-eval/golden-match3.json` → exit 0；`python -m webui.selftest` → exit 0（httpx 端到端，实测 68.3s）；占位子命令 → exit 2（占位语义即当前契约） | 9 | partial（validate/make/serve frozen；build/pack/rules-check 占位；webui frozen，commit `116d9e1`） | [orchestrator](specs/orchestrator.md) · [流水线契约](specs/pipeline-contract.md) |

## 数据文件与 eval 资产（非模块）

| ID | 名称 | 形态 | 职责 | eval → 通过线 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|
| `DATA-channel-rules` | 渠道规则库 | JSON（`channel-rules/channel-rules.json`，rulesVersion 1.1.0） | 渠道合规知识单一来源：包形态/结构/大小线/退出接口/静音要求；打包器配置来源、质检 CHK01 上限来源 | `node packages/packager/bin.mjs channels` → 结构校验过并列出渠道 | 3 | frozen（六投放渠道 applovin/meta/mintegral/google/unity/tiktok + preview 共 7 渠道，T2.4） | [channel-adapters](specs/channel-adapters.md) |
| `EVAL-gate-phase0` | Phase 0 验收门 | `scripts/gate_phase0.py` | 6 项验收固化：CLI 子命令+最小成功/失败命令、spike 六渠道按入库期望清单（specs-eval/spike-manifest.json，本机无对照工程标 SKIP-ENV）、llmgw selftest 解析 6 条 [PASS]、qacore skip 不算过（CHK03/08/09 必须 pass）+ 三变异样本恰好命中、超时按进程树清理 | `python scripts/gate_phase0.py` → `GATE PHASE0: PASS（6/6）`（实测约 25s） | 8 | frozen（**正在收紧中，以实际运行为最终真源**） | [REGENERATE](REGENERATE.md) |
| `EVAL-gate-phase1` | Phase 1 验收门 | `scripts/gate_phase1.py` | 4 项验收固化：M1 三连 / M2 测试 / M4 三渠道断言 / M3 自动试玩 | `python scripts/gate_phase1.py` → `GATE PHASE1: PASS（4/4）`（实测约 46s） | 8 | frozen | [REGENERATE](REGENERATE.md) |
| `EVAL-gate-phase2` | Phase 2 总验收门 | `scripts/gate_phase2.py` | 5 项验收固化：gate_phase0/1/mainpath 三门真实子进程回归 exit 0 / e2e_matrix 全量 `--budget-sec 1200` exit 0 且读 summary.json 双重对账 totals={pass:48,fail:0,skip:0}/mode=full / 中性名扫描 | `python scripts/gate_phase2.py` → `GATE PHASE2: PASS（5/5）`（2026-09-29 实测总墙钟 656.1s，其中 e2e 全量 48 包 422.8s 0 fail） | 8 | frozen | [orchestrator](specs/orchestrator.md) |

## 重生成依赖图（顺序位即拓扑序）

```
M1-spec(1) ──┬────────────────────────────┐
M2-bridge(2) ┼──► M3-templates(5) ──┐     │
规则库(3) ───┼──► M4-packager(4) ───┼──► M8-qacore(7) ──► gates(8) ──► ORCHESTRATOR(9)
llmgw(6，与 3-5 并行)              │
M5-assetkit(10，已实现，make 默认接线)
```

- 1→2→(3,6)→4→5→7→8→9 均已实现（9 = pfcore make/serve + webui；build/pack/rules-check 仍为占位）。
- 公开环境验收以 `EVAL-gate-phase1` 为准；`EVAL-gate-phase0` 门项 3 对照产物仅本机存在（`_vendor/`，不入库），缺失时该项标 SKIP-ENV 不算失败——期望清单已入库（specs-eval/spike-manifest.json），任何机器可按其重建对照轨并复验。全量终验 = `EVAL-gate-phase2`（48 包矩阵门，gate_phase0/1/mainpath 回归 + 中性名扫描）。
