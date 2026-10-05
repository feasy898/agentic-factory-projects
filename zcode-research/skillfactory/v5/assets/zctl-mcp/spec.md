# spec.md — zctl-mcp 资产规格（v1.0.0，2026-10-02）

> 依据：zctl/README.md（2026-09-28 状态）+ 本会话实建 server 与三门实测（绿 0 / 红空目录 1 / 用法 2）。
> 上游工具：`zcode-research/zctl/zctl.mjs`（单文件 Node CLI；变更类命令默认 dry-run 须 --yes）。

## 1. 目标

| 文件 | 角色 |
|---|---|
| package/mcp-server.mjs | MCP stdio server：initialize / tools/list / tools/call / ping |
| package/INSTALL.md | ZCode 客户端 MCP 配置片段 |
| oracle/expected_tools.json | 冻结期望（判分基准） |
| eval/runner.py | 确定性评测器 |

## 2. 行为规格（冻结）

- R1 只暴露 4 个只读工具（zctl reset status / offpeak availability / offpeak status --ids <id> / --help）；
- R2 tools/call 以子进程调 zctl.mjs，30s 超时，stderr 并入文本，退出码非 0 → isError=true；
- R3 zctl.mjs 缺失时返回结构化错误文本（不崩溃、不退出）；
- R4 未知工具 → JSON-RPC -32602；未知方法 → -32601；解析错 → -32700；
- R5 确定性：tools/list 输出恒定；无时间戳无随机。

## 3. 评测口径

见 contract.md §3-§5；eval 全离线（不真发 zcode.z.ai 请求，仅握手+列举+契约比对）。

## 4. 欠账（如实）

- 盲评加厚（n=2 标签互换，历史轮不含本资产）待补；
- 体检（v3 healthcheck 5 项）按工具类形态豁免先例（REGISTRY 注 1）暂记 C 等待 owner 裁定；
- 对 zcode.z.ai 的真实 tools/call 端到端验证待真机（zctl 上游本身也待真机验证，README 2026-09-28）。
