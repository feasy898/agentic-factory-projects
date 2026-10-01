# speaker-mapping — 说话人标签映射工具（分发包）

把 diarization 转写稿里的 `SPEAKER_XX` 标签替换为人名，或扫描转写稿生成说话人清单与
草稿映射。纯 Python 标准库、无网络、输出确定性（同输入重跑逐字节一致）。

行为规格：`../spec.md`（R1-R10）；接口契约：`../contract.md` §2；本包 `map_speakers.py`
为契约同 oracle 的分发实现（黑盒行为满足 spec，内部实现独立编写、未参照 oracle 源码）。

## 包内容

```
package/
├── map_speakers.py   工具本体（CLI 契约 = contract.md §2）
├── SKILL.md          人机协作映射流程：discover → 人工确认 → apply
├── README.md         本文件
└── out/              对 ../oracle/fixtures 6 个输入实跑的全部产物（24 个文件）
```

## 快速开始

```bash
# 扫描：看看稿里有几个说话人、各说几句，顺手产出草稿映射
python map_speakers.py --discover --transcript T.txt --out draft.json

# 人工把 draft.json 里的 "" 填成真实人名后（见 SKILL.md 第 2 步）：
python map_speakers.py --transcript T.txt --mapping draft.json --out T_named.txt
```

## CLI 与退出码（实测口径，spec.md R6）

| 项 | 约定 |
|---|---|
| 映射模式 | `--transcript T.txt --mapping m.json --out O.txt`（后两者缺一 → exit 2） |
| 扫描模式 | `--discover --transcript T.txt [--out draft.json]`；缺 `--out` 打印 stdout 且 stderr 为空 |
| 标签判定 | 行首（可选一个 `[...]` 时间戳段）+ ASCII 标识符 token + 半角/全角冒号；行中标签不识别 |
| 替换不变式 | 只换标签 span；时间戳/冒号/正文/行尾（CRLF/LF）逐字节不动；行数不变 |
| stderr | 未映射标签按标签汇总 WARNING（含次数）；映射键未出现 WARNING；成功 INFO 行 |
| 退出码 | `0` 成功（含仅警告）；`2` 输入文件不存在/参数错误；`1` 映射非合法 JSON 或顶层非对象 |

## out/ 产物根（24 个文件，布局 = contract.md §3）

```
{normal,partial,empty}__{m_full,m_partial,m_empty}.txt         9 个映射产物
{normal,partial,empty}__{m_full,m_partial,m_empty}.stderr.txt  9 个 stderr 存档
discover__{normal,partial,empty}.json                          3 个扫描草稿
discover__{normal,partial,empty}.json 的同名 .stderr.txt       3 个扫描 INFO 存档
```

### 本包 out/ 的实测产出方式

在 `../oracle/` 目录为 cwd（读取判分输入基准 fixtures），`--transcript/--mapping` 用
**反斜杠相对路径**（`fixtures\normal.txt`，使 discover JSON 的 `transcript` 字段回显与
基线一致），`--out` 指向本包（相对路径 `../package/out/…`，不写入只读的 `oracle/out/`）：

```bash
# cwd = ../oracle/ ；sep 为反斜杠 '\'
for t in normal partial empty; do for m in m_full m_partial m_empty; do
  python ../package/map_speakers.py --transcript "fixtures${sep}$t.txt" \
    --mapping "fixtures${sep}$m.json" --out "../package/out/${t}__${m}.txt" \
    2> "../package/out/${t}__${m}.stderr.txt"; done; done
for t in normal partial empty; do
  python ../package/map_speakers.py --discover --transcript "fixtures${sep}$t.txt" \
    --out "../package/out/discover__${t}.json" 2> "../package/out/discover__${t}.stderr.txt"; done
```

12/12 命令 exit 0。与 contract.md §3 基准约定的唯一差异是 `--out` 的路径回显
（进 stderr INFO 行）；INFO 行非判分对象，12 个主产物与基线逐字节一致（下节实测）。

## 验证记录（2026-09-30，本机 win32 + Python 3.12.10）

- 探针复现（spec §2.3，14/14 PASS）：CRLF 保留、全角冒号、行首锚定、8 组退出码
  （缺稿 2 / 缺映射 2 / 坏 JSON 1 / 顶层非对象 1 / 缺参 2）、discover stdout 空 stderr、
  英文冒号行计为标签、BOM 容忍、确定性。
- 交叉核对：5 组空映射产物与 fixtures 逐字节 `cmp` 相等（938/774/323 B）；已映射产物
  重跑幂等（输出≡输入，exit 0）；`grep -c "^\[.*\] SPEAKER_..:"` 与 discover 统计一致
  （normal 10 / partial 10 / empty 0）。
- 评测器（4 项检查全过，exit 0）：

```text
$ python skillfactory/v5/assets/speaker-mapping/eval/runner.py \
    skillfactory/v5/assets/speaker-mapping/package/out \
    skillfactory/v5/assets/speaker-mapping/oracle/out
{
  "ok": true,
  "summary": {
    "total": 4,
    "pass": 4,
    "fail": 0,
    "tested_root": "D:\\workspace\\zcode研究\\skillfactory\\v5\\assets\\speaker-mapping\\package\\out",
    "reference_root": "D:\\workspace\\zcode研究\\skillfactory\\v5\\assets\\speaker-mapping\\oracle\\out"
  },
  "checks": [
    {"name": "replacement_line_by_line", "pass": true,
     "detail": "9 组映射产物逐字节等于期望常量（含替换正确、未映射标签原样保留、时间戳/冒号/正文逐字节不动）"},
    {"name": "unmapped_warnings", "pass": true,
     "detail": "9 组 stderr 存档的 WARNING 与期望逐一相符（未映射标签原样保留且有警告；empty+m_full 另有 3 条映射键未出现警告）"},
    {"name": "discover_stats", "pass": true,
     "detail": "3 个 discover JSON 统计正确: normal 3人(4/3/3)、partial 4人(3/3/2/2，SPEAKER_03 按首次出现排第2)、empty 0人；draft_mapping 与清单一致"},
    {"name": "reference_agreement_100pct", "pass": true,
     "detail": "与参照产物逐字节一致 12/12（100%，确定性要求）"}
  ]
}
（runner_exit=0）
```

## 已知限制

- 英文冒号行（`Note: …`）命中标签正则，会被 discover 计为标签 / apply 警告（fixtures 未含此形态）。
- 标签 token 仅 ASCII；中文标签不支持（幂等性的来源）。
- 一行只识别行首一个标签；不做说话人分离本身。
