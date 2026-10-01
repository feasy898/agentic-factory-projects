# 学情诊断 Agent 与配套软件：SOTA 调研与开发蓝图

> 撰写日期：2026-09-28。本报告汇总十份主题调研材料（认知诊断/知识追踪、自适应测验、自动出题、K-12 知识图谱、开放数据集、课标映射、智能导师、Agent 工程、学习科学、商业对标）及一轮政策合规补充调研，对 12 项关键主张做了事实抽查（全部 confirmed，个别附注如实标注，见 §7.5）。**只使用材料中出现的信息与 URL**，材料未覆盖处明确标注"材料未覆盖"。各主题检索均遭遇过程性 429 限流，结论以实际返回与抓取页面为准。

---

## 1. 执行摘要（SOTA 全景与最重要的 10 条结论）

1. **学情建模呈"双轨 SOTA"，主流范式已收敛为混合框架。** 心理测量学 CDM（DINA/G-DINA/IRT：小样本可辨识、可解释）与深度学习 KT（DKT→AKT→simpleKT：大数据高精度）并行；2025 年后热点是"LLM 提供语义知识 + CDM/KT 出掌握度概率"。arXiv 2512.23036 实证 DKT（AUC 0.83）全面优于零样本与微调 LLM（预印本，口径与验证安排见 §7.2）。
2. **确定性内核可全部用开源拼装。** 诊断引擎 EduCDM（pip，Apache-2.0）+ 序列追踪 pyKT（NeurIPS 2022，30+ 模型，MIT）+ CAT 内核 catsim（BSD-3）+ 会话式 CD-CAT 引擎 cdCAT（CRAN 2026-06，MIT，v0.1.0）+ 间隔重复 FSRS（ts-fsrs/py-fsrs，Anki 23.10+ 内置）。
3. **中文冷启动数据唯一优选 XES3G5M**：500 万+交互、1.8 万学生、7652 道中文数学题，带题面/解析/知识点路径/中文 RoBERTa 嵌入，pyKT 兼容（MIT；论文为 NeurIPS 2023 D&B，GitHub 页未标注）。知识体系可从 Junyi 前置图与 kc 路径抽取；十余国际基准用 EduData 一条命令拉取。
4. **题库冷启动有现成 schema 与题源**：TAL-SCQ5K 字段（解析/知识点路由/难度 0-4，MIT）可当题库标准；GAOKAO-Bench（2811 真题含解析）、CMATH（1.7k 小学应用题带难度）、AGIEval/C-Eval 补初高中；EEDI misconception 标注（1857 题/2587 误解）是"错误→误解"层参考。C-Eval 与 K12-KGraph 数据为 CC BY-NC-SA（非商业）。
5. **组卷内核：诊断导向编排无成品，但开源积木齐备——选型是"复用+适配"而非从零自研。** "知识点配额+诊断信息量+曝光"联合约束无现成成品（GitHub 最大 mikemelon/java-exam 831★ 仅随机/遗传算法）；MIP-ATA 有 TestDesign（GPL）、动态选题有 catsim/cdCAT/EduCAT（BSD/MIT）——真实约束是 GPL 与适配工程，自研限定在约束装配层与接口。
6. **知识图谱骨架可直接复用 K12-KGraph**：人教版小初高数理化生教材抽取的课程对齐 KG（9 节点/14 关系）+ K12-Bench 23,640 题（数据 CC BY-NC-SA 4.0，商用需授权）。核心发现：强 LLM 存在"课标结构感知缺口"、先序图须显式外置。跨国映射无现成数据集，走"CASE/CCSS+LLM 映射+专家抽检"（纯检索 F1 仅 0.55）。
7. **教学策略选择有可执行的证据规则表。** 提取练习 d=0.49（高于 hinge d=0.40）做默认基座；间隔重复用 FSRS；expertise reversal（2025 新元分析）按先验调支架；游戏化证据不一致——DragonBox RCT 认知收益 g=0.269 且完成度最低，Kahoot! RCT 方向相反，g=0.269 是单一 RCT 数值而非领域上界，$55/生 为美国成本不可迁移；未成年人模式禁游戏链接与广告——游戏化只做机制激励与动机托底。
8. **Agent 壳选型定论**：LangGraph（v1.0：确定性节点与 LLM 节点同图混合+checkpoint+human-in-the-loop）为编排首选；MCP 作确定性策略 API 的暴露协议；Mem0 作叙述性长期记忆层。AutoGen 与微软 GraphRAG 均已进入维护模式，新项目不选。
9. **纸质卷录入批改可行但有短板。** OMRChecker（扫描件近 100%/手机约 90%）+PaddleOCR+pix2text 可拼端到端录入链；《The Aftermath of DrawEduMath》显示 11 个 VLM 在"诊断学生错误"上集体最弱——必须置信度分流+人工复核。
10. **合规是上线硬门槛（十份主题材料均未覆盖，补充调研已补齐）。** 五关：①双减；②生成式 AI/算法备案与内容标识；③未成年人个人信息（PIPL）；④未成年人模式（时长/禁游戏链接广告）；⑤小程序类目资质与教育 App 备案。**适用哪几关取决于 §1.1 渠道选择**（§7.1）。

### 1.1 产品定位前提：客户、商业模式与学科范围（owner 决策项；商业模型本身材料未覆盖）

- **渠道三选型**（合规门槛因选型而异，详见 §7.1）：①B2C 家长（小程序）——售课需《办学许可证》或非学科备案，个人主体不可售课；②B2B 教培接入——"静态卷+xAPI 回传/机构 API"，资质由机构承担；③进校——需教育 App 备案（教技函〔2019〕55 号），未备案不得进校，门槛最高。双减禁"拍照搜题"约束 C 端拍照解题；"作答回收+学情报告"不属拍照搜题，但按学科类培训售卖须挂靠资质机构。建议先 B2C 工具类目+B2B 接入，进校后置；**由 owner 决策**。
- **学科范围**：现有底座全部是数学/理科——XES3G5M/Junyi/CMATH/TAL-SCQ5K/EEDI 均数学，K12-KGraph 数理化生。**建议初期限定数学**；语文/英语的作答数据与图谱材料未覆盖（仅 EDUKG 可部分补、cn-k12 来源存疑），若覆盖则 §6 策略不成立，须另行建设。

---

## 2. 技术栈分层地图

| 层 | 要解决的问题 | SOTA 方案/共识 | 推荐开源选项（许可） |
|---|---|---|---|
| **测量层**（IRT/CAT/组卷质量） | 题参校准、动态选题、曝光与内容平衡、项目分析 | 选题三路线：信息量（MFI/KL/熵）→ 约束优化（shadow test+Sympson-Hetter）→ RL/神经选题；MIP-ATA 静态组卷 | catsim（BSD-3）；cdCAT（MIT，v0.1.0）；girth/py-irt 校准；catR/mirtCAT/TestDesign/GDINA（GPL，无商业授权可购，见 §4 提示）；Winsteps（商业） |
| **认知层**（掌握度建模） | 知识点掌握度/知识状态的确定推断 | CDM+KT 双轨：CDM 出诊断模式、KT 出序列追踪，共享 Q-matrix 互校 | EduCDM（Apache-2.0）；pyKT（MIT）；pyBKT（MIT，小样本在线更新）；knowledge-spaces KST（MIT，27★） |
| **内容层**（题库/知识图谱/出题） | 题源、知识点体系与先序图、自动出题 | TDG 模板化生成+机器可验证答案；"干扰项即误区探针"；生成后测量学校验（P 值/区分度） | TAL-SCQ5K schema（MIT）；GAOKAO-Bench/CMATH/AGIEval 题源；K12-KGraph 骨架（数据 CC BY-NC-SA）；EDUKG/XLORE/MOOCCubeX；渲染 KaTeX/exam.cls |
| **教学层**（路线/方式/复习） | 学什么、怎么教、何时复习 | 循证规则表：提取练习基座+FSRS 间隔复现+expertise reversal 支架调节+Mayer 媒体原则；教学法写成系统级指令（LearnLM 范式） | ts-fsrs/py-fsrs（MIT）；TutorRL/PedagogicalRL（CC-BY-4.0）；MathTutorBench 评测 |
| **交互层**（多端/录入/可视化） | 小程序、静态卷、OMR/OCR 录入、知识地图 | BKT 自适应系统可零后端静态部署（OATutor 先例）；VLM 批改需人机协同 | Taro（MIT）；AntV G6/ECharts；KaTeX；OMRChecker+PaddleOCR+pix2text+LaTeX-OCR；xAPI 标准+Ralph LRS |
| **工程层**（编排/接口/记忆） | 确定性内核+Agent 壳、跨会话状态 | workflow 为骨、Agent 为壳（Anthropic 判据）；掌握度更新绝不交给 LLM | LangGraph（v1.0）；MCP；OpenAI Agents SDK（MIT）；Mem0/Letta；Ralph LRS；Moodle（GPL-3）/Open edX（AGPL-3）机构接入 |

---

## 3. 分主题详细发现

### 3.1 认知诊断与知识追踪

**SOTA 现状**
- **CDM 线**：经典 DINA/G-DINA/IRT 以 EM 估计为主，GDINA R 包（JSS 2020，约 240 引用）是心理测量学标准工具；神经化由 NeuralCD（AAAI 2020/TKDE 2022）开启，EduCDM 已收敛为 pip 实现。2025 顶会热点是 LLM 增强：KCD（AAAI 2025，浙大，模型无关）、LLM4CD（ACM LearT）、KDD 2026 多智能体辩论。
- **KT 线**：pyKT（NeurIPS 2022 D&B，441★）是事实基准，30+ 模型统一评测；simpleKT（ICLR 2023）这一简单基线长期难被击败；LPKT（KDD 2021）建模学习增益/遗忘，pyKT 内置。
- **LLM 直接诊断/追踪（2024-2026）**：LKT（arXiv 2406.02893）融合题面文本做 KT，优于纯 ID 序列并缓解冷启动；RAG-KT（ACL Findings 2026）、LLMKT（LAK 2025）对话式追踪；arXiv 2510.22559 闭环 Agent 生成结构化报告。反面证据：arXiv 2512.23036（预印本，验证安排见 §7.2）警告 LLM 直接建模学习者不可靠——主流范式是"LLM 提语义、模型出概率"。
- **中文数据**：XES3G5M 为最大（抽查确认 500 万+交互/1.8 万学生/7652 题；论文为 NeurIPS 2023 D&B 但 GitHub 页未标注）；Junyi 交互量两口径并存（约 2590 万/1600 万+，未裁定，取数以 EduData 为准）；EdNet（1.3 亿交互）为规模参照。
- 中科大 2024 综述（arXiv 2407.05458）配套工具即 EduData+EduCDM，与"确定性内核"理念契合。KaNCD 独立仓库 404，实现含于 EduCDM。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| pyKT (pykt-toolkit) | KT 基准库 | 30+ 模型统一评测（MIT，441★） | https://github.com/pykt-team/pykt-toolkit |
| EduCDM | CDM 库 | 中科大全家桶，pip 可装（Apache-2.0，197★） | https://github.com/bigdata-ustc/EduCDM |
| EduData | 数据工具 | 数据集下载/预处理（310★） | https://github.com/bigdata-ustc/EduData |
| pyBKT | KT 库 | sklearn 风格 BKT+Roster 接口（280★）；Windows 慢速版 | https://github.com/CAHLR/pyBKT |
| XES3G5M | 中文数据集 | 中文数学 500 万+交互/7652 题，带题面/KC 路径/嵌入（MIT，61★） | https://github.com/ai4ed/XES3G5M |
| GDINA R 包 | 经典 CDM | G-DINA 族统一框架（GPL-3） | https://www.jstatsoft.org/article/view/v093i14 |
| simpleKT | KT 模型 | ICLR 2023 简单强基线，实现在 pyKT 内 | https://arxiv.org/abs/2302.06881 |
| KCD | LLM+CD | AAAI 2025 浙大，模型无关 | https://ojs.aaai.org/index.php/AAAI/article/view/31992 |
| LKT | LLM+KT | 题面文本融合做 KT，可 LIME 解释 | https://arxiv.org/abs/2406.02893 |
| LLM4CD | LLM+CD | 开放世界知识增强 CD（ACM LearT） | https://dl.acm.org/doi/10.1145/3746252.3761321 |
| 闭环学习 Agent | LLM Agent | 知识点级诊断+推荐闭环，生成结构化报告 | https://arxiv.org/html/2510.22559v1 |
| 认知诊断综述 | 综述 | 2024 CDM 综述（中科大） | https://arxiv.org/abs/2407.05458 |
| awesome-ai-llm4education | 论文索引 | LLM+教育论文列表（220★） | https://github.com/GeminiLight/awesome-ai-llm4education |

**对本产品的落地建议**
1. **确定性内核双模型**：诊断卷用 EduCDM 的 DINA/G-DINA（离散掌握模式，小样本可辨识、适配按知识点出报告）；持续互动用 pyKT 的 simpleKT/DKT 序列追踪；共享 Q-matrix 互为校验。
2. **中文冷启动靠 XES3G5M**：预训练 KT 模型+中文题目嵌入解决新题/新学员冷启动（csKT 思路），再在自采数据上微调。
3. **LLM 只做壳不做核**：LLM 负责 Q-matrix 自动标注、错因归因、可解释报告生成（KCD/LKT 范式）；勿让 LLM 直接输出掌握度概率（arXiv 2512.23036 反面证据，预印本验证见 §7.2）。
4. **线下教培小数据**：优先 pyBKT（在线逐生更新+Roster 班级建模）+ G-DINA；深度模型 <10 万交互易过拟合。

### 3.2 自适应测验与教育测量引擎

**SOTA 现状**
- CAT 成熟生态在 R：catR（JSS 2012，被引 200+）是经典模拟标准；mirtCAT 支持多维 IRT 并用 shiny 生成施测界面。2026 年两个新动态：① CRAN 新包 **cdCAT**（v0.1.0，2026-06-15，MIT，抽查确认）——会话式 CD-CAT，内置 DINA/DINO/GDINA、KL/PWKL/MPWKL/Shannon 熵选题与 shadow test 约束（`CdcatSession` 方法名未在 CRAN 页直接展示；GDINA 仅为 Suggests）；② ML 视角 CAT 综述被 IEEE TPAMI 2026 接收（arXiv 2404.00712）。
- 选题算法三路线：统计信息量（MFI、KL 族、Shannon 熵）→ 约束优化（van der Linden shadow test：每步组装满足全部蓝图约束的"影子卷"，统一内容平衡+曝光，配合 Sympson-Hetter 概率曝光）→ RL/神经路线（NCAT、BECAT/MAAT/BOBCAT、深度 Q 网络等）。
- CD-CAT 非参数 GNPS（Chiu 2021）免校准、适合小题库冷启动；QTI 开源参考实现为 TAO。**负面发现**：irtplay 已于 2022-09-13 因版权从 CRAN 移除（已抓页核实），不作基座。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| catsim | Python 库 | 模块化 CAT 引擎（BSD-3，153★）；不含校准（抽查确认） | https://github.com/douglasrizzo/catsim |
| mirtCAT | R 包 | 多维 IRT CAT+shiny 界面（102★） | https://github.com/philchalmers/mirtCAT |
| catR | R 包 | 经典 CAT 模拟库（GPL-3） | https://www.jstatsoft.org/v48/i08 |
| TestDesign | R 包 | MIP-ATA 组卷，v1.7.1，免费 highs 求解器（GPL-2/3） | https://cran.r-project.org/web/packages/TestDesign/index.html |
| cdCAT | R 包 | 会话式 CD-CAT：DINA/GDINA+PWKL/MPWKL/SHE+shadow test（MIT，v0.1.0） | https://cran.r-project.org/web/packages/cdCAT/index.html |
| GDINA | R 包 | CD 校准全家桶+Q 矩阵验证+GUI（GPL-3） | https://wenchao-ma.github.io/GDINA/ |
| EduCAT | Python 库 | 诊断×MFI/KLI/MAAT/BECAT/BOBCAT/NCAT 选题（MIT，76★） | https://github.com/bigdata-ustc/EduCAT |
| NCAT | 论文 | AAAI 2022，选题建模为强化学习 | https://ojs.aaai.org/index.php/AAAI/article/view/20399 |
| ML-CAT 综述 | 综述 | IEEE TPAMI 2026，机器学习 CAT 全景 | https://arxiv.org/abs/2404.00712 |
| GNPCAT | 论文 | Psychometrika 2021 非参数 CD-CAT 选题 | https://pubmed.ncbi.nlm.nih.gov/34341914 |
| Shadow test 综述 | 论文 | 2022，内容平衡最通用解法 | https://link.springer.com/article/10.1007/s41237-021-00150-y |
| Shadow test 曝光控制 | 论文 | JEEA 2004，条目曝光控制 | https://journals.sagepub.com/doi/10.3102/10769986029003273 |
| TAO | 测评平台 | QTI/LTI 开源引擎（GPL v2），PISA 采用 | https://github.com/oat-sa |
| 清华 CD-CAT 文章 | 观点文章 | 论"CD-CAT 是未来方向吗"（抓取超时，取自检索摘要） | https://brain.tsinghua.edu.cn/info/1005/1520.htm |

**对本产品的落地建议**
1. **动态选题引擎**：主栈 catsim（BSD-3），题参用 girth/py-irt 校准；知识点级诊断用 CD-CAT 选题（PWKL/MPWKL/Shannon 熵），接口设计参考 cdCAT 会话式状态机思想（**其为 v0.1.0 新包、方法名未在 CRAN 页直接展示——作设计参考而非移植蓝本，接口命名以自研规范为准**）；知识点配额用 shadow test，防泄题用 Sympson-Hetter/randomesque；EduCAT 作 RL 选题对照实验床。
2. **静态组卷引擎**：TestDesign 的 ATA 思路可直接复用（GPL，注意 §4 许可提示），把覆盖/难度/题型配额写成 MIP 约束（免费 highs 求解）；"平均画像"＝历史学员能力分布做目标信息量最大化（首份画像冷启动见 §6.1）。动态卷＝每答一题重解一次组卷问题，两链路共用一套装配求解器。
3. **交付与标准**：题库元数据按 QTI 建模（兼容 TAO 生态）。许可证：catR/GDINA/TestDesign 为 GPL（无商业授权可购，见 §4 提示），catsim/EduCAT/cdCAT 为 BSD/MIT。

### 3.3 自动出题与题库工程

**SOTA 现状**
1. **LLM 出题范式已定型：约束生成+程序化校验。** IJCAI 2024 综述（arXiv 2402.18267）分结构化/非结构化/混合三类；最可靠落地是 TDG：GPT-4 生成带参数"元模板"，程序化实例化出机器可验证答案的题目——TemplateGSM 7M+ 题即产物（arXiv 2411.18104）；变式生成与苏格拉底式子问题（arXiv 2211.12835）可服务"一题多诊"。
2. **干扰项生成最活跃，且与误区诊断合流**：LookAlike（arXiv 2505.01903）对齐学生常见错误；arXiv 2508.11184 用 MCTS 重建个体推理链生成个性化干扰项（1361 学生实测）；arXiv 2511.01526（ACL 2026 main）难度可控完形干扰项。"干扰项即误区探针"已成共识。
3. **质量控制：测量学校验仍是必经环节**——LLM 难度估计与真实作答对齐已有研究（EEDI 数据，arXiv 2601.09953；ACM CSUR 综述）；部分检索受 429 限流影响。
4. **开源组卷无诊断导向成品，但积木齐备**：GitHub 最高 mikemelon/java-exam（831★，随机/遗传算法）；ExamSym 实抓 0★ 不可用。动态选题（catsim/cdCAT/EduCAT）与 MIP-ATA（TestDesign，GPL）均有引擎（§3.2），缺"配额+信息量+曝光"联合装配层。学术原型 EduLoop-Agent（arXiv 2510.22559）闭环与本产品同构。排版渲染见下表。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| TAL-SCQ5K | 数据集 | 好未来中文小学数学竞赛单选题：解析+知识点路由+难度 0-4（MIT）；页面仅见 3.2K dev，5K/3K+2K 划分未显示 | https://huggingface.co/datasets/math-eval/TAL-SCQ5K |
| GAOKAO-Bench | 数据集 | 2010-2022 真题 2811 道（客观 1781/主观 1030）含解析（Apache-2.0，797★）；2023+ 在补充仓；页面为 10 学科 | https://github.com/OpenLMLab/GAOKAO-Bench |
| EEDI | 数据集 | Eedi 数学多选题约 2000 万条真实作答（NeurIPS 2020 Data Challenge，与 §3.5/§6 同口径），含 misconception 标注 | http://proceedings.mlr.press/v133/wang21a/wang21a.pdf |
| TDG/TemplateGSM | 论文+数据集 | 元模板生成 7M+ 可验证解数学题 | https://arxiv.org/abs/2411.18104 |
| LookAlike | 论文 | MCQ 干扰项对齐学生常见错误（2025） | https://arxiv.org/abs/2505.01903 |
| 个性化干扰项生成 | 论文 | MCTS 重建推理链，免训练个性化干扰项 | https://arxiv.org/abs/2508.11184 |
| Learning by Analogy | 论文 | MWP 变式生成 DiverseMath23K（ACL 2023 Findings） | https://arxiv.org/abs/2306.09064 |
| Socratic Subquestions | 论文 | RL 生成引导式子问题（EMNLP 2022） | https://arxiv.org/abs/2211.12835 |
| Neural QG Survey | 论文 | 神经问题生成综述（IJCAI 2024） | https://arxiv.org/abs/2402.18267 |
| EduLoop-Agent | 论文 | 诊断+BECAT 选题+LLM 反馈闭环，架构同构参考 | https://arxiv.org/abs/2510.22559 |
| 难度估计综述 | 论文 | 难度自动估计综述（ACM CSUR） | https://dl.acm.org/doi/10.1145/3556538 |
| LLM 难度估计对齐 | 论文 | 基于 EEDI 实测的难度估计 | https://arxiv.org/abs/2601.09953 |
| 难度可控完形干扰项 | 论文 | ACL 2026 main | https://arxiv.org/abs/2511.01526 |
| Winsteps/FACETS | 工具 | Rasch 项目分析：P 值/区分度/DIF（商业软件） | https://www.winsteps.com |
| exam.cls | 工具 | LaTeX 试卷类 v2.704（2023-07，LPPL 1.3），中文配 ctex | https://ctan.org/pkg/exam |
| KaTeX | 工具 | 公式渲染（MIT，20.4k★），SSR 适配小程序/H5 | https://github.com/KaTeX/KaTeX |
| mikemelon/java-exam | 开源项目 | 831★ 题库+随机/遗传组卷（非诊断导向） | https://github.com/mikemelon/java-exam |
| cppcpp/exam-system | 开源项目 | 87★ 遗传算法组卷 | https://github.com/cppcpp/exam-system |
| Excel 题库→Word 试卷 | 开源项目 | 63★ 随机组卷出 Word，适配静态分发 | https://github.com/wukai0909/Generating-WORD-Test-Papers-from-Excel-Question-Bank |

**对本产品的落地建议**
1. **题库冷启动"两库一校准"**：TAL-SCQ5K 字段为 schema 基准，GAOKAO-Bench 补初高中真题，EEDI 校准 misconception 诊断与难度先验。
2. **出题管线＝TDG+双重校验**：先做答案机器可验证的元模板，LLM 只做表层多样化与配图变式；干扰项按常见错误模式生成并绑定可诊断误区标签——诊断卷区别于普通卷的核心。
3. **测量学校验闭环不可省**：新题按"平均画像"小样本试测，P 值（0.3-0.7）与点二列区分度（≥0.2）达标回填（Winsteps 或等价自研脚本），未达标进隔离区；首批试测样本来源见 §6.1。
4. **组卷内核＝开源选题/ATA 引擎+自研约束装配层**：在覆盖/难度/exposure 约束下最大化诊断信息量（参考 BECAT/CD-CAT）；catsim/cdCAT/EduCAT 可复用，TestDesign 思路自研实现以规避 GPL，作确定性接口暴露给 Agent。
5. **分发层**：静态卷走 exam.cls（或 wukai0909 式 Word 管线）；小程序公式用 KaTeX 服务端预渲染。

### 3.4 K-12 知识图谱与知识空间

**SOTA 现状**
- 先序抽取已成成熟任务：AL-CPL（2018）→ CIKM 2024 学习路径监督 → AAAI 2025 全局结构依赖模型，ACM CSUR 2025 刊出综述（DOI 10.1145/3733593）。
- 2024-2026 主线是 LLM 深度参与构建：MDPI 2025 实证 LLM 可判读课程概念先序；AutoMathKG（arXiv 2505.13406）LLM+向量库自动构建数学 KG。对标性最强是 **K12-KGraph**（arXiv 2605.09635）：人教版数理化生教材抽取的课程对齐 KG（9 节点/14 关系）+K12-Bench 约 2.36 万题；核心发现：强 LLM 存在"课标结构感知缺口"、先序图必须显式外置。（材料称 NeurIPS 2026 D&B，未在 GitHub 页核实。）
- KST（Doignon & Falmagne）仍是"诊断卷↔知识状态"的数学基础，ALEKS 已验证 30 年。knowledge-spaces（MIT）把 KST 封装为 10 个 Agent 技能（QUERY/知识状态枚举/BLIM/PoLIM 约 20-30 题自适应测评）；仓库仅 27★，需评估成熟度。
- 中文基础设施：EDUKG、XLORE（中英跨语言）、MOOCCubeX（35.8 万练习+63.7 万知识点+三科先序+2.96 亿行为，免申请直下；偏高教）。
- **未能核实**：同名 MathKG 未检索到（最接近 Math-KG/AutoMathKG）；MathGraph 与 CourseKG 仅见于检索摘要，一手页面未打开。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| K12-KGraph | 论文+数据集 | 人教版课标对齐 KG（9 节点/14 关系）+K12-Bench 23,640 题 | https://arxiv.org/abs/2605.09635 |
| haolpku/K12-KGraph | 开源仓库 | 390★ 活跃；数据 CC BY-NC-SA 4.0/代码 MIT（含 HF 数据集与 checkpoint） | https://github.com/haolpku/K12-KGraph |
| knowledge-spaces | 开源仓库 | KST 全流程 10 个 Agent 技能（QUERY/BLIM/PoLIM 20-30 题）（MIT，仅 27★） | https://github.com/vanderbilt-data-science/knowledge-spaces |
| AL-CPL | 数据集 | 4 学科 6529 概念对先序标注（CC BY-NC-SA 4.0，24★） | https://github.com/harrylclc/AL-CPL-dataset |
| MOOCCubeX | 数据集 | 35.8 万练习+63.7 万知识点+三科先序+2.96 亿行为（GPL-3.0，195★） | https://github.com/THU-KEG/MOOCCubeX |
| 先序关系综述 | 综述 | CSUR 2025 全景 | https://doi.org/10.1145/3733593 |
| 全局结构依赖先序抽取 | 论文 | AAAI 2025 | https://ojs.aaai.org/index.php/AAAI/article/view/32156 |
| 学习路径监督先序抽取 | 论文 | CIKM 2024 | https://dl.acm.org/doi/10.1145/3627673.3679597 |
| LLM 判读课程先序实证 | 论文 | MDPI 2025 | https://www.mdpi.com/2504-4990/7/3/103 |
| ConExion | 论文 | LLM 概念抽取 | https://arxiv.org/html/2504.12915v2 |
| AutoMathKG | 论文 | LLM+向量库自动数学 KG | https://arxiv.org/abs/2505.13406 |
| ALEKS / KST | 系统+理论 | KST 商品化实现 | https://www.aleks.com |
| KnowEdu | 论文 | IEEE Access 2018，从课标抽知识点/关系（被引约 400） | https://ieeexplore.ieee.org |
| EDUKG | 在线 KG | 清华教育 KG 平台 | http://www.edukg.cn |
| XLORE | 在线 KG | 中英跨语言 KG，跨教材实体对齐 | https://xlore.cn |

**对本产品的落地建议**
1. **骨架复用 K12-KGraph**：以人教版对齐 KG 做知识地图底座，先用 K12-Bench 测基座 LLM 课标结构缺口，再定微调或检索增强；数据 CC BY-NC-SA，商用需授权或重建。
2. **半自动先序图管线**：教材/课标文本→LLM 概念抽取（ConExion 类）→LLM 先序判读（MDPI 协议）→偏序校验（AL-CPL 做法）→专家只仲裁低置信边；用 AL-CPL+MOOCCubeX 做评测集，人工标注降一个量级。
3. **诊断内核采用 KST**：knowledge-spaces 可改造为小程序/静态分发共用的接口规范；其"外缘（outer fringe）"即学习路线起点。
4. **行为数据冷启动**：MOOCCubeX 标注与 2.96 亿做题记录可作难度/区分度先验参考（偏高教，不作 K12 画像来源）。
5. **全球经验映射**：XLORE 做中英实体对齐挂接中国课标；EDUKG 补语文/英语；AL-CPL 非商业许可。

### 3.5 开放教育数据集盘点（KT/CD + 中文 K12 题源）

**SOTA 现状**
- 数据集三代：经典基准（ASSISTments，仅 ID 级）→ 超大规模日志（EdNet 1.31 亿交互、EEDI 约 2000 万条）→ 富标注新一代（XES3G5M 附题面/KC 路径，Eedi 2024 附 2587 种误解标签）。共识工具是 pykt-toolkit 与 EduData。
- 中文 K12：原生作答数据极少，XES3G5M 是唯一公开的中国 K12 大规模作答集（数学）；题源靠评测集与 HF 社区 k12 数据集；知识体系可从 Junyi 与 XES3G5M 标注抽取。
- **未决事项（如实记录）**：Junyi 确切 Kaggle 下载页两次 404 未核实（经 EduData 获取）；CMATH 官方 GitHub 未核实（HF 页已核实）；ASSISTments2012 含隐私敏感字段，商用前复核条款。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| XES3G5M | KT 数据集 | 同 3.1；555 万交互口径，NeurIPS 2023 D&B（MIT，61★ 更新少） | https://github.com/ai4ed/XES3G5M |
| Junyi Academy | KT 数据集 | 均一 K12 数学（2012-2016），自带知识点映射与前置图；Kaggle 链接未核实，经 EduData 获取 | https://github.com/bigdata-ustc/EduData |
| ASSISTments 2009/2012/2015 | KT 经典基准 | 2009 最常用；2015=70.9 万交互/100 KC | https://sites.google.com/site/assistmentsdata |
| EdNet | KT 数据集 | 托业英语 1.31 亿交互/78.4 万学生，KT1-KT4（非 K12） | https://github.com/riiid/ednet |
| EEDI (NeurIPS 2020) | 诊断题数据集 | 约 2000 万条答题，EDM 2021 最佳数据集 | https://arxiv.org/abs/2007.12061 |
| Eedi Mining Misconceptions | 误解标注数据集 | 1857 题标注 2587 种 misconceptions | https://www.eedi.com/news/from-wrong-answers-to-real-insights-how-we-used-a-kaggle-challenge-to-map-student-misconceptions |
| MOOCCube/MOOCCubeX | MOOC 数据仓库 | 清华 KEG+学堂在线（偏高教，非 K12） | http://moocdata.cn/data/MOOCCube |
| KDD Cup 2015 | MOOC 数据集 | 辍学预测基准（官网偶尔失效） | http://moocdata.cn/challenges/kdd-cup-2015/ |
| CMATH | 中文题源 | 1.7k 小学应用题，年级+难度标注（HF 已核实；GitHub 未核实） | https://huggingface.co/papers/2306.16636 |
| GAOKAO-Bench | 中文题源 | 同 3.3；多模态版 GAOKAO-MM 覆盖 2010-2023 | https://github.com/OpenLMLab/GAOKAO-Bench |
| AGIEval | 中文题源 | 20 任务考试基准，含 gaokao-五科（MIT 代码，776★） | https://github.com/ruixiangcui/AGIEval |
| C-Eval | 中文题源 | 13948 题/52 学科（CC BY-NC-SA 4.0）；2025-07 起完整测试集公开 | https://github.com/hkust-nlp/ceval |
| EduData | 数据工具集 | 一条命令拉取/预处理十余基准（310★） | https://github.com/bigdata-ustc/EduData |
| pykt-toolkit 文档 | 文档 | 内置 10 个数据集预处理（本次仅取到数据集清单） | https://pykt-toolkit.readthedocs.io/en/latest/ |
| HuggingFace k12 合集 | 题库集合 | mathfish、cn-k12（来源存疑）、CMMaTH 等 | https://huggingface.co/datasets?other=k12 |

**对本产品的落地建议**
1. **认知诊断内核训练**：XES3G5M 作主基准（同训 KT 与题目表征）；EduData 一条命令补齐 ASSISTments/Junyi/EdNet 泛化验证（pykt 协议保证可比）。
2. **知识点体系抽取**：Junyi 前置关系图 + XES3G5M 层级路径，人工校对后映射人教版教材目录，作为确定性内核知识图谱起点。
3. **静态卷题源**：CMATH（小学带难度分级）+GAOKAO-Bench/AGIEval gaokao-*（初高中真题含解析）；C-Eval 为 CC BY-NC-SA，商用需替换或授权；AGIEval 遵循原考试出处许可。
4. **"错误→误解"层**：借鉴 Eedi 方式（每题错选项绑定误解标签），自建初期 LLM 预标 Eedi 式误解再人工校验。

### 3.6 跨国课程标准映射与资源对齐

**SOTA 现状**
- **不存在现成"外国资源→中国课标"公开映射数据集**。主流路径：标准机器可读化 → LLM/RAG 打标 → 专家抽检。中国侧：教育部官网提供 2022 版 16 科课标 PDF（教材〔2022〕2 号，逐一核实可下载），无官方结构化版本，需自行解析成知识点树。
- 国外侧：1EdTech CASE（REST/JSON-LD）为标准机器可读规范，Common Core 经 CASE Network 获取；UK 课标有官方页面；GitHub 的 CCSS 散仓老旧（<5★），不足为依赖。
- 2024-2026 共识：纯检索对齐不够（F1 仅 0.55），"LLM 确认+专家校验"是标配；中文 K-12 出现可复用课标对齐 KG——K12-KGraph 与 MDK12-Bench。跨语言对齐经典为 GMNN（ACL 2019）与协同推理（AAAI 2020），LLM 时代教育领域无公认开源方案。
- OER 库（OpenStax/OER Commons/Khan）只对美标对齐；Khan/OER Commons 反爬拦截，映射数据未核实。**未竟**：PISA 2022 框架（OECD 被 Cloudflare 拦截）、"可汗-网易"合作先例（限流未获来源）。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| 义务教育课程标准（2022 年版） | 官方课标 PDF | 16 科 PDF 逐一核实可下载（教材〔2022〕2 号） | http://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html |
| K12-KGraph | 论文+KG+数据集 | 同 3.4 | https://arxiv.org/abs/2605.09635 |
| K12-KGraph 仓库 | GitHub 390★ | KG/评测/SFT 数据/管线全开源 | https://github.com/haolpku/K12-KGraph |
| K12-KGraph 数据集 | HuggingFace | KG+benchmark+训练数据（已验证 200） | https://huggingface.co/datasets/lhpku20010120/K12-KGraph |
| MDK12-Bench | 评测集 | 141K 真题、6 层 6,225 知识点，专测知识点增强 RAG（代码 87★） | https://arxiv.org/abs/2508.06851 （代码 https://github.com/LanceZPF/MDK12） |
| CMMaTH | 评测集 | 23K 中文 K12 多模态数学题 | https://arxiv.org/abs/2407.12023 |
| EDUKG | 知识图谱 | 2.52 亿实体/38.6 亿三元组 | https://arxiv.org/abs/2210.12228 |
| CASE 规范 | 标准 | 学科标准机器可读交换规范（JSON/JSON-LD） | https://www.imsglobal.org/spec/case/v1p0 |
| CASE Network | 注册库 | 官方 CASE 库，可取 Common Core 等 | https://casenetwork.imsglobal.org/ |
| UK National Curriculum | 官方课标 | 英格兰 KS1-4 全科 | https://www.gov.uk/government/collections/national-curriculum |
| TIMSS 2023 Frameworks | 评估框架 | 数学 content×cognitive 二维框架 | https://timss2023.org/frameworks/ |
| CS2013/CS2023 对齐框架 | 论文 | LLM 确认+专家验证管线，纯检索 F1 0.55 | https://arxiv.org/abs/2606.19469 |
| CourseGraph | 论文 | 跨国课程重叠/差异检测先例 | https://arxiv.org/abs/2608.05910 |
| ConnectED | 论文/系统 | 越南课标对齐教育 LLM，国家级样板 | https://arxiv.org/abs/2607.28647 |
| 跨语言 KG 对齐经典 | 论文 | GMNN（ACL 2019）/协同推理（AAAI 2020） | https://arxiv.org/abs/1905.11605 、https://arxiv.org/abs/2001.08728 |
| EduChat | 开源模型 | 华东师大中文教育对话模型（972★） | https://github.com/ECNU-ICALK/EduChat |
| EQGBench | 评测集 | 中文出题质量评测（知识点/难度/题型约束） | https://arxiv.org/abs/2508.10005 |
| OpenStax | OER 教材 | 免费开放教科书库（许可细节未核实） | https://openstax.org/details/books/prealgebra |
| Khan Academy CCSS | 练习对齐页 | 在线但反爬拦截，映射数据未核实 | https://www.khanacademy.org/commoncore |
| OER Commons | OER 库 | /api 403 反爬，接口需申请 | https://www.oercommons.org/ |

**对本产品的落地建议**
1. **中文知识点底座**：采用 K12-KGraph 的 KG+管线做起点，对照教育部 2022 课标 PDF 人工校准知识点树；CC BY-NC-SA 商用需授权或重建。
2. **国外资源入库通道**：外国教材/题源先挂 CASE/CCSS 或 TIMSS 元数据，再用 LLM 做"美标→中文知识点树"映射（参考 GMNN 思路+多语嵌入），专家抽检——纯检索/纯 LLM 都不够。
3. **诊断卷双轨标签**：每题同时打"中国课标知识点"与"TIMSS 2023 content×cognitive"双标签，便于引入国际题源并支撑知识地图。
4. **评测基准**：用 MDK12-Bench/CMMaTH/EQGBench 持续评测知识点标注与出卷质量。

### 3.7 智能导师系统与 LLM 导师

**SOTA 现状**
- 主线是 **pedagogical alignment（教学对齐）**：共识"解题能力≠教学能力"，导师必须学会不直接给答案。
- **业界商用**：Khanmigo（GPT-4 苏格拉底式引导，官网核实；有数学错误免责）；Google LearnLM（专家偏好 +31% 优于 GPT-4o、+11% 优于 Claude 3.5）；Carnegie Learning（MATHia+LiveHint AI）、ALEKS（KST）。国内：学而思九章、讯飞学习机（2025"精准学"）、松鼠AI（媒体评测），均走"诊断→溯源→个性化路径"。Duolingo Max 仅见产品评测页，**未找到同行评审效果研究**。
- **学术三主线**：①教学法对齐（QA-Alignment：LHP 优于 SFT）；②RL 训导师（TutorRL/UCO/PEARL）；③评测基准（MathTutorBench：8 模型"解题分与教学分"相关性仅 0.421，须分开报告）。
- **幻觉治理**：LearnLM 实测零样本教学提示损害事实性；主流做法是 RAG 接地+教学法护栏（引导而非给答案）。
- **更正说明**：线索"Tutelle"经检索无对应项目（仅法语"监护"一词），实为 TutorRL。CoMTA（Khan Academy 真实 Khanmigo 对话 188 段，Miller & Dicerbo 2024）arXiv 无收录，仅见于 TutorTest（OpenReview）引用，注意来源强度。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| Khanmigo | 商用 LLM 导师 | GPT-4 苏格拉底式导师+教师助手（官网核实） | https://www.khanmigo.ai/ |
| LearnLM | 教学微调模型 | Gemini 1.5 Pro 教学微调（pedagogical instruction following） | https://arxiv.org/abs/2412.16429 |
| LearnLM 评测法 | 论文/方法 | Pedagogy Bench+PedagogyGain；提示对齐损害事实性 | https://arxiv.org/abs/2407.12687 |
| Tutor CoPilot | 人机协同系统 | 900 导师/1800 学生 RCT：+4pp、弱导师 +9pp（$20/年） | https://arxiv.org/abs/2410.03017 |
| TutorRL (PedagogicalRL) | 开源 RL 导师 | GRPO 模拟课堂训 7B 接近 LearnLM（49★，CC-BY-4.0） | https://github.com/eth-lre/PedagogicalRL |
| MathTutorBench | 评测基准 | 开放式教学能力基准（EMNLP 2025 Oral） | https://arxiv.org/abs/2502.18940 |
| QA-Alignment | 奠基论文 | 教学对齐：LHP 优于 SFT（+13.1%/+8.7%） | https://arxiv.org/abs/2402.05000 |
| UCO | RL 方法 | Progress+Scaffold（ZPD）奖励（EMNLP 2026） | https://arxiv.org/abs/2511.08873 |
| PEARL | RL 方法 | 可控学生模拟器+联合奖励（2026） | https://arxiv.org/abs/2605.29582 |
| OmniEdu | 开源 K-12 基础模型 | 4B/9B/27B，Scaffold 78.74%（2026-09） | https://arxiv.org/abs/2609.23088 |
| EduChat | 开源教育 LLM | 华东师大，作文评估/苏格拉底/情感支持 | https://arxiv.org/abs/2308.02773 |
| Mr.-Ranedeer-AI-Tutor | 开源 prompt | 29.6k★ 配置化教学 prompt（已停更） | https://github.com/JushBJJ/Mr.-Ranedeer-AI-Tutor |
| TutorTest + CoMTA | 评测/数据集 | 真实 Khanmigo 对话评测（CoMTA 来源强度有限） | https://openreview.net/pdf?id=UoJZv2YfDX |
| LiveHint AI (MATHia) | 商用 ITS | 认知导师叠加生成式 AI | https://discover.carnegielearning.com/livehint-ai |
| ALEKS | 商用 ITS | KST 知识状态评估 | https://www.aleks.com/about_aleks |
| 学而思九章 MathGPT | 国内教育大模型 | "分析-详解-点睛"，不直接给答案 | https://m.bjnews.com.cn/detail/1721802964168204.html |
| 讯飞 AI 学习机 | 国内学习机 | 2025"精准学"+AI 1 对 1 | https://www.stdaily.com/web/gdxw/2025-06/25/content_360337.html |
| 松鼠 AI 学习机 | 国内智适应 | LAM 大模型+微颗粒图谱（媒体评测） | https://mt.sohu.com |

**对本产品的落地建议**
1. **教学方式选择器采用 LearnLM 范式**：教学法写成"系统级教学指令"（按知识点+画像注入脚手架/苏格拉底/直接讲解），内核存策略、Agent 只发指令——与 pedagogical instruction following 同构，免整模型微调。
2. **策略空间参数化**：TutorRL 奖励权重 λ（教学支持 vs 学生解题正确）给出可调帕累托前沿；UCO 的 ZPD Scaffold Reward 量化最近发展区——均可映射为选择器可调维度。
3. **评测闭环**：MathTutorBench 开源奖励模型做内部回归评测，教学分/解题分分开报告（相关性仅 0.421）；CoMTA 式真实对话做策略离线评估。
4. **快速起步**：提示层复用 Mr.-Ranedeer 配置化结构；模型层选 OmniEdu-27B 或 EduChat（中文）；RL 升级直接跑 PedagogicalRL（免人工标注）。
5. **幻觉治理**：勿只靠提示词做教学对齐（LearnLM 实测损害事实性）——答案与事实走内核/RAG，讲解与引导走 LLM；数学错误显式校验+免责。
6. **线下教培渠道**：Tutor CoPilot"人机协同放大弱导师"（$20/导师/年、弱导师学生 +9pp）与机构接入形态天然契合。

### 3.8 教育 Agent 工程架构与确定性接口

**SOTA 现状**
- 2024-2026 共识走向"**工作流为骨、Agent 为壳**"。Anthropic《Building Effective Agents》区分 workflow（代码路径编排）与 agent（LLM 自主决定流程），"任务可分解为固定步骤时勿用自主 agent"，并给出五种模式（chaining/routing/parallelization/orchestrator-workers/evaluator-optimizer）。
- LangGraph（2025-10 v1.0）以状态机+checkpoint+HITL 成为有状态多 agent 事实标准，同图可混合确定性节点与 LLM 节点；OpenAI Agents SDK（29.7k★，MIT）；AutoGen 与 GraphRAG 均维护模式（前者指向 Microsoft Agent Framework），新项目不选作底座。
- 接口标准化由 MCP（Linux Foundation）承担；记忆层 Mem0（Apache-2.0）与 Letta 解决跨会话状态。
- **教育学关键证据**：arXiv 2512.23036（2025-12 预印本）证明 K-12 learner modelling 上 DKT AUC 0.83 胜过零样本与微调 LLM（后者掌握度更新方向不稳、早期序列错误多、微调耗约 198 小时，"仍低 6%"未注明口径），结论是"负责任的教学需要 hybrid 框架"（验证安排见 §7.2）。
- **检索限制**：open learner model 方向未找到活跃开源实现，仅 xAPI/LRS 与 pyKT 数据结构可参照（如实记录）。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| LangGraph | 框架 | 状态机+checkpoint/HITL，v1.0 | https://docs.langchain.com/oss/python/langgraph/overview |
| OpenAI Agents SDK | 框架 | handoffs/guardrails/sessions/tracing，模型无关 | https://github.com/openai/openai-agents-python |
| AutoGen/MAF | 框架 | 61.2k★ 已维护模式；继任 MAF 支持 A2A+MCP | https://github.com/microsoft/autogen |
| MCP | 协议 | 确定性策略 API 暴露层 | https://github.com/modelcontextprotocol |
| Mem0 | 记忆层 | 三级记忆+混合检索（Apache-2.0，66.2k★） | https://github.com/mem0ai/mem0 |
| Letta (MemGPT) | 记忆层 | 有状态 agent 平台 | https://github.com/letta-ai/letta |
| GraphRAG | 检索 | 维护模式+索引贵，宜自建轻量方案 | https://github.com/microsoft/graphrag |
| pykt-toolkit | KT 库 | 30+ 模型+7 数据集（MIT） | https://github.com/pykt-team/pykt-toolkit |
| OATutor | 开源 ITS | BKT 掌握度+选题，零后端静态部署（MIT+CC BY 4.0，265★） | https://github.com/CAHLR/OATutor |
| Problems With LLMs for Learner Modelling | 论文 | DKT（AUC 0.83）胜 LLM，主张 hybrid（预印本，见 §7.2） | https://arxiv.org/abs/2512.23036 |
| MALPP | 论文 | 多 agent 学习路径规划 | https://arxiv.org/abs/2601.17346 |
| Correct Answer Trap | 论文 | "答对即懂"陷阱：漏诊误解 | https://arxiv.org/abs/2605.23925 |
| 分层检索（Mwando） | 论文 | 向量+KG+兜底分层检索 | https://arxiv.org/abs/2607.23481 |
| 洋葱学园自学破壁计划 | 工业案例 | 六角色多 agent，学情诊断驱动（2000+ 校） | https://www.qbitai.com/2025/11/349266.html |
| Building Effective Agents | 方法论 | workflow vs agent 判据与五模式 | https://www.anthropic.com/research/building-effective-agents |

**对本产品的落地建议**
1. **确定性内核**：认知状态用 pyKT 系模型（DKT/AKT/IEKT）或 OATutor 式 BKT 在数据库中确定性更新，暴露 update_state/query_state/get_strategy 三类 API（经 MCP tools 封装）；诊断卷生成与批改走固定 pipeline；掌握度更新绝不让 LLM 产出。
2. **Agent 壳**：LangGraph 编排导师/出题/学情分析多角色（orchestrator-workers），checkpoint 保证长流程可恢复、HITL 供教师审核；轻量场景用 OpenAI Agents SDK；内容检索用"向量+知识图谱+兜底"分层，避免 GraphRAG 全量索引题库。
3. **记忆分层**：Mem0 存学习偏好/情绪/交互史等叙述性记忆；掌握度向量由内核计算，二者分离。轨迹以事件流（user_id, skill, correct, timestamp）入库，兼容 pyKT 格式与 ASSISTments 风格数据。
4. **反模式**：a) LLM 直接估计掌握度；b) 多 agent 自由对话起步；c) "答对即懂"（Correct Answer Trap）——诊断卷需含过程性证据与错因标注；d) 无 checkpoint 的长会话 agent。
5. **渠道契合**：OATutor 证明 BKT 自适应系统可零后端静态分发，直接支撑"静态试卷文件"渠道；教培接入走 MCP 或 LTI。国内对标：洋葱学园六角色多 agent（2000+ 校）。

### 3.9 学习科学与教学策略选择

**SOTA 现状**
- Visible Learning MetaX（Hattie，250+ 因素，hinge point d=0.40≈一学年进步）；practice testing 已核实：加权 d=0.49（5 篇元分析、744 项研究、222,708 名学生）。
- **记忆/练习三大支柱**：①提取练习——Adesope 2017 确认优于重读等所有对照；②间隔重复——Cepeda 2006（254 项研究）奠基，工程化为 FSRS（内置 Anki 23.10+，基于 5 亿+复习记录，源头为墨墨 KDD'22 论文）；③交错练习——Brunmair & Richter 2019 元分析总体 g≈0.42，"相似性"是关键调节变量：易混相似题型（数学）收益大，差异大的材料可能无效。
- **教学方式匹配**：Mayer CTML 2024 综述（开放获取）梳理 15 条循证原则、200+ 实验；expertise reversal 有 2025 新元分析（Tetzlaff）：支架帮新手、伤高先验学生——"按学生特点选方式"最硬依据（Kalyuga 2007）。
- **游戏化**：Sailer & Homner 2020 元分析显示认知/动机/行为均为小到中等正效应；大样本 RCT：DragonBox N=1,850 七年级生 g=0.269、优于 active control，完成度却最低（5.5/9 次 vs 6.6-6.9）；Chan 2023：游戏进度仅对高先验学生预测代数知识；FH2T 对高前测收益更大（p=.011）；而 Kahoot! RCT（2023）方向相反。即：**游戏化认知收益证据不一致，g=0.269 是单一 RCT 数值而非领域上界；$55/生（Finster 2024）为美国成本核算，不可直接迁移国内定价**。游戏≠收益，动机增益与认知增益分开记账。
- **奠基背景**：Bloom 1984"2σ 问题"（1300+ 引用）；但实践复制常接近 1σ 或更低，Kulik 1990 显示群体版掌握学习仅约 0.2-0.5（检索摘要未核验）。Kahoot! Wang & Tahir 2020、Dunlosky 2013、Kulik 1990 未取得可核验 URL，数值仅作背景。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| ts-fsrs | 开源库 | FSRS-6 调度器（MIT，799★）；npm 包+Rust binding 参数优化 | https://github.com/open-spaced-repetition/ts-fsrs |
| open-spaced-repetition | 开源组织 | py-fsrs/rs-fsrs/fsrs4anki 全家桶 | https://github.com/open-spaced-repetition |
| FSRS SSP 论文 | 论文 | 墨墨 KDD'22 随机最短路径 | https://doi.org/10.1145/3534678.3539081 |
| fsrs4anki wiki | 资源索引 | FSRS 研究资源清单 | https://github.com/open-spaced-repetition/fsrs4anki/wiki/Research-resources |
| Bloom (1984) | 奠基论文 | 2σ 问题 | https://doi.org/10.3102/0013189X013006004 |
| Adesope et al. (2017) | 元分析 | 提取练习优于重读等所有对照 | https://journals.sagepub.com/doi/abs/10.3102/0034654316689306 |
| Cepeda et al. (2006) | 元分析 | 间隔效应 254 项研究综合 | https://doi.org/10.1037/0033-2909.132.3.354 |
| Brunmair & Richter (2019) | 元分析 | 交错练习 g≈0.42，相似性为调节变量 | https://doi.org/10.1037/bul0000209 |
| Visible Learning MetaX | 效应量数据库 | practice testing d=0.49（已核实）；hinge d=0.40 | https://www.visiblelearningmetax.com/influences/view/practice_testing |
| Mayer (2024) CTML 综述 | 综述 | 多媒体学习 15 条原则（开放获取） | https://link.springer.com/article/10.1007/s10648-023-09842-1 |
| Tetzlaff et al. (2025) | 元分析 | expertise reversal 最新证据 | https://www.sciencedirect.com/science/article/pii/S0959475225000660 |
| Kalyuga (2007) | 综述 | learner-tailored instruction 框架 | https://psycnet.apa.org/record/2008-00316-006 |
| Alfieri et al. (2011) | 元分析 | 有引导发现优于无引导发现 | https://doi.org/10.1037/a0021017 |
| Decker-Woodrow et al. (2023) | RCT | N=1850 三技术对照：DragonBox g=0.269 | https://pmc.ncbi.nlm.nih.gov/articles/PMC10125888 |
| Finster et al. (2024) | 成本效果研究 | DragonBox $55/生（美国口径） | https://www.tandfonline.com/doi/abs/10.1080/19345747.2023.2269918 |
| Chan et al. (2023) | 实证研究 | 游戏进度仅对高先验学生预测代数知识 | https://bera-journals.onlinelibrary.wiley.com/doi/10.1111/bjet.13304 |
| Sailer & Homner (2020) | 元分析 | 游戏化小到中等正效应及边界 | https://doi.org/10.1007/s10648-019-09498-w |
| Kahoot! RCT (2023) | RCT | 游戏化强化内容取得更好成绩（与 DragonBox 方向不一致） | https://pmc.ncbi.nlm.nih.gov/articles/PMC9957048 |

**对本产品的落地建议**
1. **间隔重复内核采用 FSRS**：前端 ts-fsrs、服务端 py-fsrs；"知识点=卡片、诊断卷错误=初始记忆状态、复习日志=反馈"映射为确定性接口；数据积累后用 Rust binding 拟合个人参数。
2. **教学策略选择器做成确定性规则表**（Agent 不可绕过）：低先验→worked example+自我解释；易混相似题型→交错出题；先验达标→撤支架、减冗余媒体（Mayer 冗余/一致性/分段原则）；游戏化仅动机托底与低龄/低先验，认知收益预期保守记账（证据不一致，勿以单一 RCT 外推上界）。
3. **以提取练习为默认基座**：每份练习卷天然是提取练习（d=0.49 > hinge 0.40），新策略上线以 d=0.40 为 ROI 对照线做 A/B。
4. **静态分发卷"平均画像"配方**：掌握学习门槛（达标才推进）+交错混排+卷末间隔复练页——Bloom 2σ 三要素（即时纠错反馈、前置知识补齐、1:1 级交互）中无需真人辅导的最低成本近似。
5. **证据缺口**：群体版 mastery learning 远小于 2σ；expertise reversal 要求先验估计准确——诊断输出与 FSRS 状态的联合校准质量决定策略上限（验收指标见 §7.6）。并叠加合规约束（§7.1）。

### 3.10 商业产品对标与全套工程选型

**SOTA 现状**
- **商业对标三类形态**：①校内阅卷+学情——讯飞智学网，专利 CN110264091A 展示"答题记录→知识点相关度→认知状态"路线；②自适应系统——松鼠AI（KST+细粒度图谱，已转"基础模型+RAG+Agent"，据 arXiv 综述）；③C 端+大模型——九章 MathGPT、作业帮学习机、猿辅导（接入 DeepSeek）。共性闭环"题库→诊断→推荐"，公开资料以专利/论文/财报为主。
- **录入链已成熟**：OMRChecker（扫描件近 100%/手机约 90%，抽查确认）+PaddleOCR（Apache-2.0）+pix2text（MIT，中文+公式→Markdown）+LaTeX-OCR（手写需微调）。
- **大模型批改**：MathAgent 三智能体做多模态错误检测；LLM 定位首错步骤；代数错误分类超越基线。但《The Aftermath of DrawEduMath》在 11 个 VLM 上发现"诊断学生错误"是所有模型最弱项——VLM 批改需置信度分流+人工复核，不能全自动。
- **标准与平台**：xAPI（ADL；2.0 在 IEEE）；LRS 起步 Ralph（MIT）；Caliper 生态弱。LMS：Moodle（GPL-3）/Open edX（AGPL-3）。可视化：G6 v5（MIT）适合知识地图，轻量 ECharts，图分析用 Cytoscape.js。
- **未找到项（如实记录）**：好未来 MathGPT、作业帮大模型均未检索到公开技术论文原文；智学网无公开架构文档（官网 JS 渲染抓取无实质内容）；Caliper 的活跃开源 LRS 未找到。

**代表项目·论文·数据集**

| 名称 | 类型 | 一句话说明 | URL |
|---|---|---|---|
| OMRChecker | 开源 OMR | 1.2k★ MIT，模板 JSON 定制，输出评分 CSV | https://github.com/udayraj123/OMRChecker |
| PaddleOCR | OCR 引擎 | 90.3k★ Apache-2.0，PP-OCRv6/VL | https://github.com/PaddlePaddle/PaddleOCR |
| pix2text | 版面+公式 OCR | 3.3k★ MIT，中文+公式→Markdown | https://github.com/breezedeus/pix2text |
| LaTeX-OCR (pix2tex) | 公式识别 | 16.6k★ MIT，手写需微调 | https://github.com/lukas-blecher/LaTeX-OCR |
| MathAgent | 论文 | 多智能体数学错误步骤检测 | https://arxiv.org/abs/2503.18132 |
| Aftermath of DrawEduMath | 论文/基准 | 11 个 VLM"错误诊断"最弱，佐证人机协同 | https://arxiv.org/abs/2603.00925 |
| Stepwise Verification & Remediation | 论文/数据集 | 1K 教师标注首错步骤 | https://arxiv.org/abs/2407.09136 |
| Algebra Error Classification | 论文 | LLM 代数错误分类超越基线 | https://arxiv.org/abs/2305.06163 |
| 可解释认知诊断新范式 | 论文 | IJCAI'21 综述 | https://www.ijcai.org/proceedings/2021/0703.pdf |
| Foundation Models for Education | 综述 | 教育大模型 Agent/RAG 架构 | https://arxiv.org/pdf/2405.10959 |
| CN110264091A | 专利 | 讯飞认知诊断方法专利 | https://patents.google.com/patent/CN110264091A/zh |
| AntV G6 | 图可视化 | 12.3k★ MIT，v5 WebGL，知识地图首选 | https://github.com/antvis/G6 |
| Taro | 小程序框架 | 37.7k★ MIT，多端小程序+H5 | https://github.com/NervJS/taro |
| Moodle / Open edX | 开源 LMS | GPL-3 7.4k★ / AGPL-3 8.2k★ | https://github.com/moodle/moodle 、https://github.com/openedx/edx-platform |
| xAPI-Spec | 标准 | ADL 学习事件标准（Statement+LRS） | https://github.com/adlnet/xAPI-Spec |
| Ralph | LRS | MIT，Python/FastAPI 学习记录库 | https://github.com/openfun/ralph |

**对本产品的落地建议**
1. **确定性内核+Agent 壳**："状态更新/查询/策略获取"定义为 REST 确定性接口；学习事件采用 xAPI Statement，LRS 起步用 Ralph；同一套接口天然支持小程序/机构系统多端。
2. **录入链**：自印卷预印 OMR 定位标记——客观题走 OMRChecker；主观题走 PaddleOCR+pix2text 输出 Markdown+LaTeX；手写公式用 pix2tex，低置信转人工，避免脏数据进知识地图。
3. **诊断内核**：每题挂 Q-matrix（知识点×难度×能力），小样本用 DINA，序列积累后叠加 DKT/AKT；"按平均画像出卷"复用 KST 选题思想（每题最大化信息量，20-30 题定状态；首份画像来源见 §6.1）。
4. **批改**：MathAgent 式多智能体初筛+首错步骤定位；按 DrawEduMath 结论设置置信度分流，主观题保留人工复核队列。
5. **可视化与分发**：学生端 ECharts graph 轻量展示，教师端 G6（Combo/WebGL）；小程序用 Taro；教培以"静态卷+xAPI 回传"优先，深度集成再考虑 Moodle/Open edX 插件。
6. **教学方式映射**：商业对手公开细节少，自建"知识点×学生画像→资源形态"策略表先冷启动，再按 Foundation Models for Education 综述的 RAG+Agent 架构演进。

---

## 4. 推荐开源组合（MVP / 进阶 / 完整）

| 模块 | MVP（最小可行） | 进阶（规模化打磨） | 完整（对标商业系统） |
|---|---|---|---|
| 诊断引擎 | EduCDM 的 DINA/G-DINA（pip，Apache-2.0） | EduCDM 与 KT 互为校验；GDINA R 包对照（GPL） | KST 路线：knowledge-spaces 改造（QUERY+BLIM/PoLIM，20-30 题定状态） |
| 序列追踪 | pyBKT（在线逐生更新、Roster 接口） | pyKT 的 simpleKT/DKT + XES3G5M 预训练微调 | AKT/IEKT/LPKT + csKT 式冷启动迁移 |
| 组卷器 | 复用 catsim 选题+自研约束装配（知识点配额+难度硬约束）；静态卷过渡用 Excel→Word 管线 | catsim 动态 CAT + girth/py-irt 校准 + shadow test 约束 + Sympson-Hetter 曝光 | cdCAT 会话式 CD-CAT 参考（v0.1.0）；MIP-ATA 按 TestDesign 思路自研实现（规避 GPL） |
| 知识图谱 | 教材目录手工知识点树 + Junyi 先序图人工校对 | K12-KGraph 骨架（数据 CC BY-NC-SA）+ LLM 先序管线+专家仲裁 | 全学科自建先序图 + XLORE 跨语言对齐 + 课标/TIMSS 双标签 |
| 题库与出题 | TAL-SCQ5K schema + CMATH/GAOKAO-Bench 题源 + 试测回填（P 值/区分度） | TDG 元模板出题管线 + LookAlike 式误区干扰项 | Eedi 式 misconception 全量标注 + EQGBench/MDK12-Bench 出卷质量评测 |
| 教学策略 | 确定性规则表 v0（提取练习基座+worked example+交错） | LearnLM 教学指令范式 + ZPD 支架维度 + Mayer 媒体合规检查 | TutorRL 式 RL 升级 + MathTutorBench 奖励模型回归评测 |
| 间隔重复 | ts-fsrs（前端）+ py-fsrs（服务端），默认参数 | 复习日志回流，binding 拟合人群参数 | 按学生/知识点个人参数训练 |
| Agent 壳 | 固定 workflow（chaining/routing，暂不上自主 agent） | LangGraph 状态机 + MCP 工具封装 + checkpoint + HITL | 多角色 orchestrator-workers + Mem0 记忆分层 + 离线策略评估 |
| 录入与批改 | OMRChecker（涂卡客观题）+ 人工录主观题 | +PaddleOCR/pix2text 主观题结构化 + 置信度分流 | VLM 批改初筛（MathAgent 式）+ 首错定位 + 人工复核队列 |
| 可视化与分发 | Taro 小程序 + ECharts graph + KaTeX SSR | 教师端 G6（Combo/WebGL） | LTI/Moodle/Open edX 机构插件（注意 GPL/AGPL 传染） |
| 数据底座 | XES3G5M 主基准 + EduData 拉取基准 | +EdNet/ASSISTments 泛化验证 + MOOCCubeX 难度先验 | 自建 LRS（Ralph 起步）+ xAPI 事件流全量回流 |

> **许可证提示（更正）**：GPL/AGPL 件（catR、GDINA、TestDesign、TAO、Moodle、Open edX）为单一 GPL 类许可、**非双重许可商品，不存在"付钱即得的商业授权"**；合规路径只有不用、进程隔离/独立部署（义务范围需法务确认）或许可兼容集成。CC BY-NC-SA（C-Eval、K12-KGraph 数据、AL-CPL）方可向权利人购买商业授权。工程策略：优先 BSD/MIT/Apache 等价物（catsim/cdCAT/EduCAT 已覆盖多数测量需求），GPL 件仅作对照实验或自研替代参照。

### 4.1 立项与定价决策缺口（材料未覆盖，立项前须补齐）

- **材料未覆盖、本报告不给估算值**：MVP 人月/工期、LLM 推理单价等 unit economics、题库版权预算、自采数据回收成本——材料均无数据，臆造会误导立项。
- 材料内仅有两个可引用参照：①DragonBox $55/生 为美国 RCT 成本核算（Finster 2024），不可直接迁移国内定价；②生成式 AI/算法备案周期约 3-6 个月（§7.1），应计入工期关键路径。
- 立项测算清单：题库版权/自建、LLM token 成本（按 MAU×频次）、备案法务、OMR/OCR 部署、三渠道资质成本、审校人力（复核队列，§7.6）。

---

## 5. 参考架构：确定性内核 + Agent 壳

**设计原则**（依据 arXiv 2512.23036（预印本，验证安排见 §7.2）、Anthropic《Building Effective Agents》、LearnLM 教学指令范式）：掌握度与一切教育决策数值由确定性模型产出；LLM 只负责内容生成、讲解与解释；Agent 经确定性接口读写，不直接改库；长流程带 checkpoint 与教师审核（HITL）。

```
              ┌─────────────────────────── 多端输出 ───────────────────────────┐
              │  微信小程序(Taro)    静态试卷PDF(exam.cls+KaTeX)    机构系统(LTI/API) │
              └──────▲────────────────────────▲───────────────────────▲────────┘
                     │ ⑤ 讲解/报告/内容          │ ③ 试卷文件            │ ⑥ 学情/策略 API
┌────────────────────┴────────────────────────┴───────────────────────┴────────┐
│                     LLM Agent 壳（LangGraph 状态机编排）                        │
│    出题Agent │ 讲解Agent(苏格拉底/脚手架/ZPD) │ 学情分析Agent │ 报告Agent          │
│    · Q-matrix 预标注 · 错因归因 · 题面多样化 · 可解释诊断报告                      │
│    · 仅经 MCP/REST 调用内核，不直接写库；checkpoint 恢复；HITL 教师审核            │
│    · Mem0 叙述记忆(偏好/情绪/交互史) ≠ 掌握度向量(由内核计算)                     │
└────────────────────────────▲─────────────────────────────────────────────────┘
                             │ ② 确定性指令：update_state / query_profile /
                             │   get_plan / generate_paper（封装为 MCP tools）
┌────────────────────────────┴─────────────────────────────────────────────────┐
│                 确定性内核（唯一写库入口，无 LLM 参与）                           │
│  ┌──────────────────┐ ┌────────────────────┐ ┌─────────────────────────┐     │
│  │ 知识本体+先序图     │ │ 学习者模型           │ │ 组卷器                    │     │
│  │ 对齐2022课标/教材   │ │ 知识点掌握度向量      │ │ 动态: CAT/CD-CAT 信息量   │     │
│  │ 版本; K12-KGraph   │ │ +作答历史事件流       │ │ 选题+shadow test 约束    │     │
│  │ 骨架+Q-matrix+KST  │ │ (xAPI Statement)   │ │ +Sympson-Hetter 曝光     │     │
│  │ 知识状态           │ │                    │ │ 静态: 平均画像 MIP-ATA    │     │
│  └──────────────────┘ └────────────────────┘ └─────────────────────────┘     │
│  ┌──────────────────┐ ┌───────────────────────────────────────────┐          │
│  │ 诊断引擎           │ │ 策略层(学习科学证据规则表,确定性,Agent不可绕过)    │          │
│  │ CD: DINA/G-DINA;  │ │ 提取练习基座(d=0.49) > FSRS 间隔复现 >        │          │
│  │ KT: simpleKT/DKT; │ │ expertise-reversal 支架调节 > Mayer 媒体合规  │          │
│  │ 小样本: pyBKT     │ │ > 游戏化仅动机托底(且须在未成年人模式合规内)      │          │
│  │                   │ │ → 学习路线 · 教学方式 · 复习排程 (get_plan)     │          │
│  └──────────────────┘ └───────────────────────────────────────────┘          │
└────────────────────────────▲─────────────────────────────────────────────────┘
                             │ ① 作答数据入口（置信度分流，低置信转人工复核）
┌────────────────────────────┴─────────────────────────────────────────────────┐
│ 录入与批改: OMRChecker(涂卡) + PaddleOCR/pix2text(主观题) + VLM 初筛(MathAgent式) │
│ 题库: TAL-SCQ5K 式 schema + P值/区分度校验闭环 + 误区标签(Eedi 式)                 │
│ 数据: XES3G5M/Junyi/EdNet/EEDI 训练底座 │ xAPI 事件流 → LRS(Ralph)              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**四个核心 REST 确定性 API**（可同时经 MCP tools 暴露给 Agent 壳）：
- `update_state`：写入作答/学习事件（xAPI Statement），触发确定性掌握度更新与 FSRS 记忆状态更新；
- `query_profile`：查询学生知识点掌握度向量、KST 知识状态、作答历史与画像；
- `get_plan`：基于策略层规则表输出学习路线、教学方式与复习排程；
- `generate_paper`：按诊断目标（动态 CAT 选题）或平均画像（静态 MIP-ATA）组卷，返回题目与蓝图合规报告。

**知识本体要求**：先序图显式外置（K12-KGraph 核心发现），对齐 2022 版课标与教材版本；每题带"中国课标知识点+TIMSS content×cognitive"双标签与 Q-matrix（知识点×难度×能力）。

---

## 6. 数据与冷启动策略

**开放数据集组合**（学科范围前提见 §1.1：现有底座均为数学/理科）

| 用途 | 首选 | 说明 |
|---|---|---|
| KT/CD 主基准 | XES3G5M | 唯一"中国 K12+题面+知识点路径"全要素公开作答集，同训 KT 与题目表征（MIT） |
| 知识点体系抽取 | Junyi Academy + XES3G5M | Junyi 自带前置图；XES3G5M 带 KC 路径；人工校对映射人教版目录（Junyi 两口径并存，经 EduData 获取） |
| 模型泛化验证 | ASSISTments/EdNet/EduData | pyKT 协议保证可比；ASSISTments2012 含隐私字段，商用前复核条款 |
| 误解诊断校准 | EEDI 两代数据 | 约 2000 万条答题 + Kaggle 误解标注（1857 题/2587 误解） |
| 难度/区分度先验 | MOOCCubeX（参考） | 35.8 万练习+2.96 亿行为预训先验；**偏高教非 K12，仅作难度先验参考、不作画像来源** |
| 中文题源 | CMATH + GAOKAO-Bench + AGIEval gaokao-* | 小学到高中，带难度/解析；C-Eval 为 CC BY-NC-SA（非商业），商用需替换或授权 |
| 出题 schema | TAL-SCQ5K 字段 | 题面/选项/解析/粗到细知识点路由/难度 0-4（MIT） |
| 知识图谱底座 | K12-KGraph（数据 CC BY-NC-SA） | 人教版对齐，商用需授权或以同管线自建 |

**课标映射路线**：教育部 2022 版 16 科课标 PDF → 解析为知识点树 → 对照 K12-KGraph 骨架校准 → 外国资源先挂 CASE/CCSS/TIMSS 元数据 → LLM 做"美标→中文知识点树"映射 → 专家抽检（纯检索 F1 仅 0.55）。

**题库冷启动流水线**：按 TAL schema 建库 → 新题按"平均画像"小样本试测 → P 值（0.3-0.7）与点二列区分度（≥0.2）达标回填，未达标进隔离区 → MCQ 错选项用 LLM 预标 Eedi 式误解标签再人工校验。

### 6.1 冷启动循环依赖的启动顺序（建议方案）

- **循环所在**：静态 MIP-ATA 需要"历史学员能力分布"组卷；新题回填 P 值/区分度需要真实作答；上线初两者皆无，而 MOOCCubeX 先验偏高教、不能充当 K12 画像。
- **启动顺序（建议）**：①题参冷启动复用已校准数据——XES3G5M 自带 500 万交互校准与嵌入、EEDI 难度/误解先验，首批题库优先由此改编；②首批组卷退化为"固定蓝图卷"：按知识点×难度配额的名义分布组卷（不依赖学员分布），对种子班/合作机构样本回收作答（种子获客渠道材料未覆盖），估计首份平均画像；③画像成形后切换 MIP-ATA 与 CD-CAT；④新题试测挂靠同批种子样本。
- 首份画像的人群代表性材料未覆盖，上线后以实际作答滚动重估；成本与预算缺口见 §4.1。

---

## 7. 风险与开放问题

### 7.1 政策与合规（主题材料未覆盖，补充调研覆盖；上线硬门槛，适用项因 §1.1 渠道选择而异）
1. **双减与校外培训监管**：《关于进一步减轻义务教育阶段学生作业负担和校外培训负担的意见》（2021-07）：不再审批新的义务教育阶段学科类机构；线上学科类培训改审批制；课时不超 30 分钟、不晚于 21 点；**禁止"拍照搜题"**。诊断服务按学科类培训售卖须挂靠资质机构。2024-2026 监管常态化，AI 学习机/智能家教相对友好（2026-05 学而思×信通院牵头智能家教标准）。来源：https://www.gov.cn/zhengce/2021-07/24/content_5627132.htm
2. **生成式 AI 与算法备案（Agent 壳上线必经）**：《生成式人工智能服务管理暂行办法》2023-08-15 施行（已抓全文核实）：涉舆论属性服务须安全评估+算法备案（第 17 条）；防未成年人过度依赖（第 10 条）；训练数据须合法（第 7 条）。流程：算法备案 → 生成式 AI 备案（约 3-6 个月）→ 安全评估，并按《人工智能生成合成内容标识办法》标识。来源：https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm
3. **未成年人个人信息保护**：PIPL 将不满 14 周岁未成年人信息列为敏感个人信息，须监护人（单独）同意；《未成年人网络保护条例》（国令 766 号，2024-01-01 施行，已抓全文核实）要求最小必要、不得因拒绝非必要授权而拒绝基本服务、每年合规审计——线下纸质卷回传的作答与画像同样落入该范畴。来源：https://www.gov.cn/zhengce/content/202310/content_6911288.htm
4. **未成年人模式与适龄要求（直接约束游戏化设计）**：《移动互联网未成年人模式建设指南》（2024-11-15，已抓全文核实）：三方联动，分龄推荐；不满 16 周岁默认每日 1 小时、22-6 时停服；在线教育产品不得插入游戏链接、推送广告。游戏化须以机制激励（积分/进度/即时反馈）而非游戏内容实现。来源：https://www.cac.gov.cn/2024-11/15/c_1733364304749288.htm
5. **分发渠道准入资质**：小程序教育-学历教育类目需区县教育部门《民办学校办学许可证》+主体证明；非学科类四选一（含全国校外教育培训监管平台备案）；个人主体仅可"教育信息展示"不可售课。教育 App 另需教技函〔2019〕55 号备案（2020-02 起未备案不得进校）。来源：https://developers.weixin.qq.com/miniprogram/product/material/

### 7.2 技术风险
- **LLM 直接估计掌握度不可靠——当前依据为单一预印本**：arXiv 2512.23036（DKT AUC 0.83 胜出；2025-12 提交、未经同行评审，"微调后仍低 6%"未注明是 AUC 百分点还是相对值）。该结论与 KCD/LKT"LLM 提语义、模型出概率"范式互证，混合框架本身也是低风险选择，故**可作为默认架构采纳；但应复现该文或补第二来源（自有 A/B、同类基准如 MathTutorBench）后再固化为不可动摇的铁律**；
- **VLM 批改"错误诊断"仍是短板**（DrawEduMath aftermath）——全自动批改不成立，需置信度分流+人工复核队列；
- **深度 KT 模型 <10 万交互易过拟合**——线下教培小数据场景用 pyBKT/G-DINA；
- **纯检索课标对齐 F1 仅 0.55**——跨国映射必须 LLM 确认+专家抽检双保险；
- **"答对即懂"陷阱**（Correct Answer Trap）——诊断卷需含过程性证据与错因标注；
- **教学分与解题分相关性仅 0.421**（MathTutorBench）——评测须分开报告；
- **零样本教学提示损害事实性**（LearnLM 实测）——讲解走 LLM、事实走内核/RAG，并对数学错误显式校验+免责。

### 7.3 数据与许可风险
- GPL/AGPL 传染：catR、GDINA、TestDesign、TAO、Moodle（GPL-3）、Open edX（AGPL-3）——**单一许可、无商业授权可购**，闭源商用需规避（进程隔离/自研替代）或许可兼容集成（见 §4 提示）；
- CC BY-NC-SA 非商业：C-Eval 数据、K12-KGraph 数据、AL-CPL——商用需向权利人购买授权或重建；
- AGIEval 遵循原考试出处许可；ASSISTments2012 含隐私敏感字段需复核条款；
- XES3G5M 仓库 61★ 更新少，长期维护存在不确定性；Junyi 交互量两口径并存（见 §7.5）。

### 7.4 商业情报与开源缺口（材料未覆盖/未找到，如实记录）
- 好未来 MathGPT、作业帮大模型无公开技术论文；智学网无公开架构文档；Duolingo Max 无同行评审效果研究；松鼠AI 细节仅媒体评测与综述转述；
- Caliper 无活跃开源 LRS（OpenLRW 已停更）；open learner model 无活跃开源实现（仅 xAPI/LRS 与 pyKT 数据结构可参照）；
- "外国资源→中国课标"现成映射数据集不存在，需自建；
- 面向诊断目标的组卷编排无现成成品，但选题/ATA 有开源积木（catsim/cdCAT/EduCAT；TestDesign 为 GPL），真实缺口是约束装配层（§1.5）；
- 目标客户/商业模式、成本与 unit economics、验收阈值中的自定项均材料未覆盖（§1.1/§4.1/§7.6）。

### 7.5 未核实清单（原始检索受限，均如实记录）
PISA 2022 数学框架（OECD 被 Cloudflare 拦截）；Khan Academy/OER Commons 映射数据（反爬）；MathGraph 与 CourseKG 一手页面未打开；精确同名 MathKG 未检索到；CoMTA 数据集 arXiv 无收录（来源强度有限）；Kahoot! Wang & Tahir 2020 综述、Dunlosky 2013 技术评级、Kulik 1990 元分析原文 URL 未取得；TAL-SCQ5K 的 5K/3K+2K 划分未在 HF 页直接显示；cdCAT 的 `CdcatSession` 方法名未在 CRAN 页直接展示；K12-KGraph 的 NeurIPS 2026 D&B 发表信息未在 GitHub 页直接核实；Junyi Kaggle 下载页与 CMATH 官方 GitHub 404 未核实，Junyi 交互量两口径（约 2590 万/1600 万+）并存未裁定，取数以 EduData 下载为准；清华 CD-CAT 文章抓取超时（信息取自检索摘要）；irtplay 已从 CRAN 移除（2022-09-13，版权原因），不可作基座。

### 7.6 验收标准与成功指标（建议框架；★=有材料依据，其余为建议阈值、须 owner 立项时确定）
- ★**题库准入**：新题试测 P 值 0.3-0.7、点二列区分度 ≥0.2 方回填题库，未达标进隔离区（§3.3）。
- ★**诊断收敛**：KST 路线 20-30 题内知识状态收敛（§3.4）；CDM 路线小样本可辨识（§3.1）。
- ★**模型回归基线**：KT 模型按 pyKT 协议在 XES3G5M 上复现公开指标作为回归线（材料数据点：DKT AUC 0.83，arXiv 2512.23036，预印本）。
- **诊断一致性（材料无数值，须自定）**：掌握判定与教师抽样判定一致率阈值；校准误差（如 ECE）上限。验证：抽样双盲比对教师判定；诊断证据须含过程性证据与错因标注（防"答对即懂"漏诊）。
- ★**策略上线**：新教学策略以 d=0.40（hinge point）为 ROI 对照线 A/B；教学分与解题分分开报告（MathTutorBench：相关性 0.421）。
- **批改（材料无数值，须自定）**：VLM 批改置信度分流阈值与人工复核率上限；复核队列清零时长目标。

---

## 8. 参考资料总表（分主题，全部 URL）

**认知诊断与知识追踪**：https://github.com/pykt-team/pykt-toolkit ｜ https://github.com/bigdata-ustc/EduCDM ｜ https://github.com/bigdata-ustc/EduData ｜ https://github.com/CAHLR/pyBKT ｜ https://github.com/ai4ed/XES3G5M ｜ https://www.jstatsoft.org/article/view/v093i14 ｜ https://arxiv.org/abs/2302.06881 ｜ https://ojs.aaai.org/index.php/AAAI/article/view/31992 ｜ https://arxiv.org/abs/2406.02893 ｜ https://dl.acm.org/doi/10.1145/3746252.3761321 ｜ https://arxiv.org/html/2510.22559v1 ｜ https://arxiv.org/abs/2407.05458 ｜ https://github.com/GeminiLight/awesome-ai-llm4education ｜ https://arxiv.org/abs/2512.23036

**自适应测验与教育测量引擎**：https://github.com/douglasrizzo/catsim ｜ https://github.com/philchalmers/mirtCAT ｜ https://www.jstatsoft.org/v48/i08 ｜ https://cran.r-project.org/web/packages/TestDesign/index.html ｜ https://cran.r-project.org/web/packages/cdCAT/index.html ｜ https://wenchao-ma.github.io/GDINA/ ｜ https://github.com/bigdata-ustc/EduCAT ｜ https://ojs.aaai.org/index.php/AAAI/article/view/20399 ｜ https://arxiv.org/abs/2404.00712 ｜ https://pubmed.ncbi.nlm.nih.gov/34341914 ｜ https://link.springer.com/article/10.1007/s41237-021-00150-y ｜ https://journals.sagepub.com/doi/10.3102/10769986029003273 ｜ https://github.com/oat-sa ｜ https://brain.tsinghua.edu.cn/info/1005/1520.htm

**自动出题与题库工程**：https://huggingface.co/datasets/math-eval/TAL-SCQ5K ｜ https://github.com/OpenLMLab/GAOKAO-Bench ｜ http://proceedings.mlr.press/v133/wang21a/wang21a.pdf ｜ https://arxiv.org/abs/2411.18104 ｜ https://arxiv.org/abs/2505.01903 ｜ https://arxiv.org/abs/2508.11184 ｜ https://arxiv.org/abs/2306.09064 ｜ https://arxiv.org/abs/2211.12835 ｜ https://arxiv.org/abs/2402.18267 ｜ https://arxiv.org/abs/2510.22559 ｜ https://dl.acm.org/doi/10.1145/3556538 ｜ https://arxiv.org/abs/2601.09953 ｜ https://arxiv.org/abs/2511.01526 ｜ https://www.winsteps.com ｜ https://ctan.org/pkg/exam ｜ https://github.com/KaTeX/KaTeX ｜ https://github.com/mikemelon/java-exam ｜ https://github.com/cppcpp/exam-system ｜ https://github.com/wukai0909/Generating-WORD-Test-Papers-from-Excel-Question-Bank

**K-12 知识图谱与知识空间**：https://arxiv.org/abs/2605.09635 ｜ https://github.com/haolpku/K12-KGraph ｜ https://github.com/vanderbilt-data-science/knowledge-spaces ｜ https://github.com/harrylclc/AL-CPL-dataset ｜ https://github.com/THU-KEG/MOOCCubeX ｜ https://doi.org/10.1145/3733593 ｜ https://ojs.aaai.org/index.php/AAAI/article/view/32156 ｜ https://dl.acm.org/doi/10.1145/3627673.3679597 ｜ https://www.mdpi.com/2504-4990/7/3/103 ｜ https://arxiv.org/html/2504.12915v2 ｜ https://arxiv.org/abs/2505.13406 ｜ https://www.aleks.com ｜ https://ieeexplore.ieee.org ｜ http://www.edukg.cn ｜ https://xlore.cn

**开放教育数据集**：https://sites.google.com/site/assistmentsdata ｜ https://github.com/riiid/ednet ｜ https://arxiv.org/abs/2007.12061 ｜ https://www.eedi.com/news/from-wrong-answers-to-real-insights-how-we-used-a-kaggle-challenge-to-map-student-misconceptions ｜ http://moocdata.cn/data/MOOCCube ｜ http://moocdata.cn/challenges/kdd-cup-2015/ ｜ https://huggingface.co/papers/2306.16636 ｜ https://github.com/ruixiangcui/AGIEval ｜ https://github.com/hkust-nlp/ceval ｜ https://pykt-toolkit.readthedocs.io/en/latest/ ｜ https://huggingface.co/datasets?other=k12

**跨国课程标准映射与资源对齐**：http://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html ｜ https://huggingface.co/datasets/lhpku20010120/K12-KGraph ｜ https://arxiv.org/abs/2508.06851 ｜ https://github.com/LanceZPF/MDK12 ｜ https://arxiv.org/abs/2407.12023 ｜ https://arxiv.org/abs/2210.12228 ｜ https://www.imsglobal.org/spec/case/v1p0 ｜ https://casenetwork.imsglobal.org/ ｜ https://www.gov.uk/government/collections/national-curriculum ｜ https://timss2023.org/frameworks/ ｜ https://arxiv.org/abs/2606.19469 ｜ https://arxiv.org/abs/2608.05910 ｜ https://arxiv.org/abs/2607.28647 ｜ https://arxiv.org/abs/1905.11605 ｜ https://arxiv.org/abs/2001.08728 ｜ https://github.com/ECNU-ICALK/EduChat ｜ https://arxiv.org/abs/2508.10005 ｜ https://openstax.org/details/books/prealgebra ｜ https://www.khanacademy.org/commoncore ｜ https://www.oercommons.org/

**智能导师系统与 LLM 导师**：https://www.khanmigo.ai/ ｜ https://arxiv.org/abs/2412.16429 ｜ https://arxiv.org/abs/2407.12687 ｜ https://arxiv.org/abs/2410.03017 ｜ https://github.com/eth-lre/PedagogicalRL ｜ https://arxiv.org/abs/2502.18940 ｜ https://arxiv.org/abs/2402.05000 ｜ https://arxiv.org/abs/2511.08873 ｜ https://arxiv.org/abs/2605.29582 ｜ https://arxiv.org/abs/2609.23088 ｜ https://arxiv.org/abs/2308.02773 ｜ https://github.com/JushBJJ/Mr.-Ranedeer-AI-Tutor ｜ https://openreview.net/pdf?id=UoJZv2YfDX ｜ https://discover.carnegielearning.com/livehint-ai ｜ https://www.aleks.com/about_aleks ｜ https://m.bjnews.com.cn/detail/1721802964168204.html ｜ https://www.stdaily.com/web/gdxw/2025-06/25/content_360337.html ｜ https://mt.sohu.com

**教育 Agent 工程架构**：https://docs.langchain.com/oss/python/langgraph/overview ｜ https://github.com/openai/openai-agents-python ｜ https://github.com/microsoft/autogen ｜ https://github.com/modelcontextprotocol ｜ https://github.com/mem0ai/mem0 ｜ https://github.com/letta-ai/letta ｜ https://github.com/microsoft/graphrag ｜ https://github.com/CAHLR/OATutor ｜ https://arxiv.org/abs/2601.17346 ｜ https://arxiv.org/abs/2605.23925 ｜ https://arxiv.org/abs/2607.23481 ｜ https://www.qbitai.com/2025/11/349266.html ｜ https://www.anthropic.com/research/building-effective-agents

**学习科学与教学策略**：https://github.com/open-spaced-repetition/ts-fsrs ｜ https://github.com/open-spaced-repetition ｜ https://doi.org/10.1145/3534678.3539081 ｜ https://github.com/open-spaced-repetition/fsrs4anki/wiki/Research-resources ｜ https://doi.org/10.3102/0013189X013006004 ｜ https://journals.sagepub.com/doi/abs/10.3102/0034654316689306 ｜ https://doi.org/10.1037/0033-2909.132.3.354 ｜ https://doi.org/10.1037/bul0000209 ｜ https://www.visiblelearningmetax.com/influences/view/practice_testing ｜ https://link.springer.com/article/10.1007/s10648-023-09842-1 ｜ https://www.sciencedirect.com/science/article/pii/S0959475225000660 ｜ https://psycnet.apa.org/record/2008-00316-006 ｜ https://doi.org/10.1037/a0021017 ｜ https://pmc.ncbi.nlm.nih.gov/articles/PMC10125888 ｜ https://www.tandfonline.com/doi/abs/10.1080/19345747.2023.2269918 ｜ https://bera-journals.onlinelibrary.wiley.com/doi/10.1111/bjet.13304 ｜ https://doi.org/10.1007/s10648-019-09498-w ｜ https://pmc.ncbi.nlm.nih.gov/articles/PMC9957048

**商业产品对标与工程选型**：https://github.com/udayraj123/OMRChecker ｜ https://github.com/PaddlePaddle/PaddleOCR ｜ https://github.com/breezedeus/pix2text ｜ https://github.com/lukas-blecher/LaTeX-OCR ｜ https://arxiv.org/abs/2503.18132 ｜ https://arxiv.org/abs/2603.00925 ｜ https://arxiv.org/abs/2407.09136 ｜ https://arxiv.org/abs/2305.06163 ｜ https://www.ijcai.org/proceedings/2021/0703.pdf ｜ https://arxiv.org/pdf/2405.10959 ｜ https://patents.google.com/patent/CN110264091A/zh ｜ https://github.com/antvis/G6 ｜ https://github.com/NervJS/taro ｜ https://github.com/moodle/moodle ｜ https://github.com/openedx/edx-platform ｜ https://github.com/adlnet/xAPI-Spec ｜ https://github.com/openfun/ralph

**政策与合规（补充调研）**：https://www.gov.cn/zhengce/2021-07/24/content_5627132.htm ｜ https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm ｜ https://www.gov.cn/zhengce/content/202310/content_6911288.htm ｜ https://www.cac.gov.cn/2024-11/15/c_1733364304749288.htm ｜ https://developers.weixin.qq.com/miniprogram/product/material/
