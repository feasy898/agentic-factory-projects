# Training Plan —— 延后的训练任务（只设计，不执行）

> 铁律：**主流程（e2e_matrix 48 包全绿）未达成前，禁止开始任何训练。** 训练全部排在 D8 之后且不挤占主路径人力。
> 目标：提高路径 B（录屏/截图 → PlayableSpec）的稳定性；完全使用"自产模板 + 合成数据"，零版权风险。

## T1 模板自标注合成数据工厂（可先写脚本，D8 执行采集，本机可跑）

- 原理：模板与参数是我们自己的，每一局 ground truth 天然精确 —— 录屏(输入) ↔ PlayableSpec(标注) 成对生成。
- 采集设计：
  1. spec 采样器：对每模板按 params 空间分层随机采样（难度/盘面/素材主题/i18n 文案），目标 ≥3000 局（4 模板 × 750）。
  2. 录制：Playwright chromium 无头 `record_video_dir`，本地伺服模板构建产物，注入受控随机输入（经 __PF_QC__.hint 的合法动作流），每局 15-30s，720×1280 竖屏为主 + 20% 横屏。
  3. 标注：spec JSON 全量 + 元数据（模板/seed/locale/时长/win 事件时间戳）→ JSONL：`{video_path, frames: 8等距抽帧, spec, meta}`。
  4. 质量门：仅收"自动试玩到达结束页且无 console error"的样本（qacore 复用）；目标有效率 ≥90%。
- 产出：`dataset/synth-v1/`（约 3000 条 ≈ 25-40GB 视频原始，抽帧后存图 <5GB；只存抽帧图 + 少量样例视频）。
- EVAL：随机抽 100 条：spec 可过 M1 校验 100%；人工看 20 条录屏与标注一致 ≥95%；帧-参数一致性抽查（盘面尺寸/颜色数）100%。

## T2 LoRA 微调（GPU，仅在 T1 完成且主路径全绿后）

- 目标模型选择（2×V100S-32GB 约束：**无 bf16、无 FlashAttention-2，仅 fp16**，单卡 32G）：
  - **首选 Qwen3-VL-8B-Instruct（Apache-2.0）**：fp16 权重 ~16G，单卡 LoRA（r=64, alpha=128, attn/mlp）+ 8 帧 448px 输入可容；双卡 DeepSpeed ZeRO-2 可加大 batch。**这是唯一进入执行清单的选项。**
  - 备选（仅设计）：Qwen3.8-27B INT4(W4A16) + LoRA 双卡推理级微调（显存紧张，V100 无 marlin/kernel 优化，预计慢 3-5 倍，性价比低）；Qwen3.6-35B-A3B 量化 LoRA（MoE 训练支持在 V100 上不成熟，标注为"不推荐"）。
- 脚本设计（写好不跑）：LLaMA-Factory（Apache-2.0）yaml：`stage: sft, finetuning_type: lora, quantization_bit: null(8B)/4(27B), cutoff_len: 8192, per_device_batch 1-2, grad_accum 16, lr 1e-4, epochs 2, fp16 true`；数据走 ShareGPT 格式适配器，图像列 = 8 帧路径，输出列 = spec JSON 字符串。
- 部署脚本设计（不执行）：vLLM serve（--max-model-len 16384 --limit-mm-per-prompt image=8），挂到 llmgw 的 PF_LLM_BASE_URL。
- GPU 时数估算（2×V100S-32GB）：
  - 8B LoRA：3000 样本 × 8 帧 × 2 epochs ≈ **6-10 GPU·时**（单卡可训，双卡减半挂钟时间）；加评测 ~2 时。
  - 合计预留 **≤16 GPU·时（1 个工作日机器时间）**；数据采集在本机（免费）。
- EVAL（训练验收）：
  - 离线：留出 300 条合成 + 30 条真人录屏（自有游戏），指标：模板四分类准确率 ≥95%；params 关键字段（盘面/颜色数/关数）EM ≥85%；生成 spec 过 M1 校验率 ≥98%。
  - 在线（终审）：生成 spec → 模板 selftest 通过率 ≥80%（基线远程 API 约 60% 时的对比记录）。
  - 回归：路径 A 全链 e2e_matrix 不得受任何影响（训练件只替换 llmgw 后端）。

## T3 后续（二期备忘，不在本期）
- 失败样本回流（repair-loop 日志）做 DPO/RLAIF 的数据准备设计。
- "看录屏 → 差异化重生成"的视觉比对评分器（qacore 视觉分）微调。
