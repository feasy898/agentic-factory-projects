# 「3.9 需求评审会」排会命令清单（2026-10-12 周一 ～ 2026-10-16 周五 · Asia/Shanghai）

> **交付物**：可按序直接执行的命令清单。工具：`lark-cli`（larksuite/cli，本机实测版本 1.0.97）。
> **命令来源**：全部命令与 flag 逐一核验自本机实际运行的 `lark-cli --help`、`lark-cli calendar --help`、`lark-cli calendar +freebusy|--suggestion|+room-find|+create --help`，以及 CLI 内置文档（`lark-cli skills read lark-calendar` 及其 references），**无任何编造的命令或 flag**。
> **本机实况（诚实声明）**：`lark-cli doctor` 实测返回 `cli_version: pass (1.0.97)`、`config_file: fail (not configured)`；`lark-cli whoami` 实测返回 `not_configured`。即本机 CLI 未完成认证，真实 API 调用无法在本机执行。因此所有**返回值一律用 `<占位符>` 表示并在 §0 注明来源**，请在已认证环境按序执行、用真实返回值回填。任务给出的 4 个 open_id 视为任务给定值原样使用。

**执行顺序**：§1（定共同时间）→ §2（定会议室）→ §3（用户确认）→ §4（创建日程）→ §5（反馈结果）。顺序依据见 §1、§2 的说明。

---

## 0. 占位符总表（回填来源）

| 占位符 | 含义 | 来源（哪条命令的返回） |
|---|---|---|
| `<推荐时段i起>` `<推荐时段i止>` | 候选时间块起止（ISO 8601，带 +08:00） | §1B `+suggestion` 返回的推荐时间块 |
| `<room_id>` | 会议室资源 ID（`omm_` 前缀） | §2 `+room-find` 返回的 `room_id` 字段 |
| `<room_name>` / `<capacity>` | 会议室名称 / 容量（展示用） | `+room-find` 返回的 `room_name` / `capacity` 字段 |
| `<选定时段起>` `<选定时段止>` | 用户确认后的最终时间 | §3 用户选择，取自 §1B 候选 |
| `<EVENT_ID>` / `<CALENDAR_ID>` | 新日程事件/日历 ID（仅备用审批流程用） | §4.2 `+create` 返回 |
| `<agenda.md 路径>` | 议程 Markdown 本地文件路径 | §4.1 由执行者保存 |

固定参数（任务给定）：参会人 `ou_wang001, ou_li002, ou_zhao003, ou_sun004`；时长 60 分钟；会议室可容纳 ≥6 人；时区 Asia/Shanghai（UTC+8，无夏令时）；工作时间按 09:00–18:00。

---

## 1. 第一步：确定四人共同有空的时间

### 1A.（可选底账）查四人公共空闲窗口

```bash
lark-cli calendar +freebusy --user-id "ou_wang001,ou_li002,ou_zhao003,ou_sun004" --start "2026-10-12T09:00:00+08:00" --end "2026-10-16T18:00:00+08:00" --type common_free --min-duration 1h
```

**理由**：一条命令拿到四人共同空闲的几何交集（`common_free` 视图，由 CLI 代算交集），`--min-duration 1h` 直接过滤掉不足 60 分钟的碎片空档，作为后续选择的事实底账。
**注意**：`common_free` 只算"谁都没被占"，18:00–次日 09:00 的夜间空档也会被列为"空闲"——它不判断该区间适不适合开会。这正是下一步必须用 `+suggestion` 的原因之一。

### 1B.（主命令）时间建议：逐工作日推荐可用时段

```bash
lark-cli calendar +suggestion --start "2026-10-12T09:00:00+08:00" --end "2026-10-12T18:00:00+08:00" --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" --duration-minutes 60 --timezone "Asia/Shanghai"
lark-cli calendar +suggestion --start "2026-10-13T09:00:00+08:00" --end "2026-10-13T18:00:00+08:00" --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" --duration-minutes 60 --timezone "Asia/Shanghai"
lark-cli calendar +suggestion --start "2026-10-14T09:00:00+08:00" --end "2026-10-14T18:00:00+08:00" --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" --duration-minutes 60 --timezone "Asia/Shanghai"
lark-cli calendar +suggestion --start "2026-10-15T09:00:00+08:00" --end "2026-10-15T18:00:00+08:00" --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" --duration-minutes 60 --timezone "Asia/Shanghai"
lark-cli calendar +suggestion --start "2026-10-16T09:00:00+08:00" --end "2026-10-16T18:00:00+08:00" --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" --duration-minutes 60 --timezone "Asia/Shanghai"
```

**理由**：把"一周工作时间范围 + 4 人 + 60 分钟"交给日历服务，产出**可直接开会的推荐时间块**（含推荐理由与冲突提示），这就是候选时间的来源。逐日显式传 09:00–18:00 边界，把"工作时间内"变成结构性保证（而非依赖隐含行为）；若接受服务端按工作时间自动过滤，也可合并为一次整周调用（`--start "2026-10-12T09:00:00+08:00" --end "2026-10-16T18:00:00+08:00"`，其余参数不变）。

**为什么推荐时段必须用 `+suggestion`、仅查忙闲（`+freebusy`）不够**（依据 CLI 内置文档 `lark-cli skills read lark-calendar`）：

1. 官方 SKILL 原文："`+freebusy` 只适用于查询忙碌/空闲时间段这一事实。如果目标是'给会议**推荐**一个合适的时间段'（单人或多人），必须优先使用 `+suggestion`——它会综合**工作时间段、忙碌时间段、休息时间段**来推荐，`+freebusy` 只回答'哪些区间空着'，不判断该区间是否适合排会。"
2. 具体差距：① `freebusy / common_free` 是纯几何交集，夜间、午休等"空着但不该开会"的区间都会返回，要人工剔除；② `+suggestion` 在服务端完成工作时间/休息时间过滤，直接返回成块的候选时段、推荐理由和冲突提示（`ai_action_guidance`），推荐方案若含忙闲冲突须向用户如实说明，不得说成"完全空闲"。

**产出**：候选时间块 `<推荐时段1起>~<推荐时段1止>`、`<推荐时段2…>`（建议取前 2~3 个）。

---

## 2. 第二步：在确定的时间块内找可容纳 6 人的会议室

```bash
lark-cli calendar +room-find --slot "<推荐时段1起>~<推荐时段1止>" --slot "<推荐时段2起>~<推荐时段2止>" --min-capacity 6 --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004" --timezone "Asia/Shanghai"
```

- `--slot` 格式为 `开始~结束`（ISO 8601 带 +08:00），可重复传入多个候选时间块，CLI 内部并发查询后聚合为一次输出。
- **理由**：`--min-capacity 6` 落实"容纳 6 人"的硬性条件；带 `--attendee-ids`（只传 4 位用户，勿传 bot——文档明确 bot 无忙闲/席位语义）让推荐结合实际参会人。不传 `--city/--building/--floor/--room-name`：任务未限定地点，文档规定不得凭空联想补全。

**为什么这个顺序不能反（必须先定时间、再找会议室）**：

1. **文档硬性规定**（`lark-cli skills read lark-calendar` 会议室规则原文）："`+room-find` 的时间输入必须是**确定时间块**，不能是时间区间搜索""用户仅要求'查会议室'但未提供明确时间时，必须先调用 `+suggestion` 获取可用时间块，再将时间块交给 `+room-find`。**严禁猜测时间盲目调用**"；schedule-meeting 工作流同样写明"预定或查找会议室，均需先确定时间块"。
2. **语义上**：会议室的"可用"只针对某个具体时间块成立；时间不锁定，`+room-find` 无从查起。
3. **工程上**：4 人的共同空闲交集通常比"某时段有空会议室"更稀缺。先锁时间再配房间，若房间不满意只需重跑本步；反之先选房间再迁就时间，一旦有人冲突要改期，会议室查询全部作废重来。且"会议室是日程的一种参与人（resource attendee），不能脱离日程单独预定"，最终必须并入 §4.2 的创建调用。

**产出**：每个时间块下的可用会议室列表；记录 `<room_id>`（`omm_` 前缀）、`<room_name>`、`<capacity>`。

---

## 3. 第三步：向用户展示候选并确认（创建前必做）

内置 schedule-meeting 工作流将此标为 **BLOCKING REQUIREMENT**："面临时间方案或会议室方案的选择时，必须先向用户展示选项并等待确认，禁止未经确认直接创建/更新日程。" 展示模板（时间与会议室必须分行，严禁同行揉排）：

```text
## 2026-10-13 周二

[选项 1] <推荐时段起> - <推荐时段止>（参会人均空闲）
  可用会议室：
  1. <room_name>(<capacity>人)
  2. <room_name>(<capacity>人)

💡 请回复您倾向的选项编号以及对应的会议室序号，我来为您完成预定。
```

**产出**：`<选定时段起>` `<选定时段止>`（= 起 + 60 分钟）与选定的 `<room_id>`。

---

## 4. 第四步：创建日程（4 位参会人与会议室一并带上）

### 4.1 前置：议程写入本地 Markdown 文件

`--description` 支持 `@文件路径` 传入 Markdown。将以下内容保存为 `agenda.md`（**UTF-8 编码**），可避免命令行内联长文本的引号转义问题：

```markdown
## 议程

1. 3.9 需求范围确认
2. 接口依赖评审
3. 排期确认
```

### 4.2 创建

```bash
lark-cli calendar +create --summary "3.9 需求评审会" --start "<选定时段起，ISO 8601 带 +08:00>" --end "<选定时段止 = 起 + 60 分钟>" --attendee-ids "ou_wang001,ou_li002,ou_zhao003,ou_sun004,<room_id>" --description @<agenda.md 路径>
```

- **理由**：`+create` 一条命令同时完成建日程与邀请参会人；`--attendee-ids` 同时支持用户（`ou_`）、群组（`oc_`）与会议室（`omm_`）——4 位参会人与 `<room_id>`（务必保留 `omm_` 前缀）一次带上，会议室即以 resource 参会人身份入会。
- 标题只写"3.9 需求评审会"：文档要求标题不含时间/地点/人物信息（时间由 start/end 承担、地点由会议室承担）。
- 风险级别为 `write`（CLI 约定仅 `high-risk-write` 需要 `--yes`；创建前用户已在 §3 确认）。
- 内置默认行为（来自文档）：参会人可互相查看与编辑日程、日程标记忙碌、开始前 5 分钟提醒、默认附带飞书视频会议。
- 失败保护：若添加参会人失败（如 open_id 错误），CLI 自动删除刚创建的空日程并回滚。
- **备用（仅当所选会议室需要审批时）**：`+create` 不暴露 `approval_reason` 字段，文档要求先用用户身份创建日程，再用完整 API 添加会议室并附审批原因（≤200 字）：

```bash
lark-cli calendar event.attendees create --as user --params "{\"calendar_id\":\"<CALENDAR_ID>\",\"event_id\":\"<EVENT_ID>\"}" --data "{\"attendees\":[{\"type\":\"resource\",\"room_id\":\"<room_id>\",\"approval_reason\":\"<审批原因>\"}]}"
```

---

## 5. 第五步：向用户反馈结果

创建成功后**直接基于 `+create` 的返回反馈，不再发起二次查询确认**（内置文档"写操作反馈"规则：写操作完成后直接基于命令返回结果反馈用户，只有用户明确要求复查才再查询）。反馈要点（取自 `<+create 返回 JSON>` 与 §2 记录）：

- 时间：`<选定时段起> – <选定时段止>`（Asia/Shanghai，周一至周五中已确认的一天）；
- 标题：3.9 需求评审会；参会人：ou_wang001、ou_li002、ou_zhao003、ou_sun004；
- 会议室：`<room_name>`（容纳 `<capacity>` 人，满足 6 人需求）；
- 议程 3 项已写入日程描述；
- 诚实性要求：若 §1B 推荐块本身含忙闲冲突，反馈时必须如实说明，不得表述为"完全空闲"。

---

## 6. 时间换算：北京时间 → 时间戳，怎么做、有什么坑

**方式 A（本清单全部采用，推荐）**：**不手工换算**——直接给 CLI 传 ISO 8601 且**显式带 `+08:00` 偏移**的时间字符串，由 CLI 完成转换。依据 `+create` 文档原文：start/end "（ISO 8601，**必须带时区偏移**，如 `2026-03-12T14:00+08:00`；不带偏移会按进程时区解析致偏移）"。

**方式 B（确需 Unix 秒时，如走完整 API：其时间参数是 Unix 秒字符串）**：必须用系统命令/脚本换算。内置文档为**强制性**要求："涉及日期（时间）字符串与时间戳的相互转换时，务必调用系统命令或脚本代码等外部工具进行处理，以确保转换的绝对准确；换算**禁止依赖容器默认时区**（常为 UTC，会导致 8 小时偏移），必须显式指定目标时区。" 本机已实测（Windows PowerShell）：

```powershell
[DateTimeOffset]::Parse('2026-10-12T09:00:00+08:00').ToUnixTimeSeconds()
# → 1791766800（等于 UTC 2026-10-12T01:00:00Z）
```

本机实测锚点表（2026-09-30 实际运行结果）：

| 北京时间（+08:00） | Unix 秒 | 对应 UTC |
|---|---|---|
| 2026-10-12 00:00:00 | 1791734400 | 2026-10-11T16:00:00Z |
| 2026-10-12 09:00:00 | 1791766800 | 2026-10-12T01:00:00Z |
| 2026-10-16 18:00:00 | 1792144800 | 2026-10-16T10:00:00Z |
| 2026-10-16 23:59:59 | 1792166399 | 2026-10-16T15:59:59Z |

**坑清单**：

1. **裸时间串不带偏移**（如 `2026-10-12 09:00:00`）会按进程时区解析——容器/服务器默认常为 UTC，直接差 8 小时。要么一律带 `+08:00`，要么用 `--timezone`（注意：只有 `+suggestion` 与 `+room-find` 有 `--timezone` flag；`+freebusy`、`+create` **没有**，勿编造，其时区语义只能靠 start/end 的偏移表达）。
2. **Unix 时间戳本身无时区**：必须先显式按 +08:00 锚定再取 epoch；禁止把北京钟面数字当 UTC 直接转换。自检方法：北京时间 09:00 应等于同日 UTC 01:00（见上表）。
3. **夏令时**：Asia/Shanghai 无夏令时，+08:00 全年恒定，这 5 天内无 DST 切换风险；但换算工具仍须显式指定时区，不得依赖默认时区（文档红线）。
4. **日期核对**：2026-10-12 经 PowerShell `(Get-Date '2026-10-12').DayOfWeek` 实测为 Monday（周一）、2026-10-16 为 Friday（周五），与任务给定一致。

---

## 7. 本机验证记录（诚实声明）

**已实际执行（2026-09-30，windev-01）**：

- `lark-cli --help`；`lark-cli calendar --help`；`+freebusy`/`+suggestion`/`+room-find`/`+create` 各自的 `--help` —— 本清单全部 flag 逐一核对自这些真实输出；
- `lark-cli skills read lark-calendar` 及 references（`lark-calendar-schedule-meeting.md`、`-schedule-fuzzy-time.md`、`-suggestion.md`、`-room-find.md`、`-create.md`）—— §1/§2/§3 的规则引用皆出自这些文档原文；
- `lark-cli doctor` → `cli_version: pass (1.0.97, up to date)`，`config_file: fail (not configured)`；
- `lark-cli whoami` → `{"ok":false,"error":{"subtype":"not_configured"}}`（exit 3）；
- §6 的 PowerShell 时间换算与星期核对（上表为真实运行结果）；
- `+suggestion` / `+room-find` / `+create` 各一次 `--dry-run`：命令行参数解析通过（未报 unknown flag），但均止步于 `not_configured`，未能生成请求预览（dry-run 在本版本也要求已配置认证）。

**未执行**：真实的 `+freebusy` / `+suggestion` / `+room-find` / `+create` —— 本机 CLI 未配置认证无法发起，且任务提供的 open_id 为样例占位。因此 §1、§2、§4 的返回值以占位符交付，在已认证环境执行后回填。

**合规**：未读取 `skillfactory/` 目录下任何文件；本目录为本次新建，OUT.md 为该目录下唯一产物。
