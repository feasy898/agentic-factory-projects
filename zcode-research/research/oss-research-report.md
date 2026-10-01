# 开源能力与课程交付调研报告（2026-09）

> **数据与口径说明**：本报告全部基于 2026-09 完成的 6 份人群调研（开店的人、公司打工人、做图片的人、做视频的人、做自媒体的人、想自己搭工具的超级个体）与 4 份专题调研（Agent 观测与治理生态、云上 Agent 手册范式、能力封装通道生态、AI 课程市场与竞品）的结果撰写，不新增调研外事实。调研中标注「未核实」的数据点本报告沿用该标注。本次调研记录的「失败的调研路」为空——即没有记录在案的失败路径；但个别子项（如豆包开放插件平台、coze.cn 官方发布流程、Devin 定价页）因 403/SPA 渲染等原因未获一手核实，正文中如实标注。
>
> **判断基准（写进所有课程设计）**：
> 1. 免费 = 单点能力（引流），付费 = 端到端成果（可验收的交付物，不是知识点）。
> 2. 高级产品 = 完整 agent + 工具与基础设施，按阿里云 AI Agent Handbook 范式组件化交付。
> 3. 用户主动选择被观测（consent-first），换取 skill 持续升级权益；轨迹回流驱动产品迭代（agentsight 模式）。
> 4. 能力封装的目标渠道是大厂通用 agent（调研已核实的国内通道：腾讯 WorkBuddy、Qoder、字节 TRAE 等；判断基准中提到的「豆包工作」未在调研中获得可核实证据——豆包独立开放插件平台未搜到证据，详见 §3.3）。
>
> **选课优先级**：开源资产链最完整 > 观测闭环接得上 > 市场已验证付费意愿。
>
> **术语白话对照（给非技术读者，正文术语以本表为准）**：
> - **agent（大模型助手）**：能自己拆解任务、调用工具、多步完成的 AI 程序——Claude、豆包、TRAE 这类产品的底层形态。
> - **skill（技能）/ SKILL.md**：教 agent「会做某件事」的说明书文件夹（核心是一个 SKILL.md 文件+可选脚本模板），装进 agent 即可被调用——可理解为「给 AI 装的 App」。
> - **MCP / MCP server**：让 agent 安全调用外部工具的标准插头。把抠图、录音转文字这类能力做成 MCP server，任何品牌的 agent 都能即插即用。
> - **产线**：从「丢进原材料」到「拿出成品」自动跑完的一串工具组合，例如「录音进→纪要出」。
> - **OTel / OTLP / GenAI span**：一套行业通用的「行车记录仪」数据格式——把 agent 每步干了什么、花多久、成没成功记成统一格式的记录（span），经标准通道（OTLP）发给任何记账系统。
> - **Langfuse**：开源的「记账系统」，装在学员自己的电脑/服务器上即可存上述记录。
> - **agentsight 观测闭环**：我们规划中的产品模式——学员自愿分享使用记录，换取技能免费持续升级。
> - **Agent Release 六要素**：交付一个生产可用 agent 的六件套清单（模型、编排逻辑、提示词与技能版本、工具与权限、运行环境、评估基准），保证交付物可复现、可验收。
> - **consent-first**：「先同意、再共享」——默认什么都不外传，学员显式打开开关才共享。
>
> **给学员的观测说明（白话，适用于本报告所有课程）**：① 产线默认只在你自己的电脑上运行，我们看不到任何东西。② 若你愿意打开「分享使用记录」开关，我们看到的只是运行记录：哪个工具被调用、每步耗时、成功还是失败；**默认不含你的录音、文件、稿件内容**——内容级日志是另一个独立开关，默认关闭（该机制沿用 Claude Code 官方遥测「默认脱敏+逐项显式开启」的成熟做法，见 §3.1）。③ 作为交换，你免费收到据此改进的新版技能。④ 不打开开关：所有功能完全一样，只是拿不到免费升级；随时可关。

---

## 1. 执行摘要

**核心结论一：开源资产已足以支撑「付费=端到端成果」的课程模式，但各链路强度分档。** 六个人群资产表合计 87 行条目（跨人群重复计入：FunASR、rembg、ComfyUI、Dify、GPT-SoVITS、MoneyPrinterTurbo、n8n、browser-use、CowAgent、whisperX、social-auto-upload 等在多表出现，去重后约 73 项）。其中**短视频量产与会议纪要两条链每一环均有 10k★ 级且活跃维护的项目**；汇报 PPT 链核心组件体量明显更小（PPTAgent 5.1k★、PPTist 9.4k★、excel-mcp-server 4.2k★ 且 v1.0 发布于调研当日，见 §2.2），内容选题雷达链则受采集合规与公众号数据断裂制约（§2.5）——后两条链可用，但需 fork 自维护与合规改造，不享受「每一环 10k★」的强度。真正的空白不在单点能力，而在**行业编排层**——把单点积木串成小店老板/打工人/创作者开箱即用的产线，这正是「免费送单点、付费交付端到端」的商业空间（§2 各人群空白、§3.4）。

**核心结论二：「用户主动被观测换技能升级」的闭环没有先例，但全部技术件已就绪。**（白话：我们想让学员自愿分享产线的「使用记录」来换取技能免费升级——所需每个零件都有现成开源品，缺的只是把它们串起来并取得学员信任。）Langfuse（35.1k★，MIT，可装在学员自己服务器上的开源「记账系统」）提供 user/session 标识、用户反馈 API 与 OTLP 端点；Claude Code 原生 OTel 导出给出「默认脱敏+显式开关」的同意机制范式；OTel GenAI 语义约定是后端无关的事实汇合点。consent 层与「轨迹→数据集→技能升级→权益兑现」管道是纯自研环节，也是差异化所在（§3.1）。注意：eunomia-bpf/AgentSight（710★，arXiv 论文）与自有 agentsight 撞名，需先做品牌区隔。

**核心结论三：课程市场的信任真空利好「按成果付费」。** 中文 AI 课三级漏斗（199 元引流→3980-7980 训练营→9800-19800 陪跑）已发生信任崩塌（李一舟 199 元课销售额约 5000 万后被下架；录播+机器人答疑完课率 <10%——上述市场数字均为 WebSearch 聚合来源、原文未逐一访问核实，明细与出处见 §3.4）；知识本身已被免费内容全覆盖（DeepLearning.AI 107 门免费短课、hello-agents 81.1k★、llm-course 83.2k★）。付费点只能落在「交付/验收/担保」上，与雇主「把 AI 能力封装为 agent 技能」的方向完全同构（§3.4）。

### 首批建议课程（按推荐优先级排序）

| # | 课程 | 你下课带走什么（验收口径） | 门槛 | 成立理由（供给侧） |
|---|---|---|---|---|
| 1 | 日更短视频量产产线 + 调度 Agent | 一条自己的产线：丢进选题清单，自动出配音字幕齐的成片与发布草稿（**最后一键发布由你人工确认**——各平台未向第三方开放全自动接口）；当天现场 ≥10 条成片进 ≥2 个平台草稿箱 | 会用电脑；能装 Docker 的电脑/服务器（课程提供部署包）；GPU 可选，无 GPU 走云端 API 降级 | 资产链五环全部 10k★+ 且活跃（MoneyPrinterTurbo 126.5k / GPT-SoVITS 62.2k / whisperX 24.3k / yt-dlp 194k / social-auto-upload 15.2k）；付费意愿为未验证假设，靠免费层先行验证（见课程一详述） |
| 2 | 会议纪要一条龙产线 | 一条私有化产线：拖入会议录音，几分钟出分发言人 Word 纪要（合规格式）+待办自动催办；现场用你的真实录音跑通 | 会用电脑；一台能跑 Docker 的普通电脑即可，全程数据不出本机 | 资产最稳（FunASR 官方 MCP / 微软 MarkItDown 187k★ / n8n 206k★）；观测闭环最好接（转写→生成→催办每步可打点）；数据不出本机是录音/工资表等敏感场景的刚需 |
| 3 | 门店短视频内容工厂 | 每天自动出 30 条用你自己声音配音的菜品/商品短视频+7 天排期表（**发布动作人工执行**——课程明示边界）；录入 10 个 SKU 现场验收 | 零技术门槛：课程方交付一键部署包，店主只填菜单/价目/卖点+5 秒声音样本 | 与课程一共享 5 个核心组件，边际开发集中在行业模板；本地生活痛点已获媒体验证（小店「开播难、成本高」）；店铺资产（菜单/价目/卖点/音色）独立治理是差异化 |
| 4 | 月度汇报生成器 | 一套汇报生成器：指向你的 Excel 台账文件夹，出套用你公司模板的可编辑 PPT+一页 Word 摘要；现场用你的真实模板验收「在真 PowerPoint 里不跑版」 | 会用电脑；本机即可（无需安装 Excel/Office，课程提供在线改稿入口） | 需求普适（§2.2 需求②）；「公司 VI 模板保真」是调研确认的开源空白；但核心组件体量小（PPTAgent 5.1k★ / PPTist 9.4k★ / excel-mcp-server 4.2k★），需 fork 预案——这是它排第四的原因 |
| 5 | 一份 SKILL.md，五个货架：agent 技能封装工坊 | 3 个你自己做的 AI 工具（网页转 Markdown / 替你操作网站 / 把软件变成命令行工具），打包成标准技能并现场上架 GitHub+国内市场，在两个不同品牌的 agent 里调用成功 | **需技术背景：命令行+基础 Python——本课不适合零技术读者，请选课程一至四** | 资产一线活跃（anthropics/skills 178.8k / FastMCP 27.9k / Crawl4AI 84.4k）；WorkBuddy 2026-09-02 刚上线，占位成本低；战略价值：课程产物即雇主产品线活样本。注意：五个货架均未验证变现（见课程五详述） |

**排序口径与首发开发顺序的说明**：上表为「推荐优先级」——按判断基准（资产链完整度 > 观测闭环 > 市场付费意愿）对市场潜力排序，课程一居首。**首发开发顺序**是另一回事：工程上先做课程二（资产最稳、观测闭环最好接，其 Docker/MCP 组件直接复用为产品线底座），再在其骨架上做课程一/课程三（见 §5.4.1）。两序分叉的原因：优先级押市场潜力，开发序押工程风险，不矛盾。

**「做自媒体的人」整组未进首批的原因（明确交代，非优先级舍弃）**：该人群三个端到端候选（选题台/长文产线/周复盘）卡在资产与合规两侧——公众号数据采集已实质断裂（wechat-article-exporter 约 13k★ 于 2026-07-30 归档，无活替代）、「数据→归因→排期」复盘层无开源平替、采集主力 MediaCrawler 免责声明禁止商业用途（§2.5 空白①②、§5.3.2）。属「资产侧暂不成立+合规风险」而非排序靠后；建议先补两项调研（小红书侧合规采集平替、发布自动化运维成本实测）再评估开课。

**商业模型与定价建议**：每门课的免费层 = 单点 MCP/skill（引流+建立「能用」的信任）；付费层 = 端到端产线+验收清单+私有化部署包；高级层 = 完整 agent Release（按手册六要素版本化）+ agentsight 轨迹回流的 skill 持续升级订阅。**定价区间建议（本报告基于 §3.4 价格锚点的推演，非调研事实，待定价验证）**：调研锚点为 199 元引流带 / 3980-7980 元差评集中带 / 9800-19800 元高端陪跑带，且 §3.4 明确建议避开中间带、往「成果交付」或「低价工具化」两端走。据此建议：免费层 0 元（单点能力全送）；付费产线课落在 **199-1999 元** 低价带（薄定价+规模化，靠部署包与验收清单区别于免费教程）；高级层不做一次性高价，改为**按月订阅或按成果计价**（对齐 Lovable credits 模式，见 §3.4），订阅内容为「技能持续升级+产线运维支持」。各门课的具体价格待免费层引流数据（下载/调用/转化率）出来后确定。

---

## 2. 人群 × 需求 × 开源资产地图

### 2.1 开店的人（实体小店：餐饮/零售/美容美发 + 线上电商卖家）

**画像与核心需求**：缺人缺时间是核心难点（观察者网称小店「开播难、成本高、效果差」）。八类需求：① 为抖音/美团/点评产出门店短视频与图文引流内容；② 商品主图/菜单图制作翻新（白底图/场景图/去水印/多平台尺寸）；③ 短视频带货批量生产（MoneyPrinterTurbo 126k★ 印证需求规模）；④ 微信私域 7x24 自动客服问答；⑤ 评价与口碑管理（差评预警/卖点提炼）；⑥ 选品比价与供货价监控；⑦ 记账对账（小票/发票识别入账——搜索确认无现成开源方案）；⑧ 会员营销物料批量产出（poster-design 5000+ 开发者使用印证）。

**资产表**：

| 资产（URL） | 成熟度 | 能力 | 封装路径 | 许可 |
|---|---|---|---|---|
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 126.5k★ / 954 提交，个人开发者持续活跃，README 已更新至支持 AI Agent 集成 | 主题关键词→文案/素材/配音/字幕/BGM/合成，竖屏横屏批量 | 已内置 Agent Skill 文档，直接整理成 skill 分发，再用其 FastAPI 做服务化底座 | MIT |
| [Dify](https://github.com/langgenius/dify) | 157k★ / 13,699 提交，官方团队极活跃，有云服务/企业版支撑 | 可视化 LLM 应用平台：工作流/RAG/Agent/模型管理/全量 API | Docker Compose 自托管 + 预置行业工作流模板（DSL 导入），产出「一键导入的客服工作流包」 | Dify OSL（Apache-2.0 附加：多租户/去 LOGO 受限） |
| [FastGPT](https://github.com/labring/FastGPT) | 29.8k★ / 3,519 提交，labring（Sealos 团队）活跃 | 知识库问答与 Agent 构建平台 | 自托管 + 预置「小店客服」应用模板（FAQ 数据集+工作流）；亦可用 OpenAPI 包成 MCP 工具 | FastGPT OSL（可作后台服务商用，禁提供 SaaS，商用保留版权） |
| [CowAgent（原 chatgpt-on-wechat）](https://github.com/zhayujie/chatgpt-on-wechat) | 47.1k★ / 3,113 提交，v2.1.9（2026-09-14）仍发版，LinkAI 提供企业服务 | 全渠道 AI 助手：微信公众号/企微/飞书/钉钉/QQ/TG 等，多模型+知识库+工具调用 | 官方已支持 MCP 与技能市场——做「开店行业技能包」（菜单问答+转人工+订单查询）挂进技能市场 | MIT |
| [rembg](https://github.com/danielgatis/rembg) | 24.9k★ / 554 提交，活跃（要求 Python≥3.11） | AI 去背景/抠图：CLI 单图与批处理、Python API、HTTP 服务、Docker | 官方自带 HTTP server，社区已有 Rembg MCP Server 方案；注意默认模型 bria-rmbg 商用付费，需换开源权重 | MIT（代码）；内置模型权重各有协议 |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 135.3k★ / 6,028 提交，Comfy-Org 周度发版 | 节点式生成/编辑引擎（SD/Flux/Qwen-Image-Edit 等）：生成、inpaint、蒙版合成、上采样 | 工作流 JSON 固化——「商品场景图/菜品氛围图」预制工作流模板，经其 API 暴露给 MCP server | GPL-3.0 |
| [IOPaint](https://github.com/Sanster/IOPaint) | 23.3k★ / Apache-2.0，但 **2025-08-13 已归档只读** | 图像修复与外扩：去水印、删多余物体、超分，pip 即用、支持 CLI 批处理 | fork/镜像 + CLI 批处理脚本封装进图像流水线，不建议单独做对外服务 | Apache-2.0 |
| [poster-design（迅排设计）](https://github.com/palxiao/poster-design) | 4.9k★ / 401 提交，个人维护，另有付费企业版（20+ 企业客户） | 仿稿定的在线海报编辑器：模板+拖拽+服务端出图（Puppeteer），2.0 内置 AI 生图/文案/抠图 | 「带小店模板库的托管实例 + 出图 API」；模板可程序化注入供 agent 生成 | AGPL-3.0（商用二开注意传染性） |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 62.2k★ / 1,050 提交，RVC-Boss 持续迭代（V2/V3/V4/V2Pro） | 少样本中文语音克隆：5 秒零样本、1 分钟微调，中英日韩粤 | 自带 API 服务——包成 MCP 工具（text→speech），做产线统一配音节点 | MIT |
| [FunASR](https://github.com/modelscope/FunASR) | 20.5k★ / 5,944 提交（v1.4.16），阿里达摩院 ModelScope 维护 | 工业级中文 ASR：离线/流式、VAD、标点、说话人分离，中文字错率约为 whisper.cpp 三分之一 | 官方原生支持 OpenAI 兼容与 MCP 部署——直接暴露成 MCP server | MIT（源码）；预训练权重单独授权 |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) | 90.3k★ / 6,927 提交（3.7.0），百度官方极活跃 | OCR 与文档 AI：图片/PDF→结构化 Markdown/JSON，PP-StructureV3 与 KIE | Python 库+CLI——包成 MCP server（image→结构化 JSON）给记账 agent 调用 | Apache-2.0 |
| [changedetection.io](https://github.com/dgtlmoon/changedetection.io) | 34.6k★ / 2,559 提交，活跃（开源 + $8.99/月 SaaS 混合） | 网站变更监控：价格/库存、JSONPath 提取、上下限触发、TG/微信 webhook 通知、AI 自然语言设规则 | Docker 自托管 + webhook 联动——「盯价→通知」包成 MCP server 或定时工作流模板 | Apache-2.0 |
| [uer/roberta-base-finetuned-dianping-chinese](https://huggingface.co/uer/roberta-base-finetuned-dianping-chinese) | 月下载约 3,618；训练自大众点评评论，模型较老无近期更新 | RoBERTa 中文情感二分类，pipeline 三行代码可用 | transformers pipeline 封 API/MCP，作评价分析管线第一道粗筛，再交 LLM 做卖点/归因提炼 | 未知（HF 页面未标注） |

**端到端候选（调研原文）**：
1. **门店短视频内容工厂（含调度 agent）**——录入菜品照片+价目+卖点后，每天自动生成 30 条带配音字幕的短视频成片和排期发布表；另有一个能听懂「这周主推毛肚，出 10 条强调性价比的」指令、自动调参重跑的 agent。栈：MoneyPrinterTurbo、GPT-SoVITS、rembg、FunASR。
2. **7x24 私域客服机器人 + 差评哨兵**——跑在微信公众号/企微上的客服机器人（知识库含菜单/营业时间/售后政策，答不了转人工）+ 评价管线（情感分类、差评即时预警、回复话术草稿）。栈：CowAgent、FastGPT、uer/roberta、Dify。
3. **商品图/菜单图一键翻新流水线**——手机拍一张照片→自动抠图→AI 场景背景生成→水印杂线清理→套模板输出电商主图/菜单图/朋友圈海报三套成品（含 10 套定制模板库）。栈：rembg、ComfyUI、poster-design、IOPaint。

**本人群空白**：① 平台数据侧全面空白——美团/饿了么/抖音本地生活商家后台的订单、账单、评价、核销数据无合规开源抓取或对账工具（「外卖商家对账 开源」搜索直接确认无匹配项目），平台 API 不对中小商家开放，爬后台有封号风险；② 内容「最后一公里」空白——自动合规发布到抖音/美团/点评的通道不存在，产线必须以「成片+排期表」收尾，发布动作留人工；③ 中文本地生活垂直模型与数据集空白（现成评论情感模型仍是 UER 老模型，团购/核销/POI/抽成等概念在开源语料中为零）；④ 「票据→记账科目」的中国本地化语义层需完全自研（PaddleOCR 只解决识别；票据类项目多为个人小仓库，成熟度未核实）；⑤ 行业编排层缺失——Cow 有技能市场但无行业内容，Dify/FastGPT 有工作流但无本地生活模板，这正是 skill/MCP 封装的商业空间；⑥ IOPaint 已归档、开源数字人 HeyGem 官方仓库已无法在 GitHub 检索到（仅剩 ≤499★ 第三方衍生版，官方状态未核实）——数字人口播带货这条线目前没有可放心交付学员的开源资产。

---

### 2.2 公司里的打工人（非技术岗知识工作者）

**画像与核心需求**：八类需求：① 零散记录汇编成有数据支撑的周报月报；② Word 方案/大纲半小时变成套公司模板的可二次编辑 PPT；③ 1-2 小时会议录音变成分发言人、带决议待办的纪要并能追踪；④ 多张 Excel 合并/清洗/去重/透视/跨表匹配、大白话代写复杂公式；⑤ 按单位固定格式起草公文（格式一错就被打回）；⑥ 扫描件/图片报表/PDF 合同数字批量提取进 Excel；⑦ 网页后台/OA/ERP 重复录入下载搬运；⑧ 多来源资料检索汇总成一页简报。

**资产表**：

| 资产（URL） | 成熟度 | 能力 | 封装路径 | 许可 |
|---|---|---|---|---|
| [FunASR](https://github.com/modelscope/FunASR) | 20.5k★ / 5,944 提交（v1.4.16），达摩院（通义实验室）维护 | 中文 ASR 全家桶：离线/流式、VAD、标点恢复、CAM++ 说话人分离，OpenAI 兼容 API、MCP server、Docker 一键部署 | 已有官方 MCP server 与 OpenAI 兼容 API，直接封为「录音转写」MCP server 或 skill | MIT（代码）；模型权重独立许可 |
| [PPTAgent](https://github.com/icip-cas/PPTAgent) | 5.1k★ / 429 提交，**2026 年 9 月仍发新功能（PPTAgent Skill）**，中科院软件所等机构维护，EMNLP 2025 论文 | Agent 化 PPT 生成：分析参考模板 .pptx 后用编辑动作生成新 PPT，视觉模型渲染审查迭代，产出可编辑 pptx | 本身按 coding-agent skill + MCP server 双形态设计，照官方注册流程接入 | MIT |
| [PPTist](https://github.com/pipipi-pikachu/PPTist) | 9.4k★ / 1,318 提交，持续活跃 | Web 端复刻 PowerPoint 的在线编辑器，导入导出 PPTX（导出保真约 95%）、AI 模板式生成 | 自部署为 Web 服务，「生成 JSON→PPTist 渲染」封装成在线改稿工作流模板 | AGPL-3.0（另有 2022 停维护的 Apache-2.0 旧版） |
| [MarkItDown](https://github.com/microsoft/markitdown) | 187k★ / 406 提交，微软官方活跃维护 | Word/Excel/PPT/PDF/图片(OCR)/音频批量转保留结构的 Markdown，专为喂 LLM 设计 | pip 库/CLI，一条命令封装成「读文档」skill 或 MCP 工具 | MIT |
| [PandasAI](https://github.com/sinaptik-ai/pandas-ai) | 23.8k★ / 1,416 提交，sinaptik-ai 团队活跃 | 自然语言向 CSV/数据库提问（df.chat），自动生成并沙箱执行代码、画图 | 包一层 MCP server（chat_with_dataframe 工具）给通用 agent | 核心 MIT；pandasai/ee 目录有单独企业版许可 |
| [excel-mcp-server](https://github.com/haris-musa/excel-mcp-server) | 4.2k★ / 48 提交，**v1.0 于 2026-09-28（调研当日）发布**，单人维护 | MCP server：AI 创建/读取/编辑 xlsx、xlsm——公式、格式化、图表、数据验证，无需装 Excel | uvx 即跑，天生就是 MCP server，直接注册进任意通用 agent | MIT |
| [Office-Word-MCP-Server](https://github.com/GongRzhe/Office-Word-MCP-Server) | 2.1k★ / 69 提交，**2026-03-03 已被所有者归档（只读）** | MCP server：AI 创建/编辑 Word——标题、表格、图片、查找替换、转 PDF、密码保护 | 已是 MCP server；因上游归档，应 fork 后自维护并打包为自己的 word-mcp | MIT |
| [Umi-OCR](https://github.com/hiroi-sora/Umi-OCR) | 47.5k★ / 1,267 提交，持续活跃，中文社区口碑极好 | 离线 OCR 软件：截图、批量图片、PDF/EPUB 识别并生成双层可搜索 PDF，内置 PaddleOCR 引擎 | 自带 HTTP 接口，Docker/本地服务暴露后封成「图片转文字」MCP 工具 | MIT |
| [n8n](https://github.com/n8n-io/n8n) | 206k★ / 24,902 次提交，极活跃，9000+ 官方工作流模板 | 可视化工作流自动化：1500+ 集成，原生 AI agent 节点与 MCP 支持，Docker 自托管 | 自托管后把每条付费课产线做成一个可导入的 n8n 工作流模板交付 | Sustainable Use License（fair-code，非 OSI 开源；商用需读条款） |
| [Dify](https://github.com/langgenius/dify) | 157.4k★ / 13,699 提交，极活跃 | 开源 LLM 应用平台：工作流/RAG/Agent/MCP 工具接入/全量 API，2C4G 即可自部署 | Docker Compose 一键部署，课程 agent 打包成 Dify DSL 应用文件导入即用 | Dify OSL（Apache-2.0 附加条件） |
| [browser-use](https://github.com/browser-use/browser-use) | 116.6k★ / 10,299 提交，极活跃，已集成进 n8n | 让 LLM 像人一样操作真实浏览器：登录后台、填表、下载、抓取 | 官方支持 MCP 与 CLI（Browser Harness），作「网页操作」skill/MCP server | MIT |
| [AutoHotkey](https://github.com/AutoHotkey/AutoHotkey) | 13.2k★ / 5,001 提交，v2 持续活跃（v1 已停维护） | Windows 宏与热键脚本：自动操作桌面软件、批量按键、窗口控制 | 常用脚本打包 .ahk 库 + agent 按需生成脚本，封为「Windows 桌面自动化」skill | GPL-2.0 |
| [OpenRPA](https://github.com/open-rpa/openrpa) | 3.1k★ / 2,306 提交，活跃维护（支持 Win11） | 企业级开源 RPA：录制回放，支持 Windows 桌面、SAP、Java、Office、终端(3270/5250)、图像识别 | 自部署后把流程录制成机器人，经 n8n/webhook 触发，成为 agent 可调度的执行器 | MPL-2.0 |
| [WhisperX](https://github.com/m-bain/whisperX) | 24.3k★ / 560 提交，持续活跃（2026 年仍在加新特性） | faster-whisper 转写：约 70 倍实时批处理、词级时间戳、pyannote 说话人分离（需 HF token） | Python 库+CLI，与 FunASR 一起封成「多语种转写」MCP server 的备选引擎 | BSD-2-Clause（whisper/pyannote 权重各有许可） |

**端到端候选（调研原文）**：
1. **会议纪要一条龙产线（录音进、纪要+催办出）**——拖入会议录音，数分钟产出分发言人逐字稿+按「决议/待办/风险」三段式的 Word 纪要（符合本单位字体字号规范），待办自动登记 n8n 并按日期邮件催办；附带可对话调度的 agent 入口。栈：FunASR、Office-Word-MCP-Server、MarkItDown、n8n、Dify。
2. **月度汇报生成器（Excel 台账进、模板 PPT+Word 摘要出）**——指向原始 Excel 台账文件夹，自动清洗统计（3-5 张图表）、套学员自己公司的 PPT 模板生成完整可编辑汇报 PPT、附一页 Word 摘要；免费层送「单次生成」，付费交付整条产线+模板固化。栈：excel-mcp-server、PandasAI、PPTAgent、PPTist、Office-Word-MCP-Server。
3. **每日值守数字员工（自动取数-整理-出日报）**——每天定时自动登录网页后台下载报表（browser-use）或操作无 API 的桌面客户端（AutoHotkey/OpenRPA），OCR 提取关键数字（Umi-OCR），汇总进固定 Excel 日报模板生成一页简报，早会前推送邮箱/IM；异常自动截图留证并 @本人。栈：browser-use、AutoHotkey、OpenRPA、Umi-OCR、excel-mcp-server、n8n。

**本人群空白**：① 中文公文写作无高质量开源专项——GitHub「公文」检索顶部均为无关泛中文资源项目，无 GB/T 9704 国标版式/机关文种的模板库/语料库/微调模型，只能自建「文种模板+格式校验规则+提示词」skill，反而是课程最有壁垒的交付物；② 「转写稿→谁在说话」最后一公里——FunASR/WhisperX 只输出匿名编号（whisperX 自述分离效果「远非完美」），SPEAKER_00→王总需声纹注册或人工确认，须自研交互流程；③ 企业 VI 级 PPT 模板固化缺位——保证导出 pptx 在真 PowerPoint 不跑版无现成开源件，需预做模板工程；④ Office 三件套+邮件+IM 统一编排层缺失——业务语义编排（纪要三段式、周报结构）全靠自研工作流模板；⑤ Office MCP 生态维护断层——Star 最高的 Word MCP（2.1k）2026-03 归档、excel-mcp-server 单人维护，付费交付前必须 fork 自维护并回归测试；⑥ 开箱即用私有化部署包空白——工资表/合同/录音高度敏感，SaaS 走不通，而现有开源件各自 Docker/uvx/pip 碎片化，无「一键 compose 全家桶」，该打包工作正是付费课必须自己承担的价值点；⑦ 中文 ASR 热词定制（公司人名/产品名/行业黑话）缺工程化工具，需自研「单位词表」管理注入转写链路。

---

### 2.3 做图片的人（设计从业者与接单画师）

**画像与核心需求**：九类需求：① 按客户文案快速产出多版风格草稿（搜索显示 AI 辅助节省约 75% 出图时间，多版方案是商单中标关键）；② 客户反馈后只改局部不重画全图（IOPaint 23.3k★、A1111 内置 inpaint 均为此存在）；③ 一套素材批量产出多尺寸/多风格/多 SKU 成图；④ 老照片修复接单（GFPGAN 37.7k★）；⑤ 白底商品图换精修场景背景与打光的「AI 商拍」（IC-Light + rembg 组合）；⑥ 个人画风或客户品牌角色训成 LoRA（kohya sd-scripts 2026-09 仍在发版）；⑦ LoRA 训练集批量打标（taggui 1.4k★ 专为此而生）；⑧ 海量参考图素材库检索复用（Eagle 收费、Billfish 不开源）；⑨ 日常抠图/去背景/去水印（rembg 24.9k★ 证明需求规模）。

**资产表**：

| 资产（URL） | 成熟度 | 能力 | 封装路径 | 许可 |
|---|---|---|---|---|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 135.3k★ / 6,028 提交，官方周更节奏，极活跃 | 节点式生成引擎：本地跑 SD/Flux/Qwen 等扩散模型，图生图/inpaint/放大/批量可编排成工作流并导出 API JSON | 工作流导出 API JSON，由 comfyui-mcp-server 类 MCP 包装成 agent 工具（调研注明已验证可行） | GPL-3.0 |
| [AUTOMATIC1111/stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui) | 165.1k★ / 7,689 提交，画师群体渗透率最高的事实标准；最近提交日期页面未显示，开发节奏已知明显放缓 | 一体化 WebUI：文生图/图生图、内外补绘制、GFPGAN/CodeFormer 修复、ESRGAN 放大、XYZ 参数表格、LoRA 加载，扩展生态庞大 | API 模式（--api）封装为 MCP server；社区已有大量扩展可复用 | AGPL-3.0 |
| [IOPaint（原 lama-cleaner）](https://github.com/Sanster/IOPaint) | 23.3k★ / 921 提交；**2025-08-13 已归档只读** | pip 一键安装的修复/外绘：LaMa 擦除、SD/SDXL/BrushNet/PowerPaint 重绘、AnyText 图上加字，插件式集成 RemoveBG/RealESRGAN/GFPGAN/SAM，CLI 批处理，Windows 一键安装器 | CLI 批处理 + 内置 HTTP 服务，天然适合封 skill/MCP tool（归档意味着需自 fork 维护） | Apache-2.0 |
| [GFPGAN](https://github.com/TencentARC/GFPGAN) | 37.7k★ / 6.3k fork / 107 提交；最后提交日期页面未显示，375 个开放 issue，稳定经典 | 腾讯 ARC 盲人脸修复：StyleGAN2 先验把模糊/损坏旧照人脸重建到发丝级清晰 | Python 库独立调用，一行推理；作为修复流水线的一个节点被 agent 编排 | Apache-2.0 |
| [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | 36.9k★ / 4.5k fork / 138 提交；最后提交日期页面未显示，README 有持续模型迭代记录，稳定经典 | 纯合成数据训练的图像/视频超分与修复：真实场景与动漫放大 4 倍，Python 脚本与 NCNN 可执行文件 | NCNN 版独立可执行文件，最适合封装 CLI skill；亦有 pip 包 | BSD-3-Clause |
| [DeOldify](https://github.com/jantic/DeOldify) | 18.5k★ / 2.6k fork；**2024-10-19 已归档只读，无维护**（MyHeritage 商用即基于它） | NoGAN 黑白照片/老视频深度学习上色，Artistic/Stable/Video 三种模型 | Jupyter/Python 调用，需自行封装服务；归档项目建议 fork 固化版本 | MIT |
| [rembg](https://github.com/danielgatis/rembg) | 24.9k★ / 554 提交，README 支持至 Python 3.13 并纳入 RMBG-2.0 等新模型，维护状态 | 去背景：CLI/Python 库/HTTP 服务器/Docker 四种用法，内置 u2net、bria-rmbg、BiRefNet 系列 | CLI 与内置 HTTP server 形态，是单点免费能力的最佳 skill/MCP 候选 | MIT（个别模型权重如 bria-rmbg 有独立许可） |
| [IC-Light](https://github.com/lllyasviel/IC-Light) | 8.5k★ / 523 fork / 118 提交，ICLR 2025 论文，README 显示 11 月仍有 Flux 相关修复，活跃 | 前景图像重新打光并可生成/融合背景：文字条件控制左光/右光/落日/影棚柔光，保持前景只改光照 | Gradio 本地运行 + 模型自动下载，可整合进 ComfyUI 工作流后经 MCP 暴露 | Apache-2.0（默认依赖的 BRIA RMBG-1.4 权重仅限非商业，商用需换 BiRefNet） |
| [IP-Adapter](https://github.com/tencent-ailab/IP-Adapter) | 6.7k★ / 148 提交；最后明确功能更新 2024-01，但已深度集成进 Diffusers/WebUI/ComfyUI，成熟组件 | 图像提示适配器：22M 参数让文生图「以图为提示」——参考图风格迁移、角色一致性（FaceID）、图生图变体 | Diffusers 库内调用或 ComfyUI 节点，随工作流经 MCP 暴露 | Apache-2.0 |
| [kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts) | 7.2k★ / 2,658 提交，**v0.12.0 发布于 2026-09-24**，支持 Windows ARM64，极活跃；LoRA 训练事实标准 | SD1.x/2.x/SDXL/SD3/FLUX.1 的 LoRA 训练、DreamBooth 微调、模型转换合并、打标脚本全套 | 纯 CLI 脚本（accelerate 启动），最适合封为「喂图出 LoRA」的 MCP 工具或自动化训练模板 | Apache-2.0（部分代码 MIT/BSD-3） |
| [TagGUI](https://github.com/jhc13/taggui) | 1.4k★ / 592 提交（v1.25.0），GitHub API 显示 2026-09-26 仍在更新，活跃 | 图像数据集打标桌面应用：键盘高速打标、标签补全、SD token 计数、WD Tagger/florence-2/cogvlm/llava 自动打标、批量标签操作 | 桌面 GUI 本体；自动打标模型可拆出做 CLI 批量打标 skill（另有 1.2k★ 的 ComfyUI-WD14-Tagger 节点版） | GPL-3.0 |
| [Qwen-Image](https://huggingface.co/Qwen/Qwen-Image) | HF 月下载约 27.8 万次 / 2.66k 赞，2025-08-04 发布，生态极活跃（100 Spaces、500+ 衍生模型），阿里 Qwen 团队维护 | 20B 文生图基础模型：中文复杂文字渲染领先，支持风格迁移、物体增删、图内文字编辑、姿态调整 | Diffusers 标准调用，ComfyUI 原生支持，经 MCP server 暴露给 agent | Apache-2.0 |
| [sd-dynamic-prompts](https://github.com/adieyal/sd-dynamic-prompts) | 2.3k★ / 642 提交，社区维护中（190 open issues） | A1111 扩展：模板语言+通配符文件+Jinja2 随机组合生成大批提示词变体，一次跑出结构化差异批量图 | 作 A1111 扩展安装；通配符模板思路可移植为 agent 生成的参数矩阵 | MIT |
| [comfyui-mcp-server (MetaBrain-Labs)](https://github.com/metabrain-labs/comfyui-mcp-server) | **仅 9★ 但 153 次提交**、文档/测试/CI 完整、中英双语，活跃维护的小众新项目（非官方） | TypeScript MCP 服务器：把 ComfyUI 自定义工作流转成参数可配置的 MCP 工具，13 个工具覆盖挂载/提队/取结果/下载资产/监控显存/上传全链路 | 本身就是 MCP server，可直接接入 Claude/Cursor；亦是自研封装的参考架构 | MIT |
| [Allusion](https://github.com/allusion-app/Allusion) | 901★ / 约 1,940 提交，仍在维护但规模小进展慢 | 为艺术家设计的开源桌面视觉素材库：集中管理参考图/灵感图，与 Blender、Krita 联动 | 桌面应用为主；「素材管理+语义检索」做成 agent skill 需另建 CLIP 向量索引层 | GPL-3.0 |

**端到端候选（调研原文）**：
1. **老照片修复接单小作坊：一键修复产线 + 调度 agent**——客户照片丢进去→自动跑人脸修复+去划痕擦除+黑白上色+4 倍放大→输出修复前后对比图和可打印大图；外加一个能批量接收订单文件夹、自动调度流水线、生成交付包的 agent；修复类三件套+IOPaint 全部免费送成单点 skill/MCP 工具。栈：GFPGAN、DeOldify、Real-ESRGAN、IOPaint、ComfyUI、comfyui-mcp-server。
2. **电商商品图 AI 商拍产线：白底图一键换场景**——上传白底商品图→自动抠图→IC-Light 影棚/场景打光合成→Qwen-Image 加中文卖点文字→批量导出主图/详情图多尺寸；以及一个读 SKU 表格自动为每件商品产出 N 套场景图的 agent。栈：rembg、IC-Light、Qwen-Image、ComfyUI、sd-dynamic-prompts、comfyui-mcp-server。
3. **个人画风 LoRA 孵化器：30 张作品变成可复用画风资产**——学员带 30 张作品来，下课带走用自己画风训好的 LoRA（含可复跑训练配置）、调用该 LoRA 出图改图的 ComfyUI 工作流、能按商单需求自动出 30 版草稿再精修的 agent；打标环节用 TagGUI+WD Tagger 自动化。栈：kohya-ss/sd-scripts、TagGUI、ComfyUI、IP-Adapter、sd-dynamic-prompts、Qwen-Image。

**本人群空白**：① 修复类组件各自独立且两条已归档（IOPaint 2025-08、DeOldify 2024-10）——开源界没有现成「老照片一键修复流水线」，须自研编排；扩散式修复易产生「换脸感」，保真不换脸的修复无现成开源方案；② 商品图合成的「真实性校验」缺失——阴影投射、透视匹配、桌面反射需手工修；「合成图一眼假在哪」的开源质检模型不存在；③ 设计师级素材管理近乎空白（Allusion 仅 901★ 且进展慢）——「自然语言搜自己素材库」没有面向设计师的成品开源工具；④ 客户反馈→改图闭环无开源工具（圈注理解→坐标定位→局部重绘→回传对比的图像理解与坐标映射需自研）；⑤ 批量出图后的「选片」环节空白——审美评分与自动初筛没有可用开源模型；⑥ 版权与合规检测空白（生成图侵权、LoRA 素材版权风险均无检测工具）；⑦ MCP 封装层不成熟——comfyui-mcp-server 仅 9★ 虽链路完整但未经大规模验证，「工作流→工具 schema→错误恢复」工程化层是明确自研空间（正是免费单点/付费端到端的切分点）。

---

### 2.4 做视频的人（短视频与剪辑从业者：口播博主、影视解说号、直播切片号、矩阵号运营、独立创作者工作室）

**画像与核心需求**：九类需求：① 日更多账号脚本量产（选题枯竭是常态）；② 长视频/直播回放切高光片段再分发；③ 批量混剪差异化喂矩阵号；④ 打轴加字幕（逐帧对齐耗时枯燥）；⑤ 配音与音色克隆（市面 TTS 机械、商用按字收费贵）；⑥ 数字人口播（HeyGen 订阅贵且角色不可控）；⑦ 多平台分发（每平台重复填标题/标签/封面）；⑧ 无版权素材获取；⑨ 视频翻译出海。

**资产表**：

| 资产（URL） | 成熟度 | 能力 | 封装路径 | 许可 |
|---|---|---|---|---|
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 126.5k★ / 954 提交 / 60 个开放 PR，持续活跃维护 | 主题关键词全自动：脚本撰写、素材匹配、配音、字幕、BGM 合成高清短视频，竖屏 9:16 与批量任务，AI Agent/WebUI/API/CLI 四种入口，可一键发布 TikTok/Instagram/YouTube Shorts | 自带 API 与 Agent 入口，最适合直接封成 MCP server（暴露 generate_video(topic, style) 等函数级工具） | MIT |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 194k★ / 24,009 提交，stable/nightly/master 三通道持续发版，极度活跃 | 命令行下载 YouTube、B 站等数千个网站音视频，选清晰度、批量、断点续传 | CLI 工具，包成 agent 的 Bash skill（下载→转存标准素材库目录）最省事 | Unlicense（源码）；PyInstaller 可执行文件含 GPLv3+ 组件 |
| [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 62.2k★ / 1,050 提交，V1→V2Pro 持续迭代，活跃 | 少样本声音克隆与 TTS：5 秒零样本、1 分钟微调，中/英/日/韩/粤跨语言，内置人声分离与数据标注 | 本地部署 WebUI/API，封为 MCP server（clone_voice + tts 两个工具，长驻 GPU 服务） | MIT |
| [whisperX](https://github.com/m-bain/whisperX) | 24.3k★ / 560 提交，2026 年仍在加新特性（Context-Aware Batching），牛津 VGG 组支持 | faster-whisper 快速 ASR：词级时间戳（wav2vec2 强制对齐）+说话人分离，large-v2 可达 70 倍实时、<8GB 显存 | Python 包+CLI，封为 MCP server（transcribe→SRT/diarization），字幕环节标准积木 | BSD-2-Clause |
| [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | 23.8k★ / 552 提交，2025-12 发布 Fun-CosyVoice3-0.5B，阿里 FunAudioLLM 维护，活跃 | 基于 LLM 的多语言 TTS：零样本克隆、9 语言+18 种中文方言、情感/语速/音量指令控制、流式延迟 150ms、vLLM/TensorRT-LLM 加速 | 提供 OpenAI 兼容 API 服务端，可直接挂成 MCP server 的后端 | Apache-2.0 |
| [pyvideotrans](https://github.com/jianchang512/pyvideotrans) | 19.2k★ / 1,580 提交，持续更新，活跃 | 带 GUI 的视频翻译一站式：ASR 字幕→LLM 翻译→多角色 AI 配音→合成视频，各阶段可人工校对 | 自带 CLI，可作翻译配音环节的工作流模板复用；GUI 适合教学演示 | GPL-3.0（传染性，深度集成需注意） |
| [LivePortrait](https://github.com/KwaiVGI/LivePortrait) | 19.1k★，2024-07 发布后持续更新（被快手/抖音/剪映/视频号采用），快手 Kling AI Research 维护 | 驱动视频让静态照片动起来：表情、头部姿态迁移，拼接与重定向精细控制，消费级显卡可跑 | 推理脚本+Gradio 界面，封为 GPU 服务 + MCP server（animate(photo, driver_video)） | MIT（代码）；默认 InsightFace 模型权重仅限非商业研究，商用须替换 |
| [social-auto-upload](https://github.com/dreammis/social-auto-upload) | 15.2k★ / 327 提交，2026-03 仍在发重构说明，活跃 | Python+Playwright 浏览器自动化：一键发布到抖音、小红书、快手、B 站、视频号、百家号、微博、TikTok、YouTube，支持定时，提供 sau CLI 和面向 Claude Code/Codex 等 AI Agent 的 Skill 接入方式 | 已提供 CLI + Claude Code Skill 接入方式，直接整理成通用 agent 的 skill，是全链路 MCP 化最现成的一块 | MIT |
| [MoviePy](https://github.com/Zulko/moviepy) | 14.9k★ / 1,532 提交，已发布 v2.0，稳定活跃并招募新维护者 | Python 视频剪辑底层库：剪切、拼接、插入标题、合成、特效 | Python 库，封为 skill（agent 按模板生成 MoviePy 脚本并执行）而非独立服务 | MIT |
| [NarratoAI](https://github.com/linyqh/NarratoAI) | 11.2k★ / 437 提交，2026-07 发 0.8.6 版（含 Apple Silicon 语音克隆），非常活跃 | AI 影视解说自动化：LLM 分析视频生成解说文案、按文案智能剪辑对应片段、配音字幕齐备，支持短剧解说与混剪，提供 Windows/macOS 整合包 | 本地部署 WebUI，适合做工作流模板（教学交付形态），核心逻辑可抽出为 MCP server | MIT |
| [ShortGPT](https://github.com/RayVentura/ShortGPT) | 8.0k★ / 298 提交，自述实验性项目；**最近提交时间未能从页面核实（活跃度未核实）** | 英文向自动化短视频框架：面向 LLM 的剪辑标记语言、自动脚本/字幕/配音（ElevenLabs+EdgeTTS 30+ 语言）、Pexels/Bing 自动取素材、整视频翻译重配音 | 剪辑标记语言思想可抽取成 skill 的中间表示；项目偏实验性，建议只借鉴不直接依赖 | MIT |
| [FunClip](https://github.com/modelscope/FunClip) | 6.4k★ / 288 提交，**2026-09 刚发 v2.2.1**，达摩院 FunASR 团队维护，非常活跃 | 本地化视频转写+智能剪辑：Paraformer ASR 带时间戳与说话人识别、支持热词、按文字/说话人自由多段剪辑、接 LLM 做「按语义选段」 | CLI+Gradio，封为 MCP server（transcribe→llm_select→clip 三步工具链） | MIT（源码）；模型权重受各自模型页条款约束（多为 Apache-2.0） |
| [auto-editor](https://github.com/WyattBlue/auto-editor) | 5.4k★ / 2,532 提交，活跃，另有在线版与桌面应用 | 命令行自动粗剪：按音频响度阈值剪掉静音/死空间、运动检测、多标签规则，可导出 Premiere/Resolve/FCP/ShotCut 工程文件 | 标准 CLI，包成 skill（agent 一次 Bash 调用）即可，零改造成本 | Unlicense（公有领域） |
| [pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) | 4.5k★ / 218 提交，0.3.0 大更新、在开发 CapCut 版，积极维护中 | pip 安装的 Python 库，程序化生成剪映草稿：轨道/字幕/贴纸/特效/转场/蒙版全可控，支持加载已有草稿做模板替换、批量生成、批量自动导出（**依赖 Windows+剪映 6 及以下**） | Python 库，封为 skill：agent 按模板参数生成草稿，人再进剪映出片 | Apache-2.0 |
| [EchoMimic](https://github.com/antgroup/echomimic) | 4.3k★ / 80 提交，AAAI 2025 论文，**更新集中在 2024-07 至 12，V2/V3 另仓** | 音频驱动的说话人像生成：纯音频、姿态地标、音频+地标三种驱动模式，有 V100 提速约 10 倍的加速版 | 推理脚本+Gradio，封为 GPU 服务 + MCP server（talking_head(photo, audio)），与 GPT-SoVITS 串联 | Apache-2.0 |

**端到端候选（调研原文）**：
1. **日更短视频量产产线 + 调度 Agent**——输入选题清单即可日更的自动产线（脚本→配音→字幕→素材→合成→定时多平台发布），以 MCP server + agent 调度的形式跑在自己电脑/服务器上，并已实际发布第一批不少于 10 条成片。栈：MoneyPrinterTurbo、GPT-SoVITS、whisperX、social-auto-upload、yt-dlp。
2. **直播/长视频高光切片分发产线**——输入一场直播回放 URL 即自动转写、LLM 挑高光、剪辑加字幕、生成剪映草稿（可人工精修）、定时分发到抖音/视频号/小红书/B 站，并用自己的一场回放跑出首批切片。栈：yt-dlp、FunClip、whisperX、auto-editor、pyJianYingDraft、social-auto-upload。
3. **个人数字分身口播矩阵工厂**——用自己的照片+1 分钟声音样本制成专属数字分身（克隆音色+音画同步口播），以及喂入批量脚本即可出片并发布的口播量产流水线，当天产出 5 条以上数字人口播成片。栈：GPT-SoVITS、CosyVoice、LivePortrait、EchoMimic、MoviePy、social-auto-upload。

**本人群空白**：① 国内平台无官方发布 API——上传全靠 social-auto-upload 这类 Playwright 自动化，风控升级即失效、Cookie 需人工养护、与平台协议存在灰色地带，是产线最脆弱一环，只能自建「发布节点运维」能力（搜索确认无官方 API 方案）；② 发布后数据回流闭环缺失——播放量/完播率/涨粉数据无公开 API，开源侧只能用 MediaCrawler 类爬虫（风控风险高）+ Metabase/DataEase 自建看板拼装（2026-09 搜索确认无现成开源方案）；③ 全链路编排与 MCP 化缺位——开源侧是单点积木，没有成熟项目把「脚本→素材→配音→字幕→渲染→发布」整链路封成 agent 可调用形态（MoneyPrinterTurbo 有 API/Agent 入口但不覆盖国内平台发布与剪映精修），这正是「免费送单点、付费交付全链路」的机会；④ 中文爆款结构语料与评测基准缺失——脚本环节质量上限全靠 prompt 自研与私域语料积累；⑤ 消费级硬件上音画同步数字人口播需自研胶水——LivePortrait 快但没有语音驱动，EchoMimic 有音频驱动但扩散推理慢、更新停在 2024 年，三者拼装与加速必须自己写；⑥ 渲染出口脆弱——pyJianYingDraft 批量自动导出绑死 Windows+剪映 6 及以下，剪映客户端升级即断；纯 ffmpeg/MoviePy 直出缺剪映成片质感。

---

### 2.5 做自媒体的人（图文自媒体与内容运营：公众号/知乎/小红书/头条等平台创作者与运营者）

**画像与核心需求**：八类需求：① 每天从热榜和对标账号筛「今天写什么」（「选题枯竭、追热点难」为自媒体前三痛点）；② 爆款拆解（MediaCrawler 65.9k★ 印证需求规模）；③ 长文写作（人工一篇平均耗时 4-6 小时）；④ 排版（Markdown→公众号/知乎带样式图文）；⑤ 封面图与图文卡片（小红书 3:4 轮播图组）；⑥ 多平台一键分发（5-10 个平台逐个粘贴）；⑦ 数据复盘（多平台数据拉齐归因，67% 企业认为获客追踪不准）；⑧ 粉丝私域运营（导到微信/企微，自动回复+分层群发）。

**资产表**：

| 资产（URL） | 成熟度 | 能力 | 封装路径 | 许可 |
|---|---|---|---|---|
| [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | 65.9k★ / 818 提交，持续活跃（164 open issues / 48 PR），个人维护（另有付费 Pro 版） | 基于 Playwright 的多平台采集：小红书/抖音/快手/B站/微博/贴吧/知乎的关键词搜索、指定帖子、二级评论、创作者主页抓取，带登录态缓存与代理池 | 包成 MCP server/CLI：「搜关键词→抓创作者主页→结构化 JSON」的采集技能（**注意其免责声明仅供学习研究、禁止商业用途**） | 仓库含 LICENSE 文件但页面未注明具体类型——未核实 |
| [TrendRadar](https://github.com/sansan0/TrendRadar) | 62.6k★，GPL-3.0，v6.10.0（2026/06）迭代频繁，另有独立 mcp-v4.0.0 版本 | AI 舆情监控：聚合知乎/抖音/B站/微博/百度/头条等 11 平台热搜+自定义 RSS，关键词筛选、AI 摘要简报推送到微信/飞书/钉钉/TG 等 9+ 渠道 | 已有官方 MCP 版本，agent 可直接对话式做趋势分析；课程侧做部署配置+关键词与推送渠道定制 | GPL-3.0 |
| [last30days-skill](https://github.com/mvanhorn/last30days-skill) | 63.1k★ / 1,268 提交，v3.11.1（2026/07）、2,700+ 测试，非常活跃（52 位贡献者） | AI agent 技能：跨 Reddit/X/YouTube/TikTok/HN/GitHub 等平台研究任意主题近 30 天内容，按真实互动数据打分并合成带引用的研究简报 | 本身就是 skill 形态（Claude skill marketplace / npx skills add / MCP bundle / CLI），其「跨源聚合→互动打分→带引用简报」方法可移植到中文平台选题流水线 | MIT |
| [doocs/md](https://github.com/doocs/md) | 13.4k★ / 1,665 提交，持续维护（doocs 社区） | 微信公众号 Markdown 编辑器：即时渲染、KaTeX/Mermaid/多图床/AI 助手，Chrome 扩展、npm CLI 和 Docker 私有化 | npm CLI 直接包进 agent 产线（稿→HTML→剪贴板）；也可再封一层 MCP server | WTFPL |
| [Wechatsync](https://github.com/wechatsync/wechatsync) | 6.4k★，v2.0.9（2026-03-24）仍在更新 | 浏览器扩展：本机登录态一键把文章同步为 29+ 平台草稿（公众号/知乎/小红书/掘金/CSDN/头条/WordPress 等），数据不经第三方服务器 | **官方已支持 Anthropic MCP 协议和 CLI**——agent 可直接调用其发布文章，最现成的「发布 MCP」 | GPL-3.0 |
| [social-auto-upload](https://github.com/dreammis/social-auto-upload) | 15.2k★ / 327 提交，活跃（正在大重构并集成 AI-agent skill） | sau CLI 自动发布视频/图文到抖音（最完整）/B站/小红书/快手/视频号/百家号/微博/TikTok/YouTube 等 11 平台，定时发布、cookie 持久化 | 天然 CLI 形态，正在官方集成 agent skill；可包成 MCP server 供 agent 调「发布视频」动作 | MIT |
| [MultiPost-Extension](https://github.com/leaperone/MultiPost-Extension) | 3.6k★ / 304 提交，活跃维护；注意官方商店版含未开源的 Agent 模块 | 浏览器扩展一键发布文本/图片/视频到知乎/微博/小红书/抖音/TikTok/YouTube 等 10+ 平台，暴露扩展 API 与 RESTful API | 通过其 RESTful API 封为 MCP server/工作流模板即可被通用 agent 调用 | Apache-2.0（开源部分） |
| [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | 20.4k★，v5 完全重写（异步架构/Docker Compose 一键部署），始于 2021 持续维护 | 自托管抖音/TikTok 数据采集与无水印下载：帖子/作者/评论/搜索数据入 PostgreSQL，提供 REST API、**MCP 服务器（streamable-http /mcp）**、CLI、Web 控制台四种入口 | 官方自带 MCP server——agent 直接挂 /mcp 端点即可查询抖音数据 | Apache-2.0 |
| [guizang-social-card-skill](https://github.com/op7418/guizang-social-card-skill) | 7.3k★，迭代至 v0.12 并有 ROADMAP，仍在维护（歸藏） | Claude Code/Codex 技能：把文章/截图/照片转成小红书轮播图文、Live Photo、公众号 21:9+1:1 封面对；2 套视觉系统/28 版式/10 主题，单文件 HTML 经 Playwright 渲染 PNG | 已是 Agent Skill（npx skills add 或克隆到 ~/.claude/skills/）；课程侧做主题定制即可直接送 | AGPL-3.0 |
| [RedInk](https://github.com/HisMax/RedInk) | 5.6k★ / 42 提交，v1.4.3（2026-06-30）迭代活跃 | 小红书图文一站式生成：基于 Nano Banana Pro+Gemini，一句话自动生成大纲、封面图和内页图文，并发批量生成与单页重绘，Docker 一键部署 | Docker 自托管+Web 界面，封为工作流模板（选题→RedInk→成图→social-auto-upload 发布） | **CC BY-NC-SA 4.0（个人非商业）；商业用途需联系作者授权** |
| [Qwen3 系列（通义千问开源模型）](https://huggingface.co/Qwen) | 阿里云官方组织维护，单模型下载数十万级（Qwen3-Next-80B 约 30 万+、Qwen3-Coder-480B-FP8 约 75 万），持续发版 | 原生中文大模型家族（指令/推理/视觉/Coder），本地或 API 部署做中文长文写作、改写、标题生成 | 以 API（DashScope/OpenAI 兼容）或本地 vLLM 接入产线；写作策略层以 skill/prompt 模板沉淀 | HF 组织页未标注具体许可证——未核实（需查各模型页） |
| [Long-Novel-GPT](https://github.com/MaoXiaoYuZ/Long-Novel-GPT) | 1.2k★ / 58 提交，迭代至 2.2 版，个人维护，规模小但方法论被广泛引用 | 长篇文本生成器：「大纲-章节-正文」自上而下分层扩写 + RAG，突破上下文限制生成万字级连贯文本，附 Prompt 集与拆书改写 | 分层扩写算法可抽成 skill/工作流模板（搭配任意模型），比直接复用仓库更现实 | 页面未显示许可证——未核实 |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 135k★ / 6,028 提交，每周发版，极活跃 | 节点式生成引擎：本地跑扩散模型生成图像/视频，工作流可保存复用、可 API 调用 | 自带 API：「载入工作流→出图」封成 MCP server 或 CLI，agent 一句话触发封面生成 | GPL-3.0 |
| [CowAgent（原 chatgpt-on-wechat）](https://github.com/zhayujie/chatgpt-on-wechat) | 47.1k★ / 3,113 提交，v2.1.9（2026-09-14）非常活跃 | 多渠道 AI Agent 框架：任务规划/工具调用/三层记忆/知识库/多 Agent 协作，接微信/飞书/钉钉/TG/QQ，支持 MCP 与 Skill Hub | 本身支持 MCP+技能系统：把选题简报/复盘报告的推送封装成其技能 | MIT |
| [Easel（浙大 ZJU-REAL 社媒智能体）](https://github.com/ZJU-REAL/Easel) | 2.1k★ / 202 提交 / 6 位贡献者，社区较活跃 | 基于 OpenClaw Agent 的五层工作台：发现热点→策划选题→创作文案/图片/音视频→发布到小红书/抖音/快手/知乎/B站/视频号/公众号→数据归因，以账号画像（定位/风格/受众/记忆）驱动 | Apache-2.0 可自由二开：课程可基于它做减法定制（砍视频、强化图文），或抽取其账号画像层 | Apache-2.0 |

**端到端候选（调研原文）**：
1. **「爆款雷达选题台」——每天 7 点自动产出《今日选题简报》的 agent**——自动抓取 11 平台热搜+3 个对标账号近 7 天爆款数据，按互动量打分后用大模型生成《今日 10 个选题（含标题候选与切入角度）》简报，推送到微信/飞书；含可复跑的 Docker Compose 与关键词配置面板。栈：TrendRadar、MediaCrawler、Douyin_TikTok_Download_API、last30days-skill、Qwen3、CowAgent。
2. **「公众号长文产线」——选题进、五平台草稿出的全自动流水线**——输入选题，自动完成分层大纲→3000 字成稿→公众号主题排版→封面图与小红书轮播卡→一键生成公众号/知乎/小红书/头条/掘金五平台草稿，人工只在最终发布页确认；另带走封装好的「写作扩写 skill」与「发布 MCP」。栈：Qwen3、Long-Novel-GPT、doocs/md、guizang-social-card-skill、ComfyUI、Wechatsync、MultiPost-Extension。
3. **「周复盘归因 agent」——每周自动回答「这周什么有效、下周写什么」**——每周一自动抓取自己账号+3 个对标账号的多平台内容表现数据入库，生成归因报告+下周选题排期建议，附可交互查询的数据看板。栈：Douyin_TikTok_Download_API、MediaCrawler、TrendRadar、Qwen3、CowAgent。

**候选级风险标注（本报告补充，区别于资产表的一体化提醒）**：上述候选 1/3 的技术栈含 MediaCrawler，其免责声明禁止商业用途——若做商业交付，抖音侧可替换为 [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API)（Apache-2.0、自托管、官方自带 MCP server），小红书/公众号侧目前无合规开源平替（调研确认的空白），只能平台后台手工导出+自研解析兜底；候选 3 另受空白①（公众号采集断裂）直接制约。这也是本人群暂不开课的原因之一（见 §1 落选说明）。

**本人群空白**：① 微信公众号侧数据采集已实质断裂——wechat-article-exporter（约 13k★、MIT）因微信关闭其依赖的核心接口于 **2026-07-30 停止维护转只读归档**，公众号阅读量/评论/涨粉历史数据获取在开源生态没有活的替代品，复盘环节只能靠官方后台手工导出+自研导入脚本；② 「多平台数据→选题归因→下周计划」复盘归因层无开源平替——采集端厚，但异构数据清洗对齐、互动率归因和看板呈现的轻量 BI 层不存在（Easel 仅做初步归因；Metabase/Superset 对自媒体人过重）；③ 发布自动化与平台风控的持续对抗是结构性风险——Easel README 明确提示小红书会检测自动化、建议预览后手动确认，商业交付必须内置「草稿+人工确认」兜底和失效告警；④ 私域（个人微信/企微）合规自动化缺位——Wechaty 版本停在 v1.11（2021-11，页面确认），个人号协议方案灰色；渠道活码、粉丝标签分层、群发 SOP 等企微 SCRM 核心能力没有成熟开源平替；⑤ 「账号风格资产」无独立可复用组件——只有 Easel 的账号画像做了初步实现；⑥ 中文平台工具的 MCP 化覆盖不全——TrendRadar/Douyin API/Wechatsync 已带 MCP，但排版（doocs/md）、图文生成（RedInk）、采集（MediaCrawler）仍是纯 Web/CLI，统一封装成本身就是差异化机会。

---

### 2.6 想自己搭工具的超级个体

**画像与核心需求**：八类需求：① 想法几天内变成能跑的小工具/小服务（低代码+AI 编程，典型栈 Next.js+Supabase+Vercel+Stripe 轻量组合）；② 重复信息收集自动化（RSSHub 46.3k★「万物皆可 RSS」印证规模）；③ 批量内容变现产线（MoneyPrinterTurbo 126.5k★ 即为此需求而生）；④ 资料/行业知识搭成可问答可对外服务的知识库（WeKnora/FastGPT/Dify 合计超 200k★）；⑤ 把已有网站/软件/网页操作封装成大厂 agent 可调用的 MCP server 或 skill（awesome-mcp-servers 索引 95.6k★）；⑥ 低成本自托管全套服务（GitHub self-hosted topic 下 n8n/open-webui/coolify 均列前十）；⑦ 小工具接用户系统和收款实现小额变现；⑧ agent 长期无人值守运行（定时调度、失败重试、成本核算、结果通知）。

**资产表**：

| 资产（URL） | 成熟度 | 能力 | 封装路径 | 许可 |
|---|---|---|---|---|
| [n8n](https://github.com/n8n-io/n8n) | 206k★ / 24,902 提交 / 760 个开放 PR，非常活跃（n8n 公司） | 可视化拖拽工作流自动化：400+ 集成节点，内置 LLM Agent 节点，JS/Python 自定义节点，自托管无工作流数限制 | 每条产线做成一个 webhook 触发的 workflow，再用 FastMCP 写一层 MCP server 调用其 API，即可被大厂 agent 调度 | fair-code（Sustainable Use License + n8n Enterprise License，非 OSI 开源，自托管免费、二次分发受限） |
| [Dify](https://github.com/langgenius/dify) | 157k★ / 13,699 提交，活跃（langgenius） | 可视化构建 LLM 应用：AI 工作流、RAG 管道、Agent 应用，拖拽即从原型到生产 | Dify 应用自带 OpenAI 兼容 API——直接把「发布后的 Dify 应用」注册为大厂 agent 的一个 MCP/API 工具 | Dify OSL（Apache 2.0 附加条件） |
| [FastMCP](https://github.com/jlowin/fastmcp) | 27.9k★ / 4,034 提交，非常活跃（Prefect 团队维护），宣称日下载百万次 | 用普通 Python 函数几行代码构建 MCP server/client，自动生成 schema、校验和文档 | 本身就是 MCP server 框架——课程封装动作的最后一步由它完成 | Apache-2.0 |
| [anthropics/skills（Agent Skills 官方规范与示例）](https://github.com/anthropics/skills) | 178.8k★，2026-09-24 仍有更新；Anthropic 官方 | Agent Skills 官方仓库：技能规范（spec）、模板（template）和成套示例技能，SKILL.md 加脚本即成可动态加载技能 | 直接产出 skill：每个单点能力按 template 打包成 SKILL.md 文件夹，可被 Claude/兼容 agent 加载 | 无统一 LICENSE 文件；README 称多数 skills 为 Apache 2.0，docx/pptx/xlsx 等文档技能为 source-available（非开源） |
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | 90.6k★ / 4,189 提交，活跃（Anthropic 管理+社区共建） | MCP 参考服务器合集（Fetch、Filesystem、Git、Memory 知识图谱、Sequential Thinking 等） | MCP server 即最终形态，可直接分发或作为自建 server 的脚手架 | 存量 MIT + 新贡献 Apache-2.0 |
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | 84.4k★，v0.9.4 发布于 2026-09-23，非常活跃（个人开发者 Unclecode + 企业赞助） | 开源爬虫：把任意网站转成适配 LLM 的干净 Markdown，支持结构化抽取，可自托管 | 用 FastMCP 包一个 crawl→markdown→结构化 JSON 的 MCP server，任何 agent 都能「读网页」 | Apache-2.0（附署名要求） |
| [RSSHub](https://github.com/DIYgod/RSSHub) | 46.3k★，GitHub API 显示 2026-09-28 当天仍有 push，极活跃（DIYgod 及社区） | 「万物皆可 RSS」：把社交媒体、榜单、公告、播客等无数非 RSS 站点转成统一 RSS/JSON 订阅源 | 自托管实例 + 一个 rss.read MCP 工具，让 agent 按订阅源拉取并摘要 | AGPL-3.0 |
| [browser-use](https://github.com/browser-use/browser-use) | 116.6k★，2026-09-26 有 push，活跃（browser-use 团队） | 让 AI agent 直接操控真实浏览器完成点击、填表、登录后抓取 | 官方即提供 MCP 集成路径；也可经 n8n 节点或 FastMCP 封装成「操作网页」技能 | MIT |
| [CLI-Anything](https://github.com/HKUDS/CLI-Anything) | 50.8k★，README 更新至 2026 年 5 月底，活跃（香港大学 HKUDS） | 「Making ALL Software Agent-Native」：自动为 GIMP、Blender、LibreOffice 等桌面软件生成 CLI，让 agent 直接调用任意软件功能 | 生成的 CLI 配一个 FastMCP 壳即成 MCP server——「任意软件工具化」标准三步 | Apache-2.0 |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 126.5k★，2026-09-28 当天有 push，活跃（个人开发者 harry0703） | 输入主题关键词，一键自动生成脚本、配音、字幕、配乐并合成高清短视频 | 其 API 可被 n8n 定时调用；再用 FastMCP 包成「一键出片」MCP 工具给任意 agent | MIT |
| [VoiceStudio](https://github.com/debpalash/VoiceStudio) | 41.7k★ / 3,381 提交并持续发版，活跃（个人开发者 debpalash 与社区） | 完全本地运行的 ElevenLabs 替代：语音克隆、配音、视频翻译、转录、有声书，覆盖 646 种语言 | 命令行调用接入 n8n 产线；或包成「文本转配音」MCP 工具 | AGPL-3.0（内置模型各有独立许可，商用需自查） |
| [Tencent WeKnora](https://github.com/Tencent/WeKnora) | 30.8k★ / 3,265 提交，最新版 v0.8.2，活跃（腾讯官方） | LLM 知识平台：原始文档变可查询的 RAG、自主推理 Agent 和自动维护的 Wiki，开箱即用带界面 | 自托管后以检索 API 为底座，外面包对话与计费层即可成付费问答服务 | MIT |
| [Coolify](https://github.com/coollabsio/coolify) | 62.3k★ / 17,444 提交，活跃（coollabsio 团队，另有付费云版） | 开源可自托管 PaaS：一键在 VPS 上部署网站、数据库、全栈应用和 280+ 服务，替代 Vercel/Heroku | 部署层而非能力层：用它把学员整套产线固化为可复制部署方案 | Apache-2.0 |
| [Supabase](https://github.com/supabase/supabase) | 110.9k★ / 38,768 提交，非常活跃（Supabase 公司） | 开源 Postgres 开发平台：托管数据库、认证、自动生成 API、实时订阅、文件存储一体化 | 给 agent 包一个「查库/写库」MCP 工具（社区已有多个现成 Supabase MCP），产品后台即被 agent 化 | Apache-2.0 |
| [Polar](https://github.com/polarsource/polar) | 10.3k★ / 17,742 提交，活跃（polar.sh） | 面向 AI 时代的开源计费平台：按 token/agent 调用/算力等用量计量收费，充当 merchant-of-record 处理税务收据 | 自托管后经其 API 生成支付链接/计量 webhook，再封成「收款」MCP 工具供 agent 开单 | Apache-2.0 |

**端到端候选（调研原文）**：
1. **个人内容印钞机：日产 30 条短视频的自动产线 + 调度它的 agent**——部署在自己 VPS（Coolify 一键部署）：RSSHub+Crawl4AI 每天自动追踪热点→生成 30 条脚本→MoneyPrinterTurbo 自动合成成片与配音→定时落盘并推送清单到 IM；外加一个能用自然语言调度/改稿/补跑的 agent（n8n workflow + FastMCP 封装的 MCP 工具）。栈：n8n、RSSHub、Crawl4AI、MoneyPrinterTurbo、VoiceStudio、FastMCP、Coolify。
2. **把任何网站/软件变成 agent 工具：学员自建的 3 个 MCP server + 1 个 skill 包**——① 网页→干净 Markdown；② 「替我操作这个网站」；③ 把本地软件变成 CLI 工具；按 anthropics/skills 规范打包成带 SKILL.md 的可分发 skill 包，附一条「任何新需求→现成能力」的封装 SOP。栈：FastMCP、Crawl4AI、browser-use、CLI-Anything、modelcontextprotocol/servers、anthropics/skills。
3. **一人公司付费知识库服务：从资料到收款上线的完整小产品**——WeKnora 把行业资料变成 RAG 问答→Supabase 管用户注册登录→Polar 按提问次数计量收款→n8n 每日自动巡检并推送经营日报；交付时已导入学员自己的资料库并完成一笔真实测试收款。栈：WeKnora、Supabase、Polar、n8n、Coolify。

**本人群空白**：① 「工作流→agent 工具」缺桥接层——n8n 工作流没有官方一键转 MCP/skill 的能力（Activepieces 做了一半），把已有自动化暴露给大厂 agent 必须自己写 API+FastMCP 壳，这正是付费课可交付的自研环节；② 中文平台的内容抓取与分发无合规开源覆盖——微信公众号/小红书/抖音的读取路由（RSSHub）频繁失效、自动发布协议不公开，产线「进」「出」两端都要自研或人工兜底；③ 中国大陆小额收款空白——Polar/Stripe 类开源方案不覆盖国内微信/支付宝个人收款+自动发货，个人开发者变现在这一环没有维护良好的开源选项；④ 个人 agent 的常驻运行时缺失——调度、记忆（hindsight 类项目刚起步）、成本核算、失败告警需把 n8n+uptime-kuma+记忆系统+IM 推送自行拼装；⑤ 低代码 agent 平台稳定性风险——Flowise（55.5k★）已于 2026-08-13 归档转只读，证明该层变动剧烈，课程设计应押注 MCP/skill 等协议层而非单一可视化平台；⑥ 「能力包」到「商品」之间缺计量计费与防滥用层——Polar 只管收款，配额、限流、防白嫖需用 Supabase+自写中间件补齐。

---

## 3. 横向专题发现

### 3.1 Agent 观测与治理生态（Langfuse / Phoenix / AgentOps / Helicone / OTel GenAI 等）

**专题资产一览**：

| 资产（URL） | 成熟度 | 定位与能力 | 许可 |
|---|---|---|---|
| [Langfuse](https://github.com/langfuse/langfuse) | 35.1k★ / 3.9k fork / 9,666 commits，2026-01 起为 ClickHouse 旗下项目，极活跃；被 langflow/open-webui 等采用 | 开箱即用的 LLM/agent 追踪、评估、用户反馈、数据集平台，Docker Compose/Helm 自托管；OTLP 端点 /api/public/otel、langfuse.user.id/session.id 属性映射、user feedback API | MIT（ee/ 目录企业功能除外） |
| [Arize Phoenix](https://github.com/Arize-ai/phoenix) | 11.6k★ / 1.2k fork / 10,117 commits，Arize AI 维护，极活跃 | OTel 原生 LLM tracing、LLM-as-a-judge 评估、trace→dataset→experiment | **Elastic License 2.0（非 OSI，不得作为托管服务提供，商用需评估）** |
| [AgentOps](https://github.com/AgentOps-AI/agentops) | 5.8k★ / 634 fork / 811 commits，活跃；被 MetaGPT、crewAI 采用；JS/TS SDK 为 alpha | agent 会话录制回放、分层 span 追踪、成本追踪 | MIT |
| [Helicone](https://github.com/Helicone/helicone) | 6.2k★ / 675 fork / 5,488 commits，YC W23，活跃，SOC2/GDPR | LLM 观测 + AI Gateway 二合一：改 baseURL 即可采集，另有 SDK 与 OpenLLMetry 异步日志 | Apache-2.0 |
| [OpenTelemetry GenAI 语义约定](https://github.com/open-telemetry/semantic-conventions-genai) | 独立仓库，640 commits / 135 issues，活跃开发，**尚无 Stable 版本**（截至 semconv v1.36.0 仍 Development） | GenAI 场景（LLM 调用、agent spans、MCP、厂商特定）的 spans/metrics/events 标准约定 | Apache-2.0 |
| [Opik (Comet)](https://github.com/comet-ml/opik) | 22.3k★ / 1.8k fork / 7,233 commits，Comet 维护，极活跃（设计支持 40M+ traces/天） | LLM 观测+评估一体化：trace 树、LLM-as-a-judge、实验、在线评估规则、Guardrails；**自带 MCP server** | Apache-2.0 |
| [OpenLLMetry (Traceloop)](https://github.com/traceloop/openllmetry) | 7.5k★ / 1.1k fork / 1,421 commits，Traceloop 维护，活跃 | 基于 OTel 的插桩套件：pip 一个 SDK 插桩 16 个 LLM 厂商、7 个向量库、主流框架与 MCP | Apache-2.0 |
| [OpenLIT](https://github.com/openlit/openlit) | 2.8k★ / 408 forks，活跃，70+ 集成，ClickHouse 存储 | 一行代码 OTel 插桩 + CLI 观测 Claude Code、Cursor、Codex 会话（文件、shell、token、成本） | Apache-2.0 |
| [AgentSight (eunomia-bpf)](https://github.com/eunomia-bpf/agentsight) | 710★ / 106 forks / 761 commits，活跃；论文 [arXiv:2508.02736](https://arxiv.org/abs/2508.02736)（ACM DOI 10.1145/3766882.3767169，被引 36 次） | eBPF 系统级 agent 观测：无 SDK/代理，在 TLS 库边界捕获明文 LLM 载荷并关联内核事件，支持 OTel GenAI span 导出 | MIT |
| [Claude Code OpenTelemetry 官方文档](https://code.claude.com/docs/en/monitoring-usage) | Anthropic 官方文档，持续更新 | CLAUDE_CODE_ENABLE_TELEMETRY=1 + OTEL_* 环境变量导出 metrics/logs/traces(beta)，内容默认脱敏、逐项显式开启，支持 user.id/session.id | 非软件资产（官方文档） |

**核心发现**：

1. **Langfuse 是「可自托管 + 用户级标识 + 用户反馈」三要素最全的开源底座**，2026 年行业对比中被公认为自托管首选（证据：仓库页 35.1k★/MIT/Docker Compose 5 分钟本地起；[官方 OTel 文档](https://langfuse.com/docs/opentelemetry)确认原生 OTLP 端点、属性映射、observation.type 含 agent/tool/guardrail/evaluator）。「用户主动被观测换 skill 升级」的闭环首选它：自托管保证数据边界可信（对用户是卖点），userId/sessionId/user feedback/公开 trace 标记原生齐备。Opik（Apache-2.0、自带 MCP server）是无 ELv2 顾虑的替代。
2. **OTel GenAI 语义约定仍是 Development 状态但已是全生态的事实汇合点**——已拆独立仓库，覆盖 agent/MCP spans，Langfuse、Opik、OpenLLMetry、OpenLIT 全部兼容。架构决策：自有 schema 包一层、以 OTel 为交换格式，不锁死在未稳定草案上。
3. **「用户主动选择被观测」在现有工具里已有可直接复用的技术范式**：默认脱敏 + 显式开启的开关组（OTEL_LOG_USER_PROMPTS / OTEL_LOG_TOOL_DETAILS / OTEL_LOG_TOOL_CONTENT）、trace 级公开标记（langfuse.trace.public）、用户反馈 API（create_user_feedback()/create_score()）。不需要发明新机制，剩下的是产品层的权益兑现。
4. **本机 agent 轨迹回流的最短路径已由 CLI 厂商铺好**：Claude Code 原生 OTel 导出（span 层级 claude_code.interaction→llm_request/tool/hook）、Codex CLI 有 OTel log exporter、Gemini CLI 缺原生支持（需经 AI gateway 或社区桥接）。eBPF 路线（eunomia-bpf/agentsight）可行但仅 Linux+sudo 且在 TLS 边界截获明文，与「用户主动同意」叙事相悖——只作安全审计选讲，不当产品 consent 机制。
5. **云端对话形态的轨迹回流以「网关改 baseURL」为最短路径**（Helicone gateway 模式），SDK 埋点次之；网关层恰好是统一执行 consent 策略的最佳拦截点。
6. **consent 层可以做成薄 Collector processor**：用户同意则放行并注入 langfuse.user.id 等属性，未同意则丢弃——观测后端零改造（Langfuse 对非标准 span 容错改写而非拒绝）。
7. **撞名警示**：GitHub 上能搜到的 [AgentSight 是 eunomia-bpf 的 eBPF 项目](https://github.com/eunomia-bpf/agentsight)（MIT、710★、arXiv+ACM 论文），与自有 agentsight 撞名——若自有 agentsight 是另一个未公开仓库，其在公开网络不可见（调研未核实两者关系）；命名与定位必须先与这个有论文背书的同名项目切割。
8. **「本机 coding-agent 观测」生态位已被占**（OpenLIT CLI 直接观测 Claude Code/Cursor/Codex），且所有平台型项目都是开发者团队工具——**没有一个是「终端用户 consent + 权益交换」设计**。
9. **生态空位明确**：没有人做「consent-first + 权益交换 + 轨迹自动沉淀为 skill 升级数据集」的完整闭环（累计 8 次有效中英文检索未发现）。agentsight 的差异化 = consent-first 的本机收集器（输出 OTel GenAI span、后端无关）+ 同意管理 + 「轨迹→匿名化数据集→skill 评估与升级→用户获权益」的自动化管道；采集技术全部复用现成开源，自建价值集中在授权与闭环编排——这也是付费课程的最佳叙事（教用户搭闭环而非教埋点）。

### 3.2 云上 Agent 手册范式（阿里云 AI Agent Handbook）

**关键事实**：任务所指的 `alibaba/cloud-agent-handbook` 仓库不存在（HTTP 404）；实际项目是阿里云 2026-09 开源的 **[aliyun/ai-agent-handbook](https://github.com/aliyun/ai-agent-handbook)**——GitHub API 核验 788★ / 124 forks、2026-09-11 创建、2026-09-24 仍在推送、Apache-2.0、阿里云团队维护。官方文章[《一本 Agent 白皮书，值得连续写两年么？》](https://developer.aliyun.com/article/1768753)（2026-09-20）确认其名为「Alibaba Cloud AI Agent Handbook」，前身是 2025-09《AI 原生应用架构白皮书》。对外表述应采用准确仓库名，避免引用不存在的 URL。

**对课程与产品架构最重要的范式结论**：

1. **手册的拆分不是「规划/记忆/工具/执行/观测/安全」六分法，而是五个能力责任域**：业务与应用层、Agent 构建与编排层、生产运行层、治理与控制层、调优层——Security 横跨五层。组件视图 13 组件（Model、Harness 编排层、Context、State、Memory、Knowledge、Skill、Tool、Runtime、Sandbox、Gateway、Observability、Evaluation）。课程大纲应按五责任域组织，安全设计为贯穿每个模块的横切内容（原文见[第 2 章](https://github.com/aliyun/ai-agent-handbook/blob/main/01-architecture/第 2 章　Agentic Application 参考架构.md)）。
2. **「记忆」被拆成五类必须分开治理的信息对象**：Context（单次调用该看什么）、State（任务事实与恢复）、Memory（运行中生成的经验）、Knowledge（组织既有知识）、Skill（如何做某类任务的方法资产）——各自的生命周期、一致性与治理要求不同；把 Memory/Knowledge 放进同一个向量库会同时失去两类治理能力。课程交付的记忆组件不能只是向量库 demo，应交付五类对象的独立 Schema 与治理策略。
3. **工具侧三层 + 受控行动六环节**：Tool（能力）/Protocol（MCP、A2A、Function Calling）/Environment（产生影响的空间）；一次受控行动至少经过能力选择、身份与权限判定、参数校验、隔离环境执行、结果校验、状态与审计记录六环节；网关按治理粒度分三层（LLM Gateway 模型调用粒度 / MCP Gateway 工具调用粒度 / Agent Gateway 任务粒度）。MCP 教学要按六环节拆练习；技能封装应显式区分「能力描述（给模型看）」与「权限判定（Harness 执行）」，避免把授权逻辑写进 prompt。
4. **Skill 是明确的「可复用能力资产」单元，有标准化 Package 结构**（[第 5 章 §5.5](https://github.com/aliyun/ai-agent-handbook/blob/main/02-build/第 5 章 信息：上下文、状态与可复用能力资产.md)）：manifest 含 name/version/owner/description/required tools/permissions/IO 与 acceptance contract；正文含 instructions/scripts/templates/examples/references/tests；三层渐进式披露（发现/选择/执行）；生命周期 Draft→Test→Review→Publish→Observe→Update。**这就是「AI 能力封装成 agent 可调用技能」的包格式标准**：每个课程交付的技能按此 manifest 发布，自带验收契约与回归用例。
5. **Agent Release 是最小可复现发布单元，绑定六类要素**：① 模型及路由策略；② Harness 编排代码与配置；③ Prompt/Context Policy/Memory Policy/Skill/Knowledge 版本；④ Tool/MCP 能力清单与权限策略；⑤ Runtime/Sandbox 配置；⑥ 评估数据集与 Evaluator 基线阈值。生命周期五阶段闭环（架构设计→构建→运行→治理→调优），调优变更不得绕过门禁直接进生产。「交付完整 agent」的合格线不再是能跑的代码，而是绑定六要素、可复现评估的版本化 Release——课程结业标准与验收单直接采用该清单。
6. **8 个构建对象作为企业检查表**（[第 3 章](https://github.com/aliyun/ai-agent-handbook/blob/main/02-build/第 3 章 范式：Harness 的主流构建方式和责任边界.md)）：Agent Contract、Execution、Context&State、Capability、Environment、Control、Interaction、Quality；另有四类构建入口（高代码框架/产品化 Harness/基于模型/云产品）。按该范式，「交付完整 agent」的课程应拆成八个可复用组件交付——每件可独立复用、可单独作为课程模块售卖。
7. **「最低充分架构」原则**：能用 Workflow 别上 Agent、能单 Agent 别上 Multi-Agent；凡授予的自主性必须有对等的边界/证据/验证；自治 L1-L5 分级；中小团队直接照搬易过度设计。课程与产品宜做成三级形态：单技能（skill 包）→ 单 agent 模板（最小充分）→ 生产级 Release（完整八组件），并以「帮中小企业做减法选型」为差异化定位，避开与手册免费内容正面竞争。
8. **治理篇按四个「让」组织且观测是硬依赖**：让运行可见（可观测）、让行为有边界（安全：纵深防护/身份鉴权/高危二次授权/数据出域阻断）、让资产可管理（Prompt/Skill/MCP/Agent 统一注册与版本）、让行为可验证（上线前 Simulation 演练）——「可观测、安全和评估是运行前提，而不是上线补丁」。每个课程 agent 都应附 Trace 采集开关、安全检查单与仿真回归场景作为标配。
9. 手册「不卖课、不卖云」纯开源（[掘金解读](https://juejin.cn/post/7689030470210076722)），提供的是共同语言与判断框架而非带教实现——付费课可卖「把 30 章范式变成可运行交付物」的实操层；[CSDN 解读的 7 个工程判断](https://blog.csdn.net/m0_62051288/article/details/166790674)与 [英文 README](https://github.com/aliyun/ai-agent-handbook/blob/main/README_EN.md)（五类角色阅读路径）可分别改写为课程决策卡片与分班/先修设计。

### 3.3 能力封装通道生态（MCP / Agent Skills / GPTs / 国内渠道）

**专题资产一览**：

| 资产（URL） | 成熟度 | 定位 | 许可/门槛 |
|---|---|---|---|
| [Agent Skills 开放标准（agentskills.io）](https://agentskills.io) | Anthropic 发起并开放，**40+ 客户端官方列出采纳**（Claude/Claude Code、ChatGPT & Codex、Gemini CLI、Cursor、GitHub Copilot、VS Code、Junie、TRAE、Qoder、Goose、OpenHands、Roo Code、Kiro 等） | skill 文件夹（SKILL.md + 可选 scripts/references/templates）与渐进式披露三阶段 | 开放标准（规范仓库许可证未核实） |
| [anthropics/skills](https://github.com/anthropics/skills) | 约 178.8k★（两次调研抓取分别为 178.7k★ 与 178.8k★，正文统一取较新值）/ 21.1k forks，Anthropic 官方维护 | 官方示范 skills + 规范 + 模板，经 Claude Code 插件市场一行命令安装 | 多数 Apache 2.0；文档技能（docx/pdf/pptx/xlsx）source-available 非开源 |
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | 90.6k★ / 11.7k forks，活跃 | MCP 参考实现（filesystem/git/memory/fetch 等），写 MCP server 的教学范本 | Apache 2.0（新贡献）/ MIT（存量） |
| [MCP 官方 Registry](https://registry.modelcontextprotocol.io) | 预览版未 GA（2025-09-08 进预览、2025-10-24 API 冻结 v0.1），约 7.3k★（[registry 仓库](https://github.com/modelcontextprotocol/registry)） | MCP server 官方注册表：发布 server.json 元数据，GitHub OIDC/DNS/HTTP 验证命名空间 | 未核实；无人工审核、近乎零门槛 |
| [mcp.so](https://mcp.so) | 活跃社区目录站 | 收录 MCP servers/clients/Loops 及 Agent Skills，附 trending；中文条目少 | 未知；GitHub issue 或站内 Submit 提交 |
| [腾讯 WorkBuddy 开放平台](https://open.WorkBuddy.cn) | **2026-09-02 上线**，自称 10 万+ 生态资产、100+ 共创伙伴，腾讯官方 | 桌面办公智能体开放平台：Buddy 应用/专家/Skill/连接器(支持 MCP)/硬件，站内市场安装 | 个人实名认证（大陆二代身份证+人脸核验）即可入驻；[skill 文档](https://open.WorkBuddy.cn/docs/skill) 原生 SKILL.md；变现/分成未披露 |
| [Qoder](https://www.qoder.com/marketplace) | 自称 600 万+ 用户，SOC2/ISO27001，运营方 BRIGHT ZENITH PRIVATE LIMITED | AI 编程平台的 Extensions 内置 Skills 市场（Popular/Newest/搜索/安装），支持上传 SKILL.md 或 ZIP，Connector 即自定义 MCP | 注册账号即可 [Submit to Community](https://docs.qoder.com/qoder/extension-publishing.md)；本地导入仅限当前设备、需人工审查组件与权限；企业版有私有市场 |
| [TRAE Agent Skills](https://www.trae.ai/blog/trae_tutorial_0115) | 字节跳动产品，2026-01 发布 skills 教程，agentskills.io 官方列名 | 字节 AI IDE（TraeCode/TraeWork）按 agentskills.io 标准导入 SKILL.md 技能 | 闭源产品（开源仓库 [bytedance/trae-agent](https://github.com/bytedance/trae-agent)）；上架通道未核实 |
| [阿里云百炼插件](https://help.aliyun.com/zh/model-studio/plug-in-overview) | 阿里云官方文档，长期维护 | 通义系 agent 构建平台插件机制：官方（组件广场）/三方/自定义插件 | 页面未提及第三方上架商店或变现 |

**核心发现**：

1. **SKILL.md 已成跨厂商事实标准，是今天触达面最广的封装形态**——一次封装即可宣称覆盖从 Claude、Codex 到 TRAE/Qoder 的全部主流 agent。写 skill 必须区分「开放标准字段」（name、description、license、compatibility、metadata、allowed-tools）与「Claude 私有扩展」（disable-model-invocation、context: fork、动态 !`command` 注入）——上传 claude.ai 或用官方打包脚本时多余字段会直接硬报错（[Claude Code skills 文档](https://code.claude.com/docs/en/skills)）。
2. **Anthropic 官方 skills 仓库（约 178.8k★，两次调研抓取 178.7k/178.8k）+ Claude Code 插件市场是最大的官方 skills 分发源**，且「把 skills 做成可一键安装的插件仓库」是被验证过的分发形态，可直接复制；教学须讲清 source-available 与 Apache 2.0 的区别。
3. **MCP 官方 Registry 尚未 GA**：只收录元数据、无人工审核、CI 即可发布，现在注册占位成本极低；但生态早期，变现无从谈起。MCP 适合需要真实 API 调用的能力。
4. **中文 MCP 生态主要沉淀在第三方目录站**（mcp.so 等，已同时收录 Agent Skills），原生中文 server 是空白——做「中文场景 MCP server」有先发机会。
5. **GPT Store 的官方 builder 变现名存实亡**：2024 试点按 engagement 付费收益极低（社区估算约 $0.0002/条消息），2025 年转向 in-chat commerce 抽佣，第三方订阅付费工具（Top Road，YC W22）成为 builder 实际变现通道（注：OpenAI 官方一手文档 403 未能直接核实）。课程若含 GPTs 模块要打预防针：官方通道是获客入口而非收入来源。
6. **腾讯 WorkBuddy 是国内最直接的「递交 skill」通道**：原生采用 SKILL.md 格式、站内技能市场分发、个人凭身份证+人脸即可入驻、2026-09-02 刚上线——窗口期占位。同一个 SKILL.md 微调字段（frontmatter 必填 description/description_zh/en/version/author）即可多平台上架。
7. **Qoder 市场分 Skills/Plugins/Connectors 三类，Skills 上传即兼容 SKILL.md**——「SKILL.md 一份、多市场分发」路径在国内 coding agent 上也已跑通。
8. **通义/扣子侧有插件机制但缺公开的第三方上架+变现闭环**：百炼是「官方/三方/自定义插件」组件广场；coze.cn 文档为纯 SPA 无法核实发布与分成细节；**豆包独立开放插件平台未搜到证据**——判断基准中提到的「豆包工作」在本次调研中没有获得可核实的开放通道证据，首批国内分发主推 WorkBuddy/Qoder/TRAE。
9. **对个人开发者最省钱的组合拳**：「一个 SKILL.md 仓库（GitHub）+ 一个 MCP server（仅当能力需要真实 API）+ 两三个国内市场（WorkBuddy/Qoder/扣子）+ GPTs 可做但别指望官方分成」——即「一份 SKILL.md，五个货架」。

### 3.4 AI 课程市场与竞品

**专题资产/竞品一览**：

| 资产（URL） | 成熟度 | 定位 | 许可 |
|---|---|---|---|
| [n8n](https://github.com/n8n-io/n8n) | 206.2k★（本次访问核实） | 对打「教 n8n 工作流课」的训练营；也是交付自动化成果的执行引擎 | fair-code |
| [Dify](https://github.com/langgenius/dify) | 157.4k★（本次访问核实） | 对打「RAG 知识库/agent 搭建陪跑」类万元课 | Dify OSL |
| [Coze Studio](https://github.com/coze-dev/coze-studio) | 21.7k★，字节 coze-dev 维护（本次访问核实） | 对打「Coze/扣子教学课」；低代码 agent 交付底座 | Apache 2.0 |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | 89.4k★，8,344 commits（本次访问核实） | 对打「AI 编程/vibe coding 训练营」——直接交付可运行代码成果 | MIT |
| [mlabonne/llm-course](https://github.com/mlabonne/llm-course) | 83.2k★，内容更新至 2026（含 MCP、test-time compute）（本次访问核实） | 免费完整 LLM 课程，覆盖数千至万元级训练营的课程内容 | Apache-2.0，「will always stay free」 |
| [Datawhale hello-agents](https://github.com/datawhalechina/hello-agents) | 81.1k★ / 10.1k fork，15 章全部完成（本次访问核实） | 15 章完整 agent 教程：ReAct/反思、AutoGen/LangGraph、记忆/RAG、MCP/A2A、RL（GRPO）、3 实战项目+毕设 | **CC BY-NC-SA 4.0（非商业！引用分发受限）** |
| [Datawhale（开源学习社区）](https://github.com/datawhalechina) | 33.5k followers / 223 仓库（本次访问核实） | happy-llm（34.1k★）、self-llm（32.3k★）、easy-vibe、llm-cookbook 等 223 仓 | 各仓不同（部分 CC BY-NC-SA） |
| [Coursera《AI For Everyone》（吴恩达）](https://www.coursera.org/learn/ai-for-everyone) | 261.9 万人注册、4.8/53,241 评分（本次访问页面核实） | 免费 audit（7 小时、35 视频），证书另购——海外通识课定价锚点 | 平台服务条款 |
| [DeepLearning.AI Short Courses](https://www.deeplearning.ai/courses/) | Short Course 共 107 门（本次访问页面核实） | agents、MCP、RAG、AI Coding、Computer Use 等免费短课 | 平台服务条款 |
| [Lovable](https://lovable.dev/pricing) | 海外头部 AI 应用构建产品（定价页结构本次访问核实） | 对话式建站/建应用，按 credits 成果计价（构建/托管/AI 功能），免费层每日 5 credits | 闭源 SaaS |
| [知识星球](https://zsxq.com/) | 中文知识社群头部平台（本次访问官网核实） | 付费星球+社群运营——中文社群型课程交付主平台 | 平台服务条款 |
| [生财有术（scys.com）](https://scys.com/) | 知识星球头部社群（zsxq.com 首页推荐位可见，本次访问核实）；年费具体金额未核实（官网无价格，搜索被限流） | 会员制创业/副业知识社群，含 AI 主题航海训练营 | 未知（社群产品） |

**核心发现**：

1. **中文 AI 付费课是标准的「低价引流→训练营→高价陪跑」三级漏斗**，价格带大致 199 元 → 3980-7980 元 → 9800-19800 元（来源：多个培训评测源与 CSDN《2026 超级个体崛起》等，经 WebSearch 聚合获得，原文未逐一访问核实——本节所有聚合来源数字同此口径）；中间层训练营是红海且口碑差评集中区，应避开该价位段，往「成果交付」或「低价工具化」两端走。
2. **交付形态与学习效果强相关**：录播+机器人答疑完课率 <10%，社群+有限答疑约 20-30%（来源：什么值得买评测帖《AI 写作课月入过万？99% 是割韭菜》〔post.smzdm.com〕，经 WebSearch 聚合、原文未直接访问核实）——「教」的形态交付效率天然低；用户付费的真实动机是「拿到结果」而非「学会」，agent 直接交付成果是比督学更根本的解法。
3. **信任崩塌已发生**：李一舟 199 元课（39 节仅 6 节讲 AI，销售额约 5000 万）小程序被违规下架（来源：证券时报 stcn.com 2024-02-22《我花 199 元买了'中国AI教父'李一舟的课》与财联社 cls.cn 2024-02-22 下架报道，经 WebSearch 聚合、原文 URL 未逐一访问核实）；DeepSeek 借势教程 0.01-9499 元乱象被多家媒体调查（来源：新浪财经 2025-02 等报道，聚合来源）——信任真空反而利好「按成果付费」的新玩家，付费即见成果可天然规避割韭菜污名。
4. **海外头部内容已免费化**：Coursera AIFE 免费 audit（261.9 万注册、4.8 分，本次访问页面核实）、DeepLearning.AI 107 门免费短课覆盖 agent/MCP/RAG/AI 编码（本次访问页面核实）；Udemy 是「常态促销低价走量」（标价 $20-160、促销 $10-28，爆款课 4 个月 23,000 学生收入约 $52k——来源：Udemy 页面/Mashable/Business Insider，经 WebSearch 聚合；Udemy 单课页 WebFetch 返回 403，现价未能核实）。付费点必须避开「知识本身」，只能收「证书/交付/服务/担保」。
5. **训练营「教的内容」已被中文/英文开源社区免费且更全地覆盖**（hello-agents 81.1k★、llm-course 83.2k★、easy-vibe、self-llm 32.3k★、happy-llm 34.1k★）——差异化只能来自督学、环境和「帮用户拿到成果」，后者正是 agent 的强项。
6. **最脆弱的靶子是「教工具」类训练营**（n8n/Dify/Coze 数千元级）：工具开源且带官方模板库，课程的真实增值（配环境、选场景、跑通第一例）恰是 agent 可自动化的部分——「别人收费在教、我们用开源+agent 直接交付」。
7. **「交付成果」型商业模式已被海外验证、中文市场近乎空白**：Lovable 按成果 credits 计价；Devin 定位自主软件工程师（约 $500/月量级，定价页未能核实）。
8. **端到端交付的四大难点**：验收标准难定义、长程任务可靠性（多步错误累积）、边际成本不趋零（每单耗算力+人工兜底）、交付后维护责任——产品形态应从「半自主 agent + 人工兜底 + 事先签好的验收清单」起步，优先选验收客观、交付可复跑的品类。
9. **可落地的产品定位**：卖「第一个跑通的成果」而非课程——用开源免费内容做获客漏斗，用 agent skill 交付成果，按成果或订阅计费；课程不是主产品而是获客漏斗与信任建设，主营收来自「用开源栈+agent 直接交付可验收成果」，与「把 AI 能力封装成 agent 可调用技能」完全同构。

---

## 4. 首批课程候选

> **课程设计基准（来自判断基准，逐条落实）**：① 免费层=单点 MCP/skill（引流、建立信任），付费层=端到端可验收成果，高级层=完整 agent Release（手册六要素版本化）；② 组件映射按手册范式（Agent Contract / Execution / Context&State / Capability / Environment / Control / Interaction / Quality 八对象 + Agent Release 六要素打包）；③ 每门课内置 agentsight 观测闭环（consent-first：默认不采集+显式开关，同意后轨迹回流，换取 skill 持续升级权益；**学员语言的隐私说明统一见报告头部「给学员的观测说明」——轨迹默认不含录音/文件内容，不开开关不影响任何功能**）；④ 交付的每个 skill/MCP 均按「一份 SKILL.md，多货架」设计（GitHub + WorkBuddy/Qoder/TRAE 等大厂通用 agent 渠道）。
>
> **排序依据**：开源资产链最完整 > 观测闭环接得上 > 市场已验证付费意愿。

### 课程一：日更短视频量产产线 + 调度 Agent（做视频的人）

- **端到端交付成果**：学员下课带走一条部署在自己电脑/服务器（Docker/n8n）上的产线：输入一份选题清单（Excel/表单），自动完成脚本撰写→GPT-SoVITS 克隆音色配音→whisperX 逐词对齐字幕→yt-dlp 素材采集入库→MoneyPrinterTurbo/MoviePy 合成成片→social-auto-upload 定时生成各平台发布草稿。**边界明示：各平台未向第三方开放发布接口，本课交付到「草稿箱+排期表」为止，最后一键发布由学员人工确认**（与课程三的边界披露一致；自动化发布通道的失效风险见 §5.3.1）。**素材合规约束**：无版权 B-roll/背景音乐是该人群的独立痛点（§2.4 需求⑧，开源侧无解），本课成片素材默认取「学员自有素材+可商用素材库」，yt-dlp 仅用于学员自有账号回放采集与竞品参考研究，不将第三方版权素材直接混入商用成片。另带走一个注册进任意 MCP agent 的调度入口（FastMCP 封装），聊天里说「处理今天的选题表」即可全链路跑通。**验收标准：当天现场产出不少于 10 条成片，且至少 2 个平台进入草稿箱/已发布状态**（验收可行性预算：调研未采集整链单条成片耗时数据，「现场 10 条」为待试跑验证的目标值——开课前必须用学员典型硬件做一次计时试跑；若单条全链路耗时过长，降级预案为现场完整跑 2-3 条+其余任务排队课后自动产出）。
- **你需要准备什么（门槛）**：会用电脑；一台能装 Docker 的电脑/服务器（课程提供部署包）。GPU 为可选而非必需——调研依据：whisperX large-v2 需 <8GB 显存即可运行、GPT-SoVITS 本地部署为长驻 GPU 服务；无 GPU 学员的降级路径是 TTS/ASR 走云端 API（FunASR 官方支持 OpenAI 兼容 API 与 MCP 部署、CosyVoice 提供 OpenAI 兼容 API 服务端，均为调研确认的现成通道）。各组件最低硬件配置调研未采集，开课前实测后写入课程页。
- **免费单点能力（引流）**：①「视频打字幕」skill——拖入口播视频，whisperX 出逐词对齐 SRT；②「我的声音」MCP server——GPT-SoVITS 封装，5 秒样本克隆音色批量配音；③「素材入库」skill——yt-dlp 一条命令把参考视频/B-roll 转存标准素材库目录。
- **开源技术栈**：[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)、[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)、[whisperX](https://github.com/m-bain/whisperX)、[yt-dlp](https://github.com/yt-dlp/yt-dlp)、[social-auto-upload](https://github.com/dreammis/social-auto-upload)、[MoviePy](https://github.com/Zulko/moviepy)、[FunClip](https://github.com/modelscope/FunClip)（高光切片扩展模块）、[auto-editor](https://github.com/WyattBlue/auto-editor)（粗剪）、[n8n](https://github.com/n8n-io/n8n)、[FastMCP](https://github.com/jlowin/fastmcp)、[Langfuse](https://github.com/langfuse/langfuse)。
- **手册范式组件映射**：Agent Contract（输入=选题清单+账号配置，输出=成片+发布回执，成功标准=10 条进草稿）；Execution=n8n workflow 编排（遵循「能 Workflow 不 Agent」，调度 agent 只做自然语言→参数）；Capability=skill/MCP 工具清单（transcribe/tts/fetch/compose/publish）；Environment=本机 Docker（GPU 可选用于 TTS/ASR）；Control=发布前 HITL 审批点+Cookie 短期凭证（应对平台风控）；Interaction=IM 推送发布清单；Context&State=素材库与选题状态外置；Quality=全链路 trace+黄金数据集（学员历史爆款脚本）+基线阈值。最终按 Agent Release 六要素版本化打包。
- **agentsight 观测闭环接法**：产线节点全部 MCP 化，FastMCP 工具调用产出 OTel GenAI span（对齐 [OTel GenAI 语义约定](https://github.com/open-telemetry/semantic-conventions-genai)），OTLP 上报自托管 [Langfuse](https://github.com/langfuse/langfuse)；默认不采集，学员显式开启开关并注入 langfuse.user.id/session.id；每条成片的「采用/弃用/人工改动 diff」经 [Langfuse user feedback API](https://langfuse.com/docs/scores/user-feedback) 回流；匿名轨迹沉淀为脚本质量数据集→迭代「爆款脚本 skill」→老学员免费获得新版本（权益兑现）。学员用 Claude Code 环境的可用[官方 OTel 开关](https://code.claude.com/docs/en/monitoring-usage)零开发回流。
- **可行性与竞争判断**：各人群端到端候选中资产链最强——五环全部 10k★+ 且活跃（126.5k/62.2k/24.3k/194k/15.2k），social-auto-upload 官方已做 agent skill 接入（最现成的一块）。**付费意愿为未验证假设**：§3.4 调研只确认了 AI 课市场存在三级漏斗价格带与数千元级「教工具」训练营生态（间接信号），未采集数字人/剪辑品类的付费规模与完课数据——本报告不宣称「已被市场反复验证」，该假设靠免费层引流数据（下载/调用/转化）先行验证。对打数千元级「教工具」课。主要风险：发布自动化与平台风控的持续对抗（结构性、无开源兜底，靠草稿+人工确认+失效告警兜底）、中文爆款语料需自研积累。

### 课程二：会议纪要一条龙产线（公司里的打工人）

- **端到端交付成果**：学员下课带走一条部署在本机 Docker 的私有化产线：拖入会议录音，数分钟内产出分发言人逐字稿（FunASR 含说话人分离）+ 按「决议/待办/风险」三段式结构化的 Word 纪要（符合本单位字体字号规范），待办自动登记 n8n 并按设定日期邮件催办；附带一个可对话调度的入口（Dify/任意 agent：「处理昨晚的录音」）。**验收标准：用自己的真实录音现场跑出一份格式合规的三段式纪要+至少一条已登记催办任务。** 交付物含自研的「说话人映射」交互流程（SPEAKER_00→王总）与「单位词表」热词管理层——两者均为调研确认的开源空白，是课程壁垒。
- **免费单点能力（引流）**：①「录音转文字」MCP——[FunASR](https://github.com/modelscope/FunASR) 官方 MCP 的部署模板+热词表管理；②「文档转 Markdown」skill——[MarkItDown](https://github.com/microsoft/markitdown) 封装，任意 Word/Excel/PDF 喂给 agent；③「Word 成品」skill——fork [Office-Word-MCP-Server](https://github.com/GongRzhe/Office-Word-MCP-Server) 的自维护版，按格式规范出 docx。
- **你需要准备什么（门槛）**：会用电脑；一台能跑 Docker 的普通电脑即可——FunASR 官方提供 Docker 一键部署与 OpenAI 兼容 API，Langfuse 官方称 Docker Compose 5 分钟本地起。FunASR 在纯 CPU 上的转写速度调研未采集，开课前实测（若过慢则提供云端 API 备选，但默认本机离线以兑现「数据不出本地」承诺）。
- **开源技术栈**：[FunASR](https://github.com/modelscope/FunASR)、[MarkItDown](https://github.com/microsoft/markitdown)、Office-Word-MCP-Server（fork 自维护）、[WhisperX](https://github.com/m-bain/whisperX)（多语备选引擎）、[n8n](https://github.com/n8n-io/n8n)、[Dify](https://github.com/langgenius/dify)、[FastMCP](https://github.com/jlowin/fastmcp)、[Langfuse](https://github.com/langfuse/langfuse)。
- **手册范式组件映射**：Agent Contract（输入=音频文件，输出=docx 纪要+催办任务，验收=三段式结构+格式合规）；Execution=n8n 触发编排；Capability=transcribe/format/notify 三类 MCP 工具；Environment=本机 Docker、离线 ASR（录音数据不出本地——Control 层网络隔离）；Interaction=邮件/IM 推送纪要与催办；Context&State=会议库与待办状态外置（Event Log/Checkpoint）；Quality=转写字错率抽检+纪要结构校验器（Evaluator 基线）。按 Agent Release 六要素版本化。
- **agentsight 观测闭环接法**：转写→生成→催办每步节点级打点，是六门课中观测闭环最好接的（每步都有客观数字可验收：转写时长、字错率抽检、纪要被采纳/人工修改量）；修改 diff 经 user feedback API 回流→「纪要结构 skill」与「公文格式 skill」迭代升级→学员获得升级版。
- **可行性与竞争判断**：需求侧依据为调研的定性结论——非技术岗知识工作者是六类调研人群之一，会议纪要/汇报 PPT/Excel 处理列为其核心需求（§2.2），本报告不再作「人群最大、最高频」的无数据断言（调研未采集人群规模量化数据）；资产极稳（FunASR 20.5k★ 官方 MCP、MarkItDown 187k★ 微软官方、n8n 206k★）。数据敏感场景（工资表/合同/录音）私有化部署是 SaaS 竞品（讯飞等）给不了的卖点。成本：Office-Word-MCP-Server 已归档必须 fork 自维护+回归测试——这同时是壁垒（别人偷懒会随上游停更而坏）。对打泛「AI 办公」录播课与 SaaS 订阅。

### 课程三：门店短视频内容工厂（开店的人）

- **端到端交付成果**：学员（小店老板/电商卖家）录入菜品照片+价目+卖点后，带走一条每天自动生成 30 条带老板自己声音（GPT-SoVITS 克隆）配音与字幕的短视频成片+一张排期发布表的产线（**发布动作人工执行——平台无发布 API，课程明示该边界**）；另带走一个能听懂「这周主推毛肚，出 10 条强调性价比的」指令、自动调参重跑产线的 agent。**验收标准：录入自家 10 个 SKU 后现场产出 30 条成片+7 天排期表。**
- **免费单点能力（引流）**：①「一键白底图」MCP——[rembg](https://github.com/danielgatis/rembg) 封装（换开源权重，规避 bria-rmbg 商用付费）；②「盯价哨兵」——[changedetection.io](https://github.com/dgtlmoon/changedetection.io) 自托管配置模板，竞品/供货价变动即推送；③「差评雷达」skill——[uer/roberta-dianping](https://huggingface.co/uer/roberta-base-finetuned-dianping-chinese) 粗筛+LLM 归因生成回复话术草稿。
- **你需要准备什么（门槛）**：面向零技术店主——产线部署形态与课程一同构（Docker/n8n），但店主不碰命令行：课程方交付「一键 compose 全家桶」部署包（该打包是调研确认的开源空白，正是付费课必须自己承担的价值点，§2.2 空白⑥），店主只需填菜单/价目/卖点与提供 5 秒声音样本；产线可跑在店主自己的一台电脑或课程协助配置的小主机上。
- **开源技术栈**：[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)、[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)、[rembg](https://github.com/danielgatis/rembg)、[FunASR](https://github.com/modelscope/FunASR)、[CowAgent](https://github.com/zhayujie/chatgpt-on-wechat)（私域客服联动模块）、[n8n](https://github.com/n8n-io/n8n)、[FastMCP](https://github.com/jlowin/fastmcp)、[Langfuse](https://github.com/langfuse/langfuse)。
- **手册范式组件映射**：复用课程一的八对象骨架，差异点在信息对象治理——把「店铺资产包」（菜单/价目/卖点/老板音色样本）作为 Knowledge 与 Skill 资产独立建 Schema（写入门槛/版本回滚），而非混进向量库（手册明确 Memory/Knowledge 分治）；Output=成片+排期表（非直接发布）；Control=老板一句话指令需参数校验+影响预览。
- **agentsight 观测闭环接法**：成片采用率回流（哪类卖点/口播风格被排期采纳、哪类被老板弃用），匿名聚合后驱动「品类内容模板 skill」升级；叠加差评雷达的预警→回复采纳数据，形成店铺级数据飞轮。
- **可行性与竞争判断**：与课程一共享 5 个核心组件（MoneyPrinterTurbo/GPT-SoVITS/n8n/FastMCP/Langfuse），新增 rembg/FunASR/CowAgent 3 个组件，边际开发集中在行业模板与店铺资产 Schema——「开发成本低」的依据是组件复用度，非量化工时估算；本地生活痛点已获媒体验证（小店「开播难、成本高」）；竞争=代运营（贵、不可控）与 SaaS 工具（不私有、按月收租）。主要风险：平台数据侧全面空白（无对账/ROI 归因开源件），课程只能交付内容侧产线，需向学员明示；免费层「差评雷达」依赖的 [UER 情感模型](https://huggingface.co/uer/roberta-base-finetuned-dianping-chinese)「较老、无近期更新」（§2.1 资产表），粗筛质量风险需在上线前抽样人工校验评估（深度归因本就设计为走 LLM 路线，粗筛仅作第一道过滤）。

### 课程四：月度汇报生成器（公司里的打工人）

- **端到端交付成果**：学员下课带走一套「指向放原始 Excel 台账和工作备忘的文件夹→自动数据清洗统计（产出 3-5 张图表）→套用学员自己公司的 PPT 模板生成完整可编辑 pptx（非图片）→附一页 Word 版汇报摘要」的产线；另带走课程方帮其完成的公司 VI 模板工程（把配色/字体/版式沉淀成可复用、可校验的模板资产——调研确认的开源空白，自研壁垒）。**验收标准：用学员真实公司模板现场生成一份在真 PowerPoint 中打开不跑版的月度汇报 PPT。** 免费层送「单次生成」，付费交付整条产线+模板固化。
- **免费单点能力（引流）**：①「大白话查表」MCP——[PandasAI](https://github.com/sinaptik-ai/pandas-ai) 封装，对 CSV/Excel 自然语言提问；②「Excel 机器人」MCP——[excel-mcp-server](https://github.com/haris-musa/excel-mcp-server) 安装配置模板；③「PPT 半成品」skill——[PPTAgent](https://github.com/icip-cas/PPTAgent) 官方 skill 形态的接入模板。
- **你需要准备什么（门槛）**：会用电脑；本机即可，无需安装 Office——excel-mcp-server 无需装 Excel（调研原文）、MarkItDown 为 pip 安装、Word 产出走 fork 的 word-mcp；PPTist 在线改稿为课程提供的自部署 Web 服务。
- **开源技术栈**：[excel-mcp-server](https://github.com/haris-musa/excel-mcp-server)、[PandasAI](https://github.com/sinaptik-ai/pandas-ai)、[PPTAgent](https://github.com/icip-cas/PPTAgent)、[PPTist](https://github.com/pipipi-pikachu/PPTist)（在线改稿入口）、Office-Word-MCP-Server（fork）、[MarkItDown](https://github.com/microsoft/markitdown)、[n8n](https://github.com/n8n-io/n8n)、[Langfuse](https://github.com/langfuse/langfuse)。
- **手册范式组件映射**：Agent Contract（输入=台账文件夹+模板 pptx，输出=汇报 pptx+Word 摘要，验收=可编辑+模板保真）；Capability=read_excel/analyze/render_ppt/export_docx 四类工具；Quality=自研「模板保真校验器」（导出 pptx 在真 PowerPoint 不跑版——开源无此件，是 Evaluator 基线的核心）+图表数据抽检；Control=数据本地处理（工资表敏感）；Interaction=汇报前推送提醒。
- **agentsight 观测闭环接法**：每版 PPT 的人工修改 diff（哪页被重做、哪些图表被换）经 user feedback API 回流→「汇报结构 skill」与「图表选型 skill」升级；匿名跨学员聚合可发现行业级汇报模式（注意匿名化，consent 层把守）。
- **可行性与竞争判断**：汇报 PPT 是职场高频刚需（§2.2 需求②），付费意愿沿三级漏斗价格带推断、无品类专项数据；**本课资产链是五门中最薄的**（PPTAgent 5.1k★、PPTist 9.4k★、excel-mcp-server 4.2k★ 且 v1.0 发布于调研当日、单人维护）——这是它排第四而非更前的直接原因；付费交付前必须 fork excel-mcp-server 并做回归测试。PPTAgent 官方正在做 skill 形态（PPTAgent Skill）是双刃剑：借势之外，官方若直接免费提供 skill，免费层③「接入模板」的差异化会被压缩——本课可防御的壁垒在官方不会做的环节（公司 VI 模板工程+模板保真校验器+产线编排），免费层定位为获客而非壁垒。「AI 做 PPT」红海（SaaS 与课程都多），差异=自有模板保真+私有化+产线可复跑，不拼生成质量拼「像我公司出的」。

### 课程五：一份 SKILL.md，五个货架——agent 技能封装工坊（想自己搭工具的超级个体/开发者）

- **端到端交付成果**：学员下课带走 3 个可被 Claude/Codex/TRAE/Qoder 等大厂通用 agent 直接加载的自建能力：①「网页→干净 Markdown」（[Crawl4AI](https://github.com/unclecode/crawl4ai) 封 MCP）；②「替我操作这个网站」（[browser-use](https://github.com/browser-use/browser-use) 封 skill）；③「把本地软件变成 CLI 工具」（[CLI-Anything](https://github.com/HKUDS/CLI-Anything) 配方+FastMCP 壳）。全部按 [anthropics/skills](https://github.com/anthropics/skills) 规范打包成带 SKILL.md 的可分发 skill 包（按手册 Skill Package 标准：manifest 含 version/permissions/IO 与 acceptance contract，附 tests 与渐进式披露结构）。**验收标准：现场完成 GitHub 仓库发布 + WorkBuddy 或 Qoder 至少一个市场的提交流程，且在两个不同厂商的 agent 客户端中成功调用自己的 skill。** 另带走一条「任何新需求→现成能力」的封装 SOP。
- **免费单点能力（引流）**：①SKILL.md 脚手架生成器（按官方 template，自动规避「多余字段硬报错」的坑）；②「网页转 Markdown」MCP server 源码一份；③多市场上架检查单（开放标准字段 vs Claude 私有扩展对照表 + WorkBuddy/Qoder frontmatter 要求）。
- **你需要准备什么（门槛）**：五门中唯一需要技术背景的课程——命令行操作+基础 Python（FastMCP 为 Python 框架、MCP server 以 uvx/npx 分发）；零技术读者请选课程一至四。
- **开源技术栈**：[anthropics/skills](https://github.com/anthropics/skills)、[FastMCP](https://github.com/jlowin/fastmcp)、[Crawl4AI](https://github.com/unclecode/crawl4ai)、[browser-use](https://github.com/browser-use/browser-use)、[CLI-Anything](https://github.com/HKUDS/CLI-Anything)、[modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)（代码范本）、[n8n](https://github.com/n8n-io/n8n)、[Langfuse](https://github.com/langfuse/langfuse)。
- **手册范式组件映射**：本课交付物就是手册定义的 **Skill Package 本身**——manifest（name/version/owner/required tools/permissions/IO+acceptance contract）+ 三层渐进式披露（发现/选择/执行）+ Draft→Test→Review→Publish→Observe→Update 生命周期；「五个货架」（GitHub/WorkBuddy/Qoder/TRAE+开放标准客户端/MCP Registry）是分发面而非组件；Quality 组件=每个 skill 自带回归用例与验收契约。
- **agentsight 观测闭环接法**：本课是 agentsight 模式的示范田——学员上架的 skill 开启 opt-in 轨迹回流（Langfuse 自托管），「哪些工具被高频调用/在哪一步失败」驱动 skill 版本迭代，学员亲历「轨迹→数据集→评估→升级→权益」闭环；该闭环本身按手册「Observe→Update」阶段实现。
- **可行性与竞争判断**：资产全部一线活跃（178.8k/27.9k/84.4k/116.6k/50.8k）；WorkBuddy 2026-09-02 刚上线（其「10 万+ 生态资产」为平台自称、无第三方流量验证）、MCP Registry 免审核——占位定位为低成本试错而非押注。**变现缺口必须向学员明示**：五个货架当前均未验证变现——WorkBuddy 分成机制未披露、TRAE 上架通道未核实、MCP Registry 生态早期「变现无从谈起」、GPTs 官方分成名存实亡、国内小额收款开源空白（§3.3/§5.1.5）。因此本课的端到端承诺止于「可上架的 skill 包+上架与双端调用跑通」，**不含收入承诺**——学员把技能变成收入属课后自负环节，课程仅提供变现路径的现状说明（含局限）。受众盘子小于前四门且需技术背景；「豆包工作」等渠道未获调研证据，不写入承诺。战略价值最高：课程产物即雇主「把 AI 能力封装为 agent 技能」产品线的活样本与人才漏斗。

---

## 5. 空白、风险与下一步建议

### 5.1 生态空白（各人群共性问题）

1. **平台数据侧全面空白**：美团/饿了么/抖音本地生活商家后台的订单、账单、评价、核销数据无合规开源抓取或对账工具；平台 API 不对中小商家开放，爬后台有封号风险。对账与短视频 ROI 归因只能人工导出报表+自研解析（§2.1）。
2. **内容「最后一公里」空白**：自动合规发布到抖音/美团/点评的通道不存在；自媒体侧公众号数据采集已实质断裂（wechat-article-exporter 约 13k★ 因微信关闭核心接口于 2026-07-30 归档）。所有内容产线必须以「成片/草稿+排期表」收尾，发布动作留人工，商业交付内置「草稿+人工确认」兜底和失效告警（§2.1/§2.4/§2.5）。
3. **行业编排层缺失**：rembg/OCR/TTS/生成各自为战，没有面向小店老板开箱即用的「开店技能包」；Office 三件套+邮件+IM 无统一编排层；「脚本→素材→配音→字幕→渲染→发布」无成熟整链路 agent 化项目——这正是「免费送单点、付费交付端到端」的商业空间（§2.1/§2.2/§2.4）。
4. **中文垂直语料与评测基准缺失**：中文本地生活垂直模型/数据集为零（评论情感模型仍是 UER 时代老模型）；中文公文写作无高质量开源专项（GB/T 9704 版式/机关文种模板库语料库全无）；中文爆款短视频脚本数据集与「爆款率」评测集缺失——三者均需 prompt 自研+私域语料积累，也是课程壁垒（§2.1/§2.2/§2.4）。
5. **中国大陆小额收款空白**：Polar/Stripe 类开源方案不覆盖国内微信/支付宝个人收款+自动发货；「能力包→商品」之间还缺配额、限流、防滥用层——超级个体变现闭环的最后一环需自研（§2.6）。
6. **观测闭环无人做**：现有项目要么面向开发者团队、要么旁路截获（eBPF）、要么只做采集——没有人做「consent-first + 权益交换 + 轨迹自动沉淀为 skill 升级数据集」的完整闭环；自有 agentsight 的自建价值集中在授权与闭环编排（§3.1）。
7. **数字人线不可交付**：开源数字人 HeyGem 官方仓库已无法在 GitHub 检索到（仅剩 ≤499★ 第三方衍生版，官方状态未核实）；EchoMimic 更新停在 2024 年（V3 另仓）——「个人数字分身口播矩阵工厂」暂缓开课（§2.1/§2.4）。

### 5.2 资产生命周期与许可风险

1. **已归档/停更的关键上游**（付费交付前必须 fork 自维护+回归测试）：[IOPaint](https://github.com/Sanster/IOPaint)（2025-08 归档）、[DeOldify](https://github.com/jantic/DeOldify)（2024-10 归档）、[Office-Word-MCP-Server](https://github.com/GongRzhe/Office-Word-MCP-Server)（2026-03 归档）、wechat-article-exporter（2026-07 归档）、Flowise（2026-08 归档）；ShortGPT 活跃度未核实、GFPGAN/Real-ESRGAN/A1111 最后提交日期页面未显示（稳定经典但节奏放缓/停滞）。因此「老照片修复小作坊」与「数字分身工厂」两候选不进首批。
2. **单人维护的新件**：excel-mcp-server（v1.0 发布于调研当日）、comfyui-mcp-server（仅 9★，链路完整但未经大规模验证）、MediaCrawler/RedInk/Easel 等——进栈前需做 fork 预案。
3. **许可地雷清单**：n8n 为 fair-code 非 OSI 开源（商用需读条款）；AGPL 系（ComfyUI、A1111、PPTist、poster-design、pyvideotrans、RSSHub、guizang-social-card-skill、VoiceStudio、TagGUI、Allusion）有传染性，深度集成需法务评估；CC BY-NC 系（RedInk、hello-agents、部分 Datawhale 仓库）禁止直接商用正文；模型权重独立许可（rembg 默认 bria-rmbg 商用付费、IC-Light 依赖的 BRIA RMBG-1.4 仅限非商业、LivePortrait 的 InsightFace 权重仅限非商业研究——均需换开源权重才能商用）；Phoenix 为 ELv2；MediaCrawler 免责声明禁止商业用途；uer/roberta、Long-Novel-GPT、Qwen3 组织页许可未标注——使用前逐一核实。
4. **撞名风险**：自有 agentsight 与 [eunomia-bpf/AgentSight](https://github.com/eunomia-bpf/agentsight)（710★、MIT、arXiv:2508.02736 论文）撞名，且后者在 TLS 边界截获明文的路线与 consent-first 叙事相悖——对外命名与定位必须先切割（两者关系调研未核实）。

### 5.3 产品与合规风险

1. **发布自动化与平台风控的持续对抗是结构性风险**（视频/自媒体/门店三条线共用 social-auto-upload/Wechatsync/MultiPost 的浏览器自动化路线），随时可能失效，无开源兜底；商业承诺必须降级为「草稿+人工确认」并内置失效告警。
2. **采集合规**：MediaCrawler 类工具学习用途免责、商业用途被明确禁止；MediaCrawler/wechat 侧数据采集的合规边界需在课程中明示，采集类模块只做「读公开数据+人工导出兜底」。
3. **数据敏感与隐私**：打工人/店主场景涉及工资表、合同、录音、店铺经营数据——私有化部署是卖点也是责任；agentsight 的 consent 层（默认不采集+显式开关+匿名化）必须先于规模化管理落地。
4. **长程任务可靠性**：端到端交付有四大难点（验收标准、多步错误累积、边际成本不趋零、交付后维护责任）——产品从「半自主 agent+人工兜底+事先签好的验收清单」起步，选验收客观、交付可复跑的品类（本报告课程一/二/四均满足）。
5. **课程市场信任环境**：三级漏斗中间层是差评集中区（3980-7980 元档口碑差），定价避开该档；知识本身免费（hello-agents 81.1k★/llm-course 83.2k★/DeepLearning.AI 107 门免费短课），付费点只能落在交付/验收/担保。

### 5.4 下一步建议

1. **开发顺序（与「推荐优先级」的分叉说明，详见 §1）**：先做课程二（会议纪要，资产最稳+观测闭环最好接，其 Docker/MCP 组件直接复用为产品线底座）与课程一（短视频产线，资产链最强）的最小可跑版本——两条产线的 MCP 化节点直接沉淀为产品线的能力资产；课程三在课程一骨架上做行业模板（共享 5 个核心组件）；课程四待 excel-mcp-server 回归测试通过、PPTAgent skill 形态进一步稳定后跟进（其资产链为五门中最薄）；课程五与产品线同步（其交付物即产品）。推荐优先级押市场潜力，开发序押工程风险，两序分叉不矛盾。
2. **渠道占位（窗口期动作）**：立即以个人实名入驻 [WorkBuddy](https://open.WorkBuddy.cn)（2026-09-02 刚上线）与 [Qoder](https://www.qoder.com/marketplace)，把课程免费层的单点 skill（打字幕/抠图/录音转文字/网页转 Markdown 等）按「一份 SKILL.md 多货架」上架；MCP Registry 免审核发布元数据占位；GPTs 仅作获客入口。「豆包工作」等未获证据的渠道不写入对外承诺，待后续专项核实。
3. **agentsight 先做 consent 层与品牌区隔**：技术面全部复用现成（Claude Code 官方 OTel 开关、Langfuse OTLP 端点、OTel GenAI span 约定、FastMCP 打点），自研集中在薄 Collector processor（同意则注入 langfuse.user.id、不同意则丢弃）与「轨迹→匿名化数据集→skill 评估升级→权益兑现」管道；同时先解决与 eunomia-bpf/AgentSight 的命名区隔再对外传播。
4. **fork 自维护仓库清单**：付费交付前 fork Office-Word-MCP-Server、excel-mcp-server（回归测试）、comfyui-mcp-server（或以 FastMCP 自研替代），建立自己的回归用例集——这是「学员环境不随上游停更而坏」的保险，也是竞品难以快速复制的工程资产。
5. **模板工程提前投入**：公司 VI 级 PPT 模板固化、公文格式校验规则、店铺资产包 Schema（菜单/价目/卖点/音色）、爆款脚本语料库——四项均为调研确认的开源空白，是课程溢价与复购（skill 升级订阅）的根基。
6. **验收单即合同**：每门课的结业验收单直接采用手册 Agent Release 六要素清单（模型及路由/编排与配置/Prompt 与能力资产版本/Tool 与权限策略/Runtime 配置/评估数据集与基线）——「付费=端到端成果」的可审计落地形式。
7. **商业闭环补课**：国内小额收款+自动发货无开源方案，短期以人工发货+知识星球/私域收款过渡，中期自研「收款+配额」中间件（Polar 模式国内化）；定价避开 3980-7980 差评带，向「低价工具化」（免费/199 元引流层）与「按成果计价」（对齐 Lovable credits 模式）两端走。

---

*报告依据：本会话收到的 6 份人群调研与 4 份专题调研结果（含各资产 URL、star/提交数、许可、封装路径、空白与来源清单），「失败的调研路」为空。所有未核实项在正文中原位标注。报告撰写日期：2026-09-28。*
