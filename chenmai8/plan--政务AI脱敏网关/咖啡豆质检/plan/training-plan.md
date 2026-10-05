# Training Plan（延后执行，本阶段只产出脚本与数据）

> 原则：10-08 前不执行任何训练；MVP 用 oracle/经典 CV + 规则分类器跑通全链路（见 开发指令.md D-1）。
> 本文件定义：训练数据规格、脚本设计、实验矩阵、目标指标、GPU 预算（anolis-gpu-01：2×V100S-32GB，AnolisOS 23，tailnet 100.64.0.7）、验收 eval。
> 执行窗口：初赛（10 月中下旬）前启动一轮，决赛（11 月中旬）前完成两轮。所有脚本先在本机做 CPU 干跑（--dry-run 校验数据管道），再上 GPU 机执行。

## T0 合成数据引擎产出规格（D2 已实现，此处为训练集产出配置）

| 项 | 规格 |
|---|---|
| 图像 | 2048×2048 PNG，top/bottom 成对，acrylic 实拍背景 + 光照扰动 |
| 每盘粒数 | 训练分布：均匀采样 80–600 粒（覆盖 350g 样品分 2–3 盘的真实密度），粘连率 0–40% 分档 |
| 类别分布 | 按 taxonomy 13 类；缺陷先验可配置（默认每类 ≥8% 盘占比，稀有类过采样：mold/insect/black） |
| 素材来源 | DCV 素材（主，12 类）+ HN-Robusta 自建素材（D4 后加入，罗豆形态）+ USK 素材（粒型补充）；**素材库按来源分层，评估时报告"未见来源"泛化** |
| 真值 | COCO RLE 掩码 + 每粒 {class_top, class_bottom, eq_diameter_mm, bean_id} |
| 规模 | v1：10,000 对（top+bottom 计 20,000 图）；val/test 用**未见素材粒**合成的 500 对固定集（seed 固定，永不入训练） |
| 另产出 | 单粒分类集：直接从素材库以增强扩张到每类 ≥2,000 crop（给 ONNXCls 备用路线） |

防泄漏红线：test 集 = 新素材粒 + 新种子合成；holdout 的 500 对盘与训练盘不同种子不同素材抽样；**holdout 永不入训练**（工程纪律）。

## T1 检测分割微调（主任务，RF-DETR-Seg）

- **脚本**（本阶段写好，`train/rfdetr_finetune.py`）：
  - `rfdetr` 包 `RFDETRSegSmall`（Apache-2.0 权重）起步；数据 COCO 格式（合成集 + DCV 原图混合，字段映射见 taxonomy）；
  - 超参：lr 1e-4（余弦）、batch 4×累积 4（V100 32G 显存富余）、epochs 50、输入 1024×1024（RF-DETR 分辨率可变，密集盘用 1280 评估两档）；
  - 早停：val mAP50 3 epoch 无提升；导出 torch best + ONNX（opset 17，静态 1024）；
  - 单卡训练（CUDA_VISIBLE_DEVICES=0），第二卡留给 T3 消融并行。
- **验收 eval**（`train/eval_seg.py`，GPU 或本机 CPU 小样本）：
  - 合成 test 500 对：mask mAP50 ≥0.90；粒数 MAE ≤3 粒/盘（≤300 粒盘）、≤8 粒（>300 粒盘）；
  - 真实盘（HN-Robusta D4 实拍 20 张，人工核对粒数）：粒数误差 ≤10%；
  - 推理速度：V100 单图 ≤400ms（1280），ONNX Runtime CPU 2048² ≤8s（记录即可）。
- **目标指标（决赛前）**：真实盘逐粒分类 macro-F1 ≥0.80（vs RulesV0 的 0.60 基线）；黑豆/破碎 F1 ≥0.90。

## T2 单面/双面消融实验设计（论文级证据，答辩用）

- **实验矩阵**（全部基于同一 T1 模型与同一 test 集）：
  | 配置 | 输入 | 配对 | 计数规则 |
  |---|---|---|---|
  | A 单面-top | 仅 top | 无 | 每粒计 top 标签 |
  | B 单面-bottom | 仅 bottom | 无 | 同上 |
  | C 双面（ ours） | top+bottom | 匈牙利 | 每粒取最严重面（M7） |
- **报告指标**：平均单类 F1（复现论文 0.727→0.908 的增益方向，我们自有数字）；逐豆缺陷漏检率（仅单面可见缺陷占比统计——DCV 双面真值直接可算，这是"双面刚需"的定量论据）；
- **验收**：`train/eval_ablation.py` 输出 `out/ablation.json`（三配置 F1 表 + 配对贡献分解）；C 相对 A 的平均单类 F1 提升 ≥0.05 才写进 PPT（否则如实报告）。

## T3 合成→真实域差实验

- 混入比扫描：真实 HN-Robusta 标注图占训练集 {0%, 5%, 10%, 20%} 四档（其余合成），看真实测试集 F1 曲线 → 回答"要多少本地数据才够"（答辩关键问题）；
- 每档同一超参重训，验收：曲线单调性合理；10% 档相对 0% 档真实集 F1 提升 ≥0.05 作为"快速本地适配"卖点证据。

## T4 单粒分类器（备用路线，低优先）

- RFDETRSeg 掩码 crop → MobileNetV3-small/ResNet18 分类头（torchvision，BSD/Apache 权重）；仅当 T1 联合分类不达 T1 指标时启用；验收：单粒集 macro-F1 ≥0.85、CPU ONNX ≤15ms/粒。

## T5 GPU 预算（2×V100S-32GB）

| 任务 | 单次时长（估） | 轮次 | 合计 |
|---|---|---|---|
| T1 主训练 | 6–8h（1 卡，20k 图×50ep） | 2（初赛前/决赛前） | ~14 GPU·h |
| T2 消融 | 评估为主，+3h | 1 | ~3 GPU·h |
| T3 域差 4 档 | 4×5h（可 2 卡并行→~10h 墙钟） | 1 | ~20 GPU·h |
| T4 备用 | 2h | 1 | ~2 GPU·h |
| 余量/失败重跑 | — | — | ~10 GPU·h |
| **合计** | | | **≈50 GPU·h（V100S 单卡口径），2 卡 2–3 个工作日墙钟，机器完全够用** |

## T6 训练脚本清单（本阶段交付，全部 --dry-run 本机可验）

```
train/
├─ prepare_coco.py        # 合成集+DCV+HN → COCO json（类别映射、holdout 划分、sha256 清单）
├─ rfdetr_finetune.py     # T1（含 --dry-run：1 batch CPU 前向反传）
├─ eval_seg.py            # T1 验收
├─ eval_ablation.py       # T2
├─ domain_mix.py          # T3 数据配比
└─ export_onnx_quant.py   # int8 量化（CPU 部署加速，可选）
```

每个脚本头部注明：输入目录约定、输出目录、期望运行时长、失败回退（重训 checkpoint 保存 every 5 epoch）。数据上传走 COS 中转（工程纪律：跨机不直传）。

## T7 不做什么

- 不做 SAM3/SAM2 微调（抠图用现成权重够）；不做 GAN/扩散增广（论文证据是长尾分类，我们用合成引擎直接解决）；不做 3D/多视角；不追求 SOTA 论文指标，只服务演示与答辩证据链。
