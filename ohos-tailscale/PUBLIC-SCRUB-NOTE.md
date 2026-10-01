# 公开清洗说明（2026-10-01）

本仓库为公开版清洗副本。全部清洗动作以 git filter-repo 在副本历史上执行（两轮 + 本说明一次修订，提交链完整保留、哈希已重写），**源仓历史未做任何改动**。本文档记录清洗范围与映射关系；按脱敏纪律，映射表只描述原文的性质，不复写原值。

## 1. 历史剥离

- `docs/oracle/raw/`（18 个文件）整体移除：真实 tailscaled 实例（2026-09-28 于内网开发机采集）的只读协议取证原始转储，含真实 tailnet 节点地址表、peer 公钥、HostInfo / Metrics / 状态导出等内部环境快照。协议结论本体保留在 `docs/oracle/protocol-notes.md`（其中敏感字段已按下表脱敏）。

## 2. 文本替换（全历史生效）

| 原文性质 | 替换为 | 出现处 |
|---|---|---|
| HTTP 收件箱（:8090）上传通道的真实令牌字面量（29 字符） | `[UPLOAD-TOKEN-REDACTED]` | HARMONY_AGENT_TASK.md 回传通道示例 |
| 内部出口网关的公网 IP | `203.0.113.10`（TEST-NET-3） | 任务书、交付报告、测试夹具（NAT 仿真地址）、协议笔记 |
| 内网开发机局域网地址 | `198.51.100.20`（TEST-NET-2） | 测试夹具（disco/netcheck 端点） |
| 内部治理面的公网 IP | `198.51.100.30`（TEST-NET-2） | DERP 测试夹具 ipv4 |
| 真实私有 tailnet 的控制面域名 | `headscale.example.internal` | README、架构文档 §7.2、control 客户端注释、协议笔记 |
| 真实 tailnet 在用节点地址（CGNAT 段内 3 个具体地址，含一个 `x.x.x.1~4` 范围写法） | `100.100.0.1 / 0.4 / 0.5` | 协议笔记、交付报告 |

> 注：文档中残留的 `203.0.113.10:8090/upload/[UPLOAD-TOKEN-REDACTED]/…` 为示例命令，不代表可用通道；真实回传通道凭据由任务下发方另行提供，勿在仓库/对话中粘贴令牌明文。

## 3. 经判定保留的项（非敏感）

- 协议标准常量：CGNAT `100.64.0.0/10`、ULA `fd7a:115c:a1e0::/48`、MagicDNS `100.100.100.100`（Tailscale 公开协议知识，非本环境专属）；
- `interop/headscale.yaml`：本机联调配置，仅含私钥**路径**（无密钥值）与本机回环地址；
- `interop/upload_server.py`：上传令牌仅从环境变量 `HMTOKEN` 读取，代码内无默认凭据；
- 测试夹具中的地址已随上表一并示例化（`app/bridge/test/`、`packages/*/test/`）；
- 保留文档中 `nodekey:/discokey:/mkey:` 公钥均已打码为前 8 hex；被剥离的 `prefs.json` 中的 `PrivateNodeKey`/`NetworkLockKey` 为 tailscaled 自身置零的全零占位值（随 raw/ 一并移除）。

## 4. 接手提示

- 仓库文档索引见 `HARMONY_AGENT_TASK.md` §7 与 `README.md`；
- 开发约定、worklog、验收口径见 `worklog.md`、`CONTEXT.md`、`DELIVERY_REPORT.md`；
- 若你（接手 agent）拿到的任务需要回传通道或控制面联调，向任务下发方索取当前有效的地址与凭据。
