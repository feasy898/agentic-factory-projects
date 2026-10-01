# CONTEXT — zcode-research（skill 工厂 / zcode 研究）

> 建卡：编排批-线3 2026-10-01（docs/project-orchestration.md §1.1）；素材=continue-cards/zcode-research.md（迁移完整性核对 2026-10-01）+ AUTONOMY.md + skillfactory/v5/REGISTRY.md。

## 背景
- 调研+工厂混合体（非 git 目录）：`research/`、`skillfactory/`（v5：assets/dist/library/REGISTRY.md）、`extracted/`（网页解包）、`oss-src/`、大量 `rt_*` 平台调研 HTML/JSON（cline/coze/cursor/pipedream/promptbase/volc/windsurf/gitee/gitcode…）、`AUTONOMY.md`（方法论入口）、`idle-research-1-报告.md`。
- 源机 108 项 3.9G → 净 131M → tar 42M；归属会话轨迹（523 会话）未随迁（windev-01 会话库按迁移口径不迁）。

## 目标
1. 若 skillfactory 为活产线：从 `skillfactory/v5/REGISTRY.md` 接续技能登记与打包（入 SkillFS 门禁数=项目指标）。
2. 方法论沉淀可引用：AUTONOMY.md 与 idle-research-1-报告.md 是结论入口。

## 验收标准（无统一测试套件，做完整性核对）
- 锚点在位：`ls skillfactory/v5/REGISTRY.md research/ extracted/` 应全部在位。
- 迁移基线：文件数 **9111=9111** 两端一致；密扫 6729 文件 4 命中全假阳性（公开 JS bundle ×2 + oracle/fixtures/red-hardcoded-secret/ 自名反例夹具 ×2）。

## 干系人
- owner（skillfactory 是否活产线的定位裁定；产出去向=SkillFS/company-assets 门禁）。

## 当前里程碑
- REGISTRY 接续点待定（先核 REGISTRY.md 尾部登记态）。
- Temporal 裁定：⏸ 暂不挂（迭代型，project-orchestration §1.2）。

## 风险
- 大量 `_tmp*`/`_ab*` scratch 目录随迁保留——确认无用后清理需 owner/接手 agent 裁定，勿擅自删。
- 无 git：目录即唯一副本，git 化待裁。
