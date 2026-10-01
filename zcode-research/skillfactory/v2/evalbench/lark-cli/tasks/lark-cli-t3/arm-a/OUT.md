# lark-cli 拉取文件夹文档只有 20/87 篇：诊断、修正方案与核对方法

> 对象命令：`lark-cli drive files list`（官方技能文档原文："读取 Drive 文件夹清单时使用 `drive files list`"，来源：skills/lark-drive/SKILL.md，抓取于 2026-09-29）。
> 依据：`ASSET-DOC.md`（本仓档）+ 当日抓取的官方仓库三个原始文件（README.md、skills/lark-drive/SKILL.md、skills/lark-drive/references/lark-drive-files-list.md）+ 本机 mock 实测。
> 诚实声明：本机未安装 lark-cli（`where lark-cli` 无输出），未对真实飞书租户执行过该命令；下述循环逻辑已用 mock lark-cli 在本机完整实测（见第三节证据）。

## 一、诊断（根因）

`drive files list` 是分页接口：单页只返回 `page_size` 条（不显式设置时用服务端默认值，同事实测单页 20 条），并在响应里给出 `has_more=true` 和下一页 token（官方参考文件写明字段为 `data.next_page_token`，需回填到下一次调用的 `--params.page_token`）。同事的脚本把"第一页成功"当成了"拉取完成"，没有回填 `page_token` 继续翻页，所以只拿到第一页的 20 篇。而第一页响应本身是合法成功（退出码 0、`ok==true`，lark-cli 的输出契约规定成功信封没有顶层 `code`/`msg`，判断成功只看 `ok==true`），属于**静默截断而非报错**，剩余 67 篇在后续页里——这就是"没有任何报错"的原因。

依据：ASSET-DOC.md:152-156（分页全局 flags）、ASSET-DOC.md:136-148（`ok==true` 输出契约）；官方参考文件 lark-drive-files-list.md 原文："`has_more=true` 时把 `next_page_token` 放回 `--params.page_token`"、响应结构为 `data.files` / `data.has_more` / `data.next_page_token`。

## 二、修正方案

### 方案 B（推荐给脚本）：`--params.page_token` 手动分页循环

官方 lark-drive 技能对脚本场景的原文要求："按模板通过 `--params` 传参并手动处理分页；不要把 `--page-all` 输出直接交给 JSON 解析脚本"。单页调用形态（注意：该命令**没有** `--folder-token` flag，参数一律走 `--params`）：

```bash
lark-cli drive files list \
  --params '{"folder_token":"<folder_token>","page_size":200}' \
  --format json
```

`page_size` 官方建议全量盘点显式设 `200`（服务端报参数错误时降级到其允许值）；响应取 `data.files[]`（每项含 `name`/`type`/`token`/`url` 等）、`data.has_more`、`data.next_page_token`；翻页时保持 `folder_token`/`order_by`/`direction`/`page_size` 不变，只回填 `page_token`。

带分页循环的完整脚本（**已在本机 mock 实测通过**，见第三节；JSON 解析用 python3，如装有 jq 可等价替换）：

```bash
#!/usr/bin/env bash
# fetch_folder_docs.sh — 分页拉取飞书 Drive 文件夹下全部文档
# 用法: ./fetch_folder_docs.sh <folder_token> [输出tsv，默认 ./all_files.tsv]
set -euo pipefail

FOLDER_TOKEN="${1:?用法: $0 <folder_token> [out.tsv]}"
OUT="${2:-all_files.tsv}"
PAGE_SIZE=200      # 官方参考文件建议全量盘点显式设 200（服务端报参数错误时调低）
RETRY_MAX=3        # has_more=true 但缺下一页 token 时，同页最多重试 3 次
PAGE_DELAY=0.5     # 页间隔秒数（等效全局 --page-delay 500）

PY=$(command -v python3 || command -v python)

# 解析单页响应 -> "N HAS_MORE NEXT_TOKEN"；非 JSON 或 ok!=true 直接报错退出（只信 ok==true）
SUMMARY='
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print("响应不是合法 JSON（检查是否把 stderr 并进了 stdout）",file=sys.stderr); sys.exit(1)
if not d.get("ok"):
    print("API错误信封: "+json.dumps(d.get("error",{}),ensure_ascii=False),file=sys.stderr); sys.exit(1)
data=d.get("data") or {}
files=data.get("files") or []
print(len(files), 1 if data.get("has_more") else 0, data.get("next_page_token") or "")
'
ROWS='
import json,sys
d=json.load(sys.stdin)
for f in (d.get("data") or {}).get("files") or []:
    print("\t".join(str(f.get(k,"")) for k in ("name","type","token","url")))
'

PAGE_TOKEN=""; TOTAL=0; PAGE_NO=0; TRIES=0
: > "$OUT"
echo "folder=$FOLDER_TOKEN page_size=$PAGE_SIZE 输出=$OUT"
while :; do
  PAGE_NO=$((PAGE_NO+1))
  PARAMS="{\"folder_token\":\"$FOLDER_TOKEN\",\"page_size\":$PAGE_SIZE"
  [ -n "$PAGE_TOKEN" ] && PARAMS="$PARAMS,\"page_token\":\"$PAGE_TOKEN\""
  PARAMS="$PARAMS}"

  # 成功信封走 stdout 且退出码 0；失败走 stderr 且非 0（lark-cli 输出契约）
  RESP=$(lark-cli drive files list --params "$PARAMS" --format json) \
    || { echo "lark-cli 调用失败（错误信封见上方 stderr）" >&2; exit 1; }

  PAGE_OUT=$(printf '%s' "$RESP" | "$PY" -c "$SUMMARY") \
    || { echo "第 $PAGE_NO 页响应校验失败，终止" >&2; exit 1; }
  read -r N HAS_MORE NEXT <<< "$PAGE_OUT"

  # 官方参考规则：has_more=true 却没有下一页 token -> 同一 page_token 重试同一页（不重复计数），3 次后停止并报告
  if [ "$HAS_MORE" = "1" ] && [ -z "$NEXT" ]; then
    TRIES=$((TRIES+1))
    if [ "$TRIES" -ge "$RETRY_MAX" ]; then
      echo "阻断: 第 $PAGE_NO 页 has_more=true 但缺 next_page_token，已重试 $TRIES 次。请记录该目录为 pagination blocker，勿当作已拉全。" >&2
      exit 2
    fi
    sleep 1
    PAGE_NO=$((PAGE_NO-1))   # 重试同一页
    continue
  fi

  printf '%s' "$RESP" | "$PY" -c "$ROWS" >> "$OUT"
  TOTAL=$((TOTAL+N))
  TRIES=0
  echo "page $PAGE_NO: +$N 篇，累计 $TOTAL"

  # 只有 has_more=false 才是完整结果
  [ "$HAS_MORE" = "1" ] || break
  PAGE_TOKEN="$NEXT"
  sleep "$PAGE_DELAY"
done
echo "DONE 共 $PAGE_NO 页 $TOTAL 篇 -> $OUT"
```

要点（每条均有出处）：
- **翻页判据只有 `has_more`**：`=false` 才是完整结果（官方参考文件；ASSET-DOC.md:370 在 base 技能中同样强调"只有 `has_more=false` 才是完整结果"）。
- **只解析 stdout**：不要 `2>&1`（错误信封在 stderr，ASSET-DOC.md:143、官方参考文件均要求）。
- **输出路径用相对路径**（`--output` 类参数只接受 cwd 相对路径，ASSET-DOC.md:292；本脚本用 shell 重定向写 `./all_files.tsv`，同样遵守）。
- **防重复计数**：重试用同一 `(folder_token, page_token)` 页键，模糊页不提交（官方参考文件的 dedupe 规则）。
- **先自省再改**：若同事看到的字段名是 `page_token` 而非 `next_page_token`，以 `lark-cli schema drive.files.list` 输出为准（官方参考文件原文："字段名以 `schema drive.files.list` 为准"），回填的键始终是 `--params` 里的 `page_token`。

### 方案 A（一次拉全）：全局 `--page-all`

lark-cli 有自动翻页的全局参数（ASSET-DOC.md:152-156；官方 README 原文注释 `--page-all  # Auto-paginate through all pages`，配套 `--page-limit N` 限制最多页数、`--page-delay ms` 页间隔）：

```bash
lark-cli drive files list \
  --params '{"folder_token":"<folder_token>","page_size":200}' \
  --format json --page-all
```

适用与告警：官方 lark-drive 技能明确警告"**不要把 `--page-all` 输出直接交给 JSON 解析脚本**"（聚合输出的结构不保证是可直接 `json.load` 的单页信封），所以它适合人工核对、`--format table` 肉眼清点或一次性导出；同事这种**脚本自动解析**场景请用方案 B。

## 三、核对方法（证明拉到了全部 87 篇）

1. **页累计计数（核心）**：循环内每页打印 `+N 篇，累计 TOTAL`（上面脚本已内置），只有最后一页 `has_more=false` 时才输出 DONE。以默认单页 20 条为例，期望序列：`20→40→60→80→87`（若 `page_size=200` 生效则可能 1 页即 87）；**TOTAL ≠ 87 或最后未见 `has_more=false`，就不算拉全**。
2. **事后三重核对**（对脚本产出的 `all_files.tsv`，列为 name/type/token/url）：

   ```bash
   wc -l < all_files.tsv                            # ① 总行数应 = 87
   cut -f3 all_files.tsv | sort -u | wc -l          # ② 去重 token 数应 = 87（证明无重复拉取/无缺漏）
   lark-cli drive files list --params '{"folder_token":"<folder_token>","page_size":200}' \
     --format json --page-all --format table        # ③ 用 --page-all 独立通道肉眼/计数比对 = 87
   ```

3. **口径提醒**：`files list` 只返回**直接子项**、不递归（官方参考文件原文："根目录只返回直接子项，不是递归结果"，总数必须来自去重后实际遍历的集合）。确认 UI 里的"87 篇"是**直接子项口径**；若要只数文档，可按 `data.files[].type` 过滤（`folder` 是子文件夹，`docx`/`doc`/`sheet`/`bitable` 等是各类文档）。
4. **本机 mock 实测证据**（`bash run_test.sh`，mock lark-cli 服务 5 页 20+20+20+20+7）：
   - TEST 1 输出：`page 1: +20 累计 20 … page 5: +7 累计 87`，`DONE 共 5 页 87 篇`，exit=0；`wc -l`=87、唯一 token=87；lark-cli 调用日志证明 `page_token` 逐页回传（`--params {"folder_token":"FOLDERXXX","page_size":200}` → `"page_token":"pt2"` → `pt3` → `pt4` → `pt5`）。
   - TEST 2（异常路径）：mock 返回 `has_more=true` 但缺 `next_page_token` → 同页重试 3 次后 `exit=2` 并打印"记录该目录为 pagination blocker，勿当作已拉全"，已提交行数=0（模糊页不计数，杜绝静默截断/重复计数）。

## 附注（与 ASSET-DOC 的关系）

- 无任务冲突。ASSET-DOC §5.3 给出 `--page-all` 分页 flags，本方案一并采用；但 ASSET-DOC 未收录 lark-drive 的 SKILL.md 与 references（其文末"未逐字核验项"已声明），本文补充抓取了 `skills/lark-drive/SKILL.md` 与 `skills/lark-drive/references/lark-drive-files-list.md`（2026-09-29，raw.githubusercontent.com/larksuite/cli/main），其中"脚本手动处理分页、`--page-all` 输出不交给 JSON 解析脚本"的官方约束使方案 B 成为脚本场景的推荐解——此为对 ASSET-DOC 的补充而非冲突。
- 未验证项如实声明：① 本机未安装 lark-cli，未对真实飞书租户执行命令，87 篇的实际拉取需同事在已配置环境（`lark-cli config init` + `auth login`）下运行；② 服务端 `page_size` 默认值未从官方文档核实，"单页 20 条"以同事实测为据；③ mock 实测只验证循环逻辑（翻页、回传、累计、终止、异常阻断），不替代真实 API 验证。
