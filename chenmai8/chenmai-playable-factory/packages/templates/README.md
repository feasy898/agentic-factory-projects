# packages/templates — M3 模板 ×4

`tmpl-match3` / `tmpl-merge` / `tmpl-pullpin` / `tmpl-sort`（批次 2 按规则卡 + 各模板 README 重实现）。

- `vendor/engine.js`：**规范母本**（字节复用资产，非实现代码）。sha256
  `660aa854f150fdc8aac45f08114f644e1569e5ed9cfbfed09fc1b0f24de8a686`，
  与 oracle 四个模板包内 bundle 同字节；版本锚 3.88.2，~1.2MB（REGENERATE 坑 2）。
  各模板包构建时**字节复制**本文件到其 `src/vendor/engine.js`，禁止改动或重新生成。
  已中性化：词表扫描 0 命中（2026-09-30 复核）。
- 构建契约（M3 落地，形态照抄 oracle）：esbuild iife + `escapeForInlineScript`（坑 7）
  + `PF_SPEC`/`PF_LOCALE`/`PF_ASSETS` 注入 + `.assets.json` 旁车。
- 冻结 eval：各模板 `tests/logic-test.ts` 数值向量字节复用（规则卡 §12 算例、
  LCG 三自由度算例、mulberry32 向量，F6/D4）。
