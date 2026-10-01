# 自制 slash 命令：每周五补丁版发布

> 仿照 [wshobson/commands](https://github.com/wshobson/commands) 库的命令文件组织方式制作。
> 该库的格式（已核对仓库实际文件，如 `workflows/tdd-cycle.md`、`tools/deploy-checklist.md`）为：
> markdown 文件 + 顶部 `---` YAML front-matter 元数据块 + 正文指令，文件按类别放在子目录
> （`workflows/`、`tools/`），子目录名即调用时的命名空间前缀。

---

## 1) 文件位置与调用名（含正确前缀）

| 项 | 值 |
|---|---|
| 安装方式 | 仓库 README：`git clone https://github.com/wshobson/commands.git ~/.claude`，命令文件置于 `~/.claude/commands/` 下 |
| **文件位置** | `~/.claude/commands/workflows/friday-patch-release.md` |
| 所属类别目录 | `workflows/`（本命令是"多阶段带门禁的开发/发布工作流"，归入库中的 workflows 类别，与 `git-workflow.md`、`tdd-cycle.md` 同类） |
| **调用名（含前缀）** | **`/workflows:friday-patch-release`** |
| 带参数的调用示例 | `/workflows:friday-patch-release 1.4.2` |

> 前缀规则：文件名（去掉 `.md`）即命令名，**所在子目录名即调用前缀**，以冒号连接——库中示例为
> `workflows/feature-development.md → /workflows:feature-development`、`tools/api-scaffold.md → /tools:api-scaffold`。
> 若把文件直接平铺在 `~/.claude/commands/` 根下（库中 README 也支持 `cp workflows/*.md .` 的平铺用法），则无前缀，直接调用 `/friday-patch-release`。

---

## 2) 文件全文

以下即 `~/.claude/commands/workflows/friday-patch-release.md` 的完整内容：

````markdown
---
name: friday-patch-release
description: 每周五补丁版发布工作流：全量测试（全绿门禁）→ 升补丁版本号 → 写 CHANGELOG → 打 tag 并推送；任何一步失败立即终止，禁止带病发布
argument-hint: [new-version]
model: inherit
---

# Friday Patch Release（每周五补丁版发布）

按顺序严格执行以下 4 个步骤，发布目标版本为 $1。
这是一条带门禁的顺序流水线：**每个步骤必须验证通过后才能进入下一步；
任何一步检查失败，立即 STOP，终止整条流水线，不得跳过、重试绕过或"修复后继续"，
把失败原因原样报告给用户，等用户处理后再重新从头执行本命令。**

## Step 1 — 全量测试（门禁：全绿才放行）

- 运行本仓库的全量测试套件（按项目实际入口执行，例如 `npm test` / `pytest` / `go test ./...`，以仓库配置为准，不得只跑部分用例或单个测试文件）。
- **GATE**：所有测试必须全部通过（0 failed、0 errored；有覆盖率门槛的项目还需达标）。
- 任一用例失败、套件无法运行或结果不确定 → **立即终止**，报告失败输出，不执行 Step 2。

## Step 2 — 版本号升一个补丁位

- 从项目清单文件读取当前版本号（按项目实际为准：`package.json` 的 `version`、`pyproject.toml`、`Cargo.toml` 等）。
- 仅修改补丁位：`MAJOR.MINOR.PATCH → MAJOR.MINOR.PATCH+1`（例如 `1.4.2 → 1.4.3`）。
- 本次发布的目标版本号以命令参数传入：**$1**。若参数为空或与"当前版本 +1 补丁位"的推算不一致，**立即终止**并报告差异，禁止自行猜测版本号。
- 将新版本写回清单文件；若项目中存在多处版本号引用（如锁文件、常量文件），一并同步更新。
- 提交一次版本号变更 commit（message 按仓库惯例，如 `chore(release): v$1`）。
- **GATE**：写回后重新读取校验版本号确为 $1，否则**立即终止**。

## Step 3 — 撰写 CHANGELOG 条目

- 在 `CHANGELOG.md` 顶部新增本次版本的条目（遵循 Keep a Changelog 习惯：`## [1.4.3] - YYYY-MM-DD`）。
- 条目内容基于自上一个 tag 以来的真实变更（`git log <上一个tag>..HEAD --oneline`），归类为 Added/Changed/Fixed/Security 等；只写实际发生的变更，不得编造。
- 若 `CHANGELOG.md` 不存在或无法确定上一个 tag → **立即终止**并报告。
- **GATE**：条目头部版本号必须与 Step 2 的 $1 完全一致，否则**立即终止**。

## Step 4 — 打 tag 并推送

- 按仓库惯例创建附注 tag：`git tag -a v$1 -m "Release v$1"`。
- 推送当前分支及其 tag：`git push && git push origin v$1`。
- **GATE**：tag 已存在于远端（`git ls-remote --tags origin v$1` 能查到）且推送无报错，发布完成；推送被拒（如无权限、tag 冲突、非快进）→ **立即终止**并报告，不得 force push。

## 全局红线

- 顺序固定：1 → 2 → 3 → 4，不得调换、并行或跳步。
- 每步的 GATE 检查是硬门禁：失败即整条流水线终止，已完成的变更保持原样并明确告知用户（Step 2/3 产生的本地 commit 是否回滚由用户决定）。
- 不执行本文件列出的 git 写操作之外的任何破坏性操作（force push、删 tag、改历史等一律禁止）。

$ARGUMENTS
````

---

## 3) 四步骤的顺序执行与失败即终止

正文中已将任务给定的 4 个步骤写成固定顺序的门禁流水线：

1. **Step 1 全量测试**：跑完整测试套件，设硬性 GATE——全绿才放行（对应任务"全绿才继续"）。
2. **Step 2 升补丁位**：读当前版本 → 仅 PATCH 位 +1，并校验与传入参数一致（对应任务"版本号升一个补丁位"）。
3. **Step 3 CHANGELOG**：基于真实 `git log` 写条目，GATE 校验条目版本号与 Step 2 一致（对应任务"按本次变更写 CHANGELOG 条目"）。
4. **Step 4 tag + 推送**：`git tag -a` + `git push`，GATE 用 `git ls-remote` 验证远端 tag（对应任务"打 git tag 并推送"）。

失败即终止的机制由三处共同保证：

- 文件开头总规则："任何一步检查失败，立即 STOP，终止整条流水线，不得跳过、重试绕过"，并要求报告失败原因；
- 每一步末尾的 `**GATE**` 行给出该步的通过条件与失败动作；
- 结尾"全局红线"再次强调顺序固定、门禁硬性、禁止 force push 等破坏性兜底操作。

## 4) 版本号的参数占位符写法

- **占位符**：正文中以 **`$1`** 表示"命令名后的第 1 个位置参数"，即版本号。Step 1 之外的 2/3/4 步中所有出现版本号的地方都写作 `$1`，Claude 执行时会用用户实际输入的参数做文本替换。
- **调用方式**：`/workflows:friday-patch-release 1.4.3` → 文件中所有 `$1` 替换为 `1.4.3`。
- **配套 front-matter**：`argument-hint: [new-version]` 会在命令补全列表里提示用户"此命令需要一个版本号参数"。
- **备选写法**：`$ARGUMENTS` 表示命令后的**全部**输入文本（库中现有文件均采用此写法，如 `deploy-checklist.md` 的 `for: $ARGUMENTS`）。本文件在正文末尾保留了一行 `$ARGUMENTS`，用于接收附加备注（如"跳过覆盖率"之类的自由文本说明）；若希望整段输入都当作版本号，把正文中各处 `$1` 换成 `$ARGUMENTS` 即可。位置参数 `$1`、`$2`… 与整体的 `$ARGUMENTS` 均为 Claude Code slash 命令的标准占位符语法。
