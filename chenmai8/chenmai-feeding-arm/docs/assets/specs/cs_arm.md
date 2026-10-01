# cs_arm spec（执行层：ArmInterface / SafetyEnvelope 硬闸 / MockArm / FeetechArm 骨架）

> 状态：**Mock 链路 frozen**（2026-09-29 eval 实测通过）；**FeetechArm 真机通道 = 骨架占位**
> （接口与参数冻结、fail-closed，实现随硬件 bring-up）。本页对照 `chengshao/cs_arm/`
> （interface.py / safety.py / kinematics.py / mock_arm.py / feetech.py / clock.py / eval_mock.py）
> 逐行核验于 2026-09-29。

---

## 1. 职责与边界

**做**：执行器统一抽象；包装任意 ArmInterface 的安全硬闸（限速/禁入区/软件急停/看门狗）；
仿真内虚拟臂（速度受限积分运动）；真机串口通道的接口与参数占位。

**铁律（契约 §3.1）**：一切 ArmCommand 只能由 SafetyEnvelope 组装并下发到底层，
其他模块不得绕过包络触达执行器（interface.py:11-12, safety.py:3-5）。

## 2. ArmInterface（interface.py，冻结签名）

```python
class ArmInterface(ABC):
    def read(self) -> ArmState: ...        # 回读 6 关节全量状态
    def write(self, cmd: ArmCommand) -> None: ...   # 违规指令必须抛 ArmCommandRejected 且零运动
    def enable(self) -> None: ...          # 上力矩
    def disable(self) -> None: ...         # 下力矩，运动立即冻结
    # 只增扩展：
    def halt(self) -> None: ...            # 立即冻结当前位形（幂等；急停/去使能由包络调用）
    @property
    def heartbeat_ns(self) -> int | None: ...   # None = 不提供心跳，包络跳过看门狗
```

- `ArmCommandRejected(reason, detail)`：`reason` 为稳定机器可读串（`not_clear_to_move` /
  `disabled` / `target_length_mismatch` / `target_beyond_joint_limits` /
  `cartesian_target_length_invalid` / `cartesian_quat_invalid` / `ik_no_solution` /
  `joint_speed_over_hard_limit` / `linear_speed_over_hard_limit` / `envelope_violation`）；
  拒绝语义 = 底层状态不变（零运动）。

## 3. SafetyEnvelope（safety.py）——行为树与真机之间唯一执行通道

### 3.1 写路径（write()，逐条指令，safety.py:121-186）

1. 取底层 fresh 状态并**先巡检禁入区**（侵入即闩锁+冻结，:315-330）；
2. 急停闩锁 / violation 未复位 / 未使能 → 拒绝 `not_clear_to_move` / `disabled`；
3. 目标解析（kinematics.resolve_target_joints）：joints 校验长度+限位原样取；
   cartesian 经 cs_sim IK 解算（3 维=pos-only 姿态保持、7 维=全位姿；**夹爪关节保持当前值**）；
4. 速度**硬限**判定（超限=拒绝，不静默放行）：joints `max_speed` > 1.5 rad/s；
   cartesian `max_speed` > 0.15 m/s（工作区接近段限速）；
5. 软限速（近脸 0.10 m/s 限速场）：**拉长执行时长**遵守（等效改写为更低速，记录进 decision）；
6. cs_sim 包络校验 `check_joint_trajectory`（[q0,q1] 两点、含加密采样+连杆扫掠+关节角速度）：
   任一违规 → 拒绝 `envelope_violation`（附校验器报告）；
7. **改写下发**：cartesian 一律在本层解算为 joints 指令（底层只吃关节目标，真机舵机通道同理；
   `max_speed` 取规划出的有效关节速度）；统计 `cartesian_rewritten_to_joints`。

**拒绝 ≠ violation**：拒绝不计入违规状态（violation 保持 none）——拒绝是包络在正确工作；
violation 只保留给真实安全事件（急停/看门狗/禁入区），其置位即 `clear_to_move=False`
直到显式 `reset()`（safety.py:19-22）。

### 3.2 安全事件语义

| 事件 | 行为 | 代码 |
|---|---|---|
| `estop()` 软件急停 | **同步闩锁**（返回即已生效）：halt 底层 + `estop_latched=True` + violation=`watchdog`（契约注释指定急停复用该类别，`estop_latched` 区分）+ 后续 write 全拒 | safety.py:206-212 |
| `reset()` 显式复位 | 清闩锁与 violation；**复位后立即重查禁入区**——TCP 仍在区内则如实重新闩锁（clear_to_move 不会在侵入中变真） | :214-226 |
| `poll()` 周期巡检 | 看门狗 + 禁入区；**巡检本身不喂心跳**（用底层 `snapshot_state` 快照，无则只在首次 read）——监控的是控制回路活性 | :228-253 |
| 看门狗 | 使能后 `watchdog_timeout_s`（缺省 **0.5s**）内无任何心跳（read/write/enable/disable 活动或底层心跳，取两侧较新者）→ violation=`watchdog` + 底层 disable；急停闩锁中不判 | :243-252 |
| 禁入区监控 | 每次 read/poll 检查当前 TCP，侵入 → violation=`face_in_zone` + 底层 halt + `zone_latches+=1` | :321-330 |

- `safety_state()` 快照满足契约不变式：`clear = enabled and not estop and violation==none`。
- 审计：`last_decision`（最近一条写指令的判定 dict：accepted/noop/mode_in/mode_out/rewritten/
  duration_s/eff_joint_speed_rad_s/eff_linear_speed_mps/linear_bound_mps 或 reason+detail）、
  `stats`（written/rejected/rejected_by_reason/cartesian_rewritten_to_joints/estop_count/
  watchdog_trips/zone_latches）。
- 模型复用：优先取底层执行器的 `model` 属性（校验层与执行层必须**同一运动学**），
  无则 `load_arm("auto")`（safety.py:82-87）。

## 4. 规划助手（kinematics.py，MockArm 与包络共用——同公式同输入同结果）

| 常量 | 值 | 语义 |
|---|---|---|
| `JOINT_LIMIT_TOL_RAD` | 1e-6 | 关节限位判定容差 |
| `TCP_LINEAR_SAMPLES` | 25 | TCP 弧长采样点数（含两端）——位置相关限速场沿实际弧线取点 |
| `LINEAR_TIME_SAFETY_FACTOR` | 1.05 | 弧长→时长的安全系数（覆盖校验器加密采样口径的弧长偏差） |
| `MIN_DURATION_S` | 1e-3 | 单条指令最短执行时长（防零时长穿越时间检查） |

- `plan_motion`（:140-204）：noop（目标=当前）→ 时长=MIN_DURATION_S；joints 硬限超 1.5 rad/s 拒；
  cartesian 硬限超 0.15 m/s 拒；`t_joint = max_dq / min(max_speed, joint_speed_limit)`
  （cartesian 恒用 joint_speed_limit）；`t_linear = arc×1.05 / min(沿途限速)`，
  cartesian 另取 `max(t_linear, arc/max_speed)`；最终 `duration = max(t_joint, t_linear, MIN_DURATION_S)`。
- `tcp_arc_samples`：直线关节插值的 TCP 轨迹是空间弧线，限速场判定必须沿弧取 25 点。
- `arm_state_from(model, q, qd, ts)`：FK 装 ee_pos/ee_quat，装配契约 ArmState。

## 5. MockArm（mock_arm.py）——cs_sim 内虚拟执行

- **速度受限积分**：write 通过全部检查后生成 `MotionPlan(q0,q1,vel,start_ns,duration_s,deadline_ns)`；
  `read()` 把状态推进到当前时钟（线性关节插值）再返回。时钟缺省墙钟 `perf_counter_ns`，
  测试/eval 注入 `VirtualClock`（clock.py：手动 advance，只进不退，起步 0）。
- **超时语义**：仿真时间越过 `deadline_ns`（start + cmd.timeout_s）→ 冻结在**截止时刻位形**
  （非目标位形），放弃剩余行程，`timeout_aborts+=1`（:276-295）。
- 双层自检：MockArm 自身也过包络校验（`validate_envelope=True` 缺省）——包络与执行器
  两层对同一指令给出一致判定。
- `snapshot_state()`：推进运动但**不喂心跳**（包络 poll 专用；真机通道按同一语义提供——
  串口巡检读数不计入控制心跳）。
- `teleport(q)`：测试/装配用直置位形（仅虚拟执行器提供；禁入区演练用 mock.teleport 装配）。
- **缺省家位 `_find_clean_home`**（:65-99）：全零位形 TCP 落在面部球域内（距口部点约 0.079m
  < 0.12m）不可作缺省家位；故固定种子 `seed=20260928`、至多 500 试、要求 TCP 与全部连杆
  参考点间隙 ≥0.03m 且落在前向工作盒 x∈[0.05,0.30]、|y|≤0.25、z∈[0.02,0.35]；
  找不到回退全零（交由禁入区监控如实闩锁——宁可误报不可漏报）。

## 6. FeetechArm 骨架（feetech.py，真机占位——fail-closed）

- `FeetechArmConfig`（冻结参数结构）：`port=""`（空=未配置）/ `baudrate=1_000_000` /
  `servo_ids=(1..6)`（必须恰 6 个、互异、正整数；下标 5=夹爪）/ `joint_speed_limit_rad_s=1.5`
  （与 workspace.json 一致）/ `return_delay_time_us=250` / `torque_enabled_by_default=False`。
- 骨架阶段所有触达硬件的方法（read/write/enable/disable/halt/connect）抛 `HardwareUnavailable`
  ——**宁可拒绝也不装作成功**；`heartbeat_ns=None`。
- 传输层二选一（接口不变）：A = 上位机机器人框架的 follower 舵机通道适配（pip 依赖已锁定）；
  B = 舵机厂商官方 Windows SDK 直连（`feetech-servo-sdk==1.0.0` 已在 requirements）。
  硬闸单点在包络层——本类不重复包络检查。

## 7. eval（精确命令与通过线）

```bash
# ① 接口/语义单测（cwd=仓库根）
.venv/Scripts/python.exe -m pytest tests/test_arm_mock.py -q     # 2026-09-29 全绿（随环境前提）
# ② eval_mock 全量验收（cwd=chengshao/ 包根）
../.venv/Scripts/python.exe -m cs_arm.eval_mock --report reports/arm_mock_eval.json
#   → exit 0。实测（2026-09-29，tier=mjcf）：急停时延 0.058ms（线 ≤100ms）且冻结+后续全拒；
#     1000 条指令注入 0 条违规执行（面部/躯干/关节超速/笛卡尔超速/对抗类全部 100% 拒）；
#     走廊跟踪误差 0.3mm（线 ≤2mm）；近脸软限速生效（请求 0.15 → 有效 0.0952 m/s）；
#     看门狗 0.4s 静默不跳 / 0.6s 必跳；禁入区闩锁+写入阻断+复位重闩；cartesian 改写 337 次。
```

- 通过线阈值（eval_mock 内置）：`injected_min=1000`、`must_reject_rate_min=1.0`、
  `violating_executed_max=0`、`estop_latency_ms_max=100`、`tracking_err_max_m=0.002`、
  `measured_tcp_speed_max_mps=0.15`、`measured_joint_speed_max_rad_s=1.5`、
  `delivery_margin_min_m=0.005`、watchdog `timeout_s=0.5` 必跳且安静期不跳。
- **环境前提**：同 cs_sim §8 坑 1——无参考件时 `auto` 落 tier3（5 关节）即不满足 6 关节契约，
  本模块全部用例失败；重生成前先满足模型前提。
