# 构建阶段工作流建议（给主会话构建编排用）

> 面向 GLM-5.3-Flash 子代理逐模块实现。每个任务 = "实现 + eval 通过"才算完成（DoD）。
> 模块编号、契约、eval 均以 `开发指令.md` §3/§4 为准；上游名仅限内部，公开物用中性名（`oss-manifest.md` 附录A）。

## 0. 总原则
1. **契约先行**：T1 产出 `pipeline/contracts.py`（C1–C8 pydantic）后冻结；后续任何任务不得单方面改 schema，改契约=改规划=主会话裁决。
2. **每任务交付物**：模块代码 + `tests/test_mx.py` + 在本机跑绿的一次记录（GPU 任务贴 ssh 执行输出）。
3. **能本机不 GPU**：CPU 可验收的模块（M2/M3/M8/M9/M11/M12/M13/M14/M15）一律本机开发验收，不占 GPU。
4. 失败降级路径写进代码（`configs/models.yaml` 的 fallback 字段），不写死单一引擎。

## 1. 任务依赖图（→ 为依赖）

```
T0 环境      T1 契约/骨架 ──┬─> T2 M1 ─> T4 M3 ─┐
T0b GPU环境 ──┬─> T3 GPU冒烟┴─> T5 M4(ASR) ─────┼─> T7 M5 ─> T10 M6 ─> T12 M7 ─> T14 M8 ─> T15 M9 ─┐
              │                                │                                                  ├─> T19 M13/T20 M14 ─> T22 e2e ─> T23 指标/对比
              └─> T6 M2(OCR) ──────────────────┘   T8 M11(字幕) <─ T15   T11 M12(标识/合规) <──┘
DG1 DubMT数据(后台) ─────────────────────────────> DG2 syl2dur拟合 ─> DG3 评测集/基线(D6)
```

## 2. 任务清单（按优先序；[本机]/[GPU] 为执行地，P0 必须/P1 尽力/P2 可砍）

| ID | 任务 | 内容（实现+eval） | 依赖 | 分工 | 优先级 |
|---|---|---|---|---|---|
| T0 | 双机环境 | windev：venv+CPU torch+paddleocr+ffmpeg 检查（`setup_windev.ps1`）；GPU：驱动/venv/HF 下载（`setup_gpu.sh`） | — | 本机+GPU | P0 |
| T1 | 契约+骨架 | contracts.py（C1–C8）、cli.py、configs 三件套、jobs 目录生成器；**本表唯一允许先行的"零 eval"任务，验收=pydantic 单测** | T0 | 本机 | P0 |
| T2 | M1 预处理 | ffmpeg 规范化+probe.json | T1 | 本机 | P0 |
| T3 | GPU 冒烟 | **IndexTTS-2.5 fp32/fp16、LatentSync1.6/1.5、VoxCPM2、Qwen3-ASR fp16 各合成/推理 1 句**；结果回填 models.yaml 降级链 | T0b | GPU | P0（D1 必须完成） |
| T4 | M3 分离 | audiosplit 封装+CPU/GPU 双路径+eval（RSM 判据） | T2 | 本机 | P0 |
| T5 | M4 ASR/对齐/情绪 | gpu-services/asr_align 服务+客户端+阿语比例估算分支 | T3 | GPU 实现/本机调 | P0 |
| T6 | M2 OCR+校对 | PaddleOCR 采样合并+OCR↔ASR 投票（先出纯 OCR 版供 D2 用） | T1,T5 | 本机 | P0 |
| T7 | M5 镜头/说话人/正脸 | TransNetV2+CAM++聚类+Light-ASD+MediaPipe；voicebank 管理子命令 | T4,T5 | 本机+GPU | P0 |
| T8 | M11 字幕 | VSR 擦除（label_zone 排除）+ASS 生成器(en/es/ar-RTL)+压制 | T2 | 本机 | P0 |
| T9 | DG1 数据合成 | datagen 脚本+prompt 模板+后台任务（不阻塞主线） | T0 | 本机(API) | P0（后台） |
| T10 | M6 翻译 | mt_backends 抽象（local+API）、角色卡生成、预算候选、syl 估算占位 | T7 | 本机+GPU | P0 |
| T11 | M12 标识/合规 | 显式水印+元数据+C2PA+AudioSeal+verify_label+三市场 YAML | T2 | 本机 | P0（D8 前完成即可，可提前并行） |
| T12 | M7 TTS | gpu-services/tts：dub-tts 主力+音色/情绪参考分离+备选引擎路由 | T10 | GPU | P0 |
| T13 | DG2 syl2dur | 2000 句拟合+models/syl2dur.json（MAPE≤8%） | T3,T9 | GPU(空闲)+本机 | P0 |
| T14 | M8 时长对齐 | 二分 duration_factor+换译回路+atempo 微调 | T12 | 本机 | P0 |
| T15 | M9 混音 | ducking+R128 归一 | T14 | 本机 | P0 |
| T16 | M10 口型 | lip_plan 分流+lip-fast/lip-pro 服务+回贴+帧哈希保证 | T7,T12 | GPU | P0(lip-fast)/P1(lip-pro) |
| T17 | DG3 评测集/基线 | 500 句冻结+基座对照评测（训练延后但基线必须先拿） | T13 | 本机+GPU | P0(D6) |
| T18 | DubMT LoRA 脚本 | train_isomt.py 设计定稿+试跑一轮 en（时间不够即转赛后） | T17 | GPU | P1 |
| T19 | M13 审校台 | FastAPI+SQLite+单句重生成回路+术语管理 | T15 | 本机 | P0 |
| T20 | M14 队列 | SQLite 调度+断点续跑+metrics.db | T15 | 本机 | P0 |
| T21 | M15 指标 | 六项指标脚本+metrics.json | T15,T16 | 本机+GPU | P0 |
| T22 | e2e_smoke | scripts/e2e_smoke.sh+check_e2e.py 三语版 | T11,T16,T19,T20 | 本机 | P0 |
| T23 | 对比+演示 | vs pyVideoTrans 默认配置对照表；录 3 分钟演示+备份 | T22 | 本机 | P0(D9) |
| T24 | pyannote 对比 | community-1（需 HF 账号）与 CAM++ DER 对比，仅作指标页素材 | T7 | GPU | P2 |

## 3. 并行批次建议（每批内可并行派发）

| 批次 | 任务 | 说明 |
|---|---|---|
| B0（D1） | T0、T0b、T1、T3 | 环境与契约，一天内收口；T3 冒烟结论决定降级链 |
| B1（D2） | T2、T4、T5、T6、T9(启动) | 音频链路四件套+OCR，契约 C2 出口径 |
| B2（D3） | T7、T10、T12 | 翻译与 TTS；T13 拟合挂 GPU 空闲 |
| B3（D4） | T8、T14、T15、T11(并行) | "能看"+混音+标识（T11 无依赖可提前） |
| B4（D5） | T16 | 口型（风险最高，独占一天；lip-pro 失败即弃） |
| B5（D6） | T17、T18 | 评测集冻结+基线+试训 |
| B6（D7） | T19、T20 | 审校台与队列 |
| B7（D8） | T11 收尾、T21 | 合规收口+指标 |
| B8（D9） | T22、T23 | e2e 全绿+录屏 |
| B9（D10） | — | PPT/计划书（主会话，非子代理） |

## 4. 本机 / GPU 机分工总表
- **本机（windev-01）**：M1/M2/M3(CPU)/M8/M9/M11/M12/M13/M14/M15、datagen(API)、全部 eval 的编排与断言。
- **GPU 机（anolis-gpu-01, ssh root@[内网地址已脱敏]）**：asr_align(:9001)、tts(:9002)、lip(:9003)、mt(:9004)、diar(:9005) 五个常驻服务；syl2dur 拟合合成；DubMT 训练/评测。两卡分工：#0=asr/mt/tts，#1=lip 与训练错峰（训练时 lip 暂停）。
- 传输：tailnet ssh + scp；>100MB 走 COS 中转（不常需）。

## 5. 给子代理的任务提示模板
```
实现模块 Mx（见 D:\workspace\澄迈8项目\短剧多国出海\plan\开发指令.md §4 Mx）。
硬性要求：
1) 只读写契约中该模块的输入/输出层，schema 用 pipeline/contracts.py；
2) 上游组件一律用中性内部名导入/封装，注释与 docstring 不得出现上游项目名；
3) 交付 = 模块代码 + tests/test_mx.py + 本机跑绿记录（GPU 任务附 ssh 命令与输出摘要）；
4) 遇到上游 API 与文档不符：停止猜测，报告主会话，不得自行换库。
```

## 6. DoD 汇总（整项目"成"的定义）
1. `scripts/e2e_smoke.sh` 三语退出码 0；
2. M15 六项指标出数（含 vs pyVideoTrans 对照）；
3. 审校台单句重生成回路演示可用；
4. verify_label PASS + 三市场合规报告样例各 1 份；
5. 演示视频（3 分钟）+备份；授权记录归档；
6. 全部 tests/ 在本机可一键跑绿（GPU 部分留 smoke 记录）。
