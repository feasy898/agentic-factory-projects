我按只读独立评审来做：先对照开发指令里的通过线，再逐项核对机械臂安全闭环、行为树、端到端脚本和报告，专门找绿灯没覆盖到的落差。仿真绿灯在 Mock 植物上是算出来的，但不能外推到舵机。有两处现码缺陷：急停复位后的第一段会继续朝未走完的途经点送入，生产口部通道的曝光窗用了另一套时钟。结论是需修后继续。下面按审查问题列出。

## A. 安全闭环真实性

- **[high]** `chengshao/cs_arm/mock_arm.py:276` — 放行后的运动是关节线性插值，植物与刚校验过的那条曲线重合；没有力矩、背隙、连杆柔顺或舵机抖动，`ViolationKind.TORQUE` 在全仓库没有置位路径。 — T10 在 `FeetechArm` 上加输出轴回读与重力方向的跟踪误差模型，包络用回读位形复检，力矩越限单独闩锁。
- **[high]** `chengshao/cs_arm/safety.py:157` — 下发给底层的是一个关节目标加一个标量 `max_speed`（`eff_joint_speed_rad_s`）；`feetech.py:16` 写明真机类不再做包络检查，`halt()` 在 `feetech.py:100` 直接抛 `HardwareUnavailable`。各舵机若写入同一速度寄存器，小行程关节会先到、路径离开已校验的线性插值。 — 按各关节 `|Δq|/T` 写速度，使六轴同时到位；到位前用回读做段级复检，急停走广播卸力矩而不是改目标位置。
- **[high]** `chengshao/cs_arm/eval_mock.py:351` — `≤100ms` 量的是 `estop()` 前后的 `time.perf_counter`，`reports/arm_mock_eval.json:22` 为 **0.058ms**，即 Python 闩锁耗时；冻结发生在 `VirtualClock` 上。e2e 的 **0.02 仿真秒**（`e2e_mock_run.py:560`，阈值 0.10）是驱动器在 `nodes.py:759` 于本拍 tick 之后注入、下一拍才被树看见的固定一拍。 — 墙钟另报「卸力矩指令发出到回读速度归零」，100ms 预算留给 USB 延迟定时器加舵机制动。
- **[med]** `chengshao/scripts/e2e_mock_run.py:122` — 禁入区间隙断言是 TCP `> 0`，报告值 0.05m，等于 `workspace.json:63` 的停点间隙；`arm_model.py:164` 的连杆点不含勺尖。勺尖伸出 0.08m，相对 0.05m 的 TCP 间隙，勺尖落在半径 0.12m 的球内约 0.03m。0.02m 余量是 `0.17−0.08−0.02−0.05` 的配置算术，采样轨迹没有勺尖点。 — 用勺尖位姿做段级间隙，阈值改为停点间隙减跟踪上界，而不是 `> 0`。

## B. 30 口 / 900 次切换是否同源自证

- **[high]** `chengshao/cs_orchestra/mock.py:399` — 注入脚本与 `SPEC_MEAL_EXPECTED_OUTCOMES` 写在同一字典旁；e2e 同样在 `e2e_mock_run.py:99` 与 `:106`。`tests/test_orchestra.py:79` 只断言转移表 docstring 里有关键词。`eval.py:243` 把同一 15 口脚本重复 30 回合（450 口、900 次切换），回合间只有 ±2mm 口部噪声和重舀 ±1cm。 — 转移表与期望结局挪到测试独占的金文件，30 回合改成互异脚本（皱眉、暂停、人脸丢失、咬合超时、勺不空各至少一回合）。
- **[high]** `chengshao/cs_orchestra/mock.py:172` — 「曝光稳定 ≥0.5s」是 `FakeMouthChannel` 用仿真钟做的无效帧窗口，窗口后直接吐 `face_center` 加噪声，没有相机、自动曝光或红外。生产通道 `runtime.py:68` 用 `time.time_ns()`，而 `set_role` 的时间戳来自 `core.py:791` 的 `perf_counter_ns`（mock 则是从 0 起的虚拟钟），两套纪元相减远大于 0.5s，稳定窗在真机路径上不会等待。断言还允许 `0.5−0.05s`（`eval.py:150`）。 — 口部通道与行为树共用同一时钟；稳定判据改为画面亮度/曝光寄存器收敛，并覆盖亮→暗与红外补光开启（`hardware.md` 现用台灯，代码里没有补光状态）。

## C. 行为树工程债

- **[med]** `chengshao/reports/orchestra_eval.json:337` — 单口中位 **19.74 仿真秒** 对应巡航 0.14m/s、近脸 0.08m/s、关节上限 1.5rad/s 的瞬时达速积分。`feetech.py:50` 只有这个 rad/s 常数，没有舵机速度寄存器换算，也没有加速斜坡。 — 标定「rad/s → 速度寄存器」和空载/持勺两条斜坡，用墙钟重算中位，再决定 ≤20s 是否仍成立。
- **[med]** `chengshao/scripts/e2e_mock_run.py:183` — 点菜和「吃饱了」走了真实 `IntentParser`，输入是写死的转写字符串；`select_1.wav` 只记名不解码，播报默认 `_QuietSpeaker`（`:134`）。转头是脚本 `head_yaw`，不是视觉。皱眉、暂停、下一口、人脸丢失、咬合超时、勺不空不在 `E2E_MEAL_SCRIPT` 里；`eval.py:178` 把 `pause==0` 且 `frown==0` 当作通过。 — 这些分支各加一条会失败的回归，e2e 至少跑通暂停与皱眉；wav 走解码或明确标成不覆盖 ASR。
- **[high]** `chengshao/cs_orchestra/nodes.py:191` — 急停/禁入区复位后的「原路退回」把 `aborted_journal` 整表逆序回放。journal 在 `core.py:524` 于指令发出时写入，急停发生在在途段，逆序的第一点就是还没到达的途经点，复位后第一段继续送入（步长 0.02–0.03m），然后才沿来路后退。回家段是新的笛卡尔 IK（`nodes.py:195`），与去程关节走廊不是同一条几何路径，只是再过一次同一个 `SafetyEnvelope.write`。转头（`nodes.py:349`）不退回，在途段会走完。禁入区单测在 `mock.py:466` 用 `teleport` 搬回家，真机没有这个操作。 — 逆序前丢掉未到达的末点，从当前回读位形向已到达的上一点退；回家段用去程关节序列而不是重新 IK；断言复位后 TCP 到口部的距离单调变大。

## D. 契约一致性

- **[low]** `chengshao/cs_schema/models.py:105` — `ArmCommand` 与 v1.1 对齐：`mode`、6 维 `target`、`max_speed`、`timeout_s`、`frame` 默认 `base`。行为树经 `ArmService` 发令，字段够用。`开发指令.md` §3.1 的表仍写 7 关节，与 `constants.py:12` 的 `N_ARM_JOINTS=6` 不一致。 — 把开发指令那张表改成 6，避免按旧表做 7↔6 映射。
- **[med]** `chengshao/cs_orchestra/core.py:91` — `camera_role` 取值 `scene` / `wrist_mouth` 与 `enums.py:27` 一致。`cam_pose` 两边都是米制 4×4，`T_base_cam = T_base_flange @ T_flange_cam`。名义手眼的平移（前 2cm、上 5cm）与注释一致，旋转不一致：注释和 `prior.py:47` 要求相机 X→法兰 −Y、Y→法兰 −Z，矩阵实际是 X→法兰 −Z、Y→法兰 +Y，绕光轴差 90°。当前树把嘴的 xyz 只记进 `aim_offset`，停点仍是固定 `delivery_stop_point()`，这 90° 还没进控制，一用嘴的位置瞄准就会偏。 — 把 `NOMINAL_T_FLANGE_CAM` 改成与 `prior` 同一套轴，并加一行「图像右方向量」单测。
- **[low]** `chengshao/cs_orchestra/core.py:752` — `BiteRecord.bite_id = idx-1`（第 12 口记成 11，e2e 用 `bite_id==11` 对急停），trace 里的 `bite` 仍是 1 起始。 — 对外记录与 trace 统一为 1 起始，看板断言跟着改。

## E. Windows / 真机预备

- **[med]** `chengshao/cs_arm/feetech.py:7` — 只记了两条传输（框架 follower 通道 / 厂商 Windows SDK）和「原生 Windows 可能失败」的回退（`开发指令.md:296`）。未记录：USB 串口默认延迟定时器约 16ms、CH340 上 1_000_000 波特不稳定、崩溃后 COM 口独占、急停需要广播卸力矩。这些直接吃掉 100ms 预算。`baudrate=1_000_000` 在 `feetech.py:48`。 — 在 `feetech.py` 的 bring-up 注释里写上上述四条，冒烟时测「卸力矩到回读停转」的墙钟。
- **[med]** `chengshao/scripts/demo_mouth.py:159` — 无相机时优先播 `face_demo_carousel.mp4`（文件在）。`imgio.py:58` 用默认 `VideoCapture`，中文路径失败再复制到临时文件；Windows 上默认 MSMF，不锁帧序、不校验帧号。`auto` 会先试 device 0，插着摄像头就不是视频。视频也打不开时，`bundled/*.jpg` 的排序轮播是确定的；卡通源用 `perf_counter`，不确定。 — 无相机演示固定 `--source bundled` 或按帧序号解码，并断言首帧哈希。

## F. 公开仓库卫生

- **[low]** `chengshao/requirements.txt:70` — `check_naming.py` 对 requirements 的包名放行，故 `lerobot==0.6.1` 与 `:55` 的 `huggingface_hub` 会留在清单里。扫描不看路径，`chengshao/training/act/` 这种目录名不会被扫到。`_vendor/` 已在 `.gitignore:42`。关节名 `shoulder_pan` 等写在 `reports/sim_eval.json:9`，黑名单未覆盖。`plan/hardware.md` 在仓库外，正文里是上游检索词，公开时不能把 `plan/` 一并带上。 — 黑名单加上路径片段；公开包把训练依赖移出运行时 requirements，或在发布清单里单独豁免并注释。

## G. 工程债 Top 5

| 排序 | 风险 | 是否阻塞 T10 真机 bring-up |
|---|---|---|
| 1 | 急停复位后第一段继续送入（C 的 high） | 阻塞安全演练。串口冒烟可以先做，带人的运动不行 |
| 2 | 包络只约束指令曲线；真机单速度寄存器、柔顺和背隙会走出包络，且底层不再复检（A 的前两条） | 阻塞把「0 违规」当成真机结论。不阻塞第一版读位置 |
| 3 | 生产曝光窗时钟纪元不一致，900 次切换全部发生在假口部通道上（B 的第二条） | 阻塞腕部双职接通。不阻塞舵机标定 |
| 4 | 急停 100ms / 0.02s 都不是「指令到机构停转」的墙钟；Windows 串口延迟未写入实现备注（A 的第三条 + E） | 阻塞安全计时签字。不阻塞 `connect()` |
| 5 | 名义手眼绕光轴 90°，加上 19.7s 没有舵机换算（D 的 med + C 的 med） | 不阻塞上电。阻塞「按嘴的位置停勺」和「单口 ≤20s」的真机声称 |

转移表同源、皱眉/暂停未进 e2e、TCP 间隙阈值 `> 0`、`bite_id` 从 0 计，都低于这五项，不单独挡住上电。

**总体结论：需修后继续。** G4 作为无硬件演示的记录可以留档（30 口闭环、仿真中位 19.74s、Mock 上 0 次包络拒绝这些数字和报告一致）。T10 在第 1 到第 3 项修完并换成非同源断言之前，不应开始真机安全演练或腕部相机接通。
