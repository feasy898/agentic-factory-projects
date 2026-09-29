# docs/specs/ — 模块资产 spec 地图（每模块双交付之一）

纪律（决策 §5）：**每个模块 = 资产 spec + 冻结/移植 eval 双交付**。
oracle `repo/docs/assets/specs/`（12 件）是**唯一规格源**（封存只读）；各模块批次开工时
以对应 spec 为准重实现，spec 缺口按资产流程回填 oracle docs/assets（资产包是活资产）；
`contract-change:` 类回填（如 CONTRACTS 痛点 8）单独 commit。

| 模块 ID | oracle 规格源（repo/docs/assets/specs/） | factory 落位 | 状态 |
|---|---|---|---|
| M1-spec | `spec-contract.md` | `packages/spec/`（校验器本体） | **M1.2a 已落**（TS 单源校验器，[spec.md](spec.md)：冻结 ajv-check 原样过 exit 0 + 11 件裁定矩阵与 oracle 双侧全等 + 算例逐值 + tsc strict；差分证据 artifacts/diff/M1.2a-spec-eval.json） |
| M2-engine-bridge | `engine-bridge.md` | `packages/engine-bridge/` | **批次 1 完成（M1.2b）**（spec 字节落位本目录；冻结 26 用例 exit 0 + c8 行覆盖 97.6%≥80%（--lines=100 门真实性已验）+ tsc strict 过） |
| M3-templates ×4 | `templates.md` + `match3-rules-card.md` | `packages/templates/tmpl-*` | 批次 2 待做 |
| M4-packager | `packager.md` | `packages/packager/` | **批次 1 完成**（spec 字节落位本目录；46 断言冻结 eval + 六渠道结构断言 exit 0） |
| M5-assetkit | `assetkit.md` | `packages/assetkit/` | 批次 3 待做 |
| M8-qacore | `qacore.md` | `qacore/` | 批次 2 待做 |
| MODEL-ADAPTER | `model-adapter.md` / `llmgw.md` | `packages/llmgw/` | 批次 1 待做 |
| ORCHESTRATOR | `orchestrator.md` | `pf/` | 批次 3 待做 |
| M10-webui | —（oracle 内 webui/） | `webui/` | 批次 3 待做 |
| CHANNEL-ADAPTERS | `channel-adapters.md` | `channel-rules/`（字节复用已完成）+ 各处实现 | 数据资产已复用；规则库消费端实现随 M4 落地（rules.mjs 配置驱动） |
| PIPELINE-CONTRACT | `pipeline-contract.md` | 全局契约（报告字段/退出码） | 冻结，全程对齐 |

各模块 spec 落地时，把（改写后的）spec 文档放进本目录并更新状态列。
