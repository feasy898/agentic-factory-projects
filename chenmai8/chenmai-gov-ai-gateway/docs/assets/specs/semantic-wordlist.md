# 语义层 spec（注入检测词表三档结构 + 位置佐证 + judge 升档位）

> 状态：frozen（T4.2 第一档落地）。对照 `recognizers/semantic/{patterns,adapter,judge}.py` 逐行
> 核验于 2026-09-29。铁律 D：MVP 识别只做规则层，语义层走适配器，**严禁拉真模型**；
> guard 模型路径只允许写 config `moderation_model`（公开仓库卫生）。

## 1. 词表三档结构（patterns.py:32-36，冻结）

`config/injection_terms.txt` 行格式 `<class>|<regex>`（# 注释；class ∈ STRONG/EXFIL/WEAK；
非法正则跳过该行记日志不中断加载；文件缺失/为空回退本文件内置默认 `DEFAULT_PATTERNS`，
两者内容保持一致——同密级词表惯例）：

| 档 | 语义 | 判定 | 置信度 | 类别码 |
|---|---|---|---|---|
| `STRONG` 强特征 | 指令覆盖/角色接管/提示词窃取/对用户隐匿（含英文直球两条） | **任意位置命中即判** | 1.0 | `INJECTION_OVERRIDE` |
| `EXFIL` 外发链 | 工具调用诱导 + 明确外发目的地（URL/外部渠道）；隐匿动作；内容走私 | **任意位置命中即判** | 1.0 | `INJECTION_EXFIL` |
| `WEAK` 弱特征 | 新任务接管标记、对话模板标记（`<\|…\|>`、`[INST]` 类）、模式开关、面向模型的嵌入式呼叫 | 须**位置启发佐证**（§2）才判，压误拦 | 0.7 | `INJECTION_EMBEDDED` |

judge 补判命中 → `INJECTION_JUDGE`（置信度 0.9）。

## 2. 反误拦护栏（patterns.py，冻结）

- **否定前缀守卫** `is_negated`：命中点前方近邻（`NEGATION_WINDOW = 8` 字符）出现禁令性
  措辞（禁止/严禁/不得/切勿/请勿/不要/避免/防止/无需/无须/不可/不能/勿/别）→ 命中不计
  ——制度文档的「严禁将内部材料上传至外部网盘」是合规表述不是注入；
- **位置佐证** `corroborated`（WEAK 专用，patterns.py:44-57）三通道：
  1. 深度：命中点位于全文深度比例 ≥ `WEAK_DEPTH_MIN = 0.5` 之后（文档深处的嵌入式指令）；
  2. 收束语之后：命中点前方 40 字符内出现公文收束用语（特此通知/特此报告/此致…——落款后
     埋注是典型文档埋注位）；
  3. 行首标记：命中所在行以 指令/备注/提示/说明/注意/AI/系统/嵌入/附录… 开头（括号可选）；
  4. 括注块：命中点前方同类括号（【】「」『』）未闭合即视为括注内。

## 3. 适配器（adapter.py，接口形状 P0 冻结）

- `moderate(text) -> {"verdict": "safe"|"flagged", "categories": [str]}`——词表命中即
  flagged；词表零命中且 judge 已配置时**补判一次**（词表已命中无需再问）；
- `detect(text) -> list[Finding]`：产出 `type=INJECTION、layer="semantic"、
  action_hint="BLOCK_FLAG"` 的 Finding——路由矩阵 R2 在 `routing.engine.decide` 原生消费，
  本层零改动完成「拦截进 decide」；
- span 去重：同/重叠区间保留首条（start 升序、长者优先）；
- **judge 升档位**（judge.py，env 驱动）：`SEMANTIC_JUDGE_*` 三变量齐备才启用；**无 key
  降级词表**（零网络行为）；judge 仅在词表零命中时补判；**judge 故障按词表结果降级、
  不抛错**（判定链路绝不因 judge 故障崩）；补判命中产出**无 span** 的整段 finding
  （`raw=""`——语义判定无字符级定位，raw 留空即不进表面形式清单/审计预览替换面）；
- `model_path` 形参仅记录不生效（与 NER 适配器同款「显式声明未加载」口径）。

## 4. 验收阈值（evals/thresholds.py:17-27）

| 常量 | 值 | 含义 |
|---|---|---|
| `INJECTION_RECALL_MIN` | 0.90 | 注入样例拦截率下限 |
| `NORMAL_TEXT_FP_MAX` | 0.05 | 正常公文误拦率上限 |
| `SEMANTIC_INJECTION_SAMPLES_MIN` | 30 | 注入样例总数下限 |
| `SEMANTIC_DIRECT_SAMPLES_MIN` / `INDIRECT` / `TOOLDESC` | 10 / 10 / 8 | 直接 / 间接（文档内嵌）/ 藏于工具描述类下限 |
| `SEMANTIC_NORMAL_SAMPLES_MIN` | 40 | 正常公文误报控制样例下限 |
| `SEMANTIC_LATENCY_MS_2000CH` | 50 | 2000 字单遍 10 次均值上限 |

## 5. eval 指针

| eval | 通过线 | 六道门指针 |
|---|---|---|
| `evals.m2_semantic` | 注入拦截 ≥0.90 / 误拦 ≤0.05 / 规模下限 / decide 集成 / judge 降级路径；`M2 SEMANTIC: N/N checks passed`，exit 0 | gate_b4 ④ 首验；gate_b5 整门链回归 |
| `evals.m10_e2e` U7 | 网页正文埋注场景 → 403 + flag=injection（见 gates spec §2） | gate_b4 ⑥ 起固化断言 |
