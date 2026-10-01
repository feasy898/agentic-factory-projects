# 需求池多维表格：2026-09 未完结需求导出 + 负责人 Top3 —— 可按序执行命令清单

**任务口径**：从「需求池」Base（`base_token=K2qbA1bC3dE4fGh`，`table_id=tblReq9Mon`，约 4600 条）导出 **提交时间 ∈ [2026-09-01, 2026-09-30] 且 状态 ∈ {待处理, 处理中}** 的全部记录，只保留 **需求标题 / 负责人 / 提交时间** 三字段，写入 `./sep-open-reqs.ndjson`；再本地统计各负责人未完结条数，给数量前 3 名。全程只读，不写回飞书。

**运行前提**：官方 lark-cli（npm 包 `@larksuite/cli`，本文全部 flag 逐字核实于 **v1.0.97** 真实二进制）已安装并认证；在 bash（Git Bash / macOS / Linux）中按序执行；`python`（3.x）在 PATH（本机无 jq，统计按任务允许的"jq/Python 二选一"选 Python）。

---

## Step 0. 确认登录态

```bash
lark-cli whoami
```

**理由**：`whoami`（risk: read）输出当前生效身份、应用、profile 与 token 状态，先确认认证有效，避免分页导出到一半因授权失败而中断。

> 若显示未认证：先 `lark-cli config init`（配置应用凭据），再 `lark-cli auth login --recommend`（登录）——官方 README 的标准两步。

## Step 1. 由链接解析 Base 坐标

```bash
lark-cli base +url-resolve --url 'https://xx.feishu.cn/base/K2qbA1bC3dE4fGh?table=tblReq9Mon' --as user
```

**理由**：内嵌 skill `lark-base` 要求"进入前必做：解析目标实体"，用 URL 解析核对 `base_token`/`table_id`（预期即 `K2qbA1bC3dE4fGh` / `tblReq9Mon`），避免凭记忆手填坐标出错。

## Step 2. 建分块暂存目录

```bash
mkdir -p .sep-chunks
```

**理由**：ndjson 模式单次最多返回 2000 条（`+record-list --help` 原文），4600 条量表必须分块，按官方 SOP 要求"每块输出到不同 artifact"，集中放块文件与其同名 `.manifest.json`。

## Step 3. 分页导出（循环至取全，过滤在服务端下推）

```bash
set -euo pipefail
i=1; offset=0
while :; do
  if [ "$i" -gt 50 ]; then echo "FATAL: 分块超过 50 次，疑似分页异常" >&2; exit 1; fi
  chunk=$(printf './.sep-chunks/chunk-%03d.ndjson' "$i")
  lark-cli base +record-list \
    --base-token K2qbA1bC3dE4fGh \
    --table-id tblReq9Mon \
    --as user \
    --filter-json '{"logic":"and","conditions":[["提交时间",">","ExactDate(2026-08-31 23:59:59.999)"],["提交时间","<","ExactDate(2026-10-01 00:00:00)"],["状态","intersects",["待处理","处理中"]]]}' \
    --field-id 需求标题 \
    --field-id 负责人 \
    --field-id 提交时间 \
    --sort-json '[{"field":"提交时间","desc":false},{"field":"需求标题","desc":false}]' \
    --offset "$offset" --limit 2000 \
    --format ndjson --output "$chunk" --overwrite
  read -r offset has_more <<< "$(python -c "import json,sys; m=json.load(open(sys.argv[1],encoding='utf-8')); print(m['next_offset'], m['has_more'])" "$chunk.manifest.json")"
  if [ "$has_more" != "True" ]; then break; fi
  i=$((i+1))
done
echo "DONE: 共 $i 块"
```

**理由**：`+record-list` 是官方 skill 指定的"结构化条件 + 排序"读取命令（`+record-search` 的帮助原文注明"For filter/sort-only reads, use +record-list"）；按 SOP §3 的大表完整读取协议——固定 filter/sort/投影，`--limit 2000` 打满单块上限，`has_more=true` 时**只用 manifest 返回的 `next_offset`** 续读，`has_more=false` 终止——保证超过单次上限也取全；过滤条件全部服务端下推（状态用 `intersects` 命中任一选项；日期字段**不支持 `>=`**，按 skill 原文下界用"前一天最后一毫秒 + `>`"表达含 9-01 当天、上界用"`<` ExactDate(2026-10-01 00:00:00)"表达含 9-30 当天）；`--field-id`×3 最小投影；`--sort-json` 固定排序保证 offset 分块顺序稳定；`--overwrite` 使重跑幂等；`set -euo pipefail` 保证任何一块失败立即中止而非静默缺数据；Base 读取按 skill 优先 `--as user`。

## Step 4. 合并分块 + 完整性校验 → `./sep-open-reqs.ndjson`

```bash
python - <<'PY'
import glob, json, sys

chunk_dir = sys.argv[1] if len(sys.argv) > 1 else './.sep-chunks'
chunks = sorted(glob.glob(chunk_dir + '/chunk-*.ndjson'))
assert chunks, '未找到任何分块文件'
manifests = [json.load(open(c + '.manifest.json', encoding='utf-8')) for c in chunks]

assert len({m.get('rev') for m in manifests}) == 1, \
    '读取期间 rev 变化，数据快照不一致：请删除 .sep-chunks 后重跑 Step 3'
assert len({json.dumps(m.get('query_context'), sort_keys=True, ensure_ascii=False)
            for m in manifests}) == 1, '各块 query_context 不一致'
assert manifests[-1].get('has_more') is False, '最后一块 has_more != false，数据不完整'

seen, out_lines = set(), []
for c, m in zip(chunks, manifests):
    n = 0
    for line in open(c, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        rid = r['record_id']
        assert rid not in seen, f'跨块重复 record_id：{rid}（offset 分块不稳定，请重跑 Step 3）'
        seen.add(rid)
        n += 1
        out_lines.append({'需求标题': r.get('需求标题'),
                          '负责人': r.get('负责人'),
                          '提交时间': r.get('提交时间')})
    assert n == m['records_count'], f'{c} 行数 {n} 与 manifest records_count {m["records_count"]} 不符'

total = sum(m['records_count'] for m in manifests)
assert total == len(out_lines), f'块记录总数 {total} 与合并行数 {len(out_lines)} 不符'

with open('./sep-open-reqs.ndjson', 'w', encoding='utf-8') as f:
    for r in out_lines:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print(f'OK: {len(chunks)} 块，共 {total} 条，已写入 ./sep-open-reqs.ndjson（仅 3 字段）')
PY
```

**理由**：把"取全"变成机械校验门——全块 `rev` 与 `query_context` 一致（SOP §3.3：rev 变化=快照变化，必须重读）、末块 `has_more=false`（SOP §3.4 终止条件）、逐块行数=manifest `records_count`、Σrecords_count=合并行数、`record_id`（NDJSON 每行自动携带的系统主键，SOP §5）无跨块重复——任一不过即报错退出，绝不带着不完整数据进入统计；同时裁剪为恰好 3 个业务字段（系统 `record_id` 在去重用完后丢弃，满足"只保留三字段"）。

## Step 5. 本地统计各负责人未完结条数，输出前 3 名

```bash
python - <<'PY'
import json
from collections import Counter

cnt = Counter()
for line in open('./sep-open-reqs.ndjson', encoding='utf-8'):
    line = line.strip()
    if not line:
        continue
    o = json.loads(line).get('负责人')
    if isinstance(o, list):
        o = o[0].get('name') if o and isinstance(o[0], dict) else None
    cnt[(o or '(空)')] += 1

for rank, (name, n) in enumerate(sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:3], 1):
    print(f'{rank}. {name}：{n} 条')
PY
```

**理由**：文件在 Step 3 已被服务端过滤为"9 月提交 ∧ 状态∈{待处理,处理中}"，本地按负责人计数即为未完结条数（任务要求本地 jq/Python 完成，不写回飞书）；按（条数降序、名称升序）排序使并列名次结果确定且条数直接可见。

---

## "取全"是如何保证的（针对"记录量超过单次拉取上限"）

1. **上限事实**：`+record-list --help` 原文——ndjson 模式 `--limit` "range 1-200, or **1-2000 for ndjson**"，"omitted limit uses 2000"；4600 条全量必超单块。
2. **分页协议**（SOP §3）：只在 `has_more=true` 时用 manifest 的 `next_offset` 续读；以末块 `has_more=false` 终止；skill 原文"只有 has_more=false 且查询范围符合问题时，才能当作完整结果"。
3. **快照一致性**（SOP §3.3）：全块 `rev`、`query_context` 必须相同，否则视为快照变化，Step 4 直接拒绝合并。
4. **对账**：逐块行数 = `records_count`，Σ`records_count` = 最终行数，`record_id` 无跨块重复。
5. **过滤下推**：时间窗与状态在服务端过滤（skill："行数较大时可用 --filter-json 下推可表达的条件"），避免"全量分页 + 本地过滤"组合下误判完整性；无法下推的条件本任务不存在。
6. **防呆**：`set -e` + 分块数 >50 熔断 + Step 4 任一断言失败即退出非零。

## 结果口径披露（随 Top3 一并交付）

- 数据来源：`K2qbA1bC3dE4fGh / tblReq9Mon` 整表（未使用 View），filter = 9 月 ∧ {待处理, 处理中}，投影 = 需求标题 / 负责人 / 提交时间。
- 时间口径：按 Base 本地日历匹配 2026-09-01~09-30（skill：ExactDate "按 Base 时区匹配"；NDJSON 中 datetime 为带 offset 的 RFC3339，manifest `timezone` 记录 Base 时区）。
- 空值口径：负责人为空计为「(空)」；前 3 名并列时按名称排序展示，条数可见，不隐藏并列。
- 只读声明：所用命令均标注 risk: read，全程无写入、无写回飞书。

## 命令/flag 语法依据（全部核实于官方来源，非记忆拼凑）

- `lark-cli --version` → **1.0.97**；`lark-cli base +record-list --help`（`--base-token/--table-id/--field-id 可重复/--filter-json/--sort-json/--offset/--limit/--format ndjson/--output/--overwrite/--as`，及 ndjson limit 上限与 "--format ndjson --output … for analysis" 建议）。
- `lark-cli base +record-search --help`（确认 filter/sort-only 读取应改用 +record-list）；`lark-cli base +url-resolve --help`；`lark-cli whoami --help`。
- 内嵌 skill `lark-base` v1.2.23（`lark-cli skills read lark-base`）：tuple filter 完整示例（Select `intersects` 数组；**"日期不支持 >=；用 > 前一天最后一毫秒表达含当天的下界"**；上界 `<` ExactDate(次月 1 日 00:00:00)）；"stdout 摘要包含 records_count 和 has_more"；NDJSON 每行含系统 `record_id`；Base 读取优先 `--as user`。
- 官方 SOP `references/lark-base-record-query-and-analysis-sop.md`（GitHub larksuite/cli main 分支）：§3 大表完整读取五步、§5 manifest 字段与"记录文件 + 同名 .manifest.json"布局、§7 交付前检查。
- 官方 README（github.com/larksuite/cli）：`config init` / `auth login --recommend` 流程。

## 本机验证记录（如实区分"已验证"与"无法验证"）

- 本机（windev-01）未预装 lark-cli 与 jq；为核实语法，在临时目录 `npm install @larksuite/cli`（装得 1.0.97）并**仅运行其 `--help` / `skills read`**，未调用任何飞书 API。
- 任务给的 Base 链接属用户租户（`xx.feishu.cn`），本机无该租户凭据，**真实导出未在本机执行**——以上命令需在已认证环境按序运行。
- 全管线（Step 3 循环 → Step 4 校验合并 → Step 5 统计）已在本机用模拟 `+record-list`（4600 行合成数据，按同一 manifest 协议返回 `records_count/has_more/next_offset/rev`）端到端跑通：
  - 命中 2 块（2000 + 296 = 2296 条），`./sep-open-reqs.ndjson` 恰 2296 行、每行恰 3 字段；
  - Top3 输出与对合成数据全集独立重算的结果**逐字一致**（`diff` 通过：984 / 657 / 328 条）；
  - 整条管线重跑幂等（`--overwrite` 生效，exit=0）；
  - 负向测试：人为篡改一块 manifest 的 `rev` 后单独执行 Step 4 代码，立即 `AssertionError: 读取期间 rev 变化…` 并以非零退出，确认不完整数据无法流入统计。
