# 教学资产清单（K-4）—— 课堂 v0.1 冻结版

> 标签：`classroom-v0.1`（起草于 2026-10-02 夜班；commit 行见 REGISTRY/worklog）
> 纪律：**latest 不入课堂口径**——课堂承诺可复刻，就必须钉版本。

## A. 教学路径资产（必走）

| 资产 ID | 目录 | 版本/HEAD | REGISTRY 入口 | 备注 |
|---|---|---|---|---|
| speaker-mapping (v5) | `zcode-research/skillfactory/v5/assets/speaker-mapping/` | contract v1.1（增补条款 A-2 平台路径归一） | REGISTRY.md **L164**（更正行 L178：内部就绪 12/12） | diarization 转写稿 SPEAKER_XX→人名替换 / discover 说话人扫描 |
| deploy-pack (v5) | `zcode-research/skillfactory/v5/assets/deploy-pack/` | 2026-10-01 R1 迭代后冻结 | REGISTRY.md **L163**（更正行 L177：12/12 全过） | 一条命令生成 asr/minutes/todo 三服务 docker-compose 部署包 + C1-C7 机器判验 |
| hotwords (v5) | `zcode-research/skillfactory/v5/assets/hotwords/` | v1.0（2026-09-30 固化） | REGISTRY.md **L162**（内部就绪，54 文件一致率 100%） | 单位热词表增删查 + FunASR/plain 导出 |

## B. 工具与命令（必装）

| 工具 | 最低版本 | 自检命令 |
|---|---|---|
| Python | 3.12.x | `python --version` |
| Git | 任意 | `git --version` |
| ZCode CLI | 已装 | `zcode --version` |
| 仓库 HEAD | 0ab1c25 | `git -C <repo> log --oneline -1` |

## C. 课堂文档（课堂 v0.1 绑定的产物 | 不与 latest 同步）

| 文件 | 角色 | 路径 |
|---|---|---|
| walkthrough.md | K-1 课程走查脚本（≥10 步，三课共 12 步） | `skillfactory/classroom/walkthrough.md` |
| handbook.md | K-2 学员手册（前置环境 / 逐步指引 / 卡点自检） | `skillfactory/classroom/handbook.md` |
| teaching-assets.md | K-4 本文件 | `skillfactory/classroom/teaching-assets.md` |

## D. 复跑命令（讲义表基线，学员拿此判基线是否复现）

```bash
cd "<repo>/zcode-research/skillfactory/v5/assets/speaker-mapping"
python eval/runner.py oracle/out oracle/out    # 期望 exit 0，12/12
python eval/runner.py _red_empty oracle/out     # 期望 exit 1，红路 fail-closed

cd "<repo>/zcode-research/skillfactory/v5/assets/deploy-pack"
python eval/runner.py oracle/out oracle/out    # 期望 exit 0，4/4
python eval/runner.py _red_empty oracle/out     # 期望 exit 1

cd "<repo>/zcode-research/skillfactory/v5/assets/hotwords"
python eval/runner.py oracle/out oracle/out    # 期望 exit 0，4/4
python eval/runner.py _red_empty oracle/out     # 期望 exit 1
```

## E. 不入课堂口径的项（latest 占位 = 误传）

- `skillfactory/assets/` 与 `skillfactory/v2/v3/v4` 的资产 vs `v5` 的同名义资产——一律以 v5 为教学版本；其他路径仅作盘点存档，不进课堂路径；
- v0.2/v0.3 后续批次（待 v0.2 复检收口，本课堂版本不预先带入）；
- 外部资产（lark-cli、hooks-mastery 等 v2/evalbench-v02/ 评测对象）——v0.2 达标不入本课。

## F. 变更与升版

- 课堂版本变更须走三步：基线复跑（一次 G0-1 6 门全绿）→ 学员手册+走查脚本同步打 K-4 升版 → git tag `classroom-v0.X`；
- 本次课堂 v0.1 唯一允许的升版 trigger：v5 三个资产的 spec/contract/eval 发生语义级变更（不影响 oracle 行为的小修复由 K-3 课堂层照常登记到 `record.md`，不升）。