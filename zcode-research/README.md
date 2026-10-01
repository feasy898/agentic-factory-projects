# zcode-research —— skill 资产工厂（课堂产线）

> 接手文档 ｜ 任务卡见 [TASK.md](TASK.md)（**owner 口径：本项目重心 = skill 工厂，具体研究内容不重要**）
> 总台账：[skillfactory/REGISTRY.md](skillfactory/REGISTRY.md)（资产级权威状态，含「未重跑盲评」等如实声明）

## 项目是什么

两部分咬合：

1. **工厂线（重心，现役）**：`skillfactory/` —— skill 资产生产线，五代迭代（v1→v5），总台账 `REGISTRY.md`（18 资产 / 可分发 3）。**owner 澄清口径（2026-10-01）**：产品面向大量想学 AI 的人，教学价值不在「讲什么内容」，而在**带着学员借助 skill、MCP 等 agent 能力支撑品，直接走一遍「获得真实交付」的过程**；课堂因此高度确定性（过程可复制、交付可验收）——这是当前整个业务的收费逻辑。
2. **研究线（已归档）**：ZCode 平台逆向（asar 解包、闲时任务/额度重置 API、`zctl` CLI）+ 课程市场调研三报告 + 平台抓取快照。验收已达成，作为工厂选品的输入资产保留。

授权框架：`AUTONOMY.md`（长期授权 + 诚实纪律 + 工作队列）；**对外发布是唯一保留的人工批准点**。

## 架构一句话

「生成 → 确定性评测 → 双臂盲评 → 体检 → 准入入册」的资产产线：每资产一个 `eval/runner.py` 确定性评测门（exit 0 过 / exit 1 红路 fail-closed / exit 2 用法错），评测输出无时间戳、可复跑对账；三齐口径 = 确定性评测 + 盲评 + 体检 A ⇒ 可分发。

## 构建与运行

- 环境：Python 3.12（venv）。
- 资产评测门（G0-1）：`python skillfactory/v5/assets/<asset>/eval/runner.py <被测产物根> <oracle/out>` → exit 0
- 红路验证（G0-2）：同命令对空目录/坏产物 → **exit 1**（禁止把红路修成 exit 0）
- 台账对账：`skillfactory/REGISTRY.md` 每行含三齐状态；`skillfactory/v5/eval-round-*/` 与 eval-records 留档可复跑。

## 验收基线（2026-10-01 实测 8 门 8/8 全绿）

| 门 | 判定 | 基线 |
|---|---|---|
| G0-1 三资产绿门 | runner exit 0 | SM（会议纪要）12/12、DP（办公文书）4/4、HW（爆款模板）54/54 |
| G0-2 红路 fail-closed | 对空目录 runner exit 1 | 验证通过（fail-closed 存活） |
| G0-3 三齐口径 | REGISTRY 行三列齐备且各自留档 | 可分发 3 个 dist 包（盲评 Δ +5.25 / +1.20 / +6.10，胜率 100%） |
| G0-4 变更留痕 | 每批收口 git 化 + worklog 一行一轮 | 在岗 |

## 已知问题

1. **三个 dist 包发布卡在人工批准**：对外发布 = 雇主/owner 批准（唯一人工例外，不可代签）；批准前只做产线与打包准备。
2. **盲评未重跑（如实声明在 REGISTRY）**：盲评记录是历史留档，不可当复跑门；加厚盲评需真实模型调用配额。
3. **历史欠账**：B 线 FunASR 彩排（需音频环境）、C 线 hot-templates 盲评加厚（需模型配额）。
4. **研究线产物为大体积一次性调研快照**（`research/`、`zctl/`），按可归档区对待；工厂线以 `skillfactory/REGISTRY.md` 为唯一状态入口。
5. dist 包内个别 JSON 存在 CRLF 脏项，发布前按 DISTRIBUTION-CHECKLIST 复核格式。
