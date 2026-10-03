# spec.md — acceptor-agent 资产规格（v1.0.0，2026-10-02）

> 依据：TASK.md 会话分解表 S-评审/ S-验收角色纪律 + 本会话实建与三门实测（绿 0 / 红空目录 1 / 用法 2）。
> 场景来源：SM（speaker-mapping）评测与彩排验收中「不信任自报、逐条留证、盲态隔离」的角色纪律。

## 1. 目标

| 文件 | 角色 |
|---|---|
| package/agent.md | 验收员角色包（可直接用作子代理 system prompt） |
| package/schema/verdict.schema.json | verdict JSON 结构冻结 |
| package/example-verdict.json | 合法示例 |
| oracle/expectations.json | 判分基准 |
| eval/runner.py | 确定性评测器（4 检查：节齐备/字段恰等/example 合法/零承诺措辞） |

## 2. 行为规格（冻结）

- R1 输出契约：verdict JSON 五顶层字段，PASS 当且仅当全 checks 过且 blockers 空；
- R2 证据纪律：每条 check 必带 evidence（路径:行号或命令+输出），未跑检查禁标 verified；
- R3 边界纪律：boundary_note 必填，只评交付过程；全文禁就业/收益承诺措辞；
- R4 失败纪律：被验收物缺失/任务卡矛盾 → FAIL + blocker，不猜测代答。

## 3. 欠账（如实）

- 盲评加厚待补；体检按 agent 定义类形态暂无对应工具（REGISTRY 注 1 同款豁免待 owner 裁定）；
- 真实子代理端到端演练（派一个真 agent 按 agent.md 验收一份产物）待下轮课堂彩排一并做。
