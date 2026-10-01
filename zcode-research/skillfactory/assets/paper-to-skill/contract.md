# contract.md — paper-to-skill 模块契约（冻结）

本契约冻结**接口与目录布局**；`package/` 内的实现（解析算法、模板措辞、规则表放哪）自由，只要产物行为满足 `spec.md` 且评测 `eval/runner.py` 通过。契约变更必须改本文件并升版本号，禁止静默变更。

## 1. 资产根目录布局

```
paper-to-skill/
├── spec.md                  # 行为规格（长期资产，随 oracle 行为冻结）
├── contract.md              # 本文件：模块契约（冻结）
├── oracle/                  # 参照实现（只读，禁止改动其行为）
│   ├── oracle.py            #   参照实现入口（仅标准库）
│   ├── inputs/source.md     #   黄金输入 1：agentskills.io 规范页正文（WebFetch 抓取稿）
│   ├── inputs/source-blog.md#   黄金输入 2：Anthropic 工程博客结构化提取稿
│   ├── out/                 #   参照产物 1：draft_skill/SKILL.md + outline.json（黄金期望）
│   ├── out-blog/            #   参照产物 2：同上（blog 例）
│   └── out-repeat/          #   确定性验证残留（与 out 仅差内嵌 --outdir 文本，留档）
├── package/                 # 被测技能包（实现方交付物，布局见 §2）
│   ├── SKILL.md             #   蒸馏器技能自述（本技能怎么用）
│   ├── scripts/distill.py   #   确定性蒸馏脚本（CLI 契约见 §2.1）
│   ├── example/SKILL.md     #   示范产物（A/B treatment 组先读它再写，见 §6）
│   └── out/  out-blog/      #   评测时生成：对两个黄金输入跑 distill.py 的产物
└── eval/
    ├── golden.json          # 黄金集（schema 固定，见 §4）
    ├── runner.py            # 确定性评测器（接口冻结，见 §5）
    └── ab_briefs/           # A/B 任务的 capability 简报（batch-rename / weekly-report）
```

评测标准姿势（与本资产 howToRun 一致；参照产物若缺则先补跑 oracle）：

```bash
cd paper-to-skill
python oracle/oracle.py --source oracle/inputs/source.md --outdir oracle/out --url https://agentskills.io/specification
python oracle/oracle.py --source oracle/inputs/source-blog.md --outdir oracle/out-blog --url https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
python package/scripts/distill.py --source oracle/inputs/source.md --outdir package/out --url https://agentskills.io/specification
python package/scripts/distill.py --source oracle/inputs/source-blog.md --outdir package/out-blog --url https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
python eval/runner.py package/out oracle/out            # spec 例评测
python eval/runner.py package/out-blog oracle/out-blog  # blog 例评测
python eval/runner.py oracle/out oracle/out             # 自校验（应 exit 0）
```

## 2. package/ 必须包含的文件

| 文件 | 必须 | 要求 |
|---|---|---|
| `SKILL.md` | ✅ | 蒸馏器技能自述；结构满足 §3 五要素；description 为触发描述（用户给出论文/规范/长文档、需要转成技能草稿时触发） |
| `scripts/distill.py` | ✅ | 命令行契约见 §2.1；行为满足 spec R1–R7；自包含（仅 Python 标准库） |
| `example/SKILL.md` | ✅ | 示范产物：一份针对某个具体能力写的、满足 §3 五要素的高质量 SKILL.md；是 runner check 1/2 的判定对象与 A/B treatment 组的先读材料；**内容不得整段复制 agentskills.io / Anthropic 官方文案** |
| `references/`、`assets/`、辅助模块 | ⛔ 可选 | 允许；但不得改变 §2.1 接口与 §1 布局约定 |
| `eval/`、`oracle/` 的副本 | ⛔ 禁止 | package/ 内不得复制品目录（评测统一用资产根的 eval/ 与 oracle/） |

### 2.1 scripts 命令行契约（冻结）

```bash
python package/scripts/distill.py --source <来源.md> --outdir <输出目录> [--url <来源URL>]
```

- 参数：`--source`（必填，来源 Markdown 路径）、`--outdir`（必填，输出目录，不存在自动创建）、`--url`（可选，来源 URL）。与 oracle 同名同义；路径相对**当前工作目录**解析。
- 产物（固定相对路径，写死）：`<outdir>/draft_skill/SKILL.md` 与 `<outdir>/outline.json`。
- 退出码：成功 0；源文件不存在/不可读非 0 且**不产出半成品、不创建输出目录**。
- 行为满足 spec 全部规则（预处理 R2、切分 R3、统计 R4、标题树 R5、SKILL.md 五要素生成 R6、确定性 R7）。
- 确定性：同输入＋同参 → `outline.json` 字节一致；`SKILL.md` 仅允许因 `--outdir` 内嵌文本产生的差异（spec R7.2）。
- 依赖上限：仅 Python 标准库。引入任何第三方依赖即违反契约。
- 实现自由：内部解析/生成算法可与 oracle 不同，只需 runner check 3 的各项统计与参照偏差 ≤30% 且五要素齐全。

## 3. SKILL.md 必备结构（五要素）

参照 `skillfactory/standard/SKILL-SPEC-v0.1.md` 的骨架，本资产的 SKILL.md（含 `package/SKILL.md`、`package/example/SKILL.md` 与蒸馏产物 `draft_skill/SKILL.md`）必须含以下五要素。**判定正则即 runner 实现，顺序可调、内容不得缺**：

1. **front-matter**：首行为 `---`，且前 30 行内出现闭合 `---`；其间有 `name:` 与 `description:` 行。`name` 遵守 agentskills.io 规范（小写字母/数字/连字符，≤64，无首尾/连续连字符）。
2. **触发描述**：`description:` 值（去引号去空白）长度 ≥20 字符，说明**何时触发**本技能（触发场景＋适用输入）。
3. **分步方法**：存在标题行匹配 `^#{1,6}\s+.*(分步|步骤|steps)`（忽略大小写）；节内（至下一个标题行）有 **≥2 条编号步骤**（`^\s*\d+[.、)]\s+\S`），且**每步可判定**——步骤行含下列至少一项标记：
   - 溯源标记：`原文 L<数字>`（oracle 产物格式）；
   - 成对反引号包裹的命令或路径（如 `` `python scripts/distill.py --source <md> --outdir <dir>` ``）；
   - 产物文件名：含 `.py`/`.md`/`.json`/`.txt`/`.csv`/`.docx`/`.pptx`/`.xlsx` 扩展名。
4. **常见坑**：存在标题行匹配 `^#{1,6}\s+.*(坑|注意|pitfalls?|caveats?)`（忽略大小写），其下有实质条目（不得只有空节）。
5. **来源引用**：存在标题行匹配 `^#{1,6}\s+.*(来源|引用|参考|sources?|references?)`（忽略大小写）。

> 例：oracle 产物的「能力范围」节满足第 2 要素由 front-matter description 承担；五要素顺序不要求固定，但每要素的**识别特征**如上，不得改成无法识别的措辞。判定均为按行正则匹配；围栏代码块（``` / ~~~）内的行不计入标题与步骤判定。

## 4. eval/golden.json（schema 冻结）

顶层固定三键：`skill`、`eval_inputs`、`ab_tasks`。

```json
{
  "skill": "paper-to-skill",
  "eval_inputs": [
    {"case": "spec", "input": "oracle/inputs/source.md", "output": "oracle/out"},
    {"case": "blog", "input": "oracle/inputs/source-blog.md", "output": "oracle/out-blog"}
  ],
  "ab_tasks": [
    {"id": "ab-001-rename", "instruction": "…具体到任务本身…", "input": "eval/ab_briefs/batch-rename-brief.md", "rubric": ["…3–5 条可判定评分维度…"]},
    {"id": "ab-002-weekly-report", "instruction": "…", "input": "eval/ab_briefs/weekly-report-brief.md", "rubric": ["…"]}
  ]
}
```

- **路径基准**：所有路径相对资产根 `paper-to-skill/`。
- `eval_inputs`：每条 = 一个黄金用例；`input` 指向 oracle/inputs/ 样例，`output` 指向期望产物目录（与 `oracle/` 下实际目录名一致）。runner 单次评一对目录，两个用例分别以 `package/out`、`package/out-blog` 调用（见 §1 姿势）。
- `ab_tasks`：恰 2 条（批量重命名 / 周报骨架）；`instruction` 写给执行 agent 的具体任务；`input` 为该任务的 capability 简报文件；`rubric` 3–5 条可判定评分维度。
- 冻结规则：修订 golden.json 必须在 CHANGELOG 记录并归档旧版；禁止为让实现通过而改断言。

## 5. eval/runner.py（接口冻结）

```bash
python eval/runner.py <被测输出目录> <参照输出目录>
# 例：python eval/runner.py package/out oracle/out          # 评被测实现（spec 例）
#     python eval/runner.py package/out-blog oracle/out-blog # blog 例
#     python eval/runner.py oracle/out oracle/out            # 自校验（应 exit 0）
```

- 两参数必填（缺省 exit 2）；目录相对当前工作目录。
- 用例标签：参照目录与 golden.json `eval_inputs[].output` 匹配时取其 `case` 名，否则记 `ad-hoc`（不阻止评测）。
- **SKILL.md 判定对象解析序**（固定）：① 被测目录的兄弟 `example/SKILL.md`（`package/out` → `package/example/SKILL.md`）；② 兜底：被测目录内 `draft_skill/SKILL.md`（自校验/ad-hoc 模式下评 oracle 自己的产物）；都不存在则 check 1/2 失败。
- 固定 3 项检查（check name 冻结）：
  1. `example_skill_md_complete` — 判定对象存在且五要素齐全（按 §3 的判定正则：front-matter 含 name+description、description 值 ≥20 字、分步方法/常见坑/来源引用标题可识别）；
  2. `steps_actionable` — 分步方法节内编号步骤 ≥2，且每步含可判定标记（`原文 L数字` / 成对反引号 / 产物扩展名）；
  3. `outline_stats_within_30pct` — 被测与参照 `outline.json` 存在且可解析；以参照 stats 的全部**数值键**为清单，被测缺失任一键即失败；每键偏差 `|被测−参照| / max(|参照|,1)` ≤ **0.30**（`code_block_languages` 等非数值键不比）。
- 输出：stdout 打印 JSON `{"ok": <bool>, "case": "<case名|ad-hoc>", "checks": [{"name","pass","detail"},...]}`（ensure_ascii=false）；全部 pass → exit 0，任一 fail → exit 1（失败明细随 checks 打印）。
- 确定性：无随机、无网络、无时间依赖；对同一对目录重复运行结果逐字一致。

## 6. A/B 对照协议（golden.ab_tasks 的用法）

- 每个任务跑两组：**treatment 组**先完整阅读 `package/example/SKILL.md` 再写；**baseline 组**不给任何示例直接写。
- 两组收到**完全相同**的 `instruction` 与 `input`（capability 简报，见 `eval/ab_briefs/`），产出写到各自指定的输出目录。
- 评分按各自 `rubric` 逐条判定（每条 0/1），对比两组总分：treatment 显著高于 baseline ⇒ 证明 example 的教学价值；两组无差 ⇒ example 需改进。
- rubric 判定允许人工或 LLM 评审，但每条维度必须可判（有明确的是/否口径），不得使用"写得更好"这类不可判定表述。
