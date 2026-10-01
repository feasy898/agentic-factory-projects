# healthcheck — skill 包体检工具

对任意 skill 包目录做结构校验并产出体检报告（`report.json` + `REPORT.md`）。
标准库实现（Python ≥3.10，win32 实测 3.12.10），无第三方依赖、无网络、无随机。

## 用法

```
python healthcheck.py --target <skill包目录> --out <报告目录>
```

| 项 | 说明 |
|---|---|
| `--target` | 必填。被体检的 skill 包目录；**不是目录（含不存在）时 stderr 报错，exit 2，不创建 `--out`、不写任何产物** |
| `--out` | 必填。报告输出目录，写出 `<out>/report.json` 与 `<out>/REPORT.md`（目录不存在则创建） |
| 退出码 | `0` = 报告已写出（**无论红绿**，体检工具只报告不设门）；`2` = 参数缺失或 `--target` 不是目录。没有 exit 1 |

## 检查项（恰 5 项，顺序固定）

| # | 名称 | 判定 |
|---|---|---|
| 1 | `skill_md_exists` | `<target>/SKILL.md` 是普通文件 → PASS（detail 含字节数）；否则 FAIL「包根未找到 SKILL.md」 |
| 2 | `front_matter_fields` | SKILL.md 以 `---` 行起始的 front-matter 块，行级 `key: value` 解析（非完整 YAML；容忍 \r\n 与 BOM；utf-8-sig 优先、失败回退 gbk）；五字段 `name`/`version`/`license`/`description`/`permissions` 非空 → PASS；缺字段 FAIL，detail「front-matter 缺字段: <缺的>（已有: <有的>）」 |
| 3 | `eval_present` | `<target>/eval/` 是目录 → PASS「eval/ 目录存在」；否则 FAIL「缺少 eval/ 目录（无确定性评测）」 |
| 4 | `eval_smoke` | 查找 runner：`eval/runner.py` > `run.py` > `eval.py` > `main.py` > eval/ 顶层按文件名排序首个 `*.py`。存在 `<target>/reference/out` 或 `<target>/eval/reference/out` → `python <runner> <ref> <ref>`（dist 自校验约定），否则 `python <runner> --help`；cwd=`<target>`、timeout 60s、`PYTHONIOENCODING=utf-8`。exit 0 → PASS（detail 含 cmd 与 stdout 摘要）；非 0/超时/无法启动 → FAIL（detail 记 cmd、exit_code、摘要，空白压缩截尾 400 字符）。**无 runner → PASS 且 detail 以 `skip:` 开头**（单次确定性调用，不重试掩蔽） |
| 5 | `scripts_syntax` | 递归遍历 `<target>/scripts/`（跳过 `__pycache__`），每个 `*.py` 以 utf-8-sig 读入后 `compile()`。目录缺失 FAIL「scripts/ 目录不存在」；无 py 文件 FAIL「scripts/ 下没有 *.py 文件」；任一失败 FAIL「N/M 个脚本语法不过: <相对路径>: 第X行 SyntaxError: <msg>; …」；全过 PASS「scripts/ 下 N 个 *.py 全部语法可编译: <文件列表>」 |

## 评级规则（写死）

```
评级 = f(失败检查数)     # fail = pass=false 的项数；skip（eval_smoke 无 runner）不算失败
0 失败 → A；1 失败 → B；≥2 失败 → C
```

评级同时写入 `report.json` 的 `rating` 字段与 `REPORT.md` 的「评级：**X**」行（机器锚点正则
`评级：\*\*([ABC])\*\*`）。A=包结构完好可分发；B=单项红（典型：缺 eval/）；C=多项红，分发前必须整改。

## 产物 schema

**report.json**（UTF-8、`ensure_ascii=False`、`indent=2`、结尾换行）：

```json
{
  "tool": "healthcheck.py 1.0.0",
  "target": "<target 绝对路径>",
  "generated_at": "2026-09-30T03:57:24+0800",
  "summary": {"total": 5, "pass": 5, "fail": 0},
  "rating": "A",
  "checks": [{"name": "…", "pass": true, "detail": "…"}]
}
```

`generated_at` 是唯一非确定性字段；其余内容同一 target 重复运行逐字节一致。
**REPORT.md**：标题 `# Skill Healthcheck Report` + 四行元信息（目标包/生成时间/评级/汇总）+
检查表格（`| 检查项 | 结果 | 说明 |`，✅ PASS / ❌ FAIL）+ `## 建议` 节（评级建议一句 + 逐失败项一条）。

## 目录内容与本包自测

```
package/
├── healthcheck.py   # 本工具
├── README.md        # 本文件
├── fixtures/        # 阴性对照样本副本（勿分发到正式包）
│   ├── broken-skill/   # front-matter 缺 version/license/permissions + bad_syntax.py + 无 eval/ → 评级 C
│   └── no-eval/        # 五字段齐全 + 脚本正常 + 无 eval/ → 仅 eval_present 红，评级 B
└── out/             # 对三个样本（meeting-minutes-skill / broken-skill / no-eval）的体检产物
```

复现自测（在仓库根 `skillfactory` 下）：

```
python v3/tools/healthcheck/package/healthcheck.py --target dist/meeting-minutes-skill --out v3/tools/healthcheck/package/out/meeting-minutes-skill
python v3/tools/healthcheck/package/healthcheck.py --target v3/tools/healthcheck/fixtures/broken-skill --out v3/tools/healthcheck/package/out/broken-skill
python v3/tools/healthcheck/package/healthcheck.py --target v3/tools/healthcheck/fixtures/no-eval --out v3/tools/healthcheck/package/out/no-eval
python v3/tools/healthcheck/eval/runner.py v3/tools/healthcheck/package/out v3/tools/healthcheck/oracle/out
```

预期三样本评级 A / C / B，eval runner 五项检查全过 exit 0。

## 边界（不做的事）

- 不做完整 YAML 解析（行级 `key: value`，嵌套/锚点/多行标量不支持）。
- smoke 单次确定性调用：无多策略重试、无失败掩蔽；超时/非零只记录，不中断整体。
- 只报告不设门：红绿都 exit 0，是否拦截由调用方决定。
- 不评估 SKILL.md 正文质量；不校验被测 eval runner 的判定逻辑（只看 exit code）。
