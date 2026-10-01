# 任务（独立第二意见评审·只读）：澄迈大赛项目「短剧出海本地化引擎」B0 审查

背景：本项目由 AI 构建流水线按 spec+eval 逐模块开发，B0 已收口（scripts/gate_b0.py 4/4 PASS）。已完成：本机环境（paddleocr 3.7.0 py3.12 可用，约束：先 import torch 再 paddle、OCR 推理 enable_mkldnn=False）、GPU 机环境（torch 2.5.1+cu118 sm_70 双 V100S）、契约 C1-C8 冻结（43 测试）、GPU 四组件冒烟（dub-tts fp32 定案 5.6s/句、lip-fast fp16 通过 41s/50帧、alt-tts-b 通过、asr-core fp16 通过需独立 venv transformers≥5.13）。models.yaml 降级链已按实测回填。你是独立评审，不信任我们的绿灯，专找盲区。

请阅读（相对当前目录）：
1. ../plan/开发指令.md（内部规划：§3 契约 C1-C8、§4 模块 spec/eval、§9 克隆清单）
2. scripts/gate_b0.py、configs/models.yaml、pipeline/contracts.py、cli.py、jobs 生成器、tests/
3. gpu/setup_gpu.sh、data/gpu_smoke_report.json、docs/setup_windev.md

评审问题（逐条回答）：
A. 冒烟结论的实证强度：smoke_report 的 PASS 是否附有产物（音频/视频文件存在与最小时长）？"dub-tts fp16 不暴露（only use_bf16）"的结论是否可能只是 API 用法问题而非真不支持（查其代码/文档的参数面）？asr-core"需独立 venv"的结论在 B1 的服务化设计（gpu-services 常驻）下是否会变成阻塞？
B. 契约质量：C1-C8 是否覆盖 B1 音频链路四件套（分离/ASR/对齐/说话人）的实际数据流？utt_id 唯一强校验在断点续跑（同 utt 重处理）时会不会自锁？秒值 3 位小数的精度约定与 ASR 对齐输出精度是否匹配？
C. 假绿灯风险：gate_b0 的 4 项里有没有"查文件存在/查字段存在"级别的弱断言？7 个 skipped 测试是什么、为什么跳？
D. GPU 机配置的工程隐患：/data/xdng venv 与 repo/gpu/setup_gpu.sh 是否幂等可重放？torch 2.5.1+cu118 与 transformers 4.52/5.13 双版本需求的共存方案是否记录清楚？显存预算（32G×2）与 B1 的 asr+tts 常驻并行的分配有没有写？
E. Windows 本机约束的传递性：先 torch 后 paddle、mkldnn 关闭这两条硬约束是否已进入代码（import 顺序/配置默认值）还是只写在文档里（会被人/后续模块踩）？
F. 公开仓库卫生：上游名残留（含中性名映射附录A 的覆盖度）。
G. 工程债 Top5（按风险排序，注明是否阻塞 B1）。

输出格式：问题清单，每项 = [high/med/low] 文件:行 — 问题一句话 — 修复建议一句话。最后给总体结论（可继续 / 需修后继续）。只读，不要修改任何文件。
