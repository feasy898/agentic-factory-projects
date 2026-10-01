# runbook_3060 —— 3060（12GB）ACT 训练实操手册（本地 Ubuntu 桌面；立项后执行）

> 机器定位：**RTX 3060 12GB Ubuntu 桌面 = 本项目真机载体**（单从臂 + 双单目相机
> 接此机）兼**本地训练机**。因此采数、训练、真机回放评测可同机闭环，数据集
> 本地直读，**无需 COS 中转**（COS 仅用于远端 V100 路线与产物备份，见 §6）。
> 纪律不变：windev-01（无 GPU 无硬件）只 dry-run；3060 机真实训练**仅当延后
> 策略训练立项后**执行（开发指令 §10.3）。训练命令一律由
> `chengshao/training/act/build_train_cmd.py` 生成（入口名运行期注入，无入口名
> exit 2 fail-closed），不手拼长命令。
> 本册与 `runbook_act.md`（命令生成/人工核对清单/失败处置树）、
> `runbook_gpu.md`（V100 远端机手册）配套；三册共用的配置源 =
> `chengshao/training/config/train_act.json`。

## 0. 开跑前置（缺一不启）

1. 延后策略训练已立项（否则本册不执行，只读不跑）；
2. 采数完成：`record_scripted` / `record_keyboard` / `record_demo`（方案 B 拖动
   示教）按 runbook_gpu.md §3 与 training-plan.md §1 覆盖矩阵采齐（≈300 条 +
   10–15% 纠错条目）；
3. 数据集结构自检通过：
   `python -m chengshao.training.record.session --validate <数据集根>`（exit 0）；
   装载终验以训练框架在 3060 机实际读取为准（首次训练前人工做一次）；
4. GPU 空闲：训练与演示/采数**不并行**（显存独占 + USB 相机带宽）。

## 1. 环境（一次性）

```bash
python3.12 -m venv ~/venvs/chengshao-gpu
source ~/venvs/chengshao-gpu/bin/activate
pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu126
pip install -r chengshao/training/requirements-gpu.txt
python - <<'EOF'
import torch
print(torch.cuda.is_available(), torch.cuda.get_device_name(0),
      round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1), "GiB")
EOF
```

- 3060 = Ampere（sm_86）：fp16 与 bf16 都可用；**本仓配置统一 `amp=fp16`**
  （`train_act.json` 由 build_train_cmd 强校验，与 V100 远端机共用同一配置，
  不为单机开特例）；
- 桌面环境（X/Wayland 合成器、浏览器）常驻占显存 0.5–1.5GB——训练前关掉
  重度图形应用；`nvidia-smi` 确认基线占用后再开跑；
- 驱动 ≥ 525（CUDA 12.x 兼容）；驱动与 torch 冲突时先修驱动，不改仓库锁版。

## 2. 显存预算与 batch 决策（12GB 的核心问题）

> 以下为**工程预估**（撰写时无 3060 实测机，本机 windev-01 无 GPU；数字给
> 初值，**首次训练必须以 500 步实测校准并回填本节**，见 §3 外推法）。

ACT 策略（ResNet-18 视觉干 ×2 路 + 4 层 Transformer，hidden 512，chunk 100；
两路 640×480 输入在策略内部降采样）在 fp16 AMP 下的单卡峰值预估：

| batch | 预估峰值（含桌面占用） | 判定 |
|---|---|---|
| 8 | ≈ 6–9 GB | 首选（与 `train_act.json` 基线一致，消融可比） |
| 4 | ≈ 3.5–5 GB | 8 出现 OOM 时退档 |
| 2 | ≈ 2.5–3.5 GB | 仍 OOM 时的保底；lr 线性缩放近似补偿 |

规程：

1. 以 `train_act.json` 原配置（batch 8）生成命令，先只跑 **500 步**；
2. 另开终端 `nvidia-smi --id=0 --loop=2` 观测峰值显存与功耗降频；
3. 峰值 ≤ 10GB → 按 100k 步正式跑；10–11.5GB → batch 4（防长尾碎片 OOM）；
   OOM → batch 4，仍 OOM → batch 2；
4. 可选缓解：`export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
   （降低碎片化；不改变数值结果）；
5. **只允许改 `train.batch_size`**（改 `config/train_act.json` 或命令行覆盖）；
   `chunk_size / n_action_steps / hidden_dim / lr / seed` 不动——与消融基线
   和远端 V100 结果保持可比；batch 改动在训练记录里注明。

## 3. 训练执行

```bash
# 3.1 命令生成（3060 机或本机均可；入口名经 --train-cmd / 环境变量注入）
python -m chengshao.training.act.build_train_cmd \
    --train-cmd <训练框架 CLI 入口名> \
    --config chengshao/training/config/train_act.json \
    --out chengshao/reports/training_act_cmd_3060.json
# 未注入入口名 → exit 2 拒绝生成（fail-closed，不得手拼命令绕过）

# 3.2 冒烟（500 步；--extra 追加步数覆盖与显存观测）
#     冒烟参数经 --extra 追加（如 steps=500），正式步数仍以生成的 100k 为准
python -m chengshao.training.act.build_train_cmd ... --extra steps=500

# 3.3 正式跑（tmux/nohup 后台 + 日志落盘；wandb 已由生成器强制关闭）
#     断点续训：入口 resume 参数经 --extra 追加，从最近 checkpoint 恢复
```

- **时长预估**：100k steps 预计 **6–12 小时**（V100 32GB 上同配置 4–7h；
  3060 对该量级小模型吞吐与之相当或略高，但 12GB 显存可能迫使降 batch、
  单步变慢）。外推法：冒烟 500 步用时 t → 总时长 ≈ 200 × t；
  **实测后回填：__h（500 步 __ min，batch __）**；
- **checkpoint 策略**：`save_freq=20000`（20k/40k/60k/80k/100k 共 5 档），
  单档约 0.2–0.4GB（权重+优化器状态），磁盘预留 ≥5GB，全部保留——
  策略选型以**真机回放成功率**为准（每档各测 5 回合选最优），ACT 常规
  无验证集，不做 best-on-val 筛选；
- **中断恢复**：从最近 20k 档 resume（`--extra` 追加 resume 参数）；两次
  中断以上 → 缩短 `save_freq` 至 10000 重跑（训练记录注明）；
- 指标只落本地 csv/json（离线红线；wandb 生成器强校验关闭）。

## 4. 采数与评测（同机闭环）

- 采数入口（3060 机，硬件会话放行）：

```bash
# 脚本示教自记录（ScriptedScoop 执行期 obs/action/image）
CS_HW_SESSION=1 python -m chengshao.training.record.record_scripted \
    --execute --port <串口号> --episodes <N> --out data/datasets/spoon_scooping_v1
# 键盘遥操（精细调整/纠错条目补采）
CS_HW_SESSION=1 python -m chengshao.training.record.record_keyboard \
    --execute --port <串口号> --episodes <N> --out data/datasets/spoon_scooping_v1
# 两入口均支持 --mock 合成 dry-run（零硬件 exit 0 + 格式校验），上机前先跑一遍
```

- 采数协议（覆盖矩阵/条数/质检/命名）仍以 training-plan.md §1 为准，本册
  不重复；拖动示教（方案 B）入口见 runbook_gpu.md §3；
- 评测：真机回放在 3060 机本机做（`cs_arm.eval_policy` 属 G2 资产，未开工前
  以手工回放代替并如实记录）；**评测不在远端 GPU 机做**；
- 指标线与失败处置树：同 runbook_act.md §6（首训每食物 ≥70%，补采后 ≥90%，
  全败切脚本舀取——MVP 不因训练阻塞）。

## 5. SmolVLA LoRA（可选延后项；12GB 紧张）

> **12GB 紧张，建议远端 V100（tailnet+COS）。** SmolVLA（语言条件策略，
> "我想吃芋泥"直达动作）全量微调远超 12GB；LoRA 微调在 12GB 上属"能跑但
> 紧张"——视觉塔梯度与激活占大头，batch 被迫压到 1–2，且与 ACT 训练不能
> 并行。**默认不在此机执行**；若确需：走远端 anolis-gpu-01（2×V100S-32GB）
> ——数据集经 `chengshao/training/transfer/cos_transfer.py --entry
> spoon_scooping_v1 up` 上行（COS），V100 机经 tailnet 内网操作、训练，产物
> `--entry runs down` 回传 3060 机评测。本项仍为延后可选项
> （training-plan.md §4）：不承诺、不进 MVP、风险自担。

## 6. 与远端 V100 路线的分工

| 事项 | 3060（本册） | anolis-gpu-01（runbook_gpu.md） |
|---|---|---|
| 采数 | ✅ 臂+相机在本机 | ❌ 无臂 |
| ACT 主力训练 | ✅（§2/§3，batch ≤8） | ✅（batch 8 余量大） |
| 消融两组并行 | ❌ 单卡串行 | ✅ 双卡各一组 |
| SmolVLA LoRA | ⚠ 紧张，默认不做 | ✅ 首选 |
| 真机回放评测 | ✅ 唯一评测点 | ❌ |
| 数据/产物中转 | 本地直读 | COS（cos_transfer.py）+ tailnet |

## 7. 纪律与回退（本册专用摘录）

- 3060 机训练**仅当立项后**执行；windev-01 零训练（占位即契约）；
- 命令一律出自 build_train_cmd（fail-closed）；不得绕过生成器手拼训练命令；
- 显存不足且调参无果 → 远端 V100 路线（§5/§6），不在 3060 上无限压 batch；
- 训练失败处置树同 runbook_act.md §6；50–70% 补采最差组合 50 条再训；
  <50% 查标定/相机位姿一致性；全败切脚本舀取（MVP 不阻塞）；
- 产物（checkpoint/数据集）不进 git（`data/`、`*.pt` 已 gitignore）；需要
  异地备份时走 `cos_transfer.py --entry runs up`，凭据永不入仓。
