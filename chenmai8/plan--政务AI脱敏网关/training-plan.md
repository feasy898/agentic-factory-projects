# Training Plan —— 延后的训练任务（10/8 大赛材料提交之后启动）

> 原则（贯彻开发指令铁律 D）：**MVP 阶段零训练**。本文件是训练期（约 10/9–10/31，与决赛迭代窗口重合）的任务清单与验收设计。合成数据生成器（T1/T2）中的"生成器 v1"属于代码，已列入 9/29 MVP 任务；此处只定义其训练语料输出档。
> 训练机：anolis-gpu-01（[内网地址已脱敏] / tailnet [内网地址已脱敏]，16C125G + 2×V100S-32GB，AnolisOS 23.5）。手册：`D:\agent-knowledge\09-anolis-gpu-01.md`（驱动/tailnet/香港出口已调通）。
> 注意：V100 不支持 bf16，统一用 fp16（amp）或 fp32；NCCL 双卡可用但本任务单卡足够，第二卡跑并行评测/消融。

## T0 标签体系冻结（依赖：GB/T 45574-2025 类别校对）

- 产出：`docs/contracts/labels.md` v2 —— EntityClass × 敏感属性 subtype × BIO 标签集（`B-/I-<TYPE>`，O），与开发指令 §5.1.1 完全一致；NER 输出即 Finding，字段零漂移。
- 验收：`python -m evals.t0_labels`（标签集常量与 recognizers/ner/adapter.py 的映射表一致性检查）。exit 0。

## T1 合成语料生成器·训练档（代码任务，可与 MVP 并行做）

在 benchmark/generator v1（检测评测集档）之上增加训练语料模式：

- 规模：**5–10 万篇**，目标 token ~2–4 亿字符级；30 类政务文书 × 槽位 × 扰动分层抽样。
- 组成配比（可配置）：
  - 纯合成文书 70%（标签在生成时确定：人名/住址/出生日期/敏感属性/机构等）；
  - 公开语料混入 ≤15%（CLUENER/MSRA/Weibo/Resume 的中文 NER 片段映射到统一标签；**只进训练机本地目录 third_party_data/，不随公开仓库分发**——许可注意项见 oss-manifest §三）；
  - 难负例/白名单 10%（单位座机、12345、公开文号、职务+姓氏非人名指称等，标签全 O）；
  - 注入/攻击文本 5%（Safety-Prompts 种子改写 + 文档埋注；标签 INJECTION，仅供语义层用）。
- 格式：JSONL `{"id","text","entities":[{"type","subtype","start","end","normalized","source":"synth|public|neg"}]}`
- 确定性：seed → manifest（篇数/类别分布/实体计数/sha256），可复现。
- 验收：`python -m evals.t1_corpus`（在训练机上跑）：规模断言 + 分布断言（每类实体 ≥ N）+ 复现哈希一致。同时抽查 200 篇人工目检记录留档（标注质量抽检用 Label Studio，仅作抽检不作全量标注）。

## T2 教师：chinese-roberta-wwm-ext-large 微调（token classification）

- 基座：`hfl/chinese-roberta-wwm-ext-large`（Apache-2.0；备选 macbert-large）。
- 数据：T1 语料 train/dev split 99/1（dev 固定 seed 抽样）；max_len 512，滑动窗口推理期再议。
- 配方：fp16 + AMP，lr 2e-5 cosine，batch 32（grad accum），2–3 epoch，ema 可选；DeepSpeed 不必要（32G 单卡放得下 large + bsz）。
- 目标指标（dev，精确匹配 span）：
  - 清洁文本：人名/地址 F1 ≥ 0.97，DATE_BIRTH ≥ 0.98，敏感属性 F1 ≥ 0.90；
  - 扰动分层（全角/插空格/OCR 形近字子集）：F1 ≥ 0.94；
  - 结构化号码不在 NER 目标内（规则层负责，指标线归 M2）。
- 产出：`models/teacher/`（HF 格式）+ 训练报告 JSON。
- 验收：`python -m evals.t2_teacher --model models/teacher`（训练机跑，加载 dev+扰动分层集，输出分项指标表，阈值判断 exit code）。

## T3 学生蒸馏：large → rbt3

- 方法：两阶段——
  1. 教师软标签预计算：对 T1 全量 train 文本跑教师，存 token 级 logits（fp16 npy/分片 safetensors，磁盘估算 ~数十 GB，分片流式）；
  2. KD 训练：rbt3（3 层 ~38M）+ token classification 头；loss = α·KL(student||teacher, T=2) + (1-α)·CE(gold)，α=0.7 起，消融 0.5/0.8。
- 配方：fp16，lr 5e-5，batch 64，3–4 epoch。
- 目标指标：dev 上不低于教师 −2 个 F1 点（即人名/地址 ≥ 0.95、敏感属性 ≥ 0.88、扰动分层 ≥ 0.92）；**结构化号码召回由规则层保障，NER 不背该指标**。
- 产出：`models/student_rbt3/`。
- 验收：`python -m evals.t3_student --model models/student_rbt3`（同 T2 评测器，阈值按本节）。

## T4 ONNX 导出 + INT8 量化 + CPU 延迟

- 导出：`torch.onnx.export` 动态轴（batch/seq），opset ≥17；`onnxruntime.quantization.quantize_dynamic`（MatMul+LSTM 全套权重 INT8，QUInt8 激活默认）。
- 精度门槛：INT8 相对 fp32 学生 F1 降幅 ≤ 0.5 点（dev 全集+扰动分层）。
- 延迟门槛：**windev-01 CPU（本机，ONNX Runtime 1.30，单线程池）2000 字端到端（分词+推理+解码）< 100ms**；训练机 CPU 不可作为口径，必须在 windev-01 实测。
- 产出：`models/student_rbt3.int8.onnx`（gitignore，走 COS 中转到 windev-01）+ `benchmark/models/latency_report.json`。
- 验收：`python -m evals.t4_onnx --onnx models/student_rbt3.int8.onnx`（本机跑：精度用固化子集 dev-mini 5k 篇 + 延迟 10 次 p95）。

## T5 接入网关（NER 层转正）

- `recognizers/ner/adapter.py` 加载 ONNX：窗口 256 stride 64 解码、span 合并、conf≥0.6 → Finding(layer=ner)；与规则层结果做 span 去重合并（规则优先）。
- 语义层同批可选：Qwen3Guard 4B 上 GPU 机做 response 侧（vLLM），0.6B 留 CPU prompt 侧——此项独立于 NER，不阻塞。
- 验收：`python -m evals.t5_e2e_ner`（本机：full_cases.jsonl 上整体识别指标——人名/地址 F1 ≥ 0.95 达成即为概念文档承诺线闭环；2000 字总延迟 < 150ms 含规则层）。

## 目标指标总表（对外汇报口径）

| 指标 | 规则层(MVP 即达) | +NER(训练后) |
|---|---|---|
| 结构化号码召回 | ≥ 99.5%（规则层内部要求 100%） | 同左（规则兜底） |
| 人名/地址 F1 | 无（NER 缺位，如实说明） | ≥ 95% |
| 敏感属性 F1 | 无 | ≥ 88–90% |
| CPU 2000 字延迟 | < 100ms（规则） | < 150ms（规则+NER INT8） |
| 脱敏后回答质量 | ≥ 95%（LLM-judge，MVP D7） | 同左 |

## GPU 时数预算（2×V100S-32GB，单卡为主）

| 任务 | 卡时 | 说明 |
|---|---|---|
| T1 语料生成 | 0（CPU，训练机 16 核或 windev-01 均可，<2h） | |
| T2 教师微调 | 3–5h | large + fp16 + bsz32，2–3 epoch / 5–10 万篇 |
| T3 软标签预计算 | 2–3h | 教师批量推理 |
| T3 学生蒸馏 | 3–4h | rbt3 很小，快速 |
| T4 导出量化 | 0（CPU 任务，1h） | |
| 评测+消融+返工缓冲 | ×1.5 | α/T/epoch 消融约 6–10h |
| **合计** | **~1.5–2.5 天（单卡）** | 第二卡跑并行评测/基线（通用 NER 基线：rbt6 或 macbert 直接微调版） |

## 训练期风险

1. V100 fp16 数值稳定（无 bf16）：启用 grad scaler；loss spike 即回退 fp32。
2. 公开语料标签体系与自研标签对齐损耗：混入比从 15% 降至 5% 或 0，指标口径以合成 dev 为准，公开语料只作泛化佐证。
3. 软标签磁盘峰值：分片流式（每片 10 万 token），盘余 300G 够用。
4. 训练机不可用（租期/驱动）：教师直接改用 `hfl/chinese-roberta-wwm-ext` 12 层 base 版在 windev-01 CPU 慢训不可行 → 降级方案：租赁按小时 V100/A10 云卡 ≤8 卡时，或维持规则层 MVP 参加决赛（功能上已闭环）。
