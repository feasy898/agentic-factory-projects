# 需求池 · 2026-09 未完结需求导出与负责人 Top3 —— 执行命令清单

## 0. 目标与口径（先读）

| 项 | 值 |
|---|---|
| 数据源 | 多维表格 `https://xx.feishu.cn/base/K2qbA1bC3dE4fGh?table=tblReq9Mon`（约 4600 条） |
| 筛选 | 状态 ∈ {待处理, 处理中} 且 提交时间 ∈ [2026-09-01, 2026-09-30]（含两端，按 Base 时区日历日） |
| 导出字段 | 需求标题、负责人、提交时间（三个字段；分块拉取时系统列 `record_id` 仅用于去重，落盘前剔除） |
| 产物 | `./sep-open-reqs.ndjson`（本地 NDJSON）+ 负责人未完结条数 Top3 |
| 边界 | 统计全部在本地 jq/Python 完成，不写回飞书 |

**取全机制**：官方 `base +record-list` 的 NDJSON 单次上限 **2000 条**（`--help` 原文：`range 1-200, or 1-2000 for ndjson`），表约 4600 条，必须按官方 SOP（`skills/lark-base/references/lark-base-record-query-and-analysis-sop.md` §3）用 `--offset` 逐块翻页，以**最后一块 `manifest.has_more=false`** 作为取全终止条件；各块 `rev`、`query_context` 必须一致（不一致=快照漂移，全部重读）。注意：该命令**不支持** `--page-all`（实测报 `unknown flag`，见文末注明）。

**本机实况（诚实声明）**：本机缓存的 lark-cli 1.0.97 可运行，但 `lark-cli auth status` 实测返回 `{"ok":false,"type":"config","subtype":"not_configured"}`（退出码 3）——本机 CLI **未配置登录**，故步骤 1–3 的远端调用未在本机执行；清单中每条命令/flag 均已用该二进制的 `--help`、官方仓库源码（`shortcuts/base/record_export.go`、`recordexport/manifest.go`）与官方 SOP/参考文档逐一核验，本地处理脚本（步骤 4–5）已在本机用合成数据全量测试通过（含 4 项完整性守卫的负向用例）。在已认证环境按序执行即可。

---

## 1. 命令清单（按序执行）

### 步骤 0 · 确认登录态

```bash
lark-cli auth status
```

**理由**：拉数据前确认已登录且 scope 就绪——按官方错误契约，仅当退出码 0 且 `ok=true` 才算通过；若报 `not_configured`/`authorization`，先按官方流程 `lark-cli config init --new` / `lark-cli auth login --recommend` 补认证（后台运行、取授权 URL 交用户浏览器完成），再回到本步。

### 步骤 1 · 解析 Base URL，拿到权威坐标

```bash
lark-cli base +url-resolve --url 'https://xx.feishu.cn/base/K2qbA1bC3dE4fGh?table=tblReq9Mon' --as user
```

**理由**：官方要求进入 Base 前先解析 URL 获取 `app_token`/`table_id`，不凭链接手工猜测拼写；后续命令的 `--base-token`/`--table-id` 以本步返回为准（下文先按 URL 中的 `K2qbA1bC3dE4fGh` / `tblReq9Mon` 书写）。

### 步骤 2 · 核对字段名（防“字段名不符被静默忽略”）

```bash
lark-cli base +field-list --base-token K2qbA1bC3dE4fGh --table-id tblReq9Mon --as user
```

**理由**：投影（`--field-id`）与筛选（`--filter-json`）都按字段**名称**匹配，名称不符时会被静默忽略并在 manifest 记为 `ignored_fields`——先核对「需求标题/状态/负责人/提交时间」与表内实际名称、类型一致（若有出入，以本步输出为准替换后续命令中的名称）。

### 步骤 3 · 分块拉取（状态 + 日期双条件下推，翻页取全）

在 **bash**（Git Bash / WSL1）中执行：

```bash
offset=0; i=0
while :; do
  chunk=$(printf "chunk-%03d" "$i")
  lark-cli base +record-list \
    --base-token K2qbA1bC3dE4fGh \
    --table-id tblReq9Mon \
    --as user \
    --filter-json '{"logic":"and","conditions":[["状态","intersects",["待处理","处理中"]],["提交时间",">","ExactDate(2026-08-31 23:59:59.999)"],["提交时间","<","ExactDate(2026-10-01 00:00:00)"]]}' \
    --field-id 需求标题 --field-id 负责人 --field-id 提交时间 \
    --format ndjson --limit 2000 --offset "$offset" \
    --output "./$chunk.ndjson" --overwrite || exit 1
  read -r has_more next_offset <<< "$(python -c "import json;m=json.load(open('./$chunk.manifest.json',encoding='utf-8'));print(m['has_more'],m.get('next_offset'))")"
  [ "$has_more" = "True" ] || break
  offset=$next_offset; i=$((i+1))
done
```

**理由**：筛选语法取自官方 Filter 条件 SSOT——单选用选项名数组相交 `["状态","intersects",["待处理","处理中"]]`；日期**不支持 `>=`**，官方规定下界用 `>` 前一天最后一毫秒、上界用 `<` 次月一日零点的 `ExactDate(...)` 写法，两句合起来精确覆盖 2026-09-01 至 2026-09-30；`--field-id` 为可重复 flag（`stringArray`），服务端只投影三个目标字段以减小传输；`--limit 2000` 取单次上限、每块落盘 `chunk-NNN.ndjson` 并生成同名 `chunk-NNN.manifest.json`（源码 `record_export.go:309`），循环读取 manifest 的 `has_more`/`next_offset` 直到 `false`，保证 4600 条量级也能取全。

> 手工展开等价式（非 bash 环境参考）：先 `--offset 0` 拉 `chunk-000`，读 `chunk-000.manifest.json` 的 `has_more`/`next_offset`；`has_more=true` 就用返回的 `next_offset`（第 2 块为 2000，第 3 块为 4000……）继续拉下一块，直到某块 `has_more=false`。约 4600 条的表最多 3 块。

### 步骤 4 · 合并校验 + 落盘 `./sep-open-reqs.ndjson` + 负责人 Top3

把附录 A 的脚本存为 `sep_merge_stats.py`（与分块文件同目录），然后：

```bash
python sep_merge_stats.py ./chunk ./sep-open-reqs.ndjson
```

**理由**：任务要求统计在本地完成——脚本先做完整性校验（每块 `records_count` 与实际行数一致、`ignored_fields` 为空、各块 `rev`/`query_context` 一致、最后一块 `has_more=false`，任一不满足立即报错拒绝出数），再按 `record_id` 去重、把 `提交时间`（NDJSON 中为带时区 RFC3339 串）换算到 manifest `timezone` 的本地日历日复核落在 2026-09-01..09-30（兜住服务端筛选的时区边界），剔除 `record_id` 后仅保留三个字段落盘，并当场输出负责人未完结条数 Top3。

### 步骤 5 · 交付前独立复核（可选但建议）

```bash
python -c "import json;rows=[json.loads(l) for l in open('./sep-open-reqs.ndjson',encoding='utf-8') if l.strip()];print('rows=',len(rows));print('keys_ok=',all(set(r)=={'需求标题','负责人','提交时间'} for r in rows));import collections;c=collections.Counter(r['负责人'] for r in rows if r['负责人']);print(c.most_common(3))"
```

**理由**：用另一条独立路径复核落盘行数、确认每行恰好只有三个字段、且 Top3 与步骤 4 一致（本机无 jq，故统一用 Python；两者均为纯本地操作，不写回飞书）。

---

## 2. 结果口径说明（Top3 怎么读）

- **范围**：仅表 `tblReq9Mon`（Base `K2qbA1bC3dE4fGh`）整表范围（未用 View），过滤条件=步骤 3 的状态 ∩ 日期双条件；「未完结条数」即该导出集内按 `负责人` 分组的行数（导出已只含待处理/处理中，故两者同口径）。
- **完整性判定**：只有脚本四项校验全过、且最后一块 `has_more=false`，结果才可作全局结论；导出期间若 `rev` 变化，脚本会拒绝出数并要求全部重读（防遗漏/重复）。
- **时间语义**：按 Base 本地日历日（manifest `timezone`）判断「9 月提交」，与用户在飞书界面上看到的日期一致，不先转 UTC 再切月。
- **空值与并列**：`负责人` 为空的记录保留在 ndjson 中但**不参与排名**（脚本单独输出「另计」）；`提交时间` 为空的记录不计入（无法证明属于 9 月）；Top3 并列时按记录首次出现顺序取足 3 名。
- **产出位置**：`./sep-open-reqs.ndjson`（每行一个 JSON 对象，仅 `需求标题`/`负责人`/`提交时间` 三键，`ensure_ascii=False` 中文原样）；Top3 打印在步骤 4/5 的 stdout；全部结果只落本地，不写回飞书。

---

## 附录 A · `sep_merge_stats.py`（已在本机用合成 fixtures 测试通过）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并 base +record-list 的分块 NDJSON 导出，校验完整性并统计负责人 Top3。

用法: python sep_merge_stats.py [分块前缀] [输出文件]
默认: python sep_merge_stats.py ./chunk ./sep-open-reqs.ndjson
读取 ./chunk-000.ndjson / ./chunk-000.manifest.json ... 直到某块 manifest.has_more=false。
输出 ndjson 每行仅含 需求标题 / 负责人 / 提交时间 三个字段。
"""
import glob
import json
import sys
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

PREFIX = sys.argv[1] if len(sys.argv) > 1 else "./chunk"
OUT = sys.argv[2] if len(sys.argv) > 2 else "./sep-open-reqs.ndjson"
FIELDS = ["需求标题", "负责人", "提交时间"]
LOW, HIGH = "2026-09-01", "2026-09-30"  # 含两端，按 manifest.timezone 的本地日历日

chunks = sorted(glob.glob(PREFIX + "-[0-9][0-9][0-9].ndjson"))
assert chunks, f"未找到分块文件: {PREFIX}-NNN.ndjson"

rev = None
qctx = None
tz = None
seen = set()
kept = []
warns = Counter()
total = 0

for path in chunks:
    mpath = path[: -len(".ndjson")] + ".manifest.json"
    with open(mpath, encoding="utf-8") as f:
        m = json.load(f)
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if ln.strip()]
    assert m["records_count"] == len(lines), (
        f"{path}: manifest.records_count={m['records_count']} != 实际 {len(lines)} 行"
    )
    assert not m.get("ignored_fields"), (
        f"{path}: ignored_fields={m['ignored_fields']}（投影字段名与表内字段不符，先核对 +field-list）"
    )
    if rev is None:
        rev, qctx, tz = m.get("rev"), m.get("query_context"), m.get("timezone") or "Asia/Shanghai"
    assert m.get("rev") == rev, f"{path}: rev 由 {rev} 变为 {m.get('rev')}，导出期间快照已变，须全部重读"
    assert json.dumps(m.get("query_context"), sort_keys=True) == json.dumps(qctx, sort_keys=True), (
        f"{path}: query_context 与首块不一致，读取范围漂移"
    )
    for ln in lines:
        total += 1
        row = json.loads(ln)
        rid = row.get("record_id")
        if rid in seen:
            warns["重复 record_id（保留首见，丢弃后续）"] += 1
            continue
        seen.add(rid)
        d = row.get("提交时间")
        if not d:
            warns["提交时间为空（丢弃）"] += 1
            continue
        day = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        if m.get("timezone"):
            day = day.astimezone(ZoneInfo(m["timezone"]))
        day = day.date().isoformat()
        if not (LOW <= day <= HIGH):
            warns[f"提交时间越界（{day}，丢弃）"] += 1
            continue
        kept.append({k: row.get(k) for k in FIELDS})

last = json.load(open(chunks[-1][: -len(".ndjson")] + ".manifest.json", encoding="utf-8"))
assert last["has_more"] is False, "最后一块 has_more=true，尚有未拉取数据：请按其 next_offset 续拉后再统计"

with open(OUT, "w", encoding="utf-8") as f:
    for row in kept:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

cnt = Counter(r["负责人"] if r["负责人"] else "(负责人为空)" for r in kept)
print(f"chunks={len(chunks)}  拉取总行数={total}  去重后={len(seen)}  "
      f"落盘={len(kept)} -> {OUT}")
print(f"rev={rev}  timezone={tz}")
for k, v in sorted(warns.items()):
    print(f"WARN {k}: {v}")
print("— 负责人未完结条数 Top3（口径：提交时间∈2026-09-01..09-30 且 状态∈{待处理,处理中}）—")
top = [(k, c) for k, c in cnt.most_common() if k != "(负责人为空)"][:3]
for name, c in top:
    print(f"{c}\t{name}")
if "(负责人为空)" in cnt:
    print(f"另计：负责人为空 {cnt['(负责人为空)']} 条（不参与排名）")
```

**脚本已验证的实测记录（本机 Python 3.12.10）**：

- 正向：2 块合成 fixtures（8 行：含跨块重复 `record_id`、08-31/10-01 越界行、空提交时间、空负责人）→ 输出 `chunks=2 拉取总行数=8 去重后=7 落盘=4`，落盘行恰好三键，Top3=`2 张三 / 1 李四`，空负责人另计 1。
- 负向（守卫逐项触发，均 exit 1 并给出可修复提示）：末块 `has_more=true` → “尚有未拉取数据”；`rev` 不一致 → “快照已变，须全部重读”；`records_count` 与行数不符 → 立即断言；`ignored_fields` 非空 → 提示先核对 `+field-list`。
- 循环原文用 stub lark-cli（模拟 2 页 API）跑通：恰好拉 2 块后按 `has_more=false` 停止，且步骤 4 脚本能直接消费其产物。

---

## 附注 · 能力资产说明与任务的冲突处理（按要求注明）

任务要求“说明与任务冲突时以任务为准”。实测发现两处资产文档（ASSET-DOC）与 CLI 实际行为的出入，均**以任务目标（取全、字段投影）为准**处理：

1. ASSET-DOC §5.3 列出全局分页 flag `--page-all / --page-limit / --page-delay`，但 `base +record-list` **实测不支持** `--page-all`（`lark-cli base +record-list ... --page-all --dry-run` 返回 `{"type":"validation","subtype":"invalid_argument","message":"unknown flag \"--page-all\" ..."}`）；该命令的官方 SOP 规定用 `--offset` + manifest `has_more/next_offset` 分块取全。本清单采用 SOP 方案。
2. ASSET-DOC §8.5 示例中 `--field-id` 以单值出现；实测 `--help` 显示其为 `stringArray`（“repeat to project only needed fields”），故用三次 `--field-id` 完成三字段服务端投影。

其余内容（安装/认证、JSON 输出契约 `ok==true` 判定、退出码表、文件路径仅接受相对路径、`+url-resolve` 进入前解析等）与 ASSET-DOC 一致，已照其执行。
