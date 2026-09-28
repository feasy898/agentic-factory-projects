# runbook_act —— 延后策略训练操作手册（只写不跑；立项后才执行）

> 纪律：本机（windev-01，无 GPU）只做 dry-run/计划生成；真实训练一律在
> anolis-gpu-01（2×V100S-32GB）执行，且仅当延后的策略训练立项后启动
> （开发指令 §10.3）。训练框架 CLI 入口名按命名纪律不入仓库文本，
> 运行期经 `--train-cmd` / 环境变量 `CS_TRAIN_CMD` / `config/train.local.json`
> （已 gitignore）注入。

## 1. 启动前置（立项门槛，缺一不启）

1. 演示版脚本舀取（ScriptedScoop）已达验收线（开发指令 §5.6）——训练是
   打磨项，不是 MVP 判据；
2. 示教数据集 `cs/spoon_scooping_v1` 已采齐（§runbook_gpu 采数节；
   3 食物 × 3 碗位 × 30–40 条 ≈ 300 条 + 10–15% 纠错条目）；
3. GPU 机环境就绪（`chengshao/training/requirements-gpu.txt`；V100=sm_70
   只用 fp16 AMP，禁止 bf16）。

## 2. 命令生成（本机 dry-run，§T11）

```bash
# 缺省（无入口名注入）→ 打印注入方式并以 exit 2 拒绝生成（fail-closed）
python -m chengshao.training.act.build_train_cmd \
    --config chengshao/training/config/train_act.json

# 注入入口名后生成完整命令（只打印/落报告，绝不执行）
python -m chengshao.training.act.build_train_cmd \
    --train-cmd <GPU 机训练入口名> \
    --config chengshao/training/config/train_act.json \
    --out chengshao/reports/training_act_cmd.json

# 消融组 B（chunk 50 对照）：--config chengshao/training/config/train_act_ab.json
```

生成器强校验：`wandb_enable=false`（离线红线）、`amp=fp16`、
`action_dim == cs_schema.N_ARM_JOINTS`、输出目录必须仓库内相对路径。

## 3. 配置基线

`config/train_act.json`：chunk 100 / n_action_steps 100 / kl_weight 10 /
hidden 512 / lr 1e-5 cosine / batch 8 / 100k steps / 每 20k 存档 /
seed 1000。超参出处为基线论文默认与训练入口文档——**训练前必须**与训练
入口 `--help` 及参考实现对读一次，未覆盖超参（如调度器细节）用 `--extra`
追加。

## 4. 人工核对清单（生成命令之后、GPU 机执行之前）

- [ ] 与训练入口 `--help` 对读：未覆盖超参已用 `--extra` 补齐；
- [ ] fp16/bf16：V100 只用 fp16；任何 bf16 建议一律拒绝；
- [ ] wandb 关闭确认（离线红线，生成器已强校验，人工复核一遍）；
- [ ] 数据集已过 COS 中转校验（7z 自校验通过，`cos_transfer.py down`）；
- [ ] 输出目录在 GPU 机本地盘（不落网络盘）。

## 5. 执行与回收（GPU 机）

1. 双卡用法 = 并行两组消融（A：chunk 100；B：chunk 50 或含纠错数据），
   非单任务数据并行；
2. 时长预算：100k steps 单卡约 4–7 小时；两组并行一晚（≤1 机器日）；
3. 产物回传：`cos_transfer.py --entry runs up`（checkpoint + 指标 JSON）；
4. 真机评测：`python -m cs_arm.eval_policy --checkpoint ... --episodes 10`
   （cs_arm 属 G2 资产，未开工前以手工回放代替并如实记录）。

## 6. 失败处置树（D5 首训起）

| 现象 | 处置 |
|---|---|
| 每食物成功率 50–70% | 补采最差食物×碗位组合 50 条再训 |
| <50% | 检查标定/相机位姿一致性；重录 60 条精品（fps 噪声） |
| 全败 | 切回脚本舀取（MVP 不因训练阻塞） |
