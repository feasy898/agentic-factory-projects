# markdown2pdf-cli · AGENTS.md 最终交付（agents-md-spec-t3 / arm-a）

> 本文件即交付物本体：**第一节是写入 markdown2pdf-cli 仓库根目录的 `AGENTS.md` 完整全文**（代码块内逐字即文件内容）；第二节为任务第 4 问要求的放置位置与理由；第三、四节为逐句溯源与硬约束遵守声明。方法依据：已完整读取 `D:\workspace\zcode研究\skillfactory\v2\evalbench\agents-md-spec\ASSET-DOC.md`（《AGENTS.md 开放规范》，agents.md 官网 + 官方仓合并条目）。

---

## 一、AGENTS.md 全文（应置于 markdown2pdf-cli 仓库根目录）

````markdown
# markdown2pdf-cli — AGENTS.md

本文件面向在本仓库工作的 AI 编码代理（coding agent）。

## 项目概览

- 项目名：markdown2pdf-cli。
- Python 3.12 命令行工具：把 Markdown 转换为 PDF。
- PDF 渲染依赖 weasyprint。
- 命令行入口名：`md2pdf`。

## 环境与安装

- 运行环境：Python 3.12。
- 渲染依赖 weasyprint：环境中需备有 weasyprint，方能完成 PDF 渲染。

## 测试

- 测试框架：pytest。
- 运行测试：`pytest`。

## 代码风格

- 使用 ruff，line-length = 100（每行不超过 100 个字符）。

## 目录禁区

- `render/` 目录正在重构：**不要改动其中任何文件**。
````

---

## 二、放置位置与理由

**位置**：markdown2pdf-cli 仓库的**根目录**，文件名 `AGENTS.md`（即 `<仓库根>/AGENTS.md`）。

**理由**（均依据本会话完整读取的 ASSET-DOC.md）：

1. **官方规范规定根目录放置**：ASSET-DOC 第三节 "How to use" 第 1 步原文要点——"Create an AGENTS.md file at the root of the repository"（在仓库根目录创建 AGENTS.md）。根目录是各编码 agent 默认读取该文件的位置，放根目录才能保证被自动发现。
2. **本仓库无嵌套需求**：ASSET-DOC 第五节规定嵌套 AGENTS.md 仅用于 monorepo 子包（nearest file wins）；事实卡未表明 markdown2pdf-cli 是 monorepo，单一根文件即可全覆盖。
3. **全新创建，不涉迁移**：事实卡注明"仓库目前没有 AGENTS.md"，因此是新建文件，无需 ASSET-DOC FAQ 中的迁移步骤（`mv AGENT.md AGENTS.md && ln -s AGENTS.md AGENT.md`）。

**如实说明（放置动作未在真实仓库执行）**：本机未找到 markdown2pdf-cli 仓库实体。已运行核查命令：

- `find /d/workspace -maxdepth 7 -iname "*markdown2pdf*"` → 无任何匹配；
- `ls /d`（核查 D:\ 根目录列表）→ 无 markdown2pdf-cli 目录。

项目仅以事实卡形式给出，故本次交付的形态是上面的 AGENTS.md 全文，其应放置的目标位置为该仓库根目录；未对任何真实仓库做写入。

---

## 三、逐句溯源（每句约定均可回溯到事实卡，硬约束 3）

| AGENTS.md 中的内容 | 事实卡原文出处 |
|---|---|
| 项目名：markdown2pdf-cli | 『项目名：markdown2pdf-cli』 |
| Python 3.12 命令行工具，把 Markdown 转换为 PDF | 『Python 3.12 命令行工具，把 Markdown 转 PDF』 |
| PDF 渲染依赖 weasyprint；环境需备有 weasyprint | 『渲染依赖 weasyprint』（"需备有"是其直接推论，非新增工具） |
| 命令行入口名：`md2pdf` | 『命令行入口名：md2pdf』 |
| 测试框架 pytest；运行测试 `pytest` | 『测试：pytest』 |
| 代码风格 ruff，line-length = 100 | 『代码风格：ruff，line-length 100』 |
| `render/` 目录正在重构，不要改动其中任何文件 | 『禁区：render/ 目录正在重构，agent 不要改动其中任何文件』（措辞近逐字保留） |
| 首行"面向 AI 编码代理"的用途说明 | ASSET-DOC 第一节：规范定位即 "a simple, open format for guiding coding agents"，非项目约定 |

**未写入的内容（因事实卡未提及，硬约束 3 禁止虚构）**：事实卡之外的任何格式化工具（如 black、isort）、CI、Docker、PR/提交规范、部署步骤、安全注意事项章节、依赖安装的具体包管理命令（如 `pip install -e .`，事实卡未说明打包/安装方式，故环境一节只陈述 Python 3.12 与 weasyprint 两个已知事实）。

---

## 四、方法依据与规范-任务冲突说明

- 方法严格按 ASSET-DOC 执行：AGENTS.md 为**纯标准 Markdown、无 schema、无 frontmatter、无必填字段**（ASSET-DOC 第二节："AGENTS.md is just standard Markdown"）；标题层级随意；只写"会告诉新同事的事"（ASSET-DOC 第二节："anything you'd tell a new teammate belongs here too"）。
- **冲突注明（按资产使用说明要求）**：ASSET-DOC 第二、三节建议覆盖"安全注意事项、PR/提交规范、部署步骤"等章节，但本任务硬约束 3 规定每一句都必须溯源到事实卡、严禁虚构事实卡中没有的约束。**以任务为准**，故上述章节一律未写入；AGENTS.md 仅保留事实卡可溯源的最小内容集。

## 五、本次会话实际执行过的核查

1. 读取 `D:\workspace\zcode研究\skillfactory\v2\evalbench\agents-md-spec\ASSET-DOC.md`（全文 107 行，方法来源）。
2. `ls .../agents-md-spec/tasks/` → 仅有 t1、t2，`agents-md-spec-t3` 目录原不存在，由本次 `mkdir -p` 创建（含 `arm-a`）。
3. `find /d/workspace -maxdepth 7 -iname "*markdown2pdf*"` → 无匹配；`ls /d` → 根目录无 markdown2pdf-cli。**结论：仓库实体不在本机，"放入仓库根"只能以"交付全文 + 指明目标位置"方式完成，未执行真实写入。**
4. 测试、构建等命令均未运行——目标仓库代码不在本机，无从运行；本任务交付物是文档本身，不含对仓库的任何可执行验证。
