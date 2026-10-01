# contract.md — content-evaluator 资产接口契约

> 接口冻结，实现自由：本文件列的是「必须不变」的命令行、文件布局与产物 schema；
> 内部实现（解析方式、代码组织）可自由替换，只要黑盒行为满足 spec.md。

## 1. package 必备文件（分发形态 = 本目录整体）

```
skillfactory/v4/tools/content-evaluator/
├── spec.md            # 规格（行为规则逐条可判定）
├── contract.md        # 本文件（接口契约）
├── eval/
│   └── runner.py      # 确定性评测器（§3 契约）
├── oracle/
│   ├── evaluate.py    # 参照实现（§2 契约）
│   ├── fixtures/      # 四份样例文案（§4，评测的输入基准）
│   │   ├── good_dy.md  good_xhs.md  bad_xhs.md  bad_wx.md
│   └── out/           # 基线产物：{good_dy,good_xhs,bad_xhs,bad_wx}/{report.json,REPORT.md}
└── README.md          # 用法/阈值/各 fixture 预期分（oracle/README.md 承担）
```

必备 = 上表全部文件存在且各自满足对应节契约；缺任一即资产不完整。
`oracle/out/` 为评测参照产物，**只读**，重跑评测不得写回此处（可重建到临时目录）。

## 2. oracle CLI 契约（冻结）

```
python oracle/evaluate.py --input <markdown文件> --platform <dy|xhs|wx> --out <报告目录>
```

| 项 | 契约 |
|---|---|
| 参数 | `--input`、`--platform`、`--out` 均必填；`--platform` 仅接受 dy/xhs/wx |
| exit 0 | 报告已写出（无论红绿；本工具只报告不设门） |
| exit 2 | 缺参 / `--platform` 非法 / `--input` 不是文件 / 输入不可解码；此时不得创建 `--out`、不得写任何产物 |
| 产物 | `<out>/report.json` + `<out>/REPORT.md`，schema 见 §5 |
| 行为 | 恰 9 项检查（名称与顺序冻结）、平台阈值与计分规则冻结 —— 细则见 spec.md §3 R2–R10 |
| 确定性 | 纯标准库、离线、无随机；同输入重复运行仅 `generated_at` 及 REPORT.md 生成时间行不同 |

## 3. eval runner CLI 契约（冻结）

```
python eval/runner.py [<被测产物根> <参照产物根>]
```

| 项 | 契约 |
|---|---|
| 缺省（零参数） | 被测 = 参照 = `<runner 目录>/../oracle/out`（自校验，应全过） |
| 产物根布局 | `<root>/{good_dy, good_xhs, bad_xhs, bad_wx}/` 各含 `report.json` + `REPORT.md`（四个样本名写死） |
| 检查 | 固定 6 项（名称冻结）：`good_fixtures_all_pass` / `bad_xhs_expected_fails` / `bad_wx_expected_fails` / `score_recompute` / `report_md_consistency` / `oracle_agreement_90pct`；判分口径见 spec.md §5 |
| stdout | JSON：`{"ok": bool, "summary": {total, pass, fail, tested_root, reference_root}, "checks": [{name, pass, detail}]}`；无时间戳（确定性） |
| exit 0 | 全部检查通过 |
| exit 1 | 任一检查失败 |
| exit 2 | 参数个数非 0/2（用法错误，信息走 stderr） |
| 依赖 | 仅 Python 标准库；无网络、无随机 |

## 4. fixtures 契约（输入基准，冻结）

四份 markdown 样例与平台组合、预期判定（与 `oracle/README.md` 预期分表一致）：

| fixture | 平台 | 预期总分 | 必须命中（供 eval check 2/3 判定） |
|---|---|---|---|
| `good_dy.md` | dy | 9/9 | 无 FAIL、无 WARN |
| `good_xhs.md` | xhs | 9/9 | 无 FAIL、无 WARN（emoji 5 个在 [2,15] 内） |
| `bad_xhs.md` | xhs | 4/9 | FAIL：title_length(25>20)、emoji_density(0<2)、tag_count(0<3)、banned_words(12词13次)、structure_cta |
| `bad_wx.md` | wx | 6/9 | FAIL：paragraph_max(422>350)、banned_words(6词6次)、structure_cta；WARN：emoji_density(22>20) |

fixtures 是判红的**输入基准**：改 fixtures 必须同步改 spec.md §2.1、contract §4 与 eval 预期。
`oracle/out/` 升级基线时：四样本名与产物文件名不变，逐项 `pass` 布尔与 score 须与本表一致。

## 5. 产物 schema（冻结）

### report.json（oracle 产出、eval 消费）

```json
{
  "tool": "evaluate.py 1.0.0",
  "input": "<输入文件绝对路径>",
  "platform": "xhs",
  "platform_label": "小红书",
  "generated_at": "2026-09-30T09:14:17+0800",     // 唯一非确定性字段
  "summary": {"applied": 9, "pass": 4, "fail": 5, "warn": 0},
  "score": {"passed": 4, "applied": 9, "ratio": 0.4444, "text": "4/9"},
  "checks": [{"name": "...", "pass": true, "warning": false, "detail": "..."}]  // 顺序=R2 冻结
}
```

- `score.ratio = round(passed/applied, 4)`；`summary.fail` = pass=false 计数；
  `summary.warn` = pass=true 且 warning=true 计数；警告不计失败、不扣分。
- 9 检查名顺序冻结：`title_length, emoji_density, body_length, paragraph_max,
  tag_count, banned_words, structure_hook, structure_cta, structure_para`。

eval 侧结构校验口径：顶层对象；`checks` 非空数组；元素 `name:str / pass:bool / detail:str`
（`warning` 可缺省，出现时须为 bool，缺省按 false 计警告口径）。

### REPORT.md（oracle 产出、eval 消费）

人读报告；机器依赖三个锚点（正则），须与 report.json 一致：

| 锚点 | 正则 | 对应 json 字段 |
|---|---|---|
| 总分 | `总分：(\d+/\d+)` | `score.text` |
| 汇总 | `应检 (\d+) 项，通过 (\d+) / 失败 (\d+) / 警告 (\d+)` | `summary.{applied,pass,fail,warn}` |
| 逐检查行 | ``\| `<name>` \| (✅ PASS\|❌ FAIL\|⚠️ WARN) \|`` | 逐项 `pass`/`warning`（pass=false→❌；pass 且 warning→⚠️；否则 ✅） |

其余结构（标题/五行元信息/表格/修改建议节）见 spec.md §3 R8。

## 6. 兼容性承诺

- 九检查项的名称集合与顺序不变；未来新增检查只能**追加在 checks 数组尾部**，
  eval 按 name 查找与复算，不受追加影响（`applied` 语义随之自然扩展）。
- 平台阈值表（spec.md §3 R3）与极限词表规模（44 词）不变；dy/wx 软上限、xhs 硬区间的
  warning 语义不变。
- 退出码语义不变（oracle 0/2；eval 0/1/2）。
- eval 六检查项名称与判定口径不变；`oracle_agreement_90pct` 阈值 0.90 不变。
