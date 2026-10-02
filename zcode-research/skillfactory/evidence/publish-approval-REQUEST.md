# K-5 发布材料就绪度核查（发布申请 · 前置状态：**受阻——缺实物**）

> 日期：2026-10-02 夜班 ｜ 撰写：zcode-nightshift
> **本文件仅为申请与核查记录。正式发布批准须由 owner 亲自签署 `evidence/publish-approval.md`；任何 agent 不得代签（TASK.md K-5 红线）。**

## 1. 结论速览

| 事项 | 状态 |
|---|---|
| 三个 dist 包发布批准（TASK.md K-5） | **受阻**：`skillfactory/dist/` 三个分发包**不在本 monorepo 快照内**，CRLF 修复与包内自检复核无实物可做 |
| 课堂层（K-1/K-2/K-4/K-3） | ✅ 完成：tag `classroom-v0.1`（commit 0079419），彩排 round-1 通过 |
| v5 三资产确定性门 | ✅ 本夜复现：SM/DP/HW 6 门全绿（绿 exit 0 / 红路 exit 1），见 classroom/rehearsal/round-1/record.md |

## 2. dist 包缺失的核查证据

- `ls zcode-research/skillfactory/dist` → `No such file or directory`（2026-10-02 实测）；
- REGISTRY.md L14-L16 仍登记三包为「可分发（待雇主批准）」，登记依据为源机盘内 `dist/`（各自独立 git 仓：29bd123 / 1e4ada5 / 52187cf）；
- CONTEXT.md 迁移口径：源机 108 项 3.9G → 净 131M → tar 42M 入公开仓；dist 三个内嵌 git 仓未随迁（疑因嵌套 git 仓被排除）。

## 3. 发布前置清单（TASK.md K-5 口径）对照

| 前置项 | 状态 |
|---|---|
| dist 包 CRLF 复核修复 | ⛔ 无实物（原登记：dist JSON 存在 CRLF 待修） |
| 包内绿自检复跑 | ⛔ 无实物（REGISTRY 载历史结果 exit 0，本轮无法复跑） |
| 三齐证据（确定性+盲评+体检） | ✅ REGISTRY L14-L16 在册（历史轮全 A/accepted）；本轮 v5 线 6 门复现佐证产线判定纪律仍有效 |
| 彩排结论 | ✅ K-3 round-1 通过（v5 教学路径；注意：彩排路径为 v5 内部就绪资产，非 dist 三包——dist 包彩排待实物恢复后另排） |
| **owner 人工批准** | ⏳ 等待（本文件非批准） |

## 4. 给 owner 的两个决定请求

1. **材料恢复通道**：dist 三包在源机（原 zcode-research 活车）仍有唯一副本——是安排从源机补迁 dist/（含内嵌 git 仓），还是放弃三包、改以 v5 三资产为可分发候选重走三齐+发布？
2. **若补迁**：恢复后按本文件 §3 清单逐项补做（CRLF→自检→彩排），再提请签署 `publish-approval.md`。

## 5. 红线重申

- 未获 owner 亲签批准前，不对任何外部渠道发布任何包；
- 本夜全部改动仅本地 git 提交，未推送远端。
