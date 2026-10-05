# Workflow Proposal —— 构建阶段任务分解（供主会话构建工作流调度）

> 每个任务 = 交给 GLM-5.3-Flash 子代理的一条可执行指令（实现 + eval）。规格来源：plan\开发指令.md §4-§8。
> 标注：〔关键路径〕= 阻塞下游；〔可并行〕= 与同组任务无文件冲突；验收 = 对应 EVAL 全过。

## Phase 0 · D1 骨架与跑通（全部完成才进 Phase 1）

| 任务 | 内容 | 验收 | 依赖 |
|---|---|---|---|
| T0.1 〔关键路径〕 | 建仓 pf\（§3 布局）+ venv + npm workspaces + requirements 锁定 + scripts\ 骨架 | `python -m pfcore --help`、`node packages\packager\bin.mjs --help` 可运行（空实现） | — |
| T0.2 〔关键路径〕 | spike：clone smoud 模板+安装 sdk/scripts@钉版，跑通 6 渠道出包，记录全部 commit/版本到 _vendor\NOTES.md | 6 包存在；记录完整 | T0.1 |
| T0.3 〔可并行〕 | M6 llmgw 完整实现（含 mock 自测） | `python -m llmgw.selftest` PASS + 零硬编码 grep | T0.1 |
| T0.4 〔可并行〕 | M8 qacore 骨架：起 Playwright、本机伺服、截屏、外网拦截、报告 JSON 骨架 | 对任一本地 HTML 产出 report.json | T0.1 |

## Phase 1 · D2 契约与首条链

| 任务 | 内容 | 验收 | 依赖 |
|---|---|---|---|
| T1.0 〔关键路径〕 | 工程正规化（Phase 0 备忘落实）：workspaces 纳入 packages\templates\*（或模板独立处理）；pfcore 去 .pth hack，改 pip 可编辑安装；README 安装步骤可复现 | 全新 venv 按 README 安装后 `python -m pfcore --help` 可用 | Phase 0 |
| T1.1 〔关键路径〕 | M1 schema v1 + pydantic/ajv 双校验 + 6 个 bad 样本 | M1 EVAL 全过 | T0.1 |
| T1.2 〔关键路径〕 | M2 engine-bridge（PF 全局、事件、静音、6 渠道退出 stub） | M2 EVAL 全过 | T1.1(类型) |
| T1.3 〔可并行〕 | M4 packager 主轨：esbuild + 单 HTML 内联 + channel-rules.json(applovin/meta/unity=单HTML；google/tiktok/mintegral=zip) | match3 占位工程→applovin 包 ≤5MB 零外链 | T0.2 |
| T1.4 〔关键路径，T1.1 后〕 | match3 模板 v1（含 __PF_QC__、attract、教程）+ golden-match3 spec | 模板 selftest：pf:end 45s 内 | T1.1,T1.2 |

## Phase 2 · D3-D4 扩张

| 任务 | 内容 | 验收 | 依赖 |
|---|---|---|---|
| T2.1 | merge 模板 + golden spec | 模板 EVAL | T1.4 模式 |
| T2.2 | pullpin 模板（含可解性校验进 M1 validator）+ golden spec | 模板 EVAL | 同上 |
| T2.3 〔可并行〕 | M5 assetkit 全量（压图/音频/字体子集/图集） | M5 EVAL（-30% 字节） | T0.1 |
| T2.4 〔可并行〕 | packager 补 google zip + tiktok(config.json) + mintegral zip（build.js+Template.html 结构，Phase 0 实测） | M4 EVAL 6 渠道 | T1.3,T0.2 |
| T2.5 〔可并行，D4〕 | M7 director 演示级（依赖 llmgw 真实 key 的部分由主会话手测） | M7 EVAL ≥3/5 | T0.3,T1.1 |

## Phase 3 · D5-D6 质检闭环与全矩阵

| 任务 | 内容 | 验收 | 依赖 |
|---|---|---|---|
| T3.1 〔关键路径〕 | qacore 10 检查全量 + 变异测试 mutant×10 | M8 EVAL：金标 PASS + 变异 10/10 | T0.4,T1.4 |
| T3.2 〔可并行〕 | M11 repair-loop（bounded 2 轮，参数级） | M11 EVAL 注入故障可修复 | T3.1,T0.3 |
| T3.3 | sort 模板 + golden spec | 模板 EVAL | T1.4 模式 |
| T3.4 〔关键路径〕 | M9 pfcore make 编排 + e2e_matrix.py（--quick 与全量）+ i18n/ar RTL 进模板 | 48 包 0 FAIL | T2.4,T3.1,4×golden |

## Phase 4 · D7-D8 产品化

| 任务 | 内容 | 验收 | 依赖 |
|---|---|---|---|
| T4.1 | M10 webui + 二维码 + 报告页 | M10 EVAL | T3.4 |
| T4.2 | 3-5 组真实素材全流程 + 性能调优（≤2s 加载）+ demo-prebuilt 定稿流程 | 单条全矩阵 ≤3 分钟 | T3.4 |
| T4.3 〔可选〕 | T1 数据工厂脚本（采集不执行） | dry-run 10 条样本 | T3.4 |

## Phase 5 · D9-D10 交付

| 任务 | 内容 | 验收 |
|---|---|---|
| T5.1 | 官方工具实测（AppLovin Playable Preview 等）→ 回填 channel-rules.json | 修订记录 |
| T5.2 | 法务扫描 scripts\legal_scan.py（§12 关键词 grep 公开仓） | 零命中 |
| T5.3 | 指标与文档、路演材料、演示视频 | 主会话验收 |

## 并行建议汇总
- 三条并行线贯穿：**模板线**（T1.4→T2.1→T2.2→T3.3）、**打包/资产线**（T1.3→T2.4 + T2.3）、**质检/LLM线**（T0.3/T0.4→T3.1→T3.2 + T2.5）。
- 单子代理任务粒度 ≤1 天人工量；每任务必须带回 EVAL 运行输出。
- 变更控制：schema/事件名/目录契约 D2 后冻结，改动需主会话批准并在本文件记录。
