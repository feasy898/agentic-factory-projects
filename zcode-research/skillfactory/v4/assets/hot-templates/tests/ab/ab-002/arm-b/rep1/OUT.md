# OUT.md — hot-templates 产物交付（ab-002 / arm-b / rep1）

- **日期**：2026-09-30
- **平台**：小红书图文（xhs）
- **主题**：租房避坑指南
- **冻结模板**：标题带数字 + emoji规则 + 正文分块 + 标签组（7 要素，template_version 1.0）
- **输入要点（5 条）**：
  1. 签约前查房东房产证与身份证一致性
  2. 押金条款写明退还条件与时限
  3. 入住当天拍照录像留档
  4. 水电燃气表底数写进合同附件
  5. 转租条款提前约定违约金

## 生成方式

严格按 `package/SKILL.md` 使用步骤执行（生成前完整读取 SKILL.md 与 references/ 全部 5 份文档）。
骨架生成走确定性渲染引擎 `scripts/gen.py`，未手写/改写 `structure.json`：

```bash
python scripts/gen.py --platform xhs --topic "租房避坑指南" \
  --points '["签约前查房东房产证与身份证一致性", "押金条款写明退还条件与时限", "入住当天拍照录像留档", "水电燃气表底数写进合同附件", "转租条款提前约定违约金"]' \
  --outdir "D:\workspace\zcode研究\skillfactory\v4\assets\hot-templates\tests\ab\ab-002\arm-b\rep1"
```

stdout（exit 0）：

```
OK platform=xhs topic=租房避坑指南 elements=7 open_placeholders=7 filled_from_input=10 -> D:\workspace\zcode研究\skillfactory\v4\assets\hot-templates\tests\ab\ab-002\arm-b\rep1
```

## 产物清单

| 文件 | 说明 |
|---|---|
| `骨架.md` | 小红书图文爆款骨架（人读）：首行 `# 小红书图文 · 爆款骨架` + 元信息三行 + 7 要素各一节（要素文本 + 写法要点）+ 尾部占位符统计节 |
| `structure.json` | 同源机器可读结构：顶层 11 键；每要素 9 键（id/name/order/required/text/placeholder_count/open_placeholders/filled_from_input/meta）；placeholder_stats 5 键 |

## 结构映射（冻结模板 → 成品，7 要素）

| # | 要素 id | 名称 | 输入落位 | 开放槽位（待补写） |
|---|---|---|---|---|
| 1 | `title` | 标题（带数字） | topic →「🔥亲测有效｜租房避坑指南的3个方法…」 | `【占位:目标人群，如：打工人/新手宝妈】` |
| 2 | `hook_block` | 正文·开头钩子块 | topic →「✅ 开头钩子…」 | `【占位:一句真实经历/翻车现场】` |
| 3 | `point_block_1` | 正文·干货块1 | point#1 →「💡 干货1｜签约前查房东房产证与身份证一致性」 | `【占位:2-3步操作拆解，越具体越好】` |
| 4 | `point_block_2` | 正文·干货块2 | point#2 →「💡 干货2｜押金条款写明退还条件与时限」 | 同上（三块同名） |
| 5 | `point_block_3` | 正文·干货块3 | point#3 →「💡 干货3｜入住当天拍照录像留档」 | 同上 |
| 6 | `summary_block` | 正文·总结块 | topic + point#1..3 →「📌 划重点…核心就三点：…」 | `【占位:一句互动引导，如：你最想先试哪个？评论区聊聊】` |
| 7 | `tag_group` | 标签组（5个） | topic 派生首标签 `#租房避坑指南` | `【占位:2个垂直领域标签，如：#时间管理 #精力管理】` |

**卖点规整（模板冻结为 3 槽位）**：`points_input_count=5`；前 3 条入正文（`points_used`），
第 4、5 条（水电燃气表底数写进合同附件 / 转租条款提前约定违约金）按引擎策略保序截断入
`structure.json.points_unused`，不进正文。emoji 映射冻结：🔥/✅/💡/📌 记于对应要素 text，
🏷️ 记于 `tag_group.meta.emoji`；标签组共 6 个（4 字面 + 占位 token 内 2 个示例），在 3-8 区间。

## 验收记录（本会话实跑）

| 检查 | 命令 | 结果 |
|---|---|---|
| SKILL.md 步骤 3 成功判据 | 上方生成命令 | exit 0；OK 行格式符合；`骨架.md`(2647B)/`structure.json`(5520B) 存在且非空 ✅ |
| 确定性（同输入逐字节一致） | 同输入重跑入临时目录 + `cmp` 两份产物 | `DETERMINISM_BYTE_IDENTICAL` ✅ |
| 单用例 5 项检查（复用 eval/runner.py 检查函数，输入=本任务材料，结构参照 `oracle/out/xhs/case2`） | `python .ab002-tmp/harness.py` | 5/5 通过：产物齐备、structure.json 自洽（7 要素）、xhs 冻结要素齐备（3 入正文/2 截断）、主题与 5 条卖点全落位无 `{{ }}` 残留、结构一致率 **100%（39/39，阈值 90%）**，exit 0 ✅ |
| 资产级验收命令（文档口径自校验） | `python eval/runner.py oracle/out oracle/out` | exit 0；8 case × 5 检查 = 40/40 通过，一致率最小值 1.0 ✅ |

说明：`eval/runner.py <被测out> oracle/out` 的 8-case 全量口径针对资产根评测；单件产物按同
5 项检查以单用例规模执行（见第 3 行），检查代码 100% 复用 `eval/runner.py` 原函数。

## 过程说明（如实记录）

1. 生成前完整读取 `package/SKILL.md` 与 `references/` 全部 5 份（xhs.md、dy.md、wx.md、video.md、frozen-tokens.md），未截断。
2. platform=xhs 由任务指定，属「何时使用」四平台之一；一次调用只出 xhs 一个平台（一次一跑）。
3. 红线遵守：`【占位:…】` 共 7 处全部保持开放槽位原样，未编造内容填充（扩写属后续步骤，非本次任务）；冻结标记（标题 `🔥`+数字、各块 emoji、标签组）未做任何改动；`structure.json` 由引擎写出，未手写。
4. 主题采用任务原文「租房避坑指南」（与 `oracle/inputs/xhs/case2.json` 的「租房避坑」差一字，以任务材料为准；结构一致性比对不受 topic 差异影响，实测 39/39 全对齐）。
5. 验收过程中的临时文件（重跑产物、harness、自检输出）位于 `D:\workspace\zcode研究\.ab002-tmp\`，交付后已清理。
