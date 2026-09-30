# contract.md — speaker-mapping 资产接口契约

> 接口冻结，实现自由：本文件列的是「必须不变」的命令行、文件布局与产物 schema；
> 内部实现（正则写法、代码组织）可自由替换，只要黑盒行为满足 spec.md。

## 1. package 必备文件（分发形态 = 本目录整体）

```
skillfactory/v5/assets/speaker-mapping/
├── spec.md            # 规格（行为规则逐条可判定 + 附录 A 期望常量全文）
├── contract.md        # 本文件（接口契约）
├── eval/
│   └── runner.py      # 确定性评测器（§4 契约）
└── oracle/
    ├── map_speakers.py  # 参照实现（§2 契约）
    ├── fixtures/        # 输入基准：normal/partial/empty.txt + m_full/m_partial/m_empty.json
    └── out/             # 基线产物 24 个文件（评测参照，只读）
```

必备 = 上表全部文件存在且各自满足对应节契约；缺任一即资产不完整。
`oracle/out/` 为评测参照产物，**只读**；重跑工具时产物写到别处。

## 2. oracle CLI 契约（冻结）

```
# 映射模式
python map_speakers.py --transcript T.txt --mapping m.json --out O.txt
# 扫描模式
python map_speakers.py --discover --transcript T.txt [--out draft.json]
```

| 项 | 契约 |
|---|---|
| 标签判定 | 行首（可选先有一个 `[...]` 时间戳段）+ ASCII 标识符 token + 半角/全角冒号；spec.md R2 冻结 |
| 替换不变式 | 只换标签 span；时间戳/冒号/正文逐字节不动；行数不变；行尾 CRLF/LF 按原文保留；未映射标签原样保留 |
| stderr | 未映射标签 → 按标签汇总 WARNING（次数）；映射键未出现 → WARNING；成功时 INFO 行（含 `--out` 路径回显） |
| 退出码 | `0` 成功（含仅警告）；`2` 输入文件不存在 / argparse 参数错误；`1` 映射文件非合法 JSON（**实测口径**，docstring 写 2 系偏差，见 spec.md R6） |
| discover | 输出 `{transcript, total_utterances, speakers:[{label,utterances}]（首次出现序）, draft_mapping:{label:""}}`；缺省 stdout（此时 stderr 为空），`--out` 写文件 + INFO |
| 依赖 | 仅 Python 标准库；无网络、无随机、无时间戳（确定性） |

## 3. 产物根布局与产出约定（冻结）

产物根 = 平铺 24 个文件（与 `oracle/out/` 同构）：

```
{normal,partial,empty}__{m_full,m_partial,m_empty}.txt         9 个映射产物
{normal,partial,empty}__{m_full,m_partial,m_empty}.stderr.txt  9 个警告存档
discover__{normal,partial,empty}.json                          3 个扫描草稿
discover__{normal,partial,empty}.stderr.txt                    3 个扫描 INFO 存档
```

**产出约定**（eval 检查 4 要求字节级一致的前提）：在 `oracle/` 目录为 cwd，按
spec.md howToRun 用**相对路径**运行，`2>` 收集 stderr 存档：

```bash
for t in normal partial empty; do for m in m_full m_partial m_empty; do
  python map_speakers.py --transcript "fixtures/$t.txt" --mapping "fixtures/$m.json" \
    --out "out/${t}__${m}.txt" 2> "out/${t}__${m}.stderr.txt"; done; done
for t in normal partial empty; do
  python map_speakers.py --discover --transcript "fixtures/$t.txt" \
    --out "out/discover__${t}.json" 2> "out/discover__${t}.stderr.txt"; done
```

用绝对路径 `--out` 产出的产物集：9 个 .txt 与 9 个 WARNING 集合仍合格
（eval 检查 1/2/3 不受影响），但 stderr INFO 与 discover `transcript` 字段的路径
回显会与基线不同 → eval 检查 4 会判败。这是约定而非缺陷。

## 4. eval runner CLI 契约（冻结）

```
python eval/runner.py [<被测产物根> <参照产物根>]
```

| 项 | 契约 |
|---|---|
| 缺省（零参数） | 被测 = 参照 = `<runner 目录>/../oracle/out`（自校验，应全过） |
| 检查 | 固定 4 项（名称冻结）：`replacement_line_by_line` / `unmapped_warnings` / `discover_stats` / `reference_agreement_100pct`；判分口径见 spec.md §5 |
| stdout | JSON：`{"ok": bool, "summary": {total, pass, fail, tested_root, reference_root}, "checks": [{name, pass, detail}]}`；无时间戳（确定性） |
| exit 0 | 全部检查通过 |
| exit 1 | 任一检查失败（含空目录/产物缺失） |
| exit 2 | 参数个数非 0/2（用法错误，信息走 stderr） |
| 依赖 | 仅 Python 标准库；无网络、无随机；不读 fixtures、不跑被测工具（期望全部固化为常量，全文见 spec.md 附录 A） |

## 5. fixtures 契约（判分输入基准，冻结）

| 文件 | 内容要点 | 关键判分作用 |
|---|---|---|
| `normal.txt` | 3 说话人 10 条（00×4/01×3/02×3） | 全替换基线；m_partial 下 SPEAKER_02×3 原样+警告 |
| `partial.txt` | 4 说话人 10 条（00×3/**03×3**/01×2/02×2） | SPEAKER_03 插队 → discover 首次出现排序判分 |
| `empty.txt` | 无标签 7 行（含 2 条仅时间戳无标签行） | 输出≡输入；映射键未出现警告 |
| `m_full.json` | 00→王总，01→李工，02→赵秘书 | 全映射；中文名标签不回代（幂等） |
| `m_partial.json` | 仅 00/01 | 部分映射：替换+保留+警告三态并存 |
| `m_empty.json` | `{}` | 输出≡输入字节恒等 |

改 fixtures 必须同步改 spec.md §2.1、附录 A 全部常量与 eval 期望。

## 6. 兼容性承诺

- 4 项检查的名称集合与顺序不变；未来新增检查只能**追加在 checks 数组尾部**。
- fixtures 的 6 个文件名、产物根的 24 个文件名不变。
- 退出码语义不变（oracle 0/1/2 按实测口径；eval 0/1/2）。
- `oracle/out/` 升级基线时：须重新逐字节验证确定性（重跑 12 命令与基线一致），并
  同步更新 spec.md 附录 A。
