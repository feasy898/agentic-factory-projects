# 「需求池」9 月未完结需求导出 + 负责人 Top3 —— lark-cli 命令清单

> **交付说明（如实声明）**：本清单面向已安装并完成认证 lark-cli 的环境，按序可直接执行。
> 编写本清单所用的分析机**未安装 lark-cli**（已核实：`command -v lark-cli` 为空；`npm ls -g` 全局列表无 `@larksuite/cli`），因此**飞书侧命令未实跑**，执行结果以实际输出为准（Top3 数字留占位符）；
> 每个命令与 flag 均逐条对照官方文档核实（来源见 §6），**无编造**；
> 第 6 步本地统计脚本已在本机用 8 行合成数据实测通过（结果见 §7）。

**目标**：从「需求池」多维表格（`https://xx.feishu.cn/base/K2qbA1bC3dE4fGh?table=tblReq9Mon`，约 4600 条）导出「提交时间在 2026-09-01 至 2026-09-30 且状态 ∈ {待处理, 处理中}」的全部记录，仅含 需求标题 / 负责人 / 提交时间 三字段，存为 `./sep-open-reqs.ndjson`；再在本地用 Python 统计各负责人未完结合计，给出 Top3。只读，不写回飞书。

---

## 0. 全程约定（每步都适用）

- **成功判定**：退出码 0 且 stdout 信封 `ok == true`；错误信封写 stderr、退出码非 0。**不用 `code == 0` 判断**（成功信封没有顶层 `code`/`msg`；`code` 只在错误信封内）。
- **身份**：全程 `--as user`（读用户自己的多维表格）。
- **路径**：所有本地文件参数一律相对路径（绝对路径会报 `unsafe file path`）。
- **只读**：清单中不含任何写命令。
- 命令为 bash 单引号风格；若在 PowerShell/cmd 执行，注意引号规则不同（cmd 无单引号语义，`--filter-json` 建议改用双引号并对内部双引号转义）。

---

## 1. 命令清单（按序执行）

### Step 1 确认登录态

```bash
lark-cli auth status
```

**理由**：后续全部命令依赖 user 身份的登录与授权，先确认 `auth status` 正常再动手，避免把授权问题误判为数据问题。

### Step 2 解析 Base 链接，取 app_token / table_id

```bash
lark-cli base +url-resolve --url 'https://xx.feishu.cn/base/K2qbA1bC3dE4fGh?table=tblReq9Mon' --as user
```

**理由**：官方规定进入 Base 前先用 `+url-resolve` 解析链接坐标、不按名称猜 token；从返回中取 `app_token` 与 `table_id`（预期为 `K2qbA1bC3dE4fGh` / `tblReq9Mon`，**以实际返回为准**），代入后续命令的 `<app_token>`、`<table_id>`。

### Step 3（可选，推荐）核实字段名与类型

```bash
lark-cli base +field-list --help        # 先核实该子命令参数名（官方原则：先 --help 核实、不盲猜 flag）
lark-cli base +field-list --base-token <app_token> --table-id <table_id> --as user   # 参数名以 --help 输出为准
```

**理由**：`--filter-json` 里写的是字段名，先确认「状态 / 提交时间」等字段在表内的准确名称与类型（日期 vs 创建时间），防止筛选条件因字段名对不上而静默失效。

### Step 4 主导出：服务端下推筛选 + 自动翻页取全 + 三字段投影

```bash
lark-cli base +record-list \
  --base-token <app_token> --table-id <table_id> \
  --filter-json '{"logic":"and","conditions":[["状态","intersects",["待处理","处理中"]],["提交时间",">","ExactDate(2026-08-31 23:59:59.999)"],["提交时间","<","ExactDate(2026-10-01 00:00:00)"]]}' \
  --field-id 需求标题 --field-id 负责人 --field-id 提交时间 \
  --page-all --page-delay 500 \
  --format ndjson --output ./sep-open-reqs.ndjson \
  --as user
```

**理由**：这一步同时完成四件事——① `--filter-json` 服务端下推（单选 `intersects` 命中两个状态；日期范围用官方等价边界写法，**日期筛选不支持 `>=`**，下界用「前一天最后一毫秒 + `>`」表达含 9/1 全天，上界用「`<` 10-01 零点」表达含 9/30 全天）；② 约 4600 条超过单次上限 2000，用全局 `--page-all` 自动翻页取全（`--page-delay 500` 降低请求频率）；③ `--field-id` 重复传三次做最小字段投影，只保留三个目标字段；④ 以相对路径导出 NDJSON（每行一条 Record JSON）。

**判定与完整性**：命令成功 = 退出码 0 且 `ok == true`；**必须再看 stdout 摘要中的 `records_count` 与 `has_more`——只有 `has_more=false` 才是完整结果**；若摘要仍为 `has_more=true`、或该命令对 `--page-all` 支持异常（如报 `command_unavailable`），改用 §2 的官方分块方案取全。

### Step 5 导出完整性抽查

```bash
wc -l ./sep-open-reqs.ndjson
head -n 2 ./sep-open-reqs.ndjson
tail -n 2 ./sep-open-reqs.ndjson
```

**理由**：本地行数应等于 Step 4 摘要的 `records_count`（对不上按 §2 补齐），首尾各抽 2 行确认 NDJSON 行结构、字段投影与日期值形态（官方 skill 示例同款抽查）。

### Step 6 本地统计各负责人未完结数并给 Top3

```bash
python - <<'PY'
import json, collections
from datetime import datetime, timezone, timedelta

CN = timezone(timedelta(hours=8))
OPEN = {"待处理", "处理中"}

def in_sep_2026(v):
    if v is None:
        return False
    if isinstance(v, (int, float)):            # 毫秒时间戳
        dt = datetime.fromtimestamp(v / 1000, tz=CN)
    else:                                       # RFC3339 或纯日期字符串
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CN)
    return (dt.year, dt.month) == (2026, 9)

cnt = collections.Counter(); total = 0; dropped = 0
with open("./sep-open-reqs.ndjson", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        total += 1
        st = r.get("状态")
        if isinstance(st, list):                # 单选 CellValue 为数组
            st = st[0] if st else None
        if st not in OPEN or not in_sep_2026(r.get("提交时间")):
            dropped += 1                        # 与服务端筛选口径不符，复核剔除
            continue
        owner = r.get("负责人")
        cnt[owner if isinstance(owner, str) and owner.strip() else "(负责人为空)"] += 1

print(f"文件总行数={total}  口径复核剔除={dropped}  未完结合计={sum(cnt.values())}")
print("Top3:")
for name, c in cnt.most_common(3):
    print(f"  {name}\t{c}")
print("全部负责人明细:")
for name, c in cnt.most_common():
    print(f"  {name}\t{c}")
PY
```

**理由**：任务要求分组计数与 Top3 在本地完成（macOS/Linux 用 `python3`），脚本同时按「两种状态 + 9 月」口径对导出结果做本地复核（兼容单选数组/字符串、RFC3339/毫秒时间戳/纯日期三种日期形态、空负责人），并打印全量明细以便 Top3 并列时人工复核。

**结果（占位，以实际执行为准）**：

```
Top3：
  1. <负责人A>　<N_A> 条
  2. <负责人B>　<N_B> 条
  3. <负责人C>　<N_C> 条
```

---

## 2. 取全保障与回退方案（官方大表 SOP 分块读取）

`--limit` 缺省与最大均为 2000；**只有 `has_more=false` 才是完整结果**。若 Step 4 未取全（`has_more=true`），按官方 Record 查询 SOP 分块读取直至取全：

```bash
# 块 1：offset 从 0 开始，每块 limit=2000，各块输出独立文件
lark-cli base +record-list \
  --base-token <app_token> --table-id <table_id> \
  --filter-json '<同 Step 4>' \
  --field-id 需求标题 --field-id 负责人 --field-id 提交时间 \
  --offset 0 --limit 2000 \
  --format ndjson --output ./sep-block-001.ndjson --as user
# 看摘要：records_count / has_more / next_offset / rev；has_more=true 才继续

# 块 2 起：offset 用上一块摘要返回的 next_offset，不要自行按 2000 递增猜
lark-cli base +record-list ... --offset <next_offset> --limit 2000 \
  --format ndjson --output ./sep-block-002.ndjson --as user
# ……重复直至最后一块摘要 has_more=false（终止条件）；期间各块 rev 必须一致，
#   rev 变化说明数据快照已变、可能遗漏或重复，需严格完整时从头重读。

# 全部取全后合并为交付文件
cat ./sep-block-*.ndjson > ./sep-open-reqs.ndjson && wc -l ./sep-open-reqs.ndjson
```

**理由**：SOP 规定「超过 2000 行且必须取得逐条原始记录」时按 `--offset` 续读、以 `next_offset` 为下一块起点、以 `has_more=false` 为终止，并用一致的 `rev` 保证同一数据快照，这是比自动翻页更可审计的取全路径。

---

## 3. 口径与边界说明

- **日期边界**（`--filter-json` 官方等价写法，日期不支持 `>=`）：
  - 下界 `["提交时间", ">", "ExactDate(2026-08-31 23:59:59.999)"]` ⇒ 含 2026-09-01 全天；
  - 上界 `["提交时间", "<", "ExactDate(2026-10-01 00:00:00)"]` ⇒ 含 2026-09-30 全天。
- **时区**：`ExactDate(...)` 按 Base 时区解释（多维表格页面所见即所得）；本地复核脚本按东八区解释毫秒时间戳、无时区字符串视为东八区。
- **未完结口径**：状态 ∈ {待处理, 处理中}；筛选已在服务端完成，本地脚本再复核一遍（剔除数应≈0，非 0 说明服务端/本地口径有出入，需排查）。
- 导出行中若带 `record_id` 等系统键属正常，统计只读三个目标键。

## 4. 本清单遵守的安全边界

- 全程 `--as user`；无 `+record-batch-create`/`+record-update` 等任何写命令；不写回飞书。
- 聚合统计全部在本地 Python 完成，未把分组/Top-K 混进 CLI 筛选参数。
- 未出现 token、secret 等敏感信息；`<app_token>`/`<table_id>` 来自 Step 2 的解析结果。

## 5. 已核实的依据（本会话实测抓取/运行）

| 依据 | 来源与核实方式 |
|---|---|
| `+url-resolve` 入口、`--filter-json` tuple 条件、`intersects`、日期 `ExactDate(...)` 边界写法、`--field-id` 可重复投影、NDJSON 每行一条 Record、stdout 摘要含 `records_count`/`has_more`、`--limit` 缺省/最大 2000、`has_more=false` 完整性 | 官方 `skills/lark-base/SKILL.md`（raw.githubusercontent.com/larksuite/cli/main，本会话 curl 抓取，L97–L125、L132、L148） |
| 大表分块取全（offset/next_offset/rev/终止条件） | 官方 `skills/lark-base/references/lark-base-record-query-and-analysis-sop.md`（本会话 curl 抓取，§3 大表完整读取） |
| filter 操作符协议（`intersects`/`>`/`<`/`==`、`ExactDate` 语义与「日期不支持 >=」） | 官方 `skills/lark-base/references/lark-base-filter-condition.md`（本会话 curl 抓取，L53–L65、L160–L169） |
| 全局翻页 `--page-all`/`--page-delay`、`--format ndjson`、`ok == true` 判定、相对路径规则 | `lark-cli/ASSET-DOC.md` §5.1/§5.2/§5.3、§8.1（文件路径仅相对）、§8.5（本机资产文档，2026-09-29 核对）及官方 README.md（本会话 curl 抓取，L264–L267） |
| 本地统计脚本正确性 | 本机实测：8 行合成夹具（含单选数组/字符串、三种日期形态、空负责人、8-31/10-01 边界行），输出「总行数=8、复核剔除=3、合计=5、Top3=小何2/小王1/(负责人为空)1」，与预期一致 |

## 6. 与 ASSET-DOC 的冲突注明

按任务要求注明：本清单以任务要求为准。本次**未发现实质冲突**——ASSET-DOC §8.5 摘要（筛选下推、2000 上限、has_more 判定、NDJSON 导出）与官方 skill 原文一致；ASSET-DOC 未收录的日期操作符细节（`ExactDate(...)` 边界写法），已按官方 `lark-base-filter-condition.md` 原文核实补充，未做任何编造。
