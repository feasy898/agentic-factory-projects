# factory/AGENTS.md — 模式 M 全新实现仓纪律

> 权威决策：`../plan/模式M-技术选型决策.md`（其裁决与批次定义优先于任何旧规划）。
> oracle：`../repo/` **封存只读**——实现代码可读作行为参考，但以 `repo/docs/assets/` 规格
> （唯一规格源）为准；**严禁写 repo/**。上游参照物一律放仓库外 `D:/upstream-refs/`。

## 栈与红线

- **TS/Node 22 单栈**（决策 §1）：产品代码全部 TypeScript/JavaScript，运行时 Node ≥22；
  产物为浏览器 JS。**产品零 Python：任何 `.py` 不得入库。**
- **零上游名**（法务红线）：入库树（`git ls-files` 的路径与内容）对投放域上游名（含主名与
  别名，完整词表见本机 `D:/upstream-refs/neutral-words.txt`）大小写不敏感子串**零命中**。
  **词表本身含上游名，永不入库**（oracle 中该表也被 .gitignore 覆盖）；新增上游参照物时
  在仓库外词表追加一行，不在仓内提及任何上游名。
- **数据契约零变更**（决策 §2.2）：specVersion 恒 `1.0.0`、rulesVersion 恒 `1.1.0`、schema 文本、
  规则库数值、报告字段、退出码、目录形状、二维码内容规则全部不动。
- **数据资产字节复用**：已复用资产及 sha256 登记于 `REUSED-ASSETS.md`；
  改动这些文件 = 违约（`npm run verify:assets` 与对应测试会拦）。
  **bad 样本属规格，永不改期望。**
- **每模块双交付**：资产 spec（docs/specs/）+ 冻结/移植 eval（真实执行 exit 0）。
- **eval 真实执行**：任何"过门"结论必须来自本机真实运行且 exit 0；不得以构建代替测试。
- **遇限流等 60s** 再试；**git 分逻辑 commit，不 push**。

## TS 纪律（坑 5，REGENERATE §8 原文照抄）

> **TS 可擦除语法**：Node 类型剥离不支持构造器参数属性
> （`ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX`），一律显式 `this.x = x`；
> import 带 `.ts` 扩展 + `allowImportingTsExtensions`。

（tsconfig.base.json 已设 `erasableSyntaxOnly` + `allowImportingTsExtensions`。）

## workspaces（坑 14 照抄）

必须同时含 `packages/*` 与 `packages/templates/*`（Phase 0 实测教训）——root package.json 已照此设置，勿删。

## node --test（坑 4 照抄）

Windows Node 22 的 `--test` 不展开目录参数：跨包测试一律靠根目录 `node --test`
默认发现（`test/**`、`*.test.mjs`），或显式列出文件；勿向 `node --test` 传目录。

## coverage（坑 16 照抄）

`c8 --include` 必须写**执行 cwd 相对**路径。用 `npm run -w <pkg>` 时脚本在包目录下执行，
写 monorepo 根相对路径会匹配 0 文件 → 0% 覆盖仍 exit 0（"空过"）。
验证门有效性的方法：临时把 `--lines` 抬到必失败值跑一遍，必须 exit 1。

## esbuild 构建链

- `npm run build` → `scripts/build.mjs`：遍历 workspaces 包，包内有 `build` 脚本则执行，无则空跑 exit 0。
- 模板构建契约（M3 落地，形态照抄 oracle）：esbuild iife + `escapeForInlineScript`
  （`<`/`>`/U+2028/9 转义，坑 7）+ `PF_SPEC`/`PF_LOCALE`/`PF_ASSETS` 注入 + `.assets.json` 旁车。
- vendor 引擎 bundle：`packages/templates/vendor/engine.js` 为规范母本（字节复用，
  版本锚 3.88.2，坑 2），各模板**字节复制**该文件，禁止改动或重新生成。

## oracle 差分（决策 §3）

对齐层=契约层：PlayableSpec 输入 → 产物 + 质检报告 + CLI 退出码。
不锁：HTML 字节逐位、截图像素、variance 原始值、墙钟绝对值。
冻结数值向量（F6）必须逐位相等。差分证据落 `artifacts/diff/`（已 gitignore）。
