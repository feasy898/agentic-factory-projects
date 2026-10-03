# dist 三包合规修复票（WS2 · 2026-10-03）

> 依据：PLAN v1.1 §4.3-3 / §7 WS2、O-2 建议默认值（打包前修）、TESTS v1.1 AC/BP/HY 组。
> 修复方式：**canonical 源包零改动**，全部修正在构建层（`dist/build.py` 三变体）完成；
> 产物落 `dist/build/<variant>/<name>/`。

## 缺陷清单（每包三处，skills-ref 0.1.5 实测拦截面）

| 包 | 缺陷 1：顶层 `version: 1.0.0` | 缺陷 2：顶层 `permissions: [shell]` | 缺陷 3：目录名≠name |
|---|---|---|---|
| meeting-minutes-skill | 有 → 剥入 `metadata.version` | 有 → 剥入 `metadata.permissions` | `meeting-minutes-skill` ≠ `meeting-minutes` → 产物目录名=name |
| office-templates-skill | 同上 | 同上 | `office-templates-skill` ≠ `office-templates` → 同上 |
| hot-templates-skill | 同上 | 同上 | `hot-templates-skill` ≠ `hot-templates` → 同上 |

skills-ref 实测（修复前，2026-10-03）：
```
Validation failed for meeting-minutes-skill:
  - Unexpected fields in frontmatter: permissions, version. Only allowed-tools,
    compatibility, description, license, metadata, name are allowed.
  - Directory name 'meeting-minutes-skill' must match skill name 'meeting-minutes'
```

## 验证证据（修复后）

见 `dist/build/ws2-checks-report.json`（AC/BP/HY 逐条）与
`dist/build/build-summary.json`（三包 × 三变体构建 + G0-5 门全过）。
确定性门复跑（BP-9）：三包 × 三变体 runner 绿路 exit 0 / 红路 exit 1（产物内 runner，
参照=canonical 源包 reference/out）。

## 附带处置（构建层声明，canonical 未动）

- `reference/`（官方样例 inputs + 参照产物 out）：oracle 性质判据面，三变体一律排除
  （HY-5 无参照泄漏）。canonical 源包内该目录的最终删除/迁移 **待 owner 裁定**
  （轨迹6 结论 12，处置三选一：删除/迁正/留证据）。
- `README.md`：standard / claude-code 剥离（SPEC §1.1-2 禁包内 README）；learner 变体
  保留为人读层（O-13 裁定）。
- 全部文本文件行尾归一 CRLF→LF（源 90/90 文本文件为 CRLF，实测 2026-10-03）；
  归一基准声明写进每份产物 MANIFEST.json（EI-4 行尾登记基准思想）。

## K-5 发布批准状态位

- [ ] **待 owner 亲签**（发布/分发动作归 owner，O-2；本轮只完成合规重打包与门禁留痕，
  未发布、未分发）。签字证据格式按 HY-4：{签署人, 日期, 被签对象 sha256}，机器侧只读。
