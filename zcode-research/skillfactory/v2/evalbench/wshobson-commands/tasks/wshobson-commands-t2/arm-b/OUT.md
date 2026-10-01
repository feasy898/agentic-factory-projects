# 自定义 slash 命令：`release-weekly`（仿 wshobson/commands 库格式）

> 任务：每周五发布版本——①跑全部测试全绿才继续；②版本号从当前值升一个补丁位；③按本次变更写 CHANGELOG 条目；④打 git tag 并推送。
> 格式依据：`ASSET-DOC.md`（§4 命令架构：markdown 文件 + front-matter + 正文指令 + `$ARGUMENTS` 占位符 + 类别目录；§7 决策矩阵；§11 命名规范），并实测核对了库内真实命令文件（见文末第 5 节）。

---

## 1. 文件位置与调用名

| 项 | 值 |
|---|---|
| **放置位置** | `~/.claude/commands/tools/release-weekly.md`（随库安装到 `~/.claude/commands/` 后置于类目目录 `tools/` 下，对应 ASSET-DOC.md §4「安装后的文件组织」第 89–102 行的目录树） |
| **调用名（含前缀）** | `/tools:release-weekly 1.4.2` —— 目录名即前缀（ASSET-DOC.md §4 第 52–61 行：`/tools:xxx`、`/workflows:xxx`） |
| **免前缀替代** | 把 `tools/*.md` 复制到 commands 根目录后可直接 `/release-weekly 1.4.2`（ASSET-DOC.md §4「Alternative Setup, No Prefixes」第 63–74 行） |

**为什么放 `tools/` 而不是 `workflows/`**：按库的决策矩阵（ASSET-DOC.md §7 第 326–334 行）——单一领域、实现路径明确、单个专业能力即可、不需要多代理编排，属于 Tool；且符合库的开发规范（§11 第 401 行）：单一用途、小写连字符、动作清晰的命名（类比 `deps-upgrade`、`deploy-checklist`）。

---

## 2. 命令文件全文

以下即 `~/.claude/commands/tools/release-weekly.md` 的完整内容（可整体复制为该文件）：

````markdown
---
name: release-weekly
description: Weekly Friday release pipeline - run the full test suite, bump the patch version from the current value, write the CHANGELOG entry, then create and push the release tag. Fail-fast - aborts at the first failing step.
model: claude-sonnet-4-0
argument-hint: <current-version>
---

# Weekly Release Pipeline

You are a release engineering expert specializing in safe, repeatable release automation. Execute the weekly release as a strict sequential pipeline in which every step has an explicit pass criterion, and any failed step terminates the whole pipeline immediately.

## Context
This command performs the recurring Friday release for the repository in the current working directory. Nothing may be modified until the full test suite is green; the version is then bumped by exactly one patch position from the current value; the change set is recorded in CHANGELOG.md; and only then is the release committed, tagged, and pushed. Later steps depend on earlier ones, so no step may be skipped, reordered, or executed after a failure.

## Requirements
$ARGUMENTS

`$ARGUMENTS` is the current release version declared by the operator (for example `1.4.2`; a leading `v` is tolerated). It is used as a safety cross-check in Step 2 so the patch bump always starts from the baseline the caller expects. If `$ARGUMENTS` is empty, abort before Step 1 and ask the operator to re-invoke with the current version.

## Instructions

### Execution contract (applies to every step)
1. Run Steps 1 -> 4 strictly in order. Never skip a step, never reorder, never continue past a failure.
2. Each step defines a pass criterion. Proceed to the next step only when the current step's criterion is met.
3. On any failure, STOP immediately: print `RELEASE ABORTED AT STEP <n>: <reason>` followed by the exact failing command output. Make no further modifications. If Steps 2-3 already made local edits, leave them uncommitted and print the cleanup hint `git checkout -- .`. Never tag or push anything after an abort.

### 1. Run the full test suite - all green or abort
Detect the project stack and run the complete test suite (never a subset):

| Stack | Command |
|-------|---------|
| Node.js | `npm test --silent` (or `yarn test` / `pnpm test`) |
| Python | `pytest` |
| Go | `go test ./...` |
| Rust | `cargo test` |
| Other | read package scripts / Makefile / CI config and run the full suite |

- **Pass criterion:** exit code `0` and zero failing tests (all green).
- If anything is red: **ABORT at Step 1** with the failing test list. Do not attempt fixes, do not bump the version.

### 2. Bump the patch version from the current value
1. Locate the version source, checking in order: `package.json` (`version` field), `pyproject.toml` (`version`), `Cargo.toml` (`version`), a `VERSION` file, else fall back to `git describe --tags --abbrev=0`.
2. Read the actual current version `CUR` and normalize by stripping a leading `v`. If `CUR` does not equal `$ARGUMENTS`, **ABORT at Step 2** with `version mismatch: repo says CUR, operator declared $ARGUMENTS` - this protects against bumping from a stale baseline.
3. Compute the target `NEXT` as `major.minor.(patch+1)` of `CUR` (e.g. `1.4.2` -> `1.4.3`). Never touch major/minor, never skip or reuse a patch number.
4. Write `NEXT` into every version source found in (1). Re-read each file and confirm it now reports `NEXT`; any write or verification failure is an **ABORT at Step 2**.

### 3. Write the CHANGELOG entry for this change set
1. Collect the change set since the previous release: `git log $(git describe --tags --abbrev=0)..HEAD --oneline` (in a repository with no prior tag, use the full `git log --oneline`).
2. If `CHANGELOG.md` does not exist, create it with an `# Changelog` header.
3. Prepend - above all existing entries - one Keep-a-Changelog style entry:

   ```markdown
   ## [NEXT] - <today's date, the release Friday>
   ### Added     <- feat: commits
   ### Changed   <- everything else
   ### Fixed     <- fix: commits
   ```

   Derive the bullet lines from the commit list in (1); omit empty subsections.
4. Verify the new entry is the first `## [` heading in the file. Failure to write or verify is an **ABORT at Step 3**.

### 4. Tag the release and push
1. Stage exactly the files touched in Steps 2-3 (version source(s) + `CHANGELOG.md`) and commit them: `chore(release): vNEXT` (a tag must point at a commit that already contains the bump and the changelog).
2. Create the annotated tag: `git tag -a vNEXT -m "Release vNEXT"`. If the tag already exists, **ABORT at Step 4** (version already released - re-check the baseline in Step 2).
3. Verify locally before publishing: `git describe --exact-match` prints `vNEXT`, and `git status --porcelain` shows no unstaged release files.
4. Push the commit and the tag: `git push origin HEAD` followed by `git push origin vNEXT`. A rejected or failed push is an **ABORT at Step 4**; print the local rollback hint `git tag -d vNEXT && git reset --hard HEAD~1` and push nothing further.

### Output
On success, print a release summary: each step with pass/failed, the version transition `CUR -> NEXT`, the CHANGELOG entry heading, the tag `vNEXT`, and the push confirmation.
````

---

## 3. 版本号参数占位符说明（要求 4）

- **占位符写法：`$ARGUMENTS`**。该库的参数机制（ASSET-DOC.md §4 第 78–87 行表；`_raw_README.md:347` "Variables | `$ARGUMENTS` placeholder | Captures and processes user input"）：命令名之后的全部自由文本会被注入文件内的 `$ARGUMENTS` 占位符，无结构化 flag。
- **本命令的传参**：`/tools:release-weekly 1.4.2` → 文件内所有 `$ARGUMENTS` 替换为 `1.4.2`，即操作者声明的**当前版本号**。
- **为什么传当前版本而非目标版本**：任务第②步要求“从当前值升一个补丁位”。命令先读取仓库实际版本，与 `$ARGUMENTS` 交叉校验（不一致即终止），再计算 patch+1（`1.4.2` → `1.4.3`）。这样既保证升位确实“从当前值”出发，又用传参防止在过期基线上误升。
- **补充**：Claude Code 亦支持位置参数 `$1`（此处等价于取第一个词作为版本号）；本命令沿用全库统一的 `$ARGUMENTS` 写法。front-matter 中的 `argument-hint: <current-version>` 用于在命令补全界面提示参数格式。
- **示例**：仓库当前版本 `1.4.2` 时执行 `/tools:release-weekly 1.4.2`，执行成功后版本变为 `1.4.3`，产生条目 `## [1.4.3] - <发布日周五日期>` 与标签 `v1.4.3` 并推送。

## 4. 四步骤与“任一步失败即终止”的对照（要求 3）

| 任务步骤 | 文件内指令 | 通过标准（pass criterion） | 失败动作 |
|---|---|---|---|
| ① 跑全部测试，全绿才继续 | Step 1：按栈全量跑测试（pytest / npm test / go test ./... / cargo test，其余读脚本与 CI 配置） | 退出码 0 且零失败（全绿） | **ABORT AT STEP 1**：输出失败清单，不修复、不升版本 |
| ② 版本号升一个补丁位 | Step 2：读当前版本 → 与 `$ARGUMENTS` 校验 → patch+1 → 写回并复读验证 | 校验一致、写入并验证成功 | **ABORT AT STEP 2**：版本不一致或写入失败即停 |
| ③ 写 CHANGELOG 条目 | Step 3：取上一 tag 以来 `git log` 变更集，按 Keep-a-Changelog 前插条目并验证 | 条目为文件首个 `## [` 标题 | **ABORT AT STEP 3**：写入/验证失败即停 |
| ④ 打 git tag 并推送 | Step 4：提交版本与 CHANGELOG 改动 → `git tag -a vNEXT` → 本地验证 → push 提交与 tag | tag 精确匹配且 push 成功 | **ABORT AT STEP 4**：tag 已存在或 push 失败即停，并给出回滚提示 |

失败语义集中在文件内 "Execution contract" 一节：顺序执行、逐步判定、任一步未达标立即打印 `RELEASE ABORTED AT STEP <n>` 终止全管线、绝不执行后续步骤、绝不推送，并提示 `git checkout -- .` 清理半途的本地改动。

> 设计说明：任务原文第④步是“打 git tag 并推送”；因 tag 必须指向包含②③产物的提交，文件把“提交版本号与 CHANGELOG 改动”并入 Step 4 的第 1 小步，4 个任务步骤与 4 个编号步骤一一对应，未增删步骤。

## 5. 与资产说明的核对记录（文末注明）

- 已实测抓取库内两个真实命令文件核对组织方式（2026-09-29，`curl https://raw.githubusercontent.com/wshobson/commands/main/tools/deps-upgrade.md` 与 `.../workflows/git-workflow.md`）：两者均为 **YAML front-matter（实测仅含 `model:` 字段）+ 正文指令 + `$ARGUMENTS`**，与 ASSET-DOC.md §4 的架构描述一致。
- 任务额外要求 front-matter “至少含名称与描述”：与库不构成冲突（库文件本就有 front-matter），故按任务补入 `name` 与 `description`，另加 `argument-hint: <current-version>` 提示版本参数——这两个字段的加入属任务驱动的扩展（库内取样文件未使用），特此注明。
- ASSET-DOC 与任务无其他冲突，未发现需要“以任务为准推翻说明”的情形。
