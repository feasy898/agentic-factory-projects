# 为什么这里有这个目录？（2026-09-28 修复工留）

本目录下的 `repo` 是一个 **Windows 目录联接（junction）**，指向真实仓库：

```
政务AI脱敏网关\plan\短剧多国出海\repo  ──junction──▶  短剧多国出海\repo
```

原因：「短剧出海B0构建工作流」草稿被保存在 `政务AI脱敏网关\plan\.zcode` 项目键下，
其脚本用相对路径 `短剧多国出海/repo/scripts/gate_b0.py` 调 B0 验收门，
相对 cwd（= 本 plan 目录）解析后指向不存在的路径，导致第 1 轮验收门
`[Errno 2] No such file or directory`。与「助餐机器人G0-G1构建工作流」的 G1 门
失败（见 `..\具身助餐机器人\README-为什么有这个目录.md`）同类同因。建此联接使命令
解析到真实仓库；门脚本内部 `Path(__file__).resolve()` 会穿透明联接
（实测：解析结果为 `D:\workspace\澄迈8项目\短剧多国出海\repo\scripts\gate_b0.py`），
实际运行的仍是真实仓库的门禁。建联接后按 runner 原命令实测 4/4 PASS、退出码 0。

处置建议：
- 草稿 2026-09-28 已改为绝对路径（`REPO + "/scripts/gate_b0.py"`），
  本联接自此仅兜底旧运行，可安全删除：`rmdir 短剧多国出海\repo`
  （rmdir 只删联接本身，不动真实仓库），随后可删整个 `短剧多国出海` 目录（内含本说明）。
- 更彻底的整改：把该工作流草稿迁到正确项目键 `短剧多国出海\plan\.zcode` 下。
