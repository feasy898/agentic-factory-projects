# 交付物：markdown2pdf-cli 的 AGENTS.md（agents-md-spec-t3 / arm-b）

> 本会话仅提供事实卡、未提供仓库检出（工作目录中无 markdown2pdf-cli），故以「全文 + 放置说明」交付；
> 落库时将下方代码块整体保存为仓库根的 `AGENTS.md` 即可。

## 一、AGENTS.md 全文（单文件）

````markdown
# AGENTS.md — markdown2pdf-cli

本文件是面向 AI Agent 与新协作者的项目约定。除本文件明确写出的内容外，请勿假设本项目还存在其他工具链或流程要求。

## 项目概述

- 项目名：`markdown2pdf-cli`。
- Python 3.12 命令行工具：把 Markdown 转换为 PDF。
- 渲染依赖 weasyprint。

## 构建 / 安装

- 使用 Python 3.12 环境。
- 渲染依赖 weasyprint：安装依赖时需包含 weasyprint 并确保其在环境中可用。
- 命令行入口名为 `md2pdf`（安装后通过 `md2pdf` 完成 Markdown → PDF 转换）。
- 具体安装/打包方式以仓库现有配置为准，本文件不额外指定包管理器或安装命令。

## 测试

- 测试框架为 pytest，运行全部测试：

```bash
pytest
```

## 代码风格

- 使用 ruff，行宽上限 100（line-length 100）；改动代码后用 ruff 按此行宽检查风格，例如：

```bash
ruff check .
```

## 目录禁区（务必遵守）

- `render/` 目录正在重构中：**不要改动其中任何文件**——不修改、不新增、不删除该目录内的任何文件，即使改动看似与当前任务相关。
````

## 二、放置位置与理由

- **位置**：仓库根目录下的 `AGENTS.md`（即 `<repo-root>/AGENTS.md`，与项目顶层配置文件并列）。
- **理由**：
  1. 任务明确要求「放入仓库根」；
  2. 事实卡注明「仓库目前没有 AGENTS.md」，因此在仓库根新建该文件不会覆盖任何现有文件；
  3. AGENTS.md 是 AI Agent 进入仓库后首先发现并加载的约定入口（本环境即以工作区/仓库根的 AGENTS.md 作为 instructions 注入），放在根目录可被发现性最大化；
  4. 单文件、全部约定集中一处，符合「单文件 AGENTS.md」的要求，无需引用子目录文档。

## 三、逐句溯源（对硬约束 3 的自检：每句约定均可溯源到事实卡）

| AGENTS.md 中的约定 | 事实卡依据 |
|---|---|
| 项目名 `markdown2pdf-cli` | 「项目名：markdown2pdf-cli」 |
| Python 3.12 命令行工具，Markdown → PDF | 「Python 3.12 命令行工具，把 Markdown 转 PDF」 |
| 渲染依赖 weasyprint，安装依赖需包含并可用 | 「渲染依赖 weasyprint」 |
| 命令行入口名 `md2pdf` | 「命令行入口名：md2pdf」 |
| 测试用 pytest（命令 `pytest`） | 「测试：pytest」 |
| 风格用 ruff，line-length 100 | 「代码风格：ruff，line-length 100」 |
| `render/` 禁区：不修改/新增/删除其中任何文件，原因是重构中 | 「render/ 目录正在重构，agent 不要改动其中任何文件」 |
| 「未写出内容勿自行假设」 | 元规则，用于防止虚构；未引入任何事实卡外的事实 |

反面核对：AGENTS.md 正文中未出现事实卡未提及的任何要求——无包管理器/虚拟环境命令、无 weasyprint 系统库（Pango 等）细节、无其他格式化工具、无 CI、无 Docker、无 ruff 之外的 lint 配置、无测试附加参数。
