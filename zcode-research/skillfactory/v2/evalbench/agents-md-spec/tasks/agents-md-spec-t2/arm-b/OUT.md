# monorepo 规则冲突裁决（agents-md-spec-t2 / arm-b）

**裁决对象**：仓库 `repo-root/` 中两级 AGENTS.md 的规则冲突——根文件规定「包管理统一使用 pnpm；提交前在仓库根运行根脚本 npm test」，子包 `packages/webapp/AGENTS.md` 声明例外「本包使用 npm 管理依赖（锁文件 package-lock.json）；本包测试命令为 npm run test:web」。

**裁决依据**（AGENTS.md 开放规范的 monorepo 嵌套与冲突规则，见 `D:\workspace\zcode研究\skillfactory\v2\evalbench\agents-md-spec\ASSET-DOC.md` §五，行 66–71）：

- 嵌套机制：在每个子包里再放一个 AGENTS.md，"Agents automatically read the nearest file in the directory tree"——agent 自动读取目录树中**距离被编辑文件最近**的那个文件；
- 冲突裁决："The closest AGENTS.md to the edited file wins"——**离被编辑文件最近者赢**；
- 全体系最高优先级：用户在聊天中的显式提示（本任务未给出任何聊天显式提示，故纯按文件规则裁决）。

---

## ① 在 `packages/webapp/src` 下新增组件并安装依赖 → 用 **npm**

**依据**：被编辑文件位于 `repo-root/packages/webapp/src/`，沿目录树向上**最近的 AGENTS.md 是 `repo-root/packages/webapp/AGENTS.md`**（同包根目录，距离近于仓库根的 `repo-root/AGENTS.md`）。按「最近者赢」，该包的例外条款整体生效：

- 依赖管理：『因客户要求锁文件必须是 package-lock.json，本包使用 npm 管理依赖』→ **用 npm 安装依赖**，锁文件为 package-lock.json；
- 测试命令：『本包测试命令为 npm run test:web』→ 在本包内跑 `npm run test:web`，而非根文件规定的 `npm test`——根的测试入口在该包范围内已被更近的文件覆盖；
- 根的「包管理统一使用 pnpm」对此包**失效**：冲突裁决只看距离，不看哪条规则更"通用"、层级更"高"或出现更早。

## ② 在根 `scripts/` 目录添加运维脚本并安装依赖 → 用 **pnpm**

**依据**：`repo-root/scripts/` 目录下没有 AGENTS.md（目录树：`repo-root/{AGENTS.md, scripts/, packages/webapp/{AGENTS.md, src/}}`），从 `scripts/` 沿目录树向上**最近的 AGENTS.md 就是仓库根的 `repo-root/AGENTS.md`**，根规则全部适用且无任何更近文件覆盖：

- 依赖管理：『包管理统一使用 pnpm』→ **用 pnpm 安装该脚本的依赖**；webapp 的 npm 例外条款只在其自身目录范围内生效（它只对 webapp 内的文件"更近"），管不到 `scripts/`；
- 提交门槛：『提交前在仓库根运行根脚本 npm test』照办——提交前在仓库根执行 `npm test`。此二者并不矛盾：「用哪个**包管理器装依赖**」（pnpm）与「提交前**用哪条命令跑测试**」（`npm test`，根文件明文指定的测试入口）是两个正交维度，根文件对两者各有明确规定，分别执行即可。

## ③ 嵌套配置的生效原则（一句话）

**对每个被编辑文件，沿目录树向上距离最近的那个 AGENTS.md 整体生效、并覆盖更远祖先文件中与之冲突的条款（"The closest AGENTS.md to the edited file wins"，最近者赢），而全体系之上唯一的更高优先级是用户在聊天中的显式提示。**

---

> 附注：已按要求比对 ASSET-DOC 说明与任务——二者一致（任务场景即规范"最近者赢"规则的直接应用），不存在冲突，无需启用"以任务为准"的偏离处理。
