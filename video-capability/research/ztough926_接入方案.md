# 接入方案 · ztough926 思想落进我们视频能力栈（关键思想落地，不整仓照搬）

> 研究：CloudCrane 视频能力迭代 worker-B ｜ 日期 2026-10-01 ｜ 上游研究：`ztough926_架构摘要.md`
> 本文所有"我们的"数字均可溯源：FINAL_REPORT_V2.md、overnight/judge基准报告.md、
> overnight/数据/golden/manifest.json、overnight/数据/score_temporal_rerun.py，以及本轮
> `research/proto/` 原型实测（退出码与结果见 §4）。

## 1. 我们的评测面（接缝在哪）

两代评测面并存：

1. **v2 门禁线（PROJECT CRADLE 2.0）**：G7 五子项夹具门禁（47 夹具=15 fail+15 pass_structural+17 pass_candidate；
   夹具拦截 15/15=100%、误杀 struct 0/15、candidate 4/17=23.5%）。其中 **G7e「VLM 成对审讯」在 v2 全程
   skipped**（无 API 口径 D-004，不做假实现）——SPECS_V2 原文：G7e 就是"改版替换 v1 的十帧网格"的
   VLM 帧对质检。**即：我们的栈自己早就需要一个更好的"帧网格"载体，v2 只是没有 API 去喂它。**
2. **overnight judge 线（金标盲测，2026-09-30）**：金标 40 clips（A 类注入缺陷 16 / B 类意图缺陷 12 /
   C 类干净对照 12，8 缺陷型×2）。六 judge 结论：冠军 J1（GLM-5.3-Flash 8帧 rubric，经 Higress
   glm-plan 通道）召回 0.750 / **FPR 0.000** / F1 0.857；推荐主判据 `J1 ∨ J3@0.7`（F1 0.914）。

**实证缺口（judge 报告 §0.5 原文）**："人眼一眼可见、但三个 VLM judge 全漏的实锤案例：中途定格 2 秒
（golden_017/028）"；J1 的 4 条漏检**全部是时序类**（frame_freeze×2、temporal_swap、ghosting）。
且 J1 在 golden_017 的判定文件里给出**错误算术依据**：`judges/glm8/golden_017.json` notes 写
"相邻帧像素差均匀（MAD 27-50，无近似零差对，排除定格）"——而 manifest 注入区间 1.531→3.531s
（2.0s）真实存在。8 帧均匀采样让模型自己算 MAD，模型算错了。

## 2. 可借鉴点（按落地优先级，全部"思想级"）

| # | 借鉴思想 | 落到我们栈哪里 | 为什么 |
| --- | --- | --- | --- |
| B1 | **帧差时间线作为确定性 QC 信号**（200px 灰度流+双角度差异+自适应阈值） | J6 检测器线新增 freeze/flicker 规则；G7b/c 的廉价前置；**零模型调用** | J1 的时序漏检根因是"让模型算帧间差"；这是确定性可算的（P1 实证见 §4） |
| B2 | **变化感知选帧替代均匀 N 帧采样**（等它变完+运动补帧） | J1/J2 runner 的取帧函数（8 帧均匀 → 关键帧集+时间戳标签） | 均匀采样对时序缺陷盲区大；变化感知采样把"变化的时刻"排给模型 |
| B3 | **模型可读分张纪律**（≤12格/张、≤4列、1600px、4:4:4、格标签） | G7e 成对审讯的帧呈现载体；judge 帧包；人工 CONFIRMATION 复核包生成 | P2 实证一张 6 格图即可让 GLM 读出乱码原文并定位到 0.1s（§4） |
| B4 | **Skill 化打包**（SKILL.md 隐式调用铁律+固定档位+三步协议） | 我们的 skill-pack 资产（"video-qc-frames"技能：抽帧→读总览→补单帧→按 G7e 六字段出 JSON） | 把评测面的取帧纪律固化成可复用资产，而不是散在 runner 里 |

**不借鉴**：整仓照搬（GPL-3.0 传染 + 它是"理解前处理"不是"生成质检"，目标函数不同：它要抹掉冗余帧，
我们质检恰恰不能抹掉时序缺陷信号，见 §5 设计发现）。

## 3. 最小原型（已落地，`research/proto/`）

**`sheetframe.py`**：上游三条思想的独立实现（cleanroom，未复制代码，~260 行）——
双角度帧差时间线 → 中位数×k 夹 [0.008,0.08] 自适应阈值 → 等它变完选帧 → 单帧导出 →
LANCZOS+4:4:4+格标签总览图（≤12格/张自动分张）→ **附加：内嵌定格检测**（近似零差 run ≥1s 且
run 外存在运动，区分"定格缺陷"与"整片静止镜头"）。

### P1：确定性定格检出（零模型调用）

命令：`cd research/proto && PYTHONPATH=./pylibs:. python3 run_proto.py` → **EXIT=0（P1_ALL_PASS）**

| clip | 期望 | 检出定格区间 | 注入区间（manifest） | 判定 | 关键帧数 | 总览图 |
| --- | --- | --- | --- | --- | --- | --- |
| golden_017 | frame_freeze | **1.562-3.500s** | 1.531-3.531s（端点误差 0.031s） | PASS | 6 | 1600×702 6格 |
| golden_028 | frame_freeze | **1.562-3.500s** | 1.531-3.531s（误差 0.031s） | PASS | 10 | 1600×1412 10格 |
| golden_001 | 干净 | 无 | — | PASS（零误报） | 5 | 1600×2114 5格 |
| golden_006 | 干净 | 无 | — | PASS（零误报） | 6 | 1600×2114 6格 |

对照：J1 对 golden_017 漏检且算术错误（§1）；本原型纯代码、零模型、毫秒级，检出端点误差 0.031s。
产物：`research/proto/out/<clip>/`（keyframes.json + overview.jpg + frames/），
汇总 `research/proto/out/proto_results.json`。

### P2：总览图模型可读性（Higress 2 次调用，配额 2/5）

命令：windev 侧 `python p2_higress_call.py` → **EXIT=0（P2_CALLS_OK）**。同一条中性质检提示词，
`model=glm-plan`（响应回显 model=glm-5.3-flash），HTTP 200 ×2：

| clip | 期望 | 模型回读（摘要） | 判定 |
| --- | --- | --- | --- |
| golden_002（A 类 garble_text 注入 1.531-3.531s） | 检出乱码 | `garble_detected=1`，**逐字读出乱码原文** `yMBeabypd5bkVqZ_T+e@Nf...`，定位 3.38s（注入窗口内那格） | 命中 |
| golden_001（C 类干净对照） | 零误报 | `garble_detected=0`，`main_issue=无`；对远处虚化店招如实写"看不清"而非编造 | 命中 |

诚实瑕疵记录：golden_002 回读把格 #004 报成 "#055"（**格序号误读，时间戳正确**）——总览图格标签
在小字号下存在被误读风险，接入时格标签应加大字号或同时依赖 keyframes.json 对齐。
产物：`research/proto/out/p2_results.json`（含 usage：2192+5228 tokens）。
凭证纪律：key 经 OpenBao `kv/company/gpu/models/higress-consumer`（字段白名单只取 key）进 windev
进程内存，零打印零落盘；GPU 机到 srv-1 无 ssh 密钥（实测 Permission denied），故调用在 windev 侧代理执行。

## 4. 关键设计发现（比"能跑通"更值钱的一条）

**变化感知选帧与定格检测存在目标冲突：选帧算法会把冻结段折叠成单帧，从而在总览图里抹掉定格证据。**
实测 golden_017：冻结区 1.531-3.531s 只被选出 1 帧稳定帧（1.625s），下一帧直接跳 5.062s——
对"内容理解"这是最优行为（冗余帧本来就该丢），对"时序质检"这恰恰销毁了证据。

→ **分工结论**：**时序缺陷走确定性帧差时间线（P1），内容缺陷走总览图+VLM（P2）**。
二者互补而非互替：时间线负责"哪一段没变过"（机器可判），总览图负责"画面/文字长什么样"（模型可判）。
这同时解释了 J1 的失败：它把两件事都压给模型——帧差算术（模型算错）+ 内容判读（模型擅长）。

## 5. 适配成本 / 风险 / 依赖 / 接缝

- **成本**：原型 ~360 行（sheetframe.py 260 + run_proto.py 100），依赖仅 ffmpeg+numpy+Pillow
  （GPU 端已装 `research/proto/pylibs`；venv 方案因 ensurepip 损坏弃用，用系统 pip `--target`）。
  正式化（全 40 金标重评 + 接进 runner）预估 1-2 个夜班。
- **风险**：
  1. 阈值区间 [0.008,0.08] 与 eps=0.004 是在 2+2 clips 上初验的口径，**全 40 金标重校准前不得当生产阈值**
     （沿用我们"校准=计算题"的方法论：v2 G7 校准流程 §4 直接可复用）；
  2. J1 的 8 帧采样换成变化感知采样后，其 rubric 提示词需同步改（时间戳标签语义）；
  3. 格标签小字号误读（P2 实测 1 次）——正式版加大标签或 JSON 对齐；
  4. P2 只验了 garble 一型内容缺陷，其余 7 型（pixelate/face_blur/hand_anomaly…）未逐一验。
- **依赖**：ffmpeg/ffprobe（GPU /usr/bin 在位）、numpy 2.4.6、Pillow 12.3.0（`research/proto/pylibs`）。
- **接缝**：
  - J1/J2 runner：取帧函数替换为 `sheetframe.select_keyframes` + `split_sheets`（对外接口已对齐 judge 需要的 frames 列表）；
  - J6 检测器线：`detect_freeze` 直接可作 freeze/flicker 规则（返回 spans，带 interior/outside_motion 口径）；
  - G7e：总览图+keyframes.json 作为成对审讯载体（v2 的"十帧网格"改版正缺此件）；
  - 人工 CONFIRMATION 复核包：47 夹具各出一张总览图，人工复核从"逐条看片"变"看图"。

## 6. 合规（GPL-3.0）

上游 GPL-3.0：我们**不复制、不分发其代码**；`sheetframe.py` 为思想级独立实现（cleanroom：
实现者只读其 README/参数文档的设计描述，未抄源码），文档引用注明思想出处与License。
若未来要直接 vendor 其脚本进我们的分发物，须先过 owner 法务裁定（人类专属清单）。

## 7. 建议后续（按优先级）

1. **全 40 金标重评 P1**（确定性，零模型配额）：freeze/flicker 两型的确定性检出率+误报率，
   与 J1/J3@0.7 做级联对比（预期：补上 J1 的时序漏检洞，FPR 不劣化）；
2. J1 runner 换 B2+B3 载体重跑金标（模型配额预算 40 次，需 owner 批）；
3. G7e 载体原型扩到 15 fail + 15 struct 夹具（复用 v2 夹具库路径口径，需先在 GPU 端重建夹具物理文件或从 INDEX.md 记录的 workdir 路径迁移）；
4. Skill 化（B4）：把"抽帧→总览→六字段 JSON"固化成 skill-pack 资产。
