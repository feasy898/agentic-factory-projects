# zctl — ZCode 闲时任务 / 额度重置 协议级 CLI

单文件 Node 脚本（Node ≥18，零依赖），把 ZCode GUI 的「闲时任务派单」与「额度重置（5 小时 / 周）」功能封装成命令行调用。
完整逆向依据见 `../zcode-闲时任务与额度重置-研究报告.md`。

## 快速用例

```bash
# 查询可重置额度（只读；返回可用的 5 小时/周 重置券数量与过期时间）
zctl.cmd reset status

# 重置 5 小时额度（先 dry-run 看请求，确认后加 --yes 真发；失败重试沿用同一 --key）
zctl.cmd reset use --type FIVE_HOUR            # dry-run 预览
zctl.cmd reset use --type FIVE_HOUR --yes      # 真正执行

# 重置周额度（即「充值 7 天限制」的周额度重置）
zctl.cmd reset use --type WEEK --yes

# 领取重置券
zctl.cmd reset opportunity --yes

# 闲时任务（协议级）：
zctl.cmd offpeak availability                          # 查询取号资格（只读）
zctl.cmd offpeak take --task-id auto --yes --record    # 取号（注意：无 GUI 调度会作废，见报告 §3.1）
zctl.cmd offpeak status --ids <ticket_id>              # 轮询票状态（只读）
zctl.cmd offpeak settle --ticket <ticket_id> --yes     # 结算
```

## 安全机制

- 变更类命令（`reset use/opportunity/history-read`、`offpeak take/settle`）**默认 dry-run**，必须 `--yes` 才发送。
- `--record` 把完整请求+响应写入 `logs\`（token 自动脱敏；`--record-raw` 才存原文，文件敏感勿外传）。
- 凭据自动从 `~/.zcode/v2/credentials.json` 解密（与 GUI/官方 CLI 同一套 AES-256-GCM 方案），token 不落任何默认输出。
- 团队套餐加 `--team --org <id> --project <id>`。

## 当前状态（2026-09-28）

- ✅ 离线验证：凭据解密、请求构造（与开源源码逐字段比对）、dry-run 输出、参数守卫。
- ⏳ 待真机验证（按约定等你指令）：对 `zcode.z.ai` 的真实请求/响应（包括只读的 status/availability 也尚未真发过）。
- 完整闲时任务派单（排队→就绪→自动执行→结算）依赖 GUI host 进程；zctl 的 offpeak 命令是裸协议操作。日常派单直接在 GUI/本会话里用 OffPeakCreate 更稳。
