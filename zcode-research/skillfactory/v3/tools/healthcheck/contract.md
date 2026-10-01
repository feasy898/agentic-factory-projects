# contract.md — healthcheck 资产接口契约

> 接口冻结，实现自由：本文件列的是「必须不变」的命令行、文件布局与产物 schema；
> 内部实现（解析方式、代码组织）可自由替换，只要黑盒行为满足 spec.md。

## 1. package 必备文件（分发形态 = 本目录整体）

```
skillfactory/v3/tools/healthcheck/
├── spec.md            # 规格（行为规则逐条可判定）
├── contract.md        # 本文件（接口契约）
├── eval/
│   └── runner.py      # 确定性评测器（§3 契约）
├── oracle/
│   ├── healthcheck.py # 参照实现（§2 契约）
│   └── out/           # 基线产物：{meeting-minutes-skill,broken-skill,no-eval}/{report.json,REPORT.md}
└── fixtures/          # 阴性对照（§4）
    ├── broken-skill/{SKILL.md, scripts/bad_syntax.py}
    └── no-eval/{SKILL.md, scripts/ok.py}
```

必备 = 上表全部文件存在且各自满足对应节契约；缺任一即资产不完整。
`oracle/out/` 为评测参照产物，**只读**，重跑体检不得写回此处。

## 2. oracle CLI 契约（冻结）

```
python oracle/healthcheck.py --target <skill包目录> --out <报告目录>
```

| 项 | 契约 |
|---|---|
| 参数 | `--target`、`--out` 均必填 |
| exit 0 | 报告已写出（无论红绿；体检工具只报告不设门） |
| exit 2 | `--target` 不是目录（含不存在）；此时不得创建 `--out`、不得写任何产物 |
| 产物 | `<out>/report.json` + `<out>/REPORT.md`，schema 见 §5 |
| 行为 | 恰 5 项检查（名称与顺序冻结）、评级 A/B/C 规则冻结 —— 细则见 spec.md §3 R2–R10 |

## 3. eval runner CLI 契约（冻结）

```
python eval/runner.py [<被测产物根> <参照产物根>]
```

| 项 | 契约 |
|---|---|
| 缺省（零参数） | 被测 = 参照 = `<runner 目录>/../oracle/out`（自校验，应全过） |
| 产物根布局 | `<root>/{meeting-minutes-skill, broken-skill, no-eval}/` 各含 `report.json` + `REPORT.md`（三个样本名写死） |
| 检查 | 固定 5 项（名称冻结）：`meeting_minutes_all_pass` / `broken_skill_expected_fails` / `no_eval_eval_present_fail` / `rating_consistency` / `oracle_agreement_90pct`；判分口径见 spec.md §5 |
| stdout | JSON：`{"ok": bool, "summary": {total, pass, fail, tested_root, reference_root}, "checks": [{name, pass, detail}]}`；无时间戳（确定性） |
| exit 0 | 全部检查通过 |
| exit 1 | 任一检查失败 |
| exit 2 | 参数个数非 0/2（用法错误，信息走 stderr） |
| 依赖 | 仅 Python 标准库；无网络、无随机 |

## 4. fixtures 契约（阴性对照，冻结）

| 样本 | 构造 | 必须触发的红项（供 eval check 2/3 判定） |
|---|---|---|
| `fixtures/broken-skill` | front-matter 缺 version/license/permissions；scripts/bad_syntax.py 含语法错误；无 eval/ | `front_matter_fields`=FAIL、`scripts_syntax`=FAIL（另 eval_present=FAIL，评级 C） |
| `fixtures/no-eval` | front-matter 五字段齐全、脚本语法正常、无 eval/ | `eval_present`=FAIL（唯一红项，评级 B，eval_smoke=skip） |

fixtures 是判红的**输入基准**：改 fixtures 必须同步改 spec.md §2.1 与 eval 预期。

## 5. 产物 schema（冻结）

### report.json（oracle 产出、eval 消费）

```json
{
  "tool": "healthcheck.py 1.0.0",
  "target": "<target 绝对路径>",
  "generated_at": "2026-09-30T03:57:24+0800",   // 唯一非确定性字段
  "summary": {"total": 5, "pass": 5, "fail": 0}, // fail = pass=false 计数
  "rating": "A",                                  // A=0 败 / B=1 败 / C=≥2 败
  "checks": [{"name": "...", "pass": true, "detail": "..."}]  // 顺序=R2 冻结
}
```

eval 侧结构校验口径：顶层对象；`checks` 非空数组；元素 `name:str / pass:bool / detail:str`。

### REPORT.md（oracle 产出、eval 消费）

人读报告；机器只依赖一个锚点：`评级：**X**`（X∈{A,B,C}，正则 `评级：\*\*([ABC])\*\*`），
须与 report.json 失败数推导评级一致。其余结构（标题/四行元信息/表格/建议节）见 spec.md §3 R10。

## 6. 兼容性承诺

- 五检查项的名称集合与顺序不变；未来新增检查只能**追加在 checks 数组尾部**，eval 按 name 查找，不受追加影响。
- 评级字母集 {A,B,C} 与「按失败数」规则不变；skip 永不计入失败数。
- 退出码语义不变（oracle 0/2；eval 0/1/2）。
- `oracle/out/` 升级基线时：三样本名与产物文件名不变，逐项 pass 布尔与评级须与 spec.md §2.1 表一致。
