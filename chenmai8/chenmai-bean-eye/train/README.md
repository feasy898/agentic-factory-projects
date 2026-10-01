# train/ · 训练脚本线（检测分割 NN 微调 / 评测 / 数据配比，T0–T3）

> 对应训练计划：`D:/new-workspace/澄迈项目/咖啡豆/afp/chenmai8/plan--咖啡豆质检/training-plan.md`
> （T0–T3 验收口径以该文件为准）。本阶段**只写脚本不训练**；每个脚本 `--dry-run`
> 纯离线可跑（不训练 / 不下载 / 不导入 GPU 机 NN 栈，exit 0）。
> 原则与红线：10-08 前不执行任何训练；holdout 永不入训练；数据跨机一律走
> COS 中转（跨机不直传）；禁 AGPL 件。

## 1. 文件与中性名对应

| 文件 | 角色 | 训练计划 T6 清单对应 |
|---|---|---|
| `prepare_coco.py` | T0 数据产出（合成集 + 外部主源 → COCO，holdout 划分，sha256 清单） | 同名 |
| `det_finetune.py` | T1 检测分割微调（单卡） | **即训练计划 T6 清单第 2 项（NN 微调脚本；原始件名只写在仓库外的计划文件里）**（见下方命名说明） |
| `eval_seg.py` | T1 验收（mask AP50 + 粒数 MAE + 测速） | 同名 |
| `eval_ablation.py` | T2 单面/双面消融（A/B/C） | 同名 |
| `domain_mix.py` | T3 域差配比（{0,5,10,20}% 混入） | 同名 |
| `export_onnx_quant.py` | 可选：ONNX 导出 + int8 量化 | 同名 |
| `_common.py` / `_metrics.py` / `_predict.py` | 私有共享模块（路径/计划打印；匹配/AP/F1/配对；NN 推理器） | — |

**命名说明（gate_d3 中性名纪律）**：训练计划 T6 清单里的上游 NN 专有名
（中性名 beaneye-det）不得出现在入库文件（`scripts/gate_d3.py` 模式表
`rf-?detr`，train/ 无豁免），故 T1 脚本以中性名 `det_finetune.py` 落盘、
NN 包/模型类名在 `_common.py` 运行时拼装（`import_nn_stack` / `pkg_class_name`，
语义注释就地写明）。若收账时决定改回计划字面名（见仓库外计划文件 T6 清单）：重命名文件 +
把 `train/*.py` 加进 gate_d2/d3 豁免名单（与 oss_smoke/download_datasets 同性质、
须在闸门提交信息给理由）+ 全局替换 `_common.py` 两处拼装函数即可，接口不变。

## 2. 快速开始（本机，全部离线）

```bash
# 纯离线计划打印（六脚本逐个；tests/test_train_smoke.py 即自动做这件事）
.venv/Scripts/python.exe train/prepare_coco.py --dry-run
.venv/Scripts/python.exe train/det_finetune.py --dry-run
.venv/Scripts/python.exe train/eval_seg.py --dry-run
.venv/Scripts/python.exe train/eval_ablation.py --dry-run
.venv/Scripts/python.exe train/domain_mix.py --dry-run
.venv/Scripts/python.exe train/export_onnx_quant.py --dry-run

# 离线小样本自检（真实模式，无需 NN 栈；512² 小盘 1 对 → COCO RLE json）
.venv/Scripts/python.exe train/prepare_coco.py --emit-sample out/train_sample --seg-format rle

# 冒烟（离线链路 + 结构校验）
.venv/Scripts/python.exe -m pytest tests/test_train_smoke.py -q
```

路径约定：**相对路径一律相对仓库根**（脚本从任意 cwd 可跑）；结果统一写
`train/runs/`（建议收账时把 `train/runs/` 追加进 `.gitignore`——本目录不动共享文件）。

## 3. GPU 机（anolis-gpu-01，2×V100S-32GB）执行顺序

```
T0 数据        python train/prepare_coco.py                    # 合成 10k 对 + holdout 500 对（CPU，≈10 h；断点续跑）
   │  数据/权重上下载一律走 COS 中转（跨机不直传）；到位后 sha256sum -c SHA256SUMS
T1 微调        CUDA_VISIBLE_DEVICES=0 python train/det_finetune.py          # 单卡 6–8 h（计划 T5）
T1 验收        python train/eval_seg.py --checkpoint <best> --check-gates   # holdout test 500 对
T2 消融        python train/eval_ablation.py --checkpoint <best>            # 第二卡可并行 T3
T3 配比        python train/domain_mix.py --real-json ... --redline-ack future-split-declared
               # → mix_r00..r20 四档各跑一次 det_finetune（同超参）→ eval_seg --gate-set real 逐档
（可选）导出   python train/export_onnx_quant.py --checkpoint <best>        # CPU 部署件
```

- T1 单卡口径 `CUDA_VISIBLE_DEVICES=0`，第二卡留给 T2/T3 并行（计划 T1/T5）。
- T2 报告默认 `train/runs/eval/ablation.json`（计划 T2 提到 `out/ablation.json`，
  需要 `--out out/ablation.json` 对齐旧口径）。
- 每个脚本 docstring 头部都带：输入/输出目录约定、期望运行时长、失败回退、
  执行顺序与 COS 提示。

## 4. 依赖清单

### 本机（windev，dry-run / 数据管线）
只依赖核心钉版 `requirements.txt`（numpy/opencv/scipy/pyyaml/pydantic…），
**不需要**装 NN 栈——所有 GPU 机依赖都在真实模式分支内惰性导入。

### GPU 机（真实模式）
NN 训练栈钉版见仓库根 **`requirements-oss.txt`**（gate 豁免的内部版文件）：
**首条即检测分割训练包（版本号以该文件钉版为准，Apache-2.0）**，连带
torch/torchvision/supervision/transformers 等闭包逐条见该文件（2026-09-28
pip 解析钉版）；权重自动缓存目录与镜像端点配置同见其头注释。

**为什么不进核心 `requirements.txt`**：① NN 栈连带 GB 级 torch 全家桶，核心钉版
是纯 CPU 冒烟环境（doctor.py 逐项核对），混装会拖垮体检口径与 CI 时长——这与
`requirements-oss.txt` 头注释「与核心依赖分离，由需要跑 NN 的环境自行安装」
的既有决策一致；② 训练栈只在 GPU 机需要，桌面/演示环境永不导入。

## 5. 验收口径（引用）

| 项 | 门槛 | 出处 |
|---|---|---|
| T1 合成 holdout test | mask AP50 ≥0.90；粒数 MAE ≤3 粒/盘（≤300 粒盘）、≤8 粒（>300 粒盘） | training-plan.md T1 |
| T1 真实盘（D4 实拍 20 张） | 粒数误差 ≤10% | 同上 |
| T1 速度 | V100 单图 ≤400ms（1280）；ONNX CPU 2048² ≤8s（记录即可） | 同上 |
| T2 消融 | C−A 平均单类 F1 提升 ≥0.05 才写进 PPT，否则如实报告 | T2 |
| T3 域差 | 曲线单调性合理；10% 档相对 0% 档真实集 F1 提升 ≥0.05 | T3 |
| T0 防泄漏 | test = 新素材粒（素材库种子 +1）+ 新种子；holdout 永不入训练 | T0 |

注意：`eval_seg.py` 的 **mask AP50 是自实现口径**（单 IoU 阈值 0.5 全点插值 AP，
类内贪心匹配，见 `train/_metrics.py` 头注释）——与 pycocotools 多 IoU 平均 mAP
不是同一数字，报告时如实标注；不引入 pycocotools 是为了守住「本轮零新增依赖」。

## 6. 红线在本线的落点

- **holdout 永不入训练**：`prepare_coco.py` 的 valid/test 与 train 种子区间/
  素材库种子双重隔离；`--real-coco-json` 只产 `real_test/` 评测目录。
- **自采集 v0.1 只评测**（docs/collect_protocol.md §6）：`domain_mix.py` 产出
  含真实档必须显式 `--redline-ack future-split-declared`（真实模式硬校验）。
- **数据不入库**：产物落 `train/runs/` 与 `out/`（后者已 gitignore），跨机走 COS。

## 7. 诚实声明 / 已知限制

1. **NN 栈 API 未在本机核对**：windev 无 GPU 栈（NN 训练包/torch 未装），真实模式
   代码按 `requirements-oss.txt` 钉版的公开 API 编写，其中
   `model.train(dataset_dir/epochs/batch_size/grad_accum_steps/lr/output_dir)`、
   `model.export()`、分割模型类构造签名（`device=...`）、早停组件
   `CustomEarlyStopping` 的存在性与参数、预测返回的 `supervision.Detections`
   掩码字段——**上 GPU 机先跑 `det_finetune.py --cpu-smoke`（前向连通）+
   `--smoke-train`（1 epoch×4 图反向覆盖）**；签名不符时脚本会回退最小构造并
   打印告警（不静默）。
2. `import beaneye.synth` 在本机实测 warm ≈44 s（cv2 单项 ≈12 s）——这是
   dry-run 路径坚持「不导入 cv2/NN 栈等重量级依赖」的原因（类别表经
   beaneye.taxonomy 会带上 pydantic/yaml，属核心钉版、可承受；实测数据见
   本线自测记录）；若要优化属另一条线的事。onnxruntime **不在**
   requirements-oss.txt 钉版清单内（该文件只列 NN 栈闭包）——走 ONNX
   评测/量化路线的 GPU 机需自行 `pip install onnxruntime`，缺失时脚本给出
   可读报错。
3. 合成集按 M12 成对语义**上下同类**（`beaneye/synth/compose.py` labels 直出），
   T2 的「仅单面可见缺陷」指标在其上恒为 0——脚本自动计算并如实标注
   `n_applicable`，该指标为真实双面真值数据预留。
4. `--seg-format rle` 的 2048² 全量产出估 ≈10 s/对（掩码栅格化），全量 10k 对
   建议默认 polygon（COCO 训练器侧自动转 mask），RLE 用于 holdout/小样本；
   `area` 字段口径 = 发出的 segmentation 的实际掩码像素数（RLE）或多边形
   shoelace（polygon），已用独立解码交叉验证一致。
