# Skill Healthcheck Report

- 目标包：`D:\workspace\zcode研究\skillfactory\dist\meeting-minutes-skill`
- 生成时间：2026-09-30T03:57:24+0800（healthcheck.py 1.0.0）
- 评级：**A**（A=0 失败 / B=1 失败 / C=≥2 失败）
- 汇总：5 项检查，5 通过 / 0 失败

| 检查项 | 结果 | 说明 |
|---|---|---|
| `skill_md_exists` | ✅ PASS | SKILL.md 存在（6605 字节） |
| `front_matter_fields` | ✅ PASS | front-matter 五字段齐全: name, version, license, description, permissions |
| `eval_present` | ✅ PASS | eval/ 目录存在 |
| `eval_smoke` | ✅ PASS | smoke exit=0（python.exe D:/workspace/zcode研究/skillfactory/dist/meeting-minutes-skill\eval\runner.py D:/workspace/zcode研究/skillfactory/dist/meeting-minutes-skill\reference\out D:/workspace/zcode研究/skillfactory/dist/meeting-minutes-skill\reference\out）stdout: { "ok": true, "checks": [ { "name": "case1/docx_opens_with_three_sections", "pass": true, "detail": "三节标题齐全（一/二/三）" }, { "name": "case1/todo_is_table_with_owner_deadline_columns", "pass": true, "detail": "待办表格表头=['事项', '负责人', '期限']（共 2 数据行）" }, { "name": "case1/summary_counts_match_docx", "pass": true, "detail": "json={\"决议事项\": 2, \"待办事项\": 2, \"风险与关注\": 3, \"合计\": 7} 与 docx 实际一致（决议 2 段、待办 2 行... |
| `scripts_syntax` | ✅ PASS | scripts/ 下 2 个 *.py 全部语法可编译: scripts/gen_docx.py, scripts/minutes.py |

## 建议

- 全绿：可作为分发参照包。
