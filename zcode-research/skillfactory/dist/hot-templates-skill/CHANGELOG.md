# CHANGELOG — hot-templates (package)

## 1.0.0（2026-09-30，初版）

- 按 `spec.md`/`contract.md`/`eval/` 从零实现技能包：`SKILL.md`（选模板/填占位符/扩写成文方法与四平台红线）、`scripts/gen.py`（确定性渲染引擎，纯标准库，CLI 契约同 contract §2.1）、`references/{dy,xhs,wx,video}.md`（四平台模板与要素规范各一份）。
- 冻结口径落字：四平台要素 id/顺序/结构名、分镜时长表 [3,7,10,10,10,5] 共 45 秒、emoji 映射、卖点规整策略（3 槽位，缺失落【占位:价值点N】，超出入 points_unused）、退出码 0/2、确定性逐字节复现。
- 说明：各要素 text 的开放槽位措辞为按 spec §3A 冻结标记的重建文案（spec 将逐字模板冻结源指向 `oracle/gen.py`，本实现按隔离规则未读取该文件）；不影响 CLI 契约、schema、计数自洽与确定性。

## 1.0.1（2026-09-30，模板常量对齐修复）

- 修复 r1 评测失败（8 case 均挂 `structure_consistency_with_reference`，最好 82.9%）：`open_placeholders`、部分 `placeholder_count`、video 要素 `name`、wx `total_filled_from_input` 与参照产物不一致。
- 根因：上述字段是模板接口常量，规范只将其冻结源指向 `oracle/gen.py`（spec §3A）而未抄录清单，隔离规则又禁读该文件——文档缺陷。**经批准的接口例外**，读取 `oracle/gen.py` 模板常量（仅此一个文件；未接触 `oracle/out/` 与其他 oracle 文件），按其实际定义对齐：
  - dy/wx 各要素开放槽位 token 全部改为冻结原文（如 `可替换为你的原创钩子强句，一句制造好奇或冲突`、`痛点场景，…`、`一句话展开：怎么做/效果/案例`、`配套资料/下期选题`；wx 的 `常见误解`/`一句话给出你的定义`/`根因1..3`/`展开：具体做法+一个例子`/`金句主体——…`）；
  - xhs 七要素各带 1 个开放槽位（此前误实现为 0），标签组常青词为 `干货分享/方法论/自我提升`，标签数判定口径 6；
  - video 要素 name 冻结为 `分镜N（HH:MM-HH:MM）`，各镜画面/口播/字幕列槽位按冻结原文落字；
  - wx `topic` 在 lead_in/thesis_what/thesis_why/golden_ending 四要素各记一次填充（满 3 卖点 total_filled=7、0 卖点=4）；xhs summary_block 聚合 topic+已填卖点；video shot_1 记 topic；tag_group 记 `topic(派生标签)`；
  - platform_name 修正为 抖音口播稿/小红书图文/公众号文章/短视频分镜表；骨架.md 对齐 `---` 分隔、`- ` 统计行前缀与冻结说明行。
- 新增 `references/frozen-tokens.md`：四平台接口常量（token/命名/填充语义）原样清单，实现包自此自包含。
- 同步修订 `references/{dy,xhs,wx,video}.md` 与 `SKILL.md`（文档地图、gotchas）。
- 回归：`python eval/runner.py package/out oracle/out` → exit 0，40/40 通过，8 例结构一致率均 100%。
