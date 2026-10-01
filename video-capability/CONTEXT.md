# CONTEXT — video-capability（视频能力迭代 / video-capability-research）

> 建卡：编排批-线3 2026-10-01（docs/project-orchestration.md §1.1）；素材=continue-cards/video-capability.md（迁移验证 2026-10-01）+ PM-LEDGER.md + SPECS_V2.md。

## 背景
- 视频生成能力研究/流水线：v2 已收官（PM-LEDGER 2026-09-09 tag v2.0），头条数字：夹具拦截 **15/15=100%**、误杀 struct 0/15 + candidate 4/17=23.5%；v1 形变 12.3%→**v2 零形变**；结构保持度 flow_cos 0.92-0.96。
- v2 收官后转 overnight 线：judge 基准（dl_judge_weights/omnijev_infer/run_judge_smoke）、vpipe VDL_v2 草案、数字人实验/边界补测。
- 非 git 目录；`overnight/数据/`（1.8G）随迁（frames_api/clips_api/golden/quarantine 等 judge 与 QC 产物）。

## 目标
1. vpipe VDL_v2 草案推进（overnight/vpipe/）。
2. owner 人工确认项闭环（唯一待用户动作）。

## 验收标准（无统一测试套件，锚点+台账核对）
- 锚点：`deliverables_v2/FINAL_REPORT_V2.md`、`deliverables_v2/fixtures/`、`overnight/judge基准报告.md`、`SPECS_V2.md`、`mpt_main.py`、三车道/夹具库产出。
- 迁移基线：tar 成员 **5644=磁盘 5644** 自洽；`ls overnight/数据` 产物在位。
- 本地成片镜像 MD5 台账在 deliverables_v2。

## 干系人
- **owner：`deliverables_v2/fixtures/CONFIRMATION.md`（A 组 13 确认 + B 组 4 复核）待人工确认——PM-LEDGER 明示的唯一待用户动作**。

## 当前里程碑
- v2 收官（tag v2.0）→ overnight 线进行中（judge 基准就绪、VDL_v2 草案）。
- Temporal 裁定：⏸ 暂不挂（迭代型，project-orchestration §1.2）。

## 风险
- ⚠️ `overnight/secrets/api_keys.env` **未迁**（密钥纪律排除，留 windev-01 约 10-07 销毁）——重跑需 API key 的脚本前要在 GPU 端以环境变量/OpenBao 重建。
- 关联目录 AI-video-reverse/（3.4G）按 owner 范围令只列不迁。
