# training-assets spec（延后训练资产包：只写不跑）

> 状态：**frozen-prototype**（脚本/配置/runbook 齐备且有 dry-run 测试；**本机禁止发起真实
> 训练**——真实训练在 GPU 机且仅当延后训练立项后启动，开发指令 §10.3）。
> 本页对照 `chengshao/training/` 逐行核验于 2026-09-29。
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

## 3. 示教录制（training/record/record_demo.py，fail-closed）

- dry-run（缺省）：打印采样计划/目录布局（本机与 GPU 机行为一致）。
- 真实录制：**必须 `CS_HW_SESSION=1` + cs_arm 接口 + 双路相机**（硬件到位后补齐录制循环
  ——fail-closed：不存在的代码不会被误触发）。输出对齐训练框架数据集格式；
  30–50Hz 关节流（6 通道=5 臂关节+夹爪）+ 相机帧；方案 B=拖动示教（扭矩关闭手拖执行）。

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
- `requirements-gpu.txt`：训练侧依赖（与主 requirements.txt 分离）。

## 6. eval（精确命令与通过线）

```bash
# dry-run 测试（cwd=仓库根；test_training_scripts.py，22 用例）
.venv/Scripts/python.exe -m pytest tests/test_training_scripts.py -q
#   → exit 0：build_train_cmd 无入口名 exit 2（fail-closed）、注入后生成命令含全部关键
#     参数且 wandb 关闭、record_demo dry-run 布局、cos_transfer 计划生成、配置装载校验。
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
