# cs_schema spec（数据契约层）

> 状态：**frozen（契约 v1.1，SCHEMA_VERSION="1.1.0"，CONTRACT_FROZEN_DATE="2026-09-28"）**。
> 本页对照 `chengshao/cs_schema/`（models.py / enums.py / constants.py / fixtures.py / __init__.py）
> 逐行核验于 2026-09-29。本包是唯一事实来源，**不得依赖其他任何 cs_* 包**（`__init__.py:5`）。

---

## 1. 职责与边界

**做**：定义全部跨模块数据结构（8 个 pydantic v2 模型）、受控词表（7 个 StrEnum 枚举）、
结构常量与缺省阈值、以及可复用的契约夹具（JSON fixtures）。JSON 可序列化，时间戳一律纳秒。

**不做**：不含任何业务逻辑、IO、时钟；不 import 其他 cs_* 包（依赖-free 是硬纪律，
新模块对契约的依赖方向只能是 cs_* → cs_schema）。

## 2. 模型表（models.py，8 个，全部继承 `_ContractModel`）

基类统一施加（models.py:33-40）：`extra="forbid"`（未声明字段拒绝）、
`allow_inf_nan=False`（NaN/Inf 拒绝）、`validate_assignment=True`（属性赋值同样过校验）。

| 模型 | 字段要点 | 跨字段不变式（model_validator） |
|---|---|---|
| `MouthPose` | ts_ns≥0, valid, x/y/z（米，base 系）, jaw_open∈[0,1], frown∈[0,1], head_yaw/pitch/roll（rad）, source∈{depth,mono,wrist}, confidence∈[0,1] | `valid=False` ⇒ `confidence==0`（坐标沿用上一有效值由生产方负责，models.py:63-67） |
| `ArmState` | ts_ns, joint_names/joint_pos/joint_vel（长度恒 `N_ARM_JOINTS=6`）, ee_pos(3), ee_quat(4, w 在前) | joint_names 互不相同（models.py:98-102） |
| `ArmCommand` | mode∈{joints,cartesian}, target, max_speed>0, timeout_s>0, frame（恒 "base"，缺省值） | joints ⇒ len(target)=6；cartesian ⇒ len(target)∈{3,7}（models.py:123-133） |
| `SafetyState` | ts_ns, estop_latched, human_zone_violation, violation∈{none,face_in_zone,speed,torque,watchdog}, clear_to_move | `violation!="none"` ⇒ `clear_to_move=False`（models.py:149-153） |
| `SpoonCheck` | ts_ns, has_food, score∈[0,1], cam_ref（非空串） | — |
| `VoiceIntent` | ts_ns, intent∈{next,pause,resume,done,select,greet,unknown}, slots(dict), confidence | 约定 select 时 slots["dish"]∈注册菜名表（不校验，由解析器保证） |
| `BiteRecord` | bite_id≥0, ts_start_ns/ts_end_ns≥0, outcome∈{success,retry,rejected,aborted}, grams_before/after 可空 | `ts_end_ns ≥ ts_start_ns`（models.py:193-197） |
| `MealSession` | session_id/user_id 非空, started_ns, ended_ns 可空, bites[], total_grams 可空 | ended 非空时 `ended_ns ≥ started_ns`（models.py:210-214） |

## 3. 枚举（enums.py，成员值即对外 JSON 字面量）

- `MouthSource`：`depth`（延后保留）/ `mono`（顶部固定先验）/ `wrist`（**v1.1 腕部双职**）。
- `CameraRole`（v1.1 新增）：`scene` / `wrist_mouth`——黑板键 camera_role 的取值域。
- `CommandMode`：`joints` / `cartesian`；`CommandFrame`：恒 `base`。
- `ViolationKind`：`none` / `face_in_zone` / `speed` / `torque` / `watchdog`（软件急停复用 watchdog，
  以 `estop_latched` 区分——cs_arm/safety.py:210 的既定口径）。
- `IntentKind`：`next` / `pause` / `resume` / `done` / `select` / `greet` / `unknown`。
- `BiteOutcome`：`success` / `retry` / `rejected` / `aborted`。

## 4. 常量（constants.py，缺省值——运行期可调参数一律从 config/ 覆盖）

| 常量 | 值 | 语义 |
|---|---|---|
| `N_ARM_JOINTS` | 6 | v1.1 修订（7→6）：5 臂关节 + 1 末端夹爪，与 6 舵机参考模型直接一致，撤销执行层映射假设（CHANGELOG.md §1） |
| `EE_POS_LEN` / `EE_QUAT_LEN` | 3 / 4 | ee_pos 米 base 系；ee_quat [w,x,y,z] w 在前 |
| `CARTESIAN_TARGET_POS_ONLY` / `_FULL` | 3 / 7 | cartesian 目标两种长度 |
| `MOUTH_PRIOR_DEFAULT_M` | 0.42 | 无深度时口部距离先验（config/mouth_prior.json 缺省同值） |
| `IPD_DEFAULT_M` | 0.063 | 成人瞳距先验（腕部 IPD 估距用） |
| `JAW_OPEN_THRESHOLD` | 0.35 | jaw_open > 0.35 判"张嘴" |
| `HEAD_YAW_TURN_THRESHOLD_RAD` | 0.4363 | 25°，`|head_yaw|` 双向判"转头" |
| `FROWN_ASK_THRESHOLD` | 0.5 | frown > 0.5 触发暂停+询问 |
| `DEFAULT_DISH_REGISTRY` | ("芋泥","南瓜粥","椰子冻") | select 槽位缺省词表，config 可扩展 |

## 5. 夹具（fixtures.py + fixtures/*.json）

- 14 个 JSON 夹具覆盖全部模型（含正例与变体：arm_command_joints/cartesian、
  safety_state_clear/estop、voice_intent_next/select）。
- API：`fixture_path(name)` / `load_fixture(name)` / `load_model(name, cls)`（带校验装载）/
  `load_model_fixture(...)` / `save_fixture(...)`。新契约字段 → 同步补夹具（tests 断言夹具与模型同步）。

## 6. 冻结纪律与变更流程

字段名、枚举成员值、常量名**只增不改名/不改值/不删除**；维度修订需走契约变更流程
（见 [../CONTRACTS.md](../CONTRACTS.md) §变更流程）。v1.0→v1.1 的实际修订记录见
`chengshao/cs_schema/CHANGELOG.md`（N_ARM_JOINTS 7→6；追加 MouthSource.WRIST 与 CameraRole；
MouthEstimator 向后兼容 keyword-only 扩展）。

## 7. eval（精确命令与通过线）

```bash
# cwd = 仓库根（pytest.ini: pythonpath=. 使 chengshao.* 可导入）
.venv/Scripts/python.exe -m pytest tests/test_schema.py -q
#   → exit 0；438 行用例全绿（2026-09-29 实测 83 passed，含 ≥12 个非法值负例：
#     extra 字段拒绝 / NaN 拒绝 / 越界拒绝 / 各跨字段不变式触发）。
```

- conftest.py 钩子在会话内跑过 test_schema 时自动落证据 `chengshao/reports/schema_eval.json`
  （字段遵循报告 schema，见 CONTRACTS C6——2026-09-30 订正：原文误写"§R"）。注意：
  `exit_status` 字段是**整个 pytest 会话**的
  退出码——与其他失败模块同会话跑会记 1，独立跑才干净（坑，见 REGENERATE §8）。
