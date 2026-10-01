# 第三波重生成 spec 缺口清单（回炉输入，2026-09-29）

> 来源：qacore/pfcore/match3rules 三试点实现者自报（全部再生成功，以下为"只凭 spec 重建时被迫自行裁定"的点）。

## qacore.md 补齐项
1. 冻结测试目录只有 fixtures/mini.html：需在 spec 写明"变异样本=gate 脚本现场最小变异"并把 MUT-01/02/04 的变异构造算法成文（MUT-03/结页不可达标注属 M8 后续）。
2. 报告 JSON 全字段在 pipeline-contract.md §4 而非 qacore.md——把字段表并入或显式交叉引用；并修 pipeline-contract 自相矛盾（§3.2/3.3 例证 stem 命名 index.report.json vs §4 示例 "x.report.png"，定死 stem 命名）。
3. CHK08 隐含前提成文：route.abort 后 Chromium 透传 'Failed to load resource: net::ERR_FAILED' 为 console error，须按前缀过滤网络源噪声（否则 MUT-01 必误伤 CHK08，与 §8 矛盾）。
4. 探针监听的 5 个 pf:* 事件名单成文（ready/start/first-interaction/cta/end）。
5. __PF_QC__.texts()/textStates()/assets() 返回形状与 everVisible 归属定义。
6. autoplay 只驱动竖屏趟（明说）。
7. 规则库具体数值（preview maxBytes=5242880、muteBeforeFirstInteraction 默认、runtime_stubs 机制）在 qacore.md 内给出或显式引用 channel-adapters §1。
8. 依赖钉版（playwright 1.63.0/pillow 12.3.0）在 §9 已有，补"试点 requirements 最小集"说明。

## spec-contract.md（pfcore）补齐项
1. bad03 张力登记：§3 标注 I4 但 schema max≤30 先行命中（同路径），spec 写明"两层都收"。
2. LCG 三自由度冻结：初态、先推进后取值、单流跨关卡/各生成器独立建流（现仅 bad02 单样本锁定）。
3. merge 模板 params 语义（I-merge sprites|spawn|goal）与 pullpin/sort/merge 子 schema 规则卡计划（templates.md 标 planned 属实，但 pfcore spec 应写明"未覆盖即结构 stub"）。
4. I2"终局与生成器一致"的具体形态（重放解至已解盘面）成文。
5. CLI stdout 格式冻结（逐文件 JSON 行）。
6. meta.title/flow.tutorial/attract/difficulty/variants/assets.audio 形状契约列出。
7. JS 镜像 ajv-check 属另一命令范围（标注归属，避免试点歧义）。

## match3-rules-card.md 补齐项
1. mulberry32 函数体内联成文（消除"规范公版 vs 变体"分歧风险）。
2. 全卡补带期望输出的数值算例（至少：一个 seed 的首 5 抽、一个恰一合法步盘、一个死局盘、一个两级连消盘的波形）。
3. hint 布局数学成文：格宽/棋盘原点/Layout 参数化+四舍五入=JS Math.round（floor(x+0.5)，与 Python 银行家舍入可区分）。
4. seed 钳制参数序消歧：(default=1, min=0, max=0x7fffffff)。
5. qc.maxLoadSec/autoplayTimeoutSec 缺省值钉死。
6. spriteKeys 缺省键名 piece-0..4 钉死。
7. Fisher-Yates 方向（n-1..1 降序）与索引→格映射（行优先）钉死。
8. 生成期 64 次重试的流消耗方式（同一主流连续消耗）钉死。
9. 死局重排流"第 k 步"定义（重排时 moves-movesLeft+1）。
10. ResolveResult.steps[] 元素 schema（match/fall/spawn + spawn cells 顺序=列优先自上而下）。
11. bestMove 并列取优规则（allMoves 序靠前）。
12. attract.nearWin 归一表补位（缺省 False）。
13. FNV 形状枚举序（圆菱方三角六边）与调色板 7 色色值表。
14. 相位机/CTA/RTL/音频/程序化贴图属模板侧（卡内标注"本卡不含"）。

## 通用教训（写入 REGENERATE §5 SOP）
- 规则卡/数值表类 spec 必须自带"带期望输出的算例"——本次三个试点全部靠"外部公知向量/手推构造盘"补位，这是可避免的脆弱性。
- 试点再生的另一个收获：match3rules 试点冻结 eval 抓出了实现者自己的 2 个真实 bug（果冻跨波重复计数/循环导入）——eval 强度的正面证据。
