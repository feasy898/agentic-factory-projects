# 澄勺 · 演示三件套逐镜头脚本（D9 现场版）

> 任务：B4 / 演示与报名物料包 · 第一件
> 定位：**现场翻车的兜底**。硬件若在 D9 前未 bring-up 成功（或现场展台断电/无显示器），
> 三段录屏直接顶替现场演示，三段合计 4 分 30 秒，片子本身即可讲完 MVP 全貌。
> 权威状态源：`chenmai8/chenmai-feeding-arm/docs/assets/manifest.md`；
> 全部数字引自 `chenmai8/chenmai-feeding-arm/chengshao/reports/*.json` 实测记录（文末列出处）。
> 命名纪律：全文中性命名，不出现任何上游参考项目原名（`check_naming` forbidden=0）。
>
> **录制纪律（对主讲人）**：三段录屏里出现的所有数字都必须能在 `reports/*.json`
> 里逐条对上；不接受的数字一律改口为"设计值/待实测"。片子里不放"未来时"的性能承诺。

---

## 0. 三件套是什么、怎么用

| 段 | 名字 | 演示的是什么 | 对应入口（cwd = `chenmai8/chenmai-feeding-arm/`） |
|---|---|---|---|
| ① | 仿真演示 | 机械臂"舀取→送达→等咬合→撤回"一整口的物理引擎画面 + 安全包络 | `.\.venv\Scripts\python.exe chengshao\scripts\demo_sim.py --bites 3 --speed 6` |
| ② | 口部追踪 | 口部三维单目估计：关键点云、开口条、转头报警、腕部视角估距 | `.\.venv\Scripts\python.exe chengshao\scripts\demo_mouth.py --wrist --source auto` |
| ③ | 全链 mock | 语音点菜→选碗→舀取→勺检→送达→撤回→看板记账 30 口 | `.\.venv\Scripts\python.exe scripts\e2e_mock_run.py --bites 30 --profile rerun` |

三段的**同一件事**：①和③是同一条编排链（`cs_orchestra` 行为树 + `cs_sim` + 安全包络），
③再接上真实的语音意图解析、选碗、勺上检查与看板 HTTP；①只做可视化剪辑，③做全量验收。
因此**片子里的机械臂动作、限速、闩锁行为与验收报告里的数字同源**，不表演。

### 现场三条命令（可直接粘贴）

```bat
cd D:\new-workspace\澄迈项目\机械臂\chenmai8\chenmai-feeding-arm
set PYTHONUTF8=1

REM ① 仿真演示（交互窗口；--frames N 为无显示器环境的干跑自检，退出码 0）
.\.venv\Scripts\python.exe chengshao\scripts\demo_sim.py --bites 3 --speed 6
.\.venv\Scripts\python.exe chengshao\scripts\demo_sim.py --frames 12 --out chengshao\reports\demo_sim_frames

REM ② 口部追踪（--source auto 摄像头优先、打不开自动回退内置视频；--wrist=腕部双职 IPD 估距）
.\.venv\Scripts\python.exe chengshao\scripts\demo_mouth.py --wrist --source auto --max-seconds 120
.\.venv\Scripts\python.exe chengshao\scripts\demo_mouth.py --wrist --frames 8 --out chengshao\reports\demo_mouth_frames

REM ③ 全链 mock 30 口（--profile rerun 把关节流与相机角色事件镜像成 .rrd 供回放）
.\.venv\Scripts\python.exe scripts\e2e_mock_run.py --bites 30 --profile rerun
```

> 参数口径：①② 来自脚本自身的 `--help`（本任务实跑 `./.venv/Scripts/python.exe
> chengshao/scripts/demo_sim.py --help`、`... demo_mouth.py --help`，2026-10-02）；
> ③ **未执行脚本本体**（任务纪律第 6 条：e2e 证据与 trace 由主工作流统一刷新），
> 其参数从脚本源码的 argparse 定义逐条核验。
> ①③ 的 `--bites/--speed/--live-config/--rerun/--frames/--out/--seed`、
> ② 的 `--source/--device/--wrist/--frames/--out/--max-seconds`、③ 的
> `--report/--trace/--bites/--seed/--tts/--profile` 均以上述口径为准。

---

## ① 仿真演示（90 秒）

**片名**：一颗勺子的 20 秒，和它背后的 30 米安全余量
**入口**：`.\.venv\Scripts\python.exe chengshao\scripts\demo_sim.py --bites 3 --speed 6`
**画面**：物理引擎交互窗口（`tier=mjcf` 原生模型，6 关节从臂 + 桌面三碗 + 口部禁入球）

| # | 时长 | 镜头 | 画面上能看到什么 | 讲解词（逐字稿） |
|---|---|---|---|---|
| 1 | 0:00–0:10 | 全景 | 从臂归位，桌面三只碗呈一字排开 | "这是澄勺，桌面助餐机械臂。我们不讲概念，直接看它自己跑一整口：舀一勺、送到嘴前五厘米、等你咬走、撤回来、记一笔。" |
| 2 | 0:10–0:25 | 推近勺上 | 腕部相机视角切近，勺头入碗、抬升 | "第一步是舀取。这里用的是**脚本化参数化轨迹 + 腕部相机闭环**：舀完立刻低头看一眼勺上有没有东西，没有就重舀，失败重试上限两次。**注意勺子始终不越过碗沿往人的方向伸。**" |
| 3 | 0:25–0:45 | 侧移跟拍 | 臂抬起，沿两个过渡点送到用户方向 | "第二步是送达。这里有一个硬数字：口部**禁入球半径 12 厘米**，而勺子的停点是**离口部中心 17 厘米**——也就是球面外 5 厘米。臂只允许停在这个安全距离上，指令本身**写不进球里**。" |
| 4 | 0:45–1:05 | 定格 + 叠加数值 | 停在停点等咬合，画面打出余量算式 | "为什么敢停这么近？余量是这么算的：17 厘米的停点距离，减去勺尖伸出 8 厘米、跟踪误差 2 厘米、感知误差 5 厘米，还**剩 2 厘米正余量**。余量小于 5 毫米就判不合格——这套算式每次运行都会重算，写在验收报告里。" |
| 5 | 1:05–1:20 | 用户前倾示意 | 停点保持，人向前凑 | "最后 5 厘米**不由机器补上，由人补上**：用户前倾自取。软勺、无尖锐边缘、限定低速——这是无深度相机路线下的核心安全设计：**机器负责送，不负责怼**。" |
| 6 | 1:20–1:30 | 收尾 | 撤回、回到家位、跑完 3 口 | "整口结束，用时中位 19.74 秒（仿真时钟）。这就是澄勺的一口。" |

**验收检查单（录制前逐条打勾，全部来自实测报告）**

- [ ] 画面里能看到**面部禁入球**与**送达停点星标**，两者肉眼可分（`--frames` 干跑
      版本在每帧标题打出相位与 `camera_role`；`chenmai8/chenmai-feeding-arm/chengshao/reports/demo_sim_frames/`）
- [ ] 报出的停点距离 = 0.17 m、禁入球半径 = 0.12 m、余量 = 0.02 m —— 与
      `chengshao/reports/sim_eval.json`（2026-09-30）`delivery` 字段逐项一致
- [ ] 报出的单口中位时长 = 19.74 s —— 与 `chengshao/reports/e2e_mock.json`（2026-09-29）
      `median_bite_sim_s` 一致
- [ ] 收尾台词里出现的"3 口"确实是本次 `--bites 3` 的实跑口数，不念报告里的 30 口
- [ ] 演示中**没有**出现"成功率 90%""送达误差 1.5cm"等**真机未实测**的数字
      （这些是 D4–D5 硬件到位后的验收线，本片不得当作已有结果陈述）
- [ ] 无头环境可复现：`demo_sim.py --frames 12 --out ...` 退出码 0（本任务已实跑，见下"本任务自跑记录"）

---

## ② 口部追踪（90 秒）

**片名**：没有深度相机，怎么知道你的嘴在哪
**入口**：`.\.venv\Scripts\python.exe chengshao\scripts\demo_mouth.py --wrist --source auto --max-seconds 120`
**画面**：左=视频画面（478 关键点点云）；右侧仪表面板（`jaw_open` 条 / `head_yaw` 条 /
`frown` 条 / 源与模式 / 基座系坐标 / 单帧推理耗时）；画面横幅（转头居中 `HEAD TURNED - HOLD`，
底部状态行 `MOUTH OPEN - DELIVER` / `FROWN - PAUSE & ASK` / `tracking`）

| # | 时长 | 镜头 | 画面上能看到什么 | 讲解词（逐字稿） |
|---|---|---|---|---|
| 1 | 0:00–0:12 | 人脸入画 | 关键点点云铺满全脸 | "这是整条链路最贵的一个决定：**我们不买深度相机**。整台机器的造价和安全余量都建立在这一个取舍上。" |
| 2 | 0:12–0:30 | 面板特写：jaw_open 条 | 条形随说话起伏，过阈值时横幅变 `MOUTH OPEN - DELIVER` | "先用 478 个面部关键点定位嘴中心。**张嘴判定不是看表情系数，是看嘴腔的几何口径比**——实测标定出两个簇：闭嘴不超过 0.11、张嘴不低于 0.23（簇界记在先验配置里），线性映射到 0 到 1 之后判定线取 0.35，正好落在两簇之间。不用表情系数，是因为实测发现它在这套样本上**区分不开张闭嘴**。" |
| 3 | 0:30–0:48 | 面板特写：Z(ipd) 读数 | 腕部模式下 Z 读数随距离变化 | "嘴在三维空间的位置怎么来？腕部模式下用**瞳距先验**估距：标定内参之后，深度等于焦距乘以瞳距先验除以图像里的瞳距像素。成人瞳距先验 63 毫米——**这是一颗相机的活儿**：同一颗相机，舀取时低头看勺，送达时抬头看脸。" |
| 4 | 0:48–1:05 | 故意转头 | 转头横幅弹出，臂保持不动 | "安全行为：转头超过 25 度，机器**保持不动**并播报提醒，不追着勺子走。低头时同理——人脸丢失超过 1 秒也保持并播报。" |
| 5 | 1:05–1:20 | 皱眉 | `FROWN - PAUSE & ASK` 横幅 | "皱眉超过 0.5，系统暂停并询问。**打扰比没喂到更糟**，所以不确定的时候先停。" |
| 6 | 1:20–1:30 | 面板收尾 | 显示推理耗时与基座系坐标 | "整套感知在普通笔记本 CPU 上跑，实测单帧延迟 p95 29 毫秒、p50 21 毫秒。深度相机我们留了接口，**将来机构版高配随时无感接上**，但今天这套演示不依赖它。" |

**验收检查单**

- [ ] 阈值全部念对：jaw_open 阈值 **0.35**、转头 **25°**、皱眉 **0.5**
      （`chenmai-feeding-arm/chengshao/cs_schema/constants.py:21-23`）；
      口径比簇界 **闭嘴 0.11 / 张嘴 0.23** 与线性映射公式出自
      `chengshao/config/mouth_prior.json` 与 `chengshao/cs_mouth/estimator.py:234-241`
      （0.35 是映射后尺度的判定线，不是 0.11 与 0.23 的算术中点）
- [ ] 延迟数字 = p50 21.1 ms / p95 29.0 ms，且**明确标注为空载实测**
      （`chengshao/reports/mouth_eval.json`，2026-09-30；manifest 备注该阈值对负载敏感）
- [ ] 腕部 IPD 模式的**精度数字不在本片里承诺**——manifest 记 wrist-view 样本为
      `planned`（入口冻结、样本缺失即 exit 2）。本段只讲"机制"不讲"±2–4cm 已达成"
- [ ] 摄像头打不开时**不静默失败**：脚本回退内置视频源，片中不得说"这是实时摄像头画面"
- [ ] 无摄像头环境可复现：`demo_mouth.py --wrist --frames 8 --out ...` 退出码 0
      （本任务已实跑，见下"本任务自跑记录"）

---

## ③ 全链 mock（90 秒）

**片名**：30 口，一句指令到一张报表
**入口**：`.\.venv\Scripts\python.exe scripts\e2e_mock_run.py --bites 30 --profile rerun`
**画面**：终端逐口推进（语音意图 → 选碗 → 舀取 → 勺检 → 送达 → 撤回），
`--profile rerun` 另落 `reports/e2e_mock.rrd` 可回放关节流与相机角色事件；报告落
`chengshao/reports/e2e_mock.json`、逐 tick 轨迹落 `e2e_mock_trace.jsonl`

| # | 时长 | 镜头 | 画面上能看到什么 | 讲解词（逐字稿） |
|---|---|---|---|---|
| 1 | 0:00–0:15 | 起手，终端滚字 | 第 1 口：语音"我想吃芋泥" → `select` 意图 → 菜序映射选碗 | "整链跑一遍。**先说人话**：我张嘴说话点一道菜，系统解析成意图、选中对应碗，全程离线，CPU 跑。" |
| 2 | 0:15–0:30 | 第 3 口 | 首轮舀空 → 勺上检查不过 → 闭环重舀命中 | "第三口故意让它**舀空一次**。腕部相机低头一检，没过，重舀——这就是'闭环重试'，也是我们敢用脚本轨迹而不是端到端学习的原因：**失败路径是被设计出来的，不是祈祷它别发生**。" |
| 3 | 0:30–0:50 | 第 7 口 | 送达中转头 2.5 秒 → 保持 → 播报 → 恢复 | "第七口，送达途中模拟用户转头 2.5 秒：臂**保持不动**、播报提醒、等人转回来再继续。全程没有任何一条指令被绕过安全层。" |
| 4 | 0:50–1:10 | 第 12 口 + 急停 | 送达中软件急停 → 本口 `aborted` → 操作员复位 → 语音"继续" → 续餐 | "第十二口，我们按空格键。**急停是闩锁不是暂停**：闩锁之后 `clear_to_move` 为假，直到显式复位；此时再来的任何指令都是**零运动**。30 口跑完的结果是 28 成功、1 中止、1 拒收——**这两个非成功恰好是这两类注入事件的正确结局**。" |
| 5 | 1:10–1:25 | 第 30 口 | 语音"我吃饱了" → 拒食撤回 → 会话结束 | "第三十口用户说'我吃饱了'，勺子撤回、会话收尾，不硬喂。" |
| 6 | 1:25–1:30 | 报告 JSON 特写 | `bites=30`、`median_bite_sim_s=19.74`、`estop_response_sim_s=0.02`、`margin_m=0.02` | "这是机器生成的验收报告，不是 PPT 数字。**每一个数都能在报告里查到来龙去脉**。" |

**验收检查单**

- [ ] 结局表 = `success 28 / aborted 1 / rejected 1`，且讲解明说"28 成功"而不是"30 成功"
- [ ] 单口中位 19.74 s（阈值 ≤20 s）、急停响应 0.02 仿真秒（阈值 ≤0.1 s）、
      最小点/段间隙 0.05 m、TCP 最小面距 0.17 m、实测最大 TCP 速度 0.144 m/s、
      送达余量 0.02 m（阈值 ≥0.005 m）、相机角色切换 60 次 = 每口恰好 2 次、
      勺上检查 30/30 判对、0 误报 0 漏报 —— 全部与
      `chengshao/reports/e2e_mock.json`（2026-09-29）一致
- [ ] 急停那一段必须**演示复位**："不 reset 就不许再动"是这套安全语义的核心
- [ ] 看板 30 口记账 30/30、聚合一致（`chengshao/reports/dashboard_eval.json`，2026-09-30）
- [ ] 台词不含任何真机指标（舀取成功率、送达误差）——那些等硬件 bring-up 后单独补录

---

## 现场兜底顺序（主讲人按此决策，不要临场想）

```
真机 bring-up 通过？
├─ 是 → 真机走一遍单口（口前 5cm 停点 + 前倾自取），三件套作为讲解补充
└─ 否 → 直接播三段片子 + 现场跑 ① 的 --frames 干跑自检（证明"它确实在跑"）
        兜底中的兜底：连显示器都没有 → 只讲片子，②③ 的终端画面本身就是证据
```

**绝不做的事**：把仿真/mock 画面说成真机；把"待实测"的指标说成"已达成"；
在片子播放失败时改口说"现场环境问题，稍后补录"而不出示报告 JSON。

---

## 本任务自跑记录（B4，2026-10-02，cwd = `chenmai8/chenmai-feeding-arm`）

| 命令 | 用途 | 结果 |
|---|---|---|
| `./.venv/Scripts/python.exe chengshao/scripts/demo_sim.py --help` | 取 ① 的参数口径 | exit 0，输出见 §0 |
| `./.venv/Scripts/python.exe chengshao/scripts/demo_mouth.py --help` | 取 ② 的参数口径 | exit 0，输出见 §0 |
| `grep` ③ 源码 `add_argument` 定义（`chengshao/scripts/e2e_mock_run.py:470-479`） | 取 ③ 的参数口径 | **未执行脚本本体**（纪律第 6 条）；参数 `--report/--trace/--bites/--seed/--tts/--profile` 与源码一致 |
| `./.venv/Scripts/python.exe chengshao/scripts/demo_sim.py --frames 12 --out chengshao/reports/demo_sim_frames` | ① 无头干跑自检 | **exit 0**；终端实印：`模型层级 tier=mjcf 关节=['shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper']`、`禁入区：面部球心 [0.42, 0.0, 0.3] r=0.12m；送达停点 [0.25, 0.0, 0.3]（球外 5cm）`、`demo 完成：bites=3 outcomes=['success','success','success'] sim_s=75.64 violations(unexpected)=[]`、`frames -> chengshao\reports\demo_sim_frames（12 张，源采样 3782）` |
| `./.venv/Scripts/python.exe chengshao/scripts/demo_mouth.py --wrist --source cartoon --frames 8 --out chengshao/reports/demo_mouth_frames` | ② 无头干跑自检（本机无摄像头，改用纯程序合成源 `cartoon`） | **exit 0**；终端实印 8 帧全部 `valid=True source=wrist`、`demo 结束：8 帧` |
| `./.venv/Scripts/python.exe chengshao/scripts/check_naming.py --root <包根绝对路径>` | 包根（公开内容）中性命名门禁 | **forbidden=0，exit 0**（warnings=28，全部为可接受的 'act' 缩写级） |
| 三份物料按 check_naming 同一规则单独扫描（物料在包根之外，不在其扫描范围内） | 本目录三份文档的中性命名 | **forbidden=0，warnings=0** |
| 同一脚本裸跑（不带 `--root`） | 环境差异记录 | 本机 monorepo 根上有 git 仓库，裸跑会扫到 `plan--具身助餐机器人/` 等按纪律允许出现上游名的内部文件与其他项目（forbidden=198，0 条在包根、0 条在三份物料）；门禁口径以包根 scoped 结果为准 |

> **未跑**：③ 的 `scripts/e2e_mock_run.py` 本次**未执行**（任务纪律第 6 条：证据与 trace
> 由主工作流统一刷新）。本文件中 ③ 的一切数字引自既有
> `chenmai8/chenmai-feeding-arm/chengshao/reports/e2e_mock.json`（2026-09-29 实测记录），
> 未新增、未修改任何报告。

## 数字出处一览（供评审逐条复核）

| 数字 | 出处文件 | 记录日期 |
|---|---|---|
| IK 200 目标 199 成功（99.5%）、位置误差上限 0.49 mm、违规轨迹 500/500 拒绝、对抗轨迹 124/124 拒绝、送达余量 0.02 m、可达体素 5605/9576 | `chenmai-feeding-arm/chengshao/reports/sim_eval.json` | 2026-09-30 |
| 急停延迟 0.058 ms、1000 条注入 0 违规执行、近脸限速降到 0.0952 m/s、看门狗 0.5 s | `chenmai-feeding-arm/chengshao/reports/arm_mock_eval.json` | 2026-09-29 |
| 检出率 100%（52 帧）、张闭嘴一致率 100%、转头触发 100%、p50 21.1 ms / p95 29.0 ms | `chenmai-feeding-arm/chengshao/reports/mouth_eval.json` | 2026-09-30 |
| 语音 20/20 正确、单条最大 0.516 s、零外联 | `chenmai-feeding-arm/chengshao/reports/voice_eval.json` | 2026-09-30 |
| 行为树 30/30 回合、450 口、中位 19.74 s、角色切换 900 次 | `chenmai-feeding-arm/chengshao/reports/orchestra_eval.json` | 2026-09-29 |
| 30 口 28/1/1、中位 19.74 s、急停 0.02 s、间隙 0.05 m、余量 0.02 m、切换 60 次 | `chenmai-feeding-arm/chengshao/reports/e2e_mock.json` | 2026-09-29 |
| 看板 30/30 记账、聚合一致、零外链 | `chenmai-feeding-arm/chengshao/reports/dashboard_eval.json` | 2026-09-30 |
| 契约用例 83 通过（含 ≥12 负例） | `chenmai-feeding-arm/chengshao/reports/schema_eval.json` | 2026-10-02 |
| 状态与口径（wrist-view 样本 planned、深度延后保留） | `chenmai-feeding-arm/docs/assets/manifest.md` | 2026-09-30 记录 |
