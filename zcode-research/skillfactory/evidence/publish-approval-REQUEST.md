# K-5 发布申请（更新版 2026-10-03：实物已补迁，全部前置就绪，停在 owner 批准点）

> 撰写：zcode-nightshift ｜ 本文件为申请，**不是批准**。正式发布批准须由 owner 亲自签署 `evidence/publish-approval.md`；任何 agent 不得代签（TASK.md K-5 红线）。

## 1. 结论

| 事项 | 状态 |
|---|---|
| dist 三包实物 | ✅ 已从源机 anolis-gpu-01（/opt/gpumachine/projects/...）补迁，1.1M tar md5=dc0cf866 两端一致 |
| 指纹核验 | ✅ 内嵌仓 SHA 与 REGISTRY L14-16 逐一相符：meeting-minutes-skill=29bd123（26 文件）/ office-templates-skill=1e4ada5（38 文件）/ hot-templates-skill=52187cf（39 文件）；工作区干净 |
| 包内绿自检 | ✅ 三包 `eval/runner.py reference/out reference/out` 全部 exit 0（2026-10-03 复跑） |
| CRLF 修复 | ✅ 12 个 JSON 的 CRLF→LF 全部修复，CR 字节残留 0；修复后三包自检复跑仍全绿（未破坏冻结期望） |
| .mimosa 污染 | ✅ 0（REGISTRY 注 1 口径） |
| requirements.txt | ✅ 三包齐备 |
| 彩排结论 | ✅ K-3 round-1 通过（教学路径为 v5 三资产；dist 包为发布物非教学路径，无彩排阻塞项） |
| 入库方式 | 内嵌 .git 已剥离（指纹上移本文件记档），105 文件以内容入 monorepo |
| **owner 人工批准** | ⏳ **唯一待办**——签署 `evidence/publish-approval.md` 后按 DISTRIBUTION-CHECKLIST 发布 |

## 2. 三包摘要（摘自 REGISTRY L14-L16，2026-09-30 轮）

| 包 | 盲评 | 体检 | 许可 | 用途 |
|---|---|---|---|---|
| meeting-minutes-skill v1.0.0 | Δ+5.25 / 8/8 全胜 / 反向 0，accepted | A（5/5） | MIT | 会议转写稿→决议/待办/风险三段式纪要 docx |
| office-templates-skill v1.0.0 | Δ+1.20 / 5/5 全胜 / 反向 0，accepted（单轮） | A（5/5） | MIT | 周报/请示函/会议通知/工作总结四类中文办公模板 |
| hot-templates-skill v1.0.0 | Δ+6.10 / 5/5 全胜 / 反向 0，accepted | A（5/5） | MIT | 主题+卖点→四平台爆款内容骨架（注：五门复检欠账见 REGISTRY 注 2，以 release-candidate 形态随批） |

## 3. 已知如实披露

- office-templates-skill 盲评为单轮信号（二轮未做）；hot-templates-skill 效率门未测、benchmark.json 未落盘（REGISTRY 注 2）——两包按登记口径随三包一并待批，不隐瞒；
- 发布渠道与 DISTRIBUTION-CHECKLIST 原件在源机盘内未随迁——发布时需按 TASK.md 口径重建清单或从源机补迁（不阻塞批准决定）。

## 4. 发布红线

未获 owner 亲签前不发布；密钥不入仓；本夜全部改动截至本文件均为本地提交。
