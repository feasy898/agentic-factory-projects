# 《移动端 3.8 迭代复盘》复审会决议落库 · lark-cli 命令清单（按序直接执行）

> 目标文档：https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh （URL 已在任务中给定，**无需占位符**，下文直接引用）
> 完成定义：① 全文读取并另存 `./replay-backup.md`；② 报出正文字数；③ 文末追加「复审会决议（2026-10-09）」（内容逐条来自复审会要点，风险高亮）；④ 回查一次确认写入完整。

## 0. 执行前须知（全局约定）

- **成功判定**：每步以 JSON 信封 `ok == true`（或退出码 0）判定成功，**不要用 `code == 0`**——成功信封没有顶层 `code` 字段，按旧惯例判断会把成功误判为失败。（依据：ASSET-DOC §5.2 / §8.1，源自官方 ERROR_CONTRACT）
- **身份**：所有 docs 命令显式带 `--as user`。官方 lark-doc 明确"文档操作推荐显式指定 `--as user`"；bot 身份查用户资源会"返回空成功而非报错"。
- **本地路径**：涉及本地文件的参数一律用 cwd **相对路径**（`--file`/`--output`/`@file` 仅接受相对路径，绝对路径报 `unsafe file path`）。（依据：ASSET-DOC §8.1 安全规则 5）
- **不盲猜 flag**：拿不准的用法先 `lark-cli <命令> --help` 或 `lark-cli schema docs.+fetch`（schema 子命令名以 `lark-cli schema` 列表输出为准）核实后再执行，本清单中此类点均已标注。
- **核实声明**：本机未安装 lark-cli，清单无法本机实跑；全部命令与 flag 已逐条对照官方仓库 `larksuite/cli`（main 分支）以下文件核实，未发现即不写（见文末来源清单）。执行前建议对每条命令跑一次 `--help` 做最终确认。

---

## 1. 读取全文，并另存为 ./replay-backup.md（任务项 1）

### 1.1 拉取全文（完整 JSON 信封落盘）

```bash
lark-cli docs +fetch \
  --doc "https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh" \
  --doc-format markdown \
  --as user \
  --format json \
  > ./replay-fetch.json
```

**理由**：`docs +fetch` 是官方"读取/摘要"场景的指定命令，`--scope` 缺省即读整篇文档；`--doc-format markdown` 让 `content` 以 Markdown 返回（默认 xml）。完整信封落盘可同时保留 `revision_id`（可选加固后续写入）与 `reference_map`，官方提示 `content` 和 `reference_map` 属同一份响应、应完整保留。

**判定**：`jq -e '.ok == true' ./replay-fetch.json`

### 1.2 从信封提取全文写入备份文件

```bash
jq -r '.data.document.content' ./replay-fetch.json > ./replay-backup.md
```

**理由**：+fetch 的返回结构已核实为 `data.document.{document_id, revision_id, content, reference_map, tips}`，用 `jq -r` 提取 `content` 即全文 Markdown，落盘相对路径 `./replay-backup.md`，完成任务"读取并同时保存"。1.1 + 1.2 两步合计即任务项 1。

> **⚠️ 核实备注（先 --help 口径）**：官方 `lark-doc-fetch` 参考与 README 均**未记载** `+fetch` 支持 `--output` 落盘参数（`--output` 仅在 `base +record-list`、`auth qrcode` 等命令处出现）。执行前请跑 `lark-cli docs +fetch --help` 确认：若该版本支持 `--output`，可用一条命令直接落盘 `./replay-backup.md` 替代 1.1–1.2 的提取步；本清单按"不编造 flag"原则采用已核实的信封 + jq 方案。

---

## 2. 统计正文字数（任务项 2）

```bash
lark-cli docs +script \
  --command parse \
  --doc "https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh" \
  --format json \
  --as user
```

**理由**：`docs +script parse` 是官方字数统计能力，`--doc` 接受在线 Docx/Wiki URL 或 token，返回 profile 含 `word_count` / `char_count` / `block_count`（需 `docx:document:readonly` scope）。**不能**拿 `./replay-backup.md` 喂 `--content`——官方注明 parse 不支持 Markdown 输入（仅 XML），故走 `--doc` 在线统计。

**报数口径**：`word_count` 为正文字数、`char_count` 为字符数，向用户报数时注明口径。返回 JSON 中 profile 的具体字段路径未在参考中给出，执行时可用 `lark-cli schema docs.+script` 核实后再解析。

---

## 3. 文末追加「复审会决议（2026-10-09）」（任务项 3）

### 3.1 追加前：查看标题大纲，确定新节标题层级

```bash
lark-cli docs +fetch \
  --doc "https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh" \
  --scope outline --max-depth 2 \
  --as user \
  --format json
```

**理由**：官方 XML 规定标题 `<h1>`–`<h9>` "层级须连续，不跳级"；先看大纲决定新节用 `<h1>` 还是 `<h2>`（下文命令按常见复盘文档结构用 `<h2>`，若大纲显示应衔接其他层级，替换之）。此步是追加前的定位读取，不是任务项 4 的回查。

### 3.2 追加决议小节（文末，一条命令）

```bash
lark-cli docs +update \
  --doc "https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh" \
  --command append \
  --as user \
  --content '<h2>复审会决议（2026-10-09）</h2><ul><li>结论：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。</li><li>待办一：小何，10/14 前更新埋点文档。</li><li>待办二：小郑，10/16 前给出崩溃率专项报告。</li></ul><callout emoji="⚠️" background-color="light-red" border-color="red"><p><b>风险：Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。</b></p></callout>'
```

**理由**：`docs +update --command append` 是官方"仅在文末追加"指令（等价于 `block_insert_after --block-id -1`），一次 `--content` 可携带多个顶层块；内容逐条取自【复审会要点】，无增删；风险条目用 callout 高亮块（`background-color="light-red"`、`border-color="red"`、`⚠️` emoji）+ `<b>` 加粗醒目呈现——均为官方 XML 语法（+update 默认 `--doc-format xml`）。

**内容保真对照（要点 → 写入文本，逐字一致）**：

| 复审会要点 | 写入文本 |
|---|---|
| 结论：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。 | 结论：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。 |
| 待办一：小何，10/14 前更新埋点文档。 | 待办一：小何，10/14 前更新埋点文档。 |
| 待办二：小郑，10/16 前给出崩溃率专项报告。 | 待办二：小郑，10/16 前给出崩溃率专项报告。 |
| 风险：Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。 | 风险：Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。（callout 高亮 + 加粗，文字未改） |

**3.2 注意事项**：

- **为什么用 XML 不用 Markdown**：官方规定"仅在用户明确要求或必须保真 Markdown 时使用 Markdown"（且须先读 `lark-doc-md.md` 参考）；本次用户未要求 Markdown，故用默认 XML。
- **--dry-run 未核实**：官方 `lark-doc-update` 参考未记载 `+update` 支持 `--dry-run`。若 `lark-cli docs +update --help` 显示支持，建议先预览请求再正式执行；不支持则跳过（本命令为纯追加、不删改原文，风险可控）。
- **退出码 10 = 确认门禁而非错误**（`error.type=confirmation`）：应停下向用户展示 `action`/`risk` 取得同意后，把 `hint` 指出的确认 flag **追加到原命令末尾**重试；绝不静默加 flag 绕过。
- **引号**：`--content` 值内无单引号字符，bash 单引号包裹可直接使用；PowerShell 下同样可用单引号字符串。整段是一行命令，`\` 仅为排版换行。

---

## 4. 追加后回查一次，确认写入完整（任务项 4）

### 4.1 重新拉取全文

```bash
lark-cli docs +fetch \
  --doc "https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh" \
  --doc-format markdown \
  --as user \
  --format json \
  > ./replay-after.json
```

**理由**：任务要求的**唯一一次**回查；重新拉全文，既能确认新节写入完整，也能确认原文未被追加操作扰动。

### 4.2 本地校验（jq / grep，只读本地文件）

```bash
jq -e '.ok == true' ./replay-after.json
jq -r '.data.document.content' ./replay-after.json > ./replay-after.md

grep -n "复审会决议（2026-10-09）" ./replay-after.md
grep -n "3.8 灰度放量节奏由 5% 调整为 10%" ./replay-after.md
grep -n "小何，10/14 前更新埋点文档" ./replay-after.md
grep -n "小郑，10/16 前给出崩溃率专项报告" ./replay-after.md
grep -n "Android 低端机 OOM 率仍高于 0.5% 阈值" ./replay-after.md
```

**判定**：五条 grep 全部命中（标题 + 结论 + 两条待办 + 风险），即写入完整；`./replay-after.md` 除末尾新增小节外应与 `./replay-backup.md` 内容一致（若 diff 因 Markdown 渲染差异产生噪声，以五条 grep 命中 + 抽查原文段落为准）。callout 在 Markdown 输出中的呈现可能带引用标记，按子串匹配即可。

---

## 5. 返回值 / 占位符来源对照

| 值 | 是否占位符 | 取自哪一步 | 用途 |
|---|---|---|---|
| 文档 URL `https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh` | 否 | 任务给定 | 所有 docs 命令的 `--doc` |
| `data.document.revision_id` | 否（实际值） | 第 1.1 步返回 | 可选加固：传给第 3.2 步 `--revision-id` 防并发覆盖（该 flag 在 update 参考中已核实存在；非必需） |
| `data.document.content` | 否 | 第 1.1 步返回 | 第 1.2 步提取落盘 `./replay-backup.md` |
| `word_count` / `char_count` / `block_count` | 否 | 第 2 步返回 | 向用户报正文字数 |
| 大纲层级 | 否 | 第 3.1 步返回 | 决定第 3.2 步 `<h2>` 是否换成相邻层级 |
| `./replay-backup.md`、`./replay-after.md`、`./replay-fetch.json`、`./replay-after.json` | 否（本清单自定名） | 第 1、4 步落盘 | 备份与回查比对 |

## 6. 异常速查（依据官方错误契约）

- `error.type=authorization`（退出码 3）：读 `missing_scopes`，用 `lark-cli auth login --scope <缺失scope>` 补授权后重试。
- `error.type=network`（退出码 4）：可安全重试；注意 `retry_after_seconds`。
- 退出码 10（`type=confirmation`）：见 3.2 注意事项，确认门禁，非失败。
- 判断成功只看 `ok == true` / 退出码 0；`message`/`hint` 不可用于分支判断。

## 7. ASSET-DOC 与任务的冲突说明（任务要求注明）

ASSET-DOC 与任务**无实质冲突**：场景路由（+fetch 读取 / +script 统计 / +update 追加）、`--as user`、相对路径、`ok == true` 判定均一致执行。唯一出入：任务项 1 的"读取并同时保存"若用单条命令需 `+fetch` 支持 `--output`，而官方 fetch 参考与 README 未记载该 flag；按任务"不要编造命令或 flag"的口径（以任务为准），拆为 1.1 拉取落盘 + 1.2 jq 提取两步完成同一目标，并在 1.1 备注中给出 `--help` 核实后的一步式替代。

## 8. 本清单核实来源（本次会话实际抓取）

| 内容 | 来源 |
|---|---|
| `+fetch` flags（`--doc/--doc-format/--scope/--detail/…`；无 `--output`；content 结构） | `https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-doc/references/lark-doc-fetch.md` |
| `+update` 的 `--command append`（"仅在文末追加，等价于 block_insert_after --block-id -1"）及 flags | `…/references/lark-doc-update.md` |
| `+script parse` 字数统计（`word_count/char_count/block_count`；`--content` 不支持 Markdown；scope 要求） | `…/references/lark-doc-script.md` |
| XML 语法：`<h1>–<h9>` 不跳级、`<ul><li>`、`<b>`、callout `<callout emoji background-color border-color>` 及颜色取值（背景 `gray/light-*/medium-*`，边框基础色相 `red/…`） | `…/references/lark-doc-xml.md` |
| 无全局 `--output`；`--format` 体系 | `https://raw.githubusercontent.com/larksuite/cli/main/README.md` |
| 信封契约 `ok==true`、退出码表、确认门禁、相对路径安全规则、`--as user` | 本地 `ASSET-DOC.md`（§5、§7、§8.1、§8.4） |
