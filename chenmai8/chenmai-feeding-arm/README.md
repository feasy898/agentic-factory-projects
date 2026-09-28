# 澄勺 · 桌面助餐机械臂

面向上肢功能障碍、吞咽正常的失能/半失能老人与残障人士的桌面助餐机器人。

**核心能力（v3 形态：单从臂 + 腕部相机 + 软件急停，无深度相机）**

- 舀取：脚本化参数化舀取（ScriptedScoop，腕部相机闭环 + 失败重试）；
  学习型舀取策略为**延后项**（见 `chengshao/training/`，只含脚本/配置，
  当前交付不依赖其产出）
- 口部定位：人脸关键点单目估计——顶部相机固定先验距离（回退路径）；
  腕部相机双职主模式按瞳距（IPD）测距（契约 v1.1），无深度相机
- 安全送达：逆运动学限速送达 + 安全包络（面部球域 / 躯干胶囊 / 限速场 /
  关节角速度上限），送达停点在禁入球外并有数值安全余量断言，软件急停
- 自然交互：语音指令（下一口 / 等一下 / 吃饱了）、张嘴触发、语音播报
- 进食数据：每餐口数、时长、摄入克数自动记录，护理看板与推送

**仓库结构（建设中）**

```
.venv/          Python 3.12 虚拟环境（仓库根）
tests/          跨模块 pytest（pytest 自仓库根运行）
chengshao/
  cs_schema/     数据契约：跨模块数据结构与枚举的唯一事实来源（契约冻结 v1.1）
  cs_sim/        仿真：模型加载、FK/IK、可达空间、安全包络验证、对抗性 oracle
  cs_arm/        执行：机械臂接口（契约 v1.1 六关节）+ Mock 臂（cs_sim 虚拟执行）
                 + SafetyEnvelope 硬闸（限速/禁入区/软急停/看门狗）+ FeetechArm 骨架
  cs_mouth/      感知：口部三维估计（mono 主路径 + depth 保留 + 腕部 IPD 模式）
  cs_food/       感知：勺上食物检查（启发式基线）、选碗
  cs_voice/      交互：离线语音识别、意图解析、语音播报
  cs_orchestra/  编排：行为树（进食全流程 + 安全打断分支）
  cs_dashboard/  数据：护理看板（HTTP + SQLite + 实时刷新）
  training/      延后训练资产：脚本/配置（只写不跑，真实训练在 GPU 机）
  scripts/       演示、标定、采样与检查脚本
  assets/        人脸 / 语音 / 勺上帧等样本资产
  config/        工作区、先验与限位等默认配置
  reports/       逐模块 eval 报告 JSON（评审证据链）
scripts/         gate_g1.py 门禁与 verify_g1_reports.py 报告独立复核
```

> 详细模块规格与验收标准见 `docs/`，逐模块 spec+eval 驱动开发。

## 模块进度

| 模块 | 状态 | 验收 |
|---|---|---|
| cs_schema | 契约冻结 v1.1 | `pytest tests/test_schema.py` |
| cs_food | 勺上检查接口 + 启发式基线（合成自检） | `pytest tests/test_food_interface.py` |
| cs_dashboard | 看板骨架 | `pytest tests/test_dashboard.py` |
| cs_mouth | 口部三维估计（mono 主路径 + depth/腕部 IPD 保留） | `python -m cs_mouth.eval`（包根下执行） |
| cs_sim | 仿真：FK/IK/可达空间/安全包络 + 独立违规轨迹 oracle | `python -m cs_sim.eval`（包根下执行） |
| cs_voice | 离线语音链路 | `python -m cs_voice.eval`（包根下执行） |
| cs_arm | 执行层：MockArm（cs_sim 虚拟执行）+ SafetyEnvelope 硬闸 + FeetechArm 骨架 | `pytest tests/test_arm_mock.py` + `python -m cs_arm.eval_mock`（包根下执行） |
| cs_orchestra | 未开工（行为树在 G3 起，消费 cs_arm 硬闸） | — |

一键门禁：`python scripts/gate_g1.py`（命名扫描 + 全量 pytest + 各模块
eval + 报告独立复核 + 看板冒烟）。

### cs_mouth：口部三维估计

单目 + 先验尺度为演示主路径：人脸 478 关键点定位口中心，顶部相机模式下
距离取先验（`chengshao/config/mouth_prior.json`，默认 0.42m，横纵误差
±3–5cm，由"勺停口前 + 用户前倾取食 + 座位定位垫"设计吸收）；腕部双职
模式（契约 v1.1 的 `mode=ipd`）按瞳距测距，接口已冻结、待腕部视角实拍
样本验收；深度后端接口不变、延后保留。张嘴用几何口径比（实测静帧上
blendshape jawOpen 不区分张闭嘴，见 `chengshao/assets/face_samples/README.md`
的实测记录），转头判定 `|head_yaw| > 25°`（双向），皱眉用 mouthFrown。

```bash
# 环境准备（一次性，权重不入库）
python chengshao/scripts/fetch_models.py

# 验收（在 chengshao/ 包根下执行；报告落 reports/mouth_eval.json）
cd chengshao && python -m cs_mouth.eval --input assets/face_samples --report reports/mouth_eval.json

# 后补真机样本（手机视频 → 抽帧 + 半自动标签初稿）
cd chengshao && python scripts/import_face_samples.py --video 前面.mp4 转头.mp4 皱眉.mp4
```

样本说明（来源 / 许可证 / 标签规范 / 实测数据）：`chengshao/assets/face_samples/README.md`。

