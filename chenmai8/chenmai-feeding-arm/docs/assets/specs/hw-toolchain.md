# hw-toolchain spec（真机工具链：FeetechArm + bring-up + 真机 eval 清单）

> 状态（2026-10-02 更新）：**B1 已交付**（tag `sw-b1-bringup-v1.0`）——§3 的五个真机入口
> （calibrate_handeye / camera_check / safety_drill / cs_arm.eval_hw / cs_arm.eval_scoop）
> 均已实现：mock dry-run 全绿（pytest 21 用例 + 6 份 mock 证据 JSON），真机分支
> fail-closed（exit 2 / HardwareUnavailable）。**真机 eval 结论仍待 T10 硬件 bring-up
> 实测**——本文"当前均无实现入口"的旧表述已作废。
> 本页其余部分对照 `chengshao/cs_arm/feetech.py` 与开发指令 §5.9（2026-09-29 核验）。
> 独立复核修复记录（2026-10-02）：失败标定不得落 `config/calib/`（防失败外参被装载，
> calibrate_handeye 已加安全闸）；eval_scoop 混合食物参数来源 bug 已修；camera_check
> 模块 docstring 过强表述已订正。

---

## 1. 已冻结的占位（当前仓库真实存在）

- `FeetechArm(ArmInterface)`：**骨架**——所有触达硬件的方法（read/write/enable/disable/
  halt/connect）抛 `HardwareUnavailable`，宁可拒绝不装作成功（feetech.py:82-121）。
- `FeetechArmConfig`（参数结构冻结）：`port=""`、`baudrate=1_000_000`、
  `servo_ids=(1..6)`（恰 6 个互异正整数，下标 5=夹爪）、`joint_speed_limit_rad_s=1.5`、
  `return_delay_time_us=250`、`torque_enabled_by_default=False`、`extra`（现场标定参数）。
- 传输层二选一（接口不变）：A = 上位机机器人框架的 follower 舵机通道适配（该 pip 依赖已在
  requirements.txt 以包名锁定——**发行名仅允许出现在依赖清单的包名位**，文档一律用中性
  描述"机器人学习运行栈"，内部代号 vendor-robot-stack）；
  B = 舵机厂商官方 Windows SDK 直连（`feetech-servo-sdk==1.0.0` 已锁定；回退 A 在原生
  Windows 实测失败时启用，开发指令 §9 风险表）。
- 语义约定（T10 实现必须遵守）：全部运动仍经 `SafetyEnvelope` 下发（本类不重复包络检查，
  硬闸单点在包络层）；看门狗心跳由**控制活动**驱动——串口巡检读数提供 `snapshot_state`
  快照而不喂心跳（与 MockArm 同语义，mock_arm.py:152-161）；`halt()` 立即冻结。

## 2. bring-up 流程（硬件到货 D3 起；骨架阶段不可执行）

1. **舵机标定**：中位/限位/回读一致（标定入口随 T10 提供）；
2. **单臂冒烟**：6/6 舵机连通、限位/温度正常、TPU 夹爪开合正常（`connect()` 校验 6/6 在线）；
3. **手眼标定（顶部相机 eye-to-hand）**：产出 `config/calib/handeye_scene.npz`
   （key：`T_base_cam`, `reproj_err_mm`）；通过线：重投影残差 ≤3mm 或 ≤2px；
4. **腕部手眼标定（eye-in-hand）**：板固定桌面、动臂采 15 位姿，产出
   `config/calib/handeye_wrist.npz`（key：`T_flange_cam`）——标定后覆盖
   `cs_orchestra.core.NOMINAL_T_FLANGE_CAM` 名义值（core.py:88-111 的装载顺序已实现：
   npz 优先、名义值兜底）；
5. **相机验收**：顶部 2MP（基准码可辨）+ 腕部 1MP 双职验收（20–50cm 面部可辨、最近对焦
   达标、亮→暗曝光恢复 ≤1s、臂全行程线缆无牵扯）；不达标 → 触发既定回退（加购专职人脸
   相机第三路，相机接口已抽象为可配置多路）。

## 3. 真机 eval 清单（**全部 planned——命令入口未实现**，开发指令 §5.9 原表）

| eval | 计划命令（未实现） | 通过线 |
|---|---|---|
| 单臂冒烟 | 标定入口（T10）+ `python -m cs_arm.eval_hw` | 6/6 舵机连通、回读一致、限位/温度正常、夹爪开合 |
| 顶部手眼 | `python scripts/calibrate_handeye.py --cam scene --points 12 --out config/calib/handeye_scene.npz` | 残差 ≤3mm 或 ≤2px |
| 腕部手眼 | `... --cam wrist --mode eye-in-hand --points 15 --out config/calib/handeye_wrist.npz` | 残差 ≤3mm 或 ≤2px |
| 相机验收 | `python scripts/camera_check.py` | §2 第 5 步各条 |
| 口部先验尺度 | `python -m cs_mouth.eval --static-distance --report reports/mouth_prior_eval.json` | 0.35/0.45/0.55m 三点误差 ≤5cm（**记录项不阻塞**，超线只修 mouth_prior.json；`--static-distance` 入口已实现，config 缺失 exit 2） |
| 腕部口部追踪 | `python -m cs_mouth.eval --wrist-view --live --report reports/mouth_wrist_eval.json` | 20/30/40/50cm 四点估距误差 ≤4cm；检出率 ≥95%；曝光切换恢复 ≤1s；送达全程帧流不中断（`--wrist-view` 离线入口已实现，样本缺失 exit 2） |
| 脚本舀取成功率 | `python -m cs_arm.eval_scoop --food <each> --trials 50` | 最终成功率（含闭环重试）≥90%、首次 ≥70%，分食物报告 |
| 安全实测 | `python scripts/safety_drill.py --cases head_turn,estop,face_intrude --trials 20`（estop=空格键软件急停 latch） | 20/20 停止或后撤；禁入区侵入 0 次 |

- 硬件形态（v3 决策，中性描述）：桌面 6 舵机单从臂（12V 版舵机 ×6 + 驱动板 + 电源 +
  TPU 夹爪），顶部 2MP + 腕部 1MP 双相机（套装自带）；无深度相机、无急停硬件
  （软件急停=空格键 latch 包络）；食品级硅胶软勺固定于夹爪。
- 采购/卖家核实清单与预算在项目内部 plan 文档（不入公开仓）。
