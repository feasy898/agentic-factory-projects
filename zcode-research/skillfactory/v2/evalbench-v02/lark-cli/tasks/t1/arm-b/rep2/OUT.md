# 《移动端 3.8 迭代复盘》复审会决议写入 — lark-cli 可执行命令清单

- 目标文档：`{{DOC_URL}}` = `https://xx.feishu.cn/docx/V3mQ8xYzAbCdEfGh`（题给，token `V3mQ8xYzAbCdEfGh`）
- 目标：① 全文读取并备份到 `./replay-backup.md`；② 统计正文字数；③ 文末追加「复审会决议（2026-10-09）」一节（内容仅来自 2026-10-09 复审会原始记录，风险醒目高亮）；④ 回查确认写入完整。
- 本清单所有步骤都直接复用 `{{DOC_URL}}`：`docs +fetch` / `docs +update` 的 `--doc` 接受「文档 URL 或 token」（`shortcuts/doc/docs_fetch.go:27`），URL 会被自动解析出 token，**无需任何"取 id"中间步骤**，因此本清单没有依赖"上一步返回值"的占位符；`{{本地文件}}` 均为本次清单自行产生的文件。

## 命令清单（按序执行）

### Step 0｜权限预检（两行，一次性）

```bash
lark-cli auth status
lark-cli auth check --scope "docx:document:readonly docx:document:write_only"
```

**理由**：本次要读要写 docx，`+fetch` 声明 scope `docx:document:readonly`（`docs_fetch.go:26`），`+update` 声明 `docx:document:write_only` + `docx:document:readonly`（`docs_update.go:41-42`）；`auth check` 即"检查当前 token 是否具备指定 scopes"，`--scope` 为空格分隔多个 scope，退出码 0=有权限、1=缺失（`cmd/auth/check.go:33-35`，README「auth」表），先确认再动手可避免中途 403。

### Step 1｜全文读取并落盘备份

```bash
lark-cli docs +fetch --doc "{{DOC_URL}}" --doc-format markdown > ./replay-backup.md
```

**理由**：`docs +fetch` 即"读取飞书文档内容"，`--doc` 必填，`--doc-format markdown` 让返回为纯 Markdown（默认 xml，见 `docs_fetch_v2.go:23-37` 的 flag 枚举 `xml|markdown|im-markdown`）；源码中该命令把 `document.content` 原文直写 stdout（`docs_fetch_v2.go:88-96`），shell 重定向即完成备份。

> 执行注意（拿不准先核实的口径）：先**不带 `>` 跑一次**确认你的版本 stdout 里是纯 Markdown 还是 JSON envelope；若是 envelope，追加 `--jq ".document.content"`（全局 flag，`cmd/root_help.go:47`）提取后再重定向。

### Step 2｜统计正文字数（本地统计）

```powershell
$raw = Get-Content -Raw ./replay-backup.md
($raw -replace '\s','').Length
```

**理由**：lark-cli 无字数/统计类命令（已在其官方仓库全量检索 `statistic`/`word_count`，仅内部质量门禁代码命中，无对用户命令），故对 Step 1 备份的**追加前正文**本地统计；口径 = 去除全部空白后的字符数（中文常规"字数"口径，含文档标题行；如团队要求排除标题行，统计前先去掉首个 `# ` 行）。Git Bash 下等价写法：`tr -d '[:space:]' < ./replay-backup.md | wc -m`。

### Step 3｜把追加内容写成 UTF-8 文件 `./replay-append.md`

新建 `./replay-append.md`，内容**逐字**如下（四条要点一律不增删；风险行用加粗+🚨 做醒目呈现）：

```markdown
## 复审会决议（2026-10-09）

**结论**：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。

**待办一**：小何，10/14 前更新埋点文档。

**待办二**：小郑，10/16 前给出崩溃率专项报告。

**🚨 风险**：Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。
```

**理由**：`--content` 支持 `@文件` 读入（`shortcuts/doc/docs_update_v2.go:37`，`Input: File|Stdin`；`@路径` 解析见 `shortcuts/common/runner.go:1332-1355`，`@@` 才表示字面 `@`），走文件可完全避免命令行引号/换行转义问题；文件请存为 UTF-8（CLI 会剥 BOM，仍建议无 BOM）。

### Step 4｜预演写入（可选但建议）

```bash
lark-cli docs +update --doc "{{DOC_URL}}" --command append --doc-format markdown --content @./replay-append.md --dry-run --as user
```

**理由**：`--dry-run` "previews the request (runs nothing)"（`cmd/root_help.go:47`），写操作前先看一眼实际 PUT 请求体，防误写；`--as user` 以用户身份执行（README「Identity」，flag 注册见 `internal/cmdutil/identity_flag.go:64-67`；个人文档用用户身份才有编辑权）。

### Step 5｜正式在文末追加（去掉 `--dry-run`）

```bash
lark-cli docs +update --doc "{{DOC_URL}}" --command append --doc-format markdown --content @./replay-append.md --as user
```

**理由**：`--command append` 即"文末追加"，且校验逻辑明确 append 只需要 `--content`、无需 block-id（`docs_update_v2.go:180-183`），底层调用 `PUT /open-apis/docs_ai/v1/documents/{token}`（`docs_update_v2.go:202-206`）；`--doc-format markdown` 与 Step 3 的 Markdown 内容匹配。

### Step 6｜回查一次，确认写入完整

```bash
lark-cli docs +fetch --doc "{{DOC_URL}}" --doc-format markdown > ./replay-after.md
```

```powershell
Select-String -Path ./replay-after.md -Pattern "复审会决议（2026-10-09）","5% 调整为 10%","10/14 前更新埋点文档","10/16 前给出崩溃率专项报告","OOM 率仍高于 0.5"
Get-Content ./replay-after.md -Tail 8
Compare-Object (Get-Content ./replay-backup.md) (Get-Content ./replay-after.md)
```

**理由**：重新拉全文（同 Step 1）后，① 用五条关键词逐一命中确认"结论/待办一/待办二/风险"逐条在文；② 看文件末尾确认新节在文档末尾；③ 与备份 diff 确认除新增节外原文未被改动。全部命中且 diff 仅新增 Step 3 内容 = 写入完整。

## 「风险」要真高亮块（可选替换方案）

飞书"高亮块"= callout。把 Step 3-5 换成 XML 版（一次命令写整节，风险行落成高亮块）：新建 `./replay-append.xml`：

```xml
<h2>复审会决议（2026-10-09）</h2>
<p><b>结论</b>：3.8 灰度放量节奏由 5% 调整为 10%，其余结论维持不变。</p>
<p><b>待办一</b>：小何，10/14 前更新埋点文档。</p>
<p><b>待办二</b>：小郑，10/16 前给出崩溃率专项报告。</p>
<callout emoji="🚨"><b>风险</b>：Android 低端机 OOM 率仍高于 0.5% 阈值，需持续盯盘。</callout>
```

```bash
lark-cli docs +update --doc "{{DOC_URL}}" --command append --doc-format xml --content @./replay-append.xml --as user
```

**依据与边界**：`h2`/`p`/`callout` 均为 DocxXML 合法标签（`shortcuts/doc/internal/docxparse/block_catalog.go:29-38`），`<callout emoji="...">...</callout>` 写法出自官方测试样例（`docs_fetch_im_markdown_test.go:121`）；callout 的底色等更多样式属性未在源码中核实到，如需精确配色请先 `--dry-run` 预览并对照飞书开放平台 DocxXML 文档确认后再正式执行。只要求"加粗醒目"即可的话，用主方案（Step 3-5）更稳。

## 口径与核实记录

- **命令与 flag 全部对照官方源码核实**：github.com/larksuite/cli（本会话 `git clone --depth 1` 至 `/tmp/lark-cli-ref` 后逐文件读取，行号均指该仓库 main 分支），未臆造任何命令/flag；上文已给"执行注意/依据与边界"之处即剩余拿不准点，执行时按注明的 `--help` / `--dry-run` / `--jq` 先核实。
- **本执行环境未安装 lark-cli**（`PATH`、`where`、`cargo/go/scoop/npm -g/pip/choco/WindowsApps`、`D:\tools` 均无；Go 工具链缺失无法本地构建跑 `--help`），故未能实际执行上述命令验证运行时行为——清单的可执行性以源码级核实为准。
- 文档若实际是 Wiki 节点：`+fetch`/`+update` 同样接受 wiki URL 并自动解析为 docx token（`docs_update_v2.go:196-200`），命令无需改动。
- 本次不涉及本地图片/文件上传，故不触发额外 media scope；字数统计因 CLI 无此能力而本地完成，口径已注明。
