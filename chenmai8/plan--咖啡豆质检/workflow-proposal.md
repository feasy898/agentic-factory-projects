# Workflow Proposal（构建工作流任务分解，供主会话派发）

> 编制：2026-09-28 · 供 GLM-5.3-Flash 子代理逐任务实现。
> 派发单位 = 一个任务卡（实现 + eval 跑绿）。子代理只做"实现"，验收以 eval 命令真实执行结果为准（详见 开发指令.md §4 各通过线）。
> 全部任务默认在 windev-01 CPU/Windows venv 执行；标 [GPU] 的只写脚本不执行（training-plan.md）。

## W0 任务依赖图

```
W0a 环境脚手架 ──► W0b oss_smoke ──► W0c 数据集下载
                                      │
W1 契约 schemas+taxonomy ◄────────────┘
   │
   ├──────────────┬───────────────┬──────────────┐
   ▼              ▼               ▼              ▼
W3 标定       W6 配对        W12a 素材库      W2 采集(Mock)
   │              │               ▼              │
   │              │            W12b 合成器 ──► W12c 自检集
   │              │               │
   ├──────┬───────┘          W4b ClassicSeg / W4a OracleSeg
   ▼      ▼                        │
W7 严重度  W5 RulesV0 ◄─────────────┘ (crop 来自 W4)
   └───────┬───────
           ▼
        W8 计量 ──► W9 标准引擎 ──► W10 质量护照 ──► W11 智能体
                                        │
           W13 API/UI ◄─────────────────┤
                                        ▼
                                    W14 e2e 集成
                                        │
        W15 实拍标定+真实数据回灌 ◄──（硬件到货，日历驱动不依赖 W14）
                                        ▼
                                    W16 评测与演示固化
W17 [GPU] 训练脚本包（可与 W4–W14 并行，只写不跑）
```

## W1 任务卡

| ID | 任务 | 产出 | 依赖 | 可并行组 | 预估 |
|---|---|---|---|---|---|
| W0a | venv + pinned requirements + doctor.py | scripts/setup_env.ps1, requirements.txt, doctor.py | 无 | A | 0.5d |
| W0b | oss_smoke.py 四件套（aruco/rfdetr-coco/sam2-hf/QR） | scripts/oss_smoke.py, make_aruco.py | W0a | A | 0.5d |
| W0c | download_datasets.py（DCV coco-segmentation + 目录规范 + sha256 清单；USK Form 人工步骤写 README） | data/datasets/… | W0a | A | 0.5d（含等下载） |
| W1 | schemas.py + taxonomy.yaml + fixtures + test_schemas | beaneye/schemas.py 等 | W0a | **阻塞全线，最先做** | 0.5d |
| W2 | 采集 MockSource/SynthSource/UsbSource | beaneye/acquisition/ | W1, W12b(SynthSource) | C | 0.5d |
| W3 | ArUco 标定 + 坐标变换（configs/tray.yaml） | beaneye/calibration/ | W1, W0b | B | 0.5d |
| W4a | OracleSeg | beaneye/segment/oracle.py | W1, W12b | C | 0.25d |
| W4b | ClassicSeg（Otsu+分水岭，configs/segment.yaml） | beaneye/segment/classic.py | W1, W3 | C | 1d |
| W5 | RulesV0（configs/rules_v0.yaml 特征规则表） | beaneye/classify/ | W1, W12a | D | 1d |
| W6 | 匈牙利配对 + 单面处理 | beaneye/pairing/ | W1 | B | 0.5d |
| W7 | 严重度裁决 | beaneye/severity/ | W1 | B | 0.25d |
| W8 | 计量（目数/ΔE/估重） | beaneye/metrology/ | W1, W3 | D | 0.75d |
| W9 | 标准 YAML×3 + 引擎（阈值 verified:false 流程） | beaneye/standards/, configs/standards/ | W1, D1 标准核对（人工） | D | 0.75d |
| W10 | 三语护照 + QR + 证据卡 + 打印 CSS | beaneye/report/ | W1 | E | 1d |
| W11 | TemplateAgent + LLMAgent(降级) + kb(bge-m3+Chroma 可选) | beaneye/agent/, beaneye/kb/ | W1 | E | 1d |
| W12a | build_materials（DCV 掩码直读；SAM2 为 usk 备用路径） | beaneye/synth/build_materials.py | W1, W0c | B | 0.75d |
| W12b | compose 合成器 + synth.yaml + 成对真值 | beaneye/synth/compose.py | W12a | C | 1d |
| W13 | FastAPI 端点 + 演示页 + test_app | beaneye/app/ | W8,W9,W10 | E | 0.75d |
| W14 | e2e_demo.py + test_e2e（oracle 与 classic 双路线） | scripts/e2e_demo.py | W2–W13 | F | 0.75d |
| W15 | 实拍：装配拍摄台、双相机标定、HN-Robusta 分拣拍照、系数回填 | data/samples/, 回填 configs | **硬件+豆到货**（日历驱动） | 人工为主 | 1–2d |
| W16 | 评测（人工 vs 系统用时/一致率）、演示脚本固化、name_audit.py | out/eval/, scripts/name_audit.py | W14, W15 | F | 1d |
| W17 [GPU] | train/ 六脚本（training-plan T0–T6），本机 --dry-run 验证 | train/ | W12b, W1 | 与 D3+ 全程并行 | 1.5d |

**可并行组**（同组内串行、组间并行）：A=环境/数据；B=几何与素材；C=分割与采集；D=分类与计量与标准；E=报告/智能体/应用；F=集成评测。

## W2 需要决策/外部输入的任务（提前排队，勿让子代理卡等）

1. W0c：Roboflow 账号+API key（人工注册 5min）；USK Form 人工提交。
2. W9：标准原文核对（D1 人工任务，产出直接回填 YAML；未回填前子代理按 verified:false 占位实现）。
3. W15：硬件/豆到货时间（最大变数）——W15 之前全部任务不依赖实拍。
4. W11：LLM API key（可选，无 key 自动降级，不阻塞）。
5. W17：GPU 机可用性与 COS 中转配置（执行前再确认，脚本先行）。

## W3 派发建议

- **D1（今天+明天）**：并行组 A 全部（W0a→W0b→W0c）+ W1。W1 是全局阻塞项，优先派最强卡。
- **D2**：并行组 B（W3、W6、W12a、W7）+ W12b 开工。
- **D3**：并行组 C（W2、W4a、W4b）+ W5。
- **D4**：并行组 D（W8、W9）。
- **D5**：并行组 E（W10、W11）。
- **D6**：W13 → W14。
- **D7–D8**：W15、W16（日历驱动，硬件不到则 W15 用手机拍摄流程顶替）。
- **全程**：W17 穿插（任何空闲子代理可领）。
- 每完成一卡：eval 输出 PASS 摘要 + 变更文件清单回传主会话；禁止顺手改 M1 契约（发现契约问题回规划 agent）。
