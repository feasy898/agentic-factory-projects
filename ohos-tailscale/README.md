# ohos-tailscale —— 鸿蒙 HarmonyOS Tailscale 客户端

> 接手文档 ｜ 任务卡见 [TASK.md](TASK.md) ｜ 项目原始自述见 [README-upstream.md](README-upstream.md)（原仓 README）
> 仓库公开化说明见 [PUBLIC-SCRUB-NOTE.md](PUBLIC-SCRUB-NOTE.md)（历史中的真实内部地址已替换为文档保留段示例地址）

## 项目是什么

鸿蒙社区版 Tailscale 兼容客户端：目标是让 HarmonyOS NEXT 电脑加入自建 tailnet（控制面为 fork 版 Headscale）。当前形态 = **纯 TypeScript（ArkTS 语法兼容）协议核心库**（npm workspace 8 包，约 8400 行：`common/crypto/noise/wireguard/derp/control/disco/netcheck`）+ HarmonyOS 工程壳（`app/`，**从未编译**）+ 协议取证文档 + 真实 headscale 互操作脚本（`interop/`）。

硬约束（机检在岗）：**D4 核心库零网络**、**P4 无非确定来源**（无 `Date.now`/`Math.random`/`node:` 导入，时钟与随机经 `common` 包注入接口）、ArkTS 禁则 A1–A36 逐条规避（`npm run validate:shell` 54 用例静态机检）。

## 架构一句话

按 Tailscale 协议分层实现为 8 个无依赖单向包（common → crypto → noise → wireguard/derp/disco/control/netcheck），接口冻结、KAT/上游取证锚定，app 壳通过 bridge mock 层与协议库集成。

## 构建与运行

```bash
npm install        # workspace 安装
npm test           # 全仓测试（基线 280 pass / 0 fail）
npm run typecheck  # 类型检查（exit 0）
npm run test:bridge        # 壳↔库 bridge mock 集成（13 用例）
npm run validate:shell     # ArkTS 禁则静态机检（54 用例）
```

互操作联调：`interop/` 内含 register / h2c / derp / start-headscale 脚本（需自建隔离 headscale 实例，禁用任何生产网络）。

## 验收基线（2026-10-01 实测）

| 门 | 命令 | 基线 |
|---|---|---|
| G0-1 全仓测试 | `npm test` | **280 pass / 0 fail** |
| G0-2 类型 | `npm run typecheck` | exit 0 |
| G0-3 bridge | `npm run test:bridge` | 13 pass / 0 fail |
| G0-4 壳机检 | `npm run validate:shell` | 54 passed / 0 failed |
| G0-5 D4/P4 机检 | grep `Date.now\|Math.random`、`node:` 导入、网络调用特征 | 全部 0 命中（注释除外） |

历史里程碑：真实 headscale v0.29.4 全链互通 `INTEROP PASS` + `DERP INTEROP PASS`（09-29 在隔离实例实测达成，属一次性历史证据；复跑需按 TASK.md 子线 D 重建环境）。官方 ArkTS linter src 告警 154 → 0（09-29）。

## 已知问题

1. **`app/` 壳从未编译**：无 DevEco 工具链；编译可行性论证见 `docs/build-feasibility-linux.md`（「做不了」已成文为可裁定证据）。真机线冻结为 WAITING_EVENT（等编译/真机环境，见 TASK.md 子线 E）。
2. **互操作不可复跑**：当前仓库环境无 headscale 二进制，09-29 的 INTEROP PASS 是转引历史证据。
3. **二期未做项**（协议面）：disco UDP relay 家族 0x04–0x09、netcheck 引擎调度、DERP region 随机选节点、netmap→WG peer 推导、完整状态机、LocalAPI/PeerAPI/MagicDNS、数据面 TUN fd 接线（现只有 bridge mock 形态）。
4. 09-29 上游实读曾修正 5 处真实语义错误（DERP 帧头 u32BE、controlbase 版本 148 等）——**凭记忆写协议语义是本项目实证过的错误来源**，续作必须先做上游源码实读。
