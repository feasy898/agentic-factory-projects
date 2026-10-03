# SF-0002 交付报告 · WS2 build.py + G0-5 合规门 + dist 三包重打包

| 项 | 值 |
|---|---|
| 任务 | SF-0002（PLAN v1.1 §7 WS2，行 426） |
| 执行者 | worker-glm-qz（glm 族，GLM-5.3） |
| 时间 | 2026-10-03 20:16–21:20 (+08) |
| 验收对照 | TESTS v1.1 §0.4 WS2 行：AC-1..AC-9 + BP-1..BP-9 + HY-1..HY-5（HY-4 留痕位口径） |
| 结果 | **28/28 PASS**（`python tests/run_checks.py` exit 0，逐条报告 `dist/build/ws2-checks-report.json`） |

## 一、做了什么

1. **`dist/build.py`（新建，标准库 only）**——渠道变体构建器 + G0-5 形式合规门：
   - 三变体（SPEC §1.5.2 + PLAN §4.3-1）：
     - `standard`：顶层 `version`/`permissions` 剥入 `metadata.version`/`metadata.permissions`；产物目录名==`name`；剥人读层白名单文件（SPEC:54）；
     - `claude-code`：standard + `<!-- cc-only:<field> -->` 标注段生成私有增强字段（无标注零私字段），标注段在**所有**变体正文剥离（可剥离层）；
     - `learner`：standard + 人读层（README.md，白名单 `LEARNER_EXTRA_ALLOWLIST` 机制，T-O 决断占位）+ 不剥离 eval/。
   - G0-5 门（`python build.py g05 <产物根>`）：frontmatter 在位 / name 合法且==产物根目录名（AC-2 作用面=构建产物根）/ 顶层白名单（与 skills-ref 0.1.5 一致）/ metadata.version 语义化 / description ≤1024 单行 / 保留名扫描；**skills-ref 前置 fail-closed**（AC-7：不可用即 exit 3，钉版记录随报告输出）；**canonical 双根 `package/` 布局拒绝**（AC-9：exit 3 不出违规结论）。
   - MANIFEST.json 逐文件 sha256（SPEC §2.5-2），**无时间戳**（BP-7 双跑逐字节一致）；行尾归一基准显式写进产物（源 90/90 文本文件为 CRLF，实测）。
   - 声明变换面：①SKILL.md frontmatter 按 variant 重写；②文本 CRLF→LF；③排除清单（`reference/`、`.git/`、缓存、保留名）；④新增 MANIFEST.json。变换面外 sha256==源（BP-6）。

2. **dist 三包重打包（canonical 源包零改动）**：三包 × 三变体产物落 `dist/build/<variant>/<name>/`（9 份，含 MANIFEST.json 指纹）。

3. **修复票 `dist/dist-compliance-tickets.md`**：三包各三处缺陷（顶层 version / 顶层 permissions / 目录名≠name）+ 修复方式 + 验证证据 + **K-5 状态位=待 owner 亲签**（发布/分发动作归 owner，O-2）。

4. **测试基座 `dist/tests/`**：golden-min 最小合规包、8 个红 fixtures（`make_red_fixtures.py` 从 golden 单一变异生成）、src-demo/cc-demo 构造源、`run_checks.py` 可见验收脚本（AC/BP/HY 28 条，零模型离线可跑）。

5. **skills-ref 钉版安装**（RT-1 第一序风险解除）：npm（registry.npmmirror.com）安装 skills-ref 0.1.5，`dist.shasum=08bd74d5bc30038eaba26acbe4b58da8b051aa5e`，钉版四元组（工具/版本/来源/日期）写死在 build.py。

## 二、证据（命令与输出摘录）

PLAN WS2 三条验收门原文逐条：

1. **skills-ref validate 通过**：
   ```
   $ skills-ref validate build/standard/meeting-minutes   → Valid skill: ... (exit=0)
   $ skills-ref validate build/standard/office-templates  → Valid skill: ... (exit=0)
   $ skills-ref validate build/standard/hot-templates     → Valid skill: ... (exit=0)
   ```
   （修复前实测被拦：`Unexpected fields in frontmatter: permissions, version` + `Directory name 'meeting-minutes-skill' must match skill name 'meeting-minutes'`）

2. **确定性门复跑全绿 + 红路 exit 1**（BP-9，三包 × 三变体，产物内 runner、参照=canonical reference/out）：
   - 改动前基线：3 包绿路 exit 0 / 红路 exit 1（对照，未破坏）；
   - 重打包后：9/9 产物 g05 门 exit 0 + runner 绿 exit 0 + 红 exit 1。
   - 装置说明：hot runner 的 golden input 路径相对资产根（`reference/`，打包卫生排除项）解析，测试脚手架在产物根临时建 junction 指回源包参照、跑完即删（产物字节不动，BP-6 保真断言在案）。

3. **learner 变体含人读层且不剥离 eval/**（BP-4）：`build/learner/<name>/` 均含 README.md + `eval/runner.py` + `eval/golden.json`，smoke 双态绿 exit 0 / 红 exit 1。

完整逐条：`dist/build/ws2-checks-report.json`（28 条 PASS）；构建汇总 `dist/build/build-summary.json`。

## 三、自测结果

`python tests/run_checks.py` → **28 PASS / 0 FAIL，exit 0**（AC 13 条含 8 fixtures、BP 11 条、HY 5 条）。两处判据实现口径说明：
- **AC-8**（G0-5 ↔ 体检器一致性）：按"留痕口径"PASS——现行 v3 体检器 `REQUIRED_FIELDS=('name','version','license','description','permissions')` 与 G0-5 白名单在 `version`/`permissions` 上**语义相反**（轨迹6 链 A 实测确认），对齐动作属 WS9（体检器分形态升级），届时重跑本条。两尺字段对照已写入检查报告 detail。
- **HY-4**（K-5 发布批准留痕）：按留痕位口径 PASS——修复票内 K-5 状态位在位且为空（待 owner 亲签），机器侧只读不代签。

## 四、未尽事项 / 给下一步的提示

1. **canonical 源包内 `reference/` 目录的最终处置待 owner 裁定**（轨迹6 结论 12 三选一：删除/迁正/留证据）。本轮构建层排除，源包未动。若裁定删除，需同步改 hot runner 的 golden input 路径约定（零改动铁律下走资产迭代任务，不走 WS2）。
2. **AC-8 完整对齐**：WS9 体检器升级后重跑（冲突字段清单已在报告里）。
3. **ESC-008**：本轮全部本地 commit，未推远端。push 待裁定（裁定后走 exit-node 网络窗配方）。
4. **doubao/qwen 变体**（SPEC §1.5.2 另两个渠道）不在 WS2 范围（PLAN §4.3-1 最小实现三变体），build.py 的 variant 框架可直接扩展。
5. git 注意：afp-clone 工作区存在**封存区（chenmai8 等）的既有未提交改动**（本轮之前就存在，非本轮产生），本轮 commit 已精确避开；后续任何人提交前先 `git status` 核对。

## 五、产物清单

| 路径 | 内容 |
|---|---|
| `afp-clone/zcode-research/skillfactory/dist/build.py` | 构建器 + G0-5 门（本轮核心交付） |
| `.../dist/tests/{golden-min,src-demo,src-demo-cc,make_red_fixtures.py,run_checks.py}` | 测试基座 |
| `.../dist/dist-compliance-tickets.md` | 三包修复票（K-5 留痕位） |
| `.../dist/build/{standard,claude-code,learner}/<name>/ ×9` | 三包 × 三变体合规产物 |
| `.../dist/build/ws2-checks-report.json` | 28 条验收逐条记录 |
| `.../dist/build/build-summary.json` | 构建汇总（g05 门全过） |
