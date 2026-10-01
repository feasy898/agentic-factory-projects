# 内容评测报告（抖音 · good_dy.md）

- 输入文件：`D:\workspace\zcode研究\skillfactory\v4\tools\content-evaluator\oracle\fixtures\good_dy.md`
- 平台：dy（抖音）
- 生成时间：2026-09-30T09:14:11+0800（evaluate.py 1.0.0）
- **总分：9/9**（100.0%）
- 汇总：应检 9 项，通过 9 / 失败 0 / 警告 0

| 检查项 | 结果 | 说明 |
|---|---|---|
| `title_length` | ✅ PASS | 标题 12 字，在区间 [10, 30] 内：三个方法帮你戒掉周日焦虑 |
| `emoji_density` | ✅ PASS | emoji 共 0 个，未超上限 10 |
| `body_length` | ✅ PASS | 正文 154 字（去空白），在区间 [50, 300] |
| `paragraph_max` | ✅ PASS | 共 6 段，最长第 4 段 34 字（上限 120）：再说清单：把下周要做的三件事写在纸上，写完就合上本子，大脑才肯下班。 |
| `tag_count` | ✅ PASS | #标签 共 5 个，在区间 [3, 8] |
| `banned_words` | ✅ PASS | 未命中 44 词内置极限词表 |
| `structure_hook` | ✅ PASS | 有钩子（？(问句)）：你是不是也一到周日晚上就开始心慌？ |
| `structure_cta` | ✅ PASS | 有 CTA（点赞、收藏、评论、分享、评论区） |
| `structure_para` | ✅ PASS | 正文分 6 段，≥ 最少要求 2 段 |

## 修改建议

- 全部通过，无需修改。
