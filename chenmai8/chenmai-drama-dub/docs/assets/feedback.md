# 反馈处置台账（feedback.md）

- **日期**：2026-09-30
- **来源**：C5 只读整体评审（外部评审员对全仓的 one-shot 评审；评审结论全文由主会话转交，本台账逐条登记处置）
- **纪律**：文档级小修（≤10 行、只动 README/docs）当场修；代码级/方向级不改代码，登记处置口径（修/缓/驳 + 理由 + 复核节点）。上游名零入产出，一律中性描述。
- **本次处置员实跑核实**（下文"已核实"均指本次实查，非转抄）：`git log -15`；`docs/assets/specs/` 目录列举（13 篇）；manifest.json/manifest.md/CONTRACTS.md/REGENERATE.md/README.md 相关段落读取；`pipeline/cli.py`、`pipeline/m9_mix.py`、`pipeline/queue.py`、`pipeline/m10_lipsync.py`、`pipeline/review_server.py`、`scripts/e2e_smoke.sh`、`scripts/gate_b4.py`、`tests/check_e2e.py` 引用行读取；`jobs/e2e01/12_out/metrics.json`、`jobs/e2e01/08_mix/mix_report.en.json`、`jobs/e2e01/07_synth/align_report.en.json` 实读；`jobs.db`/`metrics.db` 行数 sqlite3 实查；`jobs/ep01`、`clips/` 目录实查。
- **本次未复跑**（如实声明）：全量 pytest、五道门整门、e2e 冒烟、契约样本 validate、中性名扫描、B3/B4 门内台账复跑——处置动作仅为文档级修改与台账登记，未触碰代码；评审当日实测（229 passed/5 skipped、中性名零命中、契约样本 10/10）作为来源引用，未独立复现。B3/B4 整门通过记录与评审同口径：引用 `scripts/gate_b4.py` docstring 三跑台账，非本次实测。

## 处置汇总

| 口径 | 条目 |
|---|---|
| 当场修（文档级） | D1 的失实文本部分（README×2 处 + manifest.json×4 行 + manifest.md 勘误注 + CONTRACTS §3#4） |
| 修（登记，待执行） | D1 回炉主体、D2 时长对齐、D4 M12 模块化、D5 队列验收 |
| 缓（登记，外因阻塞） | D3 真实素材母盘（素材未到位+隧道依赖）；ep01 清理待 owner 确认后执行 |
| 驳 | 无——12 条 finding（5 topDebts + 7 demoRisks）经逐条核实全部成立，无驳回项；评审自认的 isomt-lora deferred 与 :9004 frozen-mock 两条"合理如实登记"判定维持 |

---

## 一、topDebts 逐条处置

### D1【high】资产包回炉：B4/B5 约 4,469 行新代码零 spec，manifest 反向失实

- **评审发现**：A4 资产包（58d20f3，09-29）之后 M10/M13/M14/M15 四批代码落地，但 `docs/assets/specs/` 13 篇无一覆盖新模块；manifest 把四模块列 planned 且 blocker 失实；REGENERATE §3 顺序表止于「10 M7」、§4 门清单止于 B3；gate_b4/eval_b5/e2e_smoke/check_e2e 四个验收入口不在资产包；CONTRACTS §3#4 未按其 §4 广播纪律同步。
- **已核实**：specs/ 目录 13 篇确无 m10/m12/m13/m14/m15；`manifest.json:311` 原文『cli run 现为占位（exit 2…）』vs `pipeline/cli.py:6`『run 按依赖图运行一集（M14 任务队列实现：enqueue + resume）』矛盾属实；REGENERATE.md §3 表末行=「10 M7」、§4 代码块末行=gate_b3、§7 变更史末行=m1-ingest 二轮裁定；提交链 58d20f3→…→d41a621（T20）→bd31a75（T20）→15397a7/65a01b4（T19）→eb47eb7（T21）→08c2b71（T23）与评审叙述一致。
- **处置：修**（登记，专项回炉批执行）。理由：按 m1-ingest 先例，spec 补篇须走双轮盲重生成流程（照 spec 盲再生→被迫裁定→钉死），属工作量级，不是 ≤10 行小修；但其中**失实文本已当场修**（见"三、当场修记录"）。
  - 回炉批清单：①补 m10-lipsync / m13-review / m14-queue / m15-metrics 四篇 spec（双轮盲重生成纪律）；②manifest.json/manifest.md 四模块状态翻转 planned→frozen（或如实 frozen-mock）；③REGENERATE §3 增步骤 11-14 与 §4 增 gate_b4/eval_b5/e2e_smoke/check_e2e 三入口；④回炉前勿按 manifest「未开工」表判定模块未实现（manifest.md 已加勘误注）。
- **复核节点**：回炉批 commit 合入时销项；期间以本台账+manifest 勘误注为准。

### D2【high】核心卖点在真实 TTS 下不成立：3/3 句超窗截断 + 对齐率口径分裂

- **评审发现**：e2e01 全链成片 3/3 句合成时长超预算窗（0.674/1.161/1.395s），M9 按句窗硬裁切；M15 `duration_alignment_rate=0.0`（线 0.7）vs M8 `align_report` 自评 `alignment_rate=1.0`（路径口径）双轨；e2e ⑦ 只验句窗非静音不验超窗，14 PASS 掩盖问题。
- **已核实**：`jobs/e2e01/12_out/metrics.json`：duration_alignment_rate value=0.0，per_utt 三句 meas 2.961/2.995/1.474s vs window [1.62,1.98]/[1.44,1.76]/[0.72,0.88] 全部落窗外，且 detail 内自带 `m8_report_alignment_rate_pred: 1.0`（口径分裂已自证在案）；`jobs/e2e01/08_mix/mix_report.en.json` `inputs.voice_track.overflow` 恰 3 条（1.161/1.395/0.674s）；`jobs/e2e01/07_synth/align_report.en.json` summary alignment_rate=1.0（n_in_budget=1/n_df=2/n_atempo=0）；`pipeline/m9_mix.py:7`『超窗末尾按 C2 句窗裁切并在报告记 overflow_s』；`tests/check_e2e.py:39-40,441-484` ⑦ 断言面确只验句窗非静音（silence_frac<2%）。
- **处置：修**（登记，产品级最高优先）。三件事：
  1. TTS 侧时长控制闭环（超预算强制走换短译法，或放宽合成后 atempo 后处理窗口——现状 atempo 冻结 0.9-1.1 救不了 65%-100% 超窗）；
  2. `tests/check_e2e.py` ⑦ 增超窗/截断断言（防 14 PASS 再掩盖）；
  3. M8 `align_report` 的 alignment_rate 改用实测落窗口径（消除 1.0 vs 0.0 双轨；M15 侧已有 pred 对照字段，改 M8 主口径即可）。
  - **演示纪律（即日生效，已写入预案 R3）**：修复前演示禁播全链成片，只播字幕擦除/AI 标识对比片段。
- **复核节点**：修复批 commit 时逐项销项；演示日前必须先行确认 D2 状态。

### D3【high】演示母盘缺失：无任何真实短剧全链交付物，ep01 为半成品

- **评审发现**：clips/ 仅 10.3s 合成素材；jobs/ep01 为 09-28 半成品（00_raw/06_mt/12_out 空）；README 承诺的输入形态从未在本仓工作区全链跑通。
- **已核实**：`clips/` 实查仅 `e2e01_raw.mp4`（595KB）；`jobs/ep01/` 实查 00_raw/06_mt/12_out 为空，残留为 `01_media/audio_16k.wav` 与 `04_dial/*`（asr/diar/emo/utterances 等）——比评审所述「仅 audio_16k.wav 残留」略多，评审此处轻微低估残留量，结论（半成品、无 12_out 成片）不变。
- **处置：缓**。理由：①真实母盘需「有权使用的真实竖屏短剧素材」到位，属外部输入，当前未到位；②跑通三语全链依赖 :9001/:9002/:9003 三条隧道与 GPU 机常驻服务（评审当日 :9001/:9004 实测 down），非本机单方可闭环；③ep01 清理=删除仓库外运行时工作区（`jobs/ep01` 在 .gitignore 口径内），属数据删除动作，本处置不代删——**待 owner 确认后执行**（确认前如需演示，注意勿点开 ep01）。
- **复核节点**：素材到位即启动（真实素材 en/es/ar 三语全链 + 保留 12_out 成片与 metrics.json 作母盘）；ep01 清理随 owner 批复发散。

### D4【medium】M12 合规模块缺位：显式标识只是 e2e 脚本内替身，水印/C2PA 未实现

- **评审发现**：显式 AI 标识是 e2e_smoke.sh 内的「M12 最小替身」（PIL 渲染 PNG + overlay），非管线模块；音频水印/C2PA 完全未实现；C8 label_status 四项只能全 pending；README 承诺只有一半落地。
- **已核实**：`scripts/e2e_smoke.sh:21`『…为本脚本的 M12 最小替身（T11 未收口的部分）』、`:368`『e2e 的 M12 最小替身』（C8 报告 explicit.video 字段）、`:436`『片头 3s 显式标识（M12 最小替身，PIL 渲染 PNG + overlay）』三处自述属实；`docs/assets/CONTRACTS.md` §1 表 C7/C8 生产方=M12（planned）属实；`pipeline/review_server.py:700` `build_compliance` 已存在（C8 生成器可复用面属实）。
- **处置：修**（登记）。最小闭环：①把 e2e 内显式标识逻辑上移进 pipeline（m12 骨架模块，e2e 改调模块）；②`review_server.build_compliance` 复用为 M12 的 C8 生成器单一来源（防两处口径分叉）；③音频水印/C2PA 如实标 pending 不伪装，但须有模块承载（m12 内落占位+reason，而非散在演示脚本）。默认图 m12 步同步补入 queue.DEFAULT_GRAPH（「只增」）。
- **复核节点**：M12 最小闭环 commit 时销项。

### D5【medium】M14 队列零生产使用：jobs.db/metrics.db 0 行 + m10 artifact 申报错位

- **评审发现**：真实 e2e 是 bash 手写顺序驱动不经 queue，两库 0 行；加模块要同步四处（queue DEFAULT_GRAPH / e2e_smoke 顺序 / review_server _stage_* 回路 / gate_b4 docstring）且 queue.py:128 自称与 e2e『同序』无人校验；m10 步 artifact 申报=lip_plan jsonl 而真实交付=done/*.lip.mp4，resume 按计划文件判跳过，误删成片不触发重跑。
- **已核实**：sqlite3 实查 `jobs/jobs.db`（jobs=0、tasks=0）与 `jobs/metrics.db`（step_metrics=0）；`pipeline/queue.py:128-131`『与 scripts/e2e_smoke.sh 的链路同序』注释无校验面；`pipeline/queue.py:200` m10 步 `artifact="09_lip/lip_plan.{lang}.jsonl"` vs `pipeline/m10_lipsync.py:747` 实际产物 `09_lip/done/<ep>.<lang>.lip.mp4`，错位属实。
- **处置：修**（登记）。①用 queue 重放一次 e2e01 全链（或 ep 级真实素材）作为 M14 验收，让 jobs.db/metrics.db 落真实行——重放依赖隧道，排下一 GPU 窗口；②m10 步 artifact 补 done 视频槽位（申报=跳过判据=交付物）；③e2e_smoke.sh 与 queue DEFAULT_GRAPH 两处头部互注「同序校验点」（改一处必查另一处）。
- **复核节点**：queue 重放跑完后销项；重放前不得宣称 M14 已生产验证。

---

## 二、demoRisks 演示预案（逐条登记，演示日必读）

> 七条风险全部成立（评审当日实测+本次抽核）。处置口径=**预案登记**；其中 R3/R7 有当场修或与 D2/D1 联动的部分，已在对应条目标注。

- **R1 隧道脆弱是常态**：评审当日实测 :9001/:9004 down、:9002/:9003 up；REGENERATE §6.1 自认公网链路周期 reset。:9001 一断，e2e/gate_b4④/审校台在线重生成全瘫。
  **预案**：演示日 T-1 提前 keepalive + 完整预跑一遍 e2e；准备离线演示录屏兜底（录屏须避开 R3 所述截断片段）。
- **R2 显存互斥**：lip-fast 常驻物理 cuda:1 与 :9002 备选合成引擎同卡互斥（`scripts/gate_b4.py` docstring 环境注记 4 已如实登记）；误触发备选链懒加载会 OOM 拖垮两条服务。
  **预案**：演示机严禁触发 :9002 备选引擎懒加载；只走常驻服务路径。
- **R3 播放全链成片暴露截断**（与 D2 联动，即日生效）：overflow 3/3 + duration_alignment_rate=0.0，评委拿到 metrics.json 或听出截断即反噬。
  **预案**：D2 修复前禁播全链成片；只播字幕擦除对比、AI 标识对比等无配音时长承诺的片段。
- **R4 审校台静默降级 mock**：:9002 断时单句重生成落 mock 占位音频（`pipeline/review_server.py:574` 起 `_stage_m7`，reason 注明但界面不显眼）。
  **预案**：演示前确认隧道；或显式 force-mock 并口头声明。
- **R5 M15 指标自证软肋**：emotion_similarity=1.0（method 自认同一判别组件回判，`metrics.json` method 字段在案）、listen_wer=0.0（引擎自转写）、lip_score/cost_per_minute 无阈值线（baseline v0）。
  **预案**：演示主打客观可验证项——非口型帧逐字节不变（e2e ⑥b 7 帧全一致）、擦字幕后中文 OCR 命中=0、成片时长差 0.0000、229 测试/五道门/契约样本 10/10；被追问 M15 时如实说明 method 口径。
- **R6 queue 现场演示风险**：`python -m pipeline.cli run` 从未在真实工作区跑过（jobs.db 0 行，本次实查佐证）。
  **预案**：现场演示走已验证的 e2e 路径，不现写 queue 命令；queue 真实验证按 D5 排期。
- **R7 文档现场被翻**：README 不存在的目录、manifest『cli run 占位』与代码矛盾——对照即穿帮。
  **处置**：**已当场修**（README 结构清单与时态、manifest.json 四条 blocker、CONTRACTS §3#4，见下节）；剩余漂移面（specs 缺四篇等）随 D1 回炉销项。

---

## 三、当场修记录（本次 commit，全部 README/docs 面提交）

1. `README.md` 仓库结构清单：删不存在的 `isomt-lora/`、`review/` 两行，改为实际布局（审校台=pipeline/review_server.py，新增 scripts/ 行）。
2. `README.md` 命令行入口行：「编排占位」改为 run=M14 队列实现的如实表述（init|validate|run|enqueue|status|resume）。
3. `README.md` 新增「当前状态」节：B0–B5 完成面 + 已知限制（时长对齐未达标/水印 C2PA 与母盘在途）+ 指针 feedback.md/REGENERATE.md。
4. `docs/assets/manifest.json` planned 区四条失实 blocker 勘误（M10/M13/M14/M15：代码已入库+入库批次+待回炉状态翻转；M14 明确标注原『cli run 占位』失实）。
5. `docs/assets/manifest.md` 「未开工」表头增勘误注：M10/M13/M14/M15 代码已入库，留表仅表示资产包覆盖未回炉。
6. `docs/assets/CONTRACTS.md` §3#4 现状行勘误：占位语义已按该行候选兑现删除（T20/M14），exit 2 现仅指未知步骤/用法错误。
7. 新建本台账 `docs/assets/feedback.md`。

## 四、复核计划

| 项 | 复核节点 |
|---|---|
| D1 回炉 | 回炉批 commit 合入时逐项销项（四 spec + 状态翻转 + REGENERATE 步骤/门入口） |
| D2 时长对齐 | 修复批 commit 销项；任一演示日前强制确认 |
| D3 母盘/ep01 | 素材到位即启动；ep01 清理待 owner 批复 |
| D4 M12 | 最小闭环 commit 销项 |
| D5 队列 | 下一 GPU 隧道窗口重放后销项 |
| R1-R6 预案 | 演示日 T-1 全项过一遍 |
