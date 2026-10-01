# Skill Healthcheck Report

- 目标包：`D:\workspace\zcode研究\skillfactory\v3\tools\healthcheck\fixtures\broken-skill`
- 生成时间：2026-09-30T03:57:24+0800（healthcheck.py 1.0.0）
- 评级：**C**（A=0 失败 / B=1 失败 / C=≥2 失败）
- 汇总：5 项检查，2 通过 / 3 失败

| 检查项 | 结果 | 说明 |
|---|---|---|
| `skill_md_exists` | ✅ PASS | SKILL.md 存在（473 字节） |
| `front_matter_fields` | ❌ FAIL | front-matter 缺字段: version, license, permissions（已有: name, description） |
| `eval_present` | ❌ FAIL | 缺少 eval/ 目录（无确定性评测） |
| `eval_smoke` | ✅ PASS | skip: 缺 eval/ 目录，跳过 smoke |
| `scripts_syntax` | ❌ FAIL | 1/1 个脚本语法不过: scripts/bad_syntax.py: 第6行 SyntaxError: invalid syntax |

## 建议

- 多项不达标：结构性问题，建议对照 A 级样本（如 skillfactory/dist/meeting-minutes-skill）重做包骨架。
- **front_matter_fields**：在 SKILL.md 头部 front-matter 中补齐缺失字段（缺哪些见 checks 明细）。
- **eval_present**：建立 eval/ 目录，放置确定性评测 runner（如 runner.py）与 golden 用例清单，保证机器可判、无网络依赖。
- **scripts_syntax**：按 checks 明细修复 scripts/ 下语法错误，本地复验：python -m py_compile <file>。
