# meeting-minutes-skill

**会议转写稿 → 三段式纪要（Word）**：把 `[hh:mm] 说话人: 内容` 格式的会议口语转写稿，确定性地整理成一份可直接归档的 **纪要.docx**——

- 一、决议事项（编号条目）
- 二、待办事项（表格：事项 / 负责人 / 期限）
- 三、风险与关注（编号条目）
- 附 `summary.json` 四键条数统计

两条设计红线（也是它区别于"让大模型随手总结"的地方）：

1. **条目逐字引用转写原句**——禁止改写、摘要、合并或编造；每条带【时间·说话人】出处前缀，可回溯。
2. **负责人/期限只按确定性规则从原句提取**——启发式抓不到一律填「待定」，绝不语义猜测。

## 快速开始

依赖：Python 3.8+，`pip install python-docx`

```bash
# 1. 用官方引擎生成纪要（输入格式见 reference/inputs/case*.txt）
python scripts/minutes.py --input reference/inputs/case1.txt --outdir out/case1

# 2. 机器自检（5 项确定性检查，4 个官方样例全跑）
python eval/runner.py out reference/out
```

`eval/runner.py` 检查：docx 可打开且三节齐全 / 待办表格含负责人与期限列 / summary 条数与文档实际一致 / 每条目可在转写稿逐字溯源 / 与参照产物条数差 ≤2。全部通过 exit 0。

## 作为 agent skill 使用

把本目录放进你的 agent 技能目录（Claude Code / Codex CLI / TRAE / Qoder 等 SKILL.md 兼容宿主均可），agent 读取 `SKILL.md` 后即可按其工作流程处理"整理会议纪要"类请求。渐进披露：主说明在 `SKILL.md`，细则在 `references/`（分类规则 / 抽取启发式 / docx 与 summary 规格）。

## 评测报告（本技能自带体检报告）

见 [EVALUATION.md](EVALUATION.md)：同模型有无技能对照盲评，三轮独立复验 delta 分别为 **+3.67 / +1.67 / +4.33**（终轮基线 5.7 → 治疗 10.0，胜率 100%）；确定性评测 5 项机器检查全绿，评测脚本随包附带，任何人可复跑验证。v0.2 加厚复验（8 任务双臂双重复）达标：**Δ +5.25、任务级胜率 100%（8/8）、反向任务 0**（v0.2 复合验收线通过，见 EVALUATION.md「三、v0.2 加厚复验」）。

## 目录结构

```
SKILL.md            技能说明（agent 读这个）
scripts/minutes.py  确定性引擎（契约入口）
scripts/gen_docx.py 等价别名入口
references/         分类规则 / 抽取启发式 / 产物规格
eval/               确定性评测器 + 黄金集清单
reference/          官方样例（inputs 转写 ×4 + out 参照产物 ×4）
EVALUATION.md       盲评实测报告
CHANGELOG.md        变更记录
requirements.txt    依赖清单（python-docx）
LICENSE             MIT
MANIFEST.md         包内容清单
```

## 边界

- 输入须是文字转写稿（`[hh:mm] 说话人: 内容` 逐行）；音频转文字请先交给语音转写工具。
- 不做叙事式会议新闻稿或自由摘要写作——它是纪要工具，不是写作工具。
