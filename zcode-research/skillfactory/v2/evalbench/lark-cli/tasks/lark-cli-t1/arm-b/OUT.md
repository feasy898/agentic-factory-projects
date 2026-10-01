# 「新建评审文档」lark-cli 命令序列（V2.3 需求评审结论）

> 依据会议原始要点（9/29 评审会：V2.3 需求通过、砍掉皮肤商城；三条待办；风险；参会产品部 12 人）产出。
> 前置条件：终端已安装 `lark-cli` 并完成飞书账号认证（首次使用先 `lark-cli auth login`，若遇身份/scope 报错再处理）；文档操作建议显式带 `--as user`。

## 一、命令清单（方案 A：新建后逐块写入，命令与块类型一一对应）

```bash
# ① 新建一篇飞书文档（仅设文档标题，正文留空）
#    返回 JSON 中记下 data.document.document_id 与 url，后续命令用其替换 <DOC_ID>
lark-cli docs +create --title "V2.3 需求评审结论" --as user

# ② 写入一级标题（heading1 块）
lark-cli docs +update --doc "<DOC_ID>" --command append --as user --content '<h1>V2.3 需求评审结论</h1>'

# ③ 写入结论正文段落（text 正文段落块）
lark-cli docs +update --doc "<DOC_ID>" --command append --as user --content '<p>评审会（9/29）结论：V2.3 需求通过，砍掉皮肤商城。参会：产品部全体 12 人。</p>'

# ④ 待办一：负责人 小张，截止 10/10（todo 待办块）
lark-cli docs +update --doc "<DOC_ID>" --command append --as user --content '<checkbox done="false">小张：10/10 前出接口文档</checkbox>'

# ⑤ 待办二：负责人 小李，截止 10/15（todo 待办块）
lark-cli docs +update --doc "<DOC_ID>" --command append --as user --content '<checkbox done="false">小李：10/15 前完成压测报告</checkbox>'

# ⑥ 待办三：负责人 王五，期限 本周内（todo 待办块）
lark-cli docs +update --doc "<DOC_ID>" --command append --as user --content '<checkbox done="false">王五：本周内确认 CDN 报价</checkbox>'

# ⑦ 风险项写入高亮（callout）块：浅红底、红边框，⚠️ 图标
lark-cli docs +update --doc "<DOC_ID>" --command append --as user --content '<callout emoji="⚠️" background-color="light-red" border-color="red"><p>风险：压测环境资源未批。</p></callout>'

# ⑧ 回查验证（只读）：确认块类型、顺序与内容
lark-cli docs +fetch --doc "<DOC_ID>" --detail with-ids
```

说明：

- `append` 指令固定在文末追加（等价于 `block_insert_after --block-id -1`），按 ②→⑦ 顺序依次执行，即可保证文档内块顺序为：一级标题 → 结论段 → 待办×3 → 风险高亮。
- `--doc` 参数可直接填 ① 返回的 `document_id`，也可直接填文档 URL。
- `<checkbox done="false">` 即待办（todo）块，`done="false"` 表示未完成；负责人与截止日按原文写入待办文本。
- callout（高亮块）子块仅支持 `p`、`ol`、`ul`、`checkbox` 与行内标签，故风险文案包一层 `<p>`；配色遵循高亮块默认 `light-*` 背景 + 基础色相边框。
- 引号约定：`--content` 一律用单引号包裹（字面量，不展开 `$` 等）；每条命令写一行即可，macOS/Linux/Git Bash 与 PowerShell 均可直接执行。
- 若返回 `warnings` 非空，按提示核对是否存在降级写入；必要时用 ⑧ 的 fetch 结果定位后修正。

## 二、备选方案 B：一步创建（整篇 XML 一次写入）

先在当前工作目录准备 `v23-review.xml`（`@file` 只接受当前工作目录下的相对路径）：

```bash
cat > v23-review.xml <<'EOF'
<title>V2.3 需求评审结论</title>
<h1>V2.3 需求评审结论</h1>
<p>评审会（9/29）结论：V2.3 需求通过，砍掉皮肤商城。参会：产品部全体 12 人。</p>
<checkbox done="false">小张：10/10 前出接口文档</checkbox>
<checkbox done="false">小李：10/15 前完成压测报告</checkbox>
<checkbox done="false">王五：本周内确认 CDN 报价</checkbox>
<callout emoji="⚠️" background-color="light-red" border-color="red"><p>风险：压测环境资源未批。</p></callout>
EOF

# 一步创建并写入全部内容
lark-cli docs +create --doc-format xml --content "@./v23-review.xml" --as user
```

## 三、「命令→块类型」对照说明

| 步骤 | 命令 | 动作 | 落入飞书文档的块类型 | 使用的标签/参数 | 对应会议要点 |
|---|---|---|---|---|---|
| ① | `docs +create --title ...` | 新建文档 | 文档标题（title，非正文块） | `--title` | 文档命名 |
| ② | `docs +update --command append` | 文末追加 | heading1（一级标题） | `<h1>` | 标题「V2.3 需求评审结论」 |
| ③ | `docs +update --command append` | 文末追加 | text（正文段落） | `<p>` | 结论：V2.3 通过、砍掉皮肤商城；参会 12 人 |
| ④ | `docs +update --command append` | 文末追加 | todo（待办块）第 1 条 | `<checkbox done="false">` | 小张 · 10/10 前出接口文档 |
| ⑤ | `docs +update --command append` | 文末追加 | todo（待办块）第 2 条 | `<checkbox done="false">` | 小李 · 10/15 前完成压测报告 |
| ⑥ | `docs +update --command append` | 文末追加 | todo（待办块）第 3 条 | `<checkbox done="false">` | 王五 · 本周内确认 CDN 报价 |
| ⑦ | `docs +update --command append` | 文末追加 | callout（高亮块） | `<callout background-color="light-red" border-color="red">` 内嵌 `<p>` | 风险：压测环境资源未批 |
| ⑧ | `docs +fetch --detail with-ids` | 只读回查 | —（不写入任何块） | — | 验收块类型与顺序 |

要点归纳：一次 `+create` 建文档并定标题；heading1 用 `<h1>`、正文段用 `<p>`、待办用 `<checkbox>`（todo 块）、高亮用 `<callout>`；每条待办块文本均含「负责人 + 截止日」，风险单独成 callout 块以示强调。
