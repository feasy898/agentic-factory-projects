# lark-cli 命令序列 — 新建「V2.3 需求评审结论」飞书文档

> 任务素材（会议原始要点，全文照录）：『评审会 9/29。结论：V2.3 需求通过，砍掉皮肤商城。待办：①小张 10/10 前出接口文档；②小李 10/15 前完成压测报告；③王五确认 CDN 报价（本周内）。风险：压测环境资源未批。参会：产品部全体 12 人。』
>
> 本清单依据：`skillfactory/v2/evalbench/lark-cli/ASSET-DOC.md`（larksuite/cli 资产档）+ 当日（2026-09-29）抓取的仓库 reference 原文（`skills/lark-doc/references/lark-doc-create.md`、`lark-doc-create-workflow.md`、`lark-doc-xml.md`、`lark-doc-md.md`）。按任务要求，本清单**未实际执行**，仅产出可在终端执行的命令。

## 0. 格式选型（为什么用 XML）

待办（todo）与高亮（callout）两类块在纯 Markdown 中无法原生表示：`lark-doc-md.md` 明确将「勾选框」列入 plain Markdown 不支持的块类型，将「高亮框（callout）」列入必须「采用 XML 语法表示」的块类型。因此本清单按官方创建工作流（`lark-doc-create-workflow.md` Step 5–7）采用 `--doc-format xml`：标题用 `<title>`（唯一、必须居文档首），块级标签为 `<h1>`/`<p>`/`<checkbox>`/`<callout>`（`lark-doc-xml.md`）。

## 1. 命令序列

### 步骤 0｜一次性配置与授权（本机已配置可跳过）

```bash
# 配置应用凭证：会输出授权 URL 交用户在浏览器完成，命令随后自动退出（Agent 模式）
lark-cli config init --new

# 登录授权（--recommend 自动选择常用权限；输出的授权 URL 需按 lark-shared 规则用
# `lark-cli auth qrcode` 配二维码展示，URL 原样转发）
lark-cli auth login --recommend

# 验证登录状态
lark-cli auth status
```

### 步骤 1｜撰写内容草稿文件 `./v23-review-draft.xml`

> 注意：lark-cli 文件参数只接受**相对路径**（lark-shared 安全规则），故草稿须放在当前工作目录下。文件内容如下（块级标记与下方对照表一一对应）：

```xml
<title>V2.3 需求评审结论</title>
<h1>V2.3 需求评审结论</h1>
<p>结论：V2.3 需求通过，砍掉皮肤商城。</p>
<p>会议：2026-09-29 评审会；参会：产品部全体 12 人。</p>
<h2>待办</h2>
<checkbox done="false">小张：2026-10-10 前出接口文档。</checkbox>
<checkbox done="false">小李：2026-10-15 前完成压测报告。</checkbox>
<checkbox done="false">王五：确认 CDN 报价（本周内，截止 2026-10-04）。</checkbox>
<h2>风险</h2>
<callout emoji="⚠️" background-color="light-red" border-color="red">
  <p>压测环境资源未批。</p>
</callout>
```

> 截止日说明：①②按要点中的 10/10、10/15 归入 2026 年；③「本周内」按周一为一周第一天推算——2026-09-29 为周二（实测：`python -c "import datetime; print(datetime.date(2026,9,29).strftime('%A'))"` 输出 `Tuesday`），本周为 2026-09-28（一）至 2026-10-04（日），故截止 2026-10-04。

### 步骤 2｜草稿预检（创建工作流 Step 6）

```bash
lark-cli docs +script --command parse --content "@./v23-review-draft.xml" --format json
```

通过判定：`data.assessment.status`；不通过时按 `data.diagnostics[]` 逐条局部修复后重跑本步（仅草稿为空、截断或结构无效时才全文重建）。

### 步骤 3｜预览请求（写入前 dry-run，lark-shared 安全规则：支持 --dry-run 先预览）

```bash
lark-cli docs +create --doc-format xml --content "@./v23-review-draft.xml" --as user --dry-run
```

### 步骤 4｜正式新建文档并写入全部块

```bash
lark-cli docs +create --doc-format xml --content "@./v23-review-draft.xml" --as user
```

- 文档操作显式指定 `--as user`（lark-doc SKILL 建议）。
- 成功判定：检查输出 JSON 的 `ok == true`（或退出码 0），**不要**用 `code == 0` 判断（成功信封无顶层 `code` 字段）；从 stdout `data` 中取文档 URL/token 交付。
- 如需回读复核内容，使用 `lark-cli docs +fetch`（用法先跑 `lark-cli docs --help` 确认，本清单未给出未核实的 flags）。

## 2. 「命令 → 块类型」对照说明

> 说明：块级内容由步骤 4 的 `+create` 命令经 `--content` 一次性写入，故对照同时给出「命令」与「该命令所承载的内容元素 → 块类型」两个粒度。

| # | 命令 / 内容元素 | 块类型 | 说明 |
|---|---|---|---|
| 1 | `lark-cli docs +create --doc-format xml --content "@./v23-review-draft.xml" --as user`（整条命令） | 新建文档（文档容器） | 返回文档 URL/token，不单独对应正文块 |
| 2 | `<title>V2.3 需求评审结论</title>` | 文档标题（title） | 唯一，必须为文档首元素 |
| 3 | `<h1>V2.3 需求评审结论</h1>` | **一级标题块**（heading1） | 任务要求①：写入一级标题 |
| 4 | `<p>结论：V2.3 需求通过，砍掉皮肤商城。</p>` 及 `<p>会议：…参会：产品部全体 12 人。</p>` | **正文段落块**（text/paragraph） | 任务要求①：写入结论正文段落 |
| 5 | `<h2>待办</h2>`、`<h2>风险</h2>` | 二级标题块（heading2） | 分区用，便于阅读 |
| 6 | `<checkbox done="false">小张：2026-10-10 前出接口文档。</checkbox>` | **待办块**（todo/checkbox） | 任务要求②；含负责人「小张」+截止日 2026-10-10 |
| 7 | `<checkbox done="false">小李：2026-10-15 前完成压测报告。</checkbox>` | **待办块**（todo/checkbox） | 任务要求②；含负责人「小李」+截止日 2026-10-15 |
| 8 | `<checkbox done="false">王五：确认 CDN 报价（本周内，截止 2026-10-04）。</checkbox>` | **待办块**（todo/checkbox） | 任务要求②；含负责人「王五」+截止日 2026-10-04（「本周内」推算值） |
| 9 | `<callout emoji="⚠️" background-color="light-red" border-color="red"><p>压测环境资源未批。</p></callout>` | **高亮块**（callout） | 任务要求③：风险项；子块仅支持 `p`/`ol`/`ul`/`checkbox` 与行内标签，正文须包在 `<p>` 内 |
| 10 | `lark-cli docs +script --command parse --content "@./v23-review-draft.xml" --format json` | （不产生块）草稿结构预检 | 步骤 2；按 `data.assessment.status` 判定 |
| 11 | 同步骤 4 命令 + `--dry-run` | （不产生块）预览请求 | 步骤 3；写入前安全预览 |

## 3. 附注（与 ASSET-DOC 的差异及未尽事项）

1. **与 ASSET-DOC 示例的差异**：`ASSET-DOC.md:99` 的 README 示例为 markdown 格式且把 `<title>` 标签写进 markdown 内容；而仓库 reference `lark-doc-create.md` 规定 markdown 导入应改用 `--title` flag、`<title>` 标签用于 XML 且唯一居首。本清单按任务对 todo/callout 块的硬要求选用 XML 路线，并遵循 reference 规则——此处属资产档（转述 README）与仓库 reference 的口径差，以仓库 reference 为准。
2. **callout 颜色枚举**：`lark-doc-xml.md` 对 `background-color`/`border-color` 仅以通配形式给出（`light-*` / `*`），未列全枚举值。本清单取 `light-red`/`red` 作风险高亮示例；执行前可先 `lark-cli docs +create --help` 核对可用取值。`emoji` 为自由取值（reference 示例为 `💡`，此处按风险语义用 `⚠️`）。
3. **省略 init-draft 步骤的理由**：官方创建工作流 Step 4（`docs +script --command init-draft`）需先读 `references/genres/` 体裁档案确定 `genre_contract`；本任务为会议纪要的机械转写（素材全文照录、内容完全给定），按 `lark-doc-create.md`「仅创建空文档或原样导入用户提供的完整内容时，跳过创建工作流」处理，保留 Step 6 parse 预检与 Step 7 create。
4. **本清单未实际执行**（任务明示不要求执行）；所有命令语法均出自 ASSET-DOC.md 及 2026-09-29 抓取的仓库 SKILL/reference 原文，未使用未核实 flags。唯一实测运行的检查为步骤 1 中「本周内」的星期推算（`python -c "import datetime; ..."` → `Tuesday`，本周 2026-09-28 至 2026-10-04）。
