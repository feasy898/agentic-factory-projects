# 澄勺 · 桌面助餐机械臂

面向上肢功能障碍、吞咽正常的失能/半失能老人与残障人士的桌面助餐机器人。

**核心能力**

- 学习型舀取：从示教数据学习不同食物、不同碗位的舀取策略
- 安全送达：人脸关键点 + 深度估计定位口部，逆运动学限速送达，禁入区 + 急停多重防护
- 自然交互：语音指令（下一口 / 等一下 / 吃饱了）、张嘴触发、表情响应
- 进食数据：每餐口数、时长、摄入克数自动记录，护理看板与推送

**仓库结构（建设中）**

```
.venv/          Python 3.12 虚拟环境（仓库根）
tests/          跨模块 pytest（pytest 自仓库根运行）
chengshao/
  cs_schema/     数据契约：跨模块数据结构与枚举的唯一事实来源（契约冻结 v1.0）
  cs_sim/        仿真：模型加载、FK/IK、可达空间、安全包络验证
  cs_arm/        执行：机械臂接口 + Mock 臂 + 真机通道 + 安全包络执行器
  cs_mouth/      感知：口部三维估计（单目 / 深度双后端）
  cs_food/       感知：勺上食物检查、选碗
  cs_voice/      交互：离线语音识别、意图解析、语音播报
  cs_orchestra/  编排：行为树（进食全流程 + 安全打断分支）
  cs_dashboard/  数据：护理看板（HTTP + SQLite + 实时刷新）
  scripts/       演示、标定、采样与检查脚本
  assets/        人脸 / 语音 / 勺上帧等样本资产
  config/        工作区、先验与限位等默认配置
  reports/       逐模块 eval 报告 JSON（评审证据链）
```

> 详细模块规格与验收标准见 `docs/`，逐模块 spec+eval 驱动开发。

## 模块进度

| 模块 | 状态 | 验收 |
|---|---|---|
| cs_schema | 契约冻结 v1.0 | `pytest tests/test_schema.py` |
| cs_food | 勺上检查接口 + 启发式基线 | `pytest tests/test_food_interface.py` |
| cs_dashboard | 看板骨架 | `pytest tests/test_dashboard.py` |
| **cs_mouth** | **口部三维估计（mono 主路径 + depth 保留）** | `python -m cs_mouth.eval`（包根下执行） |

### cs_mouth：口部三维估计

单目 + 先验尺度为演示主路径：人脸 478 关键点定位口中心，距离取先验
（`chengshao/config/mouth_prior.json`，默认 0.42m，横纵误差 ±3–5cm，由
"勺停口前 5cm + 用户前倾取食 + 座位定位垫"设计吸收）；深度后端接口不变、
延后保留。张嘴用几何口径比（实测静帧上 blendshape jawOpen 不区分张闭嘴，
见 `chengshao/assets/face_samples/README.md` 的实测记录），转头判定
`|head_yaw| > 25°`（双向），皱眉用 mouthFrown。

```bash
# 环境准备（一次性，权重不入库）
python chengshao/scripts/fetch_models.py

# 验收（在 chengshao/ 包根下执行；报告落 reports/mouth_eval.json）
cd chengshao && python -m cs_mouth.eval --input assets/face_samples --report reports/mouth_eval.json

# 后补真机样本（手机视频 → 抽帧 + 半自动标签初稿）
cd chengshao && python scripts/import_face_samples.py --video 前面.mp4 转头.mp4 皱眉.mp4
```

样本说明（来源 / 许可证 / 标签规范 / 实测数据）：`chengshao/assets/face_samples/README.md`。

