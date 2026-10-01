# 整仓再生手册（REGENERATE）

> 目标：新 agent 只凭本手册 + 各 spec，在干净机器上从零重建全部已实现模块并通过验收门。
> 所有命令在**仓库根**执行（`cwd=包根` 的另有注明）；通过线均为实测值，
> 验证状态详见 [manifest.md](manifest.md) 各行 `verified`。

---

## 0. 当前状态与首要前提（2026-09-30 回炉更新——重生成前必读）

- **模型件前提（2026-09-30 状态：已恢复）**：cs_sim 的 `load_arm("auto")` 依赖参考模型件
  （gitignore、永不入库；内部代号 `vendor-arm-model`，锁定 commit 与实体位置见
  `chengshao/reports/upstream_lock.md`）。参考件曾于 2026-09-29 被整体移出工作区
  （安全扫描门禁要求），当日 `auto` 回退链落到 tier3 内置名义链（5 关节，与契约
  `N_ARM_JOINTS=6` 不匹配），实测 `pytest tests/` 36 failed / 260 passed / 2 skipped。
  **同日 commit `cea83b1` 修复**：模型发现回退链增补工作区外集中参考目录
  `D:/upstream-refs/robot-vendor`（存在才加入）+ `CS_VENDOR_ROOT` 环境变量覆盖
  （最高优先）。**2026-09-30 回炉实测：`pytest tests/` 297 passed / 1 skipped、
  exit 0**（本机集中参考目录在位）。
- **参考件放置方法（三选一）**：
  1. 工作区外集中参考目录 `D:/upstream-refs/robot-vendor`（现行缺省，代码自动发现）；
  2. 把参考件放回可发现的 `_vendor/` 布局：仓库根或包根旁建 `_vendor/<参考件>/`，
     使 `*/Simulation/*/*.xml`（或 `*.urdf`）glob 命中（评分规则见
     [cs_sim spec §2](specs/cs_sim.md)；判据：`reports/sim_eval.json` 历史记录
     tier=`mjcf`、模型指纹 `file_sha256_16=d75253eb568e8a72`、6 关节）；
     `_vendor` 已 gitignore，不入库；
  3. 设 `CS_VENDOR_ROOT` 指向任意含参考件的根，或对 eval/调用显式传模型路径
     `load_arm(path)`（跳过 auto 发现）。
  恢复后先跑 `python -m cs_sim.eval`（tier 必须非 chain_builtin）再跑全量。
- 门禁脚本 `python scripts/gate_g1.py` 在参考件完全缺失时**注定红**——这不是代码回归，
  是环境前提；恢复前提后应全绿复跑并刷新 `reports/gate_g1.json`。**原另一已知红项已清零
  （2026-09-30）**：门禁项⑤看板冒烟曾误指不存在的 `chengshao/tests/`（实测 exit 4），
  `gate_g1.py` 已改为仓库根 `tests/test_dashboard.py` 相对路径（cwd=REPO_ROOT），
  当日整门复跑 **8/8 PASS**——见 [e2e-and-gates spec §2/§5](specs/e2e-and-gates.md)。

## 1. 环境准备（实测版本，钉版即契约）

| 件 | 实测版本 | 说明 |
|---|---|---|
| OS / Shell | Windows Server 2022 + Git Bash | 仓库路径含中文——见 §8 坑 1 |
| Python | **3.12.10** | venv 固定在**仓库根 `.venv/`**（不是包根） |

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r chengshao/requirements.txt
#   全量锁定 pip freeze 固化 170 项；核心钉版：mujoco==3.14.0 / py_trees==2.6.0 /
#   funasr==1.4.16 / mediapipe==1.0.1 / fastapi==0.141.1 / uvicorn==0.54.0 /
#   pydantic==2.13.5 / opencv-contrib-python==5.0.0.93 / ikpy==4.1.0 /
#   机器人学习运行栈 0.6.1（发行名见 requirements.txt 包名位；内部代号 vendor-robot-stack）/
#   feetech-servo-sdk==1.0.0
```

- **模型权重（一次性，不入库）**：`python chengshao/scripts/fetch_models.py`
  → `chengshao/models/face_landmarker.task`（478 关键点模型；`.gitignore` 含 `*.task`/`models/`）。
- **语音 ASR 模型**：funasr 首次运行经 modelscope 拉取小体积识别模型到本地缓存
  （`~/.cache/modelscope`；冷缓存首载实测 ≈172s，之后读本地全程离线；
  回退后端 sherpa-onnx 需 env `CS_VOICE_ONNX_DIR`，见 [cs_voice spec §4](specs/cs_voice.md)）。
- 网络受限时 pip 选国内镜像；GPU 机训练环境完全独立（`chengshao/training/runbook_gpu.md`，
  立项后才执行）。

## 2. 模块重生成顺序（依赖图即拓扑序；与 manifest 顺序位一致）

| 步 | 模块 | 验收命令（cwd 见括号） | 通过线 | spec |
|---|---|---|---|---|
| 0 | 命名扫描 | `python chengshao/scripts/check_naming.py` | forbidden=0 | [e2e-and-gates](specs/e2e-and-gates.md) |
| 1 | cs_schema | `.venv/Scripts/python.exe -m pytest tests/test_schema.py -q`（根） | exit 0 | [cs_schema](specs/cs_schema.md) |
| 2 | cs_sim | `python -m cs_sim.eval --model auto --report reports/sim_eval.json`（包根） | exit 0，22 checks；**先确认 tier≠chain_builtin** | [cs_sim](specs/cs_sim.md) |
| 3 | cs_arm | `pytest tests/test_arm_mock.py -q`（根）+ `python -m cs_arm.eval_mock --report reports/arm_mock_eval.json`（包根） | 急停 ≤100ms、1000 注入 0 违规 | [cs_arm](specs/cs_arm.md) |
| 4 | cs_mouth | `python -m cs_mouth.eval --input assets/face_samples --report reports/mouth_eval.json`（包根） | 检出/拒识/张闭嘴/转头线 + p95 ≤70ms（**空载跑**） | [cs_mouth](specs/cs_mouth.md) |
| 5 | cs_voice | `python -m cs_voice.eval --input assets/voice_samples --report reports/voice_eval.json`（包根） | ≥18/20、≤2.5s、零外联 | [cs_voice](specs/cs_voice.md) |
| 6 | cs_food | `pytest tests/test_food_interface.py -q`（根）+ `python -m cs_food.eval`（包根） | 全绿 + 合成自检 | [cs_food](specs/cs_food.md) |
| 7 | cs_dashboard | `.venv/Scripts/python.exe -m pytest tests/test_dashboard.py -q`（根） | 5 用例绿、30 口无丢失 | [cs_dashboard](specs/cs_dashboard.md) |
| 8 | cs_orchestra | `python -m cs_orchestra.eval --mock --episodes 30 --report reports/orchestra_eval.json`（包根） | 30/30、中位 ≤20s、角色切换 2/口 | [cs_orchestra](specs/cs_orchestra.md) |
| 9 | e2e | `python scripts/e2e_mock_run.py`（根） | exit 0（12 项判据） | [e2e-and-gates](specs/e2e-and-gates.md) |
| 10 | 门禁 | `python scripts/gate_g1.py`（系统 Python 即可，内部用 .venv） | 8 步全 PASS | [e2e-and-gates](specs/e2e-and-gates.md) |
| 11 | 训练资产 | `pytest tests/test_training_scripts.py -q`（根；dry-run） | 22 用例绿 | [training-assets](specs/training-assets.md) |
| 12 | 真机工具链 | ——（硬件到货后 T10；spec §3 清单全部 planned） | —— | [hw-toolchain](specs/hw-toolchain.md) |

- 4/5/6/7（感知/语音/看板）与 2/3（仿真/执行）零依赖，可两路并行。
- 实测耗时参考（参考机，单模块）：cs_sim ≈12.4min（可达性扫描 ~705s 占大头）、
  cs_arm eval_mock ≈2.6min、cs_voice ≈4min（含模型加载）、cs_orchestra 30 回合 ≈25min、
  全量 pytest ≈6.7min、e2e ≈2min。

## 3. 演示兜底（无硬件可演示三件套）

```bash
python chengshao/scripts/demo_sim.py      # 仿真演示：MuJoCo 窗口舀取→送达→撤回循环
python chengshao/scripts/demo_mouth.py    # 口部追踪演示：478 关键点/张嘴条/转头报警（四源输入）
python scripts/e2e_mock_run.py --profile rerun   # 全链 mock + 调试流旁挂
```

（脚本能力细节见各自 `--help` 与 docstring；录制兜底：演示前备好三段各 90s 录屏。）

> **演示/验收期警示**：勿在演示或评委验收前随手跑全量 pytest 或 e2e——conftest
> 会话级钩子会当场改写 `reports/` 的 schema/food/dashboard 三份证据报告（坑 5），
> 小规模试验会覆盖 trace 审计流（坑 13）。误跑后
> `git checkout -- chengshao/reports/` 恢复证据文件再演示。

## 4. 替换/重生成模块时的回归清单

| 被替换模块 | 必跑回归 | 额外人工检查 |
|---|---|---|
| cs_schema | test_schema + 全量 pytest（契约被所有模块消费） | 枚举/常量是否被任何模块按字面复述（改值会静默漂移）；fixtures 同步；CHANGELOG 追加 |
| cs_sim | sim_eval + test_sim + cs_arm/orchestra/e2e 链 | 包络缺省与 workspace.json 仍一致；tier 指纹记录进报告 |
| cs_arm | test_arm_mock + eval_mock + e2e | 拒绝 reason 词表未收窄；cartesian 改写统计仍增长 |
| cs_mouth | mouth_eval（空载）+ e2e 口部冒烟 | 口径比标定值改动须回填 config 与 spec；样本标签未漂移 |
| cs_voice | voice_eval + e2e 语音注入 | 意图优先级表未变；TTS 降级路径仍 available=False 可跑 |
| cs_food | food 两连 + e2e 勺检 | 阈值仍偏保守（宁重舀）；未登记码仍忽略 |
| cs_dashboard | test_dashboard + e2e 看板比对 | HTTP 契约 4 端点未改名；聚合 all-or-none 口径未变 |
| cs_orchestra | orchestra_eval + e2e | 状态转移表 docstring 与实现一致（tests 按表断言）；角色切换恰 2 次/口 |

通用纪律：eval **先清旧证据再跑**（reports 是本次真事实）；任何替换后先过
`gate_g1` 再提交；提交信息用中性描述（命名纪律对 commit message 同样生效）。

## 5. 再生试验 SOP（验证"spec+eval 可再生"资产主张）

1. **隔离**：独立工作目录，拷入 `docs/assets/` 全部 spec + 被测模块 `tests/`（冻结一字不改）
   与 config 骨架；**不拷贝原实现**。
2. **环境前置由 spec 声明（硬性条款）**：冻结测试对 `_vendor` 布局/venv 路径/cwd 形态
   （仓库根 pytest vs 包根 `-m`）的一切假设必须**事先写进该模块 spec**
   （范例：[cs_sim spec §8](specs/cs_sim.md) 坑 1、[e2e-and-gates §1](specs/e2e-and-gates.md)）；
   禁止实现者自创 junction/挪文件凑路径——工作流门因环境假设瞬时失败的判 spec 缺口，回炉补 spec。
3. **盲实现**：只准看 spec 与冻结测试；允许跑测试自验。
4. **裁定**：模块自验收 + 相关 pytest + 门禁相关门项；判据 = 冻结测试全绿 + 通过线达标。
5. **缺口回炉**：实现 bug → 修原实现；spec 歧义/缺失 → 补 spec；流程问题 → 改本 SOP。
   三类各自单独 commit。
6. **记录**：结果（模块/日期/首跑结果/回炉清单）追加到本节。

已登记试验：本资产包为首版（2026-09-29），尚无独立盲实现批次；撰写过程中的核验方法
（逐行对照代码 + 当日真实 eval 运行）即 §4 回归清单的来源。

## 6. 文档与资产自检

- 本资产包（docs/assets/）随代码演进：模块状态变化 → 改 manifest.md/json 的 status 与
  verified；契约变更 → 走 [CONTRACTS §变更流程](CONTRACTS.md)。
- **README.md 的模块进度表随状态变化同步刷新**（README 是资产包同步纪律之外的第一入口，
  曾停更两代里程碑——2026-09-30 订正；表内声明状态权威=manifest.md，两处不一致以
  manifest 为准，但摘要表本身不得停留在过期状态）。
- 公开仓纪律自查（每次发布前）：`python chengshao/scripts/check_naming.py` 必须零 FORBIDDEN
  （WARNING 级人工复核）；`_vendor/`、上游原始路径不入库、不入 commit message。
- 报告复核：`python scripts/verify_g1_reports.py`（独立重算，防"自报即通过"）。

## 7. 本资产包的变更史指针

| commit | 内容 |
|---|---|
| （specs commit） | docs/assets/specs/ 11 篇逐模块 spec |
| （manifest commit） | manifest.md + manifest.json |
| （contract commit） | CONTRACTS.md + REGENERATE.md |
| （reports commit） | 撰写日 eval 证据刷新（含真实运行记录与当日门禁红/绿如实状态） |
| `f3bb888` 及更早 | 模块本体构建史（T0–T9，git log chengshao/） |

## 8. 已知坑清单（构建与再生实测，重生成必读）

1. **中文路径 × 图像/视频/物理引擎**：仓库绝对路径含非 ASCII——cv2
   `imread/imwrite/VideoCapture` 静默失败（须 `cs_mouth/imgio.py` 的 `*_u` 字节流系列）；
   物理引擎按绝对路径打开模型失败（cs_sim 已相对化规避）。新工具链先过这一关。
2. **模型回退链 5≠6 关节**（本手册 §0，最重要）：`auto` 无 `_vendor` 参考件时落 tier3
   内置名义链（5 关节无夹爪），与契约 6 关节冲突——ArmState 类 pydantic `too_short`
   成片失败。先满足模型前提，再谈其他。
3. **venv 在仓库根**：`.venv/` 在仓库根（不是 chengshao/ 包根）；包根运行形态用
   `../.venv/Scripts/python.exe -m cs_<pkg>...`。两种 import 形态（`chengshao.cs_x` 与
   `cs_x`）由各包 `__init__` 的别名机制统一（保证 isinstance 同类）。
4. **模块 eval 的 cwd 契约**：`python -m cs_sim/cs_arm.eval_mock/cs_mouth.eval/
   cs_voice.eval/cs_food.eval/cs_orchestra.eval` 在**包根 chengshao/** 下执行
   （仓库根用 `python -m chengshao.cs_x...` 等价形态）；pytest 在仓库根
   （pytest.ini `pythonpath=.`）。
5. **报告 `exit_status` 是会话级**：conftest 钩子写的 schema/food_interface 报告在
   与失败模块同会话时会记 exit 1 / pass False——独立跑该文件才是干净结论。
6. **mouth 延迟阈值负载敏感**：p95 ≤70ms 在并行重负载下会假失败（实测 75.1ms FAIL →
   空载 39.7ms PASS）。验收评估串行跑。
7. **ASR 冷缓存首载 ≈172s**：cs_voice eval / 演示前先暖一次模型；64 核 Windows 必须
   torch 单线程（`CS_VOICE_TORCH_THREADS=1` 缺省即是），多线程 rtf 反而抖到 1.5+。
8. **TTS 双通道设计是坑驱动的**：pyttsx3 的 init 单例 + runAndWait 不可并发/复用——
   合成走单例工作线程、播放走一次性线程原生 SAPI COM；勿"简化"回 pyttsx3 直播。
9. **静帧 blendshape jawOpen 不区分张闭嘴**（实测张 0.079–0.094 vs 闭 0.093）——张嘴判定
   是几何口径比（标定 0.11/0.23），闭嘴滞后阈值 0.20 在编排层（cs_orchestra.nodes）。
10. **blendshape browDown 微笑误报 0.68**——皱眉用 mouthFrown 左右均值。
11. **全零位形是禁入区内的家位**（TCP 距口部点 ≈0.079m < 0.12m）——MockArm 缺省家位
    必须采样生成（种子 20260928）；写死零位会立即闩锁。
12. **Windows 控制台编码**：一切子进程统一注入 `PYTHONUTF8=1`（GBK 控制台中文乱码）；
    门禁/垫片脚本已内置。
13. **trace 是追加式审计流**：orchestra/e2e 的 trace JSONL 由 eval 自身截断重写——
    跑小规模试验会覆盖全量绿色证据，证据性文件跑完大验收后不要再碰
    （或先 `git checkout -- <trace>` 恢复）。
14. **占位即契约（fail-closed）**：`FeetechArm` 骨架方法抛 HardwareUnavailable、
    `build_train_cmd` 无入口名 exit 2、`cs_mouth.eval --wrist-view/--static-distance`
    样本缺失 exit 2——这些是**当前契约的一部分**，不要"顺手实现"而不改 spec。
15. **命名扫描把文档当一等公民**：specs/文档里复述禁用词同样命中（撰写本资产包时被
    当场拦下 7 条）——写规则时用"见扫描器 FORBIDDEN_ALL"代替字面清单。
