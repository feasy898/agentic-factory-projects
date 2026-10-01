# 《移动端 3.8 迭代复盘》复审会决议写入 — lark-cli 命令清单

> 目标文档：https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh （token = `V3mQ8xYzAbCdEfGh`，取自用户给定链接）
> 任务：①读取全文并备份到 `./replay-backup.md` → ②统计正文字数 → ③文末追加「复审会决议（2026-10-09）」（内容逐字来自复审会要点，风险加粗高亮）→ ④回查确认写入完整。
> 命令均为 bash 语法（lark-cli 官方示例即 bash；Windows 用户请在 Git Bash/WSL 下执行，cmd/PowerShell 需自行调整引号与重定向写法）。

## 核实口径（先读这里）

- 本清单所有 flag 均核对自 lark-cli 官方仓库 `larksuite/cli` 的 `skills/lark-doc/` 文档（2026-09-29 实际抓取核实）：
  - `SKILL.md`：场景路由（读取→`+fetch`、编辑→`+update`、解析统计→`+script`）；"文档操作推荐显式指定 `--as user`"；本地文件引用 "CWD 内优先使用 `@./相对路径`"。
  - `references/lark-doc-fetch.md`：`--doc`（必填，支持 /docx/ URL）、`--doc-format`（`xml` 默认 | `markdown` | `im-markdown`）、`--scope`（`keyword` 模式配 `--keyword`，`|` 表示 OR）；**无落盘 `--output` flag，输出恒为 JSON 信封**。
  - `references/lark-doc-update.md`：`--command append` = "仅在文末追加，等价于 `block_insert_after --block-id -1`"；`--content` 传内容；`--doc-format markdown` 可用但官方建议"仅在用户明确要求或必须保真 Markdown 时使用"；参考中未列 `--dry-run`。
  - `references/lark-doc-script.md`：**无独立字数子命令**，统计内置于 `parse`：`docs +script --command parse --doc "<URL>"`，结果在 `data.profile` 的 `word_count` / `char_count` / `block_count`；需 `docx:document:readonly` 权限。
- 执行环境与本清单撰写环境不同，**执行前先跑第 0 步 `--help` 再核一遍本机版本的 flag**（版本差异可能导致 flag 增删）。
- 成功判定一律看 `ok == true` 或退出码 0，**不要用 `code == 0` 判断**（成功信封没有顶层 `code` 字段）。
- 占位符说明：本流程**不需要人工回填任何服务端返回 id**（`append` 命令自带"文末"语义，无需 block-id）；唯一需要按实际返回确认的是第 1 步 JSON 里的 content 字段路径。`$DOC_URL` 来自用户给定链接（见上）。

---

## 第 0 步：预检（核实本机版本用法 + 登录态）

```bash
export DOC_URL="https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh"
lark-cli auth status
lark-cli docs --help
lark-cli docs +fetch --help
lark-cli docs +update --help
lark-cli docs +script --help
```

- **理由**：`auth status` 确认登录态与 scope（`+script parse` 明确要求 `docx:document:readonly`）；四条 `--help` 按官方 skill 通用准则"先确认用法、不要盲猜 flag"，核实下文各 flag 在本机版本中存在且拼写一致。

## 第 1 步：读取全文并备份为 ./replay-backup.md

```bash
# 1a. 全文读取（markdown 格式），完整 JSON 信封重定向落盘
lark-cli docs +fetch --doc "$DOC_URL" --doc-format markdown --as user > ./replay-fetch-raw.json

# 1b. 从信封提取 markdown 正文，得到备份文件
jq -r '.data.document.content' ./replay-fetch-raw.json > ./replay-backup.md
```

- **1a 理由**：`+fetch` 不带 `--scope` 即读全文；`--doc-format markdown` 让信封内 content 为 Markdown（与备份文件 `.md` 对应）；`--as user` 按 skill 建议"文档操作推荐显式指定 `--as user`"。官方 `+fetch` **没有保存文件的 flag**，故按信封契约把完整 JSON 重定向到 `./replay-fetch-raw.json`——同时保留 `reference_map`（若文档含图片等引用资源，完整信封是唯一不丢信息的底稿）。
- **1b 理由**：`+fetch` 输出恒为 JSON 信封（`ok`/`identity`/`data.document.*`），需提取 content 字段才是纯 Markdown。**字段路径以 1a 实际返回为准**：若 `.data.document.content` 取不到，先跑 `jq '.data | keys'`（或逐层 `keys`）核对字段名再提取。无 jq 时用任意 JSON 解析工具等价提取。
- **核对**：`head ./replay-backup.md` 确认是 Markdown 正文而非 JSON/空文件；成功判定看 1a 的 `ok==true`/退出码 0。

## 第 2 步：统计正文字数

```bash
lark-cli docs +script --command parse --doc "$DOC_URL" --format json | jq '.data.profile | {word_count, char_count, block_count}'
```

- **理由**：官方 `+script` 参考核实：统计内置于 `parse`、按 `--doc` 传 URL/token 即可（无需本地文件），结果在 `data.profile.word_count`（正文字数）与 `char_count`/`block_count`，故一并读出供参考。管道仅为了直出三个数字；**无 jq 时去掉管道**，直接在返回 JSON 的 `data.profile` 里读 `word_count`。注意：顶层 `ok:true` 只代表命令执行成功，与画像检查无关。

## 第 3 步：文末追加「复审会决议（2026-10-09）」

```bash
# 3a. 把决议内容（逐字原文，见附录 A）落成单一份本地底稿
cat > ./review-section.md <<'EOF'
## 复审会决议（2026-10-09）

结论：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。

待办一：小何，10/14 前更新埋点文档。

待办二：小郑，10/16 前给出崩溃率专项报告。

风险：**Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。**
EOF

# 3b. 文末追加
lark-cli docs +update --doc "$DOC_URL" --command append --doc-format markdown --as user --content "$(cat ./review-section.md)"
```

- **3a 理由**：内容单一来源、便于逐字审计与第 4 步 diff；四个条目（结论 1 + 待办 2 + 风险 1）逐字取自复审会原始记录，无增删；仅对风险句加 `**…**` 加粗以满足"醒目高亮呈现"（加粗是呈现格式，不改动文字内容；如需更强的红色/底色高亮，需改用 XML 格式的块属性，先经 `docs +update --help`/schema 核实后再用）。
- **3b 理由**：`--command append` 即官方定义的"仅在文末追加"，正合"追加到文档末尾"；`--doc-format markdown` 因任务明确要求格式化呈现（标题层级 + 风险加粗），符合"必须保真 Markdown 时使用"的口径；`--as user` 同前。内容经 `"$(cat …)"` 以 shell 展开内联传入（官方示例即 `--content` 内联；`--content` 是否支持 `@./review-section.md` 文件引用未经参考文件证实，若 `--help` 明示支持可改用）。
- **注意**：
  - 官方 update 参考未列 `--dry-run`，勿假设可预览；如需预览先 `docs +update --help` 确认。
  - 若退出码为 **10**（高风险确认门禁，`type=confirmation`）：这是门禁不是故障——停下向用户展示 `action`/`risk`，取得明确同意后，把错误 `hint` 指出的确认 flag **追加到原命令末尾**重试；绝不静默加 flag 绕过。
  - 写入前用户意图已由本任务明确（追加指定内容、不得增删），符合"写入操作前必须确认用户意图"的安全规则。

## 第 4 步：回查确认写入完整

```bash
# 4a. 全文回读（与第 1 步完全相同的读取参数，保证可比）
lark-cli docs +fetch --doc "$DOC_URL" --doc-format markdown --as user > ./replay-fetch-after.json
jq -r '.data.document.content' ./replay-fetch-after.json > ./replay-after.md   # 字段路径沿用第 1 步核实结果

# 4b. 与备份比对：差异应当只有文末新增的一节，且与 ./review-section.md 逐字一致
diff ./replay-backup.md ./replay-after.md

# 4c.（快速抽查，可选）按新章节独有关键词定位
lark-cli docs +fetch --doc "$DOC_URL" --doc-format markdown --scope keyword --keyword "复审会决议|10/14|10/16|0.5%" --as user
```

- **4a 理由**：回查必须用与第 1 步相同的读取参数，diff 才有可比性；字段路径直接沿用第 1 步已核实的结果。
- **4b 理由**：`diff` 是"写入完整"的强校验——期望输出仅为文末新增「复审会决议（2026-10-09）」一节（结论/待办一/待办二/风险四条俱全、风险句带加粗），除此之外无任何其他差异；若出现意外差异立即停手排查。
- **4c 理由**：`--scope keyword` + `--keyword`（`|` 为 OR，官方核实）用仅存在于新章节的关键词做快速命中抽查，作为 4b 的补充；命中说明新章节已被服务端返回。

---

## 附录 A：追加内容原文（即 ./review-section.md，逐字来自 2026-10-09 站会原始记录）

```markdown
## 复审会决议（2026-10-09）

结论：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。

待办一：小何，10/14 前更新埋点文档。

待办二：小郑，10/16 前给出崩溃率专项报告。

风险：**Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。**
```

## 附录 B：与能力资产说明（ASSET-DOC.md）的关系及冲突处理

本清单依据 ASSET-DOC.md 的方法完成任务（lark-doc 场景路由、`--as user`、`ok==true` 判定、相对路径、退出码 10 门禁），并按其指引追查到官方仓库 `skills/lark-doc/` 的 SKILL.md 与三个 references 文件（2026-09-29 实际抓取）核实了具体 flag。与 ASSET-DOC 说明不一致或其未覆盖之处，均**以任务为准**，明细如下：

1. **任务要求"读取全文并同时保存为本地文件"**：ASSET-DOC §8.4 及官方 fetch 参考均无落盘 `--output` flag（输出恒为 JSON 信封）→ 以任务为准，用"重定向完整 JSON + 提取 content"两步实现 `./replay-backup.md`（第 1 步）。
2. **ASSET-DOC §8.4 称 `+script` 支持"字数统计"**：官方 script 参考细化为**无独立字数子命令**，统计内置于 `parse`、读 `data.profile.word_count`（第 2 步按此写）。属细化而非冲突。
3. **任务要求风险"醒目高亮"**：官方 update 参考建议"仅在用户明确要求或必须保真 Markdown 时使用 `--doc-format markdown`"→ 任务明确要求格式化呈现，以任务为准，追加采用 markdown 格式（第 3 步）。
4. **ASSET-DOC §8.1 "写入/删除操作前必须确认用户意图"**：本任务即用户的明确书面指令（追加指定四条内容、不得增删），意图已确认；执行中若遇退出码 10 门禁仍按 §7.3 停下再次确认，不绕过。
5. **撰写环境无法实测运行**：本机未安装 lark-cli（`where lark-cli` 与 `npm ls -g` 均无），故全清单未经实际执行验证；flag 以 2026-09-29 官方仓库文档核实为准，并按"先 `--help`/schema 核实"口径在第 0 步安排了执行前复核。
