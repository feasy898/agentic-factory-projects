# CRADLE 协调台账 —— ✅ v2 已完成 2026-09-09 12:0x（tag v2.0，墙钟 ~14h / 4天预算）

## v2 终态（详见 deliverables_v2/）
- **两个头条数字：夹具拦截 15/15=100%（≥90%）、误杀 struct 0/15 + candidate 4/17=23.5%（带内）**
- 9 片三车道成片（本地镜像 9/9 MD5 一致）；生产 G7 零触发；**v1 形变 12.3%（Wan口径25%）→ v2 零形变**
- G7 五子项 + thresholds_v2.yaml（ROC 校准，离线重放 10920 组合）；47 条夹具库四类覆盖
- 结构保持度 flow_cos 0.92-0.96（正控带内/负控 20 倍之上）；Wan 全局 92/200；API 0 次
- 待用户唯一人工动作：deliverables_v2/fixtures/CONFIRMATION.md（A组13确认 + B组4复核）
- 事件：V2-M3 代理静默死亡一次（V2-M3C 接棒，顺带修出 G7 集成假绿 bug）；巡检自动化已删除

---

# v1 归档（09-08 完成，全文见 git tag v1.0 与 deliverables/）

## v2 任务（SPECS_V2.md，墙钟 ≤4 天 → 硬停 ~09-12 21:00）
**核心**：G7 物体恒存门禁（五子项 a/b/c/d/e）× 回归夹具库（v1 克苏鲁废片=夹具）× 三车道重构（pure_gen_short 环境氛围 1-2s / compositing_2d5 食物默认 / evidence_transfer 演示）。
**验收重心**：夹具拦截率 ≥90%（目标100%）、pass_structural 误杀 ≤15%、pass_candidate 误杀 ≤25%（不对称原则：宁误杀不漏网）。产出后重点看食物镜头"永不变形"。

## v2 代理花名册
| 代理 | 任务 | 状态 |
|---|---|---|
| V2-M0 | 审计恢复+磁盘治理+夹具库47条+G7模型6件Volta自查 | ✅ 完成+主控验收（commits 4053905/7635856/544f975；fail15四类/pass_struct15/pass_cand17；v1复跑51s全绿；盘31G；D-051..D-055） |
| V2-M12 | G7五子项实现(M1)+ROC校准与工作点(M2) | ✅ 完成+主控验收（**拦截 15/15=100%、struct误杀 0/15、cand误杀 4/17=23.5%带内**；commits fc53ed9/164ad63/376ee48；pytest 257；thresholds_v2.yaml；g7_runs 876行；D-056..D-059） |
| V2-M3 | 三车道重构+模板v2+合成源验证 | ⚠️ 静默死亡（01:24 后双端零活动，同 M5-PROD 模式）。**代码全部写完未验证**：3 车道 gen + 19 卡 v2（10comp/6pure/2evid/1kb）+ narrative_v2 + 6 测试文件 + 4 工具脚本；pytest 306/3 挂；overlay/实测/验证全未跑 |
| V2-M3C | 接棒：修3测试+overlay库+三车道实测+合成源验证+报告 | ✅ 完成+主控验收（commits 1d3c3cb+ecb2aa7；pytest 309；**修出 G7 假绿 bug**（orchestrator 未注入模型函数，自 M1 起集成链 G7 恒 1.0——校准链不受影响，已修+重验）；overlay 3/6 过审可用；三车道实测 G7 0.98-0.998；结构保持度 flow_cos 0.92-0.96 正控带内；D-060..D-069） |
| V2-M4 | 三车道量产 8-10 片+v1/v2 对比数据 | ✅ 完成+主控验收+**VLM抽帧终检通过**（9片 30/28.5s 逐秒精确；19/19任务 25/25候选；G7生产0触发；Wan 92/200；**v1形变12.3%→v2零形变**；commit f2773de；D-070..D-072） |
| V2-M5 | FINAL_REPORT_V2+夹具确认清单+gallery_v2+README+终检 | 后台运行中（11:1x 派发） |

## V2-M4 终态数字（终报引用）
- 主控 VLM 抽检 v2_t1_seeding_v2 帧：毛肚形状自然零形变/蒸汽豁免生效/字幕"三起三落"正确/数字只在字幕/边缘结构稳定
- 成片：v2_t1×3(30s,5+3+1) v2_t2×3(28.5s,4+4+1) v2_t3×3(28.5s,4+3+1)；ASS 9/9；CER small 5/9→medium 6/9（同音字口径）
- 生产 G7 分数 ∈[0.9758,0.9983]，a=d 最低 0.9515（阈 0.82/0.84）；G7e 全 skipped（目检代位）
- v1/v2 对比：122池15形变(12.3%)/Wan60池25%、8曾pass、6入片 → v2 25候选+21帧 0形变

## V2-M3 关键事实（M4/M5 引用）
- 三车道实测基线：comp S01 overall 0.960/G7 0.984；puregen S09 overall 0.945/G7 0.998（G7c P95=0.5px 几何锁定生效）；evid S18 overall 0.961/G7 0.991（演示源）
- overlay 可用：steam_thin/mist_cool/light_warm（3/6 过审，浓雾类物理性 FAIL 勿用）
- Wan 累计 ~78/200；vid2vid 路径①维持（denoise 0.30，flow_cos 0.92-0.96）
- v1 形变基线（终报用）：60 Wan 候选→15 fail 夹具、8 条曾 pass、6 条入成片；v2 食物全 comp→预期 0
| 🔔 巡检自动化 | automation-4a1163b3（每2小时，09:15 首跑）：双端>90min无变化即判僵死→固化现场→派接棒 | 2026-09-09 07:5x 建立 |
| ↳ 巡检记录 | 08:15 ✓ M3C 正常 → 10:15 ✓ M4 正常（GPU 100%，沙箱 19 任务 10 gating/1 gen/8 pending，14 候选） | — |

## V2-M1/M2 关键事实（后续代理引用）
- 最终阈值：g7a_mode=full 0.82 / g7d 0.84（主工作子项，fail max 0.8365 vs struct min 0.949 间隔0.11）/ g7b delta>4 var>100 churn>12 / g7c P95>30px 灾难网 / g7e 0.6（无API全skipped）
- 校准方法：冷启动初跑→运行JSON落盘→离线重放10920组合栅格扫描→定版OP1→终验重跑逐条吻合（1/3轮达标）
- pass_candidate 被杀4条：FX-C001/C002/C003（毛肚剧烈演化 d/a 真实低分，宁误杀）+FX-C010（夜景churn）——人工复核清单在 G7_CALIBRATION.md §6

## V2-M0 关键事实（后续代理引用）
- 夹具可分性：fail dino∈[0.352,0.845] vs pass_structural∈[0.962,0.984] 零重叠；pass_candidate∈[0.760,0.998] 与 fail 重叠→组合判据必然
- fail 夹具 8 条曾是 v1 verdict=pass、6 条入过成片（伤疤确凿）；最大形变量级：FX-F001 虾仁9只→糊浆 dino 0.352、RAFT P95=128px
- 模型口径：dinov2 fp16 OK；grounding-dino-tiny 必须 fp32+autocast（D-054）；RAFT fp32；SAM fp16 OK
- 夹具→镜头卡追溯链：fixtures.human_source(如 SB_S17_58) → 沙箱库查 shot_id → 卡 subject → G7b 文本提示

## v2 关键事实
- 服务器 HEAD=569108a（SPECS_V2.md 已 commit），v1.0 tag 完好，GPU 空闲，盘 29G（M0 负责清理至 >20G 红线上方并腾 8G+）
- 夹具素材池：主仓 34 LTX 拒绝候选 + 沙箱 60 Wan 候选 + 10 AB 候选；v1 画廊 24 例是 G5 偏差型非天然 fail
- 新模型预算 ~6-8G：DINOv2-L / GroundingDINO(transformers内置,Volta安全) / SAM-B+MobileSAM / RAFT-small / DepthAnything-V1-S / (M3 再议 VACE ~3-4G 或 Fun 视频条件)
- 下载源沿用 D-021（ModelScope 主源）；DECISIONS 从 D-051 续编（单文件增量）
- v1 里程碑对照：M0≤0.5d M1≤1d M2≤1d M3≤1d M4≤0.5d M5≤0.5d；G7 未达标禁止带病进 M3

---

# v1 归档（09-08 完成，全文见 git tag v1.0 与 deliverables/）

> 最终交付：服务器 ~/cradle（git tag v1.0, 13 commits, status 干净）+ 本地镜像 D:\workspace\video-capability-research\deliverables\（reports 4件/output 10片 MD5 全对/gallery INDEX）。
> 墙钟：开工 09-08 00:52 → 完成 09-08 21:05，**约 20.2 小时**（预算 5 天）。全部 §10 九项经主控独立取证通过。

## 项目终态（详见 deliverables/reports/FINAL_REPORT.md）
- 成片 9+1 条（3模板×3变体），生产任务良率 17/17=100%，含降级交付率 100%（≥95% 标准）
- 六门禁全链 + CLIP 双锚启发式 VLM（未经 API VLM 审核，已标注）；阈值全部维持冷启动（上调被试点否决）
- 崩溃恢复 kill -9 演示通过；pytest 226；DECISIONS 50 条；失败画廊 24 例
- Wan 预算 60/200；API 调用 0 次（全本地兜底）；事件：M5-PROD 代理僵死后 M5-CONT 接棒补齐

> 我只做任务下达与协调；重活全部子代理。状态落盘于此 + 服务器 ~/cradle/{PROGRESS,DECISIONS}.md。

## 事实速查
- 服务器: `ssh -i C:\Users\Administrator\.ssh\wsl_key root@203.0.113.40`（Git Bash: `/c/Users/Administrator/.ssh/wsl_key`）
- V100S-PCIE-32GB sm_70, fp16 only / no bf16 / no fp8 / no flash-attn2。盘 99G(83G avail)。Python 3.12.3。现独占。
- 仓库: 服务器 `~/cradle`（git 已 init，SPECS.md 为主）。本地主副本: `D:\workspace\video-capability-research\SPECS.md`
- 墙钟: 开工 2026-09-08 00:52 → 硬停 2026-09-13 00:52
- D 盘参考: `D:\agent-knowledge\05-gpu-machine.md`(机器), `02-network-and-shell-pitfalls.md`(下载源)

## 子代理花名册
| 代理 | 任务 | 状态 | 派发时间 |
|---|---|---|---|
| M1-ENV | venv/torch/diffsynth/模型下载/Volta自查/LTX+Wan冒烟 | ✅ 完成+主控验收（volta PASS 66.45TFLOPS；LTX 3.1s/条；Wan 364.6s/条 480×832；ffprobe 亲核；D-019~D-023） | 09-08 01:0x → 03:5x |
| M2-CODE | 全部管线代码+CPU单测 | ✅ 完成+主控复验（pytest 187 passed 亲测复现；commits 25b7bea/8903d22；D-006..D-018） | 09-08 01:0x → 02:2x |
| M2-EXEC | LTX十镜头闭环+SDXL资产+良率报告v1+wan.py装配 | ✅ 完成+主控验收（12/12 终态 9acc/3fb/0blk；G1-G4/G6 100%，G5 42.4%=启发式资产类型偏差；pytest 192；Wan验证全门禁过 G5=0.745；commit a3b1695；D-024..D-031） | 09-08 04:3x → 06:0x |
| M34-COMPOSE | M3 合成成片(TTS/ASS/CTA/G6硬校验) + M4 一键&kill恢复 | ✅ 完成+主控验收（25.000s 精确成片；CER 3.23%/6.45% 双数字；kill -9 恢复 mtime 级铁证；pytest 209；commits 4dd2135/8dccc36；D-032..D-037） | 09-08 06:1x → 07:2x |
| M5-PROD | 校准+A/B+Wan量产 | ⚠️ 异常死亡（~09:00 僵尸，TaskStop 时已不存在）。**成果实际大部分完成**：D-038..D-045（沙箱隔离/双锚G5 42.4%→96.6%/短路/compose-video CLI/SDXL本地加载/17卡9模板变体）；A/B 10任务全过(08:13)；量产27任务全accepted/60候选58pass(13:25,墙钟6h)。未提交、成片未合成（死点） | 09-08 06:0x → 异常 |
| M5-CONT | 接棒：固化commit+修1测试+合成9成片+A/B结论+良率报告 | ✅ 完成+主控验收+**3片VLM目检通过**（死因修正：合成从未启动非中途崩；9/9 成片 0.0s 偏差；pytest 226；commits 322bb42/35d1938；D-046..D-048） | 09-08 19:45 → 20:0x |
| M6-FINAL | 失败画廊≥20+FINAL_REPORT+README+git收尾+自检清单 | 后台运行中 | 09-08 20:1x |

## M5 终态数字（终报引用）
- 成片 9+1 条（output/），1088×1920，G6 逐字 9/9，CER small 1/9 / medium 8/9（差因 ASR 同音混淆，D-047）
- 生产 17/17 任务 accepted 100% 首轮，候选 48 pass/2 fail（G5 边缘 0.69），0 fallback；A/B 10/10；Wan 60/200
- A/B：竖版胜（0.939 vs 0.917）维持 480×832；阈值全部维持冷启动（G3/G4 上调被试点否决）
- 目检（主控 VLM 抽 3 帧）：t1 无变形无乱码字幕正确 / t2 氛围正常 / t3 字卡数字程序渲染生效

## 事件记录：M5-PROD 僵尸事故（2026-09-08）
- 现象：本地侧 08:56、服务器 13:25(量产PROD_DONE) 后零活动，无完成通知，TaskStop 报任务不存在=异常终止
- 教训：①长期代理要更早分阶段 commit（M5-PROD 攒了 14 文件未提交）；②服务器侧产物是唯一可信进度源（DB+日志），主控巡检要查沙箱（D-038 后生产在沙箱跑，主仓库 output 会长期为空）
- Wan 预算已耗 70/200（A/B 10 + 量产 60）；量产一次通过 27/27、0 fallback

## 主控已定的 M5 校准决策（待写入 M5 代理简报）
1. G5 启发式按资产类型分锚（美食/场景两套 appeal 锚），用 M2 的 62 候选实测数据重定标，重跑存量候选分数验证不劣化美食卡
2. 阈值采纳：G3 0.65→0.78、G4 0.85→0.95（先 5 镜头 pilot 验证 Wan 长片分布再全量）；G5 维持 0.70 待重定标后复核
3. 实现 stable-borderline 短路（同镜头候选分数方差<ε 且全 borderline 时停止重试，省预算——M2 实测 58% 生成量耗在无效重试）
4. 竖/横 A/B（§5.2）：同 5 镜头各跑竖 480×832/横 832×480 各 n_best=1，门禁分布对比，竖版明显劣→全横版+DECISIONS
5. 量产首帧 img2img 风格统一步骤开启（§5.3 规定，当前默认关）
6. Wan 预算规划：~16-20 任务 × n_best3 × 重试 ≈ 60-100 候选 ≤200 上限；~6min/条 → 6-10h GPU

## 关键实测数据（后续代理可直接引用）
- LTX 一条 3.1s（384×512/33帧/steps15，峰值16.2GB）；SDXL 一张 4.4s（8.0GB）；Wan 一条 364.6s（480×832/81帧/steps20，峰值16.9GB）
- Wan 主选模型不存在→PAI/Wan2.1-Fun-1.3B-InP（D-019）；diffsynth 1.1.9 已打 patchify 补丁（D-022，脚本 scripts/07_patch_diffsynth.sh）
- 下载：hf-mirror 不可用，ModelScope curl 11-12MB/s（D-021）；大文件一律 curl 直连
- 盘 62G used / 33G avail（红线 <20G avail）

## M2-CODE 遗留缺口（下一代理必须处理）
1. `src/gen/ltx.py:35`、`src/gen/wan.py:69` 的 DiffSynth 管线装配是 NotImplementedError 桩——需按 M1-ENV 实测的 DiffSynth API 补齐
2. CLIP/edge-tts/whisper/SDXL 仅 stub 契约测试，未运行级验证
3. 下一步（M2-EXEC）：LTX ≥10 镜头"卡→生成→六门禁→路由"闭环 + 阈值校准 + 良率报告 v1——必须等 M1-ENV 交还 GPU

## 里程碑门
- M1 完成判据: volta_check.txt + m1_ltx_smoke.mp4 + m1_wan_smoke.mp4 + json 统计存在且内容合格
- M2 完成判据: ≥10 镜头 LTX 闭环 + 良率报告 v1（reports/milestones/）
- M3: LTX 镜头拼 1 条完整成片（TTS/字幕/CTA）
- M4: cli 一键 + kill 恢复演示
- M5: Wan 8-10 条成片 + 良率统计
- M6: 失败画廊≥20 + FINAL_REPORT + README

## 已知决策（详见服务器 DECISIONS.md）
D-001 盘<150G 继续+瘦身纪律 / D-002 M1 允许单条 Wan 冒烟 / D-003 git 排除大媒体 / D-004 API 空全兜底 / D-005 tmux 前缀 cradle_

## 监控协议（主控每次醒来执行）
1. `ssh ... 'cd ~/cradle && tail -30 PROGRESS.md && git log --oneline | head && tmux ls 2>/dev/null; nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader; df -h / | tail -1'`
2. 收子代理完成通知 → 验收产物（不轻信"完成"二字，查文件）→ 派下一个代理
3. 临近 09-13 硬停 → 无论进度切 M6 收尾模式
