# CONTEXT — chenmai8（澄迈8 项目群 + 乱码分支）

> 建卡：编排批-线3 2026-10-01（docs/project-orchestration.md §1.1）；素材=continue-cards/chenmai8.md（迁移验证 2026-10-01）+ `_交付/调度台.md`、`_交付/资产总文件-模块契约与spec-eval.md`（项目群交付口径权威）。

## 背景
- 澄迈杯项目群（非 git 目录群，源机 22 项）：**主项目 6**——具身助餐机器人 / 可玩的中转 / 可玩的小游戏广告 / 咖啡豆质检 / 政务AI脱敏网关 / 短剧多国出海；支撑层 `_交付/`（调度台/资产总文件/开源清单/硬件采购/训练延后）、packages/packager、specs-eval、_ops、_regen*、_reviews、python/、t3_smoke。
- 各项目 plan/repo 二层结构；短剧线有 jobs/（jobs.db、metrics.db）+ clips/materials 生产线；咖啡豆质检含 HF sam2 权重（**GPU 端 blobs 176M 已落地可用**）。
- 乱码分支 = `luanma-branch/`（"可玩的小游戏广告"编码事故名空壳，676B）——owner 待裁弃置项。

## 目标
1. 从 `_交付/调度台.md` 恢复项目群全景并恢复各 repo 开发（venv/node_modules 均可再生物未迁，按各 repo README/plan 重建）。
2. 五条里程碑线（可玩广告/政务网关/助餐/咖啡质检/短剧出海）按里程碑推进。

## 验收标准
- 全景恢复锚点：`ls _交付/调度台.md 短剧多国出海/jobs/jobs.db 咖啡豆质检/repo/models/hf` 全在位。
- jobs.db 可读：python sqlite3 连接 sqlite_master 计数正常（接续卡自检命令）。
- 里程碑验收：acceptance_ref（_交付/资产总文件-模块契约与spec-eval.md）指向的判据逐条实跑（Temporal 模板 workflows/chengmai8-milestone.yaml 约定）。

## 干系人
- owner（交付裁决/硬件采购/评审点）；澄迈杯赛事方（交付口径以 `_交付/` 五文档为准）。

## 当前里程碑
- 迁移完成态：tar 成员 **8403 = 磁盘 8381 文件 + 22 symlink**（HF snapshots→blobs 链接有效），零真实丢失。
- Temporal 裁定：✅ 部分——每子项=一个里程碑意图流（workflows/chengmai8-milestone.yaml，status=shadow [待-bootstrap]）；**日常迭代仍走 glue.team_task 工单**（project-orchestration §1.2）。

## 风险
- 混合技术栈（python venv 需逐 repo 重建 + node + sqlite + 可能的外部渲染工具）——先读各 repo plan 再动。
- `.zcode/`、`D:` symlink、`nul`、venv* 排除未迁（预期）；gguf 大模型未迁（HF 类模型可用）。
- 乱码分支空壳删除需 owner 裁定（本机+GPU 端两份）。
