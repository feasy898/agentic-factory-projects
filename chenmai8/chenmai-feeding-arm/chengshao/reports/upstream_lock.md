# 上游参考件锁定记录（中性描述）

> 日期：2026-09-28（D1）。用途：记录 `_vendor/` 下四个本地参考克隆的锁定版本，
> 供复现与版本对齐。克隆与版本细节的完整台账（含原始来源地址与许可证复核）
> 保存在项目内部文档中，不入本公开仓库。
>
> 命名纪律：本文件与全仓库只使用中性内部名；上游原始项目名仅存在于
> 内部文档与 `_vendor/`（gitignore，不入库）。

## 克隆清单（`_vendor/`，本地，gitignore）

| 内部代号 | 用途（中性描述） | 锁定 commit | 许可证（以本地 LICENSE 原文复核） |
|---|---|---|---|
| `vendor-robot-stack` | 机器人学习运行栈：数据录制格式、遥操作入口、训练入口（本项目经 pip 直接依赖，见 `requirements.txt` 中同名包） | `e595b7902714ba51f91e47523f66f89c5181b649` | Apache-2.0 |
| `vendor-arm-model` | 桌面主从臂结构件、装配指南与仿真模型目录（STL/STEP/Simulation），cs_sim 模型回退链第一优先来源 | `5f6d2b876a53a4872e405b991dd925556c9e38a4` | Apache-2.0 |
| `vendor-safety-ref` | 助餐场景安全设计只读参考（急停看门狗在线确认、失败状态机），不安装不构建不复制代码 | `0e91e8d33836ef675217ced4690e1e913dbbedda` | BSD-3-Clause |
| `vendor-policy-ref` | 模仿学习策略原论文对照实现的只读参考，实际训练走运行栈内置策略，不直接使用 | `742c753c0d4a5d87076c8f69e5628c79a8cc5488` | MIT |

## 备注

- 克隆方式：`git clone --depth 1`（经境外出口中转），克隆后以 `git rev-parse HEAD` 锁定；
  本地表中 commit 已与 `_vendor/` 本地副本逐一核对一致。
- `vendor-arm-model` 克隆内确认存在 `Simulation/` 目录（cs_sim 模型回退链第一级可用）。
- 复核方式：四个本地副本 LICENSE 文件头均读取原文核对（2026-09-28）。
