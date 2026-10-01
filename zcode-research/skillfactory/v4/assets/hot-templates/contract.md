# contract.md — hot-templates 模块契约（冻结）

> **版本：1.0**（2026-09-30，初版冻结）：spec.md / contract.md / eval/{runner.py, golden.json} 随
> oracle 参照引擎（gen.py + 8 份样例）一并固化。接口、命令行契约、检查项均以本文为准；
> 契约变更必须改本文件并升版本号，禁止静默变更。

本契约冻结**接口与目录布局**；`package/` 内的实现（代码怎么写、模板表放哪）自由，只要产物行为满足 `spec.md` 且评测 `eval/runner.py` 通过。契约变更必须改本文件并升版本号，禁止静默变更。

## 1. 资产根目录布局

```
hot-templates/
├── spec.md                  # 行为规格（随 oracle 行为冻结）
├── contract.md              # 本文件：模块契约（冻结）
├── inputs/                  # 8 份样例的实现者副本（与 oracle/inputs/ 字节一致，规范源仍为 oracle/inputs/）
│   └── <dy|xhs|wx|video>/case{1,2}.json
├── oracle/                  # 参照实现（只读，禁止改动其行为）
│   ├── gen.py               #   参照引擎（唯一入口，纯标准库）
│   ├── run_all.py           #   8 份样例批量驱动（子进程真实调用 gen.py CLI）
│   ├── verify.py            #   V1-V6 验收（存在性/自洽/确定性复跑/失败路径）
│   ├── README.md            #   oracle 用法
│   ├── inputs/<platform>/case{1,2}.json   # 黄金样例（规范源）
│   └── out/<platform>/case{N}/{骨架.md,structure.json}   # 参照产物（eval 的参照目录）
├── package/                 # 被测技能包（实现方交付物，布局见 §2）
│   ├── SKILL.md
│   ├── scripts/gen.py
│   └── out/<platform>/caseN/{骨架.md,structure.json}   # 被测产物（spec §8 D.1，先产出后评测）
└── eval/
    ├── golden.json          # 黄金集（schema 固定，见 §4）
    └── runner.py            # 确定性评测器（见 §5）
```

评测标准姿势（与本资产 howToRun 一致）：

```bash
# 参照产物若缺则补跑（规范源在 oracle/inputs/）：
python oracle/gen.py --platform dy --topic 时间管理 --points oracle/inputs/dy/case1.json --outdir oracle/out/dy/case1
# 被测产物（先产出后评测，spec §8 D.1）：
python package/scripts/gen.py --platform dy --topic 时间管理 --points inputs/dy/case1.json --outdir package/out/dy/case1
# 评测：
python eval/runner.py package/out oracle/out
```

> 运行目录注记：runner 与 golden.json、样例输入均按脚本自身位置/参数相对路径定位（golden 的
> `input` 路径相对**资产根**解析），不假设 CWD——已从工作区根（绝对路径调用）与资产根
> （相对路径调用）两种 CWD 实跑验证（spec §10）。workflow 执行器经目录联接调用
> `python skillfactory/v4/assets/hot-templates/eval/runner.py <被测> <参照>` 亦可。

> 输入样例注记：实现方生成被测产物时 `--points` 一律用 `inputs/<platform>/<caseN>.json`
> （资产根副本），无需触碰 `oracle/`。「禁止读取 oracle/」的隔离规则针对参照实现
> `oracle/gen.py` 与参照产物 `oracle/out/`；输入样例是评测材料。评测必须按资产布局以
> `oracle/out` 为参照目录运行（runner 检查 5 需要 `<参照>/<case>` 存在），参照目录不可移动或改名。

## 2. package/ 必须包含的文件

| 文件 | 必须 | 要求 |
|---|---|---|
| `SKILL.md` | ✅ | 结构见 §3；front-matter `name` 必须为 `hot-templates` |
| `scripts/gen.py` | ✅ | 命令行契约见 §2.1；自包含（仅依赖 Python 标准库） |
| `references/`、`assets/`、辅助模块 | ⛔ 可选 | 允许；但不得改变 §2.1 接口与 §1 布局约定 |
| `eval/`、`oracle/`、`inputs/` 的副本 | ⛔ 禁止 | package/ 内不得复制品目录（评测统一用资产根的 eval/ 与 oracle/，样例统一用资产根 inputs/） |

### 2.1 scripts 命令行契约（冻结）

```bash
python package/scripts/gen.py --platform <dy|xhs|wx|video> --topic <主题> --points <卖点json> --outdir <输出目录>
```

- 参数：四参数全部必填，语义与 spec §2（R1）一致；路径相对**当前工作目录**解析，脚本不得假设运行位置。
- 产物（固定文件名，写死在 `<outdir>/` 下）：`骨架.md` 与 `structure.json`，内容分别满足 spec §3A–§6。
- 退出码：成功 **0**（stdout 打印 `OK platform=… topic=… elements=… open_placeholders=… filled_from_input=… -> <outdir>` 一行）；参数非法（platform 非法 / topic 空 / points 不可解析、缺 points 键、非字符串列表、含非字符串项）**2**，且**不产生产物、不建输出目录**。
- 确定性（MUST）：同输入重复运行，两份产物**逐字节一致**（spec R2）。
- 依赖上限：Python 标准库。需要任何第三方依赖即违反契约。

## 3. SKILL.md 必备结构

按 `skillfactory/standard/SKILL-SPEC-v0.1.md` 的骨架，本技能包 SKILL.md 必须含以下节（顺序可调、内容不得缺）：

1. **front-matter**：至少 `name: hot-templates` 与 `description`（≤1024 字符，含触发短语，如「爆款骨架」「抖音口播」「小红书图文」「公众号文章」「短视频分镜」「口播稿」）。
2. **何时使用**：用户给出主题（可附卖点列表），需要抖音口播/小红书图文/公众号长文/短视频分镜四平台之一的爆款内容结构骨架时。
3. **输入格式**：platform 四值、非空 topic、卖点 JSON（文件路径或内联串；纯列表或含 `points` 键的对象）（引用 spec R1.4）。
4. **四平台模板表**：四平台结构名与要素清单（引用 spec §3A，或内联等价表：dy 6 要素 / xhs 7 要素 / wx 5 要素 / video 6 镜 45 秒）。
5. **使用步骤**：优先调用 `scripts/gen.py`（命令 + 成功判据：exit 0 且两产物存在；失败判据：exit 2 且无产物目录）。
6. **产物与验收**：`骨架.md` + `structure.json`；卖点规整策略（不足补 `【占位:价值点N】`、超出截断入 `points_unused`）；验收判据 = `python eval/runner.py <被测out> oracle/out` exit 0。
7. **边界**：非目标清单（引用 spec §7）与「`【占位:…】` 是留给使用者的开放槽位，禁止实现自行编造内容填充」红线。

## 4. eval/golden.json（schema 冻结）

顶层固定三键：`skill`、`eval_inputs`、`ab_tasks`。

```json
{
  "skill": "hot-templates",
  "eval_inputs": [
    {"case": "dy/case1", "input": "oracle/inputs/dy/case1.json", "output": "oracle/out/dy/case1"}
  ],
  "ab_tasks": [
    {"id": "ab-001", "instruction": "…自含全部生成材料…", "input": null, "rubric": ["…3-4 条可判定评分维度…"]}
  ]
}
```

- **路径基准**：`input`/`output` 相对资产根 `hot-templates/`；`case` 为产物根下的子目录路径（`<platform>/<caseN>`），同时用作 check name 前缀。
- `eval_inputs`：**恰 8 条**（dy/xhs/wx/video × case1/case2）；`output` 指向参照产物目录（`oracle/out/<case>`），与 `oracle/out/` 实际子目录一一对应。
- `ab_tasks`：**恰 5 条**；`instruction` 必须自含全部生成材料（platform、topic、points 内联写明），不依赖读取外部文件；`rubric` 每条 **3-4 条**可判定评分维度。当前覆盖：ab-001 dy 满 3 条、ab-002 xhs 5 条截断、ab-003 wx 0 条零卖点、ab-004 video 1 条缺失槽位、ab-005 确定性+失败路径工程验收。
- 冻结规则：修订 golden.json 必须在 CHANGELOG 记录并归档旧版；禁止为让实现通过而改断言。

## 5. eval/runner.py（接口冻结）

```bash
python eval/runner.py <被测输出目录> <参照输出目录>
# 例：python eval/runner.py package/out oracle/out
#     python eval/runner.py oracle/out oracle/out   （自校验，应 exit 0）
```

- 两参数必填；目录可相对当前工作目录。用例清单读 runner 同目录 golden.json 的 `eval_inputs`；每个 case 的样例输入按 golden 的 `input` 路径（相对资产根）定位，用于"样例数据填充"判定。
- 每个用例固定 5 项检查（check name 前缀为 case 名）：
  1. `artifacts_present` — `骨架.md` + `structure.json` 存在、非空、JSON 可解析；
  2. `structure_json_self_consistent` — 顶层 11 键/要素 9 键/统计 5 键齐全，`element_count==len(elements)`、`order` 从 1 连续、占位符重计数与 `open_placeholders`/`by_element`/`total_open`/`filled_slots`/`open_tokens_unique` 全部自洽（spec R5）；
  3. `platform_template_complete` — 平台冻结要素齐备：dy 含 `hook_3s` 与 `cta`（6 要素 id 序列）；xhs 标题含数字与 `🔥`、emoji 映射、标签数 3-8（7 要素）；wx 三段论标记 `一、是什么/二、为什么/三、怎么办`（5 要素）；video 四列分镜表头 `| 序号 | 时间轴 | 画面 | 口播 | 字幕 |` + 冻结时间轴 00:00-00:03…00:40-00:45 + 共 45 秒（6 镜）；并校验卖点规整（缺失槽位落 `【占位:价值点N】`、`points_used` 恒长 3、截断项与 `points_unused` 逐一相等）；
  4. `sample_data_filled_no_template_residue` — 样例 topic 出现在 md 且与 `structure.json.topic` 相等；前 3 条卖点出现在某要素 text、其余出现在 `points_unused`；两份产物无 `{{ }}` 模板残留；
  5. `structure_consistency_with_reference` — 与参照产物逐项比对（要素 id 序列；各要素 name/order/placeholder_count/open_placeholders；`element_count`/`template_version`/`platform`/`structure_name`/`points_used`/`points_unused`；`placeholder_stats` 三键；md 小节标题序列），**结构一致率 ≥90%** 判过，检查项附 `rate` 字段。
- 输出：stdout 打印 JSON `{"ok": <bool>, "summary": {"cases","checks_total","passed","failed","consistency_threshold","consistency_min"}, "checks": [{"name","pass","detail"(,"rate")},...]}`（ensure_ascii=false，indent 2）；全部 pass → exit 0，任一 fail → exit 1；参数缺失/golden 不可读 → exit 2（用法打印到 stderr）。
- 确定性：无随机、无网络、无时间依赖；对同一对目录重复运行结果一致。
- 只读承诺：runner 只读被测/参照/样例路径，不写任何文件。

## 6. 冻结与版本

- 本契约 1.0 冻结项：目录布局（§1）、package 契约（§2/§3）、golden schema 与条数（§4）、runner 接口与 5 项检查及 90% 阈值（§5）、产物文件名 `骨架.md`/`structure.json`、退出码语义（0/2）、`structure.json` 键集（spec R5）。
- 变更流程：改 contract.md/spec.md 并升版本号 + CHANGELOG.md 记录 + 归档旧 golden；`oracle/` 行为任何改动都视为 breaking。
