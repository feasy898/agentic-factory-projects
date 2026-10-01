# 内容评测报告（小红书 · good_xhs.md）

- 输入文件：`D:\workspace\zcode研究\skillfactory\v4\tools\content-evaluator\oracle\fixtures\good_xhs.md`
- 平台：xhs（小红书）
- 生成时间：2026-09-30T09:14:14+0800（evaluate.py 1.0.0）
- **总分：9/9**（100.0%）
- 汇总：应检 9 项，通过 9 / 失败 0 / 警告 0

| 检查项 | 结果 | 说明 |
|---|---|---|
| `title_length` | ✅ PASS | 标题 16 字，在区间 [8, 20] 内：救命！这家咖啡馆也太治愈了吧☕️ |
| `emoji_density` | ✅ PASS | emoji 共 5 个，在区间 [2, 15] 内 |
| `body_length` | ✅ PASS | 正文 198 字（去空白），在区间 [100, 800] |
| `paragraph_max` | ✅ PASS | 共 7 段，最长第 3 段 40 字（上限 160）：靠窗的位置能看到一整面墙的绿植🌿，下午三点后的阳光刚好斜进来，随手一拍都是壁纸。 |
| `tag_count` | ✅ PASS | #标签 共 7 个，在区间 [3, 10] |
| `banned_words` | ✅ PASS | 未命中 44 词内置极限词表 |
| `structure_hook` | ✅ PASS | 有钩子（救命、标题带emoji）：姐妹们！我发现了一家宝藏咖啡馆，真的会一直回头的那种！！ |
| `structure_cta` | ✅ PASS | 有 CTA（码住、评论、评论区、蹲一个） |
| `structure_para` | ✅ PASS | 正文分 7 段，≥ 最少要求 3 段 |

## 修改建议

- 全部通过，无需修改。
