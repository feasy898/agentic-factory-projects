# tests/CHANGELOG.md · Spec↔Eval 同构登记（01-contracts.md §6 重生成协议）

> 协议：SPEC 变更（含措辞导致行为语义变化）时，受影响 EVAL 必须重生成，并在本文件
> 登记 `spec_hash → eval_hash` 对；无登记的 EVAL 与 SPEC 不一致视为验收失败。
> `spec_hash` = spec_ref 列表文件按序拼接字节的 sha256（与 suite 文件内声明一致，
> runner 每次运行重算比对）；`eval_hash` = `tests/test_<module>.yaml` 文件字节 sha256。

---

## 2026-09-28 · S0 首条登记（仓库骨架与 EVAL 验收基座）

- **模块**：S0（基座套件 `tests/test_m0.yaml`；m1..m7 由各模块交付时在本文追加登记）
- **spec_ref**（按序拼接取 hash）：
  - `specs/01-contracts.md`
  - `specs/00-ontology.md`
  - `specs/ADDENDUM.md`
- **spec_hash → eval_hash**：

  | suite | spec_hash (sha256) | eval_hash (sha256) |
  | --- | --- | --- |
  | test_m0.yaml | `ddb3b0a38cc193ce3e7a4cfc3d0b4906d6c3e3f87f93331bded3758a05e5be04` | `41ebfbf8959bdab0e02df0a4964b3ba4714d3edddc1c1ea4f032d7790a042bf2` |

- **覆盖范围**：S0 套件 49 条用例——12 个冻结数据结构 round-trip 与负向拒绝
  （01§2.1–§2.12）、三状态机迁移断言（01§5.1–§5.3）、策略三值与不可改清单
  （00§1.3/§1.4）、幂等（01§3.3）、判据表达式（01§6）、事件序回放与 trace 贯穿
  （01§4/§8）、本体/规程/种子数据核对（插件执行器）、性能门槛。七类 Eval 形态
  （事件序回放/状态迁移断言/策略三值/幂等/表达式判据/负向拒绝/性能门槛）全部落位，
  schema 见 `tests/EVAL-SCHEMA.md`。
- **登记的偏差与落盘口径**（均为机械落盘时的必要消歧，未改任何冻结语义）：
  1. 01§5.2 原文 `DENY→DENYED` 系笔误；action 生命周期终态按 00§2 枚举落为
     `DENIED`（`tests/fixtures/frozen_state_machines.yaml` 注释同记）。
  2. 01§5.2 `FAILED→COMPENSATED` 为条件迁移（reversible 且有 compensation），
     迁移表以 `conditional_transitions` 标注，不进无条件表。
  3. `ontology/seed.yaml` 中电容 `state: OFF` 加引号——YAML 1.1 下裸 `OFF`
     会被 pyyaml 解析为布尔 False，加引号保持 00§1.1 "state(投/切)" 的字符串语义。
  4. contracts 时间戳字段接受字符串（UTC ISO-8601）与 pyyaml 解析出的 UTC
     `datetime` 对象两种形态（数据文件未加引号的时间戳）；非 UTC 拒绝。
     `ScenarioSpec` 的 `at` 字段为时间引用（格式由 M5 约定），接受非空字符串或 datetime。
  5. `ontology/rules.yaml` 为规则 ID 注册表（PHYS-*/SAFE-*/COMM-*/授权规则），
     判据全文落 `regulations/REG-TECH.yaml`（M5 判据唯一阈值来源）、条款全文落
     `REG-SAFE/REG-COMM.yaml`；授权规则以 `AUTH-ACTION-DEFAULT-POLICY` 登记并指向
     `ontology/actions.yaml` 的缺省 Policy。
  6. specs/README §0 称"11 数据结构"，01§2 实定义 12 个（§2.1–§2.12，含
     ReleaseBundle）；S0 按 12 个全部代码化（超集无风险）。
