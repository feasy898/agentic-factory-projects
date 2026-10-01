# 任务（独立第二意见评审·只读）：澄迈大赛项目「可玩广告生产线」Phase 0 审查

背景：本项目由 AI 构建流水线按 spec+eval 逐模块开发，Phase 0 已全绿（scripts/gate_phase0.py 5 项 PASS：骨架 CLI、六渠道出包 spike、LLM 网关 mock 自测、质检雏形、验收门）。你是独立评审，不信任我们的绿灯，专找盲区。当前工作树可能包含 Phase 1 半成品，聚焦已提交的模块、测试与验收门。

请阅读（相对当前目录）：
1. ../plan/开发指令.md（内部规划：契约/模块 spec/eval/通过线；含 Phase 0 实测备忘）
2. scripts/gate_phase0.py 及其调用的全部 eval 入口
3. python/llmgw/（含 selftest）、python/qacore/、python/pfcore/、packages/packager/
4. _vendor/NOTES.md（六渠道 spike 记录）

评审问题（逐条回答）：
A. 假绿灯风险：gate_phase0.py 的 5 项检查里，哪些断言过弱或有自欺空间（如 eval 自己 mock 掉被测物、只查文件存在不查内容、容差过宽）？
B. qacore 质检雏形：外链拦截是否覆盖 WebSocket/fetch/XHR 全通道？静音断言在无音频页面是否形同虚设？
C. llmgw：密钥是否可能泄漏进日志/异常栈？超时重试逻辑有没有指数退避缺失导致的雪崩风险？
D. Windows 原生坑：编码（GBK/UTF-8）、中文路径（cv2/文件 IO）、端口占用残留进程？
E. 公开仓库卫生：代码/注释/配置/package.json 是否残留上游开源项目名？
F. 工程债 Top5（按风险排序，注明是否阻塞 Phase 1-2）。

输出格式：问题清单，每项 = [high/med/low] 文件:行 — 问题一句话 — 修复建议一句话。最后给总体结论（可继续 / 需修后继续）。只读，不要修改任何文件。
