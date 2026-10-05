# 模型适配器（逻辑模块 = M6 llmgw + M7 director + M11 repair-loop）

> 重组说明：原规划 M6/M7/M11 三模块合并为一个逻辑模块「模型适配器」。`llmgw` 保持单库（frozen）；
> director 与 repair-loop **明确暂缓**——按资产纪律**不写可重生 spec**，本页只给边界说明。
> 可重生部分：[llmgw spec](llmgw.md)。

---

## 1. 现状一句话

适配器在（llmgw 全功能 + 离线 mock 自测全绿），生成器不在（两个调用方均为空壳或无代码）——
**当前没有任何生产调用方**。技术口径：这是"模型接口可替换"的证明，不构成"AI 产出了广告"。

## 2. llmgw（frozen，单库）

- 位置：`python/llmgw/`；spec：[llmgw.md](llmgw.md)；eval：`python -m llmgw.selftest`（6 项 mock 全过）。
- 正在收紧中（另一代理修改），以 eval 为最终真源。
- 红线：零厂商/端点/模型名硬编码（gate_phase0 门项 4 词表扫描）。

## 3. director（M7）—— 边界说明（暂缓）

- **职责**：路径 B 的生成器——输入截图 / ≤30s 录屏抽帧（≤8 帧）→ 视觉模型（经 llmgw）输出 PlayableSpec
  草稿（模板四选一 + params 偏差 + 素材建议）→ 过 M1 校验 → 不合格自动补一轮；界面与材料必须标注 DEMO，
  不承诺成功率。
- **为何暂缓**：不在演示主路径（路径 A 已定为 100% 稳）；零生产调用方；演示金标输入目录
  `specs-eval/inputs/` 不存在，规划中的 3/5 验收**当前无法执行**；演示日口径是"模型接口已留、今天不演示生成"。
- **触发条件（满足才开工）**：① 主路径（编排器一条命令 + 扫码）彩排稳定；② llmgw 已有真实 key 与至少一个
  真实调用链路；③ 先建 `specs-eval/inputs/`（≥5 个金标输入）与验收脚本。开工时第一件事 = 把边界说明升级为
  完整 spec（含提示词、抽帧策略、schema 提示、失败重试轮次）。

## 4. repair-loop（M11）—— 边界说明（暂缓）

- **职责**：质检 FAIL 的有界自动修复——qacore 失败报告 + 截图 + 相关 spec 片段喂模型 → 输出**参数级**修正
  （只许改 spec 的 `params/difficulty/assets`，不许改代码）→ 重建重检，≤2 轮；不收敛输出人工修复建议。
- **为何暂缓**：依赖两个尚不存在的前置——qacore 的变异测试（防假绿灯）与编排器的重建链路；且规划中的
  `--inject-fault` eval 钩子未实现，验收无法执行。
- **触发条件**：① M8 变异测试落地（qacore spec §8 的 4 个 mutant 先行）；② 编排器能一条命令重建；
  ③ 注入故障 eval（如把 match3 moves 降到 3 使自动试玩超时）可复现。开工时同样先升级本节为完整 spec
  （含允许修改的 JSON 指针白名单与轮次预算）。

## 5. eval 现状

| 组件 | eval | 通过线 |
|---|---|---|
| llmgw | `python -m llmgw.selftest` | 6 项 PASS，exit 0 |
| llmgw 红线 | gate_phase0 门项 4 扫描 | 零厂商端点命中 |
| director | 无（验收前提 `specs-eval/inputs/` 不存在，如实记录） | — |
| repair-loop | 无（依赖 M8 变异 + 编排器） | — |
