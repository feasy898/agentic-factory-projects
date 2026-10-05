# training-assets spec（延后训练资产包：只写不跑）

> 状态：**frozen-prototype**（脚本/配置/runbook 齐备且有 dry-run 测试；**本机禁止发起真实
> 训练**——真实训练在 GPU 机且仅当延后训练立项后启动，开发指令 §10.3）。
> 本页对照 `chengshao/training/` 逐行核验于 2026-09-29；2026-10-02 增补
> record/ 采数资产与 3060 runbook（B3），核验口径不变。
> 命名纪律：训练框架与其入口名按 check_naming 规则不入仓库文本——文档用中性描述
> "训练框架入口名"，运行期经注入（见 §1）。

---

## 1. 训练命令生成器（training/act/build_train_cmd.py，269 行，零执行路径）

- **只生成不执行**：从 `training/config/train_act*.json` 生成训练框架 CLI 命令行并打印/落报告；
  没有任何子进程/训练调用，dry-run 即其唯一本机形态。
- **入口名解析优先级（fail-closed）**：① `--train-cmd` 命令行 → ② env `CS_TRAIN_CMD` →
  ③ 本地覆盖文件 `training/config/train.local.json`（**已 gitignore**，entry 名永不入库）的
  `train_cmd` 键 → ④ 训练配置 `runtime.train_cmd`（入库缺省 null）。
  全链未解析 → **拒绝生成并 exit 2**；`--allow-placeholder` 允许以占位符输出
  （仅供人检阅，不可直接执行）。
- 强校验：`wandb` 强制关闭（离线红线）；`repo_id` 正则校验；输出路径 `safe_rel_output`
  防越仓；`action_dim` 取自契约 `N_ARM_JOINTS=6`（v1.1 同步修订）。
- 配置双份：`train_act.json`（基线）与 `train_act_ab.json`（消融对照——V100 双卡各跑一组）。

## 2. 勺上分类器（training/spoon_cls/，延后、GPU 定稿 CPU 可预研）

| 文件 | 职责 |
|---|---|
| `prepare_data.py` | 自动标注数据准备：正例=舀取完成帧、负例=咬合结束帧（协议：前后各 3 帧、模糊帧丢弃）；**按回合切分 70/15/15（防同回合泄漏）**；按食物/光照分层 |
| `model.py` | 主干 torchvision 预训练 MobileNetV3-Small + 2 层 MLP 头；输入 224×224 |
| `train.py` | CE loss + 色彩抖动增强；指标口径：**test acc ≥95% 且漏检（有食物判无）<3%**（漏检=喂空勺，比误检严重——阈值向 has_food 偏置）；CPU 推理 ≤15ms |
| `export_onnx.py` | 导出 ONNX，经 cs_food.SpoonClassifier 同一协议无感替换启发式 |
| `eval.py` | 独立评测入口 |

数据源（v2 决策）：**ScriptedScoop 运行帧自动标注，无需示教**；演示期每食物 50 次运行
自然积累，目标 ≥3000 帧。补充增强数据集仅限研究/非商用（许可已在内部台账记录，
训练出的权重不得用于商业交付）。

## 3. 采数资产（training/record/，无主臂方案；fail-closed）

单从臂无主臂遥操作（training-plan v2），采数三入口 + 共享件，全部支持
**plan-only dry-run（缺省，exit 0 不落盘不碰硬件）与 --mock 合成数据
dry-run（exit 0 且格式校验通过）**；真实采集一律 `CS_HW_SESSION=1` +
设备就绪，缺失显式失败 exit 2（占位即契约）。

| 文件 | 职责 |
|---|---|
| `record_scripted.py` | **脚本示教自记录**：ScriptedScoop 执行期逐步经 SafetyEnvelope 下发悬停→入碗→合爪（记 scoop_done）→抬勺腿，记录 obs（6 关节回读）/action（6 维关节目标）/image（双路相机） |
| `record_keyboard.py` | **键盘遥操录制**：固定键位表（q/a…y/h 六关节±、space=标记 scoop_done、enter=收回合、esc=中止），增量目标经包络限步；纠错条目补采用 |
| `record_demo.py` | 方案 B 拖动示教计划（回合原始布局 frames/+wrist/+joints.csv+events.json，供 spoon_cls 消费）；录制循环硬件到位后补齐（fail-closed） |
| `session.py` | 共享件：**机器人学习运行栈数据集布局**（meta/info.json+episodes.jsonl+tasks.jsonl、data/chunk-XXX/episode_YYYYYY.parquet、videos/chunk-XXX/<cam>/episode_YYYYYY.mp4，中性名）写入器与结构自检 `validate_dataset`、合成帧（确定性）、mock 环境（MockArm+包络+虚拟时钟）、硬件门；`--validate <root>` CLI：好数据 exit 0 / 对账不符 exit 1 / 目录不存在 exit 2 |

- 数据格式一致性：入口 1/2 输出训练框架可装载的数据集布局（feature 维度
  与 cs_schema.N_ARM_JOINTS 锁定、双路相机视频通道、回合记账列齐全）；
  **结构自检是本仓库口径，装载终验以训练框架在 GPU 机实际读取为准**；
- 事件 sidecar `meta/record_events.json` 为本仓库扩展（训练装载不读）：
  帧下标事件供 spoon_cls 自动标注与人工质检对账。

## 4. 数据传输（training/transfer/cos_transfer.py，只出计划不落密钥）

- `--entry <name> up|down --out <plan.json>`：生成 COS 命令清单（写入只用 coscmd），
  **只写计划 JSON，由操作者逐条执行**；凭据不入仓（COS 会话在机器级配置）。
- 路径约定：桶内 `chengshao/datasets/<name>`（下行）/ `chengshao/runs/`（产物回传）。

## 5. 配置与 runbook

- `training/config/datasets.json`：数据集登记表；`spoon_cls.json`：分类器训练参数；
  `train_act.json` / `train_act_ab.json`：策略训练参数（chunk 100、`action_dim=6`、
  两路 480p 图像、离线指标输出）。
- `runbook_act.md`：延后策略训练操作手册（启动前置：脚本舀取达标 + 数据集采齐 + GPU 机就绪；
  本机只 dry-run）。**V100=sm_70：fp16 AMP 可用、bf16 禁止**。
- `runbook_gpu.md`：GPU 机执行手册（venv + cu126 torch + requirements-gpu.txt；采数/训练/
  产物回传全流程；评测在本地机器人侧做，不在 GPU 机）。
- `runbook_3060.md`：**3060 12GB 本地机（Ubuntu 桌面，真机载体）ACT 实操**——显存预算与
  batch 决策（预估+500 步实测校准规程）、checkpoint 策略、采数-训练-评测同机闭环、
  SmolVLA LoRA 注记「12GB 紧张、建议远端 V100（tailnet+COS）」。
- `requirements-gpu.txt`：训练侧依赖（与主 requirements.txt 分离）。

## 6. eval（精确命令与通过线）

```bash
# dry-run 测试（cwd=仓库根；test_training_scripts.py，31 用例——22 既有 +
#   9 采数资产增补：record_scripted/record_keyboard/session，2026-10-02）
.venv/Scripts/python.exe -m pytest tests/test_training_scripts.py -q
#   → exit 0：build_train_cmd 无入口名 exit 2（fail-closed）、注入后生成命令含全部关键
#     参数且 wandb 关闭、record_demo dry-run 布局、record_scripted/record_keyboard
#     三态（plan-only 不落盘 / --mock 合成小样本+格式校验 / execute 逐级 fail-closed）、
#     数据集结构自检（好数据 0 / 篡改 1 / 缺目录 2）、cos_transfer 计划生成、配置装载校验。
# 命令生成（人工 dry-run）：
.venv/Scripts/python.exe -m chengshao.training.act.build_train_cmd \
    --config chengshao/training/config/train_act.json          # → exit 2 + 注入方式说明
.venv/Scripts/python.exe -m chengshao.training.act.build_train_cmd \
    --train-cmd <GPU 机训练入口名> --config chengshao/training/config/train_act.json \
    --out chengshao/reports/training_act_cmd.json              # → exit 0（只打印/落报告）
```

- **纪律**：真实训练（GPU 机、2×V100S-32GB）整册延后；本资产包的完成判据就是
  "脚本+配置+runbook 齐备且 dry-run 全绿"，**不含任何已训练权重**（*.pt/*.onnx 均被
  gitignore）。
