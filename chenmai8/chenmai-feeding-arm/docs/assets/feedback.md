# 反馈处置台账（feedback）

> 用途：整体评审/外部反馈的逐条处置登记。处置口径三档：**修**=当场已修（附 commit）；
> **缓**=成立但延后（触发条件+落实动作）；**驳**=不采纳（附依据）。本文不留未处置项。
> 纪律：上游参考件零原始名（命名纪律对本文同样生效）；每条带证据指针与复核日期。

## 2026-09-30 · C5 批次整体评审（只读整体评审，一次一项目）

评审总判断：本仓工程纪律完整（契约冻结+独立报告复核+fail-closed 占位+验证状态如实分级），
未发现代码级安全问题或契约违背；真风险不在代码而在"绿色状态只存在于未提交工作树"与
文档同步纪律三处漏洞。评审员实测复现门禁 8 步中的 2 步（check_naming forbidden=0、
全量 pytest 297 passed/1 skipped），其余 6 步仅有当日报告与 commit 证据佐证。

### topDebts 处置（5 条）

| # | finding（摘要） | 处置 | 理由与落实 | 证据指针 | 复核 |
|---|---|---|---|---|---|
| T1 | **high**：门禁项⑤看板冒烟路径修复（`chengshao/tests/` 不存在致 exit 4 → 改仓库根 `tests/test_dashboard.py`）+ 2026-09-30 当日 8/8 证据（4 份 JSON）+ 三处文档状态说明，共 5 文件全部只存在于未提交工作树——新 clone=门禁必红+证据 4/8，与"盲评全过、裁定钉死"直接冲突 | **修**（当场） commit `ed36266` | 工作树修复是正确的（diff 实证：⑤内部命令改 `tests/test_dashboard.py` 相对路径、cwd 改 REPO_ROOT），当日证据与文档说明均自洽，唯一缺口就是未提交。本轮提交修复+4 份证据+三处文档同步（e2e-and-gates §2 表⑤/§5、REGENERATE §0、manifest md/json EVAL-gate_g1 行），绿色状态回到 HEAD。 | `scripts/gate_g1.py:181-183`；`chengshao/reports/gate_g1.json`（steps_passed=8/8，⑤ detail `exit=0, 76.2s`）；`docs/assets/specs/e2e-and-gates.md` §2/§5；`docs/assets/REGENERATE.md` §0；`docs/assets/manifest.md` EVAL-gate_g1 行 | 2026-09-30 已核：报告⑤步 detail 为修复后命令形态，与工作树 diff 一致 |
| T2 | **medium**：git 索引混入 11 个非本仓文件（本仓嵌套路径副本 5 + 兄弟项目门禁垫片 6，`f3bb888` 引入）；工作树另有指向兄弟项目的 junction 与 untracked 兄弟垫片 1 个——新 clone 带出兄弟项目片段，破坏一仓一项目 | **修**（当场） commit `5d97f7e` | 11 个已跟踪垫片经 `git rm -r` 移除（其 docstring 自证为"验收工作流路径兼容转发入口、不纳入本仓跟踪"，对应批次已收敛、使命已完成）；untracked 兄弟垫片删除（删前与真实项目原件比对确认为同方案垫片非独有内容）；junction 经 `cmd rmdir` 删除（只删链接不动目标）；`.gitignore` 补 5 条锚定根的兄弟目录条目。**清理后零回归复验（本轮实测）**：`python chengshao/scripts/check_naming.py` → forbidden=0 / warnings=27（全为 training 侧缩写提示，与评审基线一致）exit 0；`.venv/Scripts/python.exe -m pytest tests/ -q` → 297 passed / 1 skipped、exit 0（281.23s，与文档钉死数字一致）；conftest 会话级钩子改写的三份证据报告已 `git checkout --` 恢复。 | `git ls-files` 清理后零外来条目；`.gitignore:54-58`；本次 commit message 含实测数字 | 2026-09-30 实测 |
| T3 | **medium**：`manifest.md:29` cs_voice 冻结契约列残留旧优先级口径（select 列次高），与已订正的 spec §6 及代码（规则表五条全未命中后 select 才兜底）矛盾；只读 manifest 再生的 agent 会复活原 bug。CONTRACTS §变更流程广播清单漏"manifest 冻结契约列"这一同步点 | **修**（当场） commit `766c5cf` | manifest md/json 契约列订正为"规则表五条顺序即优先级 done>pause>next>resume>greet；select=规则表全未命中后的兜底（全表最低，槽位只取注册菜名表）"；CONTRACTS §变更流程第 1 步显式补"manifest.md/json 冻结契约列同步"。 | `docs/assets/manifest.md` cs_voice 行；`docs/assets/manifest.json` modules[4].contract.intentPriority；`docs/assets/CONTRACTS.md` §版本与变更流程第 1 步；`docs/assets/specs/cs_voice.md` §6（订正权威来源） | 2026-09-30 已核，md/json 双形态一致 |
| T4 | **medium**：README 状态表停更两代里程碑（cs_orchestra 写"未开工"实为 frozen 且 30/30 mock 回合验收，commit `ca12905`；cs_dashboard 写"骨架"）；"详细模块规格见 docs/"实为 docs/assets/；README 是资产包同步纪律不覆盖的第一入口 | **修**（当场） commit `766c5cf` | 模块进度表按 8 模块现状重写（cs_orchestra=编排行为树全节点 mock 30/30、cs_dashboard=护理看板全量、cs_arm 补 fail-closed 真机 T10 注记）；显式声明"状态权威=docs/assets/manifest.md，不一致以 manifest 为准"；补 e2e/门禁/演示三件套入口与当日门禁 8/8 状态；REGENERATE §6 自检清单纳入"README 状态表随状态变化同步刷新"。 | `README.md` 模块进度节；`docs/assets/REGENERATE.md` §6 | 2026-09-30 已核 |
| T5 | **low**：再生环境前提绑死本机——cs_sim 参考模型件实体在本机专用路径，四个参考克隆的原始来源与许可台账只在仓外内部文档；docs/assets 内仅锁定 commit 与中性代号。换机/交付场景下顺序位 2/3/8/9 验收会成片红且仓内无获取路径 | **缓**（交接期执行） | 机制本身 REGENERATE §0 已如实记录（前提缺失时 auto 落 tier3 五关节链、2026-09-29 实测 36 failed），恢复方法三选一（集中参考目录/`_vendor` 布局/`CS_VENDOR_ROOT`）已写明；所缺仅"新机交付时的参考件恢复包"——按锁定 commit 打包四个参考克隆传 COS + 解包后 `CS_VENDOR_ROOT` 指向并跑 `cs_sim.eval` 确认 tier≠chain_builtin（指纹 d75253eb568e8a72）的 SOP。属仓外交接物动作（需 COS 凭据与打包带宽），不在本仓文档处置范围（评审亦明言"docs/assets 无需改动，维持中性纪律"）。**触发条件**：换机演示/交付/交接启动时执行。 | `chengshao/reports/upstream_lock.md`（四克隆锁定 commit 与许可）；`docs/assets/REGENERATE.md` §0 参考件放置三选一 | 2026-10-15 或交接启动日（先到者） |

### demoRisks 处置（9 条）

| # | risk（摘要） | 处置 | 理由与落实 | 证据指针 |
|---|---|---|---|---|
| D1 | 换机演示翻车：物理引擎模型件缺失时 auto 回退链落 tier3 五关节，与契约 6 关节冲突 | **缓**（演示纪律） | 与 T5 同根因同解法。演示期约定：钉死本机跑；任何换机先按 REGENERATE §0 三选一恢复参考件并跑 `cs_sim.eval` 确认 tier≠chain_builtin 再彩排 | `docs/assets/REGENERATE.md` §0/§8 坑 2 |
| D2 | ASR 冷缓存首载 ≈172s（voice_eval 实测 model_load_s=57.9），演示开场卡顿 | **缓**（演示彩排项） | REGENERATE 坑 7 已有暖机指引。落实为演示 SOP 固定动作：开场前先跑一次 `cs_voice.eval` 或 demo 预热；多线程 rtf 抖动已由缺省单线程规避，勿改 | `docs/assets/REGENERATE.md` §8 坑 7；`chengshao/reports/voice_eval.json` |
| D3 | 口部追踪 p95≤70ms 负载敏感（空载 39.7ms PASS / 并行负载 75.1ms 假 FAIL） | **缓**（已有文档+演示纪律） | REGENERATE 坑 6 与 manifest cs_mouth 行均已标注"空载跑"。落实：演示时清空后台重负载（含全量 pytest——正是本轮处置跑过的东西） | `docs/assets/REGENERATE.md` §8 坑 6；`docs/assets/manifest.md` cs_mouth 行 |
| D4 | demo_mouth 四源回退链会静默切源（演示机摄像头被占用/不存在时画面悄然换源） | **缓**（演示彩排项） | REGENERATE §3 已列四源顺序。落实：彩排时显式锁定 `--source` 并预演一遍回退路径 | `docs/assets/REGENERATE.md` §3；`chengshao/scripts/demo_mouth.py --help` |
| D5 | 物理引擎视窗在远程桌面/无 GL 环境可能开不了窗 | **缓**（兜底已备，彩排预演） | 无头 `--frames` 落帧兜底已实测 exit 0（commit `c099571`）；REGENERATE §3 已备三段各 90s 录屏兜底。落实：彩排时验证演示机窗口可用，不可用即切录屏兜底 | `docs/assets/REGENERATE.md` §3；git log `c099571` |
| D6 | 演示/验收前误跑全量 pytest 或 e2e：conftest 会话级钩子当场改写 schema/food/dashboard 三份证据报告，trace 审计流被小规模试验覆盖 | **修**（当场） commit `766c5cf` | REGENERATE §3 增演示期警示框：禁在演示/验收前跑全量套件；误跑后 `git checkout -- chengshao/reports/` 恢复。本轮处置全程实测了该行为（全量 pytest 后三份报告确被重写，已按此恢复），警示非纸面推演 | `docs/assets/REGENERATE.md` §3 警示框；§8 坑 5/坑 13 |
| D7 | 门禁修复未提交前不可当场给评委跑 gate_g1（HEAD 上项⑤必红 exit 4） | **修**（随 T1 消解） commit `ed36266` | 修复+当日证据已入 HEAD，整门 8/8；门禁逐项回显形态适合答辩展示，可放心用作演示环节 | `chengshao/reports/gate_g1.json`；commit `ed36266` |
| D8 | 看板演示数据是脚本灌入的 30 口 mock 记录（非真实老人数据）；服务缺省绑 127.0.0.1:8100，投屏时勿改绑 0.0.0.0 | **缓**（答辩口径纪律） | 答辩如实声明"脱敏仿真数据"；投屏用演示机本机浏览器，不改 `--host`（无安全与契约上的必要） | `chengshao/cs_dashboard/__main__.py:19`（缺省 127.0.0.1:8100）；`data/`（gitignore） |
| D9 | 评委若期待物理臂：现场只有仿真+腕部相机双职演示可给（硬件在途，从臂/相机未到货） | **缓**（答辩口径纪律） | FeetechArm 未接硬件即显式失败是 fail-closed 契约的一部分；真机 eval 全部 planned（T10）。答辩如实说"软件形态演示，真机为下一里程碑"，勿临时接舵机表演未验收路径 | `chengshao/cs_arm/feetech.py:35`（HardwareUnavailable）；`docs/assets/specs/hw-toolchain.md` §3；`docs/assets/manifest.md` HW-toolchain 行 |

### 本轮处置自我声明（验证边界）

- 本轮实测执行的检查：`python chengshao/scripts/check_naming.py`（forbidden=0，exit 0）、
  `.venv/Scripts/python.exe -m pytest tests/ -q`（297 passed / 1 skipped，exit 0，281.23s）——
  均在 T2 索引清理之后执行，作为清理零回归依据。
- 未重跑：门禁整链 8/8 与各模块 eval / 独立复核 / e2e（单次 ≈50min 且受 D6 演示期纪律约束）；
  其效力依据为 2026-09-30 当日 `reports/gate_g1.json` 报告与相应 commit。
