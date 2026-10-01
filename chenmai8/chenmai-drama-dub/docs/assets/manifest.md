# 资产包总表（manifest）

> 本表按**逻辑模块**组织。已冻结的代码结构不动，物理位置逐行标注。
> 每模块一行：模块ID / 名称 / 形态 / 职责 / 冻结契约 / 依赖 / eval 命令与通过线 / 重生成顺序位 / 状态。
> 详细契约汇总见 [CONTRACTS.md](CONTRACTS.md)；整仓再生手册见 [REGENERATE.md](REGENERATE.md)；逐模块 spec 在 [specs/](specs/)。
> 所有 eval 命令在仓库根执行。通过线均为**冻结契约的一部分**（改行为先改 eval）；
> 各项最近一次实测通过记录见各 spec 与 REGENERATE §6 变更史（含批次门禁输出数字）。

## 状态图例

| 状态 | 含义 |
|---|---|
| `frozen` | 已实现且 eval 全绿（记录在案）；契约冻结，改动视为破坏契约 |
| `frozen-mock` | 模块与 eval 冻结，但主后端依赖的 GPU 服务尚未部署冒烟（如实在登记，不伪装 ok） |
| `planned` | 未开工；规划有明确 spec 与开工前置 |
| `deferred` | 明确延后（训练类）；只有 plan 文档，无可重生 spec |

## 契约与共享原语（顺序位 0，先于一切模块）

| ID | 名称 | 形态 | 职责（一句话） | 冻结内容 | eval → 通过线 | 状态 | spec |
|---|---|---|---|---|---|---|---|
| `C1–C8+C2pre` | 冻结契约（唯一权威 schema） | pydantic（`pipeline/contracts.py`） | 全管线跨模块交换格式：镜头表 C1 / 单句事实表 C2 / 说话人段级 C2-pre / 角色卡 C3 / 译文候选 C4 / 合成计划 C5 / 口型分流 C6 / AI 标识 C7 / 市场合规报告 C8 + 时间零点 / utt_id 公式 / 原子 upsert 等冻结原语 | 全部字段 + `extra="forbid"` + 冻结规则 1–11（contracts.py 模块头） | `python -m pipeline.cli validate <kind> <path>` → exit 0；`pytest tests/test_contracts.py tests/test_b1_contract.py` → 38 passed（T13 门记录 2026-09-29） | frozen | [contract-io](specs/contract-io.md) |
| `IO-atomic` | JSONL 原子写盘原语 | `dump_jsonl` / `upsert_jsonl`（contracts.py） | 临时文件 + `os.replace` 原子整文件写；按 id 替换后整表强校验重写（禁止同 id 追加——追加触发唯一性自锁） | 见 [contract-io §3](specs/contract-io.md) | 由 test_contracts/test_b1_contract 钉住 | frozen | [contract-io](specs/contract-io.md) |
| `JOB-LAYOUT` | 每集工作区（13 层目录 + 产物槽位） | `pipeline/scaffold.py` | `jobs/<ep>/00_raw…12_out` 布局与各层预期产物名；集 ID 白名单防路径穿越 | `LAYERS` + `EXPECTED_FILES`（scaffold.py） | `python -m pipeline.cli init ep01` → 13 层目录就绪 | frozen | [contract-io §5](specs/contract-io.md) |

## 管线模块（本机 CPU 链）

| 模块ID | 名称 | 形态 | 职责（一句话） | 冻结契约 | 依赖 | eval 命令 → 通过线 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|---|---|
| `M1-ingest` | 摄取与预处理 | Python + ffmpeg（`pipeline/m1_ingest.py`） | 任意输入 → 1080x1920/25fps H.264 + 48k 立体声（loudnorm 基础归一）+ 16k 单声道（派生）+ probe.json | C-无（01_media 槽位 + probe.json 口径）；EBU 常量 TP=-1.5/LRA=11 | — | `pytest tests/test_m1.py` → 7 passed（§4 M1：产物存在 + ffprobe 断言 + 时长差 ≤0.2s；无独立 eval 脚本，门禁 B1 ② 固化同口径） | 1 | frozen | [m1-ingest](specs/m1-ingest.md) |
| `M2-ocr` | 硬字幕 OCR + OCR↔ASR 校对 | Python + cap-ocr（`pipeline/m2_ocr.py` + `pipeline/ocr_wrap.py`） | 字幕带 0.2s 采样 OCR → 合并去重 → 与 ASR 按重叠 ≥60% 投票（OCR 置信 ≥0.9 以 OCR 为准）→ C2 出口 | 冻结常量（0.2s/0.9/60%）+ C2 融合口径 + **两条 Windows 硬约束的可执行落点**（先 torch 后 paddle / mkldnn 关闭） | M1（视频）、M4（ASR 行，可选） | `bash scripts/eval_m2.sh` → 12 passed（冻结线：语料级 CER ≤5%；起止误差 ≤0.3s 且 ≥90% 命中；T13 记录 365s 含真引擎推理） | 2 | frozen | [m2-ocr](specs/m2-ocr.md) |
| `M3-separate` | 人声/背景分离 | Python + audiosplit（`pipeline/m3_separate.py`） | 48k 混音底座 → 人声（`04_dial/vocals.wav`，16k 单声道）+ 背景（`01_media/bgm.wav`）+ 分离报告 | B1 人声槽位（M4 只读人声）+ RMS 判据（有声 ≥ 总轨−6dB / 纯背景 ≤−15dBFS） | M1 | `pytest tests/test_m3.py` → 9 passed（含输出时长=输入、RMS 判据、60s 素材 CPU ≤10 分钟；T13 记录 891s 真模型推理） | 3 | frozen | [m3-separate](specs/m3-separate.md) |
| `M5-diar` | 镜头切分 + 说话人聚类 + 正脸近景 | Python（`pipeline/m5_diar.py` + `_scdet_net/_voxdia_net/_facemesh_face`） | shot-cut 镜头表 C1 + voxdia 嵌入谱聚类回填 diar/C2 speaker + facemesh 正脸近景判定 + actspk MVP + voicebank 子命令 | C1 + C2-pre 回填口径 + 正脸阈值（±25°/框高 ≥1/4 画幅） | M1, M2(字幕窗真值), M4(可选预分段) | `pytest tests/test_m5.py` → 13 passed（冻结线：diar 一致率 ≥0.85、切分召回 ≥0.8、正脸近景逐镜一致 ≥80%；T13 记录 73s） | 5 | frozen | [m5-diar](specs/m5-diar.md) |
| `M8-align` | 时长对齐 | 纯编排（`pipeline/m8_align.py`，零外部依赖） | C4 候选 → syl2dur 占位 → duration_factor 二分 → 换译 → atempo 收口 → C5 合成计划（每语种一份） | C5 出口 + m8 常量（df∈[0.5,2.0] / atempo∈[0.9,1.1] / 二分 10 轮） | M4(C2), M6(C4), C3 | `bash scripts/eval_m8.sh` → 10 passed（对齐率 ±10% 命中 ≥0.70；七类路径全触发；B3 门记录 10 passed 3.99s） | 8 | frozen | [m8-align](specs/m8-align.md) |
| `M9-mix` | 混音 + 成片合成 | Python + ffmpeg（`pipeline/m9_mix.py`） | 合成人声按 C2 句窗摆时间轴 → 确定性 ducking（−6dB/句心再 −3dB）→ R128 −16 LUFS 两趟 → 12_out 成片（ASS + AI 隐式标识位） | m9 常量（duck/斜坡/响度）+ 与 M11/M12 职责边界 | M1, M3, M7, M8, M11 | `bash scripts/eval_m9.sh` → 17 passed（时长差 ≤0.2s；响度 ±1LU；可懂度峰值比 ≥8dB；标识位回读一致；B3 门记录 17 passed 71.41s） | 9 | frozen | [m9-mix](specs/m9-mix.md) |
| `M11-subs` | 字幕擦除 + 目标语渲染 | Python + ffmpeg/libass（`pipeline/m11_subs.py`） | OCR 行 bbox → delogo/inpaint 擦除（label_zone 排除）→ 目标语 ASS（en/es 左下、ar 右下 RTL）→ 压制成片 | erase/subs 常量 + label_zone 排除 + RTL 渲染责任归 libass（不预反转） | M1, M2, M6 | `bash scripts/eval_m11.sh` → 24 用例（擦除后中文 OCR 命中=0 / 标识区像素哈希一致 / ar bidi+shaping 断言；自验收 778s exit 0） | 7 | frozen | [m11-subs](specs/m11-subs.md) |

## GPU 服务模块（双机：本机客户端 + GPU 机常驻服务）

| 模块ID | 名称 | 形态 | 职责（一句话） | 冻结契约 | 依赖 | eval 命令 → 通过线 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|---|---|
| `M4-asr-align` | 识别 + 字级对齐 + 情绪/事件（客户端+服务） | httpx 客户端（`pipeline/m4_asr.py`/`gpu_client.py`）+ FastAPI（`gpu-services/asr_align/service.py`，:9001） | 人声 wav 一次调用拿全：转写 + 字级时间戳 + 情绪标签/事件 + VAD 预分段 → C2/C2-pre 出口 | **时间零点冻结规则 7**（响应=上传音频内相对时间）+ 切句规则 8 + 阿语字符比例降级 | M3(vocals.wav), 隧道 | `bash scripts/eval_m4.sh`（先 `ops/tunnel_gpu.sh start`）→ tests/test_m4.py 全绿（含 ：9001 在线冒烟三模型 loaded）；gate_b1 ⑤ PASS 记录在案 | 4 | frozen | [m4-asr-align](specs/m4-asr-align.md) |
| `M6-translate` | 整集上下文翻译 + 时长预算 | 三后端抽象（`pipeline/mt_backends.py`）+ 编排（`pipeline/m6_translate.py`） | 通读 C2 生成角色卡工作纸 → 逐句 3–5 候选（上下文=角色卡+术语+前后 2 句+预算窗）→ in-budget-first 排序 → C4 出口 | C4 复合键 (utt_id,tgt) + 预算窗=C2×[0.9,1.1] + 三后端同一 `translate()` 接口 | M2/M4(C2), C3 | `bash scripts/eval_m6.sh` → 10 passed（全离线 mock：术语命中 100%、超预算句 100% 判出、payload 桩服务契约）；local 后端 :9004 部署冒烟归 T12 批 | 6 | frozen-mock | [m6-translate](specs/m6-translate.md) |
| `M7-tts` | 情绪迁移合成（客户端+服务） | httpx 客户端（`pipeline/tts_client.py`）+ FastAPI（`gpu-services/tts/service.py`，:9002） | **双参考合成**：voice_ref=角色干净人声 + emo_ref=原片该句人声（可不同说话人）→ wav + 实测时长 | C5 参数域 + 双参考接口 + 引擎降级链（routing.tts 冻结镜像）+ attempts 如实回传 | M8(C5 计划), 隧道 | `bash scripts/eval_m7.sh` → 11 passed（T13 记录 35s：4 离线 + 7 在线全跑） | 10 | frozen | [m7-tts](specs/m7-tts.md) |
| `TUNNEL` | GPU 隧道与保活 | bash（`ops/tunnel_gpu.sh`） | 本机 127.0.0.1:900x → GPU 机服务的 ssh 隧道（幂等 start/stop/status/keepalive） | 端口区分日志/锁（9001 历史名不变）；keepalive 单实例锁 | — | `bash ops/tunnel_gpu.sh status` → exit 0 且 /health 可达 | 0（服务前置） | frozen | [gpu-tunnel](specs/gpu-tunnel.md) |
| `MODELS-REGISTRY` | 组件注册表与 Volta 降级链 | YAML（`configs/models.yaml`） | 每组件：职责/语种/设备/精度/权重路径/版本固化/fallback 降级链/volta 实测结论 + 服务→venv→torch→transformers 部署矩阵 | routing 四表（tts/mt/align/separation/lip）+ 部署矩阵 | — | gate_b0 ②：每条目有 fallback，四已冒烟组件 volta_status 严格 ok | 0（声明式） | frozen | [models-registry](specs/models-registry.md) |

## 验收门（四道批次门）

| ID | 名称 | 形态 | 职责 | 通过线 | 状态 | 备注 |
|---|---|---|---|---|---|---|
| `GATE-B0` | 环境与契约门 | `scripts/gate_b0.py` | ①pytest 全绿零跳过（ffmpeg PATH 断言）②models.yaml fallback+volta 断言 ③GPU 冒烟报告产物可核 ④中性名扫描（附录A 强校验+公开文件零命中） | 全 PASS exit 1 on any FAIL | frozen | 系统 Python 任意 cwd 可跑 |
| `GATE-B1` | 音频链路门（M1–M4） | `scripts/gate_b1.py` | ①全量套件 ②M1 ③M2 ④M3 ⑤M4 :9001 冒烟 ⑥中性名 | 全 PASS；单次门墙钟 ~45 分钟量级（真模型 CPU 推理 724–1932s） | frozen | 记录：6/6 PASS，92 passed 零跳过 |
| `GATE-B2` | M5/M6/M7 收口门 | `scripts/gate_b2.py` | 六项：全量套件/M5/M6/M7 :9002 冒烟/B1 契约回归/中性名；超时预算单项 1800s 整门 3600s；SKIP-GPU 逐条归因豁免 | 全 PASS | frozen | 记录：6/6 PASS 867s，126 passed 零跳过 |
| `GATE-B3` | M8/M9/M11 收口门 | `scripts/gate_b3.py` | 六项：全量套件/M11/M8/M9/gate_b2 整门回归/中性名；超时预算同 B2（单项 1800s/整门 3600s） | 全 PASS | frozen | 记录：6/6 PASS 3469s/3600s——177 passed 零跳过 / M11 24 / M8 10 / M9 17（2026-09-29，commit b25fc4b）；全门墙钟 ~55 分钟量级，外部超时帽需 ≥60min |

## 未开工（planned / deferred，只有规划依据）

> **勘误（2026-09-30，整体评审后）**：下表 M10/M13/M14/M15 四行**代码已入库**（T16/T19/T20/T21 四批，
> 见 manifest.json planned 区 blocker 勘误与 docs/assets/feedback.md D1）——留在本表仅表示
> **资产包覆盖未回炉**；spec 补篇与状态翻转随回炉批执行，回炉前勿按本表判定模块未实现。

| ID | 名称 | 规划出处 | 开工前置 | 状态 |
|---|---|---|---|---|
| `M10-lip` | 按镜头分流口型 | 开发指令 §4 M10 | GPU #1 卡显存预算表（lip-pro ~18GB 与 alt-tts-b 互斥）+ 两引擎 D1 冒烟回填 | planned |
| `M12-label` | 合规报告 + AI 标识 | 开发指令 §4 M12 | M9 已写隐式元数据位（职责边界见 m9 notes §2.6）；显式 drawtext/C2PA/音频水印待实现 | planned |
| `M13-review` | 审校台 Web | 开发指令 §4 M13 | 依赖 M8/M9 单句回路 | planned |
| `M14-queue` | 任务队列与编排 | 开发指令 §4 M14 | `python -m pipeline.cli run` 现为占位（exit 2，占位语义即当前契约） | planned |
| `M15-metrics` | 指标体系 | 开发指令 §4 M15 | 依赖全链 + C2 出口稳定 | planned |
| `isomt-lora` | 时长可控翻译 LoRA（自训） | training-plan.md（全部延后） | 500 句评测集冻结 + syl2dur 拟合表 `models/syl2dur.json` | deferred |

## 重生成依赖图（顺序位即拓扑序）

```
0 契约/原语/JOB-LAYOUT → 1 M1 → 2 M2 → 3 M3 → 4 M4(:9001) → 5 M5 → 6 M6(mock 可先行)
→ 7 M11 → 8 M8 → 9 M9 → 10 M7(:9002)
门：GATE-B0(环境) → GATE-B1(M1–M4) → GATE-B2(M5–M7) → GATE-B3(M8/M9/M11)
GPU 服务：setup_gpu.sh(主 venv) → setup_asr_venv.sh(venv-asr) → run_gpu.sh × 服务 → tunnel_gpu.sh
```

- M2 与 M4 可互不阻塞（M2 纯 OCR 模式先跑，M4 就绪后投票融合）；M6 的 mock 后端全离线，可与 GPU 批并行。
- M7 依赖 M8 的 C5 计划（计划先于合成），但两者 eval 互不阻塞（M7 eval 用独立请求，不读 C5 文件）。
