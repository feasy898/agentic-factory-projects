# M11 溯因智能体 spec（agent + kb · 溯因知识库结构）

> 状态：冻结（79 用例全绿，2026-09-29 实测）。模板后端离线保底是**主链路**（评测不依赖
> 网络/环境变量）；LLM 后端与知识库检索都是可选增强，缺失/失败自动降级、绝不阻塞。
> 本页对照 `beaneye/agent/`（template/llm/knowledge）、`beaneye/kb/__init__.py` 与
> `configs/rootcause.yaml` 逐行核验于 2026-09-29。

---

## 1. 溯因知识库结构（configs/rootcause.yaml，TemplateAgent 唯一数据源）

```yaml
version: 1                          # 必须 >=1 整数
stages: [采摘, 发酵, 干燥, 仓储, 脱壳]   # 环节表（默认即此五环节；非空、无重复）
stage_names:                        # 环节译名（zh 即环节键本身；每环节恰含非空 en/vi）
  采摘: {en: harvest, vi: thu hoach}
  发酵: {en: fermentation, vi: len men}
  干燥: {en: drying, vi: say kho}
  仓储: {en: storage, vi: bao quan}
  脱壳: {en: hulling, vi: xat kho}
evidence:                           # 三语证据句模板（整库共用，每语恰一条非空）
  zh: "检出 {count} 粒{name}（占 {share}），证据指向{stage}环节。"
  en: "Detected {count} {name} bean(s) ({share} of {total}); evidence points to the {stage} stage."
  vi: "Phat hien {count} {name} ({share} trong {total} hat); bang chung chi vao giai doan {stage}."
defects:                            # 必须与 taxonomy 缺陷类恰好一一对应（12 类；normal 禁入）
  black:
    causes:                         # 环节归因先验，非空；likelihood ∈ (0,1] 数值；加载后按降序排
      - {stage: 发酵, likelihood: 0.45}
      - {stage: 采摘, likelihood: 0.30}
      - {stage: 干燥, likelihood: 0.15}
    advice: {zh: [...], en: [...], vi: [...]}   # 三语各 ≥1 条非空
    citations: ["std:cqi_fine_robusta#defect.black", "kb:rootcause.black"]  # 非空字符串列表
  # …共 12 类（broken/faded/brocade/immature/peaberry/shell/elephant/insect/dried/sour/mold/black）
general:                            # 通用建议/引用：好豆批的全部输出；缺陷批追加在后
  advice: {zh: [...], en: [...], vi: [...]}
  citations: [...]
```

**证据句占位符**（整库共用一套）：`{count}` 该缺陷粒数 / `{share}` 占整盘百分比（如 20.0%）/
`{total}` 整盘豆数 / `{name}` 缺陷名（taxonomy 三语名）/ `{stage}` 当前归因环节名（三语）。

**加载期强校验**（失败抛 `RootCauseConfigError`，信息带文件路径）——把「全缺陷类 × 三语
齐全」做成加载期不变式，运行期不再可能缺键：

- `defects` 与 taxonomy 缺陷类（12 类，不含 normal）**恰好一一对应**：缺失、多余、normal
  混入都拒绝；
- 三语（zh/en/vi）advice / evidence 缺语言、缺条目、空白文本都拒绝；
- `stage` 只能取 stages 表内环节；`likelihood ∈ (0,1]`；
- **坏占位符哑值试格式化**：加载期用哑值（count=2/share="20.0%"/total=10/name="x"/stage="y"）
  把每条证据句 × 每个候选环节 × 三语全部试格式化一遍，坏占位符提前暴露（不让它在用户
  面前才炸）。
- 越南语沿用「无变音占位」风格（vi_verified=false 口径，与 taxonomy 一致，D1 核对后回填）。

## 2. TemplateAgent（离线规则保底）

- 输入只读 `BatchResult.grading.defect_counts`（契约不变式：每粒只计最严重缺陷）+ 逐粒
  `final_severity_rank`；缺陷展开顺序 = 严重度降序 → 粒数降序 → key 稳定序。
- causes = 检出缺陷 × 该类全部环节候选（likelihood 降序），证据句按 lang 格式化（带粒数/
  占比实据）；advice/citations = 检出缺陷各自条目 + `general`（**去重保序**：`dict.fromkeys`）。
- **好豆批**（无缺陷）：causes=[]，只有 general 建议与引用——合法输出，不是降级。
- 复杂度只随缺陷**类**数增长（不随豆数）：200 粒盘实测 0.06ms（通过线 ≤100ms）。
- 非法 lang 抛 `AgentError`；知识表缺检出缺陷的条目 → AgentError（配置与契约不一致，
  显式失败优于静默漏报）。

## 3. LLMAgent（OpenAI 兼容 ChatCompletions，可选增强）

- **配置**：env 三件套 `BEANEYE_LLM_BASE_URL`（拼 `/chat/completions`）/`BEANEYE_LLM_KEY`
  （Bearer）/`BEANEYE_LLM_MODEL`——任一缺失即「未配置」，每次直接走 Template
  （`backend="template"`）。构造参数可覆盖 env。
- **请求**：system prompt 内嵌 ①输出 JSON schema 约定（causes 元素形状/defect 只能取检出
  键/stage 只能取五环节/likelihood 0-1/lang 固定）②根因知识参考项（检出缺陷的 stage_priors/
  advice_candidates/citations，按严重度降序）③标准 YAML 摘要（configs/standards 下存在即带）
  ④知识库检索片段（k=4，检索失败静默省略）；user 消息 = 整盘统计 JSON（sample/standard/
  grade/passed/bean_count/defect_counts（非 normal 且 >0）/sieve_pass/sieve_hist/delta_e_mean/
  est_weight_g，数值预舍入）。`temperature=0.2`、默认超时 20s。
- **JSON 模式两级**：先带 `response_format={"type":"json_object"}`；服务端不支持（HTTP≥400
  且响应体含 "response_format" 字样）→ 去参重试一次，走**解析兜底**（剥 markdown 围栏 +
  截取首 `{` 到末 `}` + JSON 解析）。
- **输出净化 `_sanitize`**（不合约定即抛错→由 explain 捕获降级模板）：lang 与请求不一致判
  失败；causes 只保留「本次检出且 taxonomy 合法」的缺陷（幻觉键丢弃）；stage 只取五环节；
  likelihood 截断 [0,1] 且须有限数值；evidence_summary 非空；**检出缺陷却给不出任何有效
  causes → 判失败**（防「成功返回但内容全废」被当增强）；advice 非空。
- **总降级原则**：网络/HTTP/解析/校验**任何失败**自动降级 TemplateAgent 并
  `backend="template"` 标注——LLM 永不影响主链路。`http_client` 可注入（评测 MockTransport /
  生产连接池复用）。降级后输出与 TemplateAgent **全等**（eval 断言）。

## 4. 知识库接口（beaneye/kb，接口留桩）

| 件 | 语义 |
|---|---|
| `KbChunk` | `{chunk_id, text, source, score=0.0, metadata}`；text 原样引用不改写；chunk_id 可直接进 `AgentReport.citations`，形如 `kb:rootcause.black` / `std:cqi_fine_robusta#defect.black` |
| `KnowledgeBase` Protocol | `retrieve(query, k=4) -> list[KbChunk]`（相关度降序）；**必须离线安全：不可用返回空列表而非抛异常** |
| `NullKnowledgeBase` | 默认装配，恒返回空（零依赖零网络）；溯源主链路在任何部署形态可跑通 |

- 切块来源（内部规划）：三套标准 YAML + 缺陷图说明 + 初加工规范文本，按「条款/条目」粒度
  切块。两类未来后端：语义嵌入向量索引（多语召回好，模型缓存 `models/`、索引 `data/kb_index/`）
  与词频检索兜底（无模型依赖）——均为可选增强，未落地（本包不写可重生 spec）。
- LLM 与 KB 都不影响主链路评测：断网时 e2e 仍全绿（通过线之一）。

## 5. eval（2026-09-29 实测）

```bash
python -m pytest tests/test_agent.py -q
# → 79 passed
# 覆盖：Template 12 类×三语逐类齐全+三语互异+严重度排序+好豆批 general 兜底+占比格式化+
#   确定性+AgentReport 嵌入 BatchResult 往返+200 粒盘 0.06ms；知识表加载校验 8 例+
#   kb 接口 3 例；LLM：MockTransport 罐头成功解析+请求契约断言（/chat/completions 路径/
#   Bearer/model/response_format/prompt 内容）+response_format 不支持两请求解析兜底+
#   HTTP500/非 JSON/语言不一致/缺 causes/空 causes（好豆批合法）/连接异常全部正确降级
#   template 且与 TemplateAgent 输出全等+幻觉键清洗+坏 stage/likelihood 截断+env 配置读取
```
