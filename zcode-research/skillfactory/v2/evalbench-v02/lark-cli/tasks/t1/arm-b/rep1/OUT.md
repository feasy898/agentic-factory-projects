# 《移动端 3.8 迭代复盘》操作命令清单（lark-cli，可按序直接执行）

**目标文档**：https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh （document token `V3mQ8xYzAbCdEfGh`，取自用户提供的链接，全程通过 `--doc` 参数传入）
**前置条件**：用户本机已安装 lark-cli 且 `lark-cli auth status` 正常（任务前提，不重复认证）。
**执行环境约定**：命令为 bash / Git-Bash 语法（用到 `tee`、`jq`、`tail` 等常见 shell 工具）；在 PowerShell/cmd 下执行需自行调整引号与管道。

> **核实口径声明（如实）**：本清单撰写环境未安装 lark-cli，以下命令**未经本机实测**。全部子命令与 flag 逐一核对自官方仓库 [larksuite/cli](https://github.com/larksuite/cli)（main 分支，2026-09-29 取回）的 README 与 `skills/lark-doc/` 参考文档（依据清单见附录 B），无任何编造 flag。若本地 CLI 版本与 main 分支有差异，按「先 --help 核实」约定先执行 Step 0 的核实命令再继续。

---

## Step 0 · 执行前核实（约定动作，10 秒）

```bash
lark-cli auth status
```
理由：复核登录态与已授权 scope（`docs +script parse` 需 `docx:document:readonly`），token/scope 失效时快速失败。

```bash
lark-cli docs --help
```
理由：核实本机版本下 `docs` 服务与 `+fetch` / `+update` / `+script` 快捷命令名仍然存在，履行「先 --help 核实」约定。

---

## Step 1 · 读取全文，并保存为 ./replay-backup.md

```bash
DOC='https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh'
lark-cli docs +fetch --doc "$DOC" --as user --doc-format markdown \
  | tee ./replay-fetch-raw.json \
  | jq -r '.data.document.content' \
  | tee ./replay-backup.md
```
理由：`docs +fetch` 不带 `--scope` 即读整篇文档、`--doc-format markdown` 指定返回 Markdown 全文（`--revision-id` 默认 `-1` 最新版）、`--as user` 是官方推荐的用户身份；`tee` 把全文同时回显并落盘为 `replay-backup.md`，另存一份原始 JSON 供 Step 4 回查比对。

- 返回值依据（官方 fetch 参考文档「返回值」节）：全文在响应 JSON 的 `data.document.content`，版本号在 `data.document.revision_id`——请记下此值，下文记作 **`<old_revision_id>`**（取自本步的 `replay-fetch-raw.json`）。
- 若本机无 `jq`：先 `lark-cli docs +fetch --help` 查看 `+fetch` 是否支持内置 `--jq` 裁剪参数（该 flag 已在官方文档为 `docs +script` 明确记载；`+fetch` 是否同款支持以 --help 为准），支持则用其替换 jq 管段，并把原始 JSON 另存一次（否则 Step 4 的版本比对改用 Step 4.1 输出中的 `revision_id` 字段）。

---

## Step 2 · 统计正文字数

```bash
lark-cli docs +script --command parse --doc "$DOC" --as user --format json --jq '.data.profile'
```
理由：官方内置 `parse` 脚本接受在线文档 URL，返回的 `profile` 含 `word_count`（字数，即所求）、`char_count`（字符数，供交叉核对）与 `block_count`；`--jq` 是该脚本官方记载的 JSON 裁剪参数。

---

## Step 3 · 在文档末尾追加「复审会决议（2026-10-09）」

### 3.0 先查现有标题层级（决定追加标题用 h1 还是 h2）

```bash
lark-cli docs +fetch --doc "$DOC" --as user --scope outline --max-depth 3
```
理由：飞书 XML 标题层级须连续不跳级（官方规则：`<h1>` 后不能直接 `<h3>`），先看大纲确定新章节标题层级。

### 3.1 追加（逐条如实、不多不少）

```bash
lark-cli docs +update --doc "$DOC" --as user --command append --content '<h2>复审会决议（2026-10-09）</h2><p>结论：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。</p><p>待办一：小何，10/14 前更新埋点文档。</p><p>待办二：小郑，10/16 前给出崩溃率专项报告。</p><callout emoji="⚠️" background-color="medium-red" border-color="red"><p><b>风险：Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。</b></p></callout>'
```
理由：`append` 是官方定义的「仅在文末追加」指令（等价于 `block_insert_after --block-id -1`，只需 `--content`），不触碰原正文任何字符，比 `overwrite` 安全（官方明确警告 overwrite 丢失评论与资源）；风险条目用 `callout` 高亮块（官方色彩规则：强提醒用 `medium-*` 背景、`border-color` 用基础色相）加 `b` 加粗，实现醒目高亮。

- **标题层级自查**：若 3.0 返回的大纲显示文档顶级章节是 `<h1>`，把上行 `<h2>` 改为 `<h1>`（同级追加）；若文档尚无任何标题，也用 `<h1>`。
- 四条文字与【复审会要点】**逐字一致**（含标点），高亮仅为呈现标记，未增删任何字词——逐条映射见附录 A。

---

## Step 4 · 回查写入完整性

### 4.1 重读文末内容

```bash
lark-cli docs +fetch --doc "$DOC" --as user --doc-format markdown \
  | tee ./replay-fetch-after.json \
  | jq -r '.data.document.content' \
  | tail -c 800
```
理由：按官方 update 文档的 Verify 约定（每轮写操作后按影响范围重新 fetch 验证），文末应出现完整新章节：标题 + 结论 + 待办×2 + 风险高亮块，与 3.1 写入内容逐字一致。

### 4.2 版本号比对

```bash
jq -r '.data.document.revision_id' ./replay-fetch-raw.json
jq -r '.data.document.revision_id' ./replay-fetch-after.json
```
理由：写入后版本号 **`<new_revision_id>`**（取自本步第二条命令输出）应大于 Step 1 的 `<old_revision_id>`，相等即写入未生效。

### 4.3 按 ID 定位新块（存证）

```bash
lark-cli docs +fetch --doc "$DOC" --as user --scope keyword --keyword '复审会决议|OOM' --detail with-ids
```
理由：关键词定位新章节并返回 block ID（**`<blk…>`**，取自本步返回值），作为内容完整、位置正确的存证。

- 收尾：`replay-fetch-raw.json` / `replay-fetch-after.json` 为过程文件，可删；`replay-backup.md` 是全文备份，建议保留。

---

## 附录 A · 【复审会要点】↔ 写入内容映射（不得增删的核对表）

| 原始记录（2026-10-09 站会） | 写入 XML | 呈现 |
|---|---|---|
| 结论：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。 | `<p>结论：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。</p>` | 正文段 |
| 待办一：小何，10/14 前更新埋点文档。 | `<p>待办一：小何，10/14 前更新埋点文档。</p>` | 正文段 |
| 待办二：小郑，10/16 前给出崩溃率专项报告。 | `<p>待办二：小郑，10/16 前给出崩溃率专项报告。</p>` | 正文段 |
| 风险：Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。 | `<callout emoji="⚠️" background-color="medium-red" border-color="red"><p><b>风险：Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。</b></p></callout>` | 红底高亮块 + 加粗（仅呈现增强，文字未变） |

章节标题「复审会决议（2026-10-09）」为任务要求的节名。

## 附录 B · 用法核实依据（官方仓库 larksuite/cli，main 分支，2026-09-29 取回）

- `README.md`：`auth status` / `auth check`、全局 `--as user|bot`、`--format`、schema 自省机制
- `skills/lark-doc/SKILL.md`：`docs +fetch` / `+update` / `+script` 场景路由；「文档操作推荐显式指定 `--as user`」
- `skills/lark-doc/references/lark-doc-fetch.md`：`--doc`、`--doc-format markdown`、`--scope outline/keyword`、`--keyword`（`|` 表 OR）、`--detail with-ids`、`--revision-id` 默认最新、返回结构 `data.document.{content,revision_id}`
- `skills/lark-doc/references/lark-doc-update.md`：`--command append`「仅在文末追加，等价于 `block_insert_after --block-id -1`」、`--content`、`overwrite` 丢失评论警告、Verify 回查约定
- `skills/lark-doc/references/lark-doc-script.md`：`parse --doc` 返回 `profile`（含 `word_count`/`char_count`/`block_count`）、`--jq`、`--format`、所需 scope `docx:document:readonly`
- `skills/lark-doc/references/lark-doc-xml.md`：标题 `h1-h9` 层级连续不跳级、`<callout>` 高亮块（子块限 `p` 等与行内标签 `b`）、合法色值（高亮块背景支持 `medium-{色相}`，强提醒用 `medium-*`；`border-color` 用基础色相）
