# 资产总文件：模块、契约、spec+eval（5 项目合订）

> 本文件是"可反复再生的资产"总目录：每个项目的模块切分、模块间冻结契约、每模块 spec+eval 的索引与状态。
> **核心价值主张：spec+eval 能稳定再生可工作的软件。** 模块内可重生成（由 GLM-5.3-Flash 构建工作流按 spec 实现、按 eval 验收），模块间契约冻结。

## 总体工程纪律（全项目适用）

### 资产收敛判据 v1（2026-09-28 主人定义"优化到极限"的可检验形式）

资产包持续优化，**五条全绿 = 达到极限**；任何一条不满足即继续优化循环：

- **C1 再生稳定性**：全部 frozen 模块各完成 ≥2 次独立盲实现试验（隔离目录+冻结测试+禁看原实现+工作流验收门），首跑通过率 100%，且最近一整轮试验的 spec 新增缺口数为 0。
- **C2 spec 自含性**：独立只读 agent 仅凭 spec 接受盘问（魔法数字/时序/默认值/边角各抽样），答案与代码事实一致率 100%。
- **C3 eval 强度**：每模块 eval 具备独立断言（与实现不同源）、变异样本（故意违规必被击中且互不误伤）、零 skip 空过、验收门独立重算指标（不信任模块自报 pass）。
- **C4 契约完备**：CONTRACTS.md 覆盖全部跨模块接口；无未消费 schema 字段、无双路径无主、命令名唯一。
- **C5 目的收敛**：Grok 整体反馈的整改清单全部关闭或显式转"赛后"；最近一轮整体反馈无新增 high。

### 模式 M：成品化模式（2026-09-28 主人指令，全部项目适用）

判据达成后：
1. **总设计师 agent（GLM-5.3）**从目的出发做技术选型决策记录——语言/栈/结构不受原实现约束（原实现只是跑通开源组合的验证载体）。
2. **全新生成**：Flash 构建工作流按资产 spec+eval 实现全新成品（eval 保持行为断言，允许技术适配）。
3. **Oracle 差分**：原实现（开源软件+胶水代码与配置）封存为 oracle——在契约层对齐输入（同 spec/同数据），双实现产物与行为逐项比对（结构/报告/端到端行为）。
4. **通过条件**：行为一致；或差异属于**确定性为目的服务的行为提升**（逐项论证并记录）。
5. 通过 → 全新实现即**正式成品**；原实现仅作 oracle 与回归参照，不再演进。

### 基础纪律
1. 先用开源组合跑通端到端，再基于跑通成品裁剪、整体重写。
2. 重写按模块切分；模块间契约一经冻结，改动需走契约变更流程。
3. 每模块一 spec+一 eval；eval 不过不算完成。
4. 公开仓库内不出现开源项目名/许可证声明（统一见《开源项目清单与授权需求》——已裁定，不再复议）。
5. 训练一律延后（材料与脚本先备好）。

## 项目一：具身助餐机器人（repo: chengmai-feeding-arm）

- 模块切分：**已资产化**——repo/docs/assets/manifest.md（8 核心模块：cs_schema 数据契约层 / cs_sim 仿真 / cs_arm 执行（Mock 链路 frozen、FeetechArm 骨架 partial fail-closed）/ cs_mouth 口部感知 / cs_voice 语音交互 / cs_food 勺检·选碗 / cs_orchestra 行为树编排 / cs_dashboard 护理看板）+ 4 件验收工具（E2E-mock 无硬件端到端 / gate_g1 一键门禁 / verify_g1_reports 报告独立复核 / check_naming 中性名扫描）+ 延后件（训练资产包 frozen-prototype 只写不跑；真机工具链 planned）；每模块带依赖、eval 命令与通过线、重生成顺序位 0–12 拓扑图，状态五级如实（frozen/frozen-prototype/partial/planned/deferred）
- 冻结契约：契约基线 v1.1（`SCHEMA_VERSION="1.1.0"`：cs_schema 8 模型+7 枚举，只增不改名不改值）+ ArmCommand 下发纪律（一切指令经 SafetyEnvelope 组装下发，拒绝≠violation）+ 黑板 8 键冻结清单 + 相机角色切换时序（每送达口恰 2 次切换 + 0.5s 曝光稳定窗）+ 看板 HTTP 4 端点 + 报告 JSON schema（模块自报 pass 不算裁定，verify_g1_reports 独立重算交叉核对）+ 目录与配置契约（详见 repo/docs/assets/CONTRACTS.md C1–C7，含版本锚与 `contract-change:` 变更流程）
- spec+eval 索引：repo/docs/assets/specs/ 11 份逐模块 spec（cs_schema / cs_sim / cs_arm / cs_mouth / cs_voice / cs_food / cs_orchestra / cs_dashboard / e2e-and-gates / training-assets / hw-toolchain）+ REGENERATE.md（整仓再生手册；§0 模型件环境前提与恢复方法——参考件在工作区外 `D:/upstream-refs/robot-vendor`，`CS_VENDOR_ROOT` 可覆盖）+ manifest 逐行 eval 命令与通过线（2026-09-29 实测基线）
- 试验记录：**首轮 ✅ cs_food 试点再生成功**（`_regen/robot-pilot`：隔离目录+冻结测试/conftest sha256 门前后双自检+禁看原实现）——2026-09-29 报告 54 passed+合成自检全对（`chengshao/reports/food_interface_eval.json` pass=true）；**2026-09-30 复跑 gate PASS 2/2**（G1 54 passed；G2 `cs_food.eval` self_check=True）。本轮资产收敛（C1 二轮盲实现/C2 盲评）进行中：本仓首轮已过、二轮待排（当前轮二轮/盲评产物集中于可玩仓，见模式 M 专节注）。门禁现状（2026-09-30 本日实跑）：`python scripts/gate_g1.py` 8 步 7 PASS——①中性名 ②全量 pytest 297 passed+1 skipped（137.9s）③a cs_sim eval tier=mjcf（模型指纹 d75253eb568e8a72，6 关节）③b cs_mouth（检出/拒识 1.000，lat_p95 26.3ms）③c cs_voice ③d cs_food 54 passed ④独立复核 reports=7 failures=0；**唯 ⑤ 看板冒烟 FAIL 为门脚本自身路径 bug**（`scripts/gate_g1.py:182` 指向 `chengshao/tests/test_dashboard.py`，文件实际在仓库根 `tests/`；f3bb888 改进程内冒烟时路径未同步）——看板套件本体在本日直跑 5 passed 绿（待属主修门脚本路径后复跑 8/8）。终态参照：G0–G4+审查修复（f3bb888 四处安全加固）+演示脚本（demo_sim/demo_mouth）。

## 项目二：可玩广告生产线（repo: chengmai-playable-ads）

- 模块切分：**已资产化**——repo/docs/assets/（manifest：5 核心=规格/桥/模板插件/打包器/质检 + 合并项=模型适配器/编排器 + channel-rules 数据文件；含 frozen/planned 状态与 eval 指针）
- 冻结契约：PlayableSpec schema v1（pydantic/ajv 双侧）+ PF 运行时契约 + 产物目录契约 + channel-rules 结构（详见 repo/docs/assets/CONTRACTS.md，含 10 条已识别契约痛点为变更候选）
- spec+eval 索引：repo/docs/assets/specs/（15 份：流水线契约/三消规则卡/渠道适配器表/质检魔法数字+变异样本/可解性单一真源等六件优先级 + 模块 spec）+ REGENERATE.md（15 条实测坑）
- **重生成试验：✅ 通过（2026-09-28，engine-bridge）**——全新 Flash 实现者只凭 spec+冻结测试从零重建（~300 行 5 文件），26/26 测试首跑全绿、行覆盖 96.3%、typecheck 过；验收门由工作流真实执行（失败探针正确 exit 1）。试验发现的 spec 缺口（coverage 空过 bug/事件时序未写明/locale 边角）已回炉。试验形态固化为 SOP（隔离目录+冻结测试+禁看原实现），推广到其余模块。

## 项目三：咖啡豆质检（repo: chengmai-bean-eye）

- 模块切分：**已资产化**——repo/docs/assets/manifest.md（11 核心模块+合成引擎：M1 契约（13 模型+5 Protocol+taxonomy 构造期校验）/ M2 采集三源 / M3 标定 / M6 上下配对 / M7 严重度裁决 / M8 计量 / M9 标准引擎（换标准=换 YAML）/ M10 质量护照 / M11 溯因智能体 / M13 应用与 API 壳 + M12 合成数据引擎；识别两腿已接入：M4 分割（ClassicSeg 产品缺省+OracleSeg 评估上界，W4a/W4b）、M5 分类 RulesV0（W5，acc 0.7712 为 oracle 掩码口径）；另有 6 项数据文件（taxonomy/tray/camera/三套标准 YAML/根因知识表/上游映射内部件）与验收门 gate_d1–d4）；状态分级含「冻结·已知回归」如实用法
- 冻结契约：单粒（BeanMask/BeanObservation，lab8 三通道 ∈[0,255] 构造期拒绝越界）/ 整盘（TrayScan/CalibResult/PairedBean/Measurements/GradingDecision/BatchResult——三重一致性不变式 model_validator：defect_counts 直方、主次分计、bean_count==len(beans)）/ 护照（PassportReport：QR 负载 `{base}/r/{id}|{sha256}`，sha256=canonical_json(BatchResult)）三大 schema + 裁决计数契约（M7 与契约校验器独立双实现交叉验证）+ 可复现确定性契约（同 seed 像素级一致）（详见 repo/docs/assets/CONTRACTS.md，含 7 条契约痛点变更候选）
- spec+eval 索引：repo/docs/assets/specs/ 7 份（markers-geometry / pairing / severity / metrology / standards-yaml / passport / rootcause-kb）+ REGENERATE.md（钉版装配/坑清单）+ 验收门脚本 gate_d1–d4；**终态实测：gate_d4 4/4 PASS**（commit 9346ec6：① pytest 全量 508 passed 404s ② e2e_synth_run 缺省 3 盘 exit 0（out/e2e_synth/summary.json 实测：46.3s/3 盘、均值 15.44s/盘，粒数恢复率 1.0078）③ gate_d3 原样回归 4/4 ④ 中性名扫描 137 文件×23 模式零命中）——即 D1–D4+W13 全链+无数据集合成链（W12 程序化豆素材+铺盘合成器，素材零数据集依赖；HN-Robusta 自建集为规划主路径见 docs/collect_protocol.md）
- 试验记录：**首轮 ✅ M7-severity 试点再生成功**（`_regen/coffee-pilot`：隔离目录+冻结测试 tests/test_severity.py）——**2026-09-30 复跑 83 passed**（1.6s）；首轮发现的六项 spec 缺口已回炉落库（commit 2517095，2026-09-30 14:01：severity.md/CONTRACTS.md 补齐）。本轮资产收敛（C1 二轮盲实现/C2 盲评）进行中：本仓首轮已过+缺口回炉完成，二轮待排。

## 项目四：政务AI脱敏网关（repo: chengmai-gov-ai-gateway）

- 模块切分：**已资产化**——repo/docs/assets/manifest.md（十大模块：GATEWAY 网关主链 / RECOG 三层识别·规则层 / MASKING 可逆脱敏+会话存储 / ROUTING 策略路由 / OUTGUARD 输出侧 / FILECHAN 文件通道+OCR / SEMANTIC 语义层注入检测 / AUDIT 审计+看板 / BENCH 生成器与测评 / GATES 六道门验收体系）+ 基础设施支撑面（INFRA/NAMELINT/E2E/LABELS/WEBUI）；每模块带**六门 eval 指针**（哪道门首验、哪些门逐批回归）
- 冻结契约：C1 Finding（EntityClass 19 值+9 子类型，action_hint 映射冻结）/ C2 RouteDecision（9 码词汇表，R1–R6 矩阵，BLOCK 恒 null 上游）/ C3 MaskingMapping（占位符算法 HMAC-SHA256 一字不差，碰撞升 10/12 位；会话存储与审计库分文件）/ C4 AuditEvent（无 raw 字段；assert_no_raw_pii 入库闸+全库 bytes 级扫描双闸）/ C5 FileReport/FileFinding（导出 re-ingest 零残留铁律）/ C6 HTTP API / C7 环境与配置（密钥只写环境变量名）（详见 repo/docs/assets/CONTRACTS.md 契约基线 v1.0.0，含 4 条痛点候选）
- spec+eval 索引：repo/docs/assets/specs/ 11 份（gateway-main-chain / recognizers-rule / masking-placeholder / masking-normalize / routing-matrix / outguard / filechannel-locations / semantic-wordlist / audit-schema / benchmark-generator / gates）+ REGENERATE.md + docs/contracts/labels.md（标签体系文档自验收 `evals.t0_labels` 8/8）；2026-09-29 本机 15 个 eval 入口逐项实测全绿（manifest 头注记，含 m10_e2e `7 PASS / 0 FAIL / 0 DEFERRED` ≈337s；例外 m8_baselines/m8_quality 规划态如实标注）
- 试验记录：**首轮 ✅ M3-masking 试点再生成功**（`_regen/gov-pilot`：冻结 eval 字节级复制，exit 0 裁定）——**2026-09-30 复跑 8/8**（10 万值插入零碰撞、50 占位符 2000 字符还原 mean 0.044ms<20ms）。本轮资产收敛（C1 二轮盲实现/C2 盲评）进行中：本仓首轮已过、二轮待排。批次终态：B0–B6 门全链（gate_d0+gate_b1..b6）+ **gate_final 收官终检门**（T8.3，批次 0–6 七门全回归+M11 健壮性+公开导出终检+指标终值表，commit 9ac4566）+ **U8/m9 修复**（T8.3 U8 审计零明文宿主裁定 ce33638；T8.4 占位符改形容错还原 88b176f/80d87ae；m9 看板渲染快照增量口径 4cd073d——回归 m9_webui 14/14 ×2、m7_audit 16/16）。

## 项目五：短剧出海引擎（repo: chengmai-drama-dub）

- 模块切分：**已资产化**——repo/docs/assets/manifest.md（契约与共享原语：C1–C8+C2pre 唯一权威 schema / IO-atomic 原子写盘 / JOB-LAYOUT 每集 13 层工作区；本机 CPU 链：M1 摄取 / M2 硬字幕 OCR+校对 / M3 人声分离 / M5 镜头切分+说话人聚类+正脸近景 / M8 时长对齐 / M9 混音成片 / M11 字幕擦除+目标语渲染；GPU 服务模块（双机）：M4 识别+字级对齐+情绪(:9001) / M6 翻译三后端（mock 全离线先行）/ M7 双参考合成(:9002) / TUNNEL / MODELS-REGISTRY；已入库后续批：M10 口型分流(:9003)、M15 指标六项；M12 合规标识/M13 审校台/M14 队列 planned、isomt-lora deferred）+ 验收门 GATE-B0–B4
- 冻结契约：schema 唯一权威 `pipeline/contracts.py`（pydantic v2，`extra="forbid"`，冻结规则 1–11：时间秒 3 位小数 / utt_id 稳定公式 `<ep>-u<起始毫秒 8 位>` / 时间零点=上传音频内相对时间、offset 客户端注入 / 原子 upsert 禁同 id 追加 / diar 未定人填 unknown / C5.atempo 增补等）+ 九类冻结契约文件（镜头表 C1/单句事实 C2/说话人段级 C2-pre/角色卡 C3/译文 C4/合成计划 C5/口型分流 C6/AI 标识 C7/市场合规 C8）+ CLI `validate <kind>` 九 kind 登记（详见 repo/docs/assets/CONTRACTS.md，含 5 条痛点候选）
- spec+eval 索引：repo/docs/assets/specs/ 13 份（contract-io / m1-ingest / m2-ocr / m3-separate / m4-asr-align / m5-diar / m6-translate / m7-tts / m8-align / m9-mix / m11-subs / gpu-tunnel / models-registry）+ REGENERATE.md（双机角色与本机/GPU 分工、§6 坑清单、§7 变更史含各门实测数字）
- 试验记录：**首轮 ✅ M1-ingest 试点再生成功**（`_regen/drama-pilot`：冻结测试 sha256 门前后自检+ffmpeg PATH 注入）——**2026-09-30 复跑 7 passed**（13.4s）。本轮资产收敛（C1 二轮盲实现/C2 盲评）进行中：本仓首轮已过、二轮待排。批次终态：**B0–B4 门全绿**（gate_b4 6/6 PASS exit 0，2026-09-30 第三跑：①全量 208 passed 零跳过 1547.7s ②M10 15 passed ③M15 16 passed ④e2e_smoke 单语 en lip=on exit 0 539s ⑤B3 独有面 51 passed ⑥中性名 94 文件×88 token 零命中）；**B5 进行中**（对应规划 T17/T18 评测集冻结+基线+试训——仓库尚无该批提交，2026-09-30 时点）；并行批 B6 已先行落库（09-30 14:29/14:31：T19/M13 审校台 65a01b4+15397a7，eval 8 passed+1 skipped GPU 豁免；T20/M14 SQLite 队列 bd31a75，tests/test_queue.py 17 passed），T19 注记 gate_b4 由 owner 另行直跑——gate_b4 重跑排队认证新 HEAD。

## 模式 M 专节：成品化实施（首个落地：可玩广告生产线）

> 模式 M 判据见文首「总体工程纪律」。2026-09-30 时点仅可玩项目进入成品化；其余四项目仍处资产收敛（C1–C5）阶段。

- **决策摘要**：`可玩的小游戏广告/plan/模式M-技术选型决策.md`（2026-09-29，GLM-5.3 规划层任总设计师）——**单一 TypeScript/Node 22 栈**全新实现（全 Python 结构性不可行一票否决；Rust/Go 与维持双栈两案拒）；数据资产**字节级复用**（schema JSON、channel-rules v1.1.0、specs-eval 11 件、vendor 引擎 bundle、冻结 JS 测试——factory/REUSED-ASSETS.md 16 项与 oracle 逐项 sha256 对账一致）；冻结 eval JS 侧原样复用、Python 侧按「语义冻结、宿主移植」重写；**数据契约零变更**，唯一预 declare 的实现契约变更 P1（可解性单一真源：模板包导出 check(spec) 进程内调用，双镜像废除）；oracle 差分在**契约层**对齐（PlayableSpec 输入 → 产物+质检报告+CLI 退出码），硬线 D1–D9 / 提升线 P1–P6 / 模块级回退规则 R5。原实现 repo/ 自决策起**封存为 oracle 只读**。
- **批次进展**（新实现落位 factory/，git 仓与 repo/ 平级）：
  - **批次 1「地基与无浏览器模块」✅ 绿**——出口门 `scripts/gate-m1.mjs`：spec/bridge/packager 三包冻结测试全量 + 数据资产 sha 清单复验 + 中性名扫描（commit 71bc5c5「M1.3 批次1出口门」）。
  - **批次 2「判官与模板」✅ 绿**——出口门 `scripts/gate-m2.mjs` **PASS 4/4 exit 0**（commit 64ac950）：批次 1 整门回归 + 四模板 logic 数值向量真实执行 + 判官/编排 tsc strict + **48 包全量矩阵**——`factory/artifacts/matrix/summary.json`（generatedAt 2026-09-30T04:08:47）：mode=full，**48/48 pass、0 fail、0 skip**，wallSec 655.3 ≤ 预算 1200（7 格抖动单重试吸收）。
  - **批次 3「差分与成品」进行中**——oracle 差分 harness 已开工：`factory/scripts/diff/` 四件（d1-packages / d2-crossqc / d3-cli-exitcodes / assemble-report）在飞未落库；首个差分产物 `factory/artifacts/diff/M1.2a-spec-eval.json`（2026-09-30）：**F1 校验裁定 11/11 三侧全等**（golden 4 件三侧同过、bad 6 件三侧同码同路径拒绝）、**F6 数值向量全部 equal**（LCG/mulberry32/盘面生成/最优步/死局重排 trace）；交叉质检矩阵（D5 面）与差分台账 `plan/模式M-差分台账.md` 待产出。
- **factory 仓指针**：`可玩的小游戏广告/factory/`（README.md = 命令与布局；AGENTS.md = 单栈/可擦除语法/零上游名/数据契约零变更纪律；packages/ spec+engine-bridge+packager+templates×4+llmgw+assetkit；qacore/ 判官；pf/ 编排 CLI；webui/；channel-rules/ 与 specs-eval/ 字节复用；scripts/ gate-m1、gate-m2、e2e-matrix、diff/）。oracle 参照 = `可玩的小游戏广告/repo/`（只读）。
- **与资产收敛轮的关系**：本轮 C1 二轮盲实现与 C2 盲评产物当前集中在可玩仓——C1 二轮试点 `_regen2/`（packager2 / qacore2 / rules2，隔离目录+冻结 eval）；C2 盲评三轮 `_regen2/quiz*-verdict.json`（第 1 轮 2026-09-29：24 题中 20 一致 4 不一致；第 2 轮 7 处 mismatch；第 3 轮 2026-09-30：3 处，已回炉修 spec 使如实——commit 4a178a4「代码为权威，本轮零实现改动」）。其余四仓首轮试点已过、二轮待排（各节试验记录已标注）。

---
*更新记录：2026-09-28 骨架；2026-09-30 回填四项目节（机器人/咖啡/政务/短剧）+ 新增模式 M 专节——数字引用各仓 manifest/CONTRACTS/git log 与当日实跑证据（四仓首轮试点 gate 复跑全过；机器人 gate_g1 7/8，步骤⑤门脚本路径 bug 如实记录待属主修复）。2026-09-30 15:00 L4 复核：咖啡 e2e 计时口径校正为 out/e2e_synth/summary.json 实测（46.3s/3 盘、均值 15.44s/盘、count_recovery 1.0078）；短剧节补记 B6（T19/M13+T20/M14）先行落库与 gate_b4 重跑排队。*
