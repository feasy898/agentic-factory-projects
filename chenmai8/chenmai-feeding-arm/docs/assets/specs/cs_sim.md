# cs_sim spec（仿真层：模型回退链 / FK/IK / 可达空间 / 安全包络 / 对抗 oracle）

> 状态：**frozen**（2026-09-29 全量 eval 实测通过，tier=mjcf；环境前提见 §8——参考模型件不在
> 公开仓内，`auto` 回退链的终点是内置名义链，公开克隆环境表现见 §8 坑 1）。
> 本页对照 `chengshao/cs_sim/`（model_source.py / backends.py / frames.py / arm_model.py /
> ik_solver.py / reachability.py / safety_envelope.py / adversarial.py / eval.py）逐行核验于 2026-09-29。

---

## 1. 职责与边界

**做**：机械模型装载与三级回退；FK/IK（阻尼最小二乘 + 确定性多起点）；可达空间体素扫描与
PNG 渲染；安全包络校验器（禁区/限速场/关节轨迹/连杆扫掠/送达停点与数值安全余量）；
独立违规轨迹 oracle（对抗样本生成 + 预定类别命中断言）。

**不做**：不发指令（执行在 cs_arm）；不渲染交互窗口（eval 渲染强制 matplotlib Agg）；
不承担真机标定。

## 2. 模型回退链（model_source.py + arm_model.py:229-260，冻结语义）

```
load_arm("auto")
  └─ discover_model_file()：候选根 = 包根(chengshao/)与 cwd 各向上 4 级里的 "_vendor/" 目录
     ＋存在则追加的工作区外集中参考目录 D:/upstream-refs/robot-vendor（及其 _vendor/）
     ＋环境变量 CS_VENDOR_ROOT 指向的根（最高优先、插最前）
     （model_source.py:62-92，2026-09-29 commit cea83b1 增补外链；_vendor 本地参考件，
     gitignore 永不入库）
     ├─ tier1 "mjcf"        ：glob "*/Simulation/*/*.xml"，评分选优
     ├─ tier2 "urdf_mujoco" ：glob "*/Simulation/*/*.urdf"
     └─ tier3 "chain_builtin"：都没找到 → 内置名义链（无文件依赖，最后手段）
_backend_for()（arm_model.py:229-260）：任一层装载/校验失败自动降级：
  MJCF(物理引擎) → 同目录 URDF(物理引擎) → 同目录 URDF(ikpy 纯运动学链, tier 记 "chain_urdf_ikpy")
  → 内置名义链
load_arm(显式路径)：按扩展名 .xml/.mjcf/.urdf 选 MujocoBackend，不存在即 FileNotFoundError。
```

- 候选评分 `_score`（model_source.py:95-103）：文件名含 `new_calib` 优先于含 `calib` 优先于其他；
  含 `camera` 降级；含 `leader` 降级；再按文件名字典序。排除 `scene*` 汇总与 `*joints_properties*` 参数表。
- 版本锁定：报告只记文件 SHA-256 前 16 位（`file_sha256_prefix`，无泄漏指纹）；
  参考件内部代号与锁定 commit 见 `chengshao/reports/upstream_lock.md`（`vendor-arm-model` 条目）。

## 3. 后端统一口径（backends.py，冻结）

- 关节向量 q 长度 = 模型可动关节数。**参考模型为 6 = 5 臂关节 + 1 夹爪**（夹爪不影响 TCP）；
  关节名实测：`shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper`
  （reports/sim_eval.json metrics.model）。
- TCP 定义 = 参考模型 `gripperframe` 工具系；**零位 TCP = (0.3914, 0.0000, 0.2265) m**（backends.py:16-18）。
- **URDF 工具系对齐**：URDF 写法与 MJCF site 写法差一个绕工具系 Y 轴 -90° 的固定旋转，
  `URDF_TOOL_ALIGN_QUAT = (0.7071067811865476, 0.0, -0.7071067811865476, 0.0)`（backends.py:44-46）；
  后端内部完成对齐，各 tier 对外同一 TCP（实测跨 tier FK 逐点一致 ≤4e-6 m）。
- URDF 途径 TCP 解析：在 URDF 原文找"末端连杆 → *frame*"固定关节取 xyz/rpy（缺失退化为单位变换），
  `_parse_urdf_tool_joint`（backends.py:196-220）。
- **坑（Windows 非 ASCII 路径）**：物理引擎按绝对路径打开含中文的路径会失败，相对路径可用
  （backends.py:129-132）——装载前把路径相对化（`_relative_to_cwd_if_possible`）。
- 坐标系：base 系 X 前向/Y 左/Z 上，米/弧度；四元数 [w,x,y,z] w 在前；
  rpy 固定角 R = Rz(yaw)·Ry(pitch)·Rx(roll)（frames.py:1-8）。
- `link_frames(q)`：返回各关节体原点 + TCP 共 n+1 个点（连杆胶囊扫掠的连杆近似参考点）。

### 内置名义链常数（tier3，BUILTIN_CHAIN，backends.py:305-323）

5 关节（无夹爪）：shoulder_pan / shoulder_lift / elbow_flex / wrist_flex / wrist_roll，
各连杆 translation/quat 与关节限位逐字取自参考 MJCF；tool 平移 (-0.0079, -0.000218, -0.0981274)、
quat (0.707107, 0, 0.707107, 0)。**注意：tier3 只有 5 关节，与契约 N_ARM_JOINTS=6 不匹配**——
见 §8 坑 1。

## 4. FK / IK（arm_model.py + ik_solver.py）

- 契约签名（只增不改）：`fk(q) -> [x,y,z,qw,qx,qy,qz]`（7 浮点）；
  `ik(target_pos, target_quat, seed=None) -> q | None`；`reachable_map(grid) -> dict`。
- `validate()`（arm_model.py:173-203）：关节 ≥2、限位有限且 upper>lower、中位 FK 输出 7 维有限、
  四元数单位（|q|-1 ≤1e-6）、TCP 中位可达距离 ∈[0.02, 1.2] m（参考臂 ~0.5m 级）。
- **DLS 求解器魔法数字（ik_solver.py:43-55）**：`iters=250, pos_tol_m=5e-4 (0.5mm),
  ori_tol_rad=5e-3 (5mrad), lambda0=0.05, lambda_max=10.0, max_step_rad=0.5`；
  停滞早退：总误差无 0.5% 级改善连续 40 步即断；自适应阻尼：误差回升 λ×3（≤λmax）且不接受该步，
  下降 λ/2（≥1e-4）；关节限位逐次截断。
- **多起点重启（ik_solver.py:147-182）**：`restarts=32`，seed 优先（clip 到限位），否则中位起步；
  重启用确定性伪随机 `rng_seed=0`（`np.random.default_rng`），**无全局随机性、可复现**；
  收敛即提前返回。实测 200 随机可达目标成功率 99.5%。
- **假收敛补丁（v3.1，ik_solver.py:133-144）**：从"误差回升路径的历史最优点"返回时，
  converged 必须按实际返回的 q 重算——防止把收敛旗标带到误差更大的解上。
- **奇异保护（eval 层）**：解的 `sigma_min(Jp)` 低于阈值判失败（随机批 0.005、
  送达工作区批 0.02——eval.py THRESHOLDS）。对外通过线（开发指令 §5.1）：位置 ≤5mm、
  姿态 ≤0.05rad；内部收敛门槛 0.5mm/5mrad 严于通过线。

## 5. 可达空间（reachability.py）

- 位置级可达定义：存在满足限位的 q 使 TCP 到达体素中心。`DEFAULT_GRID`：
  x [0,0.50]、y [-0.40,0.40]、z [-0.05,0.50]、res 0.03 m（arm_model.py:43-48）。
- 扫描：仅位置 DLS（`pos_only=True`，iters=80，max_step_rad=0.8），体素间**温启动**
  （上一解作初值），失败用 12 次确定性重启兜底（`rng_seed=1`；`pos_tol=5e-4`）。
  v3.1 修正：仅 warm 位形会大量漏判（200 体素抽样仅 6% 可达），故重启兜底必备（reachability.py:46-82）。
- 网格体素上限 200,000（超出抛错）；端点含入的确定性计数（`n = round((hi-lo)/res)+1`）。
- PNG 渲染：3D 散点 + XZ 中面切片，强制 Agg 后端（无显示环境安全）；产出 `reports/reach_map.png`。

## 6. 安全包络（safety_envelope.py，v3.1 审查修订）

### 6.1 禁入区与限速场（缺省 = config/workspace.json，二者数值一致）

| 项 | 值 | 代码位置 |
|---|---|---|
| 面部球域（球心=口部点） | center (0.42, 0.0, 0.30) m，r=0.12 m | safety_envelope.py:60-61 |
| 躯干胶囊 | p1 (0.48, 0, -0.10)、p2 (0.48, 0, 0.22)、r=0.15 m（躯干在口部点后方，不遮挡工作区） | :62-64 |
| 接近段限速 | 0.15 m/s | :65 |
| 近脸限速 | 0.10 m/s（距口部点 ≤0.15 m 的壳层） | :66-67 |
| 关节角速度上限 | 1.5 rad/s | :78 |
| 连杆近似半径 | 0.03 m | :79 |
| 关节段加密采样步长 | 0.05 rad（防"弦在球外、弧在球内"） | :80 |

### 6.2 判定语义（冻结）

- **轨迹级连续检查**：相邻采样点构成的**线段整体**参与禁区相交检测（线段-球 / 线段-胶囊
  最近距离，frames.py:129-176），采样稀疏不漏判穿入；时间须严格递增。
- **限速**：逐线段平均速度与**两端点处更严限速**比较（`speed_limit_at` 取 min）；
  超限容差 1e-9 相对量。
- **多区命中逐区报告**（v3.1 补丁，:278-298）：一条段穿多个禁区时全部列出（按间隙升序），
  不再只报最深一区。
- **关节轨迹** `check_joint_trajectory`（:381-461）：①关节段按 ≤0.05rad 加密 FK 采样后走线段检查；
  ②连杆扫掠：相邻连杆参考点连线叠加连杆半径逐子段检查（违规 kind=`link_sweep`，**豁免不适用于连杆体**）；
  ③关节角速度：逐原段 max|Δq|/Δt ≤1.5 rad/s（kind=`joint_speed`）。
- 违规 kind 词表：`zone` / `speed` / `link_sweep` / `joint_speed`。任一违规 ⇒ `rejected=True`。

### 6.3 送达停点与数值安全余量公式（v3.1 核心口径，:240-274）

```
delivery_stop_point = 口部点沿 -X 退 (face_radius + stop_clearance)
                    = (0.42, 0, 0.30) + (-(0.12+0.05), 0, 0) = (0.25, 0.0, 0.30)
停点必在面部球面之外（名义送达不需要任何豁免）；勺头伸向用户，用户前倾取食。

margin = stop_distance − spoon_tip_reach − tracking_err_bound − sense_err_bound
       = 0.17 − 0.08 − 0.02 − 0.05 = 0.02 m
通过线：margin ≥ DELIVERY_MARGIN_MIN_DEFAULT_M = 0.005 m（严格为正）
```

| 余量分量 | 缺省值 | 说明 |
|---|---|---|
| `stop_clearance_m` | 0.05 | 停点在球面外的额外间隙 |
| `spoon_tip_reach_m` | 0.08 | 夹爪口沿→勺尖，**保守常量未实测**（取偏大值保断言成立），臂上件后实测覆盖 |
| `tracking_err_bound_m` | 0.02 | 轨迹跟踪误差上界（执行层标定前保守值） |
| `sense_err_bound_m` | 0.05 | 口部感知误差上界（mono fixed 误差带上界；ipd 模式实测后可收紧） |

- **送达豁免** `register_delivery_target(point, r=0.03)`：保留给非名义场景（示教微调）；
  仅对"整段完全落在目标球内"的线段豁免禁区判定（限速与连杆扫掠不豁免）；
  cs_sim eval 的名义送达走廊**不登记任何豁免**。

## 7. 对抗性 oracle（adversarial.py，独立证据）

- **不复用校验器距离代码**（不 import frames.py），几何判据独立实现（点-球/点-胶囊穿透、
  线段采样最近距）；只在**关节空间**生成轨迹，覆盖三类此前无样本的违规：
  `joint_speed_over_limit` / `link_capsule_sweep` / `tcp_arc_zone_intrusion`（弦在球外弧在球内）。
- 每条轨迹带预定违规类别（生成前经独立判据证实违规），eval 要求校验器拒绝**且 kind 命中预定类别**
  ——两边有一边错即暴露（adversarial.py:1-21）。

## 8. eval 与环境前提（坑）

```bash
# cwd = chengshao/（包根）
../.venv/Scripts/python.exe -m cs_sim.eval --model auto --report reports/sim_eval.json
#   → exit 0；报告 22 项 checks 全 True。实测（2026-09-29，tier=mjcf）：
#     IK 200 目标 199 成功=99.5%（线≥98%），pos_err_max 0.49mm，ori_err_max 4.85mrad；
#     口前送达工作区 60/60（线≥95%，sigma_min≥0.02）；
#     跨 tier FK：chain_builtin 最大位置差 9.1e-9 m / chain_urdf_ikpy 与 urdf_mujoco 3.7e-6 m；
#     违规轨迹 500/500 拒绝；对抗 124/124 拒绝且类别命中 100%；
#     送达 margin=0.02≥0.005、走廊可通行（min_zone_clearance 0.05m）；
#     可达 5605/9576 体素=58.5% + reports/reach_map.png。
#   → 实测 wall ≈ 742s（可达性扫描占 ~705s；改 reachability 相关代码时预留 15 分钟）。
```

**坑 1（最重要）**：`auto` 依赖参考模型件（gitignore，不入库；内部代号
`vendor-arm-model`，见 reports/upstream_lock.md）。参考件于 2026-09-29 被整体移出工作区（安全扫描
门禁要求，实体在外部目录，路径登记于 upstream_lock.md 头注）后，公开/无参考件环境的 `auto`
一度落到 tier3 内置名义链——**该链只有 5 关节（无夹爪），与契约 N_ARM_JOINTS=6 不匹配**，
凡经 `ArmState`（要求 6 元数组）的路径全部 pydantic `too_short` 失败
（当日实测：全量 pytest 36 failed/260 passed；`cs_orchestra.eval --mock 1` exit 1 同因）。
**已修复（2026-09-29 commit `cea83b1`，2026-09-30 回炉实测）**：`_candidate_roots()`
（model_source.py:74-83）在 `_vendor` 之外追加发现工作区外集中参考目录
`D:/upstream-refs/robot-vendor`（及其 `_vendor/`，存在才加入）并支持 `CS_VENDOR_ROOT`
环境变量指向任意参考根（最高优先）；本机该目录在位，`pytest tests/` 实测
**297 passed / 1 skipped（exit 0）**。完全无参考件的环境仍会落 tier3 → 同样失败面，
**重生成前置**：参考件放回可发现位置——`_vendor/<参考件>/Simulation/<型号>/*.xml` 布局、
集中参考目录 `D:/upstream-refs/robot-vendor`，或设 `CS_VENDOR_ROOT`；亦可用显式路径调
`load_arm(path)`；_vendor 只在本地、永不入库。
**坑 2**：模型文件含中文路径时物理引擎绝对路径装载失败——已用相对化规避；自建模型目录避免非 ASCII。
**坑 3**：tier3/URDF(ikpy) 途径活动关节 = revolute 链接；URDF 链截断于名称含 "frame" 的工具系
link（其后夹爪指不入链）。
