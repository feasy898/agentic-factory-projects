# 整仓再生手册（REGENERATE）

> 目标：新 agent 只凭本手册 + 各 spec，在干净机器上从零重建全部已实现模块并通过验收门。
> 所有命令在**仓库根**执行（另有注明除外）；全部通过线均为 2026-09-28 实测值。

---

## 1. 环境准备（实测版本，钉版即契约）

| 件 | 实测版本 | 说明 |
|---|---|---|
| OS / Shell | Windows Server 2022 + Git Bash | 路径含中文——见 §7 坑 1 |
| Node | **v22.23.2**（要求 ≥22） | 原生 TS 类型剥离（`--test`/`.ts` 直载）；包管理 npm 10.x |
| Python | **3.12.10** | venv 固定在 `python/.venv` |

```bash
# Node 侧：根工作区（workspaces = packages/* + packages/templates/*，勿漏 templates）
npm ci          # devDependencies 钉版：ajv 8.20.0 / c8 12.0.0 / esbuild 0.28.2 / jsdom 30.1.1 / sharp 0.35.5 / typescript 7.0.2

# Python 侧：venv + 钉版依赖 + 可编辑安装（勿用 .pth hack）
python -m venv python/.venv
python/.venv/Scripts/python.exe -m pip install -r python/requirements.txt
#   钉版：playwright 1.63.0 / fastapi 0.141.1 / uvicorn 0.54.0 / httpx 0.28.1 / pydantic 2.13.5 /
#         jsonschema 4.26.0 / pillow 12.3.0 / fonttools 4.66.0 / qrcode 8.2（清单末尾另有一个规划遗留的
#         LLM SDK 条目，llmgw 实际零依赖它——收紧时清理）
python/.venv/Scripts/python.exe -m pip install -e python/     # pyproject packages = ["pfcore","qacore"]
python/.venv/Scripts/python.exe -m playwright install chromium # qacore 必需
```

- 网络受限时 pip/npm 选国内镜像；Node ≥22 的 `.ts` 直载与 `import ... with { type: "json" }` 是硬依赖，勿降级。
- 无浏览器环境跑不了 qacore（playwright chromium 需先安装）。

## 2. 模块重生成顺序（依赖图即拓扑序）

```
1 M1-spec → 2 M2-engine-bridge → 3 规则库(JSON) → 4 M4-packager → 5 M3-tmpl-match3
→ 6 llmgw(可与 3-5 并行) → 7 M8-qacore → 8 验收门 → 9 编排器(下一个缺口，planned)
```

每步的"验收命令 → 通过线"：

| 步 | 模块 | 验收命令 | 通过线 | spec |
|---|---|---|---|---|
| 1 | M1 | `python/.venv/Scripts/python.exe -m pfcore validate specs-eval/golden-match3.json`；`... validate "specs-eval/bad/*.json"`；`node packages/spec/test/ajv-check.mjs` | golden exit 0；bad 6 个全 exit 1 含 `$.` 路径；ajv PASS | [spec-contract](specs/spec-contract.md) |
| 2 | M2 | `node packages/engine-bridge/test/run.mjs`；`npm run coverage -w @pf/engine-bridge`；`npm run typecheck -w @pf/engine-bridge` | 26 用例过；行覆盖 ≥80%；tsc 干净 | [engine-bridge](specs/engine-bridge.md) |
| 3 | 规则库 | `node packages/packager/bin.mjs channels` | 结构校验过，列出 preview/applovin/meta/mintegral | [channel-adapters](specs/channel-adapters.md) |
| 4 | M4 | `node packages/packager/test/run.mjs` | 全断言过（含 zipfile 交叉验证、可复现、负向 3 条） | [packager](specs/packager.md) |
| 5 | M3 | `node packages/templates/tmpl-match3/build.mjs --spec specs-eval/golden-match3.json --out artifacts/preview/match3.html`；`npm run typecheck -w @pf/tmpl-match3` | 产物 ~1.24MB 零外链；tsc 干净 | [templates](specs/templates.md) + [规则卡](specs/match3-rules-card.md) |
| 6 | llmgw | `python/.venv/Scripts/python.exe -m llmgw.selftest`（cwd=python/ 亦可） | SELFTEST PASS，6/6 | [llmgw](specs/llmgw.md) |
| 7 | M8 | `python/.venv/Scripts/python.exe -m qacore run artifacts/preview/match3.html --channel preview --autoplay` | exit 0；pf:end ≤45000ms（实测 ≈26.6s） | [qacore](specs/qacore.md) |
| 8 | 门 | 见 §3 | — | — |

## 3. 全仓验收（gate 脚本）

```bash
python scripts/gate_phase1.py    # 公开环境主验收：GATE PHASE1: PASS（4/4），实测 ≈46s
python scripts/gate_phase0.py    # 本机门禁：GATE PHASE0: PASS（5/5），实测 ≈6s
```

- **gate_phase1 门项**：M1 三连（golden/bad/ajv）+ M2 测试 + M4 三渠道断言（大小/结构/零外链/注入/禁用，
  `pack-manifest.json` 不计包内）+ M3 构建后 autoplay 全过且 pf:end ≤45s。产物写 `tmp/gate-phase1/`
  （先清后跑）。
- **gate_phase0 门项**：pfcore/packager CLI 骨架、llmgw 自测+零厂商端点扫描、qacore 夹具 mini.html，
  以及**门项 3 = 本机对照 spike 六渠道产物**（依赖 `_vendor/NOTES.md` 与 `_vendor/spike/dist/*`，
  仅本机存在、`.gitignore` 覆盖）。**公开克隆环境门项 3 必 FAIL——公开环境以 gate_phase1 为准**（如实记录）。
- 一次性全链（更细粒度）：按 §2 表逐行跑。

## 4. 替换/重生成模块时的回归清单

| 被替换模块 | 必跑回归 | 额外人工检查 |
|---|---|---|
| M1 schema/不变式 | 门项 1 全部 + 双侧一致性（Python/JS 同判） | bad 样本是否仍各自击中原检查项；CONTRACTS 痛点候选是否被影响 |
| M2 桥 | 26 用例 + coverage + 门项 4（CHK04 静音链路真机语义） | 事件 detail 表无删改；退出路由单次锁语义 |
| M3 三消 | 门项 4 + 规则卡 §12 缺口清单复核 | nearWin 仍单次触发；pf:end 时长无明显回退；包体 ≤5MB |
| M4 打包器 | 自验收 22+ 断言 + 门项 3 | 重复构建字节一致仍成立（zip 时间戳）；零外链正则未被放松 |
| 规则库 | M4 自验收 + 门项 3 + qacore CHK01 | 新数值与 channel-adapters 表一致 |
| llmgw | selftest + gate_phase0 门项 4 扫描 | env 默认值表未漂移 |
| M8 质检 | gate_phase0 门项 5 + gate_phase1 门项 4 | 魔法数字表未漂移（改任一数字须回填 qacore spec §3） |

通用纪律：门禁/测试**先清旧产物再跑**（存在=本次真事实）；任何模块替换后先跑 `gate_phase1` 再提交。

## 5. 再生试验 SOP（标准操作——验证"spec+eval 可再生"资产主张）

> 首例试验（2026-09-28，M2 engine-bridge）：全新实现者（未读过原实现的 Fresh Flash 实例）只凭
> docs/assets spec + 冻结测试重建，**首跑 26/26 全绿、覆盖率 96.3%**——资产主张成立。
> 试验回炉产出三件（均已入库）：① coverage 脚本根相对 include 的"空过"bug 修复（§7 坑 16）；
> ② engine-bridge.md 补时序约束/告警文案/locale 空串回退；③ 本 SOP。

标准操作（每个模块的再生试验都按此执行）：

1. **隔离**：建独立工作目录，拷入 `docs/assets/` 全部 spec + 被测模块的 `test/`（含夹具/testsupport，
   **冻结一字不改**）与 package.json 骨架；**不拷贝原实现 `src/`**。
2. **环境前置由 spec 声明（第二批试验教训，硬性条款）**：冻结测试对目录形状/根路径反推/junction/
   venv glue/node_modules 依赖的一切假设，必须**事先写进该模块 spec**（范例：packager.md §6 测试环境前置）；
   **禁止实现者自创 junction/venv glue 或临时挪文件凑路径**——工作流门因环境假设瞬时失败的，判 spec 缺口，
   回炉补 spec，而不是记实现失败。
3. **盲实现**：实现者只准看 spec 与冻结测试，明确禁止看原实现；允许跑测试自验。
3. **裁定**：跑模块自验收 + coverage + 门禁相关门项；判据 = 冻结测试全绿 + 通过线达标
   （coverage 门另验：故意压低于线必须 exit 1，防"空过"）。
4. **缺口回炉**：实现的 bug → 修原实现/包脚本；spec 歧义或缺失（实现者靠测试反推的点、环境假设未成文）→
   补 spec；流程问题 → 改本 SOP。三类各自单独 commit。
5. **记录**：试验结果（模块/日期/首跑结果/回炉清单）追加到本节与 §9 变更史。

已登记试验：

| 批次 | 日期 | 模块 | 结果 | 回炉清单 |
|---|---|---|---|---|
| 1 | 2026-09-28 | M2 engine-bridge | 首跑 26/26 全绿，覆盖率 96.3%（通过） | coverage include 路径 bug 修复；spec 补时序/告警/locale 回退；本 SOP 建立 |
| 2 | 2026-09-28 | M6 llmgw | 盲实现再生成功 | spec 补 schema 序列化形态/attempts 0 基与退避关系/错误类型速查/json_of 非 dict/模块级 chat() 参数表/最小 eval 环境 |
| 2 | 2026-09-28 | M4 packager | 自测 3 次过；工作流门一次瞬时失败后主会话复跑 3 次全绿——**判定通过，暴露环境脆弱性** | spec 补：规则库三渠道内容全量、golden 夹具内容、**测试环境前置成文（run.mjs 路径假设/esbuild/venv SKIP 语义）**、manifest zip 形状与 specVersion 位置、MRAID 大小写与 maxFiles 语义；exit code 统一；SOP 增环境前置硬性条款 |

## 6. 演示兜底（demo-prebuilt）

规划要求 `artifacts/demo-prebuilt/` 存最后一次全绿产物（`artifacts/` 整体 gitignore，不入库）——
**当前仓库无此目录（如实记录，未实现）**。落地方式待编排器里程碑定（库内提交 or 发布附件）；
在那之前，全绿产物的人工留存是演示日的前置条件。

## 7. 文档与资产自检

- 本资产包（docs/assets/）随代码演进：模块状态变化 → 改 manifest.json/md；契约变更 → 走 CONTRACTS §变更流程。
- 公开仓纪律自查（每次发布前）：对内部红线词表（引擎/字体/素材包/模型的上游名）做大小写不敏感 grep，
  要求零命中；`_vendor/` 不入库。

## 8. 已知坑清单（构建过程实测，重生成必读）

1. **中文路径 × 图像库**：仓库绝对路径含中文；cv2 系 `imread/imwrite` 在 Windows 非 ASCII 路径下失败，
   须 `np.fromfile + cv2.imdecode`（或如 qacore 用 Pillow）。任何新图像工具链先过这一关。
2. **渲染引擎版本锚点 3.88.2**：vendor bundle 由引擎 ESM 发行文件经 esbuild
   （`--bundle --minify --format=esm --legal-comments=none --target=es2019`）+ token 级改名产出（约 1.2MB）；
   公开仓 grep 引擎原名必须零命中；升级 = 重跑 vendor 流程 + qacore 回归。jsdom 无 2D/WebGL——引擎只能
   冒烟加载，真实验证只有 qacore（真实 Chromium）。
3. **mintegral zip 结构**：包内是 `build.js + Template.html`（入口 Template.html 相对引用 build.js）——
   Phase 0 对照工程实测修正，勿按"单 HTML"假设；规则库、打包器、门禁三处一致。
4. **Node `--test` 目录参数**：Windows Node 22 不展开目录 → engine-bridge 需 `test/index.js` 进程内装载入口；
   `run.mjs` 用 `NODE_TEST_CONTEXT` 防递归自举。
5. **TS 可擦除语法**：Node 类型剥离不支持构造器参数属性（`ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`），
   一律显式 `this.x = x`；import 带 `.ts` 扩展 + `allowImportingTsExtensions`。
6. **zip 可复现**：固定 DOS 时间戳（2026-01-01）是"重复构建字节一致"断言的前提；动 zip.mjs 时间字段必炸自验收。
7. **内联 spec JSON**：必须 `escapeForInlineScript`（`<`/`>`/U+2028/9 转义），防 `</script>` 提前闭合。
8. **qacore 探针只注入一次**：`add_init_script` 每页面一次，重复包装 AudioContext 会让 running 计数失真；
   竖/横两趟各建新 context（隔离静音态与请求记录）。
9. **Windows 编码**：门禁对子进程统一注入 `PYTHONUTF8=1`；pfcore/gate 入口 `reconfigure(encoding="utf-8")`
   （GBK 控制台中文乱码）。
10. **pfcore schema 定位**：env `PF_SPEC_SCHEMA` 可覆盖；默认经 `validation.py parents[2]` 找仓库根——
    **模块目录不可挪**。pfcore/qacore 靠 `pip install -e python/`，勿回退 .pth hack。
11. **qacore 仅收 .html**：zip 渠道产物当前无法质检（已知缺口）；产物不存在/非 html → exit 2。
12. **packager dist 优先级**：存在 `<dist>/<locale>/index.html` 则基准目录切到该子目录；`type=module` 外链脚本
    会告警（合并后 import/export 失效），dist 必须自包含。
13. **landingUrl 白名单**：spec 落地页是产物唯一允许外链——改 golden 的 landingUrl 要同步 gate 断言。
14. **npm workspaces**：必须同时含 `packages/*` 与 `packages/templates/*`（Phase 0 实测教训）。
15. **占位子命令语义**：pfcore build/pack/rules-check exit 2 是当前契约的一部分，不要"顺手实现"而不改
    pipeline-contract。全流水线命令名 2026-09-28 裁决为 `make`（已实现；占位 `run` 已删除，勿复活）。
16. **coverage include 必须包内相对**：npm workspaces 的 `npm run -w <pkg>` 在**包目录**下执行脚本，
    c8 `--include` 写 monorepo 根相对路径会匹配 0 文件 → 0% 覆盖仍 exit 0（"空过"，2026-09-28 再生试验
    发现并修复）。验证门有效性的方法：临时把 `--lines` 抬到必失败值跑一遍，必须 exit 1。

## 9. 本资产包的变更史指针

| commit | 内容 |
|---|---|
| `e55f9e8` | manifest（逻辑模块重组） |
| `3685725` | 六件优先级 spec |
| `270bd76` | 周边逻辑模块 spec |
| （本文件与 CONTRACTS 所在 commit） | 再生手册 + 契约汇总 |
| （再生试验回炉 commit） | engine-bridge 再生试验回炉：coverage 空过 bug 修复 + spec 时序/告警/locale 补齐 + 再生试验 SOP |
| `8e6782d`…`e50abdf` | 模块本体构建史（pfcore/qacore/llmgw/gate0/spec/bridge/packager/tmpl-match3/gate1） |
