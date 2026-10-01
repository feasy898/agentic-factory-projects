# training-plan —— 延后训练任务清单（只设计，不在本机执行）

> **v2（2026-09-28 主人硬件决策 v3 后修订）**：单从臂方案下**无主臂可遥操作，ACT 整体延后**，本计划降级为"延后叙事 + 将来启动条件"；演示版舀取主路径=ScriptedScoop（见 开发指令.md §5.6），不依赖本计划任何产出。
> 纪律：本机（windev-01，无 GPU）只做数据准备脚本与训练脚本；真实训练一律在 anolis-gpu-01
> （2×V100S-32GB，AnolisOS 23.5，tailnet [内网地址已脱敏]）执行，**且仅当 ACT 立项后**启动。
> 训练框架走 `lerobot[training]==0.6.1`（Apache-2.0，训练入口 `lerobot-train --policy.type=act`，已核实 2026-09-28）。

## 1. 示教数据采集协议（ACT 舀取）【延后——当前无主臂，全文备查】

> **启动前置条件（二选一，届时再决策）**：
> - 方案 A：补购 SO-101 主臂（¥1000–1500 追加），标准主从遥操作采数（质量高，推荐）；
> - 方案 B：**拖动示教**（零硬件成本）——从臂扭矩关闭后手拖执行，用 cs_arm 的 `ArmInterface.read()` 以 30–50Hz 录关节流+相机帧（需写一个小录制脚本，属 T11 资产包范围）。代价：轨迹一致性差，条数需上浮约 +50%，且手部入镜需裁剪/裁视场。

### 1.1 覆盖矩阵与条数
| 维度 | 取值 |
|---|---|
| 食物 | 芋泥（黏稠）、南瓜粥（糊状）、椰子冻（固态滑）3 种（海南本地，评委可感） |
| 碗位 | 定位餐垫上 3 个孔位（中心 ±8cm） |
| 剩余量 | 满/半/少（≈1/3）三档，采集中自然递减覆盖 |
| 光照 | 正常 + 补光灯两档（演示现场光照兜底） |
| 条数 | 3 食物 × 3 碗位 × 30–40 条 ≈ **300 条**（每条 = 舀一勺完整回合 10–20s） |
| 纠错 | 额外 10–15%（35–45 条）"没舀到→抬升→再舀"的连贯示教（教策略自恢复） |
| 对照 | 每食物另录 5 条脚本舀取（固定关节轨迹）用于成功率对照 |

### 1.2 录制规格
- 工具：`lerobot-record`（lerobot 0.6.1 实际 CLI 参数以 `lerobot-record --help` 为准）；方案 A=主臂遥操作；方案 B=拖动示教自制录制脚本（输出对齐 LeRobotDataset 格式）。
- 相机：场景相机（看碗/勺/可兼面部）+ 腕部相机（勺尖闭环）2 路，分辨率 640×480、fps 30；关节 6 通道（单从臂，含夹爪则 7）。
- 数据集：`repo_id=cs/spoon_scooping_v1`，LeRobotDataset 格式（由录制工具生成，格式版本不硬编码，`lerobot-dataset-viz` 验收）。
- 质检：每 50 条抽看 5 条回放；关节速度无爆冲、图像无丢帧（工具自带对账）；不合格条目重录。
- 时间预算：熟练后 1 条/分钟内，300+45 条 ≈ 1 人日（D4）。
- 命名/元数据：episode 元数据记录食物/碗位/光照标签（工具支持的 tags 字段或旁路 CSV，训练时据此分层评测）。

### 1.3 传输
采集机（本地 Windows 或临时 Linux 机）→ 7z 分卷 → COS 中转（`coscmd`，桶 `everything-1476163454` 下 `chengshao/datasets/`）→ GPU 机拉取。单数据集约 20–40GB（2 路 480p 视频），COS 上行按 20MB/s 估 20–35 分钟/卷。

## 2. ACT 训练（主力舀取策略）【延后：演示版 ScriptedScoop 达标后再议立项】

### 2.1 训练配置（V100S-32GB ×2）
- 命令（在 GPU 机 lerobot venv 中）：
  ```bash
  lerobot-train \
    --policy.type=act --policy.chunk_size=100 --policy.n_action_steps=100 \
    --dataset.repo_id=cs/spoon_scooping_v1 \
    --output_dir=runs/act_v1 --batch_size=8 --steps=100000 \
    --save_freq=20000 --log_freq=500 \
    --wandb.enable=false   # 离线要求，用本地 csv/metric 输出
  ```
- 精度：fp16/AMP（V100 支持 fp16；不支持 bf16，勿开）。V100 = sm_70，torch cu126/cu128 wheel 均支持（cu126 更稳）。
- 单卡显存估算：ACT（ResNet 视觉干 + Transformer，两路 480p 图像）batch 8 远小于 32GB，无需双卡并行；**双卡用法 = 并行两组消融**（chunk_size=100 vs 50；或 v1 vs 含纠错数据 v2）。
- 时长估算：100k steps 在单张 V100 约 4–7 小时（对照：官方称 4090 数小时级）。两组并行 = 一晚（≤1 机器日）。
- 超参基线出处：ACT 原论文/LeRobot 默认（chunk 100, kl_weight 10, hidden 512, 4 层，lr 1e-5 cosine）——训练前与 upstream/act 仓库 README 对读一次。

### 2.2 评测与目标
- 真机回放评测：`python -m cs_arm.eval_policy --checkpoint runs/act_v1/checkpoints/100000 --episodes 10 --food <each>`（每食物 10 回合）。
- 指标：D5 首训 每食物成功率 ≥70%；补采/重训后 D7 ≥90%（与脚本舀取对照组同法测 50 次/食物，与概念文档指标一致）；单口时延 ≤20s。
- 失败处置树：成功率 50–70% → 补采最差食物×碗位组合 50 条再训；<50% → 检查标定/相机位姿一致性，降低 fps 噪声（重新录 60 条精品）；全败 → 切脚本舀取版本（MVP 不因此阻塞）。

## 3. 勺上检测分类器（小模型，延后；现阶段 cs_food 用启发式）

- 任务：腕部相机勺形 ROI 二分类 has_food。接口 `cs_food.SpoonClassifier` 已冻结，训练产物以 ONNX/ state_dict 无感替换启发式实现。
- 数据：
  - 自动标注（**v2：数据源=ScriptedScoop 运行帧，无需示教**）："脚本舀取完成帧→has_food=1"，"咬合结束帧→has_food=0"（协议：取前后各 3 帧，模糊帧丢弃）；演示期每食物 50 次运行即可自然积累，目标 ≥3000 帧，按食物/光照分层。
  - 补充（仅研究用途）：FoodSeg103 裁剪食物块做负/正增强——**该数据集仅限研究/非商用（已核实），训练出的权重不得用于商业交付；商用需自建数据重训**（已在 oss-manifest.md 记录）。
  - 划分：按回合切分 train/val/test = 70/15/15（防同回合泄漏）。
- 模型与训练：MobileNetV3-Small（torchvision 预训练）+ 2 层 MLP 头；输入 224×224；CE loss + 色彩抖动增强；CPU 预研可跑，GPU 定稿 <0.5 GPU 时。
- 目标指标：test acc ≥95%；**漏检（有食物判无）<3%**（漏检会导致喂空勺，比误检严重——阈值向 has_food 偏置，宁可重舀）；CPU 推理 ≤15ms。
- 脚本落位：`chengshao/training/spoon_cls/{prepare_data.py,train.py,export_onnx.py,eval.py}`（构建期写好，GPU 机执行）。

## 4. 可选/延后项（不承诺，不进 MVP）

| 项 | 条件 | 说明 |
|---|---|---|
| SmolVLA LoRA 微调 | ACT 达标且剩余 GPU 时 >4h | `pip install 'lerobot[smolvla]'`，支持语言条件（"我想吃芋泥"直达策略）；V100-32GB 单卡可试 LoRA，风险自担不写进演示脚本 |
| openpi π0.5 LoRA | 不做 | 官方要求 22.5GB+ 显存虽可满足，但框架复杂度/时间不允许 |
| 摄入克数回归 | 有称重硬件后 | 先做称重差分记录（非训练），数据攒够再议 |

## 5. GPU 机执行清单（供主人/后续 agent 用，**v2 起整节延后：仅当 ACT 立项后执行**）

1. 环境：AnolisOS 23.5 + Python 3.12 venv + `pip install "lerobot[training]==0.6.1"`（torch 装 cu126 Linux wheel）；驱动与 V100 兼容性按 `D:\agent-knowledge\09-anolis-gpu-01.md` 手册确认。
2. 数据：从 COS 拉 `chengshao/datasets/spoon_scooping_v1`。
3. 任务 A（单卡）：ACT v1 §2.1 命令；任务 B（另一卡，并行）：spoon_cls §3 train.py。
4. 产物回传：checkpoint + metrics json → COS `chengshao/runs/` → 本机下载 → `cs_arm.eval_policy` 真机回放评测（评测在本地机器人侧做，不在 GPU 机）。
5. 验收 eval：§2.2 指标表 + spoon_cls §3 指标表；全部结果 JSON 落 `reports/`（与工程纪律一致）。

## 6. GPU 时数预算汇总（2×V100S-32GB）
| 任务 | 卡时 |
|---|---|
| ACT 100k steps | 4–7h ×1 卡（两组消融并行 = 仍是一晚） |
| 补采重训（预留 1 轮） | +5h |
| spoon_cls | <0.5h |
| 合计 | **≤ 1 机器日（≤16 卡时）**，远低于 2 卡单日能力，训练窗口 D4 晚–D5 全天 |
