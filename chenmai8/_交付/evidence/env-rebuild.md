# 环境重建记录（evidence/env-rebuild.md）

> 批次：chengmai8 批0「六仓环境重建」之 C1 机械臂线（chengmai-feeding-arm）。
> 执行：windev-01 主线 agent，2026-10-01（D3）。原则：如实记录红绿与差异，不静默改契约。
> 本文同时是 3060 Ubuntu 侧 venv 配方的母本（差异项已标注）。

## 1. 机器与时间

| 项 | 值 |
|---|---|
| 机器 | windev-01（Windows Server 2022 + Git Bash，无 GPU） |
| Python | 3.12.10（系统 Python，venv 建在**包根** `chengshao-feeding-arm/` 下） |
| 包管理器 | uv 0.12.15（pip 传统解析器在本依赖集上死回溯，见 §3） |
| pip 镜像 | 阿里云 `https://mirrors.aliyun.com/pypi/simple/` |

## 2. 克隆与 Windows 专属坑（monorepo 形态引入）

1. **仓内含保留设备名文件**：`zcode-research/skillfactory/v5/assets/deploy-pack/package/NUL`。
   Windows 上一次 `git clone` 的 checkout 必然失败（"invalid path"），且此后本机任何
   `git commit/reset/restore` 都会因 index 无法写入该路径而失败。
   **修复**：不用 index——`ls-tree -r -z HEAD` 读全树 → `hash-object -w` 写新 blob →
   `mktree` 自底向上重建受影响子树 → `commit-tree` + `update-ref`。
   已固化为脚本 `C:\devsetup\mkt_commit.py`（stdin 必须字节模式，Windows 文本模式会把
   `\n` 转 `\r\n` 污染树内文件名——首版即因此产出过一棵全 \r 树，已弃用重做）。
   push 不涉及 index，正常。**Linux（3060）无此问题，NUL 是合法文件名。**
2. **monorepo 合并后 git toplevel 变了**：`gate_g1.py` 命名扫描默认根=toplevel，会把
   monorepo 全量（含其他子项目与内部 plan 文档）都扫进来。已改 `gate_g1.py` 命名项为
   显式 `--root <包根>`（语义与单仓时代一致）。**遗留问题（需 owner 裁定，未擅自处理）**：
   handover 合并把本应内部管理的 plan/ 与交付清单并入公开仓，其中含上游原名
   （仓内 194 条 FORBIDDEN，chengmai8 内 81 条：plan--*/ 68、_交付/开源清单 9、_reviews/ 4）。
   纪律原文：「plan/ 与 upstream/ 不进公开仓」。可选处置：脱敏改写 / 移入私有仓 / 扫描器
   显式豁免并人审留痕。**本次未改这些文件。**
3. 中文绝对路径 × cv2/物理引擎坑：代码层已处理（`cs_mouth/imgio.py` 字节流系列、
   cs_sim 模型相对化），重建环境无需额外操作。

## 3. 依赖重建（requirements 派生）

原 `chengshao/requirements.txt`（170 项 pip freeze）直接重装会失败，实测三类问题：

| 问题 | 证据 | 处置 |
|---|---|---|
| opencv 三变体同窗（contrib 5.0.0.93 + base 5.0.0.93 + headless 4.13.0.92） | pip 传统解析器死回溯 25min 零产出；uv 报 unsatisfiable | 只保留 **opencv-contrib-python==5.0.0.93**（含 ArUco 基准码模块，即 REGENERATE 核心钉版行）；base/headless 剔除 |
| tiktoken==0.14.2 | uv: "no version of tiktoken==0.14.2"；PyPI 最高 0.14.0 | 钉 **0.14.0** |
| zipp==4.0.1 | uv: "no version of zipp==4.0.1"；PyPI 无 4.0.1（3.23.1 / 4.1.0 有） | 钉 **3.23.1**（最后 3.x，兼容性最稳） |

- 派生清单：`chengshao/requirements-rebuild.txt`（其余 165 项与原冻结逐字一致）。
- **Ubuntu（3060）差异项（预估，装时按实际调整）**：无 Linux wheel 的 Windows 专属包
  `pywin32==312` / `pypiwin32==223` / `comtypes==1.4.17` **直接删行**；pyttsx3 在
  Ubuntu 走 espeak（装 `espeak-ng`），pynput/ sounddevice 正常。
- 装机口径：`uv pip install -r chengshao/requirements-rebuild.txt --python .venv/bin/python
  --index-url https://mirrors.aliyun.com/pypi/simple/`。

## 4. 模型件与上游参考（cs_sim 环境前提）

- **人脸关键点权重**：`python chengshao/scripts/fetch_models.py` 直连成功
  （3,758,596 B → `chengshao/models/face_landmarker.task`，gitignore 不入库）。
- **ASR 模型**：funasr 首次运行经 modelscope 拉小模型（国内直连可达，冷启 ≈172s，先暖机）。
- **vendor-arm-model（仿真模型件）**：本机 `D:/upstream-refs/robot-vendor/SO-ARM100`
  四个上游参考克隆在位（锁定 commit 与 `upstream_lock.md` 一致）。
  **COS 镜像已建**：`cos://everything-1476163454/chenmai8/c1-arm-vendor/simulation/Simulation/`
  （57 文件 ≈23M， Simulation/ 全量）。3060 拉取：
  `coscmd download -r chenmai8/c1-arm-vendor/simulation/ <本地>/`（COS 凭据：Vault `secret/tencentcloud`），
  然后 `export CS_VENDOR_ROOT=<含 Simulation 的父目录>`。
  自检：`python -m cs_sim.eval --model auto` 在包根跑，tier 必须 `mjcf`、6 关节。
- **四个上游仓 URL + 锁定 commit 台账**：写入 bao `secret/chenmai8/upstream-refs`
  （srv-1，OpenBao）。公开仓命名纪律禁止 URL 入仓，故只存 bao。

## 5. GitHub 推送链路

- PAT：Vault `secret/credentials/github-feasy898`（feasy898，含 `repo` scope，已验证）。
- 本机凭据存储：`C:\devsetup\git-credentials`（0600，git credential.helper store 指定文件）。
- 提交必须走 `mkt_commit.py`（见 §2 第 1 条），推送 `git push origin HEAD:main`。
- 备用 SSH 通道：专用密钥 `~/.ssh/github_push_key` 已生成（公钥待网络恢复后加账号，
  sprint 结束可移除）。
- **网络实况（2026-10-01 傍晚）**：GitHub 智能协议端点从本机直连被 reset；
  gitconfig 内 URL 级 socks5 代理（hk-gateway:7864）随 tailscale 掉线失效；
  windev-01 tailscale 处于 logged-out 态需重登。推送改为带退避的重试，恢复后立即补推。

## 6. tailnet / 3060 接入物资

- 预授权 key（可复用、7 天）：bao `secret/chenmai8/tailnet-preauth-3060`。
- 入网命令模板见 `_交付/HANDOFF-3060-v0.5.md` §7。
- COS/bao/Vault 位置见同文 §7。

## 7. 门禁基线（本机）

- 命令：`python scripts/gate_g1.py`（系统 Python 即可，内部切 .venv）。
- 参考耗时（REGENERATE 实测口径）：pytest ≈7min、cs_sim ≈12.4min、cs_arm eval_mock ≈2.6min、
  cs_voice ≈4min（含模型加载）、cs_orchestra ≈25min、e2e ≈2min；**整门约 40–60min**。
- cs_mouth 延迟阈值负载敏感：p95 ≤70ms 必须**空载串行**跑（并行重负载实测假失败 75.1ms）。
- 演示/验收前勿随手跑全量 pytest/e2e：conftest 会话级钩子会改写 reports/ 三份证据，
  误跑后 `git checkout -- chengshao/reports/` 恢复（坑 5/13）。

## 8. 待办（继承）

- [ ] GitHub 推送恢复后补推 HANDOFF v0.5 与本文（本地已提交待推）。
- [ ] owner 裁定 plan--*/ 公开仓命名问题（§2 第 2 条）。
- [ ] G1 门禁本机全绿复跑并刷新 `chengshao/reports/gate_g1.json`（依赖装完即跑）。
- [ ] 3060 侧 venv 建立后回报 Ubuntu 实际差异，回填本文。
