# 资产包总表（manifest）

> 本表按**逻辑模块**组织，物理位置逐行标注。每模块一行：模块ID / 名称 / 语言形态 / 职责 /
> 冻结契约 / 依赖 / eval 命令与通过线 / 重生成顺序位 / 状态。
> 详细契约汇总见 [CONTRACTS.md](CONTRACTS.md)；整仓再生手册见 [REGENERATE.md](REGENERATE.md)；
> 逐模块 spec 在 [specs/](specs/)。
> 所有 eval 命令在仓库根或包根（另有注明）执行。**验证状态如实分级**：
> "2026-09-29 实测"=本资产包撰写当日真实运行；环境前提（参考模型件）不满足的条目单独标注，
> 见 [cs_sim spec §8](specs/cs_sim.md)。

## 状态图例

| 状态 | 含义 |
|---|---|
| `frozen` | 已实现且验收全绿；契约冻结，改动视为破坏契约 |
| `frozen-prototype` | 雏形已冻结可复验；全量（真机/真实训练）在后续里程碑 |
| `partial` | 主体 frozen，子项占位（占位语义 fail-closed，exit 2 / HardwareUnavailable） |
| `planned` | 未开工；有明确接口占位或开工前置 |
| `deferred` | 明确延后；只有边界说明，不承诺 |

## 核心模块（8）

| 模块ID | 名称 | 语言/形态 | 职责（一句话） | 冻结契约 | 依赖 | eval 命令 → 通过线 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|---|---|
| `cs_schema` | 数据契约层 | Python（pydantic v2） | 跨模块数据结构/枚举/常量的唯一事实来源 | 8 模型 + 7 枚举 + 常量表（契约 v1.1，SCHEMA_VERSION="1.1.0"）；extra=forbid + 跨字段不变式 | — | `pytest tests/test_schema.py -q`（cwd=仓库根）→ exit 0（2026-09-29 实测 83 passed，含 ≥12 负例） | 1 | frozen（v1.1） | [cs_schema](specs/cs_schema.md) |
| `cs_sim` | 仿真层 | Python（numpy + 物理引擎 + ikpy） | 模型三级回退装载、FK/IK、可达空间、安全包络校验、对抗 oracle | load_arm/fk/ik/reachable_map 冻结签名；包络禁区+限速场+余量公式（margin=0.17−0.08−0.02−0.05=0.02m≥5mm）；URDF 工具系对齐 Ry(−90°) | cs_schema | `python -m cs_sim.eval --model auto --report reports/sim_eval.json`（cwd=包根）→ exit 0，22 checks 全 True（2026-09-29 实测 tier=mjcf；**环境前提：_vendor 参考件在位**，见 spec §8 坑 1） | 2 | frozen（含环境前提） | [cs_sim](specs/cs_sim.md) |
| `cs_arm` | 执行层 | Python | ArmInterface 抽象 + SafetyEnvelope 硬闸（限速/禁入区/软急停/看门狗）+ MockArm + FeetechArm 骨架 | ArmInterface 四方法 + halt/heartbeat 只增；一切指令经包络；拒绝=零运动且不计 violation | cs_schema, cs_sim | `pytest tests/test_arm_mock.py -q` + `python -m cs_arm.eval_mock --report reports/arm_mock_eval.json`（cwd=包根）→ 急停 ≤100ms、1000 注入 0 违规执行、跟踪 ≤2mm、看门狗 0.5s（2026-09-29 实测全达标；同 cs_sim 环境前提） | 3 | Mock 链路 frozen；FeetechArm partial（骨架 fail-closed） | [cs_arm](specs/cs_arm.md) |
| `cs_mouth` | 感知·口部 | Python（478 关键点推理） | BGR→MouthPose（mono 固定先验 / 腕部 IPD 双职 / depth 保留） | 契约签名 v1.1 向后兼容扩展（cam_pose/pose_provider）；几何口径比标定 0.11/0.23；IPD Z=fx×0.063/ipd_px | cs_schema | `python -m cs_mouth.eval --input assets/face_samples --report reports/mouth_eval.json`（cwd=包根）→ 检出/拒识 ≥95%、张闭嘴 ≥90%、转头 100%、p95 ≤70ms（2026-09-29 实测 exit 0；**延迟阈值负载敏感**，空载跑） | 4 | frozen（mono 主路径）；wrist-view 样本 planned（入口 frozen，缺失 exit 2） | [cs_mouth](specs/cs_mouth.md) |
| `cs_voice` | 交互·语音 | Python（funasr/sherpa-onnx/pyttsx3+SAPI） | VAD→离线 ASR→关键词意图→VoiceIntent；TTS 播报 | VoiceLink start/poll/say 冻结；意图规则表五条顺序即优先级 done>pause>next>resume>greet；select=规则表全未命中后的兜底（全表最低，槽位只取注册菜名表）（2026-09-30 依代码订正，见 cs_voice spec §6） | cs_schema | `python -m cs_voice.eval --input assets/voice_samples --report reports/voice_eval.json`（cwd=包根）→ 20 条 ≥18 对、单条 ≤2.5s、零外联（2026-09-29 实测 20/20、max 0.736s、exit 0） | 5 | frozen | [cs_voice](specs/cs_voice.md) |
| `cs_food` | 感知·勺上/选碗 | Python（OpenCV） | HSV 启发式勺上检查（接口冻结）+ 基准码选碗 | SpoonClassifier Protocol 冻结；config 校验 extra 键拒绝 | cs_schema | `pytest tests/test_food_interface.py -q`（54 用例，2026-09-29 实测绿）+ `python -m cs_food.eval --report reports/food_eval.json`（cwd=包根，合成自检，2026-09-29 实测 exit 0） | 6 | frozen（启发式基线）；分类器 deferred（接口无感替换） | [cs_food](specs/cs_food.md) |
| `cs_orchestra` | 编排层 | Python（py_trees） | 50Hz 行为树：进食全流程 + 安全/交互打断 + 相机角色台账 | 单口状态机 10 相位 + 打断分支表（docstring 即冻结表）；camera_role 每进送达口恰 2 次切换 + 0.5s 曝光稳定窗 | 全部 cs_* | `python -m cs_orchestra.eval --mock --episodes 30 --report reports/orchestra_eval.json`（cwd=包根）→ 30/30 回合、结局表全符、中位 ≤20s（2026-09-29 实测 19.74s；同 cs_sim 环境前提） | 8 | frozen（mock）；真机接线已备（runtime.py 薄封装） | [cs_orchestra](specs/cs_orchestra.md) |
| `cs_dashboard` | 数据层 | Python（FastAPI+SQLite）+ 单页 | 护理看板：HTTP 契约 + SSE + 离线静态页 | 4 个冻结端点 + 追加端点；SQLite 三表；克数 all-or-none 聚合 | cs_schema | `pytest tests/test_dashboard.py -q`（cwd=仓库根，进程内随机端口）→ 5 用例绿、30 口无丢失、聚合一致、零外链（2026-09-29 实测绿） | 7 | frozen | [cs_dashboard](specs/cs_dashboard.md) |

## e2e 门与验收工具（非模块）

| ID | 名称 | 形态 | 职责 | eval → 通过线 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|
| `E2E-mock` | 无硬件端到端 | `scripts/e2e_mock_run.py`（垫片→chengshao/scripts/） | 全链同进程 30 口：mock 臂+行为树+脚本用户+真实看板 HTTP+真实口部冒烟，trace 镜像 | `python scripts/e2e_mock_run.py` → exit 0：30 口闭环、结局 28/1/1、中位 ≤20s、estop ≤0.1s、margin ≥5mm、每口 2 次角色切换（2026-09-29 实测全达标） | 9 | frozen | [e2e-and-gates](specs/e2e-and-gates.md) |
| `EVAL-gate_g1` | 一键门禁 | `scripts/gate_g1.py` | 命名扫描+全量 pytest+4 模块 eval+报告独立复核+看板冒烟 | `python scripts/gate_g1.py` → 8 步全 PASS（**2026-09-30 整门复跑全绿**，`reports/gate_g1.json`；09-29 曾红于模型件前提+门禁项⑤路径误指，均已修复，见 REGENERATE §0） | 10 | frozen（脚本）；门禁状态见该 spec §5 | [e2e-and-gates](specs/e2e-and-gates.md) |
| `EVAL-verify_reports` | 报告独立复核 | `scripts/verify_g1_reports.py` | 只读报告 JSON 独立重算 metrics vs thresholds，与自报 pass 交叉核对 | `python scripts/verify_g1_reports.py` → exit 0 | 10 | frozen | [e2e-and-gates](specs/e2e-and-gates.md) |
| `EVAL-check_naming` | 对外命名扫描 | `chengshao/scripts/check_naming.py`（仓库根垫片） | 公开内容零参考件原始名（一级/二级禁用+警告级） | `python chengshao/scripts/check_naming.py` → forbidden=0（2026-09-29 实测 0/23 warnings） | 0 | frozen | [e2e-and-gates](specs/e2e-and-gates.md) |

## 训练资产包与真机工具链（延后/占位）

| ID | 名称 | 形态 | 职责 | eval → 通过线 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|
| `TRAIN-assets` | 延后训练资产包 | `chengshao/training/`（脚本/配置/runbook） | 策略训练命令生成（fail-closed exit 2）、勺上分类器、拖动示教录制（CS_HW_SESSION 才可执行）、COS 传输计划；**本机零真实训练** | `pytest tests/test_training_scripts.py -q` → 22 用例绿（dry-run） | 11 | frozen-prototype（只写不跑；真实训练在 GPU 机，立项后才执行） | [training-assets](specs/training-assets.md) |
| `HW-toolchain` | 真机工具链 | `cs_arm/feetech.py` 骨架 + bring-up 手册 | 真机串口通道（参数结构冻结、HardwareUnavailable 显式失败）+ 标定/冒烟/成功率/安全演练清单 | 骨架期：构造 FeetechArmConfig 校验（tests 覆盖）；真机 eval 全部 planned（见 spec §3 原表） | 12 | planned（T10 随硬件 bring-up） | [hw-toolchain](specs/hw-toolchain.md) |

## 重生成依赖图（顺序位即拓扑序）

```
0 命名扫描 → 1 cs_schema → 2 cs_sim（需 _vendor 参考件，见 REGENERATE §0）
  → 3 cs_arm(Mock) → 4 cs_mouth（并行无依赖）→ 5 cs_voice（并行无依赖）
  → 6 cs_food（并行无依赖）→ 7 cs_dashboard（并行无依赖）
  → 8 cs_orchestra（依赖 2/3/4/5/6/7 契约）→ 9 e2e → 10 门禁
  → 11 训练资产（独立）→ 12 真机工具链（硬件到货后）
```

- 感知/语音/看板（4/5/6/7）与仿真/执行线（2/3）零依赖可两路并行。
- **2/3/8/9 的验收依赖 cs_sim 模型件环境前提**（`_vendor` 参考件在位；公开克隆环境的
  表现与恢复方法见 [cs_sim spec §8](specs/cs_sim.md) 与 [REGENERATE §0](REGENERATE.md)）。
