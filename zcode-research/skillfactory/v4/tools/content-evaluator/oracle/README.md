# content-evaluator oracle（v4 参照实现）

新媒体内容的确定性评测 CLI：给定一篇 markdown 文案和目标平台，输出逐项检查结果与总分。
全部规则内置、离线可跑、同输入同输出（无网络/无随机/无 LLM 调用）。

## 用法

```bash
python evaluate.py --input <markdown文件> --platform <dy|xhs|wx> --out <报告目录>
# 例：python evaluate.py --input fixtures/bad_xhs.md --platform xhs --out out/bad_xhs
```

- 产出：`<out>/report.json`（checks 数组 + 总分 = 通过项/应检项）+ `<out>/REPORT.md`（逐项明细 + 修改建议）
- 退出码：0 = 报告已写出（红绿均算，只报告不设门）；2 = 参数或输入文件无效
- 依赖：仅 Python 3.8+ 标准库

## 检查项（9 项，全部应检）

| 检查项 | 规则 |
|---|---|
| title_length | 标题（首个 `# ` 行）字数在平台区间内 |
| emoji_density | xhs 硬区间 [2,15]，越界失败；dy/wx 仅超上限（10/20）警告，不计失败 |
| body_length | 正文（去空白字符）在平台区间内 |
| paragraph_max | 最长段落（空行分块）不超过平台单段上限 |
| tag_count | `#标签` 数量在平台区间内（排除 markdown 标题行） |
| banned_words | 命中内置 44 词极限词表（最好/第一/国家级/100%/No.1 等）即失败 |
| structure_hook | 标题或首段含钩子词/问号；xhs 额外承认标题带 emoji |
| structure_cta | 正文含引导词（点赞/关注/收藏/评论/私信/在看/星标 等） |
| structure_para | 正文段落数 ≥ 平台最少段落数 |

## 平台阈值

| 平台 | 标题字数 | 正文字数 | 单段上限 | 标签数 | emoji | 最少段落 |
|---|---|---|---|---|---|---|
| dy（抖音） | 10-30 | 50-300 | 120 | 3-8 | >10 警告 | 2 |
| xhs（小红书） | 8-20 | 100-800 | 160 | 3-10 | 硬区间 2-15 | 3 |
| wx（微信公众号） | 10-64 | 300-3000 | 350 | 0-8 | >20 警告 | 3 |

## fixtures 与预期结果

| fixture | 平台 | 预期总分 | 关键命中 |
|---|---|---|---|
| good_dy.md | dy | 9/9 | 全过 |
| good_xhs.md | xhs | 9/9 | 全过（emoji 5 个在区间内） |
| bad_xhs.md | xhs | 4/9 | 超长标题(25>20) + 极限词(12词13次) + 无标签 + 无emoji + 无CTA |
| bad_wx.md | wx | 6/9 | 超长段落(422>350) + 极限词 + 无CTA + emoji 22>20 警告 |

复跑全部样例：

```bash
python evaluate.py --input fixtures/good_dy.md --platform dy  --out out/good_dy
python evaluate.py --input fixtures/good_xhs.md --platform xhs --out out/good_xhs
python evaluate.py --input fixtures/bad_xhs.md  --platform xhs --out out/bad_xhs
python evaluate.py --input fixtures/bad_wx.md   --platform wx  --out out/bad_wx
```

`out/` 为可再生产物，删掉后重跑上面四条命令即可重建。
