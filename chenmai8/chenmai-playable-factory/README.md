# factory — 可玩广告生产线 · 模式 M 全新实现

TS/Node 22 单栈重写（决策：`../plan/模式M-技术选型决策.md`，其裁决优先于任何旧规划）。
oracle `../repo/` 封存只读；差分对齐在**契约层**（spec 输入 → 产物 + 质检报告 + CLI 退出码）。

## 命令

```bash
npm ci            # 安装（离线机用预打包 node_modules）
npm test          # node --test 全仓测试（含数据资产 sha 逐项校验）
npm run build     # esbuild 构建链（遍历 workspaces 包；空跑 exit 0）
npm run verify:assets   # 单独重算 REUSED-ASSETS.md 登记册
```

## 布局（决策 §2 树）

```
packages/   spec(M1) engine-bridge(M2) packager(M4) templates(M3×4+vendor母本) llmgw assetkit(M5)
qacore/     M8 判官（批次 2）
pf/         编排 CLI：node pf.mjs validate|make|serve（批次 3）
webui/      M10 网页壳（批次 3）
channel-rules/  字节复用（rulesVersion 1.1.0）
specs-eval/     字节复用（golden×4 + bad×6 + demo-zh + spike-manifest + 素材）
scripts/        build.mjs / verify-reused-assets.mjs（gate_*.mjs、e2e、diff/ 随批次落）
docs/specs/     模块资产 spec 地图（每模块 = spec + eval 双交付）
```

数据资产字节复用登记：**REUSED-ASSETS.md**（16 项已与 oracle 逐项 sha256 比对一致）。
开发纪律：**AGENTS.md**（可擦除语法、单栈、零上游名、数据契约零变更、坑 4/5/14/16）。
