# 需求池：2026 年 9 月未完结（待处理/处理中）需求导出 + 负责人 Top 3 —— 可直接执行命令清单

- 数据源：飞书多维表格 `K2qbA1bC3dE4fGh`，数据表 `tblReq9Mon`（约 4600 条；字段：需求标题/状态/负责人/提交时间/预估工时）
- 工具：`lark-cli`（官方 CLI，仓库 [larksuite/cli](https://github.com/larksuite/cli)，npm 包 `@larksuite/cli`，已安装并已认证）
- 目标文件：`./sep-open-reqs.ndjson`（仅含 需求标题、负责人、提交时间 三字段的 NDJSON）
- 运行环境二选一：**Git Bash / Linux / macOS**（用 A 组命令）或 **Windows PowerShell**（用 B 组命令）；统计步骤两个环境通用（Python 3）
- 诚实声明：本清单在编写机上**没有** lark-cli、无该 Base 访问权，导出命令未对真实飞书执行过；但每条命令与 flag 均逐条核对自官方仓库源码与文档（依据见附录 A），分页循环、合并、统计全链路已在本地用 mock 数据**实测跑通**（证据见附录 B）。**未验证的内容不含在本清单内**（如 jq 统计一行版，因编写机无 jq 无法验证，已舍弃）。

---

## 第 0 步（可选）：确认登录态

```bash
lark-cli auth status
```
理由：后续全部走 `base:record:read`、`base:field:read` 权限，先确认认证有效，避免循环中途 401。

## 第 1 步：字段预检（确认字段名一字不差）

```bash
lark-cli base +field-list --base-token K2qbA1bC3dE4fGh --table-id tblReq9Mon
```
理由：`--filter-json` 与 `--field-id` 均按「字段名或字段 ID」精确匹配，先确认「需求标题 / 状态 / 负责人 / 提交时间」的真实名称与「状态」确为单选，避免拼错导致过滤恒空。（依据：`shortcuts/base/field_list.go:14`，`Command: "+field-list"`；官方 Base 技能文档亦建议「先用 +field-list / +record-list 确认，再构造条件」）

## 第 2 步：把筛选条件写入 `sep-filter.json`（两环境等价，二选一）

筛选 JSON（2026-09-01 00:00:00 ≤ 提交时间 < 2026-10-01 00:00:00，且状态 ∈ {待处理, 处理中}）：

```json
{"logic":"and","conditions":[["提交时间",">","ExactDate(2026-08-31 23:59:59.999)"],["提交时间","<","ExactDate(2026-10-01 00:00:00)"],["状态","intersects",["待处理","处理中"]]]}
```

写法依据（官方 filter SSOT `skills/lark-base/references/lark-base-filter-condition.md`，该文档第 3 节明确其适用范围包含 `+record-list --filter-json`，且第 2 节标题即「单表谓词下推」，即**服务端过滤**）：
- 月份范围官方定式（原文示例）：日期不支持 `>=`，下界用「`>` 前一天最后一毫秒」表达含当天的下界；上界用「`<` 次月 1 日零点」→ 故为 `> ExactDate(2026-08-31 23:59:59.999)` 且 `< ExactDate(2026-10-01 00:00:00)`；
- 单选集合命中任一选项用 `intersects` 数组（`["状态","intersects",["待处理","处理中"]]`）；
- `ExactDate(...)` 按 Base 时区匹配当天/时刻。

**A（bash）**

```bash
cat > sep-filter.json <<'EOF'
{"logic":"and","conditions":[["提交时间",">","ExactDate(2026-08-31 23:59:59.999)"],["提交时间","<","ExactDate(2026-10-01 00:00:00)"],["状态","intersects",["待处理","处理中"]]]}
EOF
```
理由：`--filter-json` 支持 `@文件` 引用（flag 描述原文 "filter JSON object or @file"，官方示例即 `--filter-json @filter.json`），落盘引用可完全规避引号转义问题。

**B（Windows PowerShell）**

```powershell
$filter = @'
{"logic":"and","conditions":[["提交时间",">","ExactDate(2026-08-31 23:59:59.999)"],["提交时间","<","ExactDate(2026-10-01 00:00:00)"],["状态","intersects",["待处理","处理中"]]]}
'@
[IO.File]::WriteAllText("$PWD\sep-filter.json", $filter)
```
理由：用 .NET `WriteAllText` 写出的是**无 BOM 的 UTF-8**（本机实测文件头 `7b 22 6c`，JSON 可解析）；而 `Set-Content -Encoding UTF8`（PS 5.1）会带 BOM，Go 程序读 JSON 遇 BOM 会报错。

## 第 3 步：分页拉取全部命中记录（每页上限 2000，循环到取完）

> 关键事实（官方源码原文）：`+record-list` **每条命令只发一次请求、最多 2000 条**；"The public CLI reads one page only. Continue explicitly with the manifest's next_offset when has_more is true, **including when the API returns a short page**"（`shortcuts/base/record_export.go:175-177` 及 :28 的官方 Tip）。因此**必须**循环 `--offset` 直到 `has_more=false`，这就是 4600 条量级下「保证取全」的机制；CLI 无 `--page-all` 一类自动翻页可用于此命令，不要指望单条命令拉全。每次调用会在输出文件旁生成 `*.manifest.json`，内含 `records_count`、`has_more`、`next_offset`（`recordexport/manifest.go:58-61`）。

**A（bash）** —— 原样保存为 `loop.sh` 后 `bash loop.sh`，或直接粘贴执行：

```bash
mkdir -p pages && rm -f pages/page-*.ndjson pages/page-*.manifest.json
offset=0; i=0
while :; do
  pg=$(printf 'pages/page-%03d' "$i")
  lark-cli base +record-list \
    --base-token K2qbA1bC3dE4fGh \
    --table-id tblReq9Mon \
    --field-id 需求标题 --field-id 负责人 --field-id 提交时间 \
    --format ndjson --limit 2000 --offset "$offset" --overwrite \
    --filter-json @sep-filter.json \
    --output "${pg}.ndjson" || exit 1
  has_more=$(python -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1],encoding='utf-8'))['has_more']))" "${pg}.manifest.json")
  [ "$has_more" = "true" ] || break
  offset=$(python -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8'))['next_offset'])" "${pg}.manifest.json")
  i=$((i+1))
done
echo "共拉取 $((i+1)) 页"
```

各片段理由：
- 用 `base +record-list` 而非 `+record-search`：官方提示「For filter/sort-only reads, use base +record-list; it accepts --filter-json and --sort-json」——本任务纯过滤无关键词，`+record-search` 的 flag 模式强制要求 `--keyword`（`record_query.go:23`、`record_search.go:24`）。
- `--field-id 需求标题 --field-id 负责人 --field-id 提交时间`：服务端投影，导出文件天生只含这 3 个字段（`--field-id` 可重复，接受字段名；官方分析示例同款写法）。
- `--format ndjson --limit 2000`：ndjson 模式单页上限即 2000（`maxNDJSONRecordReadLimit`，范围 1–2000），页越大请求次数越少；ndjson 是该命令默认格式，此处显式写出以防歧义。
- `--offset "$offset"` + 读 manifest 的 `has_more`/`next_offset` 决定续拉或停止：官方唯一指定的取全方式。
- `--overwrite`：重复运行时允许覆盖同名分页产物（不带它时输出文件已存在会直接报错，源码 `ensureRecordExportTargets`）。
- `--output pages/page-%03d.ndjson`：每页独立文件名（`--output` 必须以 `.ndjson` 结尾，且默认拒绝覆盖已存在文件），从 0 开始编号便于合并与断点排查。
- `|| exit 1`：任何一页失败立即停，绝不带着缺页的数据往下统计。

**B（Windows PowerShell）** —— 保存为 `loop.ps1` 后 `powershell -NoProfile -ExecutionPolicy Bypass -File .\loop.ps1`：

```powershell
New-Item -ItemType Directory -Force -Path pages | Out-Null
Remove-Item pages\* -ErrorAction SilentlyContinue
$offset = 0; $i = 0
while ($true) {
  $pg = 'pages/page-{0:d3}' -f $i
  lark-cli base +record-list `
    --base-token K2qbA1bC3dE4fGh `
    --table-id tblReq9Mon `
    --field-id 需求标题 --field-id 负责人 --field-id 提交时间 `
    --format ndjson --limit 2000 --offset $offset --overwrite `
    --filter-json '@sep-filter.json' `
    --output "$pg.ndjson"
  if ($LASTEXITCODE -ne 0) { throw "lark-cli 拉取第 $i 页失败" }
  $m = Get-Content "$pg.manifest.json" -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $m.has_more) { break }
  $offset = $m.next_offset
  $i++
}
Write-Host "共拉取 $($i + 1) 页"
```

与 A 逐条同义；两个 PowerShell 专属注意点（本机实测踩过）：
1. `'@sep-filter.json'` 必须带引号：不带引号的 `@` 开头 token 可能被 PowerShell 当作 splatting 解析；
2. 含中文的 `.ps1` 必须存成 **UTF-8 with BOM**（Windows PowerShell 5.1 对无 BOM 文件按 ANSI 解析，中文会乱码并吞掉引号导致语法错误——实测复现过）。若用 PowerShell 7（pwsh）则默认 UTF-8 无此问题。

## 第 4 步：合并分页文件为 `./sep-open-reqs.ndjson` 并做完整性校验

保存为 `merge_pages.py`（Python 3，无第三方依赖），然后运行 `python merge_pages.py`（环境里命令叫 `python3` 就用 `python3`）：

```python
import glob
import json

files = sorted(glob.glob('pages/page-*.ndjson'))
n = 0
with open('sep-open-reqs.ndjson', 'wb') as out:
    for p in files:
        data = open(p, 'rb').read()
        out.write(data)
        n += sum(1 for line in data.splitlines() if line.strip())

manifest_total = 0
for p in sorted(glob.glob('pages/page-*.manifest.json')):
    manifest_total += json.load(open(p, encoding='utf-8'))['records_count']

print(f'ndjson 分页文件数: {len(files)}')
print(f'合并后记录数: {n}')
print(f'manifest records_count 合计: {manifest_total}')
print('一致性校验:', 'OK' if n == manifest_total and n > 0 else 'MISMATCH，请检查')
```

理由：ndjson 每行就是一个扁平对象 `{列名: 值}`（导出器源码 `recordexport/ndjson.go:24-27`），按页序二进制拼接即得全量文件；用各页 manifest 的 `records_count` 之和与合并行数互验，任何一页丢失/重复都会立刻暴露为 MISMATCH。按文件名排序拼接与 `--offset` 递增次序一致，不会乱序。

## 第 5 步：统计各负责人未完结条数 Top 3

保存为 `count_top3.py`，然后运行 `python count_top3.py`：

```python
import json
from collections import Counter

counts = Counter()
with open('sep-open-reqs.ndjson', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        owner = json.loads(line).get('负责人')
        if isinstance(owner, list):  # 防御：若负责人为多值字段会导出为数组
            owner = '、'.join(map(str, owner)) if owner else '(空)'
        elif owner is None or owner == '':
            owner = '(空)'
        counts[owner] += 1

total = sum(counts.values())
print(f'未完结（待处理/处理中）记录总数: {total}')
print('各负责人未完结条数 Top 3:')
for owner, n in counts.most_common(3):
    print(f'  {owner}: {n}')
```

理由：导出文件已经是「9 月 + 待处理/处理中」的交集（服务端已过滤），所以文件内按 `负责人` 计数即未完结条数；对 owner 做了「数组/空值」防御以兼容字段实际导出形态；`most_common(3)` 输出数量前 3 名，并列时按出现先后。统计纯本地完成，不写回飞书。

## 预期输出形态

```
共拉取 3 页                      # 命中量 ≤2000 时为 1 页，≤4000 时为 2 页，依此类推
ndjson 分页文件数: 3
合并后记录数: <命中条数>
manifest records_count 合计: <命中条数>
一致性校验: OK
未完结（待处理/处理中）记录总数: <命中条数>
各负责人未完结条数 Top 3:
  <负责人A>: <n1>
  <负责人B>: <n2>
  <负责人C>: <n3>
```

---

## 取全保证小结（为什么这套方案不会漏）

1. **服务端过滤**：`--filter-json` 走官方「单表谓词下推」，日期区间与状态过滤在飞书侧完成，导出的就是命中全集，无需本地二次筛选再担心本地时区/格式差异。
2. **翻页直到穷尽**：每条命令单页 ≤2000 条（官方硬限制），循环读 manifest 的 `has_more`/`next_offset`，官方源码明确短页（返回条数 < limit）也继续用 next_offset 续拉；约 4600 条全表、9 月未完结子集无论多大都会被循环覆盖。
3. **数量互验**：各页 `records_count` 合计 = 合并文件行数（merge 脚本内置校验），少一页即报 MISMATCH。
4. **幂等可重跑**：分页文件按序号命名 + `--overwrite`，任一页失败立即 `exit`/`throw`，修复后重跑不产生脏数据。

## 附录 A：命令/flag 依据（全部核对自官方仓库 larksuite/cli，main 分支）

| 清单中的用法 | 依据（仓库内文件与位置） |
|---|---|
| `base +record-list`、`base +field-list` 命令形态 | `shortcuts/base/record_list.go:15`、`shortcuts/base/field_list.go:14`（`Service:"base"`, `Command:"+record-list"/"+field-list"`） |
| `--base-token`、`--table-id`（ID 须以 tbl 开头或用表名） | `shortcuts/base/base_command_common.go:12-18` |
| `--field-id` 可重复、接受字段名（投影） | `record_list.go:23`、`record_ops.go:425-431`、`base_command_common.go:20-22`；官方示例 `record_list.go:39-40` |
| `--filter-json`（对象或 `@file`，视图同款 tuple 结构） | `record_query.go:26-32`、`record_search.go:45`、SSOT 文档 `lark-base-filter-condition.md` §0/§2/§3 |
| 月份范围写法 `> ExactDate(前一日 23:59:59.999)` + `< ExactDate(次日零点)` | `lark-base-filter-condition.md` §2 示例 64–65 行（原文注明「日期不支持 >=」） |
| 单选 `intersects [选项数组]` | `lark-base-filter-condition.md` §4 select 节 |
| `--format ndjson`（读命令默认）、`--limit` 1–2000（ndjson 默认 2000）、`--offset` | `record_list.go:29-31`、`record_list.go:82-89`、`record_export.go:26-27` |
| 单命令=单页、须按 manifest `next_offset` 续拉（含短页） | `record_export.go:28`（官方 Tip 原文）、`record_export.go:175-177`（源码注释原文） |
| manifest 含 `records_count`/`has_more`/`next_offset`，`next_offset = offset + 本页条数` | `recordexport/manifest.go:58-61, 117-120` |
| `--output` 须以 `.ndjson` 结尾；已存在须 `--overwrite` | `record_export.go:138-143`、`record_export.go:328-346` |
| ndjson 每行 = `{列名: 值}` 扁平对象 | `recordexport/ndjson.go:14-33` |
| 纯过滤读取选 `+record-list` 而非 `+record-search` | `record_query.go:23`（官方 hint 原文） |
| `lark-cli auth status` | 官方 README「Authentication」节（`auth status` 在列） |

## 附录 B：本机验证记录（2026-09-30 实测）

编写机（Windows，Git Bash + Python 3.12）未装 lark-cli，故：
- **导出命令本体**：无法对真实 Base 执行——按附录 A 核对到 flag 级；
- **循环/合并/统计全链路**：用 mock `lark-cli`（按官方单页行为：读 `--offset/--limit/--output`，写 ndjson + 含 `has_more/next_offset/records_count` 的 manifest）+ 4601 行合成数据实测：
  - bash 版 `loop.sh`：3 页（2000+2000+601），短页正确终止，`共拉取 3 页`；
  - PowerShell 版 `loop.ps1`（UTF-8 BOM 保存）：同样 3 页、exit 0；并实测确认两个 PS 坑——`.ps1` 无 BOM 时中文乱码导致解析失败（已写入第 3 步注意事项）、`[IO.File]::WriteAllText` 产出的 filter 文件无 BOM 且 JSON 可解析；
  - `merge_pages.py`：`合并后记录数 4601 = manifest 合计 4601，一致性校验 OK`；
  - `count_top3.py`：Top3 = `张三: 1500 / 李四: 1200 / 王五: 900`，与独立一次性 Counter 核对结果完全一致（合成数据即按此构造）。
