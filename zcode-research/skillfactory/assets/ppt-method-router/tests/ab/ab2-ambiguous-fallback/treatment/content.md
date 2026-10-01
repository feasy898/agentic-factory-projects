# ab2-ambiguous-fallback · treatment — 无信号歧义样例（case11）单条路由

> 执行时间：2026-09-29（本目录全部产物为本次运行实时生成/刷新，非缓存复述）
> 执行依据：`package/SKILL.md`（§4 裁定规则 3、§5 使用步骤 1、§6 输出契约）
> 资产根：`skillfactory/assets/ppt-method-router/`（以下相对路径均以此为基准）

---

## 1. 任务与样例

对「歧义型·无信号」样例做单条路由，并与 oracle 参照判定对照。重点检验：
无任何关键词命中时是否**稳定落到兜底裁定**，且 `reasons` **如实说明无信号与兜底依据**。

**样例输入**（`oracle/inputs/case11.txt`，UTF-8，单行，全文）：

```
内容大概是产品介绍和团队情况，你看着办
```

**oracle 参照判定**（`oracle/out/labels.json` case11 条目，oracle/out/labels.json:91-98）：

```json
{"case": "case11", "method": "editable_pptx", "confidence": 0.4,
 "reasons": ["未命中任何类别关键词（无信号），按兜底规则默认裁定 editable_pptx(数据驱动可编辑汇报)，置信度低"]}
```

## 2. 执行的命令与原始输出

命令（SKILL.md §5 步骤 1，cwd=资产根）：

```
python package/scripts/route.py --input oracle/inputs/case11.txt
```

**stdout（恰一行 JSON，原始字节存档于 `stdout.raw`，404 字节；行尾 `\r\n` 为 Windows 管道 os.linesep）：**

```json
{"method": "editable_pptx", "confidence": 0.4, "reasons": ["未命中任何类别关键词（无信号）：意图文本中未出现 template_fill / editable_pptx / visual_report 三组信号词中的任何一个", "按无信号兜底默认裁定为 editable_pptx（数据驱动可编辑汇报），置信度固定低值 0.4，不代表有正向证据；建议先向用户澄清用途再进入执行"]}
```

- 退出码：**0**；stderr：**0 字节**（4 次运行均如此）。
- stdout 行数=1、恰 1 个行终止符、`json.loads` 可解析，且正文与
  `json.dumps(payload, ensure_ascii=False)` **逐字节一致**（无任何隐藏额外输出，符合 SKILL.md §6 契约）。

**稳定性**：同命令连续运行 4 次（原始字节存档于 `runs/run{1..4}.stdout.txt`），
4 次 stdout 的 sha256 **全部一致**：
`3a006ba77732a9063b7e588a1445ed39fab58c8751ca6326450e168156f13744`
（符合 SKILL.md §4「同一输入重复运行输出逐字节一致」）——无信号输入稳定落到兜底裁定，无抖动。

## 3. 与 oracle 对照结论

| 维度 | package 单条路由 | oracle case11 | 一致 |
|---|---|---|---|
| method | `editable_pptx`（兜底裁定） | `editable_pptx` | ✅ |
| confidence | `0.4`（R5 固定兜底值） | `0.4` | ✅ |
| reasons 语义 | 「未命中任何类别关键词（无信号）」+「按无信号兜底默认裁定 editable_pptx…不代表有正向证据」 | 「未命中任何类别关键词（无信号），按兜底规则默认裁定 editable_pptx…置信度低」 | ✅ 同义如实（措辞差异为两实现文案风格） |

package 自身批量产物 `package/out/labels.json` 的 case11 亦为 `editable_pptx / 0.4`，与单条路由一致。

## 4. rubric 逐项判定（24/24 通过，逐条证据见 `verify_result.json` 与 `verify-output.txt`）

| rubric 项 | 结论 | 证据 |
|---|---|---|
| method 与参照判定一致（editable_pptx 兜底） | ✅ | 上述 stdout；走 `route.py:61-72` 的 R5 无信号兜底分支（`FALLBACK_METHOD`/`FALLBACK_CONFIDENCE` 常量在 route.py:37-38）；`oracle/out/labels.json` case11 method 相同 |
| reasons 非空，明确说明「未命中任何类别关键词/无信号」与兜底默认，未编造命中词 | ✅ | reasons 共 2 条（均非空字符串）：第 1 条含「未命中任何类别关键词（无信号）」，第 2 条含「按无信号兜底默认裁定为 editable_pptx…置信度固定低值 0.4，不代表有正向证据」；reasons 中不存在任何「命中[类别(标签)]关键词：…」行（该格式仅在有命中时由 route.py:75 产出；R5 分支注释「不编造命中词，如实说明并给低置信」，route.py:61） |
| confidence ∈ [0,1] 且 ≤0.6，明显低于有明确信号命中的情形 | ✅ | confidence=0.4（数值型、∈[0,1]、≤0.6）；对照 R3 单类命中公式下限 0.80（0.80+0.05×(1−1)，route.py:81），0.4 明显更低；0.4 恰为 R5 兜底常量 `FALLBACK_CONFIDENCE = 0.40`（route.py:38） |
| 未把「产品介绍」「团队情况」等普通词误报为任何类别关键词的命中 | ✅ | 独立复算：case11 全文 `lower()` 后对 16 个信号词（词表已与实现 `RULES` route.py:28-35 交叉核对完全一致）做子串匹配，**命中=[]**；「产品介绍/团队情况/产品/团队/介绍/情况/看着办/内容」均不在词表内（route.py:30-34），reasons 中亦无任何把它们报为命中的行 |
| stdout 恰为一行可解析 JSON，退出码 0 | ✅ | 见 §2：行数=1、`json.loads` 成功、returncode=0（4 次均 0）、stderr=0 字节 |

## 5. 结论

对无信号歧义样例 case11（「内容大概是产品介绍和团队情况，你看着办」），package 实现按
SKILL.md §4 裁定规则 3 **稳定**落到兜底裁定 `editable_pptx` / `0.4`（4 次复跑逐字节一致），
与 `oracle/out/labels.json` 的 case11 参照判定 method/confidence 完全一致；reasons 如实写明
「未命中任何类别关键词（无信号）」与「兜底默认裁定 editable_pptx…不代表有正向证据，建议先向
用户澄清用途再进入执行」（与 SKILL.md §2 澄清策略相符），未编造命中词、未把普通词误报为命中。
**全部 24 项检查通过（`verify_result.json` `all_passed=true`），本 treatment 臂验证通过。**

## 6. 目录结构说明（本目录产物）

```
treatment/
├── content.md                 本文件（完整文本内容 + 结构说明，评审入口）
├── stdout.raw                 第 1 次路由运行的 stdout 原始字节（404 B，单行 JSON + \r\n）
├── stderr.txt                 第 1 次路由运行的 stderr 原始字节（0 B）
├── runs/
│   ├── run{1..4}.stdout.txt   4 次重跑的 stdout 原始字节（各 404 B，sha256 全部一致）
│   └── run{1..4}.stderr.txt   4 次重跑的 stderr 原始字节（均 0 B）
├── verify.py                  本轮校验脚本（subprocess 重跑 4 次 + 24 项断言）
├── verify-output.txt          verify.py 的人读输出（逐项 PASS/FAIL 明细）
├── verify-stdout-final.txt    verify.py 最终一次运行的完整 stdout
├── verify-stderr.txt          verify.py 最终一次运行的 stderr（0 B）
└── verify_result.json         机器可读校验结果（24 checks，all_passed=true）
```

说明：本任务是**路由决策层**的单条路由验证，不产生 docx/pptx/xlsx 二进制产物
（SKILL.md §7 非目标：不生成/渲染任何 PPT、海报或信息图）；产物均为 JSON 判定与文本/字节存档，无遗漏。
