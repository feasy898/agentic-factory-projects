# 内容评测报告（微信公众号 · bad_wx.md）

- **输入文件**：D:\workspace\zcode研究\skillfactory\v4\tools\content-evaluator\package\fixtures\bad_wx.md
- **平台**：微信公众号（wx）
- **生成时间**：2026-09-30T11:29:54+0800
- **总分：6/9**（66.7%）
- **汇总**：应检 9 项，通过 6 / 失败 3 / 警告 1

| 检查项 | 结果 | 说明 |
|---|---|---|
| `title_length` | ✅ PASS | 标题 20 字，在区间 [10, 64] 内 |
| `emoji_density` | ⚠️ WARN | emoji 共 22 个，超出软上限 20（仅警告，不计失败） |
| `body_length` | ✅ PASS | 正文 526 字，在区间 [300, 3000] 内 |
| `paragraph_max` | ❌ FAIL | 最长段落 422 字，超出单段上限 350 |
| `tag_count` | ✅ PASS | 标签 0 个，在区间 [0, 8] 内 |
| `banned_words` | ❌ FAIL | 命中 6 个极限词（共 6 次）：100%×1、国家级×1、完美×1、最全×1、最好×1、立竿见影×1 |
| `structure_hook` | ✅ PASS | 首段含钩子词「为什么」 |
| `structure_cta` | ❌ FAIL | 正文未含 CTA 引导词（词表 21 词） |
| `structure_para` | ✅ PASS | 段落 4 段，达到最少 3 段 |

## 修改建议

- 【paragraph_max】拆分超长段落，单段控制在平台单段上限以内。
- 【banned_words】替换或删除命中的极限词，改用可证实的中性表述。
- 【structure_cta】结尾补充行动引导语（点赞/关注/收藏/评论等）。
- 【emoji_density】按平台口径增减 emoji：小红书为硬区间 [2,15]，抖音/公众号超软上限仅警告但建议收敛。
