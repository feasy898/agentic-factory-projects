# cs_schema 契约修订说明

## v1.1.0（2026-09-28，tag `cs_schema-v1.1`）

审查驱动的契约修订（独立评审报告 A 类问题 11/12）。原则：字段名与既有枚举值不改不删，只做一处维度修订与追加。

### 1. 修订：`N_ARM_JOINTS` 7 → 6

- 依据：参考模型为 6 舵机（5 臂关节 + 1 夹爪），cs_sim 仿真模型关节数即 6；
  原 v1.0 的"7 关节统一数组 + 执行层再做映射"引入了不存在的隐式映射层，
  在执行层落码前必须修正。
- 影响：`ArmState.joint_*` 与 `ArmCommand(mode=joints).target` 长度契约 7→6；
  夹具 `arm_state.json` / `arm_command_joints.json` 同步；测试断言同步。
- 训练侧一致性：`training/config/train_act*.json` 的 `dataset.action_dim` 7→6。

### 2. 追加：`MouthSource.WRIST = "wrist"`（腕部双职）

腕部相机双职（舀取时看勺、送达时看脸）的感知路径进入契约：

- 口部三维 `MouthPose.source` 新增字面量 `"wrist"`：单目 + IPD 瞳距先验
  （`Z = fx × ipd_m / ipd_px`，ipd_m 缺省 0.063m）+ FK 相机位姿换算到基座系。
- `MouthEstimator` 向后兼容扩展（keyword-only 可选参数，缺省行为不变）：
  - `__init__(..., pose_provider: Callable[[], tuple] | None = None)`
    ——无参函数返回 `(T_base_flange, T_flange_cam)`（行为树接 FK 用）；
  - `from_bgr(img, depth=None, *, cam_pose=(T_base_flange, T_flange_cam))`
    ——单帧覆盖；提供该参数时走 IPD 估距且 `source="wrist"`。
- `MouthPrior` 新增 `mode: "fixed" | "ipd"`（config/mouth_prior.json）与
  `ipd_m: float = 0.063`；`mode=fixed` 行为与 v1.0 完全一致（顶部相机回退路径）。

### 3. 追加：`CameraRole` 枚举（黑板键 `camera_role`）

- `CameraRole.SCENE = "scene"` / `CameraRole.WRIST_MOUTH = "wrist_mouth"`。
- 行为树黑板键冻结清单新增 `camera_role`（cs_orchestra）：
  "勺上检查通过→开始送达"置 `wrist_mouth`；"撤回完成/急停/中止"回 `scene`。
- 腕部角色生效期间，cs_mouth 采口部帧前先等曝光稳定（≤500ms，模块实现细节）。

### 4. 验收入口

- `python -m cs_mouth.eval --wrist-view`：腕部视角样本验收（检出率 ≥95%、
  IPD 估距误差 ≤4cm）；样本目录缺失时退出码 2（接口先冻结，样本后补）。

### 版本

- `SCHEMA_VERSION = "1.1.0"`，`CONTRACT_FROZEN_DATE = "2026-09-28"` 不变。
