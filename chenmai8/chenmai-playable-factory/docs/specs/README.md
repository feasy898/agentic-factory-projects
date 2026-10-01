# docs/specs/ — 模块资产 spec 地图（每模块双交付之一）

纪律（决策 §5）：**每个模块 = 资产 spec + 冻结/移植 eval 双交付**。
oracle `repo/docs/assets/specs/`（12 件）是**唯一规格源**（封存只读）；各模块批次开工时
以对应 spec 为准重实现，spec 缺口按资产流程回填 oracle docs/assets（资产包是活资产）；
`contract-change:` 类回填（如 CONTRACTS 痛点 8）单独 commit。

| 模块 ID | oracle 规格源（repo/docs/assets/specs/） | factory 落位 | 状态 |
|---|---|---|---|
| M1-spec | `spec-contract.md` | `packages/spec/`（校验器本体） | **M1.2a 已落**（TS 单源校验器，[spec.md](spec.md)：冻结 ajv-check 原样过 exit 0 + 11 件裁定矩阵与 oracle 双侧全等 + 算例逐值 + tsc strict；差分证据 artifacts/diff/M1.2a-spec-eval.json） |
| M2-engine-bridge | `engine-bridge.md` | `packages/engine-bridge/` | **批次 1 完成（M1.2b）**（spec 字节落位本目录；冻结 26 用例 exit 0 + c8 行覆盖 97.6%≥80%（--lines=100 门真实性已验）+ tsc strict 过） |
| M3-templates ×4 | `templates.md` + `match3-rules-card.md` | `packages/templates/tmpl-*` | **批次 2 完成（M2.1）**（spec 字节落位本目录 #34–#35；四模板按规则卡+templates.md 全新实现，冻结 logic-test 字节复用 exit 0 + tsc strict + 构建 exit 0；M2.1 的 oracle qacore 临时验收已按计划换成 M2.2 本判官复验全绿；复验回修：引擎 WebAudio 启动期创建 AudioContext 在 autoplay 授予时形成首交互前 running 的真实违规，四模板改引擎原生 `audio:{noAudio:true}` 关闭，音效仍走 PF.audio） |
| M4-packager | `packager.md` | `packages/packager/` | **批次 1 完成**（spec 字节落位本目录；46 断言冻结 eval + 六渠道结构断言 exit 0） |
| M5-assetkit | `assetkit.md` | `packages/assetkit/` | **已落地（成品切换批次，2026-09-30）**（[assetkit.md](assetkit.md) 改写落位；oracle 全四能力语义移植：压图 sharp 四候选竞标（子进程助手→进程内）+ ffmpeg AAC + 字体子集 subset-font(harfbuzzjs)（TTC 成员 0 抽取，宿主差异登记）+ shelf 图集；`pf make` 默认接线 `PF_ASSET_OPTMAP`（仅 tmpl-match3 消费——oracle 原状）；`--no-assetkit` 逃生口。eval：selftest 9 断言 exit 0（`npm run test:assetkit`，实测 21,497,003B→163,548B 降 99.24%，oracle 同表 99.23%）+ 单测 7 件并入 npm test + make 接线实测 demo piece-0.png 893B→402B（降 54.98%，与 oracle 登记值逐位一致）+ CHK10 像素对账过） |
| M8-qacore | `qacore.md` | `qacore/` | **批次 2 完成（M2.2）**（spec 字节落位本目录 #38；Node+playwright 1.63.0 移植：探针/手势表/魔法数字/十项检查/报告逐字段；PROBE_JS 与 oracle 逐字节一致；mini.html 夹具字节复用 #39；MUT-01/02/04 构造算法逐条照搬恰命中；eval：unit 10 + 浏览器 5 + 四模板 5 全 exit 0，`npm run test:qacore`；R1 方差对齐 Pillow ≤0.04%；MUT-03 仍列后续） |
| MODEL-ADAPTER | `model-adapter.md` / `llmgw.md` | `packages/llmgw/` | 批次 1 待做 |
| ORCHESTRATOR | `orchestrator.md` + `pipeline-contract.md` | `pf/` | **批次 2 完成（M2.3，编排 CLI；assetkit/webui 已于成品切换批次接入）**（spec 字节落位本目录 #40–#41；`node pf/pf.mjs` validate/make/serve 子命令/旗标/退出码/产物树全对齐 oracle pfcore——validate 11 件与 oracle 同判；make 全链：构建→打包→判官 --autoplay→汇总页双名+LAN 二维码+墙钟双口径+demo-prebuilt，质检 fail 即 exit 1 不产出二维码；serve 前台伺服+现场重建汇总页/二维码+端口顺延；8618 顺延/TCP-only 健康检查/伺服复用三重核实（PID 映像名按宿主钉 node*）/二维码 LAN IP 段优先级全保；宿主适配两处已登记：静态伺服 python→node 分离子进程、serve 停机增 stdin-EOF 等价钩子（Windows 无跨进程 SIGINT）；build/pack/rules-check 占位 exit 2 原样保契约。eval：pf/test/pf.test.mjs 13 件 + make-serve.test.mjs 2 件真实执行 exit 0（`npm run test:pf`）+ e2e-matrix.mjs 48 包全矩阵 0 FAIL ≤1200s（gate-m2 门项 3）） |
| M10-webui | —（oracle 内 webui/） | `webui/` | **已落地（成品切换批次，2026-09-30）**（[webui.md](webui.md) 改写落位；FastAPI→node:http 单进程 + 自写 multipart 负向测试 + specgen（I3 预检/pullpin 实算复核复用 @pf/spec 单源）+ 单页零外链 + /artifacts 挂载伺服；sort 未入表为 oracle 原状（登记根 README 预留栏）。eval：单测 17 件并入 npm test + 端到端 `npm run test:webui` 30 断言 exit 0（实测 99.0s：两模式 done、质检 0 fail、pf:end win、链接/二维码/3 渠道包逐个 200、负向 400）） |
| CHANNEL-ADAPTERS | `channel-adapters.md` | `channel-rules/`（字节复用已完成）+ 各处实现 | 数据资产已复用；规则库消费端实现随 M4 落地（rules.mjs 配置驱动） |
| PIPELINE-CONTRACT | `pipeline-contract.md` | 全局契约（报告字段/退出码） | 冻结，全程对齐 |

各模块 spec 落地时，把（改写后的）spec 文档放进本目录并更新状态列。
