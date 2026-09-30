# CONTEXT — ohos-tailscale（鸿蒙 HarmonyOS Tailscale 客户端）

> 建卡：编排批-线3 2026-10-01（docs/project-orchestration.md §1.1）；素材=continue-cards/ohos-tailscale.md（迁移验证 2026-10-01 实跑）+ DELIVERY_REPORT.md + docs/（架构契约/ArkTS 约束/协议取证）。

## 背景
- 鸿蒙端 Tailscale 客户端：packages/ 六个纯 TS 协议包（common/crypto/noise/wireguard 等，40 src 文件/5503 行 + 28 测试文件）+ app/ HarmonyOS 工程壳（手写骨架，**从未编译**）+ docs/。
- 交付基线 2026-09-28 DELIVERY_REPORT；09-29 收尾清零评审遗留三项 ArkTS 合规问题（R4 tuple/A14 下标/A2 对象字面量）。
- **未纳入 git 管理**（.gitignore 已为 git 化预留），无 CI，随迁为纯目录。

## 目标
1. git 化 + 建远端（.gitignore 已预留，即开即用）。
2. 二期协议范围：netcheck / disco / LocalAPI / MagicDNS / PeerAPI（DELIVERY_REPORT §3.2）。

## 验收标准
- `npm install && npm test` → **238 pass / 0 fail**（GPU 2026-10-01 实跑，Node v22.23.2；交付基线 217→收尾增补后 238=当前全量）。
- `npm run typecheck`（tsc --noEmit；GPU 未复跑，本机基线 0 错误）。
- 未验证项如实保留：真实服务端互操作（AU1-AU3，无凭据）、app/ 编译与真机。

## 干系人
- owner（DevEco 环境机器裁定、上游核对凭据面）；Tailscale 上游协议（docs/architecture.md §10.2 AU/CU 清单）。

## 当前里程碑
- 协议包测试全绿=一期收口；AU1–AU4 上游核对 + CU1–CU10 ArkTS 未验证项待清（docs 两文件）。
- Temporal 裁定：⏸ 暂不挂（迭代型，project-orchestration §1.2）。

## 风险
- 鸿蒙编译链（DevEco Studio + HarmonyOS SDK）**不在 GPU 机**——app/ 编译/真机在哪台机器做需 owner 裁定。
- 未 git 化：目录即唯一副本（GPU+windev 各一），git 化前勿做破坏性清理。
