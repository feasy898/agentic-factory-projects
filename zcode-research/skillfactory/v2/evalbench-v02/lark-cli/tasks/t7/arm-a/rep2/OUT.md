# 3.9 需求评审会 · 排会执行清单（2026-10-12 周一 ～ 2026-10-16 周五 · Asia/Shanghai）

> 交付物：可按序直接执行的命令清单。`<占位符>` = 上一条命令的返回值，来源在各条「来源」注明；每条命令附一句理由；全部命令与 flag 均有出处（本机 `lark-cli` 1.0.97 的 `--help` 实测输出 + 飞书官方 `larksuite/cli` 仓库 SKILL.md / references 原文），无一杜撰。
>
> 需求：60 分钟「3.9 需求评审会」，4 位参会人 `ou_wang001, ou_li002, ou_zhao003, ou_sun004`，会议室可容纳 ≥6 人，工作时间内（本清单约定为 09:00–18:00，Asia/Shanghai，午休 12:00–14:00 由推荐命令的休息时间逻辑规避），议程三项写入日程描述。

---

## 0. 执行前提（含一处必须说明的实测偏差）

| 项 | 状态 | 依据 |
|---|---|---|
| lark-cli 已安装 | ✅ 成立 | 本机实测 `lark-cli --version` → `lark-cli version 1.0.97` |
| 已完成认证 | ⚠️ **本机未成立** | 实测 `lark-cli auth status` → 退出码 3，`{"ok":false,"error":{"type":"config","subtype":"not_configured","hint":"run `lark-cli config init --new` …"}}`。任务前提「已认证」在**本机档案**上不成立；本清单第 0 步即认证核验，若在已认证环境执行则直接通过 |
| 命令 flag 权威来源 | ✅ | ① 本机 `lark-cli calendar +suggestion/+freebusy/+room-find/+create --help` 输出（对已装版本 1.0.97 权威）；② 官方 `skills/lark-calendar/` 的 SKILL.md 与 `references/lark-calendar-{suggestion,room-find,create}.md`（GitHub raw） |

---

## 1. 时间换算（北京时间 → 时间戳）：用什么方式、有什么坑

**方式：系统工具 + 显式 `+08:00` 偏移字符串。**

- 本清单四个快捷命令（`+freebusy` / `+suggestion` / `+room-find` / `+create`）的时间参数**直接收 ISO 8601 带偏移字符串**（help 原文 "ISO 8601"），因此主路径**无需手工转时间戳**。其中 `+create --start/--end` 官方参考明确要求「ISO 8601 时间，必须带时区偏移（例如 `2026-03-12T14:00+08:00`）；缺少偏移会导致解析错误」。
- 需要 Unix 时间戳时（如 §2 分支 5b 的完整 API 场景），用系统工具转换（skill 时间规则原文：「日期/时间戳转换必须调用系统工具」）：

```powershell
# PowerShell（本机已实测，见 §6）
[DateTimeOffset]::Parse('2026-10-12T09:00:00+08:00').ToUnixTimeSeconds()
```
```python
# Python 等价写法
from datetime import datetime
int(datetime.fromisoformat('2026-10-12T09:00:00+08:00').timestamp())
```

**本清单窗口的实测换算值**（PowerShell `[DateTimeOffset]::Parse(...).ToUnixTimeSeconds()`，本机 2026-09-30 实跑）：

| 北京时间 | Unix 秒 | 星期 |
|---|---|---|
| 2026-10-12T09:00:00+08:00 | `1791766800` | Monday（周一，与任务前提一致 ✓） |
| 2026-10-16T18:00:00+08:00 | `1792144800` | Friday ✓ |
| 2026-10-13T14:00:00+08:00（格式示例用） | `1791871200` | Tuesday |
| 2026-10-13T15:00:00+08:00（格式示例用） | `1791874800` | Tuesday |

**三个坑**：
1. **禁止依赖宿主/容器默认时区**（skill 时间规则原文：常为 UTC，会导致 8 小时偏移）。规避法：字符串里**显式写 `+08:00`**——解析带偏移的字符串后，换算结果与宿主时区无关；绝不可写「裸本地时间字符串直接 `.timestamp()`」这类依赖宿主时区的代码。
2. **完整 API（raw API / 分支 5b）的时间参数是 Unix 秒，不是毫秒**（create 参考原文：「完整 API 中的时间参数以 Unix 秒为单位」）；快捷命令则相反收 ISO 8601——两套入口单位不同，勿混用。
3. 中国无夏令时，`+08:00` 全年固定，但偏移仍必须显式写；同时 `+create` 缺偏移会直接解析报错（见上）。

---

## 2. 命令清单（按序执行）

> 约定：read 类命令（步骤 0–3，help 标注 `Risk: read`）可直接执行；write 类（步骤 5，`Risk: write`）执行前先 `--dry-run` 预览再实跑。身份一律 `--as user`（操作登录用户日历与用户参会人；bot 身份查用户资源会「返回空成功而非报错」，lark-shared 规则）。

### 步骤 0 · 认证核验

```bash
lark-cli auth status
```

- **理由**：确认已登录且 scope 覆盖日历域，后续命令才能以 `--as user` 身份读到 4 位参会人的忙闲。
- **预期与占位**：stdout 信封 `"ok": true` → `<AUTH_STATUS>`（来源：本命令 stdout 信封，契约见 ASSET-DOC §5.2）。若返回 `not_configured` / `authentication`，按官方流程后台执行 `lark-cli config init --new`（输出授权 URL 交用户浏览器完成）与 `lark-cli auth login --recommend`，再回到本步复核。

### 步骤 1 · 查 4 人共同忙闲（事实底座）

```bash
lark-cli calendar +freebusy --as user ^
  --start "2026-10-12T09:00:00+08:00" --end "2026-10-16T18:00:00+08:00" ^
  --user-id "ou_wang001,ou_li002,ou_zhao003,ou_sun004" ^
  --type common_free --min-duration 1h
```

- **理由**：先拿到 5 个工作日窗口内 4 人「≥60 分钟共同空闲块」的事实底座；`--type common_free` 让 CLI 直接算多用户交集（help Tips 原文：用 `--type common_free --min-duration <dur>` 让 CLI 计算交集而不是手工合并），`--min-duration 1h` 过滤掉不足以放下 60 分钟会议的碎片。
- **返回占位**：`<COMMON_FREE>`（来源：本命令 stdout 信封 `data`）。

### 步骤 2 · 时间建议，定推荐时段（决策输出）

```bash
lark-cli calendar +suggestion --as user ^
  --start "2026-10-12T09:00:00+08:00" --end "2026-10-16T18:00:00+08:00" ^
  --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" ^
  --duration-minutes 60 --timezone "Asia/Shanghai"
```

- **理由**：skill 明文规定「推荐时段必须用 +suggestion」——它综合工作时间、忙闲与休息时间产出**带理由的候选时段**；本任务输入是「10-12～10-16 工作时间内」这种范围而非明确时间点，正中 suggestion 参考文档的触发条件（“本周”“近三天”类模糊时间）。详细论证见 §3。
- **返回占位**：`<SUGGESTIONS>`（来源：本命令 stdout 信封 `data` 中的推荐时段列表）。从中选定一个时段，记 **`<T_START>` / `<T_END>`**（选取时与步骤 1 的 `<COMMON_FREE>` 交叉核对，优先整点开始、避开午休）。

### 步骤 3 · 在确定时间块内找会议室

```bash
lark-cli calendar +room-find --as user ^
  --slot "<T_START>~<T_END>" ^
  --min-capacity 6 ^
  --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" ^
  --timezone "Asia/Shanghai"
```

- **理由**：会议室候选随时段变化，必须在**已确定的**时间块内查该时段可用的房间（顺序不能反的论证见 §4）；`--slot` 格式为 `开始~结束`（可重复传多个候选块，room-find 参考原文），`--min-capacity 6` 对应「可容纳 6 人」（4 位参会人 + 组织者本人 = 5 人，留 1 人余量）；带 `--attendee-ids` 让推荐考虑参会人（参考文档示例同款用法）。
- **返回占位**：**`<ROOM_ID>`**（`omm_` 前缀）、`<ROOM_NAME>`（来源：本命令 stdout 会议室候选的 `room_id` / `room_name` / `capacity` 字段，字段名出自 room-find 参考文档「关键字段」节）。

### 步骤 4 · 写议程描述文件（供 `@file` 引用）

在当前工作目录保存 `agenda.md`（内容如下；本次交付已同时备好一份：`skillfactory/v2/evalbench-v02/lark-cli/tasks/t7/arm-a/rep2/agenda.md`）：

```markdown
## 议程
1. 3.9 需求范围确认
2. 接口依赖评审
3. 排期确认
```

- **理由**：`+create --description` 支持 `@文件路径` 或 stdin（help 原文），走文件避免命令行引号/转义问题；lark-shared 安全规则规定此类路径**只接受 cwd 相对路径**，绝对路径报 `unsafe file path`。

### 步骤 5 · 创建日程（4 位参会人与会议室一并带上）

先预览，确认请求无误后去掉 `--dry-run` 实跑：

```bash
lark-cli calendar +create --as user ^
  --summary "3.9 需求评审会" ^
  --start "<T_START>" --end "<T_END>" ^
  --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004,<ROOM_ID>" ^
  --description @agenda.md ^
  --dry-run
```

- **理由**：一条命令把 4 位用户参与人（`ou_`）与会议室资源参与人（`omm_`）一并带上——help 原文：`--attendee-ids` "supports user ou_, chat oc_, room omm_"；会议室正是以资源参与人身份随日程预定（room-find 参考原文：「会议室是日程的资源型参与人，不能脱离日程单独预定」）；议程三项以 Markdown 有序列表落入 description。
- **返回占位**：**`<EVENT_ID>`**（来源：本命令 stdout 信封 `data`；成功判定 `ok==true` 且退出码 0，勿用 `code==0`，见 §5）。
- 注意（`Risk: write`）：这是写操作，任务方已确认意图；若触发退出码 10 确认门禁，按 §5 处理。

**分支 5b（仅当会议室需要审批时）**——create 参考文档原文给出的完整 API：

```bash
lark-cli calendar event.attendees create --as user ^
  --params '{"calendar_id":"<CALENDAR_ID>","event_id":"<EVENT_ID>"}' ^
  --data '{"attendees":[{"type":"resource","room_id":"<ROOM_ID>","approval_reason":"3.9 需求评审会，6 人会议室，4 位参会人"}]}'
```

- **理由**：create 参考明确「若会议室需要审批，请使用此完整 API 命令」，`approval_reason` ≤200 字符；`<CALENDAR_ID>` 缺省即主日历 `primary`。

### 步骤 6 · 直接向用户反馈结果（不做二次查询）

创建成功（stdout `ok:true`、退出码 0）后，**立即**向用户反馈：会议时间 `<T_START>～<T_END>`（Asia/Shanghai，60 分钟）、会议室 `<ROOM_NAME>`、日程 ID `<EVENT_ID>`、4 位参会人已发出邀请、议程已写入描述。

- **理由**：skill 限制原文「写操作后直接反馈，不要二次查询确认」；且 `+get` 本就不返回参会人/会议室（需 `+list-attendees`），复查没有增量信息，只会多一次无意义请求。

---

## 3. 为什么定推荐时段必须用 `+suggestion`，仅查忙闲（`+freebusy`）不够

1. **规则层（硬约束）**：skill 限制原文：「推荐时段必须用 `+suggestion`，`+freebusy` 只回答哪些区间空闲」。这是官方 skill 的明文规定，不是风格偏好。
2. **功能层**：`+freebusy` 的输出是忙/闲区间列表（`--type common_free` 也只是「全员共同空闲」的交集集合）；`+suggestion` 参考文档明确其职责是「根据非明确时间推荐多个可用时间块」，综合**工作时间、忙闲与休息时间**，输出候选时段+理由。本任务的输入「10-12～10-16 工作时间内」是范围而非明确时间点，正中 suggestion 的触发条件（“本周”“近三天”类）；若用户已给出明确时间点才不调用它。
3. **结果层**：`common_free` 的交集完全可能落在午休（12:00–14:00）、临近下班（17:20–18:00）或跨日碎片上，仍需人工逐段过滤与判断；`+suggestion` 直接在工作时间/休息约束内给方案，且方案存在忙闲冲突时会**如实标注**并给优化建议（返回含 `ai_action_guidance` 时须主动向用户提供调整建议）。

结论：步骤 1（freebusy）提供「事实底座」，步骤 2（suggestion）产出「决策输出」，二者互补不可互替——只查忙闲不等于完成了「定推荐时段」。

## 4. 为什么必须先定时间、再在时间块内找会议室（顺序不能反）

1. **命令输入约束**：`+room-find` 的时间输入「必须是确定时间块，不是时间区间搜索」（room-find 参考原文），skill 原文「`+room-find` 需确定时间块，禁止猜时间」，SKILL.md 操作规则「若未明确时间，先调用 `+suggestion`」。没有步骤 2 的输出 `<T_START>~<T_END>`，步骤 3 根本没有合法输入——这不是流程偏好，是命令的前置条件。
2. **可用性是时间的函数**：「房间能容纳 6 人」不随时段变，但「该房间在该时段是否空闲」随时段变。若先找房再定时间，等时间最终确定后，选中的房间大概率已被他人订走，只能推倒重找；先定时间再 `+room-find`，一次查询得到的就是「该时段可用且 ≥6 人」的候选，结果即取即用。
3. **落地依赖链**：会议室是日程的 resource 参与人，「不能脱离日程单独预定」（room-find 参考原文）；而日程创建（步骤 5）需要确定的 `start/end`。时间块 → 房间 → 带房创建是依赖链的正序，反过来每一环都悬空。

## 5. 异常处理与红线

- **成功判定**：只看 `ok == true` 或退出码 0，**不用 `code == 0`**（ASSET-DOC §5.2：成功信封没有顶层 `code`，按旧 OpenAPI 惯例判断会把成功误判为失败）。
- **退出码 10 = 高风险确认门禁，不是错误**：停下 → 向用户展示 `action`、`risk` 及关键参数 → 取得显式同意后，把 `hint` 指出的确认 flag **追加到原始 argv 末尾**重试；绝不静默加 flag 绕过（ERROR_CONTRACT §7.3）。
- **参会人 open_id 错误 → 创建回滚**：create 参考原文「参会人添加失败（例如 open_id 错误）会触发回滚，删除已创建的日程」——需修正 ID 后整体重来，勿以为日程还在。
- **`--attendee-ids` 同类型内是 OR（并集）不是 AND**（skill 限制原文）：「共同有空」的判定靠步骤 1/2 的忙闲与推荐命令完成，不靠参会人列表本身。
- **错误信封分支**：只对 wire-stable 字段（`type`/`subtype`/`code`/`retryable`…）分支；`authorization` → 读 `missing_scopes` 提示补授权；`network` → 可安全重试。
- **身份一律 `--as user`**：本流程操作登录用户的日历与用户型参会人。
- **禁止拼接链接**：日程分享链接 ≠ 会议链接，反馈时只用命令返回值，不手工拼 applink（skill 限制原文）。

## 6. 本清单验证记录（如实区分「已跑」与「未跑」）

**已在本机实跑（2026-09-30）**：

| 检查 | 命令 | 结果 |
|---|---|---|
| 安装与版本 | `lark-cli --version` | `lark-cli version 1.0.97` |
| flag 权威核对 | `lark-cli calendar +suggestion/+freebusy/+room-find/+create --help` | 四份 help 全部拿到，清单 flag 与之一致 |
| 认证核验 | `lark-cli auth status` | **退出码 3，`type=config / subtype=not_configured`**——本机未配置，任务前提「已完成认证」本机不成立（已如实上报，修复路径见步骤 0） |
| 时间换算 | `powershell …[DateTimeOffset]::Parse('2026-10-12T09:00:00+08:00').ToUnixTimeSeconds()` 等 4 条 | `1791766800`（周一）/ `1792144800`（周五）/ `1791871200` / `1791874800` |
| 主命令干跑 | 步骤 1/2/3/5 四条命令 + `--dry-run` | 全部返回 `type=config / not_configured`（退出码 3），在配置层拦截，**无任何副作用**；未出现 `validation` 错误 |
| 控制实验 | `lark-cli calendar +freebusy --definitely-not-a-flag x --dry-run` | 返回 `type=validation / invalid_argument ("unknown flag")`——证明 **flag 解析先于配置门禁**，故上述干跑通过配置前解析即证明清单中所有 flag 均被 1.0.97 识别，无杜撰 flag |

**未跑（本机无法跑）**：步骤 1–5 的真实执行——需要已认证环境（本机 `not_configured`，且认证需用户浏览器交互）。因此所有返回值以占位符交付，来源已逐条注明。

## 7. 与 ASSET-DOC / 官方 skill 的冲突说明（按任务要求注明，以任务为准）

- 官方 `lark-calendar-schedule-meeting` 工作流要求「时间方案或会议室方案必须先让用户确认，禁止擅自创建/更新」；本任务明确指示「先定共同空闲 → 再在确定时间块找房 → 创建时把参会人与会议室一并带上 → 创建成功后直接向用户反馈」，即由任务方预先授权直达创建、不做中途确认。按「任务为准」原则，本清单按任务顺序直达创建，未插入人工确认环节；若在真实环境执行，建议在步骤 2/3 输出处顺带向用户展示所选时段与会议室（不与任务冲突，更稳妥）。
- 其余全部一致：时间换算必须用系统工具且显式 `+08:00`、推荐时段必须 `+suggestion`、`+room-find` 必须确定时间块、会议室作为 `omm_` 资源参与人随 `+create` 一并创建、写操作后直接反馈不二次查询。

---

*交付物生成于 2026-09-30；命令与 flag 出处：本机 lark-cli 1.0.97 `--help` 实测 + `github.com/larksuite/cli` 官方 SKILL.md / references（lark-calendar-suggestion / room-find / create / schedule-meeting）原文；验证记录见 §6。*
