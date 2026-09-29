# e2e 与验收门 spec（e2e_mock_run / gate_g1 / verify_g1_reports / check_naming）

> 状态：**frozen**（2026-09-29 e2e 实测 exit 0；gate 与复核脚本入口 frozen——当日门禁状态
> 受模型件环境影响见 §5 如实记录）。本页对照仓库根 `scripts/`（4 个入口，其中 2 个为转发垫片）
> 与 `chengshao/scripts/e2e_mock_run.py` 逐行核验于 2026-09-29。

---

## 1. e2e_mock_run（无硬件总验收，开发指令 §5.8/§7）

- 双路径：仓库根 `scripts/e2e_mock_run.py` 是**转发垫片**（优先改用 `<仓库根>/.venv` 解释器
  执行真身——外部复核器的系统解释器不装依赖；`PYTHONUTF8=1`；退出码原样回传）；
  真身 `chengshao/scripts/e2e_mock_run.py`（仅依赖自身 `__file__` 定位仓库根，任意 cwd 可跑）。
- CLI：`--report` / `--trace`（缺省 `chengshao/reports/e2e_mock*.json[.jsonl]`）、
  `--bites 30`、`--seed 20260929`、`--tts`（缺省静音记录）、`--profile none|rerun`
  （rerun=相机帧+关节流推调试可视化通道）。
- 全链同进程：MockArm(cs_sim) + SafetyEnvelope + 行为树（MockScoop 注入）+ 脚本用户
  + cs_voice 队列注入（不经麦克风）+ **真实 uvicorn 看板**（随机端口+比对 GET 快照）+ 启发式 cs_food
  + cs_mouth 冒烟（真实 MouthEstimator 走腕部路径 source=wrist）。
- 注入脚本：与 orchestra eval 同源五类事件（第 3 口舀空/第 7 口转头/第 9 口长反应/
  第 12 口 estop/第 30 口 done）+ 语音 wav 注入（"我想吃芋泥"→select、"我吃饱了"→done）
  + 操作员 reset+resume。
- 全程消息镜像写 `reports/e2e_mock_trace.jsonl`（回放/取证）。

**通过线（exit 0 判据）**：30 口闭环且结局与期望表全符（28 success/1 estop-aborted/
1 done-rejected）；单口中位 ≤20s；estop 响应 ≤0.1s（仿真秒）；0 禁入区闩锁/0 包络拒绝；
数值安全余量 ≥5mm；camera_role 每进送达口恰 2 次切换且稳定 gap ≥0.5s；看板 HTTP 与树内
计数一致、会话正常结束。实测（2026-09-29）：全部达标，meal 727s/wall 113s/36350 tick。

## 2. gate_g1（一键门禁，仓库根 `scripts/gate_g1.py`，系统 Python 可跑）

门禁项（任一 FAIL → exit 1；单步硬超时 1800s；子进程统一 `PYTHONUTF8=1`；内部统一改用
`.venv` 解释器）：

| # | 门禁项 | 命令（内部） |
|---|---|---|
| ① | 中性命名扫描零命中 | `.venv python chengshao/scripts/check_naming.py` |
| ② | pytest 全量全绿 | `.venv python -m pytest tests/ -q`（cwd=仓库根） |
| ③a | cs_sim eval | `-m cs_sim.eval --model auto --report reports/sim_eval.json`（cwd=包根） |
| ③b | cs_mouth eval | `-m cs_mouth.eval --input assets/face_samples --report reports/mouth_eval.json` |
| ③c | cs_voice eval | `-m cs_voice.eval --input assets/voice_samples --report reports/voice_eval.json` |
| ③d | cs_food 接口测试 | `-m pytest tests/test_food_interface.py -q`（cwd=仓库根） |
| ④ | 报告独立复核 | `.venv python scripts/verify_g1_reports.py --report-dir chengshao/reports` |
| ⑤ | 看板冒烟 | `-m pytest chengshao/tests/test_dashboard.py -q`（进程内套件，无子进程服务） |

证据落 `chengshao/reports/gate_g1.json`（含逐步 detail 与 exit code）。

## 3. verify_g1_reports（报告独立复核，审查 B8 产物）

- **只读 JSON、只用标准库、不 import 任何 chengshao 模块**：用独立比较逻辑从每份报告的
  `metrics` 与 `thresholds` 重算每一项检查，并与模块自报 `pass`/`checks`/`self_check`
  交叉核对——任一重算不达标、自报与重算不符、报告缺失/字段缺失 → FAIL（exit 1）。
- 定位：eval 子进程退出码可能被"写报告的同一段代码"抬高（阈值写错或合成帧灌满时 exit 仍 0），
  本脚本是第二双独立眼睛。

## 4. check_naming（对外命名检查，CI 前置）

- 扫描根 = git toplevel（取不到回退自身上溯）；豁免：扫描器自身（黑名单本体）、二进制后缀、
  本地目录（.venv/_vendor/data/models/.zcode 等）、**symlink/junction 不跟随**（与 git 口径一致）。
- 一级禁用（任何文件含即 FAIL，依赖清单也不豁免）：机器人参考件四来源的组织名与型号名
  ——字面清单只存在于扫描器 `chengshao/scripts/check_naming.py` 的 `FORBIDDEN_ALL`
  （本黑名单本体文件豁免扫描），本文档刻意不复述（写了即命中）。
- 二级禁用（代码/文档不得出现；`requirements*.txt` 的 **pip 包名本身** 白名单放行——
  包名属依赖声明而非内容引用，但行内注释/杂注仍照扫）：机器人学习运行栈的发行名
  （`FORBIDDEN_EXCEPT_MANIFESTS`）。
- 警告级（不判失败，人工复核）：延后策略训练的通用缩写与其变体名——训练侧文档/代码
  已知的此类提示属预期（内部代号叙事，不指代上游）。
- 退出码：0=干净；1=存在禁用名。**公开仓纪律**：任何入库文本不得出现参考件原始名——
  文档一律用内部代号（vendor-robot-stack / vendor-arm-model / vendor-safety-ref /
  vendor-policy-ref，见 reports/upstream_lock.md）或中性描述。
- 2026-09-29 实测：`forbidden=0`（基线 23 条 warning 全部为 training 侧缩写提示）；
  本资产包撰写时本页初稿曾因复述禁用词被本扫描器当场拦下 7 条 FORBIDDEN——
  门禁有效性的一次实测自证。

## 5. 当前门禁状态（2026-09-29 如实记录）

- 本日独立复验**通过**：check_naming（exit 0）、cs_food.eval（exit 0）、
  cs_mouth.eval（exit 0，空载 lat_p95=39.7ms）、cs_voice.eval（exit 0，20/20）、
  tests/test_schema.py + tests/test_dashboard.py（88 passed）、
  tests/test_food_interface.py（54 passed）。
- **全量门禁当前为红**：`pytest tests/` 36 failed / 260 passed / 2 skipped——根因是
  cs_sim 模型回退链环境前提被破坏（参考件移出工作区后 `auto` 落 tier3 内置名义链 5 关节，
  与契约 6 关节不符；详见 [cs_sim](cs_sim.md) §8 坑 1）。凡不依赖 `load_arm("auto")` 的
  模块（schema/dashboard/food/voice/mouth 空载）全部绿；恢复 `_vendor` 参考件后应全绿复跑
  `python scripts/gate_g1.py`。
