# T4 · 飞书机器人向 3 群发送「3.8 灰度计划变更」卡片 — 可按序执行命令清单

> 生成日期：2026-09-30。执行前提：本机已安装并配置 `lark-cli`，且已有一个**已授权**的飞书机器人（任务给定，不再执行 `config init` / `auth login`）。
> 工具依据：`skillfactory/v2/evalbench-v02/lark-cli/ASSET-DOC.md`（2026-09-29 刷新版）+ 本次（2026-09-30）实抓的 5 份官方 raw 文档（清单见文末「来源」）。
> 全部命令与 flag 均有官方出处，未编造；返回值一律用 `<<占位符>>` 并注明来源。
> 命令以 bash 形式书写（与官方文档一致）；Windows cmd/PowerShell 适配见「平台备注」。

---

## 目标

向以下 3 个群各发一条**内容一致**的卡片消息（标题、正文、按钮见下方 payload，三群共用同一份）：

| 群名 | chat_id |
|---|---|
| 3.8 迭代同步群 | `oc_aaa111` |
| 测试环境通知群 | `oc_bbb222` |
| 灰度值班群 | `oc_ccc333` |

---

## 步骤 0 — 发送前确认授权有效

```bash
lark-cli auth status
```

- **理由**：写操作前先确认机器人凭证/授权未失效，避免发到一半失败；这是 ASSET-DOC §2.3 Agent 流程的第 4 步（"验证：`lark-cli auth status`"）。
- **返回（占位符）**：`<<当前登录状态与已授权 scope 列表>>`（来源：ASSET-DOC §3 认证命令表："查看当前登录状态和已授权的 scope"；其具体输出格式 ASSET-DOC 未记载，以实际输出为准）。
- **通过判定**：输出显示已登录、无 `authentication`/`config` 类错误（ASSET-DOC §7.2：这两类错误退出码为 3）。异常则先修复授权，不继续。

## 步骤 1 — 按官方卡片工作流生成 payload（不手写结构）

ASSET-DOC §8.3 明确：**"发送/回复/更新卡片前 MUST 先读 `references/card/lark-im-card-create.md` 并按其工作流生成 payload，不可手写。"** 本次已实抓该文档，按其 6 步工作流的步骤 1–3 执行：

- 工作流步骤 1（意图分析）：场景=群通知/计划变更提醒，无回调交互（仅跳转按钮），宽度模式取 `default`（官方骨架示例值；工作流称通知类也可用 `compact`/400px，二者均合规，本文取有直接文档示例的 `default`）。
- 工作流步骤 2（加载文档）：已读 `card-2.0-schema.md`、`components/markdown.md`、`components/button.md`（2026-09-30 实抓）。
- 工作流步骤 3（构建 JSON）：结果如下，保存为 `card-grayplan38.json`（相对路径，符合 lark-shared 安全规则 5 的相对路径要求）。

`card-grayplan38.json` 全文（**这就是三群共用的卡片正文**）：

```json
{
  "schema": "2.0",
  "config": {
    "update_multi": true,
    "width_mode": "default"
  },
  "header": {
    "title": { "tag": "plain_text", "content": "3.8 灰度计划变更" },
    "template": "blue"
  },
  "body": {
    "direction": "vertical",
    "padding": "12px 12px 20px 12px",
    "elements": [
      {
        "tag": "markdown",
        "content": "原定 10/12 的灰度推迟至 10/14 10:00 开始，放量范围由 5% 调整为 10%，请各值班同学按新窗口盯盘。"
      },
      {
        "tag": "button",
        "text": { "tag": "plain_text", "content": "查看灰度方案" },
        "type": "primary",
        "behaviors": [
          { "type": "open_url", "default_url": "https://xx.feishu.cn/docx/GrayPlanV38" }
        ]
      }
    ]
  }
}
```

**逐字段出处**（全部来自 2026-09-30 实抓的官方文档，无自创字段）：

| 字段 | 出处 |
|---|---|
| `"schema": "2.0"` | card-2.0-schema.md P0 硬规则："Card 2.0 必须包含 `"schema": "2.0"`"，否则按 1.0 渲染 |
| `config.update_multi` / `config.width_mode` / `body.direction:"vertical"` / `body.padding` | card-2.0-schema.md 顶层骨架示例（原文："config 可整体省略"；骨架含 `"width_mode": "default"`、`"direction": "vertical"`、`"padding": "12px 12px 20px 12px"`） |
| `header.title{tag:"plain_text",content}` / `header.template:"blue"` | card-2.0-schema.md header 示例（`"title": { "tag": "plain_text", "content": "卡片标题" }`，`"template": "blue"`） |
| 正文元素 `{tag:"markdown",content:...}` | components/markdown.md 最小示例（`"tag": "markdown"`, `"content"` 为 Markdown 文本）。正文文字与任务给定**逐字一致**，未加粗、未改写 |
| 按钮 `{tag:"button",text:{tag:"plain_text",...},type:"primary",behaviors:[...]}` | components/button.md 最小示例（tag/text/type/behaviors 结构；`type` 枚举含 `primary`；独立按钮必须带 `behaviors`） |
| `{"type":"open_url","default_url":"https://..."}` | components/button.md 跳转行为结构（`{ "type": "open_url", "default_url": "https://x", ... }`）。`pc_url`/`ios_url`/`android_url` 为平台覆盖项，单链接场景省略，全端走 `default_url` |

保存命令（bash；Windows 下用编辑器将上述内容存为当前目录 `card-grayplan38.json`，UTF-8）：

```bash
cat > card-grayplan38.json <<'EOF'
{
  "schema": "2.0",
  "config": {
    "update_multi": true,
    "width_mode": "default"
  },
  "header": {
    "title": { "tag": "plain_text", "content": "3.8 灰度计划变更" },
    "template": "blue"
  },
  "body": {
    "direction": "vertical",
    "padding": "12px 12px 20px 12px",
    "elements": [
      {
        "tag": "markdown",
        "content": "原定 10/12 的灰度推迟至 10/14 10:00 开始，放量范围由 5% 调整为 10%，请各值班同学按新窗口盯盘。"
      },
      {
        "tag": "button",
        "text": { "tag": "plain_text", "content": "查看灰度方案" },
        "type": "primary",
        "behaviors": [
          { "type": "open_url", "default_url": "https://xx.feishu.cn/docx/GrayPlanV38" }
        ]
      }
    ]
  }
}
EOF
```

- **理由**：把 payload 固化为单一份文件，三群发送共用，保证内容绝对一致且避免重复粘贴出错。
- **返回（占位符）**：`<<无 CLI 返回；文件落盘>>`。

## 步骤 2 — 预览（dry-run，不真正发送）

```bash
lark-cli im +messages-send --chat-id oc_aaa111 --msg-type interactive --content "$(cat card-grayplan38.json)" --as bot --dry-run
```

- **理由**：任务要求"发送前先做一次不真正发送的预览"；lark-shared 安全规则 3（"目标命令支持 `--dry-run` 时，先用其预览危险请求"）；`--dry-run` 官方语义 = "Print the request only, do not execute it"（lark-im-messages-send.md）。
- **flag 出处**：`--chat-id`、`--msg-type`、`--content`、`--as`（默认即 `bot`，此处显式写明）、`--dry-run` 全部见 lark-im-messages-send.md 的 flags 表；卡片发送形态 `--msg-type interactive --content '<card_json>'` 见 lark-im-card-create.md 步骤 4 原文命令。卡片无 `--card` flag（文档确认不存在）。
- **返回（占位符）**：`<<打印出的请求预览，不执行、不产生消息>>`（来源：lark-im-messages-send.md --dry-run 描述）。
- **确认点**：预览中 `msg_type=interactive`、目标 `oc_aaa111`、标题/正文/按钮 URL 与上文一致 → 进入步骤 3；任一不符 → 修改 `card-grayplan38.json` 后重跑本步。
- **身份依据**：任务指定"通过已授权的 bot 发送"，故 `--as bot`；该身份要求"the app must already be in the target group"（lark-im-messages-send.md 身份注记）——3 个目标群均已含此机器人（任务前提）。

## 步骤 3 — 发送群 1「3.8 迭代同步群」

```bash
lark-cli im +messages-send --chat-id oc_aaa111 --msg-type interactive --content "$(cat card-grayplan38.json)" --as bot --idempotency-key grayplan38-a111
```

- **理由**：执行真正的发送；`--idempotency-key`（≤50 字符，"the same key sends only one message within 1 hour"，lark-im-messages-send.md）保证网络重试时同群不重复发送（ASSET-DOC §7.4：network 类错误可安全重试）。
- **返回（占位符，成功）**：

```json
{ "ok": true, "identity": "bot", "data": { "message_id": "om_xxx", "chat_id": "oc_aaa111", "create_time": "<<秒级时间戳>>" } }
```

（来源：`message_id`/`chat_id`/`create_time` 字段见 lark-im-messages-send.md 返回值示例；`ok/identity` 成功信封见 ASSET-DOC §5.2。）
- **成功判定**：退出码 0 且 `ok == true`；**不得**用 `code == 0` 判断（ASSET-DOC §5.2 原文规则）。记录 `om_xxx` 备汇报。

## 步骤 4 — 发送群 2「测试环境通知群」

```bash
lark-cli im +messages-send --chat-id oc_bbb222 --msg-type interactive --content "$(cat card-grayplan38.json)" --as bot --idempotency-key grayplan38-b222
```

- **理由**：同一 payload 发第二群，仅替换 chat_id 与各自的幂等键（不同群不同 key，互不干扰）。
- **返回（占位符，成功）**：同步骤 3 形态，`"chat_id": "oc_bbb222"`，`"message_id": "om_xxx"`。

## 步骤 5 — 发送群 3「灰度值班群」

```bash
lark-cli im +messages-send --chat-id oc_ccc333 --msg-type interactive --content "$(cat card-grayplan38.json)" --as bot --idempotency-key grayplan38-c333
```

- **理由**：同一 payload 发第三群；至此三群内容一致（共用同一文件）。
- **返回（占位符，成功）**：同步骤 3 形态，`"chat_id": "oc_ccc333"`，`"message_id": "om_xxx"`。

## 步骤 6 — 直接汇报，不做多余查询

按任务要求，三条全部发出后**立即汇报结果、不再做任何查询**（不读消息、不查群）。汇报内容 = 三条发送返回的 `message_id` 占位：群1 `om_xxx`、群2 `om_xxx`、群3 `om_xxx`。这与 ASSET-DOC §8.3 lark-im 的规则一致（写操作后直接反馈，不要二次查询确认）。任一群失败则如实汇报该群失败及错误 `type/subtype`（取自错误信封 stderr，ASSET-DOC §5.2/§7.1），不掩盖。

---

## 异常处理（仅在触发时执行）

1. **退出码 10 / `type=confirmation`**（高风险确认门禁，ASSET-DOC §7.3）：不是错误。停下向用户展示 `action`/`risk` 及关键参数，取得确认后，把错误 `hint` 指出的确认 flag（占位：`<<hint 指出的确认 flag>>`）追加到**原 argv 末尾**重试；绝不预先猜测该 flag，也绝不静默绕过。
2. **发送失败**：按卡片工作流（lark-im-card-create.md 步骤 4）最多重试 3 次；`network` 类可安全重试（ASSET-DOC §7.4），重试沿用**同一** `--idempotency-key` 防重复；3 次仍失败则停止并向用户上报错误信封（stdout/stderr JSON 的 `type`/`subtype`/`code`/`log_id`）。
3. **`api` 类错误且疑似 bot 不在群**：lark-im-messages-send.md 注明 `--as bot` 要求应用已在目标群。此时如实上报，不自行改用 user 身份（任务指定 bot），不自行拉群。
4. **防御性解析**：脚本化消费输出前先 `jq -e .` 校验为 JSON（ASSET-DOC §7.4）。

## 平台备注（Windows）

- 以上为 bash 形式（与官方文档一致，`"$(cat card-grayplan38.json)"` 由 shell 把文件内容作为一个参数传入，不涉及 CLI 的文件路径 flag）。在 PowerShell 中执行时 `--content` 参数改写为 `--content (Get-Content card-grayplan38.json -Raw)`；cmd.exe 无等价简洁写法，建议在 Git Bash 或 PowerShell 执行。
- `card-grayplan38.json` 需保存为 UTF-8；文件路径使用相对路径（lark-shared 安全规则 5）。

---

## 来源清单

本次实际读取（本会话内完成）：

1. `skillfactory/v2/evalbench-v02/lark-cli/ASSET-DOC.md`（本地资产说明，2026-09-29 版）——安装、认证、`--format`/成功信封/`ok==true` 判定、dry-run、错误契约 §7、lark-im/lark-shared 规则 §8。
2. https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-im/references/card/lark-im-card-create.md （2026-09-30，WebFetch）——卡片 6 步工作流；发送命令原文 `lark-cli im +messages-send --chat-id oc_xxx --msg-type interactive --content '<card_json>'`；失败重试上限 3 次。
3. https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-im/references/card/card-2.0-schema.md （2026-09-30，WebFetch）——`schema:"2.0"` P0 规则、顶层骨架、header 示例、card_link。
4. https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-im/references/card/components/markdown.md （2026-09-30，WebFetch）——markdown 元素最小 JSON 与字段。
5. https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-im/references/card/components/button.md （2026-09-30，WebFetch）——button 最小 JSON、`type` 枚举、`open_url` 行为结构。
6. https://raw.githubusercontent.com/larksuite/cli/main/skills/lark-im/references/lark-im-messages-send.md （2026-09-30，WebFetch）——`+messages-send` 全部 flags（含 `--as`、`--dry-run`、`--idempotency-key`）、bot 身份要求、返回值 `message_id/chat_id/create_time`。

本次**未执行**任何真实 CLI 命令（本任务产出的是命令清单，且无真实机器人环境；步骤 0–5 的返回值均为占位符并已注明来源）。ASSET-DOC 引用的 `errs/ERROR_CONTRACT.md` 原文本次未重新抓取，沿用 ASSET-DOC §7 的同日已验证摘录。

## 与 ASSET-DOC 的冲突说明（按要求注明）

- ASSET-DOC §9 官方安全建议为"将该工具集成的机器人作为私人对话助手，勿拉入群聊或让他人与其交互"；本任务要求经已授权 bot 向 3 个群发送通知卡片，两者冲突，**以任务为准**（本清单按任务执行群发，且该 bot 已被授权用于此用途）。
- 其余无实质冲突：lark-shared"写入前确认用户意图"已由任务指令（明确收件群、内容、按钮、URL）满足；lark-im"写操作后直接反馈、不二次查询"与任务"发送完成后不做多余查询"一致。
