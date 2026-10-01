# 内容评测报告（小红书 · bad_xhs.md）

- **输入文件**：D:\workspace\zcode研究\skillfactory\v4\tools\content-evaluator\package\fixtures\bad_xhs.md
- **平台**：小红书（xhs）
- **生成时间**：2026-09-30T11:29:46+0800
- **总分：4/9**（44.4%）
- **汇总**：应检 9 项，通过 4 / 失败 5 / 警告 0

| 检查项 | 结果 | 说明 |
|---|---|---|
| `title_length` | ❌ FAIL | 标题 25 字，超出区间 [8, 20] |
| `emoji_density` | ❌ FAIL | emoji 共 0 个，低于区间 [2, 15] |
| `body_length` | ✅ PASS | 正文 118 字，在区间 [100, 800] 内 |
| `paragraph_max` | ✅ PASS | 最长段落 45 字，未超单段上限 160 |
| `tag_count` | ❌ FAIL | 标签 0 个，低于区间 [3, 10] |
| `banned_words` | ❌ FAIL | 命中 12 个极限词（共 13 次）：最好×2、世界级×1、全国第一×1、史上最×1、史上最全×1、史无前例×1、完美×1、最全×1、立竿见影×1、第一×1、绝对×1、顶级×1 |
| `structure_hook` | ✅ PASS | 标题含钩子词「攻略」 |
| `structure_cta` | ❌ FAIL | 正文未含 CTA 引导词（词表 21 词） |
| `structure_para` | ✅ PASS | 段落 3 段，达到最少 3 段 |

## 修改建议

- 【title_length】把标题字数调整到平台建议区间内，先给结论再放卖点。
- 【emoji_density】按平台口径增减 emoji：小红书为硬区间 [2,15]，抖音/公众号超软上限仅警告但建议收敛。
- 【tag_count】补充平台话题标签至建议区间（#标签1 #标签2 #标签3）。
- 【banned_words】替换或删除命中的极限词，改用可证实的中性表述。
- 【structure_cta】结尾补充行动引导语（点赞/关注/收藏/评论等）。
