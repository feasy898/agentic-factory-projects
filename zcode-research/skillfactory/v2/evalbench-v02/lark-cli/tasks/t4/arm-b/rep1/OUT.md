# T4 ·「3.8 灰度计划变更」卡片 → 3 群发送 · 可按序执行命令清单（交付物）

> 工具：飞书官方 CLI `lark-cli`（npm `@larksuite/cli`，本清单全部命令/flag 已在 **v1.0.97** 实机 `--help` 输出上逐一核验，非凭空编写）。
> 方法：严格按 `lark-cli skills read lark-im/references/card/lark-im-card-create.md` 官方卡片工作流生成 payload（Step 1–3 完成，含 P0–P7 自检），发送前 `--dry-run` 预览，确认后逐群发送。
> 占位符约定：所有 `<...>` 为执行时才产生的返回值，来源在「占位符一览」中注明；清单编写者未编造任何返回值。

---

## 0. 前提与约定（执行前必读）

1. 执行机已安装 `lark-cli`（未装则先执行第 1 步的 cmd-0/1）；任务前提为**已授权的飞书机器人**，故 OAuth 流程不在清单内，仅做状态校验。
2. **bot 必须在三个目标群内**：身份决定可操作性，同一 API 换身份可能"返回空成功而非报错"（ASSET-DOC §8.1 准则 2、§8.3）。
3. 所有命令在 lark-cli 工作目录（cwd）下执行；`--content @./card.json` 只接受 **cwd 相对路径**，绝对路径与 `..` 会被拒绝（lark-shared 安全规则，`--help` 中 `--file`/`--audio` 等同款限制已实机确认）。
4. 成功判定：**退出码 0 且 stdout JSON `ok == true`**；禁止用 `code == 0` 判断（官方输出契约，ASSET-DOC §5.2/§8.1 准则 4）。
5. `+messages-send` 实机 `--help` 标注 `Risk: write`，**非** high-risk-write，正常情况不触发退出码 10 确认门禁；若仍出现 `type=confirmation, exit 10`，停下向用户确认后再把 `hint` 指出的 `--yes` 追加到原命令末尾重试，绝不静默加 flag（ASSET-DOC §7.3）。
6. 命令为 bash 语法（Git Bash / WSL1 均可）；cmd.exe 下需自行调整重定向与引号。`card.json` 必须以 **UTF-8** 编码保存（含中文）。

### 占位符一览（返回值 → 来源）

| 占位符 | 来源 |
|---|---|
| `<AUTH_STATUS>` | cmd-2 stdout：当前登录身份与已授权 scope（官方 `auth status` 输出，ASSET-DOC §3） |
| `<PREVIEW_REQUEST>` | cmd-3 stdout：`--dry-run` 打印的请求体（`--help` 原文 "print request without executing"；不产生发送） |
| `<message_id_aaa111>` / `<message_id_bbb222>` / `<message_id_ccc333>` | cmd-4/5/6 各自 stdout 成功信封 `{"ok":true,...,"data":{...}}` 中的消息 ID（`om_` 前缀；信封结构见 ASSET-DOC §5.2，消息 ID 形态见 §8.3 "Message（om_xxx）"。发送端点不在 `lark-cli schema` 覆盖内，**字段路径以实际响应为准**——本机无飞书凭证，未能实测真实响应，特此注明） |

---

## 1. 前置：安装（已装可跳过）与登录状态校验

```bash
# cmd-0（仅当执行机未安装 CLI）
npx @larksuite/cli@latest install        # 理由：官方推荐安装方式（ASSET-DOC §2.1）；本机实测该内置安装器会失败，改用下一条
npm install -g @larksuite/cli            # 理由：内置安装器失败时的官方回退提示原文 "Failed to install globally. Run manually: npm install -g @larksuite/cli"（本机实测成功，装得 1.0.97）

# cmd-1（仅当需要 Agent Skills 文档时）
npx skills add larksuite/cli -y -g       # 理由：ASSET-DOC §2.1 标注"安装 CLI SKILL（必需）"，供工作流文档本地检索

# cmd-2（必做）
lark-cli auth status                     # 理由：发送前确认 bot 已登录、scope 齐备 → 得 <AUTH_STATUS>；若报 authorization/missing_scopes，按 ASSET-DOC §7.4 用 auth login 补授权后再继续
```

---

## 2. 生成卡片 payload（官方卡片工作流产物，非手写）

```bash
# cmd-3：在工作目录落盘卡片 JSON（UTF-8），供预览与发送共用
cat > ./card.json <<'JSON'
{
  "schema": "2.0",
  "config": { "width_mode": "compact" },
  "header": {
    "title": { "tag": "plain_text", "content": "3.8 灰度计划变更" },
    "template": "blue"
  },
  "body": {
    "direction": "vertical",
    "padding": "12px 12px 20px 12px",
    "elements": [
      {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "blue-50",
        "margin": "0px 0px 12px 0px",
        "columns": [
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "padding": "12px",
            "vertical_spacing": "4px",
            "elements": [
              { "tag": "markdown", "content": "<font color='grey'>原计划</font>\n10/12 开始 · 放量 5%" }
            ]
          },
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "padding": "12px",
            "vertical_spacing": "4px",
            "elements": [
              { "tag": "markdown", "content": "<font color='grey'>调整后</font>\n**10/14 10:00 开始 · 放量 10%**" }
            ]
          }
        ]
      },
      {
        "tag": "markdown",
        "content": "请各值班同学按新窗口盯盘。",
        "margin": "0px 0px 12px 0px"
      },
      {
        "tag": "button",
        "text": { "tag": "plain_text", "content": "查看灰度方案" },
        "type": "primary_filled",
        "width": "fill",
        "behaviors": [
          {
            "type": "open_url",
            "default_url": "https://xx.feishu.cn/docx/GrayPlanV38",
            "pc_url": "",
            "ios_url": "",
            "android_url": ""
          }
        ]
      }
    ]
  }
}
JSON

# cmd-3b：防御性校验 JSON 可解析（官方建议"先用 jq -e . 校验输出是 JSON 再解析"，ASSET-DOC §7.4；本机已用 node 等价实测通过）
jq -e . ./card.json                      # 理由：落盘内容必须先验证为合法 JSON，再进入发送流程
```

**工作流留痕**（按官方卡片工作流逐步执行，依据 `lark-cli skills read` 本地文档，与 GitHub raw 2026-09-29 抓取一致）：

- **版本**：Card 2.0（工作流默认推荐；必须有 `"schema": "2.0"` 否则不渲染）。
- **意图匹配**：样式指南「意图 → 组件组合 · 通知类 / 纯文字通知 / 系统公告」行 → `column_set`（通知正文，`blue-50` 背景）+ `button(open_url)`，`header.template: blue`。
- **宽度**：`compact`（工作流 Step 1：compact 适合通知/轻提醒、内容精简单焦点）。
- **组件依据**：`button.md` 强制规则"全卡仅 1 个按钮 → `type: primary_filled` 且 `width: fill`"；跳转用 2.0 写法 `behaviors:[{type:"open_url", default_url:...}]`（1.0 式顶层 `url` 已废弃）；`column_set` 背景块承载通知正文；`markdown.md` 字段表（`content` 内换行用 `\n`、HTML 属性用单引号）。
- **header 未配 icon**：样式指南要求 icon token 必须取自 `resource/icons.md` 枚举、禁止自行拼接；已 grep 该枚举无匹配灰度/发布语义的 token，按规则"没有合适的 token 时省略 icon"。
- **P0–P7 自检（阻断项全过）**：
  - P0 ✓：信息点①原定 10/12→原计划列；②新时间 10/14 10:00→调整后列；③放量 5%→10%→两列对照；④"请各值班同学按新窗口盯盘。"→独立 markdown（原文保留）；⑤按钮跳转→button `open_url`。无缺、无多余填充。
  - P1 ✓：唯一最强焦点 = 调整后列加粗 `**10/14 10:00 开始 · 放量 10%**`；原计划行常规字重为次；`grey` 标签为辅。
  - P2 ✓：时间/放量同主题收进同一 `column_set` 背景块；盯盘提醒独立成块；无 hr 平铺。
  - P3 ✓：视觉块 3 个（背景块/提醒行/按钮）∈ [2,5]；主色系仅 blue（blue-50 + primary_filled）≤3；含非纯文本结构元素（blue-50 背景块）——纯文字流水账反例不成立。
  - P4 ✓：焦点加粗 vs 正文常规差档；正文无 `#/##`。P5 ✓：margin 仅一种取值 `0px 0px 12px 0px`（非末位容器统一），间距值种类 ≤4，body 用推荐 padding。P6 ✓：header blue → 块用邻近 blue-50，grey 表次要。P7 ✓：列 `weighted`，无 stretch 风险。

---

## 3. 预览（不真正发送）

```bash
# cmd-4：dry-run 预览请求体，确认收件人/内容/身份三要素后再发送（--help 原文 Prerequisites："Confirm the recipient, content, and sending identity before sending"）
lark-cli im +messages-send --as bot --chat-id oc_aaa111 --msg-type interactive --content @./card.json --dry-run
# → <PREVIEW_REQUEST>；三群内容一致，预览一次即可（chat-id 取第一目标群）
# 通过标准：打印出的请求体 msg_type=interactive、content 与 ./card.json 一致、receive_id=oc_aaa111，退出码 0
```

> 本清单编写时已在无凭证环境实测该命令：**flag 解析全部通过**，仅止步于 `{"type":"config","subtype":"not_configured"}`（退出码 3，与官方错误契约 config→3 一致），证明命令形态正确；有凭证的执行机上此步将输出真实预览体。

---

## 4. 逐群发送（内容一致，逐群执行）

```bash
# cmd-5：发送群 1「3.8 迭代同步群」→ stdout 重定向留档，得 <message_id_aaa111>
lark-cli im +messages-send --as bot --chat-id oc_aaa111 --msg-type interactive --content @./card.json --idempotency-key grayplan-v38-oc_aaa111 > ./send-oc_aaa111.json
# 理由：bot 身份发群卡片（工作流 Step 4 群聊命令 + --help 实证 --as bot/--msg-type interactive/--content @file 均合法）；幂等键防重试重发（--help："prevents duplicate sends"，≤50 字符）

# cmd-6：发送群 2「测试环境通知群」→ 得 <message_id_bbb222>
lark-cli im +messages-send --as bot --chat-id oc_bbb222 --msg-type interactive --content @./card.json --idempotency-key grayplan-v38-oc_bbb222 > ./send-oc_bbb222.json
# 理由：同 cmd-5；三个幂等键各不相同，确保互不吞并

# cmd-7：发送群 3「灰度值班群」→ 得 <message_id_ccc333>
lark-cli im +messages-send --as bot --chat-id oc_ccc333 --msg-type interactive --content @./card.json --idempotency-key grayplan-v38-oc_ccc333 > ./send-oc_ccc333.json
# 理由：同 cmd-5；逐群串行执行，便于失败时定位到具体群
```

---

## 5. 结果核验与汇报（不做多余查询）

```bash
# cmd-8：按官方契约核验三份响应均为成功信封（检查 ok==true，而非 code==0）
jq -e '.ok == true' ./send-oc_aaa111.json ./send-oc_bbb222.json ./send-oc_ccc333.json
# 理由：官方输出契约"判断成功应检查 ok == true（或退出码），不要用 code == 0"（ASSET-DOC §5.2）
```

**汇报口径**（发送完成后直接汇报，不再做任何查询）：向用户报告 3/3 群发送成功及各群消息 ID（`<message_id_aaa111>`、`<message_id_bbb222>`、`<message_id_ccc333>`），并附卡片标题「3.8 灰度计划变更」与按钮跳转链接；若某群失败，只报告该群错误信封的 `type/subtype/hint`。

---

## 6. 异常处理（官方契约，按序分支）

| 情形（退出码 / `error.type`） | 处置（依据 ASSET-DOC §7、card-create.md） |
|---|---|
| exit 10 / `confirmation` | 确认门禁非错误：停下向用户展示 action/risk，取得同意后把 hint 指出的 `--yes` 追加到**原 argv 末尾**重试（`+messages-send` 实测 Risk: write，预期不触发） |
| exit 3 / `authorization` | 读 `missing_scopes`，提示用户 `lark-cli auth login` 补授权后重发 |
| exit 4 / `network` | 可安全重试；幂等键已保证不重发 |
| 卡片被服务端拒（如 `there is an invalid user resource (at/person) in your card`） | 按 card-create.md 常见失败列表对照修复；最多重试 3 次，仍失败则按工作流**降级为 Card 1.0** 重新构造（1.0 无本地参考文档） |

---

## 7. 来源清单

| # | 来源 | 用途 |
|---|---|---|
| 1 | `skillfactory/v2/evalbench-v02/lark-cli/ASSET-DOC.md`（2026-09-29 抓取版） | 安装/认证/输出契约/错误契约/安全规则/卡片必须走官方工作流（§8.3"发送/回复/更新卡片前 MUST 先读 references/card/lark-im-card-create.md"） |
| 2 | 本机实测 `lark-cli im +messages-send --help`（v1.0.97） | 核验 `--as/--chat-id/--content(@file、- stdin)/--msg-type(interactive)/--dry-run/--idempotency-key/--format/--jq` 及 `Risk: write` |
| 3 | 本机实测 `lark-cli skills read lark-im/references/card/{lark-im-card-create,lark-im-card-style,components/button,components/markdown,components/column_set,resource/icons}.md` | 卡片工作流 Step1–4、P0–P7、意图→组件表、button 强制规则、open_url 结构、背景块写法、icon 枚举（无匹配故省略） |
| 4 | WebFetch GitHub raw：`skills/lark-im/references/card/lark-im-card-create.md`、`card-2.0-schema.md`、`components/markdown.md`、`components/button.md` | 与本地 skills 文档交叉核对一致（schema 2.0 顶层结构、发送命令形态） |
| 5 | 本机实测：`npm install -g @larksuite/cli`（装得 1.0.97）、`node -e "JSON.parse(...)"`（card.json 合法）、dry-run（flag 全通过，止于 `config/not_configured`，退出码 3） | 见 §3 附注；本机无飞书应用凭证，**真实发送与真实响应未执行、未观测**，故消息 ID 仅以占位符交付 |

---

## 8. 与 ASSET-DOC 的冲突说明（任务要求注明）

- **未发现影响本任务的实质冲突**：dry-run 预览、`ok==true` 判定、卡片官方工作流、bot 身份等任务要求与 ASSET-DOC 完全一致。
- 两处**以任务为准**的取舍，特此注明：① ASSET-DOC §9 转述官方 README"建议将机器人作为私人对话助手，勿拉入群聊"——本任务明确要求经已授权 bot 向 3 个指定群发送，按任务执行；② 官方安全规则"写入操作前必须确认用户意图"——本任务自带"先预览、确认后发送"流程，已满足，不再额外打断。
- 诚实声明：占位符 `<message_id_*>` 的字段路径未经真机响应实测（本机无凭证、无法完成 `config init` 的人工 OAuth），仅有信封结构与 `om_` ID 形态两项官方依据，执行时以实际响应为准。
