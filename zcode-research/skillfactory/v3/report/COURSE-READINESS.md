# 五门课程就绪度对照报告（COURSE-READINESS）

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v3/report/COURSE-READINESS.md` |
| 日期 | 2026-09-30 |
| 输入材料（本会话全文实读） | ① `research/oss-research-report.md`（位于工作区根 `D:\workspace\zcode研究\research\`，不在 skillfactory/ 下；5 门课候选、端到端交付物定义、开源技术栈、空白与风险，§1/§2/§4/§5）；② `skillfactory/REGISTRY.md`（2026-09-30 台账，18 资产、本轮复跑记录、附录 A 核验记录）；③ `skillfactory/v2/plan/COURSE-ASSET-TIERS.md`（三层方案、课程×资产对照、榜单安置） |
| 本会话追加核实动作 | `ls` 实查 `dist/ assets/ v3/assets/ v4/assets/ v2/evalbench-v02/` 与台账一致；实读 `v4/assets/mcp-office-pack/package/mcp.office.json` 解析出 10 个 MCP server 名单；grep 实读 `v4/report/V7-FORGE-DELIVERY.md:106,133`（hot-templates 定位与 P0-1 欠账）；`ls` 确认 `standard/SKILL-SPEC-v0.1.md` 与 `v2/standard/EVAL-SPEC-v0.2.md` 在位 |
| 口径声明 | 本报告为**文档对照分析**：未重跑任何确定性评测、盲评或体检，全部评测数字转引 `REGISTRY.md` 的 2026-09-30 当日复跑记录；未实跑任何外部开源组件；未访问任何外部渠道（WorkBuddy/Qoder 等） |

**组件状态图例（四类）**：
- **【自产】** = 已自产（引台账路径与状态；注意「可分发」三包均待雇主批准，REGISTRY:142）
- **【外达标】** = 外部资产已过我方盲评达标线（全厂仅 lark-cli 一件）
- **【外未验】** = 外部候选未验（调研引用的高星开源件，未实跑、未过我方盲评）
- **【空白】** = 空白须生产（调研确认开源空白或自研环节未做）

---

## 课程一：日更短视频量产产线 + 调度 Agent（做视频的人）

**验收口径**（`oss-research-report.md:369`）：当天现场产出 ≥10 条成片，≥2 个平台进入草稿箱；交付到「草稿箱+排期表」为止，发布人工确认。

| # | 组件 | 状态 | 依据 |
|---|---|---|---|
| 1 | 脚本/内容骨架（四平台爆款模板） | 【自产】（带欠账） | `dist/hot-templates-skill`（RC 形态）：盲评 Δ+6.10 / 100% 全胜 accepted（厂史最高），体检 A；但按 SKILL-SPEC §4 五门口径欠账未清（效率门未测、每臂 2<3、benchmark.json 未落盘，REGISTRY 注 2）——V7 原要求复检通过前不进分发（`v4/report/V7-FORGE-DELIVERY.md:133`）；V7:106 明确它是课程一脚本环节**增强件**，不是免费单点三件 |
| 2 | 文案合规打分（dy/xhs/wx 极限词） | 【自产】 | `v4/tools/content-evaluator`：内部就绪，本轮复跑 6/6 exit 0（REGISTRY:36） |
| 3 | 配音：GPT-SoVITS 克隆音色 | 【外未验】 | 62.2k★，调研 §4 课程一技术栈引用；未实跑 |
| 4 | 字幕：whisperX 逐词对齐 | 【外未验】 | 24.3k★；未实跑 |
| 5 | 素材采集：yt-dlp | 【外未验】 | 194k★；未实跑 |
| 6 | 合成：MoneyPrinterTurbo / MoviePy | 【外未验】 | 126.5k★ / 14.9k★；未实跑 |
| 7 | 发布草稿：social-auto-upload | 【外未验】 | 15.2k★；平台风控对抗为结构性风险（调研 §5.3.1），「草稿+人工确认」兜底与失效告警机制【空白】 |
| 8 | 编排：n8n workflow | 【外未验】 | 206k★；fair-code 非 OSI 开源，商用须读条款（调研 §5.2.3） |
| 9 | 调度入口：FastMCP 封装「处理今天的选题表」 | 【空白】 | 全链路编排与 MCP 化为调研确认空白（§2.4 空白③），自研胶水 |
| 10 | 中文爆款脚本语料 | 【空白】 | §2.4 空白④，需自研积累 |
| 11 | 观测闭环：Langfuse + consent 薄 Collector | 【外未验】+【空白】 | Langfuse 35.1k★ 未自托管实跑；consent processor（同意注入 user.id/不同意丢弃）为自研件（§5.4.3） |
| 12 | 免费单点三件（打字幕 skill / 我的声音 MCP / 素材入库 skill） | 【空白】 | 未生产；调研 §4 课程一引流件原清单（`oss-research-report.md:371`） |
| 13 | Docker 一键部署包 | 【空白】 | §2.2 空白⑥，付费课承担的价值点 |
| 14 | 「现场 10 条」计时试跑 | 【空白】 | 验收目标值未经验证，调研明示开课前必须用学员典型硬件试跑（`oss-research-report.md:369`） |

**就绪度评级：有硬缺口。** 一句话理由：核心五环（配音/字幕/采集/合成/发布）全部是未实跑的外部件，免费单点三件与全链路编排未生产，验收目标值「现场 10 条」从未计时试跑——自产件只覆盖脚本增强与合规打分两个辅助环节。

---

## 课程二：会议纪要一条龙产线（公司打工人）

**验收口径**（`oss-research-report.md:379`）：用自己的真实录音现场跑出格式合规的三段式 Word 纪要 + 至少一条已登记催办任务。

| # | 组件 | 状态 | 依据 |
|---|---|---|---|
| 1 | 三段式纪要生成 skill（docx，逐字溯源） | 【自产】★核心 | `dist/meeting-minutes-skill` v1.0.0：**可分发**（待雇主批准）——确定性 20/20、盲评 v0.2 Δ+5.25 / 100%（8/8）/ 反向 0 accepted、体检 A 三门齐（REGISTRY:14,138） |
| 2 | 中文办公文书模板（字体字号规范类能力） | 【自产】 | `dist/office-templates-skill` v1.0.0：可分发（待批准），68/68、Δ+1.20 / 100% accepted——对外须标 `single_round_signal`（二轮未做，REGISTRY:15,146） |
| 3 | 转写 ASR：FunASR 官方 MCP | 【外未验】 | 20.5k★；未实跑；CPU 转写速度调研未采集、开课前须实测（`oss-research-report.md:381`） |
| 4 | 文档转 Markdown：MarkItDown | 【外未验】 | 187k★ 微软官方；未实跑 |
| 5 | Word 成品：Office-Word-MCP-Server 自维护 fork | 【外未验】+【空白】 | 上游 2026-03 已归档，付费交付前必须 fork + 回归（§5.2.1）——fork 与回归用例未做 |
| 6 | 催办编排：n8n 待办登记+邮件 | 【外未验】 | 206k★；未实跑 |
| 7 | MCP 安装配置包（excel/word/powerpoint 等 10 server） | 【自产】 | `v4/assets/mcp-office-pack`：内部就绪，eval 5/5，oracle validate 7/7，10/10 协议握手实录（REGISTRY:34）；本会话实读 `mcp.office.json` 确认含 filesystem/excel/word/powerpoint/google-workspace/gmail/playwright/excel-npm/tavily/context7 |
| 8 | 验收集（中文办公 50 题×230 checks） | 【自产】 | `v4/assets/office-eval-suite`：内部就绪，4/4 ALL GREEN（REGISTRY:35） |
| 9 | 护栏 hook（产物 fail-closed + PII 拦截） | 【自产·待迭代】 | `v3/assets/office-guard-hooks`：确定性 7/7 过，但体检 C（2/5：缺 front-matter 三字段、缺 eval/、缺 scripts/，REGISTRY:30）——作治理随行件前须修复 |
| 10 | 飞书生态扩展模块 | 【外达标】 | `v2/evalbench-v02/lark-cli`：v0.2 Δ+1.6875 / 75%（6/8）/ 反向 0，accepted=true（REGISTRY:42）；注意 t1–t4 为文档比对级证据，实跑补验是打包前置 |
| 11 | 说话人映射交互（SPEAKER_00→王总） | 【空白】 | 调研确认开源空白（§2.2 空白②），课程自研壁垒（`oss-research-report.md:379`） |
| 12 | 单位词表热词管理 | 【空白】 | 同上（§2.2 空白⑦），课程自研壁垒 |
| 13 | 一键 compose 私有化部署包（数据不出本机） | 【空白】 | §2.2 空白⑥；「数据不出本机」是本课核心卖点，打包工作须自己承担 |
| 14 | 观测闭环（转写→生成→催办逐步打点） | 【外未验】+【空白】 | 调研认定六门课中最好接（`oss-research-report.md:384`），但 Langfuse 实跑与 consent processor 均未做 |

**就绪度评级：组件齐待集成。** 一句话理由：唯一已过三门（确定性+盲评+体检 A）的核心 skill 现成，配置包/评收集齐，缺的只是说话人映射、热词表、compose 部署包三件自研与 FunASR 实跑集成——全是集成工作量而非组件缺口，与三层方案「首发试点」定位一致（`COURSE-ASSET-TIERS.md:101`）。

---

## 课程三：门店短视频内容工厂（开店的人）

**验收口径**（`oss-research-report.md:389`）：录入自家 10 个 SKU 后现场产出 30 条成片 + 7 天排期表；发布动作人工执行。

| # | 组件 | 状态 | 依据 |
|---|---|---|---|
| 1 | 内容脚本骨架 | 【自产】（带欠账） | `dist/hot-templates-skill`（同课程一 #1，五门欠账未清） |
| 2 | 文案合规打分 | 【自产】 | `v4/tools/content-evaluator`（同课程一 #2） |
| 3 | 老板音色配音：GPT-SoVITS | 【外未验】 | 62.2k★；未实跑 |
| 4 | 合成：MoneyPrinterTurbo | 【外未验】 | 126.5k★；未实跑 |
| 5 | 一键白底图：rembg | 【外未验】+【待办】 | 24.9k★；默认权重 bria-rmbg 商用付费，**换开源权重的改造未做**（§2.1 资产表、`oss-research-report.md:390`） |
| 6 | ASR：FunASR | 【外未验】 | 20.5k★；未实跑 |
| 7 | 私域客服联动：CowAgent | 【外未验】 | 47.1k★；未实跑 |
| 8 | 盯价哨兵：changedetection.io 配置模板 | 【外未验】 | 34.6k★；配置模板未做 |
| 9 | 差评雷达：uer/roberta 粗筛 + LLM 归因 | 【外未验】 | 模型较老无近期更新，粗筛质量须上线前抽样人工校验（`oss-research-report.md:395`） |
| 10 | 编排（n8n）+ 自然语言调度入口（FastMCP） | 【外未验】+【空白】 | 同课程一 #8/#9 |
| 11 | 店铺资产包 Schema（菜单/价目/卖点/音色，独立建 Schema+版本回滚） | 【空白】 | 调研确认开源空白、本课差异化所在（§5.4.5、`oss-research-report.md:393`） |
| 12 | 一键 compose 全家桶（零技术店主不碰命令行） | 【空白】 | 付费核心价值点（§2.2 空白⑥、`oss-research-report.md:391`） |
| 13 | 行业内容模板（菜品/商品场景） | 【空白】 | 边际开发集中处（`oss-research-report.md:395`），未生产 |
| 14 | 观测闭环（成片采用率回流） | 【外未验】+【空白】 | 同课程一 #11 |

**就绪度评级：有硬缺口。** 一句话理由：完整继承课程一的全部未验外部件与空白，另加店铺资产 Schema、零技术部署包、行业模板三件自研空白——缺口集合是五门中最大之一，只能跟随课程一骨架排产（`COURSE-ASSET-TIERS.md:103`）。

---

## 课程四：月度汇报生成器（公司打工人）

**验收口径**（`oss-research-report.md:399`）：用学员真实公司模板现场生成一份**在真 PowerPoint 中打开不跑版**的可编辑月度汇报 PPT + 一页 Word 摘要。

| # | 组件 | 状态 | 依据 |
|---|---|---|---|
| 1 | Excel 台账→图表+汇报 PPT 生成器 | 【自产·待迭代】★核心 | `assets/monthly-report-ppt`：**下发 evalPassed=false**（确定性门未过）；本轮盘内存量产物复跑 16/16 exit 0 但不推翻下发判定，须按同一版 golden 复裁落盘（REGISTRY:26）；未盲评、未体检 |
| 2 | PPT 制作方法意图路由 | 【自产·待迭代】 | `assets/ppt-method-router`：确定性 6/6 过，但盲评 Δ0 / 33%（1胜1负1平）未达线——路由对但端到端零增益（REGISTRY:27） |
| 3 | Excel 读写：excel-mcp-server | 【外未验】 | 4.2k★ 单人维护，付费交付前须 fork+回归；LEADERBOARD 中期信号 Δ+0.67 / 2胜1平**未过线**，复检前不作最终结论（`COURSE-ASSET-TIERS.md:220,225`）；其安装配置已含于 `v4/assets/mcp-office-pack`【自产】 |
| 4 | 数据分析：PandasAI | 【外未验】 | 23.8k★（ee 目录企业版许可须注意）；未实跑 |
| 5 | 模板 PPT 生成：PPTAgent | 【外未验】 | 5.1k★（体量五门最小，`oss-research-report.md:405`）；官方正做 skill 形态，免费层差异化受压缩 |
| 6 | 在线改稿入口：PPTist | 【外未验】 | 9.4k★，AGPL-3.0 传染性须法务评估；未实跑 |
| 7 | Word 摘要：word-mcp fork | 【空白】 | 上游 Office-Word-MCP-Server 2026-03 归档，fork+回归未做（§5.2.1） |
| 8 | 公司 VI 模板工程（配色/字体/版式沉淀为可复用资产） | 【空白】 | 调研确认开源空白、本课自研壁垒（`oss-research-report.md:399`） |
| 9 | 模板保真校验器（「不跑版」Evaluator） | 【空白】 | 开源无此件（`oss-research-report.md:403`）——**验收标准本身直接依赖这个尚不存在的组件** |
| 10 | 验收基建（中文办公评测集） | 【自产】 | `v4/assets/office-eval-suite`（同课程二 #8） |
| 11 | 观测闭环（人工修改 diff 回流） | 【外未验】+【空白】 | 同前 |

**就绪度评级：有硬缺口。** 一句话理由：核心自产件 monthly-report-ppt 未过确定性门（下发口径仍为 false），而验收口径「真 PowerPoint 不跑版」所依赖的模板保真校验器是开源空白、尚未开始自研——资产链本就是五门最薄（`oss-research-report.md:405`）。

---

## 课程五：一份 SKILL.md，五个货架——技能封装工坊（超级个体/开发者）

**验收口径**（`oss-research-report.md:409`）：现场完成 GitHub 仓库发布 + WorkBuddy 或 Qoder 至少一个市场提交流程，且在两个不同品牌 agent 客户端中成功调用自己的 skill。

| # | 组件 | 状态 | 依据 |
|---|---|---|---|
| 1 | 工厂 SOP 教材（SPEC+评测协议+上架 SOP+体检样例） | 【自产】 | `standard/SKILL-SPEC-v0.1.md`、`v2/standard/EVAL-SPEC-v0.2.md` 本会话 ls 确认在位；三层方案判「现成」（`COURSE-ASSET-TIERS.md:105`） |
| 2 | 正反教学案例（4 进 1 出实录） | 【自产】 | meeting-minutes（全胜 Δ+5.25）/ hot-templates（Δ+6.10）/ ppt-method-router（零增益 Δ0）/ paper-to-skill（负增益 Δ−0.5，全批唯一负增益）——REGISTRY:25-28 各行 |
| 3 | hooks 反面教材（「教学材料≠可用资产」） | 【外达标·不采用】 | `v2/evalbench-v02/hooks-mastery`：Δ−0.67，accepted=**false**，我方不迭代、维持禁挂，仅作课程五教材（REGISTRY:43） |
| 4 | 体检流水线（体检报告即分发物料） | 【自产】 | `v3/tools/healthcheck`：内部就绪，oracle 对拍 15/15=100%（REGISTRY:31） |
| 5 | SKILL.md 脚手架生成器（免费单点①） | 【空白】 | 未生产（`oss-research-report.md:410`） |
| 6 | 「网页转 Markdown」MCP 源码（免费单点②） | 【空白】 | Crawl4AI 封装未做（本体 84.4k★【外未验】） |
| 7 | 多市场上架检查单（开放标准 vs Claude 私有字段对照，免费单点③） | 【空白】 | 未生产（`oss-research-report.md:410`） |
| 8 | 封装栈：FastMCP / browser-use / CLI-Anything / anthropics/skills | 【外未验】 | 27.9k / 116.6k / 50.8k / 178.8k★，全部一线活跃但未实跑 |
| 9 | 货架实测（WorkBuddy/Qoder 提交流程走通） | 【空白】 | 渠道占位动作未做（§5.4.2）；TRAE 上架通道调研亦未核实 |
| 10 | 观测闭环示范田（学员 skill opt-in 回流） | 【外未验】+【空白】 | Langfuse 未实跑；consent 管道自研未启动 |

**就绪度评级：组件齐待集成。** 一句话理由：教材主体（SOP+四个正反案例+体检器+规范）全部自产现成，缺的是三个免费单点生产、货架提交流程实测与 D90 前的教材化改造（排期口径 `COURSE-ASSET-TIERS.md:105`）——且本课排期本就最晚，不阻塞其他课。

---

## 汇总：五门课就绪度总表

| 课程 | 评级 | 自产达标件 | 外部已达标件 | 主要硬缺口 |
|---|---|---|---|---|
| 二 会议纪要 | **组件齐待集成** | meeting-minutes-skill（三门齐）、office-templates-skill、mcp-office-pack、office-eval-suite | lark-cli | 说话人映射、热词表、compose 部署包、FunASR 实跑 |
| 五 技能封装 | **组件齐待集成** | SOP+4 案例+healthcheck+SPEC | 无 | 三个免费单点、货架流程实测、教材化改造（hooks-mastery Δ+0.70 / 60% **accepted=false** 仅作教材，不满足达标定义——2026-09-30 审读修正：原错置于外达标列，与 #3 行及图例矛盾） |
| 一 短视频 | **有硬缺口** | hot-templates（带欠账）、content-evaluator | 无 | 五环外部件全未实跑、免费单点三件、全链路编排、「现场 10 条」试跑 |
| 三 门店工厂 | **有硬缺口** | 同课程一 | 无 | 课程一全部缺口 + 店铺 Schema + 零技术部署包 + 行业模板 + rembg 换权重 |
| 四 月度汇报 | **有硬缺口** | monthly-report-ppt（**未过确定性门**）、ppt-method-router（盲评未达线）、office-eval-suite | 无（excel-mcp-server 中期信号未过线） | 核心件复裁返工、模板保真校验器（验收依赖它）、VI 模板工程、excel-mcp fork 回归 |

**结论：0 门可立即开课；2 门组件齐待集成（课程二、五）；3 门有硬缺口（课程一、三、四）。** 这与三层方案开课进入条件一致——「≥2 门课端到端产线可复跑且现场验收彩排通过」尚未满足任何一门（`COURSE-ASSET-TIERS.md:112`），免费层引流基线（F5 私域 ≥300）与收款通路也未就绪。

---

## 下一波生产建议（nextWave，按「开课最快收益最大」排序）

1. **课程二三件自研空白生产：说话人映射交互 + 单位热词表 + 一键 compose 部署包**——把唯一「组件齐待集成」的端到端课推到试点就绪，其核心 skill（meeting-minutes-skill）已三门达标可直接内嵌，做完即锁死首发位置。
2. **课程二真实录音计时彩排（验收口径：三段式纪要 + ≥1 条催办任务）**——直接兑现 D60 试点 1 期（KPI P1），同场实测 FunASR CPU 转写速度（调研明示开课前必测项）。
3. **hot-templates 五门复检清账（V7 P0-1：补效率门 + 每臂 3 重复 + benchmark.json 落盘）**——一次动作同时解锁课程一/三脚本增强件的合规使用与免费层第二件上架（厂史最高盲评 Δ+6.10，收益杠杆最大）。
4. **课程一免费单点三件生产（whisperX 打字幕 skill / GPT-SoVITS 我的声音 MCP / yt-dlp 素材入库 skill）**——课程一与课程三共享的前置件，生产即免费层上架物，同时倒逼三个核心外部件首次实跑。
5. **课程一整链计时试跑（选题清单→成片→草稿箱，学员典型硬件）**——「现场 10 条」验收目标值从未验证（调研明示开课前必须试跑），试跑数据直接决定课程一/三能否排期与验收口径是否需降级。
6. **monthly-report-ppt 按同一版 golden 复裁落盘**——课程四唯一核心自产件目前下发 evalPassed=false（盘内 16/16 复跑不推翻下发判定），复裁是课程四排期讨论重启的前提动作。

---

*本报告由课程对照师会话产出（2026-09-30）。全部评测数字转引 `REGISTRY.md` 2026-09-30 复跑记录，本会话未重跑评测；外部组件成熟度转引 `research/oss-research-report.md`，本会话未实跑、未回访外部 URL。*
