# cs_orchestra spec（编排层：行为树 / 单口状态机 / 相机角色时序 / mock 验收）

> 状态：**mock 链路 frozen**（2026-09-29 eval 实测 30/30 回合全绿，tier=mjcf 环境前提下；
> 真机接线=生产薄封装已备）。本页对照 `chengshao/cs_orchestra/`（core.py / nodes.py /
> runtime.py / mock.py / eval.py）逐行核验于 2026-09-29。
> **状态转移表的权威文本 = core.py 模块 docstring**（`STATE_TRANSITION_TABLE` 指向它，
> tests/test_orchestra.py 按关键词断言存在）；本页是其展开。

---

## 1. 职责与边界

**做**：50Hz tick 行为树（py_trees）；单口状态机全节点；打断分支（急停/禁入区/转头/语音/
皱眉）；相机角色（scene/wrist_mouth）切换与台账；对执行层只经 SafetyEnvelope（ArmService
不提供任何旁路）。

**不做**：不组 ArmCommand 以外的执行原语；不直接开相机/串口（帧源经 `frame_provider` 注入）；
舀取策略可替换（MockScoop/ScriptedScoop/延后学习型策略对齐同一交互协议，不重构树）。

## 2. 树结构（nodes.py:681-703，装配冻结）

```
root(Selector, 无记忆)
 ├─ SafetyGate        急停闩锁/禁入区违规（最高优先级打断）
 ├─ InteractionGate   done 收尾(terminal)/pause/转头·人脸丢失>1s/皱眉/next/select
 ├─ SessionGuard      餐已结束 → SUCCESS（root 收敛，tick 循环退出）
 └─ meal(Sequence, 无记忆)
     SelectBowl → Scoop → SpoonCheckGate → Deliver → WaitBite
       → SpoonEmptyConfirm → Retract → RecordBite
```

全部主序列节点按 `BitePhase` 相位幂等（口外/已过/未到 → SUCCESS；被高优先级分支打断/
复位后原地恢复——进度只存在于 TickContext，不在树节点里）。

## 3. 单口状态机与转移表（core.py:6-44 + BitePhase）

`BitePhase`（数值只增不改）：IDLE=0 → SELECT_BOWL=1 → SCOOP=2 → SPOON_CHECK=3 →
DELIVER=4 → WAIT_OPEN=5 → WAIT_BITE=6 → SPOON_EMPTY=7 → RETRACT=8 → RECORD=9。
无中断时严格按序走完 RECORD 后开下一口。

| 阶段 | 进入条件 | 离开条件（→ 下一相位） |
|---|---|---|
| SELECT_BOWL | 开新口（SelectBowl 兼负开新口职责；到额定口数→自然收尾） | 选定碗（点菜偏好优先于场景扫描；未见码 RUNNING 重扫）→ SCOOP |
| SCOOP | — | 发起一轮舀取行程（`scoop.plan_round`），行程完成 → SPOON_CHECK |
| SPOON_CHECK | 先 `on_round_complete`（世界侧），再取勺检 | 过→DELIVER；不过且 `scoop_round-1 < scoop_retries_max(=2)` → SCOOP 重舀回流；**耗尽 → outcome=retry，直接 RETRACT（该口 camera_role 全程 scene，0 次切换）** |
| DELIVER | **入场沿：camera_role scene→wrist_mouth（reason=delivery_entry，在进送达运动之前）**；起算曝光稳定窗 | 路线完成且到位误差 ≤arrive_tolerance_m(0.01m) → WAIT_OPEN；超差 → 本口 aborted |
| WAIT_OPEN | 勺停包络送达停点 | 见到张嘴（jaw_open>0.35，open_seen=True）→ WAIT_BITE（超时基准复用为张嘴时刻）；闭嘴等待超时 25s → rejected+RETRACT |
| WAIT_BITE | — | jaw_open<0.20（编排层闭嘴阈值）→ SPOON_EMPTY；超时 25s → rejected+RETRACT |
| SPOON_EMPTY | — | 勺空（has_food=False）→ RETRACT；仍见食物按 0.5s 间隔复检 ≤3 次后 → rejected+RETRACT |
| RETRACT | 未进送达的口直接回家；进过送达的口沿送达走廊笛卡尔返向（停点→预停点→途经点逆序→家）+开爪 | 路线完成沿：**camera_role wrist_mouth→scene（reason=retract_complete）** → RECORD |
| RECORD | — | 写 BiteRecord（sink+黑板 session）→ 口关闭，下一 tick 开新口 |

## 4. 打断分支（每 tick 最高优先级，响应动作冻结）

| 触发 | 响应（一次性入场） | 恢复条件 |
|---|---|---|
| 软件急停（estop 闩锁） | 立即停 + **camera_role→scene(estop_abort)**（若在腕部角色）+ 本口 outcome=aborted + 播报"急停！我已停止运动。" | 包络 reset（操作员）+ 收到 resume/next 任一；恢复时**逆序回放被中止路线的前向关节路径**（原路退回，覆盖"后撤 5cm"意图且不进未知位形区）+ 补一记回家笛卡尔腿 |
| 禁入区违规（闩锁） | 同上（reason=zone_abort）；**闸自行尝试 env.reset()**——TCP 仍在区内会被包络如实重新闩锁，闸保持 RUNNING 等外部解除（mock 用 teleport 装配移出） | 移出+复位后原路退回+回家，等 resume/next |
| 转头/人脸丢失 >1s | **仅腕部角色的 DELIVER/WAIT_OPEN/WAIT_BITE/SPOON_EMPTY 相位**：保持（主序列不再下发新指令段，在途段自然完成）+ 播报一次（key 去重） | 恢复（valid 且 |yaw|≤25°）后原地继续当前阶段；非腕部相位自动清窗 |
| intent=pause | 悬停 + 播报"好的，我先停住。" | intent=resume |
| intent=done（吃饱了） | **terminal**：本口 rejected → 沿撤回路线收尾（完成沿 camera_role→scene, **done_retract**）→ 会话结束（sink.end_session）→ 永久 SUCCESS | — |
| intent=next | **仅 WAIT_OPEN/WAIT_BITE 两阶段生效**：跳过等待，outcome=rejected，撤回；其他阶段记录 next_ignored 不动作 | — |
| intent=select | 记录点菜偏好（菜序→碗序映射：registry.index(dish) % 碗数），**下一口选碗生效** | — |
| frown>0.5 | 暂停 + 播报询问（key 去重） | frown 回落，或 resume 解除（frown 未落也要能继续） |
| greet/unknown | 记录 trace 不动作 | — |

意图消费为 FIFO 逐条取用（`take_intent`）；播报文案表 `_ANNOUNCE`（nodes.py:78-87）共 8 条；
每条播报经 trace `announce` 事件（key 一次性去重+计数）。

## 5. 相机角色切换时序（v3.1 契约核心，core.py CameraRoleLedger）

- 黑板键 `camera_role ∈ {scene, wrist_mouth}`；台账记每次切换
  `{ts_ns, bite, from, to, reason}` 并同步 trace `role_switch` 事件 + 通知口部通道
  `mouth.set_role(to, ts)`。重复切换到同角色直接抛错（台账即断言器）。
- **断言口径（eval 与 tests 共用 `per_bite_report`）**：
  - 进入送达的口**恰好 2 次切换**：
    ① `scene → wrist_mouth`，reason=`delivery_entry`（进送达运动之前）；
    ② `wrist_mouth → scene`，reason ∈ {`retract_complete`, `estop_abort`, `zone_abort`,
    `done_retract`}（四者中先发生者），且 ts ≥ ①的 ts；
  - 未进送达的口（重舀耗尽 retry）**0 次切换**。
- **曝光稳定窗**：DELIVER 入场置 `settle_until_ns = now + exposure_settle_s(0.5s)`；
  窗口内口部通道一律返回失效帧（生产 WristMouthChannel 与 mock 同语义，
  runtime.py:65-79）——**先等曝光稳定再采信口部帧**。eval 断言每次 delivery_entry 后
  第一帧有效口部采样距切换 ≥0.5s（tick 粒度余量 0.05s）。
- `WRIST_PHASES = {DELIVER, WAIT_OPEN, WAIT_BITE, SPOON_EMPTY}`（core.py:155-161）——
  转头/皱眉打断只在腕部角色 + 处于这些相位时生效。

## 6. 运行参数（OrchestraParams，缺省=config/orchestra.json 一致；可 config 覆盖）

| 参数 | 缺省 | 语义 |
|---|---|---|
| tick_s | 0.02 | 50Hz tick（§5.6） |
| cruise_speed_mps | 0.14 | 转运巡航（<接近段硬限 0.15，留包络余量） |
| approach_speed_mps | 0.08 | 末段逼近停点 |
| scoop_descend_speed_mps | 0.06 | 入碗慢降 |
| route_step_m / final_step_m | 0.03 / 0.02 | 转运/末段流式步长（细步防关节大步密的峰速超限） |
| exposure_settle_s | 0.5 | 相机角色切换后曝光稳定窗（契约 v3.1） |
| turn_sustain_s | 1.0 | 转头/人脸丢失保持判定持续阈值 |
| wait_bite_timeout_s | 25.0 | 等待咬合超时（超时按 rejected 撤回） |
| scoop_retries_max | 2 | 空勺重舀上限（含首次共 ≤3 次行程） |
| spoon_empty_rechecks / spoon_recheck_interval_s | 3 / 0.5 | 勺空确认复检 |
| retreat_distance_m | 0.05 | 禁入区后撤距离（实现=原路退回，覆盖之） |
| arrive_tolerance_m | 0.01 | 送达到位判定半径 |
| cmd_timeout_s | 30.0 | 单条 ArmCommand 超时（仿真秒） |
| max_meal_sim_s | 900.0 | 单餐仿真时长上限（防挂死） |
| home_point_m | [0.24,−0.08,0.16] | 家位（TCP 目标） |
| delivery_via_points_m / _by_bowl | 共享 2 点 / 逐碗 3 组 | 送达途经点（仿真走廊搜索实测选优；逐碗表优先） |
| stop_approach_offset_m | 0.08 | 停点 −X 方向预停点偏移 |
| jtrack_replay_speed_rad_s | 1.2 | 关节轨迹回放速度上限 |
| bowl_hover_offset_m / bowl_dip_offset_m | 0.08 / 0.015 | 碗上悬停高 / 入碗深度 |
| gripper_open / gripper_close | 0.6 / 0.2 | 夹爪开/合位 |
| user_*（4 项） | 0.4/0.4/0.3/0.012 | **仅 mock 仿真用**（生产无此组） |

碗位：config/workspace.json `bowls_m`（三点 [0.22,∓0.18/0,0.02]），缺失回退代码缺省。

## 7. 路线跟随器 RouteFollower（core.py:423-562）

- 路线项 5 类：`("cart", 点, 速度, 步长)`（起段时从当前 TCP 展开为 ≤step 的绝对途经点序列逐点下发）
  / `("grip", 开度, 速度)` / `("joints", q, 速度)` / `("jtrack_reverse", 速度上限)` /
  `("jtrack_seq", 轨迹, 速度上限)`。
- **journal 只记前向探索写**（cart 项按包络同口径预解析关节目标；joints 回放写不计入）——
  保证 `jtrack_reverse` 逆序回放得到的是**纯去程路径**（带嵌入式回放的去程逆序会先重新下碗）。
- **抬勺用 jtrack_reverse 的原因**：入碗段已逐点过包络、反向同样可通行；避免点式 IK 在
  腕部滚转重构区换支（3+ rad 突跳）。
- **回放逐写速度公式** `_replay_speed`（:457-473）：`speed = min(jtrack_replay_speed(1.2),
  0.8 × 段中点限速 / max(TCP增益,1e-6))`，其中 TCP 增益 `gain = chord/dq_max`
  （TCP 速度 ≈ chord×speed/dq_max 须 ≤ 段限速近脸 0.10/接近 0.15）；dq<1e-9 时回 0.5。
- 被打断（急停冻结/闸保持）后原地继续——绝对途经点仍然成立；`ArmCommandRejected` 记
  `route_rejected` trace 并 failed（正常调度不应发生，触发即本口 aborted）。

## 8. 生产接线（runtime.py，T9/e2e 与真机共用）

`WristMouthChannel`（消费 cs_mouth.MouthEstimator：scene 角色或稳定窗内不采帧，腕部角色
`from_bgr(frame, cam_pose=(T_base_flange, T_flange_cam))`，手眼外参 `handeye_wrist.npz`
优先、名义值兜底）；`SceneBowlScanner`（cs_food.BowlSelector+顶部帧源）；`WristSpoonSource`
（SpoonClassifier+腕部帧裁剪）；`ScriptedScoop`（悬停→慢降→合爪→jtrack_reverse 抬勺→回悬停，
无抖动）；`VoiceBusLink`（透传 VoiceLink）；`HttpDashboardSink`（看板 HTTP 契约）。

## 9. mock 验收脚本（mock.py；eval 与 e2e 共用口径）

- **回合脚本（每回合同一）**：15 口额定；注入表 `SPEC_MEAL_SCRIPT`：
  第 3 口 `first_scoop_empty`（首轮舀空→闭环重舀命中）、第 7 口 `turn_s=2.5`（送达中转头
  2.5s）、第 9 口 `reaction_s=6.0`（闭嘴等待 6s）、第 12 口 `estop`（送达在途注入急停，
  操作员 reset+"继续"续餐）、第 15 口 `done`（等待咬合时"吃饱了"）。
- **期望结局表** `SPEC_MEAL_EXPECTED_OUTCOMES`：1..15 = success，**12=aborted、15=rejected**
  （其余全 success；第 3 口重舀后仍 success）。
- mock 用户状态机（FakeMouthChannel._tick_user）：勺停稳（进入 WAIT_OPEN）后
  反应延时(0.4s) → 0.3s 张开到 jaw=0.85 → 保持 0.4s → 0.3s 闭合；jaw≤0.20 判咬合完成
  （世界侧勺空）。转头窗口 yaw=0.62rad（≈35°>25° 阈值）；人脸丢失窗口返回失效帧；
  scene 角色一律失效帧（顶部相机无面部职责）；正常 yaw=0.05、位置=面心+±2mm 噪声、
  confidence=0.9、source=wrist。
- MockScoop 重舀轮次带闭环修正抖动（入碗点 xy ±0.01m）。
- 黑板冻结键初始化（MealRunner）：`camera_role/spoon/intent/bowl_sel/session` 先置初值；
  `mouth/arm_state/safety` 每 tick 刷新——**8 键齐**（eval 断言 exists 数=8）。
- tick 循环：`clock.advance_s(tick_s) → poll（env.poll + arm_state + 开会话 + sample_mouth +
  voice.poll 入队）→ root.tick_once()`；root SUCCESS 或超 max_ticks（900s/0.02=45000 tick）终止。

## 10. eval（精确命令与通过线）

```bash
# cwd = chengshao/（包根）或仓库根（python -m chengshao.cs_orchestra.eval）
../.venv/Scripts/python.exe -m cs_orchestra.eval --mock --episodes 30 \
    --report reports/orchestra_eval.json --trace reports/orchestra_trace.jsonl
#   → exit 0。实测（2026-09-29，tier=mjcf）：30/30 回合过、450 口、
#     outcomes {success:390, aborted:30, rejected:30} 与期望表全符、
#     单口中位 19.74s（线 ≤20）、切换 900 次（每进送达口恰 2）、
#     曝光稳定 gap≥0.5s、0 安全违规/0 意外拒绝/0 意外失败。wall ≈ 25 分钟。
```

| 通过线 | 值 |
|---|---|
| 回合数 | 30 回合全过（15 口/回合并发注入脚本） |
| camera_role | 每进送达口恰 2 次切换 + 时序正确（30/30） |
| 曝光稳定 | delivery_entry 后首帧有效采样 ≥0.5s（余量 0.05s） |
| 单口时延中位数 | ≤20s（仿真秒） |
| 安全 | zone_latches=0、envelope rejected=0、unexpected_failures=0 |
| 结局 | estop 口=aborted、done 口=rejected，其余 success |
| 审计 | trace 含全部 role_switch 事件；腕部通道收到的 T_base_flange 与黑板采样同源 |
