# 跨模块冻结契约汇总（CONTRACTS）

> 版本：契约基线 v1.1（cs_schema SCHEMA_VERSION="1.1.0"，2026-09-28 冻结，同日修订）。
> 本页汇总跨模块冻结契约（ArmCommand 下发纪律 / 黑板键 / 报告 JSON schema / 目录与配置 /
> 相机角色时序），标注版本与变更流程；执行细节以各 spec 为准。

---

## C1 数据契约（cs_schema v1.1）

- 权威：`chengshao/cs_schema/`（[spec](specs/cs_schema.md)）。8 个 pydantic v2 模型、
  7 个 StrEnum、常量表；`extra="forbid"` + `allow_inf_nan=False` + `validate_assignment=True`。
- 结构锚点：`N_ARM_JOINTS=6`（5 臂关节 + 1 夹爪）；`ArmCommand(mode=joints).target` 长度 6、
  `cartesian` 为 3（仅位置）或 7（位置+四元数 [w,x,y,z]）；时间戳一律纳秒。
- 冻结纪律：字段名/枚举值/常量名**只增不改名不改值不删除**；维度修订走 §变更流程
  （v1.0→v1.1 的 7→6 修订记录见 cs_schema/CHANGELOG.md）。

## C2 ArmCommand 下发纪律（执行层唯一通道）

- **一切 ArmCommand 只能由 `SafetyEnvelope` 组装并下发到底层**（行为树/演示脚本/测试
  一律经包络；`ArmService` 不提供旁路，FeetechArm 是包络的底层、不重复包络检查——
  硬闸单点在包络层）。
- 包络写路径（[cs_arm spec §3](specs/cs_arm.md)）：禁入区巡检 → 闩锁/使能检查 → 目标解析
  （cartesian 在包络层经 IK **改写为 joints** 下发，夹爪保持当前值）→ 速度硬限
  （joints >1.5 rad/s 或 cartesian >0.15 m/s ⇒ 拒绝）→ 软限速（近脸 0.10 m/s 场）拉长时长
  → cs_sim 包络校验 ⇒ 下发。
- **拒绝语义**：`ArmCommandRejected(reason, detail)`，底层零运动；拒绝**不计入** violation
  （violation 只留给真实安全事件：急停/看门狗/禁入区；置位即 `clear_to_move=False`
  直到显式 `reset()`）。
- 安全事件：`estop()` 同步闩锁（violation=`watchdog`，`estop_latched` 区分）；
  看门狗 0.5s 无心跳 ⇒ `watchdog` + disable（巡检不喂心跳）；
  `reset()` 复位后立即复查禁入区（侵入中不复真）。

## C3 黑板键（行为树内部共享，冻结清单 8 键）

| 键 | 类型 | 写入方 | 语义 |
|---|---|---|---|
| `mouth` | `MouthPose` | runner 每 tick（sample_mouth） | 最近口部采样；腕部角色经 `cam_pose=FK×手眼` |
| `arm_state` | `ArmState` | runner 每 tick | 执行层回读 |
| `safety` | `SafetyState` | runner 每 tick（env.poll） | 安全快照 |
| `spoon` | `SpoonCheck` |勺检/勺空节点 | 最近勺上检查（cam_ref="wrist_cam"） |
| `intent` | `VoiceIntent\|None` | runner 每 tick（voice.poll） | 最近语音意图（挂起队列另存于 ctx） |
| `session` | `MealSession\|None` | runner/收尾节点 | 看板聚合单元 |
| `bowl_sel` | `int\|None` | SelectBowl | 当前碗序 |
| `camera_role` | `CameraRole`("scene"/"wrist_mouth") | 台账 switch | 当前相机角色（v1.1 追加） |

eval 断言 8 键齐（cs_orchestra.eval `blackboard_frozen_keys`）。

## C4 相机角色切换时序（v1.1 腕部双职，冻结）

- 转换"勺上检查通过→开始送达"（DELIVER 入场沿，**在进送达运动之前**）：
  `camera_role: scene → wrist_mouth`，原因码 `delivery_entry`；
- 转换"撤回完成/急停/禁入区中止/done 收尾撤回完成"：`wrist_mouth → scene`，
  原因码 `retract_complete` / `estop_abort` / `zone_abort` / `done_retract`（先发生者）；
- **每进送达口恰好 2 次切换**（未进送达的口 0 次），台账 + trace `role_switch` 事件双记录；
- 切换后**曝光稳定窗 0.5s**（`exposure_settle_s`）内口部通道一律返回失效帧
  （生产 WristMouthChannel 与 mock 同语义）；eval 断言首帧有效采样距切换 ≥0.5s；
- 口部坐标换算：`T_base_cam = T_base_flange(FK, 关节编码) × T_flange_cam(腕部手眼外参)`；
  手眼外参 `config/calib/handeye_wrist.npz`（key=`T_flange_cam`）优先、名义值兜底。

## C5 看板 HTTP 契约（cs_dashboard，冻结 4 端点）

`POST /api/session/start {user_id} → {session_id}`；`POST /api/bite`（裸 BiteRecord）→ 204；
`GET /api/session/current → MealSession`；`GET /api/stream`（SSE）。错误码：
无会话/重复 bite_id/重复开 session → 409；校验失败 → 422。追加端点与聚合口径见
[cs_dashboard spec](specs/cs_dashboard.md)。

## C6 报告 JSON schema（一切 eval 证据，开发指令 §10.2，冻结）

```json
{
  "module": "<cs_模块名|gate_g1|e2e_mock>",
  "date": "YYYY-MM-DD",
  "cmd": "<产生本报告的精确命令>",
  "metrics": { "…": "实测指标（含逐项数值）" },
  "thresholds": { "…": "与 metrics 同键的通过线" },
  "pass": true,
  "checks": { "…": "逐项布尔（可选，eval 自报）" }
}
```

- 落点：`chengshao/reports/<module>_eval.json`（门禁汇总 `gate_g1.json`；
  trace 审计流 `orchestra_trace.jsonl` / `e2e_mock_trace.jsonl`）。
- **裁定纪律**：模块自报 `pass` 不是最终裁定——`scripts/verify_g1_reports.py` 只读 JSON
  独立重算 metrics vs thresholds 并交叉核对（不一致即 FAIL）；skip 不算 pass；
  不许 mock 被测物（mock 臂/预录媒体是"无硬件仿真口径"的既定被测形态，注明于报告 `mode`）。
- `exit_status` 坑：tests/conftest 钩子写的报告（schema/food_interface）里 `exit_status`
  是**整个 pytest 会话**的退出码——与其他失败模块同会话跑会记 1（`pass` 随之为 False），
  独立跑该文件才是该模块的干净结论。

## C7 目录与配置契约

- 运行期可调参数只在 `chengshao/config/`（结构+缺省值；不放密钥与机器相关路径）；
  代码内常量（cs_schema）是**缺省值**，config 同名值必须与之一致（workspace.json 与
  EnvelopeConfig 缺省同源）。
- 证据/审计：`chengshao/reports/`；运行期数据 `data/`（gitignore）；模型权重 `models/`
  （gitignore，`*.task` 等）；本地参考件 `_vendor/`（gitignore，**永不入库**，公开文档只准
  内部代号）；标定产物 `chengshao/config/calib/handeye_*.npz`。
- Windows 非 ASCII 路径红线：图像/视频 IO 一律经 `cs_mouth/imgio.py` 的 `*_u` 系列；
  物理引擎模型装载经相对化路径（cs_sim backends）。

## 版本与变更流程（冻结）

- **版本锚**：`SCHEMA_VERSION="1.1.0"` / `CONTRACT_FROZEN_DATE="2026-09-28"`
  （cs_schema/__init__.py）；cs_arm `__version__="0.1.0"`；包络缺省=config/workspace.json。
- **谁批准**：契约（C1–C7）变更由仓库 owner / PM 批准；实现者不得单方面变更。
- **怎么广播**（每次契约变更必须全做）：
  1. 更新本页对应小节 + 受影响 specs/*（各 spec 头部"对照文件与核验日期"同步刷新）
     + **manifest.md/json 的冻结契约列同步**（语义口径变更最易漏的同步点——2026-09-30
     cs_voice 意图优先级订正时 spec 已改而 manifest 冻结契约列残留旧口径，即此漏洞实证）；
  2. cs_schema 模型/枚举/常量同步改 + fixtures 补齐 + CHANGELOG.md 追加修订记录；
  3. 受影响模块实现同步改；相关 eval 全绿（模块 eval + 受影响 pytest + gate_g1）；
  4. 单独 commit，标题带 `contract-change:` 前缀；破坏性变更进大版本（v1.1→v2.0）。
- **命名纪律（随契约冻结）**：公开仓文本零参考件原始名——文档用内部代号或中性描述；
  `python chengshao/scripts/check_naming.py` 作 CI 前置（本资产包撰写时曾被它当场拦下
  复述的禁用词——按 [e2e-and-gates spec §4](specs/e2e-and-gates.md) 规则改写后放行）。
