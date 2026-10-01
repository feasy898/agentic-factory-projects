# 任务（独立第二意见复审·只读）：政务AI脱敏网关——审查修复后的回归复审

背景：本仓库此前经独立审查判定"需修后继续"（8 项 high/med），修复工作流已完成全部 8 项并通过 gate_d0 与 gate_b1。你是复审员，验证修复是否真的修到位、有没有引入新问题。重点核验：

1. 出站全量检测（gateway/pipeline.py）：_aux_texts 是否真覆盖 tools 定义全部字符串叶/历史 tool_calls.arguments/function_call/非 text 段；辅助面命中 BLOCK_FLAG 是否整单 403；有没有仍被绕过的字符串面（如 response_format/json_schema 字段、metadata、user 字段、logit_bias 键）。
2. 人名规则层 v0（recognizers/rule/detect.py 第 11 步）：词表+前 100 姓启发式的误报面（如「经办主任王强」吞「任王强」方向、停用词豁免是否够）；与 U1 全文 diff 断言（e2e_smoke 期望 span 手工声明+mapper 冻结占位符）——这个"防同源假绿"设计是否真防住了（期望文件是谁写的？会不会仍然同源）。
3. 审计硬闸（audit/store.py + e2e U5）：表面形式+归一化值+500 字截断守护的实际实现；73728 字节全库扫描是否含 WAL/-shm；会话库（存归一化原值）与审计库的隔离是否严密。
4. /internal/* 鉴权、sse.py finish 顺序与多行组帧、端口清理（GBK 解码修复）、export_public.py 导出门（依赖行剔除+_BY_DEPLOYER_ 置换+strict 终检）的实现质量。
5. 新引入风险：aux 深拷贝重建对大 payload 的性能/内存；PERSON 启发式对正常公文（领导人姓名/职务）的误报会不会把公文涂花。
6. 修复工作流自报的遗留清单是否如实（姓启发式边界/U2 固定切点夹具/mock raw_messages 正向 e2e/low 项）——有没有漏报的。

输出：结论（修复验收通过/仍需修）+ 问题清单（[high/med/low] 文件:行 — 问题 — 建议）+ 遗留确认。只读，不修改任何文件。
