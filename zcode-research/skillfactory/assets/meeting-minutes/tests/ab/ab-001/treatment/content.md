# ab-001 treatment 产物说明（meeting-minutes 技能 · case1 618 大促备战会）

- 输入：`skillfactory/assets/meeting-minutes/oracle/inputs/case1.txt`（12 行发言，UTF-8）
- 实现路径（本轮实跑）：按 `package/SKILL.md` 执行——先完整读取 SKILL.md 与三份 references（classification-rules / extraction-heuristics / docx-and-summary）及 scripts/minutes.py，再运行契约入口：
  ```
  python package/scripts/minutes.py --input oracle/inputs/case1.txt --outdir tests/ab/ab-001/treatment
  ```
  退出码 0，打印 `OK ... 决议 2 · 待办 2 · 风险 3 · 合计 7`；随后 ls 回读确认 `纪要.docx` 与 `summary.json` 均存在（SKILL 成功判据「写后回读三态」）。
- 产物：本目录下 `纪要.docx` + `summary.json`（固定文件名）+ `content.md`（本文，供评审）

## 归类依据（机械规则，非语义判断）

| 行 | 判定 | 依据 |
|---|---|---|
| 09:00 主持人 | 排除 | 无 11 关键词命中（寒暄开场） |
| 09:01 王磊 | 排除 | 无关键词命中（压测结果过场发言） |
| 09:02 王磊 | 决议① | 含「结论」（决议关键词） |
| 09:04 陈静 | 排除 | 无关键词命中（预算过场发言） |
| 09:05 刘洋 | 待办① | 含「需要」；负责人 4 规则未命中→待定；期限规则 3 命中「周五前」 |
| 09:06 主持人 | 决议② | 含「议定」 |
| 09:08 陈静 | 风险① | 含「风险」 |
| 09:09 刘洋 | 风险② | 含「延期」 |
| 09:10 主持人 | 风险③ | 含「延期」（否定词不影响归类，「不能延期」归风险，SKILL 已知可接受的「错」） |
| 09:12 王磊 | 排除 | 口误更正行，无关键词命中，不做上下文关联 |
| 09:13 王磊 | 待办② | 含「需要」；负责人/期限全规则未命中→均待定 |
| 09:15 主持人 | 排除 | 散会行，无关键词命中（只看关键词不看行位置） |

条数：决议 2 · 待办 2 · 风险 3 · 合计 7。

## 纪要.docx 完整文本（python-docx 逐段/逐格回读）

- P0（标题，居中 18pt 加粗）：`会议纪要`
- P1（元信息行）：`来源：case1.txt ｜ 解析发言 7 条（决议 2 · 待办 2 · 风险 3）`
- P2（节标题，14pt 加粗）：`一、决议事项`
  - P3：`1. 【09:02 · 王磊】优惠券模块还有两个已知问题，我们内部的结论是必须在上线前修完。`
  - P4：`2. 【09:06 · 主持人】好，这个方案就议定下来，费用走大促专项。`
- P5（节标题，14pt 加粗）：`二、待办事项`
  - 表格 T0（样式 Table Grid，3 列）：
    | 事项 | 负责人 | 期限 |
    |---|---|---|
    | 客服侧需要临时增加二十个坐席，我周五前把名单给到外包公司。 | 待定 | 周五前 |
    | 准确数字是下单接口7500，优惠券接口还有瓶颈，我需要再压一轮。 | 待定 | 待定 |
- P6（节标题，14pt 加粗）：`三、风险与关注`
  - P7：`1. 【09:08 · 陈静】有个风险要提示，物流侧去年大促爆过仓，今年单量预计还要涨三成。`
  - P8：`2. 【09:09 · 刘洋】我补充一句，万一华东仓爆仓，能不能延期发货？`
  - P9：`3. 【09:10 · 主持人】不行，48小时发货的承诺不能延期，我们要提前把运力锁掉。`

全文正文 run 字体显式设为宋体（含 w:eastAsia）。决议/风险条目格式为 `<i>. 【hh:mm · 说话人】原句`，内容逐字引用 case1.txt 原句，无改写、无编造；抓不到的负责人/期限如实填「待定」（extraction-heuristics.md R4/R5，红线：禁止语义推断）。

## summary.json（原样）

```json
{
  "决议事项": 2,
  "待办事项": 2,
  "风险与关注": 3,
  "合计": 7
}
```

恰四键（决议事项/待办事项/风险与关注/合计），数值与 docx 实际条数逐项一致，合计 = 三类之和 = 元信息行「解析发言 7 条」。

## 验收记录（本轮实跑）

1. **生成回读**：`python package/scripts/minutes.py --input oracle/inputs/case1.txt --outdir tests/ab/ab-001/treatment` → 退出码 0；`ls` 回读两产物存在。
2. **技能验收（SKILL 步骤 2）**：`python eval/runner.py tests/ab/ab-001/treatment/_staging oracle/out`（资产根下执行）→ 退出码 0、`"ok": true`，20/20 项检查通过；case1 五项全过：三节标题齐全／待办表格表头=['事项','负责人','期限'] 共 2 数据行／summary 与 docx 实际一致（决议 2 段、待办 2 行、风险 3 段）／7 条目全部在 oracle/inputs/case1.txt 逐字溯源（含时间+说话人）／与参照 oracle/out/case1 各类差值全 0。_staging 为同一脚本对 golden 4 用例的产物（eval runner 要求 `<case>/` 布局）；已核对顶层 `纪要.docx`/`summary.json` 与 `_staging/case1` 段落+表格文本逐字一致、summary 数值一致（`_verify_rubric_ab001.py` 一致性检查 PASS）。
3. **rubric 专项校验**：`python _verify_rubric_ab001.py`（作用于顶层交付产物）→ 18/18 全 PASS、退出码 0，覆盖 rubric 五维度：①三节标题逐字精确且顺序正确、docx 可被 python-docx 打开；②决议 2/待办 2/风险 3（含「不能延期」行归风险）、summary 四键与 docx 一致、合计=7；③待办 3 列表格、表头含事项/负责人/期限、数据行 2；④每条目【时间 · 说话人】前缀 + 原句逐字溯源（决议/风险 5 条 + 待办事项列 2 行全部命中出处行）；⑤5 行噪声（09:00/09:01/09:04/09:12/09:15）全文零命中。

> 注：首轮专项校验曾报 3 项 FAIL，系校验脚本自身把 list `<=` 误用作子集判断（Python 3 中对 list 是字典序比较）导致表头检测失败；修正为 set 子集判断后全 PASS。产物本身自始未变。

## 目录内文件清单

| 文件 | 性质 |
|---|---|
| `纪要.docx` | 最终产物（本轮生成） |
| `summary.json` | 最终产物（本轮生成） |
| `content.md` | 本说明（评审用，本轮重写） |
| `_verify_rubric_ab001.py` | 中间文件：本轮 rubric 专项校验脚本（18 项检查） |
| `_staging/case1..4/` | 中间文件：eval/runner.py 所需 `<case>/` 布局（本轮由 `_stage_and_eval.py` 重新生成；case1 与顶层产物同源同文本） |
| `_stage_and_eval.py` | 中间文件：本轮实跑（复制 case1 产物入 `_staging`、生成 case2..4、调用 eval/runner.py 并做确定性比对） |
| `_verify_readback.py` | 上一轮遗留的流程脚本，本轮未改动、未依赖 |
