# Monorepo 规则冲突裁决（agents-md-spec-t2 · arm-a）

## 案情（照录自任务给定材料）

- `repo-root/AGENTS.md`：「包管理统一使用 pnpm；提交前在仓库根运行根脚本 npm test。」
- `repo-root/packages/webapp/AGENTS.md`：「本包例外：因客户要求锁文件必须是 package-lock.json，本包使用 npm 管理依赖；本包测试命令为 npm run test:web。」
- 目录树：`repo-root/{AGENTS.md, scripts/, packages/webapp/{AGENTS.md, src/}}`

---

## ① 在 `packages/webapp/src` 下新增组件并安装一个依赖 → **用 npm**

**结论**：使用 npm，在 `packages/webapp` 内执行（如 `npm install <依赖名>`），锁文件落地为该包的 `package-lock.json`。

**依据**：

1. **适用规则集**：对 `packages/webapp/src` 下的文件，同时有两份 AGENTS.md 命中——仓库根的 `repo-root/AGENTS.md` 与更深的 `repo-root/packages/webapp/AGENTS.md`。后者距被操作的 `src/` 更近。
2. **嵌套优先规则**：agents.md 规范明确支持 monorepo 嵌套配置——"agents automatically read the nearest file in the directory tree, so the closest one takes precedence"；其 FAQ 进一步写明："The closest AGENTS.md to the edited file wins; explicit user chat prompts override everything."（来源：https://agents.md/ ，2026-09-29 经 WebFetch 抓取核验）
3. **就近条款给出显式例外**：`packages/webapp/AGENTS.md` 自我声明为「本包例外」，理由是客户要求锁文件必须是 `package-lock.json`，并规定本包用 npm 管理依赖。最具体、最就近的规则覆盖根的通用规则（pnpm）。
4. **不存在真实冲突干扰项**：根文件中的「npm test」是提交前在仓库根运行的测试脚本入口命令（`npm run`/`npm test` 执行的是 package.json 里的 script，与用哪个包管理器安装依赖无关），因此根文件自身并不对依赖管理器给出第二套相反规定；依赖管理器的冲突只发生在「根：pnpm」与「webapp：npm」之间，按就近原则判 npm 胜出。（同一份就近文件还规定了本包测试命令为 `npm run test:web`，与本裁决同一逻辑。）

## ② 在根 `scripts/` 目录添加运维脚本并安装其依赖 → **用 pnpm**

**结论**：使用 pnpm（在仓库根执行安装，如 `pnpm add <依赖名>`），锁文件维持 pnpm 体系（`pnpm-lock.yaml`）。

**依据**：

1. **该子树只有一份生效配置**：`scripts/` 目录及其各级祖先中，除 `repo-root/AGENTS.md` 外没有任何嵌套 AGENTS.md，故唯一适用的是根规则「包管理统一使用 pnpm」。
2. **例外不外溢**：`packages/webapp/AGENTS.md` 的例外措辞是「**本包**例外」，其效力范围由文件所在目录限定（自身目录 + 子目录），仅覆盖 `packages/webapp/` 子树。局部例外不改变根默认规则在 `scripts/` 等其余子树的效力。
3. **旁注**：运维脚本的依赖用 pnpm 安装，与根规则「提交前在仓库根运行根脚本 npm test」并行不悖——后者是测试入口命令，前者是依赖管理方式，二者规范的对象不同。

## ③ 嵌套配置的生效原则（一句话）

**最近优先**：每份 AGENTS.md 的效力范围是其所在目录及全部子目录，当多份同时命中一次操作时，距被操作文件最近（最深）的那份在最具体事项上胜出，而外层文件继续提供未被覆盖的一般约定——即「根定默认、就近例外、例外只覆盖其子树」。

---

## 引用与检查记录

- 任务给定材料（本裁决的主要依据）：`repo-root/AGENTS.md` 与 `repo-root/packages/webapp/AGENTS.md` 全文、目录树（已照录于上文「案情」）。
- agents.md 规范站点：https://agents.md/ ，2026-09-29 本次会话经 WebFetch 抓取，确认嵌套规则原文："agents automatically read the nearest file in the directory tree, so the closest one takes precedence"；FAQ："The closest AGENTS.md to the edited file wins; explicit user chat prompts override everything."
- 本次会话执行的检查：`WebFetch https://agents.md/`（核验嵌套优先原则）；`mkdir -p` + `ls -d` 确认本产物目录存在。未读取 `skillfactory/v2/evalbench/` 与 `skillfactory/v2/agentkit/` 下任何文件（符合公平性限制；本文件为唯一写入）。
