# 3.8 灰度计划变更 · 三群卡片通知 — 可按序执行命令清单

> 执行工具：飞书官方 CLI **`lark-cli`**（开源仓库 [larksuite/cli](https://github.com/larksuite/cli)，npm 包 `@larksuite/cli`）。
> 本清单在 **bash（如 Git Bash）** 中按序执行；所有命令与 flag 均出自官方仓库文档（每条注明出处），无自造参数。
> 前提：任务说明机器人已授权，即 `lark-cli config init` 已完成（appId/appSecret 已配置）；机器人已被加入下方 3 个群（官方要求：`--as bot` 发群消息时应用必须在目标群内）。

## 0. 任务给定信息（占位符来源）

| 项 | 值 | 来源 |
|---|---|---|
| 群 1 | 「3.8 迭代同步群」 `oc_aaa111` | 任务给定 |
| 群 2 | 「测试环境通知群」 `oc_bbb222` | 任务给定 |
| 群 3 | 「灰度值班群」 `oc_ccc333` | 任务给定 |
| 卡片标题 | 3.8 灰度计划变更 | 任务给定 |
| 卡片正文 | 原定 10/12 的灰度推迟至 10/14 10:00 开始，放量范围由 5% 调整为 10%，请各值班同学按新窗口盯盘。 | 任务给定 |
| 按钮文字 / 跳转 | 查看灰度方案 → `https://xx.feishu.cn/docx/GrayPlanV38` | 任务给定 |

三群内容一致性由「三个发送命令共用同一份卡片文件 `gray_plan_card.json`」机械保证。

---

## 1. 命令清单（按序执行）

### 命令 1（可选，仅本机未装 CLI 时）安装官方 CLI

```bash
npx @larksuite/cli@latest install
```

- **理由**：安装飞书官方命令行工具本体（已有环境可跳过）。
- **出处**：README.zh.md「安装与快速开始 → 安装」（`npx @larksuite/cli@latest install`）。

### 命令 2 发送前核验身份与凭证

```bash
lark-cli whoami
lark-cli auth status --json --verify
```

- **理由**：确认当前生效身份与凭证有效；本次以 bot 身份发送（bot 凭证来自 config 的应用凭证，bot scope 在开发者后台开通、不走 `auth login`），故只需确认应用配置就绪、无异常登录态。
- **出处**：lark-shared/references/lark-shared-identity-and-permissions.md「认证任务速查」（`lark-cli whoami`＝当前实际生效身份；`lark-cli auth status --json --verify`＝检查登录态/凭证有效性）；同文档「身份类型」（bot 凭证获取方式＝appId+appSecret，Bot 权限只需后台开通 scope）。
- **返回值占位**：终端打印的身份/状态 JSON `<WHOAMI_STATUS>`（人读核对，不进入后续命令）。

### 命令 3 按官方卡片工作流生成卡片 JSON（工作流 Step 1→3，含 P0–P7 硬 Gate）

官方文档**强制**：任何 `interactive` 卡片在 send/reply/patch 前必须先走 `card/lark-im-card-create.md` 工作流，`--content` 里的 JSON 必须是该工作流的产物，**不得手写或抄示例**（lark-im/SKILL.md「Card Messages (Interactive)」；lark-im-messages-send.md 同节）。以下为按该工作流逐步产出的结果：

**Step 1 设计方案（文字诉求路径）**：本卡为「纯文字通知 / 系统公告」意图 → 采用意图表该行推荐组合：`column_set`（通知正文，`blue-50` 背景块）+ `button(open_url)`，`header.template: blue`。版本 **Card 2.0**（工作流推荐）；宽度 **`compact`**（400px，工作流明确“适合通知/轻提醒（内容精简、单焦点）”）；交互类型：**纯跳转 open_url**（不回调服务端，无需监听 card.action.trigger）。

**Step 3 构造 + 发送前硬 Gate 自检**（P0、P1–P3 为阻断项，全部通过）：

| Gate | 自检结论 |
|---|---|
| P0 符合诉求 | 标题→`header.title`；正文三要点（推迟至 10/14 10:00、放量 5%→10%、按新窗口盯盘）→正文 `markdown`；按钮+跳转→`button` `open_url`。无缺失、无与诉求无关的填充（故未加 subtitle 等额外内容） |
| P1 层级 | header 承载「这是什么」；body 内唯一焦点为加粗蓝色小标题「变更要点」，正文 normal |
| P2 分组 | 同一主题（变更说明）收进同一个 blue-50 背景容器；无「一路 hr 平铺」 |
| P3 复杂度 | 视觉块 2 个（正文块、按钮）∈[2,5]；主色系 1 个（蓝）≤3；含非纯文本结构元素（背景块） |
| P4/P5 | 标题与正文有字号/粗细差；间距交由容器 `padding`/`vertical_spacing`，margin 仅规范值 `0px 0px 12px 0px`，取值种类 ≤4 |
| P6/P7 | 蓝=信息语义一致，body 蓝与 header blue 同色系；列宽用 `weighted` 未用 `stretch`；仅用系统色枚举（`blue-50`），深浅色自动适配 |

落盘（生成工作流产物 `gray_plan_card.json`）：

```bash
cat > gray_plan_card.json <<'JSON'
{
  "schema": "2.0",
  "config": {
    "update_multi": true,
    "width_mode": "compact"
  },
  "header": {
    "title": { "tag": "plain_text", "content": "3.8 灰度计划变更" },
    "template": "blue",
    "icon": { "tag": "standard_icon", "token": "bell_outlined", "color": "blue" }
  },
  "body": {
    "direction": "vertical",
    "padding": "12px 12px 20px 12px",
    "elements": [
      {
        "tag": "column_set",
        "flex_mode": "none",
        "margin": "0px 0px 12px 0px",
        "columns": [
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "background_style": "blue-50",
            "corner_radius": "8px",
            "padding": "12px",
            "vertical_spacing": "4px",
            "elements": [
              { "tag": "markdown", "content": "**<font color='blue'>变更要点</font>**" },
              { "tag": "markdown", "content": "原定 **10/12** 的灰度推迟至 **10/14 10:00** 开始；放量范围由 **5%** 调整为 **10%**。请各值班同学按新窗口盯盘。" }
            ]
          }
        ]
      },
      {
        "tag": "button",
        "text": { "tag": "plain_text", "content": "查看灰度方案" },
        "type": "primary_filled",
        "width": "fill",
        "behaviors": [
          { "type": "open_url", "default_url": "https://xx.feishu.cn/docx/GrayPlanV38" }
        ]
      }
    ]
  }
}
JSON
```

- **理由**：产出官方工作流强制要求的卡片 JSON 文件（后续三群发送共用，保证内容一致）。
- **结构依据**（全部取自官方组件文档，非自造）：根结构 `schema:"2.0"`（缺失则不按 2.0 渲染）、`config.width_mode`、`header.title/tag:plain_text`、`body.direction/padding`＝card-2.0-schema.md「根结构」；`column_set/column` 背景块写法（`background_style:"blue-50"`、`corner_radius:"8px"`、`padding:"12px"`、`vertical_spacing:"4px"`、`flex_mode:"none"`、`width:"weighted"`）＝lark-im-card-style.md「意图→组件组合·纯文字通知」与「高亮块模式」；单按钮强制 `type:"primary_filled"` + `width:"fill"`、跳转行为 `behaviors:[{"type":"open_url","default_url":...}]`＝components/button.md；margin 规范值＝lark-im-card-style.md「间距纪律」；header 图标 `bell_outlined`（通知/铃铛）取自 resource/icons.md 的**精确 token 枚举**（该文档禁止按名称规律自拼 token）。

### 命令 4 发送前预览（不真正发送，仅一次）

```bash
lark-cli im +messages-send --as bot --chat-id oc_aaa111 --msg-type interactive --content "$(cat gray_plan_card.json)" --dry-run
```

- **理由**：`--dry-run` 只打印完整请求（URL / body / params）**不执行**，满足“发送前做一次不真正发送的预览”；三群 payload 完全相同、仅 `--chat-id` 不同，预览一次即可核对内容。
- **出处**：lark-im-messages-send.md 参数表（`--dry-run`＝Print the request only, do not execute it）；lark-shared-high-risk-approval.md（`--dry-run` 不触发确认门禁，会打印完整请求供 review）；`--msg-type interactive --content` 发卡片命令形态＝lark-im-card-create.md Step 4 与 lark-im-messages-send.md「Interactive Card」节；显式 `--as bot`＝lark-shared-identity-and-permissions.md「身份延续」（明确需要某一身份时建议全程显式选择）。
- **确认点**：预览中应见 `msg_type=interactive`、`receive_id_type=chat_id`、`receive_id=oc_aaa111`、`content` 与 `gray_plan_card.json` 一致。确认无误后才进入命令 5–7。
- **返回值占位**：终端打印的请求预览 `<REQUEST_PREVIEW>`（非 API 返回值，人读核对）。

### 命令 5 / 6 / 7 逐群正式发送（每群一条，内容一致）

```bash
# 命令 5：3.8 迭代同步群
lark-cli im +messages-send --as bot --chat-id oc_aaa111 --msg-type interactive --content "$(cat gray_plan_card.json)" --idempotency-key gray38-plan-change-oc_aaa111

# 命令 6：测试环境通知群
lark-cli im +messages-send --as bot --chat-id oc_bbb222 --msg-type interactive --content "$(cat gray_plan_card.json)" --idempotency-key gray38-plan-change-oc_bbb222

# 命令 7：灰度值班群
lark-cli im +messages-send --as bot --chat-id oc_ccc333 --msg-type interactive --content "$(cat gray_plan_card.json)" --idempotency-key gray38-plan-change-oc_ccc333
```

- **理由**：按群逐条发送同一张卡片（官方 API 一次只投递一个会话）；`--idempotency-key`（≤50 字符）用于失败重试时去重，**三个群必须用不同的 key**——同一 key 在 1 小时内只会投递一条消息，复用会导致后续群收不到；发送身份为 bot（消息以应用名义出现在群里）。
- **出处**：命令形态＝lark-im-card-create.md Step 4；`--idempotency-key`（max 50 chars，same key sends only once within 1 hour）＝lark-im-messages-send.md 参数表与示例；`--as bot` 走 tenant_access_token、需要 scope `im:message:send_as_bot`、且应用须已在目标群＝同文档 Notes；bot 凭证自动、无需 `auth login`＝lark-shared-identity-and-permissions.md「身份类型」。
- **返回值占位与来源**（每条命令的 stdout，官方 Return Value 结构）：
  - 命令 5 → `{"message_id":"<om_xxx_1>","chat_id":"oc_aaa111","create_time":"<ts_1>"}`
  - 命令 6 → `{"message_id":"<om_xxx_2>","chat_id":"oc_bbb222","create_time":"<ts_2>"}`
  - 命令 7 → `{"message_id":"<om_xxx_3>","chat_id":"oc_ccc333","create_time":"<ts_3>"}`
  - 来源：lark-im-messages-send.md「Return Value」（`om_xxx`/时间戳以实际 stdout 为准）。
- **成功判定**：退出码 0 且信封 `ok == true`（官方明确**不要**用 `code == 0` 判断成功）——出处：README.zh.md「JSON 输出契约」、lark-shared/SKILL.md 通用准则 4。

### 命令 8 向用户汇报结果（无额外查询）

发送完成后直接汇报，不再回查：

> 「3.8 灰度计划变更」卡片已发往 3 个群：3.8 迭代同步群 `<om_xxx_1>`、测试环境通知群 `<om_xxx_2>`、灰度值班群 `<om_xxx_3>`（`<om_xxx_N>`＝命令 5/6/7 返回的 message_id）。如有失败群，附该群 stderr 的 `error.message` 及下方异常处置结果。

- **理由**：任务要求“发送完成后直接汇报结果，不做多余查询”；message_id 已在发送返回值中，无需再调读接口。

---

## 2. 异常处置速查（均出自官方文档，非自造）

| 现象 | 官方处置 |
|---|---|
| 退出码 **10**，stderr `error.type=="confirmation"`、`error.subtype=="confirmation_required"` | 高风险写操作确认门禁（非错误）：向用户展示 `error.action`、`error.risk` 与关键参数，**取得显式同意后**把 `error.hint` 指出的确认 flag（多数命令为 `--yes`）追加到原 argv 末尾重试；禁止静默加 flag 绕过。出处：lark-shared-high-risk-approval.md |
| 报权限错误，含 `missing_scopes` / `console_url`（bot 身份） | 把 `console_url` 原样给用户，去开发者后台开通 bot scope（本任务即 `im:message:send_as_bot`）；**禁止对 bot 执行 `auth login`**。出处：lark-shared-identity-and-permissions.md「权限不足处理」 |
| 卡片发送失败（如 `there is an invalid user resource ...`） | 对照 card-create.md「常见失败列表」修复后重发，最多 **3 次**；3 次仍失败则按工作流降级为 Card 1.0 重构发送。出处：lark-im-card-create.md Step 4 |

补充说明：官方发送安全约束要求发送前确认收件人/内容/身份——本次任务指令已明确三者（3 个群、既定卡片文案、bot 身份），命令 4 的 dry-run 预览即最终人工核对点。

---

## 3. 占位符对照总表

| 占位符 | 含义 | 来源 |
|---|---|---|
| `oc_aaa111` / `oc_bbb222` / `oc_ccc333` | 三群 chat_id | 任务给定 |
| `https://xx.feishu.cn/docx/GrayPlanV38` | 按钮跳转链接 | 任务给定 |
| `<WHOAMI_STATUS>` | 命令 2 终端输出 | 本机执行结果（人读核对） |
| `<REQUEST_PREVIEW>` | 命令 4 `--dry-run` 打印的请求 | 本机执行结果（人读核对） |
| `<om_xxx_1/2/3>`、`<ts_1/2/3>` | 三群消息的 message_id / create_time | 命令 5/6/7 stdout（官方 Return Value 结构） |
| `<确认 flag>` | exit 10 时的确认 flag | 该次 stderr `error.hint`（多数为 `--yes`） |
| `gray38-plan-change-oc_*` | 幂等键 | 自拟字符串（≤50 字符，仅要求群间互不相同） |

## 4. 出处索引（官方文档，本清单全部命令/flag 的唯一依据）

均为 GitHub `larksuite/cli` 仓库 `main` 分支原始文件（2026-09-30 抓取核对）：

- README.zh.md — 安装、JSON 输出契约（`ok==true`）、Dry Run
- skills/lark-shared/SKILL.md — 通用准则（身份/安全/成功判定）
- skills/lark-shared/references/lark-shared-identity-and-permissions.md — `whoami` / `auth status --json --verify` / bot 身份与权限
- skills/lark-shared/references/lark-shared-high-risk-approval.md — exit 10 确认门禁与 `--dry-run` 预览
- skills/lark-im/SKILL.md — interactive 卡片强制走 card 工作流
- skills/lark-im/references/lark-im-messages-send.md — `+messages-send` 全部参数、interactive 发送形态、Return Value、scope
- skills/lark-im/references/card/lark-im-card-create.md — 卡片工作流 Step 1–6、Step 4 发送命令、失败重试
- skills/lark-im/references/card/card-2.0-schema.md — Card 2.0 根结构与 config
- skills/lark-im/references/card/lark-im-card-style.md — 意图→组件组合、P0–P7、间距/高亮块模式
- skills/lark-im/references/card/components/button.md — button 字段、`primary_filled`+`fill`、`open_url` behaviors
- skills/lark-im/references/card/resource/icons.md — 图标精确 token 枚举（`bell_outlined`）

---

### 交付说明

本文件即交付物：一份可直接按序执行的命令清单（含工作流产出的完整卡片 JSON）。本机未实际执行命令 4–7 的发送——任务给定的 chat_id（`oc_aaa111` 等）为占位值，且需在已配置该授权 bot 的环境运行；执行时用真实 chat_id 替换后逐条运行即可。
