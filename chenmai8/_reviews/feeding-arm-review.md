这是一次只读的独立评审。我先读规划、门禁脚本和各模块实现，再对照 eval 报告核对安全主张是否真有实证。总体结论：**需修后继续。** `scripts/gate_g1.py` 只认子进程退出码，这层「脚本会红」可信；报告里的「500 条 100% 拒」和「五项 1.000」是模块用自己生成的样本给自己打分，不能当作靠近人脸的安全实证。真机送达之前要先改关节契约和禁入区几何。

## A. 安全主张的实证强度

1. **[high]** `chengshao/cs_sim/eval.py:229` — 500 条全是同一校验器能认出的笛卡尔 TCP 折线：150 条终点塞进面部球、100 条塞进躯干胶囊、125 条把路程/时间做成 0.4–0.9 m/s、125 条贴着球面做 0.11–0.14 m/s；`sim_eval.json:116` 里「超速」类同时出现 `zone`，拒绝原因没有按预定类别拆开。生成器与 `EnvelopeValidator.check_trajectory` 共用同一套线段距离，100% 拒是自洽，不是独立oracle。关节角速度、可操作度、肘/连杆扫掠、关节空间插值把 TCP 带进禁区，都没有样本。修复：另写关节轨迹生成器，经 FK 后要求「预定违规类别命中」，并加连杆胶囊与关节速度上限。

2. **[high]** `chengshao/cs_sim/eval.py:89` — IK 的 200 个目标由随机关节角做 FK 得到，按构造可达；99.5%（199/200）量的是阻尼最小二乘的收敛，`ik_solver.py:103` 只加大阻尼、不因奇异拒绝。`restarts_used_max=27` 说明有目标靠 32 次重启才过。修复：对口前 5 cm 那一片工作空间单列 IK，并在可操作度低于阈值时判失败。

3. **[high]** `chengshao/cs_sim/safety_envelope.py:280` — `check_joint_trajectory` 只对采样点的 TCP 做弦检，eval 从未调用；关节空间弧线可以弦在球外、弧在球内。修复：对关节段做更密的 FK 采样，或对 TCP 弧与禁区做连续相交。

4. **[high]** `tests/test_sim.py:261` — 口前 5 cm 的停点被单测写明落在 r=0.12 m 的面部球内；`register_delivery_target(..., 0.03)` 把球内线段的禁入判定拿掉。豁免要求线段两端都在 3 cm 球内（`safety_envelope.py:186`），从球外走入该球的那一段仍然判入侵，名义送达在当前规则下走不通。500 条 eval 明确不登记豁免（`safety_envelope.py:19`）。修复：停点改到球面之外，豁免半径单独论证，并加一条「从碗到停点」的整段轨迹测试。

5. **[high]** `chengshao/reports/mouth_eval.json:46` — 「±3–5 cm、勺停口前 5 cm」只写在 `error_band_note` 字符串里，指标里没有间隙。上界 5 cm 对 5 cm 停距，沿接近方向的余量是 0；TCP 是 `gripperframe`（`backends.py:14`），勺头伸出量未建模。修复：在 eval 里计算 `停距 − 误差上界 − 勺头伸出 − 跟踪误差`，要求结果大于 0 才允许 `pass`。

6. **[high]** `chengshao/cs_mouth/eval.py:109` — 「五项 1.000」的检出池是 40 张 bundled + 12 张卡通（`detect_frames=52`）。bundled 来自 5 张 NASA 公版种子各 8 个光度/翻转/缩放变体，标签从种子复制且 `draft=false`（`bootstrap.py:66`）。拒识 4 帧全是 `draw_no_face`。张嘴 24 帧、转头 8 帧各来自 1–3 个身份。没有腕部视角、没有老年人脸、没有估距误差数字。修复：检出率分「真人种子 / 变体 / 卡通」三列；腕部 20–50 cm 样本和 IPD 误差进硬门槛，卡通不进分子。

7. **[med]** `chengshao/cs_mouth/estimator.py:202` — 距离永远是 `prior.distance_m`（0.42 m）。虹膜点 468/473、`Z = fx×0.063/ipd_px`、`cam_pose` 都不在这条链路里，报告里的误差带没有被这次 eval 测量。修复：IPD 模式单独出 `mouth_wrist_eval.json`，用已知距离的样本报误差分布。

## B. 假绿灯

8. **[high]** `scripts/gate_g1.py:147` — 门禁以 eval 进程退出码为通过，不回读 JSON、不重算指标。`pass` 由写报告的同一段代码赋值（`cs_sim/eval.py:439`、`cs_mouth/eval.py:222`）。阈值写错或分子被合成帧灌满时，退出码仍为 0。修复：门禁用独立脚本只读 `metrics` 与 `thresholds` 重算 `checks`，与模块自报 `pass` 不一致则失败。

9. **[med]** `chengshao/cs_voice/eval.py:42` — 语音 20/20 的 wav 由同一台 SAPI 按关键词合成（`gen_voice_samples.py:3`），标签就是合成文本。离线证据只钩 `socket.socket.connect`，报告自己写明拔网线未做（`voice_eval.json:51`）。修复：真人麦样本进硬门槛；外联改钩 `getaddrinfo` 与 HTTP 客户端，或在断网环境跑。

10. **[med]** `chengshao/cs_food/eval.py:148` — `food_eval.json` 的 `pass:true` 来自程序画的色块和 ArUco，阈值就是「合成集必须全对」。G1 不跑这条命令。真实帧路径还不设硬线，却仍写 `pass`。修复：合成自检改名为 `self_check`，`pass` 只留给有人工标签的真实帧。

## C. 契约一致性

11. **[high]** `chengshao/cs_schema/constants.py:10` — 冻结 `N_ARM_JOINTS=7`（注释写成「6 臂 + 夹爪」），`tests/test_schema.py:414` 把 7 锁死。仿真模型是 6（5 臂 + 夹爪，`backends.py:11`，`sim_eval.json:8`），§5.9 也是 6 个舵机。映射被推迟到尚不存在的执行层。修复：在臂代码写下之前把契约改成 6，并改夹具与该断言。

12. **[high]** `chengshao/cs_mouth/estimator.py:50` — v3.1 的 `pose_provider`、`from_bgr(..., cam_pose=)`、`mouth_prior.json` 的 `mode`、黑板 `camera_role` 都没有进已冻结代码。`MouthSource` 只有 `depth|mono`（`enums.py:12`）。`cs_orchestra/__init__.py:3` 的黑板列表没有 `camera_role`。`cs_mouth/eval.py:80` 没有 `--wrist-view`。规划写明 G0–G1 可以不改签名，因此当前绿灯不覆盖腕部双职。修复：G2 动行为树之前先发一版契约修订，把 `camera_role`、`cam_pose`、`ipd` 写进 schema 和 prior。

## D. Windows

13. **[med]** `chengshao/cs_food/eval.py:117` — 真实勺帧用 `cv2.imread`。本仓库路径含中文时 OpenCV 会静默返回空，函数再抛「帧读取失败」。口部侧已用 `imgio.py:21` 的 `np.fromfile` 绕开。修复：食物与相机落盘一律走 `imread_u` / `imwrite_u`。

14. **[med]** `chengshao/cs_voice/tts.py:131` — `say()` 在新线程里 `Dispatch("SAPI.SpVoice")`，没有 `pythoncom.CoInitialize()`，并且线程启动后立刻 `return True`。eval 只走临时目录里的 `save_to_file`（这次 `synth_ok:true`），不覆盖播放线程。修复：播放线程先 `CoInitialize`，`say()` 的返回值改为播报线程的实际结果。

15. **[low]** `scripts/gate_g1.py:78` — 子进程已设 `PYTHONUTF8=1`，报告以 UTF-8 写入。这层编码坑已经盖住。

## E. 公开仓库卫生

16. **[med]** `chengshao/scripts/check_naming.py:130` — 文件头写明一级禁用词（含 `huggingface`）连依赖清单也要扫，循环却把整个 `requirements*.txt` 跳过。`requirements.txt:3` 的手写注释、`:55` 的 `huggingface_hub`、`:70` 的 `lerobot` 因此不可见。`_vendor/` 已在 `.gitignore:42`，`upstream_lock.md` 用了中性代号，这两处处理是对的。修复：清单只放行包名白名单，注释和其余文本仍扫；删掉第 3 行里的上游项目名。

17. **[low]** `README.md:7` — 公开首页仍写「学习型舀取」和「深度估计定位口部」。当前实现是固定先验单目加未训练的启发式勺检。修复：改成与 v3 一致的单从臂、腕部相机、软件急停表述。

## F. 工程债 Top 5

| 排序 | 风险 | 是否挡住后续真机 |
|---|---|---|
| 1 | 禁入球 r=12 cm 与「停嘴前 5 cm」重叠，豁免把球内线段放行，且没有「最坏仍不接触」的数值；包络只看 TCP 折线 | **挡住。** 任何靠近人脸的伺服运动都不能开始 |
| 2 | 契约 7 关节 vs 模型/舵机 6 关节，执行层还没写映射 | **挡住 G2 臂接口。** 现在改只碰夹具和一条断言 |
| 3 | 软件急停、看门狗、`SafetyEnvelope` 执行器不存在（`cs_arm/__init__.py` 只有文档字符串）；唯一急停是空格键 | **挡住真机上电。** 不挡住继续写纯仿真节点，但仿真节点也不能下发未被包络包住的 `ArmCommand` |
| 4 | 腕部双职 / IPD / `camera_role` 停在规划文，未进冻结契约；口部 1.000 与语音 20/20 都是自产样本 | **挡住把 G1 数字当成送达感知的依据。** 行为树可以在契约修订后开工 |
| 5 | 食物真实帧 `cv2.imread` 与 TTS 播放线程的 COM 初始化 | **挡住 D4 勺帧 eval 和现场播报。** 不挡住当前合成自检 |

G1 可以保持「这些命令在这台机器上退出码为 0」这个含义。把它读成「违规轨迹已被证明挡得住、口部误差已被证明吃得下」会在真机送达阶段翻车。
