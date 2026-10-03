# contract.md — acceptor-agent 接口契约（冻结 v1.0.0，2026-10-02）

## 1. 资产定位

「验收员」agent 定义资产：从 SM（会议纪要）场景的验收纪律泛化的独立验收子代理角色包。产出物 = 一份符合输出契约的 verdict JSON。

## 2. 产物根布局

```
package/agent.md                    # 角色定义（职责/输出契约/禁令三节，冻结）
package/schema/verdict.schema.json  # verdict 结构冻结（顶层 5 字段）
package/example-verdict.json        # 合法示例（校验通过）
oracle/expectations.json            # 冻结期望（判分基准）
eval/runner.py                      # 确定性评测器
```

## 3. 冻结项（eval 逐条判定）

| # | 冻结项 | 判定 |
|---|---|---|
| F1 | agent.md 含「职责/输出契约/禁令」三节 + 两条禁令关键句 | 文本比对 |
| F2 | verdict 顶层字段恰为 verdict/deliverable_path/checks/blockers/boundary_note | schema 比对 |
| F3 | verdict 枚举 PASS/FAIL；check 项字段 name/passed/evidence/status；status 枚举 verified/judged | schema+example 比对 |
| F4 | example verdict 校验通过（PASS ⇔ blockers 空；evidence 非空） | 规则校验 |
| F5 | 全部文本零就业/收益承诺措辞 | 反向词表比对 |

## 4. 红路（fail-closed）

空目录 / 缺任一 package 文件 / 缺节 / 字段不恰等 / example 非法 / 出现承诺措辞 → exit 1；红路永不修成 exit 0。

## 5. 用法错

参数个数 ∉ {0, 2} → exit 2。
