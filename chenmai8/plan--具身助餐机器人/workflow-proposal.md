# workflow-proposal —— 构建阶段任务建议（供主会话构建工作流逐任务下发）

> **v3 硬件决策（2026-09-28 主人）已吸收**：单从臂、无深度相机（mono 主路径）、软件急停、无称重/补光/扩展坞、舀取主路径=ScriptedScoop。
> **G0–G4 任务与全部冻结契约不受 v3 影响，正在构建中，勿动。**
> 每个任务 = "实现模块（或资产）+ 跑其 eval 至绿 + reports/ 落证据 + git commit"。
> DoD 统一按 开发指令.md §10；验收命令一律可在本机无 GPU、无硬件执行。
> 并行组 = 组内任务互不依赖，可同时派发子代理；组间按依赖顺序。

## 任务总表

| ID | 任务 | 产出 | 验收（eval） | 依赖 | 并行组 | 需 GPU 机 |
|---|---|---|---|---|---|---|
| T0 | 环境与仓库骨架 | chengshao/ git 仓库、venv、requirements.txt 全装、upstream 四仓克隆并锁 commit（回填 oss-manifest §5）、目录模板 | `pip check`；`python -c "import mujoco,mediapipe,py_trees,funasr"` | — | G0 | 否 |
| T1 | cs_schema | §3.1 全部 pydantic 模型 + 枚举 + fixtures | `pytest tests/test_schema.py` | T0 | G0 | 否 |
| T2 | cs_sim | 模型加载（回退链：MJCF→URDF→ikpy 链）、FK/IK、可达空间、安全包络校验器 | `python -m cs_sim.eval ...`（通过线见 开发指令 §5.1） | T1 | G1 | 否 |
| T3 | cs_mouth | mono 后端 + eval 工具 + face_samples 导入脚本 | `python -m cs_mouth.eval ...` | T1 | G1 | 否 |
| T4 | cs_voice | SenseVoiceSmall ASR + 意图解析 + pyttsx3 TTS + eval | `python -m cs_voice.eval ...` | T1 | G1 | 否 |
| T5 | cs_dashboard | FastAPI+SQLite+SSE+本地化单页看板 | `pytest tests/test_dashboard.py` + 截图 | T1 | G1 | 否 |
| T6 | cs_arm(Mock) | ArmInterface/MockArm/SafetyEnvelope + mock eval | `pytest tests/test_arm_mock.py` + `cs_arm.eval_mock` | T1,T2 | G2 | 否 |
| T7 | cs_food | 接口 + HSV 启发式 + ArUco 选碗 + 接口测试 | `pytest tests/test_food_interface.py` | T1 | G1 | 否 |
| T8 | cs_orchestra | 行为树全节点 + 注入式 mock eval（30 回合）+ **v3.1 相机角色切换时序断言**（camera_role 每口 2 次，见 开发指令 §5.6） | `python -m cs_orchestra.eval --mock` | T2,T6,T7 | G3 | 否 |
| T9 | e2e mock + 无硬件演示三脚本 | scripts/e2e_mock_run.py、demo_sim.py、demo_mouth.py、check_naming.py | `python scripts/e2e_mock_run.py`（§5.8 通过线） | T3,T4,T5,T8 | G4 | 否 |
| T10 | 单从臂 bring-up 工具链 | scripts/calibrate_handeye.py（**含 eye-in-hand 腕部模式**）、camera_check.py（**含腕部双职验收：近距对焦/曝光切换/线缆余量**）、safety_drill.py（含空格键软件急停 drill）、cs_arm/FeetechArm 封装（单从臂直连，lerobot so101_follower 或 feetech SDK 传输层）+ 单臂冒烟 runbook | 真机 eval 表前四行：单臂冒烟/顶部手眼/腕部手眼/相机验收（到货后） | T6, 硬件到货 | G5 | 否（本机接臂） |
| T11 | 训练资产包（延后，只写不跑） | chengshao/training/ 全部脚本+配置+COS 传输脚本+GPU 机 runbook（ACT 立项后才执行） | `pytest tests/test_training_scripts.py`（dry-run/参数解析/路径检查） | T1 | G5 | 延后（ACT 立项才用） |
| T12 | 脚本舀取调参与成功率评测 | 逐食物 ScriptedScoop 轨迹参数集（入 config/）、闭环重试阈值、成功率报告（每食物 50 次：最终 ≥90%/首次 ≥70%） | `python -m cs_arm.eval_scoop --food <each> --trials 50` 达标；报告落 reports/ | T10 | G6（D4–D5） | 否 |
| T13 | 真机全链集成 | ScriptedScoop 接入行为树（ActPolicy 预留不实现）、**腕部双职 ipd 模式上线（cam_pose=FK×腕部手眼）+ camera_role 切换接入**、顶部 fixed 先验为回退、看板口数/时长（称重延后）、软件急停全场景演练 | §5.9 全表 | T9,T10,T12 | G6（D5–D7） | 否 |
| T14 | 安全实测+试用+演示物料 | safety_drill 报告、5–10 人试用记录表、演示视频 3 段、BOM/安全说明 | §5.9 安全行；视频成片检查单 | T13 | G7（D8–D9） | 否 |

## 派发建议

- **G0→G1 串行，G1 内部 T2/T3/T4/T5/T7 五路并行**（互不依赖，且都只依赖 T1 的契约）——这是最大并行窗口，D1 下午到 D2 上午完成。
- G2/G3 串行短链（T6→T8），因为行为树要消费 MockArm 与 cs_sim。
- **G4（T9）是 D2 晚硬闸门**：不过不睡。过了它，项目进入"硬件什么时候到都稳"状态。
- G5（T10/T11）可与 G1–G4 并行预写，但 FeetechArm 真机验证必须等硬件（预期 D3）。
- 需要人工插入的节点（不可自动化，子代理不要尝试跳过）：
  1. T0 前主人完成 hardware.md 下单（v3：单从臂套装 ×2 家卖家）；
  2. T3/T4 的样本由主人手机录制后用导入脚本入库；
  3. T10 单从臂组装验收/标定需真人在场；
  4. T12 舀取调参与试喂必须真人在场（安全）；
  5. D2 养老院访谈（概念文档排期项，与工程并行）。
- 每个子代理 prompt 模板：`实现 <模块> 于 chengshao/<pkg>，遵守 plan/开发指令.md §3 契约与 §5.x spec，完成后执行 <eval 命令>，报告 JSON 落 reports/，DoD 见 §10。禁止引入上游项目名（check_naming.py 必须过）。`
- 回退触发：任一任务 eval 连续 2 轮不过 → 按 开发指令.md §9 回退表执行（例：T2 模型问题→URDF→ikpy 链；T12 某食物不达标→换食物/参数扫参/收紧闭环阈值；FeetechArm Windows 失败→feetech SDK 直连传输层）。
- **GPU 机排期（v3）**：训练全部延后，当前无 GPU 机任务；若赛后 ACT 立项，按 training-plan.md §5 runbook 执行（T11 资产包届时已备好）。其余一切在本机。
