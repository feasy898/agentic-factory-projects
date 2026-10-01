# 「3.9 需求评审会」排会执行清单（2026-10-12 周一 ~ 2026-10-16 周五 · Asia/Shanghai）

> **需求**：为 4 位参会人（`ou_wang001`、`ou_li002`、`ou_zhao003`、`ou_sun004`）安排一场 60 分钟会议，配一间可容纳 ≥6 人的会议室；时间限定在 2026-10-12（周一）至 2026-10-16（周五）的工作时间内；议程三写入日程描述。
> **方法依据**：`skillfactory/v2/evalbench-v02/lark-cli/ASSET-DOC.md` §8.2（CRITICAL：凡涉及预约日程/会议室，第一步必读 `references/lark-calendar-schedule-meeting.md`）。本清单按该工作流逐条执行；所用 flag 已对照 GitHub 官方 reference 原文（本次实读）与本机 `lark-cli` v1.0.97 的 `--help` 实测输出双重核验，无编造。
> **占位符约定**：`<…>` 为占位符，每处注明来源（哪条命令返回值的哪个字段）。

---

## 一、流程判定（为什么走这条路径）

按 `lark-calendar-schedule-meeting.md` 工作流（官方要求按顺序执行，不得跳过前置步骤）：

| 工作流步骤 | 本任务判定 | 依据 |
|---|---|---|
| ① 任务类型判定 | **新建日程**（无既有日程锚点 + 修改动词） | schedule-meeting.md「任务类型判定」 |
| ② 补默认值 | 标题=用户给定「3.9 需求评审会」；参会人=用户给定的 4 人；时长=用户给定 60 分钟 | schedule-meeting.md「新建日程：智能推断默认值」 |
| ③ 时间是否明确 | **模糊**：只给了日期区间 + 「工作时间」，未定具体时点 → 进入模糊时间分支 | schedule-meeting.md「分支路由」 |
| ④ 模糊分支动作 | 先 `+suggestion` 产出候选时间块；**需要会议室** → 候选块交给 `+room-find` → 结构化展示【时间+会议室】供用户选择 | schedule-fuzzy-time.md「流程」 |
| ⑤ 用户确认 | **BLOCKING REQUIREMENT**：展示选项并等待用户确认后，禁止未经确认直接创建 | schedule-meeting.md 执行摘要 |
| ⑥ 落地 | `+create`：4 位参会人（`ou_`）+ 会议室（`omm_`，resource 型参与人）一并写入参与人列表 | schedule-meeting.md「落地日程变更」 |

---

## 二、为什么推荐时段必须用 `+suggestion`、仅查忙闲（`+freebusy`）不够

- **官方明文分工**（SKILL.md `+freebusy` 一节）：「`+freebusy` 只适用于查询忙碌/空闲时间段这一事实。如果目标是“给会议**推荐**一个合适的时间段”（单人或多人），必须优先使用 `+suggestion`——它会综合**工作时间段、忙碌时间段、休息时间段**来推荐，`+freebusy` 只回答“哪些区间空着”，不判断该区间是否适合排会。」
- **能力差异**（suggestion.md「与其他命令对比」）：`+suggestion` 返回**多个推荐时段及其理由**（并说明是否存在忙闲冲突）；`+freebusy` 只返回忙碌/空闲时段列表，**没有日程推荐语义**。
- **本任务实操差距**：窗口跨 5 个工作日。若用 `+freebusy --type common_free`，只能拿到 5 天内「4 人共同空闲」的原始区间，还需自己叠加工作时间过滤、午休剔除和排序；`+suggestion` 直接产出可直接提交用户挑选的候选时间块。
- **流程强约束**（schedule-fuzzy-time.md）：模糊时间场景核心动作就是「调用 `+suggestion` 产出候选时间块」；且确认时间块后「**无需再次调用 `+freebusy`**，直接进入落地操作」。

> 结论：`+freebusy` 回答的是事实问题（谁哪段空），`+suggestion` 回答的是决策问题（该约哪段）——本任务要的是后者。

## 三、为什么「先定时间、再找会议室」顺序不能反

1. **会议室的模型决定**（schedule-meeting.md「核心概念」）：「会议室是日程的一种参与人（attendee / resource），**不能脱离日程单独预定**」——预定或查找会议室，均需先确定时间块。
2. **命令输入约束**（room-find.md 参数表）：`--slot`（格式 `开始时间~结束时间`）是**必填**参数，且「`+room-find` 的时间输入必须是**确定时间块**，不是时间区间搜索」（SKILL.md「会议室规则」同款禁令）。
3. **官方明令**（SKILL.md）：「用户仅要求“查会议室”但未提供明确时间时，必须先调用 `+suggestion` 获取可用时间块，再将时间块交给 `+room-find`。**严禁猜测时间盲目调用**。」
4. **逻辑上也无意义**：时间未定时查到的“空闲会议室”不构成任何承诺——时间一变，空闲性全部作废，还得重查；反过来，时间块确定后查会议室，查到即可直接作为参与人落入 `+create`。

---

## 四、时间换算（北京时间 → 时间戳）：用什么方式、有什么坑

### 方式（首选：不换算）

`suggestion` / `room-find` / `create` 三个 shortcut 的 `--start`、`--end`、`--slot` **直接收 ISO 8601 带时区偏移的字符串**（如 `2026-10-12T09:00:00+08:00`），根本不需要手工换时间戳——这是本清单采用的方式（suggestion.md「时间格式」表；create.md 参数表）。

### 方式（确需时间戳时：系统工具 + 显式时区）

只有完整 API 命令的时间参数才用 **Unix 秒字符串**（create.md「高级用法」：「时间参数是 Unix 秒字符串（非 ISO 8601）」）。此时**必须调用系统命令/脚本换算，且显式指定 +08:00**（SKILL.md 强制性注意）。三种等价写法：

```powershell
# PowerShell
[DateTimeOffset]::Parse("2026-10-12T09:00:00+08:00").ToUnixTimeSeconds()
```
```bash
# Linux/macOS date（显式 +0800）
date -d "2026-10-12 09:00:00 +0800" +%s
```
```python
# Python
int(datetime.fromisoformat("2026-10-12T09:00:00+08:00").timestamp())
```

**本机实测记录（已运行，非推算）**：

```
PS> [DateTimeOffset]::Parse('2026-10-12T09:00:00+08:00').ToString('yyyy-MM-dd dddd'); ...ToUnixTimeSeconds()
2026-10-12 星期一
1791766800            ← 窗口起点（周一 09:00 北京时间）
PS> [DateTimeOffset]::Parse('2026-10-16T18:00:00+08:00') ...
2026-10-16 星期五
1792144800            ← 窗口终点（周五 18:00 北京时间）
PS> [DateTimeOffset]::FromUnixTimeSeconds(1791766800).UtcDateTime.AddHours(8).ToString(...)
2026-10-12 09:00:00   ← 反向换算回环验证一致
```

### 坑（逐条）

1. **禁止依赖容器/进程默认时区**：SKILL.md 强制性注意原文——「涉及日期（时间）字符串与时间戳的相互转换时，务必调用系统命令或脚本代码等外部工具进行处理……换算**禁止依赖容器默认时区**（常为 UTC，会导致 **8 小时偏移**），必须显式指定目标时区」。
2. **ISO 8601 必须带偏移**：create.md `--start` 说明——「**必须带时区偏移**，如 `2026-03-12T14:00+08:00`；**不带偏移会按进程时区解析致偏移**」。
3. **日期简写 ≠ 工作时间**：suggestion.md 时间格式表——仅传日期时 `--start` 取 `00:00:00`、`--end` 取 `23:59:59`（整天）。要限定工作时间，必须**显式写 `T09:00:00+08:00` / `T18:00:00+08:00`**（本清单第 1 条命令即如此处理）。
4. **Unix 时间戳一律秒级**（suggestion.md：`1741564800` 秒级时间戳），不要用毫秒。
5. **两套格式不要混**：shortcut 用 ISO 8601，完整 API 用 Unix 秒字符串——同一时间在两条路径下写法不同。
6. **星期/时区基准**：周一为一周第一天（SKILL.md「时间推断规范」）；Asia/Shanghai 现行无夏令时，+08:00 恒定（2026-10-12 实测确为星期一）。

---

## 五、命令清单（按序直接执行）

> 执行环境：用户已安装并完成认证的 lark-cli（任务前提）。每条命令附一句理由；flag 均有出处（GitHub 官方 reference + 本机 v1.0.97 `--help` 实测）。

### Step 1｜求 4 人共同空闲的 60 分钟候选时间块 —— `calendar +suggestion`

```bash
lark-cli calendar +suggestion \
  --start "2026-10-12T09:00:00+08:00" \
  --end "2026-10-16T18:00:00+08:00" \
  --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" \
  --duration-minutes 60 \
  --timezone "Asia/Shanghai" \
  --format json
```

**理由**：用户给的是日期区间 + 工作时间（模糊时间），必须由 `+suggestion` 综合工作/忙碌/休息时间产出 4 人共同空闲的 60 分钟候选块；仅查忙闲不产生推荐（见第二节）。
**说明**：工作时间按 09:00–18:00 显式传入（坑 3）；`+suggestion` 内部还会结合各人日历的工作/忙碌/休息设置过滤（SKILL.md）。4 人 ID 均为 `ou_` 用户（未传 bot 的 open_id，suggestion.md 参数表警告 bot 无忙闲语义会干扰推荐）。
**返回值占位**：`<候选时间块>` ← 本命令返回 JSON 中的推荐时间块列表（形如 `2026-10-13T14:00:00+08:00~2026-10-13T15:00:00+08:00`；具体字段名以返回为准，文档未逐一列名）。**注意**：返回的方案不保证完全空闲（suggestion.md AI 行为指导），需按推荐理由甄别并如实向用户标注冲突。

### Step 2｜在确定的时间块内查 ≥6 人会议室 —— `calendar +room-find`

```bash
lark-cli calendar +room-find \
  --slot "<候选时间块start>~<候选时间块end>" \
  --min-capacity 6 \
  --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" \
  --timezone "Asia/Shanghai" \
  --format json
```

**理由**：会议室只能作为日程的 resource 参与人预约、不能脱离日程单独预定，且 `+room-find` 必须基于**确定时间块**（`--slot` 必填）——所以必须在 Step 1 确定时间块之后调用（见第三节）；「可容纳 6 人」映射为 `--min-capacity 6`（room-find.md 参数表：用户提出容量要求时提取数字入此参）。
**说明**：若 Step 1 返回多个候选块、且想按官方 fuzzy-time.md 建议让用户「时间+会议室」一次选完，可重复 `--slot` 批量查询（本机 `--help` 实证 `--slot stringArray` 可重复）。用户未指定城市/楼宇/楼层/会议室名，故不传 `--city/--building/--floor/--room-name`（`--city` 仅在用户明确说出城市时才允许提取，room-find.md 规则）。
**返回值占位**：`<omm_room_id>` ← 本命令返回的 `room_id` 字段；`<会议室名称>` ← `room_name` 字段（展示给用户必须逐字透传原值，禁止重组）；另有 `capacity`（容纳人数）、`reserve_until_time`（最晚可约时间，本任务非重复日程仅作校验）——均见 room-find.md「字段说明」。

### Step 3｜展示【时间 + 会议室】选项，等待用户确认（流程必需，不可跳过）

**动作**：将候选时间块与对应可用会议室按官方要求的结构化格式（分行、编号，时间与会议室**不得同行**）展示给用户，等待其选定。
**理由**：schedule-meeting.md 执行摘要——「**BLOCKING REQUIREMENT**：面临时间方案或会议室方案的选择时，必须先向用户展示选项并等待确认，禁止未经确认直接创建/更新日程」；且 `+create` 是写操作，执行前必须确认用户意图（create.md CAUTION）。
**产出占位**：`<确定时间块start>` / `<确定时间块end>` ← 用户选定的候选块（源自 Step 1）；`<omm_room_id>` ← 用户选定的会议室（源自 Step 2）。

### Step 4｜创建日程：4 位参会人 + 会议室一并带上 —— `calendar +create`

```bash
lark-cli calendar +create \
  --summary "3.9 需求评审会" \
  --start "<确定时间块start>" \
  --end "<确定时间块end>" \
  --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004,<omm_room_id>" \
  --description "## 会议议程
1. 3.9 需求范围确认
2. 接口依赖评审
3. 排期确认" \
  --as user \
  --format json
```

**理由**：`+create` 一次完成「创建日程 + 邀请参会人」，参与人列表同时收 `ou_`（用户）与 `omm_`（会议室 resource）——这正是「会议室只能作为日程参与人预定」的落地方式（schedule-meeting.md：需要会议室时，将选中的 `room_id` 写入参与人列表）。
**要点**：
- 时间用 **ISO 8601 带偏移**（坑 2），开始/结束为用户确认块的 60 分钟起止；
- `--summary` 只放标题，不含时间/地点/人物（create.md 参数表）；议程以 **Markdown 有序列表**写入 `--description`（create.md：描述统一此字段，Markdown 格式）；
- 长描述可改走 `--description @agenda.md`（`@` 文件）或 `-`（stdin）——注意文件路径**只接受 cwd 相对路径**（lark-shared 安全规则 5，ASSET-DOC §8.1）；
- 默认行为（create.md）：自动加 5 分钟提醒、忙状态、飞书视频会议、参会人 `can_modify_event`；**失败保护**：若参会人（含会议室 ID）添加失败，CLI 自动删除刚建的空日程并回滚；
- 会议室若需审批：`+create` 不暴露 `approval_reason`，应先用 `+create` 创建，再以用户身份调完整 API `calendar event.attendees create --as user` 添加会议室并附 `approval_reason`（create.md 注释及示例，此处不展开）；
- 若命令返回退出码 10（`type=confirmation` 高风险确认门禁）：停下→向用户展示 `action`/`risk`→取得显式同意→把 `hint` 指出的确认 flag **追加到原始 argv 末尾**重试，绝不静默加 flag（ASSET-DOC §7.3）。
**返回值占位**：`<EVENT_ID>` ← 本命令成功信封（`{"ok":true,...}`）中的新建日程标识；**成功判定看 `ok == true`（或退出码 0），不要用 `code == 0`**（ASSET-DOC §5.2）。

### Step 5｜直接向用户反馈结果（不二次查询）

**动作**：基于 Step 4 的返回结果直接反馈：会议时间、时长、4 位参会人、会议室名称与容量、日程描述（议程三）、`<EVENT_ID>`。
**理由**：SKILL.md「写操作反馈」——「创建、更新、删除、RSVP 等写操作完成后，直接基于命令返回结果反馈用户；**不要为了“确认是否生效”主动发起二次查询**。」

**反馈话术模板**：

> ✅ 「3.9 需求评审会」已创建（60 分钟）。
> 时间：2026-10-XX（周X）HH:MM–HH:MM（北京时间）
> 参会人：ou_wang001、ou_li002、ou_zhao003、ou_sun004
> 会议室：<会议室名称>（容 <capacity> 人）
> 议程已写入日程描述：1) 3.9 需求范围确认；2) 接口依赖评审；3) 排期确认。

---

## 六、核验记录（本次实际执行过什么）

| 核验项 | 命令 | 结果 |
|---|---|---|
| 官方方法来源 | 读取本地 `ASSET-DOC.md` 全文；下载并通读 GitHub raw：`lark-calendar/SKILL.md` 及 `references/` 下 schedule-meeting / schedule-fuzzy-time / suggestion / room-find / create 六篇 | 通过（引用均注明） |
| flag 实证 | 本机 `lark-cli calendar +suggestion --help`、`+room-find --help`、`+create --help`（v1.0.97） | 通过：`--start/--end/--attendee-ids/--duration-minutes/--timezone`、`--slot(可重复)/--min-capacity`、`--summary/--description/@file/--as` 等全部存在 |
| 时间换算 | PowerShell `[DateTimeOffset]::Parse(...)` 正向 ×2 + `FromUnixTimeSeconds` 反向 ×1 | 通过：10-12=周一 1791766800；10-16=周五 1792144800；回环一致 |
| 认证状态 | 本机 `lark-cli auth status` | 返回 `ok:false, not_configured`——**本机未配置**；本清单面向任务前提中“已认证的用户环境”。若确在未认证环境执行，先按 ASSET-DOC §2.3：后台跑 `lark-cli config init --new`（输出授权 URL 交用户完成）再 `lark-cli auth login --recommend` |
| 实际排会 | 未执行（交付物为执行清单；且本机未认证，无法也不应代跑写操作） | 如实说明 |

---

## 七、冲突注明（任务要求 vs 资产说明）

按任务要求在此注明两者的差异处理，**以任务为准**：

1. **无实质冲突**。任务规定的顺序（先定共同空闲 → 在确定时间块内找会议室 → 创建日程）与官方 schedule-meeting → fuzzy-time 工作流完全一致。
2. **一处细节差异**：任务口径是“确定的时间块”内找会议室；官方 schedule-fuzzy-time.md 进一步建议——需要会议室时**不要让用户只先选时间**，而应把 `+suggestion` 的多个候选块**一次性批量**传给 `+room-find`，将【候选时间 + 对应可用会议室】结构化展示，让用户一次完成选择。本清单主路径按任务口径（Step 2 用单个确定时间块），并在 Step 2 说明中保留“多候选批量 `--slot`”的官方推荐作为可选项。
3. **一处任务未提、资产说明强制的补充**：创建前的 BLOCKING 用户确认门禁（Step 3）与 `+create` 写操作确认要求（create.md CAUTION）。该补充与任务“创建成功后直接反馈”不矛盾，已纳入清单。
