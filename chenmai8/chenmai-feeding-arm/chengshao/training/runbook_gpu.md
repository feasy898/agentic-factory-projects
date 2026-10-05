# runbook_gpu —— GPU 机与延后训练资产执行手册

> 范围：anolis-gpu-01（2×V100S-32GB，AnolisOS 23.5）。机器底座（驱动/
> tailnet/香港出口）见机器知识库 anolis 篇；本手册只覆盖**本仓库资产**
> 的执行。整册延后：仅当策略训练立项后执行（开发指令 §10.3）。

## 1. 环境准备（一次性）

```bash
python3.12 -m venv ~/venvs/chengshao-gpu
source ~/venvs/chengshao-gpu/bin/activate
pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu126
pip install -r chengshao/training/requirements-gpu.txt
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

- V100=sm_70：fp16 可用、bf16 不可用——所有训练配置 `amp=fp16`；
- 驱动与 torch 版本冲突时，优先按机器知识库手册重配驱动，不改仓库锁版。

## 2. 代码与数据上机

```bash
# 代码：git 仓克隆/同步（不经 COS；仓库内无密钥）
# 数据：COS 中转下行（在 GPU 机）
python -m chengshao.training.transfer.cos_transfer \
    --entry spoon_scooping_v1 down --out /tmp/cos_plan.json
# 核对 /tmp/cos_plan.json 的命令清单后由操作者逐条执行（写入只用 coscmd）
```

## 3. 采数（无主臂方案三入口；硬件到位后启用真实采集）

```bash
# 入口 1：脚本示教自记录（ScriptedScoop 执行期 obs/action/image；
#         --mock 合成数据 dry-run 零硬件可跑）
python -m chengshao.training.record.record_scripted            # plan-only dry-run
python -m chengshao.training.record.record_scripted --mock --episodes 1
CS_HW_SESSION=1 python -m chengshao.training.record.record_scripted \
    --execute --port <串口号> --episodes <N> --out data/datasets/spoon_scooping_v1

# 入口 2：键盘遥操录制（精细调整/纠错条目补采；键位表见 --plan 输出）
python -m chengshao.training.record.record_keyboard            # plan-only dry-run
CS_HW_SESSION=1 python -m chengshao.training.record.record_keyboard \
    --execute --port <串口号> --episodes <N> --out data/datasets/spoon_scooping_v1

# 入口 3：方案 B 拖动示教（录制循环硬件到位后补齐——fail-closed）
python -m chengshao.training.record.record_demo --episode taro_bowlA_full_001
```

- 入口 1/2 输出**机器人学习运行栈数据集布局**（meta/ + parquet + mp4，中性名），
  自带结构自检：`python -m chengshao.training.record.session --validate <数据集根>`
  （exit 0=过；装载终验以训练框架实际读取为准）；
- 入口 3 回合产出布局见 dry-run 输出（frames/ + wrist/ + joints.csv +
  events.json），供 spoon_cls/prepare_data 消费；
- 采数协议（覆盖矩阵/条数/质检）见 `plan/training-plan.md §1`；
- 12GB 本地机（3060 Ubuntu）的采数+训练同机闭环实操另见 `runbook_3060.md`。

## 4. 勺上分类器（小模型，CPU 预研可跑、GPU 定稿）

```bash
# 1) 帧清单/自动标注（dry-run 先看计划）
python -m chengshao.training.spoon_cls.prepare_data \
    --episodes-root data/spoon_cls/raw --out data/spoon_cls/dataset
python -m chengshao.training.spoon_cls.prepare_data \
    --episodes-root data/spoon_cls/raw --out data/spoon_cls/dataset --write

# 2) 训练计划核对（本机与 GPU 机同命令；真实训练需 CS_ALLOW_TRAIN=1 + CUDA）
python -m chengshao.training.spoon_cls.train

# 3) 导出与阈值评测（acc ≥95%、漏检率 <3% 为硬线）
python -m chengshao.training.spoon_cls.export_onnx --checkpoint <ckpt> --dry-run
python -m chengshao.training.spoon_cls.export_onnx --checkpoint <ckpt>
python -m chengshao.training.spoon_cls.eval --metrics <preds.json> --report chengshao/reports/spoon_cls_eval.json
```

注：`spoon_cls.train --execute` 的真实训练循环属延后实现（本仓库交付到
环境/纪律门 + 计划生成为止）；模型结构已冻结在 `spoon_cls/model.py`，
GPU 机训练脚本直接复用 `build_model()`，按本节顺序跑即可。

## 5. 策略训练（ACT）

见 `runbook_act.md`（命令生成 + 人工核对清单 + 失败处置树）。

## 6. 回收

- checkpoint + 指标 JSON：`cos_transfer.py --entry runs up`；
- 产物不进 git（`data/`、`*.onnx`、`*.pt` 已 gitignore）；
- 训练指标只允许本地 csv/json 输出（离线红线，wandb 禁用）。
