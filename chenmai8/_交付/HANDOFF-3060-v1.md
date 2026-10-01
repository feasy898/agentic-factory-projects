# HANDOFF v1 — 3060 Ubuntu 桌面：澄勺硬件攻坚（M4→M6）完整交接

> 写给：3060 Ubuntu desktop 上的 agent（ZCode CLI + workflow + 子代理，minimax 模型）。
> 发自：windev-01 主线 agent。日期：2026-10-01（D3 晚）。
> 前置：先读 `HANDOFF-3060-v0.5.md`（bootstrap/bring-up 清单/红线/资源）。本文是它的续篇与总成。
> 倒计时：D9 必须能演示（约 10-06/07），D10=2026-10-08 报名材料截止。试用由 owner 本人执行，不需要外部试用联系人。

---

## 1. windev-01 侧已交付（软件面，全部在 GitHub main，`git pull` 即得）

| 交付物 | 位置 | 状态 |
|---|---|---|
| 3060 启动单 v0.5（bootstrap/红线/资源） | `_交付/HANDOFF-3060-v0.5.md` | ✅ 已推送 |
| 环境重建证据（NUL 提交管线/钉版修正/COS 模型件/bao 台账） | `_交付/evidence/env-rebuild.md` | ✅ 已推送 |
| 环境重建依赖清单（Ubuntu 直接可用，Windows 专属包差异已注明） | `chengmai-feeding-arm/chengshao/requirements-rebuild.txt` | ✅ 已推送 |
| 门禁命名扫描锚定修复（monorepo 后 git toplevel 变了） | `chengmai-feeding-arm/scripts/gate_g1.py` | ✅ 已推送 |
| SO-101 仿真模型件 COS 镜像（57 文件） | `cos://everything-1476163454/chengmai8/c1-arm-vendor/simulation/` | ✅ 已上传 |
| 四个上游仓 URL+commit 台账 | bao `secret/chengmai8/upstream-refs` | ✅ |
| tailnet 预授权 key（7 天可复用） | bao `secret/chengmai8/tailnet-preauth-3060` | ✅ |
| B1 bring-up 脚本包（calibrate_handeye/camera_check/safety_drill/eval_hw/eval_scoop，mock dry-run 全绿） | `chengmai-feeding-arm/scripts/` 等 | 见 git log `sw-b1-bringup-v1.0` |
| B2 仿真预扫参（config/scoop_params.json + 证据 + 测试） | `chengmai-feeding-arm/config/` | 见 git log `sw-b2-simsweep-v1.0` |
| B3 ACT 训练资产包（无主臂采集 + 3060 runbook） | `chengmai-feeding-arm/chengshao/training/` | 见 git log `sw-b3-trainassets-v1.0` |
| B4 演示物料（demo 三件套脚本/报名技术草稿/BOM 安全说明） | `_交付/demo-三件套脚本.md` 等 | 见 git log `sw-b4-materials-v1.0` |
| **硬件攻坚工作流脚本（M4→M6 编排）** | **`_交付/chengshao-sprint-3060.workflow.ts`** | ✅ 本文 §2 的载体 |

> B1–B4 的具体结论、门禁数字与独立复核发现，以 main 上最新 commit 与该次运行的交付报告为准；每包都有 `reports/` JSON 证据与 tag，复核从证据开始，不信自报。

## 2. 硬件攻坚工作流怎么跑（M4→M6 的总编排）

1. 把 `_交付/chengshao-sprint-3060.workflow.ts` 拷到 3060 本地（不要改仓库内这份），改开头 CONFIG 三行：
   `REPO`（克隆根）、`FA`（包根）、`HWUSER`。
2. 模型通道：ZCode CLI 的 provider 用 minimax（`minimax/MiniMax-M3.1-Flash-Preview` 作 workflow 子代理模型），
   GLM-5.3-Flash 兜底（见 §5）。
3. 启动（headless 或交互均可）：
   `zcode --prompt "运行 chengshao-sprint-3060 工作流：路径 /path/chengshao-sprint-3060.workflow.ts（已改 CONFIG）" --mode yolo`
   主会话按 workflow 编排：环境自检 → 安全前置 → M4 八步 → 独立验收 → M5 三食物并行调参 →
   M6 集成/安全/试跑 → 演示筹备 → 汇总推送。
4. 工作流内建：每任务只跑自己相关的测试（不跑全量/e2e/gate，证据刷新有专门步骤）；独立验收员只读重算；
   连续不过按 §9 回退；仍不过记录 blockers 停下等 owner——**不空转、不造假**。
5. 安全前置没过多以前，工作流不会让臂动（safetyPreflight 步骤先于一切运动）。

## 3. 日计划（D4=10-02 起；按实际到货日顺延，演示日不可顺延）

| 日 | 主线 | 门禁/产出 |
|---|---|---|
| D4（或启动日） | 环境自检 + 安全前置 + M4 八步（标定/手眼/相机/口部/safety_drill/舀取首轮） | preflight JSON + bring-up 各证据；`hw-m4-bringup-v1.0` |
| D5 | M5 三食物调参（每食物 50 次） | scoop_eval.json 全食物达标；`hw-m5-scoop-*-v1.0` |
| D6 | M6 集成：行为树接线 + mock 对照 30/30 + e2e 30 口 + safety_drill 真机 20/20 | `hw-m6-integration-v1.0` |
| D7 | 真机全链 30 口试跑 + 看板核对 + owner 首次自试 | 全链证据；问题清单 |
| D8 | 修复轮 + 演示彩排（三段）+ 兜底三件套回放确认 | `hw-demo-rehearsal-v1.0` |
| D9 | 正式演示（owner 主场） | — |
| D10 | 报名材料截止：技术部分已由 windev-01 备好草稿（`_交付/报名-技术部分草稿.md`），owner 签章 | — |

## 4. 模块所有权与合并协议（防双头打架）

- **3060 拥有硬件接触面**：`cs_arm` 真机路径、`config/` 真机参数（scoop_params.json 真机段）、
  `chengshao/reports/` 硬件证据、`hw-*` tag、hardware.md 的实测补充。
- **windev-01 拥有软件面**：`cs_sim`、`cs_food`、`training/`、`cs_dashboard`、`docs/`、`_交付/` 软件物料、
  `sw-*` tag。硬件攻坚期间如发现软件侧 bug：记入 blockers，windev-01 修，不就地改。
- **分支**：3060 推 `hw/m4`、`hw/m5`、`hw/m6` 等分支（或按 tag 粒度直推 main 的 `hw-*` 提交也可以，
  但不要动 `sw-*` 提交）；windev-01 每日一个合并窗口：pull + 复跑 `gate_g1.py` + 处理冲突
  （冲突以冻结契约为准，不裁决放水）。
- **冻结契约**：cs_schema v1.1 / ArmInterface / SafetyEnvelope 签名与语义、config schema、
  通过线阈值——任何修改都是契约变更，必须双方 + owner 留痕，不允许单方面改。

## 5. 模型通道与凭据（零落盘）

- **ZCode CLI 安装**：`npm i -g zcode-app-cli`（本机同款 3.14.3-28；Ubuntu 需 node ≥18）。
- **provider 配置**：写 `~/.zcode/cli/config.json`（0600 权限），模板：
  ```json
  {
    "provider": {
      "minimax": { "kind": "openai", "baseURL": "https://api.minimaxi.com/v1",
                   "apiKey": "<owner 提供的 key，只写这里，勿入任何仓库文件/日志/对话>",
                   "apiKeyRequired": true },
      "builtin:bigmodel-coding-plan": { "kind": "anthropic",
                   "baseURL": "https://open.bigmodel.cn/api/anthropic",
                   "apiKey": "<GLM 兜底 key，同上只写本文件>", "apiKeyRequired": true }
    },
    "model": { "main": "minimax/MiniMax-M3.1-Flash-Preview" }
  }
  ```
  workflow 子代理模型：`minimax/MiniMax-M3.1-Flash-Preview`（可用时）／`GLM-5.3-Flash`（兜底，
  本机实战：minimax 在重负载长回合下两次 turn 失败，GLM-5.3-Flash 稳定——**建议 3060 直接
  以 GLM-5.3-Flash 为主、minimax 为备用**，或两个都配、失败即切）。
- headless 跑法：`zcode --prompt "..." --mode yolo --output-format json`（详见知识库 AGENTS.md 第七节）。
- GitHub PAT：owner 直接交付，`~/.git-credentials` 0600。
- tailnet：bao `secret/chenmai8/tailnet-preauth-3060`（可复用 7 天；用后让 owner 作废重建）。
- 上游仓 URL：bao `secret/chenmai8/upstream-refs`（严禁写入公开仓任何文件——命名门禁会拦）。
- COS 凭据：Vault `secret/tencentcloud`（100.64.0.2:8200，需 tailnet）。
- **3060 机器上严禁装 mihomo 类 TUN 代理**（会弄死 tailscale 数据面，见知识库 02 篇实测）。

## 6. 升级规则（什么时候必须停下找 owner）

1. 安全数字不过：safety_drill 非 20/20、禁入区侵入非 0、急停 >100ms、送达误差 >1.5cm——**停线**，不带着问题演示。
2. 同一 eval 连续 2 轮不过（已按 §9 回退表走过一遍）。
3. 需要新的物理资源（第三路相机、蘑菇头急停、备件舵机顺丰次日达）。
4. 阈值/契约要改（阈值判定后不可改，改=契约变更+人审）。
5. 报名三问未确认（现场演示形式/公司主体/辅器具归类）影响演示与材料。

## 7. 每日节奏与 digest

- 每任务：`reports/` JSON 证据 + `hw-*` tag + 中性 commit message。
- 每日一次：更新 `_交付/调度台.md` 与 `chengmai8/worklog.md`（状态/证据索引/阻塞），
  digest 一段（今日门禁数字/明日计划/需 owner 决策项）由 windev-01 汇总转 owner。
- 所有结论分三态：**实测**（附证据路径）/ **预扫**（仿真口径）/ **未验证**——报告里必须可区分。

## 8. Linux 与 Windows 的差异备忘（env-rebuild.md 的 Ubuntu 摘录）

- git 正常（NUL 合法文件名）；venv 在包根 `.venv`（bin/ 非 Scripts/）。
- Windows 专属包（pywin32/pypiwin32/comtypes）删行；pyttsx3 需 espeak-ng。
- 串口/相机权限：`usermod -aG dialout,video` + 重新登录。
- `CS_VENDOR_ROOT` 指向上游参考件根（COS 拉取的 simulation/ 的父目录）。
- 其余钉版与 `requirements-rebuild.txt` 一致；遇到源上不存在的钉版：取最高可用版并在
  `_交付/evidence/env-rebuild.md` 记差异。
