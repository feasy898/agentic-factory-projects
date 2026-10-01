# lark-cli 文档列表只回 20/87 —— 诊断 · 修正 · 核对

> 现象（同事原话）：`lark-cli` 拉取某文件夹下全部文档，脚本正常结束只得 20 篇（实际 87 篇），无任何报错；响应里有 `page_token` 字段，脚本未处理。

---

## 一、根因诊断

最可能的根因是：该列表命令走的是飞书分页接口——一次调用只返回**第一页**（本例恰为 20 条），并在响应里附上 `page_token`（配合 `has_more`）表示"还有下一页"；而脚本把第一页响应当成完整结果直接落盘，从未把 `page_token` 回传给下一次调用，于是在 20/87 处**静默截断**。之所以"没有任何报错"，是因为分页协议下第一页请求本身完全成功——漏翻页是客户端逻辑缺失，服务端不会报错，这类 bug 只有对总数时才暴露。响应里出现 `page_token` 而脚本无对应处理分支，正是"单页消费"的直接证据。

---

## 二、修正方案

### 方案 A（首选）：官方自动翻页参数 `--page-all`

官方 `lark-cli`（github.com/larksuite/cli）README 的 **Pagination** 节明确提供全局分页参数（本次已抓取原文核实）：

```bash
--page-all                  # Auto-paginate through all pages（自动翻完所有页）
--page-limit 5              # Max 5 pages（最多翻 5 页）
--page-delay 500            # 500ms between page requests（页间隔）
```

给列表命令加上 `--page-all` 即可一次拉全，无需改脚本逻辑：

```bash
# API 命令形态（子命令名用 `lark-cli drive --help` 确认；README 示例风格为 `lark-cli calendar calendars list`）
lark-cli drive files list --folder-token <FOLDER_TOKEN> --page-all --format json > all_files.json

# 或原始 API 形态（README：`lark-cli api GET /open-apis/...` 覆盖 2500+ 平台接口）
lark-cli api GET /open-apis/drive/v1/files \
  --params '{"folder_token":"<FOLDER_TOKEN>","page_size":100}' \
  --page-all --format json > all_files.json
```

### 方案 B（通用兜底）：手动 `page_token` 循环（shell），任何 CLI 版本都可用

核心就是把响应里的 `page_token` 回传给下一次调用，直到没有下一页：

```bash
#!/usr/bin/env bash
FOLDER="<FOLDER_TOKEN>"
page=0; total=0; token=""
> all_docs.tsv
while :; do
  page=$((page+1))
  if [ -z "$token" ]; then
    resp=$(lark-cli drive files list --folder-token "$FOLDER" --format json)
  else
    resp=$(lark-cli drive files list --folder-token "$FOLDER" --format json --page-token "$token")
  fi
  # README：以 ok == true 判成功（错误走 stderr、非零退出码）
  echo "$resp" | jq -e '.ok == true' >/dev/null || { echo "API 调用失败，停止"; exit 1; }

  n=$(echo "$resp" | jq '[.data.files[]?] | length')
  total=$((total+n))
  echo "第 $page 页：+$n 篇，累计 $total"                      # ← 逐页累计计数
  echo "$resp" | jq -r '.data.files[]? | [.token, .name] | @tsv' >> all_docs.tsv  # 逐页落盘防丢

  token=$(echo "$resp" | jq -r '.data.page_token // .data.next_page_token // empty')
  has_more=$(echo "$resp" | jq -r '.data.has_more // empty')
  # 终止条件：has_more 显式为 false，或已无下一页 token（两种字段名都做了防御）
  if [ "$has_more" = "false" ] || [ -z "$token" ]; then break; fi
done
echo "TOTAL=$total"
```

说明：不同接口的翻页字段名可能是 `page_token` 或 `next_page_token`，终止以 `has_more==false` 或 token 为空为准，循环里两者均防御；若所用版本手动翻页参数名不是 `--page-token`，以 `--help` 输出为准（走 raw API 则把 token 拼进 `--params`）。

**附带优化（减少翻页次数，非正确性修复）**：官方《获取文件夹中的文件清单》文档显示 `GET /open-apis/drive/v1/files` 的 `page_size` 默认 100、上限 200（来源见文末核实记录）。把 `page_size` 提到 ≥87 后一页即可拿全；但正确性保障必须靠分页循环或 `--page-all`，不能靠"调大 page_size 碰运气"——文件数涨过一页上限时同样的截断会复发。

---

## 三、核对方法（证明拉到了全部 87 篇）

三层核对，全部可脚本化：

1. **逐页累计计数（主证据）**：方案 B 循环每页打印 `累计 X`，结束后断言：
   - `TOTAL == 87`；
   - 且最后一页响应满足 `has_more == false`（或 `page_token` 为空）。
   "总数 87 + 末页被显式标记为无下一页"即完整性证明——这不是凑数碰上 87，而是分页协议自己声明了"没有更多了"。

2. **去重唯一数核对（防翻页重叠/错位）**：全部落盘到 `all_docs.tsv` 后：

   ```bash
   cut -f1 all_docs.tsv | sort -u | wc -l   # 必须等于 87
   cut -f1 all_docs.tsv | sort | uniq -d    # 必须为空（无重复 token）
   ```

   若唯一数 ≠ 87 或出现重复，说明翻页 offset 错位或页间重叠，拉全不成立。

3. **独立二次口径核对（防同源盲区）**：换一条独立路径再数一遍，两种口径一致才闭环：

   ```bash
   # 用 page_size=200（接口上限）一次拉全，应同样得 87
   lark-cli api GET /open-apis/drive/v1/files \
     --params '{"folder_token":"<FOLDER_TOKEN>","page_size":200}' \
     --page-all --format json | jq '[.data.files[]?] | length'   # 期望输出 87
   ```

   有条件的话再与飞书客户端该文件夹 UI 显示的条目数对表，作为第三口径。

**一句话判定**：`TOTAL=87` ＋ 末页 `has_more=false` ＋ `sort -u` 去重后唯一 token 数 = 87，三者同时成立即证明拉到了全部 87 篇。

---

## 来源与核实状态（本次实际执行的检查）

| 事项 | 核实方式与结果 |
|---|---|
| 本机能否复跑该命令 | **不能**。已运行 `where lark-cli`、`where lark`（均"无法找到文件"）、`npm ls -g`、检查 `D:\tools\bin` 与 `D:\tools\npm-global`——本机未安装 lark-cli，故命令形态基于官方文档抓取，`lark-cli drive files list` 子命令名系按 README 的 OAPI 命名风格（`lark-cli calendar calendars list`）推断，**使用前请以 `lark-cli drive --help` 或 `lark-cli schema drive` 确认** |
| `--page-all` / `--page-limit` / `--page-delay`、`--format json` 默认、`ok==true` 判成功 | 抓取 github.com/larksuite/cli（官方仓库）README 原文 Pagination 节与 Output 节，逐字核实 |
| 服务层自动分页实现存在 | 经 GitHub API 抓取仓库源码树，含 `cmd/service/service_paginate_test.go` |
| `page_size` 默认 100 / 上限 200 | 来自飞书开放平台《获取文件夹中的文件清单》（`GET /open-apis/drive/v1/files`）文档页的搜索摘要；官方文档页为 JS 渲染，本次两种抓取工具均取不到正文，**未能直接引用原文**，请以文档/`--help` 为准。同事实际只得 20 条，说明其调用链上生效的 page_size 为 20（CLI 默认或脚本传入），确切来源待其 `--help` 确认 |
| "20 篇、无报错、响应含 page_token" | 任务描述原话（同事反馈），诊断的事实基础 |
| 产物目录限制 | 全程未读取 `skillfactory/v2/evalbench/` 与 `skillfactory/v2/agentkit/` 下任何文件（仅目录名列表定位产物路径） |
