---
description: 会议纪要整理——转写文件进，三段式纪要（决议/待办/风险）+ summary.json 出
argument-hint: <转写文件路径> [输出目录，默认 ./minutes-out]
---

按 OFFICE-KIT 流程 A 整理会议纪要。

输入转写文件：$ARGUMENTS

执行步骤（严格按序）：

1. 先读 kit 根的 `skills.manifest`，确认 meeting-minutes 的路径与用法；再通读技能包内 `SKILL.md`（权威规则置顶条款：新对话第一个工具调用必须重新读 SKILL.md）。
2. 校验转写文件存在；不存在则停止并向用户要正确路径，禁止编造输入。
3. 运行：`python <meeting-minutes包目录>/scripts/minutes.py --input <转写文件> --outdir <输出目录>`（输出目录缺省 `./minutes-out/<转写文件名去扩展名>`）。
4. 写后回读三态：退出码 0 且 `<输出目录>/纪要.docx` 与 `<输出目录>/summary.json` 都真实存在才算完成；缺任一，排查重跑，不得宣称完成。
5. 向用户汇报：产物两个路径 + summary 四键数值（决议事项/待办事项/风险与关注/合计）。

红线提醒：条目逐字引用原句；负责人/期限抓不到填「待定」；零条保留节标题。
