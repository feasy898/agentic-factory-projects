# Skill Healthcheck Report

- 目标包：`D:\workspace\zcode研究\skillfactory\dist\hot-templates-skill`
- 生成时间：2026-09-30T15:40:59+0800
- 评级：**A**（A=0 失败 / B=1 失败 / C=≥2 失败）
- 汇总：5 项检查，5 通过 / 0 失败

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| skill_md_exists | ✅ PASS | SKILL.md 存在（8682 字节） |
| front_matter_fields | ✅ PASS | front-matter 五字段齐全（name/version/license/description/permissions 均非空） |
| eval_present | ✅ PASS | eval/ 目录存在 |
| eval_smoke | ✅ PASS | smoke exit=0 \| cmd: python eval/runner.py reference/out reference/out \| stdout 摘要: { "ok": true, "summary": { "cases": 8, "checks_total": 40, "passed": 40, "failed": 0, "consistency_threshold": 0.9, "consistency_min": 1.0 }, "checks": [ { "name": "dy/case1/artifacts_present", "pass": true, "detail": "骨架.md（921 字符）+ structure.json（3001 字符）均存在且可解析" }, { "name": "dy/case1/structure_json_self_consistent", "pass": true, "detail": "schema 与计数全部自洽（6 要素）" }, { "name": "dy/case1/platform… |
| scripts_syntax | ✅ PASS | scripts/ 下 1 个 *.py 全部语法可编译: scripts/gen.py |

## 建议

评级 A：无失败项，包结构与确定性评测齐备，可进入分发流程。
