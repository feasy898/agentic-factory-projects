# Skill Healthcheck Report

- 目标包：`D:\workspace\zcode研究\skillfactory\dist\office-templates-skill`
- 生成时间：2026-09-30T09:59:35+0800
- 评级：**A**（A=0 失败 / B=1 失败 / C=≥2 失败）
- 汇总：5 项检查，5 通过 / 0 失败

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| skill_md_exists | ✅ PASS | SKILL.md 存在（10796 字节） |
| front_matter_fields | ✅ PASS | front-matter 五字段齐全（name/version/license/description/permissions 均非空） |
| eval_present | ✅ PASS | eval/ 目录存在 |
| eval_smoke | ✅ PASS | smoke exit=0 \| cmd: python eval/runner.py reference/out reference/out \| stdout 摘要: { "ok": true, "tested": "reference\\out", "reference": "reference\\out", "checks": [ { "name": "units_found", "pass": true, "detail": "8 个期望单元齐全: 周报/case1, 周报/case2, 请示函/case1, 请示函/case2, 会议通知/case1, 会议通知/case2, 工作总结/case1, 工作总结/case2" }, { "name": "products_exact", "pass": true, "detail": "每个单元目录恰含 文书.docx + fields.json" }, { "name": "reference_dir_has_units", "pass": true, "detail": "参照根 referen… |
| scripts_syntax | ✅ PASS | scripts/ 下 1 个 *.py 全部语法可编译: scripts/gen_doc.py |

## 建议

评级 A：无失败项，包结构与确定性评测齐备，可进入分发流程。
