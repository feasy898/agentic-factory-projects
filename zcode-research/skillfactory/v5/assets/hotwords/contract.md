# contract.md — hotwords 资产接口契约（冻结）

> **版本：1.0**（2026-09-30 初版冻结）：spec.md / contract.md / eval/runner.py 随 oracle
> 参照实现（hotwords.py + run_all.py + fixtures）一并固化。接口、命令行契约、检查项均以
> 本文为准；契约变更必须改本文件并升版本号，禁止静默变更。
>
> 本资产的特殊约定：评测含**与参照产物逐文件一致率 100%** 的检查（contract §4 检查 4），
> 因此被测实现的全部**可见行为**（stdout/stderr 文案、库 JSON 布局、导出产物、退出码）
> 均为冻结面，全文见 spec.md 附录 A；实现内部写法自由，行为必须与 oracle 逐字节一致
> （cmd.txt 中的机器相关绝对路径除外，按 A.7 归一化）。

---

## 1. 资产根目录布局

```
hotwords/
├── spec.md                  # 行为规格（随 oracle 行为冻结，附录 A = 逐字节常量全文）
├── contract.md              # 本文件：模块契约（冻结）
├── oracle/                  # 参照实现（只读，禁止改动其行为）
│   ├── hotwords.py          #   参照 CLI（唯一工具入口，纯标准库）
│   ├── run_all.py           #   10 步操作序列批量驱动（真实 CLI 子进程）
│   ├── README.md            #   oracle 用法
│   ├── fixtures/            #   base.json（演示库）+ script.json（10 步序列）——规范源
│   └── out/                 #   参照产物（python run_all.py 产出 → eval 的参照产物根）
├── package/                 # 被测实现（实现方交付物，布局见 §2）
│   ├── hotwords.py
│   ├── run_all.py
│   ├── fixtures/{base.json,script.json}   # 与 oracle/fixtures 字节一致
│   └── out/                 #   python run_all.py 产出 → 被测产物根（先产出后评测）
└── eval/
    └── runner.py            # 确定性评测器（接口见 §4）
```

## 2. 被测实现（package/）必备文件

| 文件 | 必须 | 要求 |
|---|---|---|
| `hotwords.py` | ✅ | CLI 契约见 §2.1；自包含（仅 Python 标准库） |
| `run_all.py` | ✅ | 驱动契约见 §2.2；自包含（仅 Python 标准库） |
| `fixtures/base.json`、`fixtures/script.json` | ✅ | 与 `oracle/fixtures/` 对应文件**逐字节一致**（全文见 spec 附录 A.1/A.2） |
| `out/` | ✅ | 由 `python run_all.py` 在评测前产出（先产出后评测） |
| `references/`、辅助模块等 | ⛔ 可选 | 允许；但不得改变 §2.1/§2.2 接口与产物字节 |
| `eval/`、`oracle/` 的副本 | ⛔ 禁止 | package/ 内不得复制品目录（评测统一用资产根的 eval/ 与 oracle/） |

### 2.1 hotwords.py 命令行契约（冻结）

```bash
python hotwords.py [--store <json>] <add|list|remove|export> [参数...]
```

| 项 | 冻结约定 |
|---|---|
| `--store` | 全局选项，须在子命令之前；默认 `./store.json` |
| `add` | `add <词> [--category 类别] [--note 备注] [--weight N]`；默认类别「默认」、备注空、权重 20；与既有词完全同字 → 退出码 2、库不变、stderr 中文；库不存在自动新建 |
| `list` | 按类别分组（类别字典序、组内插入序），格式见 spec R4/A.3 |
| `remove` | `remove <词>`；不存在 → 退出码 2、库不变 |
| `export` | `--format <funasr\|plain>` 必填；funasr 每行「词 权重」（缺省 20）、plain 每行一词；省略 `--out` 写 stdout；`--format` 非法 → 退出码 2 中文 |
| 库 JSON | `{"version":1,"words":[{word,category,note,weight},...]}`；落盘 indent=2 + ensure_ascii=False + 末尾换行、UTF-8 无 BOM（spec R2） |
| 退出码 | `0` 成功 / `2` 失败（业务错误 stderr 中文，argparse 语法错误英文）；退出码语义冻结 |
| 确定性 | 同输入重复运行全部输出逐字节一致（无时间戳/随机/网络） |

### 2.2 run_all.py 契约（冻结）

- 清空重建 `out/`；`fixtures/base.json` 复制为 `out/_work/store.json` 跨步延续。
- 逐步以**真实 CLI 子进程**执行 `fixtures/script.json` 的 10 步：argv =
  `[python, hotwords.py, --store <工作库>] + step.args`，cwd = 该步快照目录。
- 每步快照 `out/<NN>_<id>/`：`cmd.txt / exit_code.txt（"%d\n"）/ stdout.txt / stderr.txt /
  store.json` + 导出产物。
- 汇总 `out/manifest.json`：键结构见 spec 附录 A.8，含 `all_pass`。
- 整体退出码：任一步与 expect 不符 → 1，否则 0。

## 3. 评测标准姿势（与 howToRun 一致）

```bash
# 参照产物若缺则补跑（规范源 oracle/）：
cd skillfactory/v5/assets/hotwords/oracle && python run_all.py
# 被测产物（先产出后评测）：
cd <package 根> && python run_all.py
# 评测（两种写法等价，runner 支持父目录单层回退）：
python skillfactory/v5/assets/hotwords/eval/runner.py skillfactory/v5/assets/hotwords/package/out skillfactory/v5/assets/hotwords/oracle/out
python skillfactory/v5/assets/hotwords/eval/runner.py skillfactory/v5/assets/hotwords/package skillfactory/v5/assets/hotwords/oracle
```

> 运行目录注记：runner 只依赖两个位置参数定位产物根（direct 或父目录 `out/` 单层回退），
> 不假设 CWD；已从工作区根（相对路径）实跑验证（spec §7）。产物根不可移动或改名——
> 第 4 项检查按两树并集逐文件比对。

## 4. eval/runner.py 接口（冻结）

```bash
python skillfactory/v5/assets/hotwords/eval/runner.py <被测产物根> <参照产物根> [--out <path>]
# 例：python .../runner.py oracle/out oracle/out      （自评，应 exit 0）
```

- 两位置参数必填；产物根 = `run_all.py` 产出的 `out/`（或其父目录，单层回退留痕
  `resolved_via=parent-out`）；解析不出 `manifest.json` → 相关检查前置失败判红。
- **检查项名称（冻结，恒 4 项齐全）**：
  1. `script_sequence_consistent` — 操作序列每步快照与期望一致（10 步 id/expect/exit_code/快照文件/manifest 登记）。
  2. `duplicate_add_rejected` — 重复 add 报错（exit=2、stderr 中文命中关键词、stdout 空、库不变）+ remove 缺失词同样报错。
  3. `funasr_export_format` — funasr 行格式（词+空格+权重、缺省 20、与库快照逐行一致）+ plain 每行一词 + stdout 导出一致。
  4. `consistency_with_reference_100` — 与参照产物逐文件一致率恰 **100%**（cmd.txt 按 spec A.7 归一化，其余逐字节；缺失/多出/不一致均判红）。
- **stdout**：`[PASS]/[FAIL]` 逐项行 + JSON 报告（UTF-8 无 BOM，形状如下）+ 汇总行；给了
  `--out` 另写报告文件。

```jsonc
{
  "tool": "runner.py",
  "asset": "skillfactory/v5/assets/hotwords/eval",
  "candidate": "<按命令行原样>", "reference": "<按命令行原样>",
  "candidate_resolved": "...", "candidate_resolved_via": "direct | parent-out(...) | none",
  "reference_resolved": "...", "reference_resolved_via": "同上",
  "self_eval": true,
  "ok": true,
  "summary": { "checks": {"total":4,"passed":4,"failed":0},
               "steps": {"total":10,"ok":10},
               "files": {"files_universe":54,"files_matched":54,"files_mismatched":0,
                         "files_missing":0,"files_extra":0},
               "consistency_rate": 1.0 },
  "checks": [ {"name":"...","passed":true,"detail":"..."} ]   // 恒 4 项，允许附加审计键
}
```

- **退出码**：0 = 4 项全过；1 = 任一失败（仍打印完整 JSON，`ok=false`）；2 = 用法错误。
- **确定性**：无时间戳、无随机、无网络；同参数重复运行 stdout 逐字节一致。
- 消费方只应依赖 `ok`、`checks[].name/passed/detail`；其余字段为审计信息，可向后兼容地增删。

## 5. 实现自由度

| 可自由 | 冻结 |
|---|---|
| hotwords.py / run_all.py 内部实现、函数划分、注释 | CLI 参数面、退出码、库 JSON 布局、全部用户可见文案（spec 附录 A）、确定性 |
| package/ 内辅助文件 | 必备文件清单（§2）与 fixtures 字节一致性 |
| runner 的审计字段与 detail 文案 | runner CLI、4 项检查名、`ok`/`checks[].{name,passed,detail}`、退出码、100% 阈值、A.6/A.7 常量与归一化规则 |
| 产物根传 `out/` 本身或其父目录 | §4 解析顺序（direct → parent-out 单层回退） |

## 6. 冻结与版本

- 本契约 1.0 冻结项：目录布局（§1）、package 契约（§2）、runner 接口与 4 项检查及 100% 阈值
  （§4）、退出码语义（0/1/2）、spec 附录 A 全部逐字节常量。
- 变更流程：改 contract.md/spec.md 并升版本号 + 记录变更说明；`oracle/` 行为任何改动视为 breaking。
- **eval 只增不删**：对 `eval/runner.py` 的修改只允许新增检查项或收紧阈值，不允许删除/放松
  既有 4 项检查与 100% 一致率要求。
- **oracle 只读**：`oracle/` 是参照实现，不得修改；演进版实现在新 package 根生成，用 runner
  与 `oracle/out` 比对。
- 未来新增检查项须写入 spec.md §4.3 并保持可判定（无模型调用）。
