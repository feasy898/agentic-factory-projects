# video-capability —— AI 营销视频生产流水线（PROJECT CRADLE → v3）

> 接手文档 ｜ 任务卡见 [TASK.md](TASK.md) ｜ 两代收官台账见 [PM-LEDGER.md](PM-LEDGER.md)

## 项目是什么

「**无人干预 70 分**」AI 营销视频自动生产流水线的迭代研究：

- **v1**（收官）：六门禁生成管线，成片 9+1 条、良率 17/17；
- **v2**（收官，tag 历史见 PM-LEDGER）：G7 物体恒存门禁 + 三车道重构，AI 形变 12.3% → **零形变**，夹具拦截 15/15；
- **overnight 基线**：金标 40 条 judge 盲测基准，主判据 **E10=J1∨J3@0.7（召回 1.000 / FPR 0.250 / F1 0.914）**；
- **v3（现役）**：vpipe spec 驱动 QC 流水线——L0 确定性预检、J6v2 平台豁免、known_cuts 白名单、QCReport 契约 1.1。

⚠️ **运行时依赖不在仓内**：模型权重（约 77G）、四个 Python 运行环境、金标 40 条数据、各 API 通道凭据（`overnight/secrets/api_keys.env` 已按密钥纪律排除，从不入 git）——克隆本仓后需按 TASK.md 重建环境才能跑生成/评测全链。

## 架构一句话

生成（草稿→终稿）→ 确定性 QC 门禁（G7 物体恒存 / L0 预检 / 夹具库拦截，宁可误杀不可漏网）→ judge 盲测合议（六 judge、金标 40 条、E10 判据）→ 人工灰区；「重生成某模块 = 新 agent 只读 SPEC + contracts + eval，跑 eval 通过才算验收」。

## 构建与运行

- v3 确定性自检（零模型调用，~1.5 分钟）：`python overnight/vpipe/tests/run_v3_checks.py` → `== 汇总 == ALL PASS` + `EXIT=0`
- 评测基线：`python overnight/vpipe/eval/eval_run.py`（overnight/vpipe 下）→ ACCEPT；阈值唯一来源 `overnight/vpipe/eval/thresholds.yaml`（sha256 留痕对账）
- 完整生成链需要：GPU + 模型权重 + 各通道 API key（均不在仓内，见 TASK.md 阶段 (a)）

## 验收基线（2026-10-01 实测两次）

| 门 | 命令 | 基线 |
|---|---|---|
| G0-1 v3 自检 | `python overnight/vpipe/tests/run_v3_checks.py` | **ALL PASS / EXIT=0（1m33s）**（A 预检/B 豁免/C 白名单/D 无声明回归/E eval 双模块全 PASS） |
| G0-2 E10 基准 | eval_run 独立复跑 | ACCEPT；R=1.000 / FPR=0.250 / F1=0.9143 与基准位级一致 |
| G0-3 阈值对账 | `sha256sum overnight/vpipe/eval/thresholds.yaml` 与 eval 留痕 JSON 内记录一致 | 一致 |
| G0-4 密钥零入库 | `git ls-files | grep -i secret` | 空 |

## 已知问题

1. **CONFIRMATION.md（A13+B4 共 17 条）自 09-09 挂起待 owner 逐条处置**（`deliverables_v2/fixtures/CONFIRMATION.md`）——这是 v3 走向的第一待决项，不可代签。
2. **MediaPipe 手部检测缺失**：`import mediapipe` → ModuleNotFoundError（P0 待办）。
3. **凭据需重建**：Vidu/StepFun/MiniMax 等通道 key 不在仓内；重建只走环境变量或密钥服务，不得落仓。
4. **运行区不在仓内**：`/data/night`（模型 77G、venv、金标）随原机器走，新环境需重建；v1/v2 的 git 历史已随旧训练机灭失，本仓 + `PM-LEDGER.md` + `deliverables*` 结论镜像是唯一史料。
5. 历史/文档中出现的 `203.0.113.x`、`100.100.0.x` 为公开化替换的示例地址（文档保留测试网段），不是真实服务。
