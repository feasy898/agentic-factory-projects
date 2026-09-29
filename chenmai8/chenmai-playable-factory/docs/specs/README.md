# docs/specs/ — 模块资产 spec 地图（每模块双交付之一）

纪律（决策 §5）：**每个模块 = 资产 spec + 冻结/移植 eval 双交付**。
oracle `repo/docs/assets/specs/`（12 件）是**唯一规格源**（封存只读）；各模块批次开工时
以对应 spec 为准重实现，spec 缺口按资产流程回填 oracle docs/assets（资产包是活资产）；
`contract-change:` 类回填（如 CONTRACTS 痛点 8）单独 commit。

| 模块 ID | oracle 规格源（repo/docs/assets/specs/） | factory 落位 | 状态 |
|---|---|---|---|
| M1-spec | `spec-contract.md` | `packages/spec/`（校验器本体） | 批次 1 进行中（M1.1 已落 schema 资产） |
| M2-engine-bridge | `engine-bridge.md` | `packages/engine-bridge/` | 批次 1 待做 |
| M3-templates ×4 | `templates.md` + `match3-rules-card.md` | `packages/templates/tmpl-*` | 批次 2 待做 |
| M4-packager | `packager.md` | `packages/packager/` | 批次 1 待做 |
| M5-assetkit | `assetkit.md` | `packages/assetkit/` | 批次 3 待做 |
| M8-qacore | `qacore.md` | `qacore/` | 批次 2 待做 |
| MODEL-ADAPTER | `model-adapter.md` / `llmgw.md` | `packages/llmgw/` | 批次 1 待做 |
| ORCHESTRATOR | `orchestrator.md` | `pf/` | 批次 3 待做 |
| M10-webui | —（oracle 内 webui/） | `webui/` | 批次 3 待做 |
| CHANNEL-ADAPTERS | `channel-adapters.md` | `channel-rules/`（字节复用已完成）+ 各处实现 | 数据资产已复用；实现随 M4 |
| PIPELINE-CONTRACT | `pipeline-contract.md` | 全局契约（报告字段/退出码） | 冻结，全程对齐 |

各模块 spec 落地时，把（改写后的）spec 文档放进本目录并更新状态列。
