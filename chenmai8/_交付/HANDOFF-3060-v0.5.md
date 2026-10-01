# HANDOFF v0.5 — 3060 Ubuntu 桌面：澄勺机械臂 D3 启动单

> 写给：3060 Ubuntu desktop 上即将启动的 agent（ZCode CLI + workflow + 子代理）。
> 发自：windev-01 主线 agent（本机负责全部软件面开发，硬件面归 3060）。
> 日期：2026-10-01（10 天契约 D3，硬件 T10 已到货、已在 3060 上位）。
> 目标倒计时：**D9（约 10-06/07）必须能演示；D10=2026-10-08 报名材料截止。**
> 本文是 v0.5（环境引导 + bring-up 启动 + 红线 + 节奏）；v1 将补 sprint workflow 脚本与
> 模块所有权协议。本文与 v1 以 git 中最新版为准，冲突时以冻结契约为准。

---

## 0. 一句话总纲

3060 负责**硬件关键路径**（环境重建 → M4 bring-up → M5 舀取调参 → M6 集成/演练/自试）；
windev-01 负责**全部软件面**（bring-up 脚本包、仿真预扫参、训练资产、demo 物料）。
双方只推分支不直推 main；每日一次合并窗口由 windev-01 主合并并复跑门禁。

## 1. 仓库与克隆（公开仓）

- 仓：`https://github.com/feasy898/agentic-factory-projects.git`（默认分支 main）
- 项目根：`chengmai8/chenmai-feeding-arm/`（本文简称"包根"）；权威状态 `docs/assets/manifest.md`，
  进度口径冲突以 manifest 为准。
- 国内直连 GitHub 慢时的兜底顺序：① `git clone --filter=blob:none --sparse` 后
  `git sparse-checkout set chenmai8`；② codeload tar 包
  （`https://codeload.github.com/feasy898/agentic-factory-projects/tar.gz/refs/heads/main`）；
  ③ 入 tailnet 后经 hk-gateway 中继。
- 已知仓库特性：仓内有一个名为 `NUL` 的文件（zcode-research 子树，Windows 克隆会
  checkout 失败、Linux 无此问题）；中文路径下的 cv2 读写坑代码层已处理（`cs_mouth/imgio.py`）。
- 凭据：推送用 owner 的 feasy898 PAT（3060 上由 agent 以 0600 权限写
  `~/.git-credentials` 或走 credential store；**密钥零落盘、零进对话**）。

## 2. 3060 环境 bootstrap（按序执行，每步留证据到 `_交付/evidence/`）

1. **硬件安全前置（未完成前三项前不得给舵机上电做任何运动）**：
   - 核对 6 只 12V 舵机与 12V 电源适配器规格一致（严禁混压）；
   - 腕部相机线缆预留臂全行程运动余量；
   - 桌面防滑垫 + 座椅定位贴就位（单目先验的误差吸收设计）。
2. **系统权限**：`sudo usermod -aG dialout,video $USER` 后**重新登录**；
   确认 `ls /dev/ttyUSB*` 与 `v4l2-ctl --list-devices` 可见（装 `v4l-utils`）。
3. **Python 环境**：Python 3.12 + venv 建在**包根**（`chenmai8/chenmai-feeding-arm/.venv`，
   不是 monorepo 根）；pip 走国内镜像（阿里云 `https://mirrors.aliyun.com/pypi/simple/`）。
4. **依赖安装**：`pip install -r chengshao/requirements-rebuild.txt`
   （windev-01 侧预解析版；与原冻结的差异台账见 `_交付/evidence/env-rebuild.md`）。
   **Windows 专属包在 Ubuntu 上直接删行**：`pywin32` / `pypiwin32` / `comtypes`（无 Linux wheel）。
   其余钉版不变；若再遇到"源上不存在的钉版"，取最高可用版并在 env-rebuild.md 记差异。
5. **仿真模型前提（cs_sim 的 `load_arm("auto")` 必须落 tier=mjcf、6 关节）**：
   上游参考件 `vendor-arm-model` 的 Simulation 子集从 COS 拉取：
   - 入 tailnet 后：`coscmd config` 用 Vault `secret/tencentcloud` 的 COS 凭据 →
     `coscmd download chenmai8/c1-arm-vendor/simulation/ <本地目录>/`
     （上传与精确路径以 windev-01 侧 env-rebuild.md 记录为准；upload 完成前，
      owner 直接从内网中转或按 bao 台账 git clone 锁定 commit 的四个上游仓）。
   - 放置：设 `CS_VENDOR_ROOT=<含参考件的根>`（代码自动发现，最高优先）。
   - 四个上游仓的 URL+锁定 commit 台账在 **bao**（`secret/chenmai8/upstream-refs`，
     中性代号引用；URL 属内部信息，严禁写入公开仓任何文件——命名门禁会拦）。
   - 自检：`python -m cs_sim.eval --model auto --report reports/sim_eval.json` 在包根跑，
     tier 必须非 chain_builtin、`N_ARM_JOINTS=6`。
6. **模型权重**：`python chengshao/scripts/fetch_models.py`（人脸 478 关键点；
   直连失败用 `--url` 走 hf-mirror/modelscope 白名单镜像，脚本内置 SSRF 白名单，勿绕）。
7. **语音模型暖机**：funasr 首次经 modelscope 拉小模型（国内直连可达，冷启 ≈172s），
   gate 跑之前先暖一次。
8. **复跑门禁建立基线**：`python scripts/gate_g1.py`（系统 Python 即可，内部切 .venv）。
   预期 7 步全 PASS（参考耗时：pytest ≈7min、cs_sim ≈12min、orchestra ≈25min、voice ≈4min，
   整门约 40–60min；cs_mouth 延迟阈值负载敏感，**空载串行跑**）。

## 3. M4 bring-up 顺序（照 §5.9 与 hw-toolchain spec，逐步留 JSON 证据 + git tag）

| # | 步骤 | 命令/入口 | 通过线 |
|---|---|---|---|
| 1 | 舵机标定 + 连通冒烟 | 标定入口 + `python -m cs_arm.eval_hw` | 6/6 舵机连通、回读一致、限位/温度正常、夹爪开合 |
| 2 | 顶部手眼（eye-to-hand） | `python scripts/calibrate_handeye.py --cam scene --points 12 --out config/calib/handeye_scene.npz` | 重投影残差 ≤3mm 或 ≤2px |
| 3 | 腕部手眼（eye-in-hand） | `... --cam wrist --mode eye-in-hand --points 15 --out config/calib/handeye_wrist.npz` | 同上；npz 优先覆盖 `cs_orchestra.core.NOMINAL_T_FLANGE_CAM` 名义值 |
| 4 | 相机验收 | `python scripts/camera_check.py` | 顶部基准码可辨；腕部 20–50cm 面部可辨、曝光恢复 ≤1s、线缆无牵扯；不达标→第三相机回退（接口已抽象多路） |
| 5 | 口部静态尺度核查 | `python -m cs_mouth.eval --static-distance --report reports/mouth_prior_eval.json` | 0.35/0.45/0.55m 三点 ≤5cm（记录项，不阻塞） |
| 6 | 腕部口部追踪 live | `python -m cs_mouth.eval --wrist-view --live --report reports/mouth_wrist_eval.json` | 四点 ≤4cm、检出率 ≥95%、曝光切换恢复 ≤1s、帧流不中断 |
| 7 | 分食物舀取 | `python -m cs_arm.eval_scoop --food <each> --trials 50` | 最终 ≥90%、首试 ≥70%（先用 windev-01 交付的仿真推荐初始参数） |
| 8 | 安全实测 | `python scripts/safety_drill.py --cases head_turn,estop,face_intrude --trials 20` | 20/20 停止或后撤；禁入区侵入 0 次 |

> 注：以上命令入口在 hw-toolchain spec 中状态为 **planned（未实现）**——windev-01 会在
> HANDOFF v1 前后交付"mock dry-run 全绿"的实现包；3060 拿到包后先在 mock 模式跑通再上真机。
> 上真机前必须：软急停（空格 latch）可用、限速生效、禁入区参数已按红线加载。

## 4. 安全红线（冻结，任何 agent 不得放宽；违反即停线报 owner）

- 禁入区 = 口部点外扩 **r=0.12m 球域 + 躯干胶囊**；速度：接近段 **≤0.15m/s**、
  面部 15cm 内 **≤0.10m/s**；软急停 = **空格键 latch** SafetyEnvelope。
- `violation != "none"` → `clear_to_move=False`，直到显式 `reset()` 才解锁。
- **ArmCommand 只能由 SafetyEnvelope 下达到执行层**；FeetechArm 不重复包络检查（硬闸单点在包络层）。
- 看门狗：串口巡检读数提供 snapshot_state 快照而**不喂心跳**（与 MockArm 同语义）；halt() 立即冻结。
- 兜底：软勺 + 低速 + 用户前倾自取；如需物理急停，常闭蘑菇头串入从臂电源线（备件清单 ¥15–40）。
- 阈值/判据第一批判定后**不可改**；改阈值 = 改契约 + 人审留痕。

## 5. 回退策略（连续 2 轮 eval 不过即按序回退；仍不过 → 升级 owner，不空转）

| 失败点 | 回退 |
|---|---|
| 机器人学习运行栈 follower 通道在 Ubuntu 异常 | 换传输层 B：feetech 官方 SDK 直连（`feetech-servo-sdk` 已锁 1.0.0，只换传输层、接口不变） |
| cs_sim 模型件缺失/回退链 5≠6 关节 | 先修 `CS_VENDOR_ROOT`；再 MJCF→URDF→ikpy 链降级 |
| 腕部相机对焦/曝光不达标 | 加购第三路专职人脸相机（多路相机接口已抽象，接入即用） |
| 某食物舀取不达标 | 换食物/参数扫参/收紧闭环阈值；sim 预扫参数（windev-01 交付）起步 |
| 依赖装不上 | 国内镜像 + 逐包回退（mediapipe→py3.11 venv；funasr→sherpa-onnx） |

## 6. 工作方式（与全仓方法论一致）

- **每任务 DoD**：代码 + 指定 eval 跑绿（exit 0）+ `reports/` JSON 证据 + git tag + 命名检查零命中。
- **子代理派发模板**：模块 spec（§3 契约 + §5.x spec）+ 唯一 eval 命令 + 阈值 + JSON 报告格式
  `{module,date,cmd,metrics,thresholds,pass}` + DoD + 禁令（不改冻结签名、不引入上游原名）。
- **会话角色**：S-执行（写代码，不自判完成）/ S-验收（跑门禁，不信任自报，与执行不同会话）/
  S-评审（盲态独立复核，结论回写 `_reviews/`）/ S-人审（owner 触点：阈值冻结确认、凭证供给、
  废留处置）。
- **分支约定**：3060 推 `hw/*` 分支；windev-01 推 `sw/*`；每日 21:00 前后合并窗口，
  windev-01 合并后复跑 gate_g1 并打整合 tag。冲突以冻结契约为准。
- **每日 rhythm**：撤点前更新 `_交付/调度台.md` 与 `chengmai8/worklog.md`；每任务证据落盘；
  摘要一段回传 owner（3060 侧 agent 负责产出 digest，windev-01 汇总转发）。

## 7. 资源位置（密钥一律走 Vault/bao，零落盘）

- **tailnet 预授权 key**（可复用、7 天）：bao `secret/chenmai8/tailnet-preauth-3060`
  （srv-1=100.64.0.6；入网前由 owner 中转给你；入网命令模板：
  `tailscale up --login-server=https://net.hkmingdajiaoyu.com --authkey <key>`；
  **机器上严禁装 mihomo 类 TUN 代理**，会弄死 tailscale 数据面）。
- **四个上游参考仓 URL + 锁定 commit**：bao `secret/chenmai8/upstream-refs`。
- **COS 凭据**（厂商件镜像/大文件中转）：Vault `secret/tencentcloud`（100.64.0.2:8200）。
- **GitHub PAT**（owner feasy898）：owner 直接交付给 3060 agent，0600 落盘。
- **LLM 通道**：3060 的 ZCode CLI 用 minimax 通道（`minimax/MiniMax-M3.1-Flash-Preview`
  作 workflow 子代理模型；GLM-5.3-Flash 兜底）。国内直连无障碍，无需代理。

## 8. 本机（windev-01）承诺交付的软件面（HANDOFF v1 前后落地）

1. bring-up 脚本实现包（`calibrate_handeye.py` / `camera_check.py` / `safety_drill.py` /
   `cs_arm.eval_hw` / `cs_arm.eval_scoop`），mock 模式 dry-run 全绿、契约签名不变；
2. 仿真预扫参推荐初始参数（进 `config/`，压缩真机调参轮次）；
3. ACT 训练资产包（无主臂采集方案 + 3060 12GB runbook）；
4. demo 三件套物料与报名材料技术部分；
5. `chengshao-sprint.workflow.ts`（M4→M6 编排工作流，子代理 minimax、门禁/回退/升级内建）。

## 9. 今天（D3）最小闭环

 bootstrap 1–7 完成 → gate_g1 基线绿 → bring-up 第 1 步（舵机标定+连通冒烟）。
 若第 1 步受阻：先并行做 2–3 的标定脚本 dry-run 与相机枚举核对，**不空转、不跳过安全前置**。
