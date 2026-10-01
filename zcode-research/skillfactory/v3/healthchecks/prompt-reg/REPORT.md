# Skill Healthcheck Report

- 目标包：`D:\workspace\zcode研究\skillfactory\v3\assets\prompt-regression\package`
- 生成时间：2026-09-30T08:44:26+0800
- 评级：**C**（A=0 失败 / B=1 失败 / C=≥2 失败）
- 汇总：5 项检查，2 通过 / 3 失败

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| skill_md_exists | ✅ PASS | SKILL.md 存在（4076 字节） |
| front_matter_fields | ❌ FAIL | front-matter 块缺失（首行不是 ---） |
| eval_present | ❌ FAIL | 缺少 eval/ 目录（无确定性评测） |
| eval_smoke | ✅ PASS | skip: 缺 eval/ 目录，跳过 smoke |
| scripts_syntax | ❌ FAIL | scripts/ 目录不存在 |

## 建议

评级 C：失败项 ≥2，分发前必须完成整改。
- front_matter_fields：front-matter 块缺失（首行不是 ---）
- eval_present：缺少 eval/ 目录（无确定性评测）
- scripts_syntax：scripts/ 目录不存在
