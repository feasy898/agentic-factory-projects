# 治理面输出方案——个人版与企业版

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/plan/治理面输出方案.md` |
| 版本 | v0.3（2026-09-29；v0.2 同日早稿的修订版） |
| 定位 | 把 CloudCrane 治理体系（建设方案 v2.0 回并版）裁剪成两类可售输出：个人版治理随行包、企业版治理套件；并规定 skill/MCP 资产的注入与管理、与 CloudCrane 的逐项对接、风险红线 |
| 上位输入 | ① `D:/workspace/阿里agent能力全调研/建设方案-v2.0.md`（现行验收基准，本会话全文读取 312 行）；② `建设方案-v2.1.md`（已降为变更说明与存档——v2.0.md:3-8 基准标注，本会话全文读取 253 行）；③ 首批技能资产四项（本轮任务下发台账，与本会话读取的各资产 `tests/ab_summary.json` 逐项比对一致）；④ `skillfactory/standard/SKILL-SPEC-v0.1.md`（本会话全文读取 386 行）；⑤ 背景约束：雇主自有观测项目与 eunomia-bpf/AgentSight 撞名且路线相悖，对外命名必须切割、观测必须 consent-first（任务下发；`research/oss-research-report.md:280`、`阿里agent能力全调研/阿里Agent基础设施全景与自研内核选型报告.md:137` 本会话实读佐证） |
| 关系文档 | `skillfactory/plan/总体方案.md`（商业总体：本文是其「治理随行包/治理面托管」两条线的展开）；`skillfactory/standard/SKILL-SPEC-v0.1.md`（资产门禁，全文有效） |
| v0.3 变更 | ① 首批资产台账改用**本轮铸造权威数字**（任务下发 = 盘内 `tests/ab_summary.json`）：meeting-minutes Δ=4.33/胜率 1.0（v0.2 所载 1.67/0.67 为上一轮盲评快照，已被本轮取代）；ppt-method-router Δ=0/胜率 0.33（原 0.67/0.67）；paper-to-skill Δ=−0.5/胜率 0（原 −0.5/0.5）；验收结论不变：**仅 meeting-minutes 接受，1/4 过线**（§0.2 披露）；② 两轮盲评数字漂移（1.67→4.33、0.67→0）作为治理事实入册，强化评测记录落盘纪律（§0.3 P0-1）；③ 三资产盲评迭代方向按**本轮判词**重写（§0.3 第 5 项）；④ 全部核验命令由本轮会话实际执行并留档（§0.1、附录 A）。 |

---

## 0. 材料实态与本轮实测核验（先说结论：一处口径更新 + 三处工程欠账）

### 0.1 本轮实际执行的检查（全部本会话运行）

| # | 检查 | 命令 / 方法 | 结果 |
|---|---|---|---|
| V0 | 盲评数字对账 | 读取三资产 `tests/ab_summary.json` 并与本轮任务下发数字比对 | **逐项一致**：meeting-minutes Δ=4.333/胜率 1.0（3 任务，10 vs 5.67，3:0 全胜）；ppt-method-router Δ=0/胜率 0.333（3 任务，8.67 vs 8.67，1 胜 1 负 1 平）；paper-to-skill Δ=−0.5/胜率 0（2 任务，8.5 vs 9，1 负 1 平） |
| V1 | 四资产确定性评测复跑 | 各目录 `python eval/runner.py <tested> <reference>` | **四项全部 exit 0**：meeting-minutes 20 checks 全过（含 case4 全零边界）；monthly-report-ppt 16 checks 全过（3 产物单元：页数/图表/重算/脏数据/页差）；ppt-method-router method 一致率 20/20=100%≥80%；paper-to-skill 五要素齐/6 步可判定/13 项统计偏差最大 0.0%≤30% |
| V2 | monthly-report-ppt 是否抄参照产物 | `diff <(cd oracle/out && find . -type f -exec sha256sum {} \;) <(cd package/out && …)` | **15/15 文件哈希全部不同**——现存 `package/out` 是真实被测产物，V1 的通过不是同哈希假阳性 |
| V3 | 评测记录落盘 | `find assets -name "benchmark.json"`（排除 .mimosa） | **四资产均无 `eval/results/benchmark.json`**，`protocol.md` 亦均缺（SPEC §1.1「入库必带」、§4「验收记录必须落盘」不满足） |
| V4 | 发布件 | `find assets -name "MANIFEST.json"` | **四资产均无**（SPEC §1.1/§2.5 发布必须） |
| V5 | front-matter 必填六字段 | 逐包 `awk` 读取 `package/SKILL.md` 头部 | meeting-minutes、paper-to-skill 六字段齐；**monthly-report-ppt、ppt-method-router 仅 name+description**，且 description 未按 §1.3 三段式 |
| V6 | 打包卫生 | `ls -la paper-to-skill/NUL` | 456 字节杂散文件在位（违反 SPEC §1.1 补充规则 3 禁占位/临时产物） |
| V7 | 资产根 CHANGELOG | 逐资产根检查 | 仅 meeting-minutes 在位（含 specfix 1.1 完整记录）；**其余三个资产根缺失** |
| V8 | Langfuse 云可达性 | `curl https://cloud.langfuse.com/api/public/health` | **HTTP 200（1.28s）；根路径 200**——windev-01 出口可达。口径限制：单机单网单时点测量，非终端用户侧网络测量，不构成 SLA 承诺 |
| V9 | 引用行号核验 | `sed -n` 逐一抽验 | oss-research-report.md :32/:269/:277/:279/:280/:282/:374 与 survey 报告 :137/:138/:275、`build/cnb-company-knowledge/reports/06-龙蜥AgenticOS.md:48` 全部命中原文 |
| V10 | 同仓文档数字对账 | `grep -n "1.67\|0.67" plan/总体方案.md` | `总体方案.md` v1.0 与本文 v0.2 所载仍为**上一轮**盲评数字（meeting-minutes Δ=1.67/0.67 等），已被本轮取代——见 §0.2 披露 |

### 0.2 首批资产台账（权威口径 = 本轮任务下发，与盘内 ab_summary.json 互证）

盲评门判定式：`SKILL-SPEC-v0.1.md:271`——treatment 均分 − baseline 均分 **≥1.0 且胜率 ≥60%**，双条件与门。

| key | 确定性门（下发/本轮复跑） | Δ / 胜率（下发=盘内） | 盲评门判定 | **下发验收** | 盘内佐证（本轮判词要点） |
|---|---|---|---|---|---|
| meeting-minutes | 过 / exit 0 | **4.33 / 1.0** | 4.33≥1.0 且 100%≥60% → 过 | **接受为资产** | `tests/ab_summary.json`：3 任务 10 vs 5.67 全胜；treatment 产物与官方参照 oracle 逐字全同、官方 runner 满分通过；baseline 实测被抓出无编号条目/表格粘前缀溯源失败/负责人语义猜测三处技能合规硬伤 |
| monthly-report-ppt | **不过（下发，铸造时点）** | —（盲评臂无落盘记录：盘内无 `tests/` 目录） | 未进入盲评 | **不接受——资产或实现需返工** | 本轮复跑现存产物 exit 0 且 15/15 哈希异于 oracle（V1/V2），失败轮现场未归档，原因无法回溯；接受与否待按 SPEC §4 门 1 对同一版 golden.json 全量重跑并归档后裁定 |
| ppt-method-router | 过 / exit 0 | **0 / 0.33** | 0<1.0 → 不过 | **不接受——技能本体或 spec 需迭代** | `tests/ab_summary.json`：3 任务 8.67 vs 8.67（1 胜 1 负 1 平）；负场判因=treatment 清理了复跑临时证据致复现链不可独立复核、且缺对任务三问的专门作答节；平局场双方 rubric 全过、各有一项对方不具备的强项 |
| paper-to-skill | 过 / exit 0 | **−0.5 / 0** | −0.5<1.0 且 0%<60% → 不过 | **不接受——技能本体或 spec 需迭代** | `tests/ab_summary.json`：2 任务 8.5 vs 9；ab-001-rename baseline 9 : treatment 8——treatment 缺可运行参考实现（baseline 的 qc_check.py 实跑 29 项全过）、漏 POSIX 平台差异坑、产物 SKILL.md 混入评测元叙事；ab-002 双臂 9:9 平 |

**口径披露（如实）**：① 本文 v0.2 与 `总体方案.md` v1.0 所载为上一轮盲评快照（meeting-minutes Δ=1.67/0.67、ppt-method-router 0.67/0.67、paper-to-skill −0.5/0.5），本轮铸造已重跑双臂，**以本轮台账为准**；验收结论两轮一致（1/4 过线，均为 meeting-minutes）。② **两轮数字漂移（1.67→4.33、0.67→0、判词构成亦变）本身是治理事实**：在 §0.3 P0-1（`eval/results/benchmark.json` 落盘 + golden 版本冻结）落地前，任何 Δ/胜率都只是当轮快照，不构成资产的可复核属性——这正是 SPEC §3.2 规则 4 与 §4 落盘纪律要防的事，首批就发生了。影响：过盲评门资产基线为 **1/4**（总体方案 KPI「基线 1」维持），阶段 1「课程二首发」进入条件（meeting-minutes 过门）仍成立且本轮余量更足（4.33/1.0）。

### 0.3 工程欠账与 P0 返工单（输出管线开通的前置）

三资产「确定性评测通过」可信（V1 复跑佐证），但**「可分发」均不成立**：评测记录落盘（V3）、MANIFEST（V4）、部分形式条款（V5）、打包卫生（V6）、CHANGELOG（V7）未齐。返工单：

1. 四资产补齐 `eval/results/benchmark.json` + 五门验收单落盘（SPEC §4）；盲评数字按 §0.2 台账登记**本轮**数值并注明轮次与「本会话未复跑双臂」；此后每轮盲评数字只增不改、旧轮归档（防再漂移）。
2. 四资产生成 MANIFEST.json（逐文件 sha256；SPEC §2.5）；删除 `paper-to-skill/NUL`。
3. monthly-report-ppt / ppt-method-router：front-matter 补齐六字段、description 改三段式（SPEC §1.2/§1.3），补资产根 CHANGELOG；暂不补者按 SPEC §6.3 书面豁免（豁免不构成先例）。
4. monthly-report-ppt 按 SPEC §4 门 1 对同一版 golden.json 全量重跑并归档失败轮现场后，再裁定接受与否；此前维持下发结论，不进分发。
5. **两项盲评迭代（按本轮判词定向）**：
   - **ppt-method-router**：把「证据留存与作答结构」从运气变成技能契约——负场败因（复跑临时捕获被清理、无对任务三问的专门作答节）与平局判词（「复跑证据仅断言记录未落盘独立文件」）都指向同一件事：**SKILL.md 正文必须规定每次运行落盘原始 stdout + sha256 溯源清单、输出报告强制「逐问作答」节**；差异增益必须体现在 rubric 可分维度上，而非路由算法本身（两臂算法输出完全一致——20/20 一致率是护城河也是盲评拉不开差距的原因，需在 ab_tasks 中增加「路由质量可分」的任务型用例）。
   - **paper-to-skill**：按 ab-001-rename 三处败因修模板——①蒸馏模板**必须**要求产出可运行的参考实现并实跑验证（rubric 把「实测可运行」判为差异项）；②坑点清单**必须**含平台差异类（POSIX/Windows 行为分叉，如 `os.rename` 静默覆盖）；③产物 SKILL.md **禁止**混入评测元叙事（「treatment 组」「评测装置」等词全部不得出现在交付文本）。
6. build.py 渠道变体生成器最小实现（standard + claude-code 两变体；SPEC §1.5.2）。

---

## 1. 总裁剪原则：四圈 → 三件可售输出

CloudCrane 四圈（theory/product/line/exec，v2.0 §1.1）中，**theory（治理参考）与 exec（执行面）整体不输出**——前者是内部宪法，后者绑定 jiuwenswarm/provider 池等自有设施。可售的是 **product（控制面）的部分对象** 与 **line（生产线）的资产方法论**，收敛为三件：

| 可售输出 | 内容 | 面向 |
|---|---|---|
| A. 个人版治理随行包（工作名 **skilldock**） | skill 注入器（本地 SkillFS 式目录管理+格式校验）、consent 开关、轻量观测 shim（skilldock-lens）、升级权益兑现 | 个人客户/课程学员 |
| B. 企业版治理套件（工作名 **skilldock-registry** 及配套） | 私有 skill registry、审计计量（usage_events 观念）、租约与权限中介裁剪版、定制 holdout 评测服务、升级阶梯企业映射 | 企业客户 |
| C. 资产分发体系（不单独卖，A/B 共用） | build 渠道变体、MANIFEST/sha256 双钉、评测报告随包、失效停更流程、MCP 通道 | 全部 |

继承 CloudCrane 设计原则中直接可售的四条（v2.0 §0）：**fail-closed**（原则 2：校验不过拒装、无评测报告不可分发）、**决策唯一**（原则 3：装/卸/回滚只由 skilldock 一个工具裁决）、**自动化可逆优先**（原则 7：升级失败自动回退 fallback，破坏性动作人工批准）、**凭证最小驻留**（原则 9：观测上报令牌可撤销、不进 skill 包内）。数据主权（原则 8）在企业版落为 self-host 选项。CloudCrane 两层观测（System→Langfuse；Behavior→ATIF→MinIO，v2.0 §4.4）在输出面只保留 System 层的 Langfuse 通道；Behavior 层的内核级采集路线**不输出**（与 §6 R1 命名切割联动，亦合 survey 报告 :275「内核级采集不建议自研」结论）。

---

## 2. 问一：输出给个人客户——最小可用包

### 2.1 最小可用包（skilldock v0）= 四件

**（1）skill 注入器：本地 SkillFS 式目录管理 + 格式校验。**
- 目录管理实现 SkillFS 的**三态语义**：`current`（生效）/ `fallback`（可信快照，回退即用）/ `hidden`（停用——宿主查找返回不存在）（出处：`阿里agent能力全调研/阿里Agent基础设施全景与自研内核选型报告.md:138`「三态决策 current/fallback/hidden」、`build/cnb-company-knowledge/reports/06-龙蜥AgenticOS.md:48`「live/快照/隐藏三态」）。但 **v0 用目录级实现（state.json + 目录切换），不做 FUSE**——SkillFS 原生是 Rust FUSE + K8s sidecar 形态（06-龙蜥:48），对个人客户装机摩擦过大；FUSE 版与句柄级版本固定（survey:138）列 P2。
- 格式校验 = SKILL-SPEC §1 可机判子集：name==目录名、六必填字段、description≤1024 字符单行、正文≤500 行且≤10,000 字符、eval 四件在位、MANIFEST 逐文件 sha256 复核。**fail-closed：任一不过拒装**（CloudCrane 原则 2），错误信息指到具体条款。
- 安装目标按宿主约定（SPEC §1.5.2 通用规则 1：Claude Code `~/.claude/skills/` 或项目 `.claude/skills/`、Qoder `~/.qoder-cn/skills/<kebab>/SKILL.md`、Kimi `KIMI_SKILLS_ROOT` 等）。
- **不做常驻全量注入**：Symphony 式「按需展示」在此简化为 description 触发 + 文档地图表（SPEC §1.3/§1.4 已承载）——检索式按需加载是学术与官方双重共识（SPEC §0.2；arXiv:2608.23067 实测无差别注入通常让 agent 更差，转引自 SPEC 附录 C）。

**（2）consent 开关（consent-first，默认关）。**
- consent ledger 本地落盘 `~/.skilldock/consent.json`：`consent_id / 事件范围白名单 / 版本 / 授予时间 / 撤销方式`；云端兑换时同步登记。
- 事件范围白名单（默认全部关闭）：skill 触发/完成/失败、版本、耗时、宿主类型、token 用量（宿主可得时）。**prompt 正文与文件内容永不在白名单内**；可选 `prompt_hash`（SHA-256 截断）须单独勾选。
- 一键撤销：撤销后本地缓冲删除 + 云端停止接收 + **已获权益保留**（事前承诺，写入权益条款）。

**（3）轻量观测 shim（工作名 skilldock-lens）。**
- **路线与 eunomia-bpf/AgentSight 明确切割**：不做 TLS 边界截获、不做 eBPF/uprobe、不需 sudo——该路线「仅 Linux+sudo 且在 TLS 边界截获明文，与用户主动同意叙事相悖」（`research/oss-research-report.md:277`；技术面 uprobe 挂 `SSL_read/SSL_write` 加密前抓明文见 `阿里agent能力全调研/阿里Agent基础设施全景与自研内核选型报告.md:137`）。lens 只走**应用层显式通道**：宿主官方 hook / OTel 导出（Claude Code 原生 OTel 导出为范本，`oss-research-report.md:277`）+ 包内 scripts 可选打点，产出 OTel GenAI span。
- 上报端：个人版走 **Langfuse 云**（OTLP 端点、user/session 标识语义，`oss-research-report.md:32`）。**可达性已由本会话实测**：windev-01 出口 `curl https://cloud.langfuse.com/api/public/health` → HTTP 200/1.28s（V8）；仍保留双通道预案——① edge-server 自建多租户 Langfuse（srv-1 已有 langfuse-web+worker 建成与运维经验，v2.0 §4.1）；② 纯本地模式（只落本地 NDJSON，权益降级为体检报告自评版）。**无论哪条通道：consent gate 在最前——未同意一律丢弃，同意则注入 user/session 后放行**（薄 Collector processor 模式，`oss-research-report.md:279`）。
- 端侧脱敏默认开：手机号/身份证/邮箱/IP/银行卡等模式（字段集先例见 survey 报告 :137 端侧脱敏清单）。

**（4）升级权益兑现。**
- 权益目录（consent 换）：① 资产库全量解锁 + 月度新资产包；② 每季个人资产健康体检报告（基于回流轨迹+回归评测）；③ 新版 skill 免费升级推送——「轨迹→数据集→skill 升级→用户获新版」闭环，生态空位已核实：8 次中英检索未发现先例（`oss-research-report.md:282`）。
- 兑现机制：兑换码/订阅态 → 服务端签发 `SKILLDOCK_CONSENT_TOKEN` → lens 凭 token 上报；撤销=吊销 token（凭证最小驻留，原则 9）。付费档（C2）增加定制评测额度。

### 2.2 客户分级 C0–C3（刻意与 CloudCrane L0–L5 错开命名，防混用）

| 层 | 定位 | 内容 |
|---|---|---|
| C0 免费 | 铺量获客 | 注入器 + 格式校验 + 3 个基础资产（不带观测） |
| C1 权益层 | consent 兑换 | 开观测 → 全资产库 + 月度包 + 新版推送 |
| C2 订阅层 | 付费 | C1 + 季度体检报告（评测回归版）+ 定制评测额度 + 优先支持 |
| C3 定制通道 | 通向企业版 | 转 §3 企业套件销售线索 |

### 2.3 部署形态

| 形态 | 接法 |
|---|---|
| 本机 agent（Claude Code / zcode / Kimi Code / Qoder / TRAE 本地） | `pipx install skilldock` → `skilldock install <name>` 写宿主技能目录；观测经宿主官方 hook/OTel 配置注入（Claude Code 官方开关零开发回流，`oss-research-report.md:374`）；无 hook 能力的宿主降级为包内 scripts 可选打点（**观测不可用≠注入器不可用**，功能分级） |
| 云端 agent（云沙箱/创空间/容器化 agent） | ① 镜像预装：Dockerfile 层装 skilldock + 资产 bundle + 预校验（build 时跑校验器，运行时 fail-closed 复核 sha256）；② entrypoint 拉取：启动时按 registry 钉定版本拉取+校验后装。consent 在云端以 `SKILLDOCK_CONSENT_TOKEN` 环境变量表达（企业/平台代个人持有 consent 时必须在协议中写明代持条款） |
| 托管对话平台（WorkBuddy 类，无本地文件系统） | 见 2.4 专项路径——注入退化为「文本上架」，观测退化为平台内反馈件，lens 标注「不支持」 |

### 2.4 与 WorkBuddy / Qoder / TRAE 等宿主的兼容路径

总策略 = SPEC §1.5.2 的**三要素最大公约数**（name/description/SKILL.md）+ build 变体 + 渠道校验器前置；禁深度定制、禁独家（SPEC §1.5.2 规则 4）。

| 宿主 | skill 注入路径 | 校验 | 观测接法 | 依据 |
|---|---|---|---|---|
| WorkBuddy | **纯文本形态**：standard 变体文本经开放平台上架/配置（其 Skill=纯文本提示词零代码） | 上架前本地跑 skills-ref validate（standard 变体必须过，SPEC §1.5.2 规则 3） | 无本地通道 → 平台内反馈/导出件替代，lens 标注「不支持」 | SPEC §1.5.1 矩阵 WorkBuddy 列（纯文本直接兼容；Expert/Connector 为平台私有层） |
| Qoder | 本地目录 `~/.qoder-cn/skills/<kebab>/SKILL.md` 直装 | 对齐其 catalog 逐文件 sha256 惯例 → MANIFEST 双向校验 | 无公开 hook 证据 → 降级可选打点 | SPEC §1.5.1 Qoder 列 |
| TRAE | agentskills.io 采纳方，standard 变体 + 内置技能市场上架 | 渠道校验器 | 同上降级 | SPEC §0.2（40+ 客户端采纳） |
| Claude Code | `~/.claude/skills/`；cc-only 变体生成 when_to_use 等增强字段（`<!-- cc-only -->` 标注可剥离） | 官方文档约束 | **原生 OTel 导出 + 官方 hooks（lens 首发宿主）** | SPEC §1.5.1；`oss-research-report.md:277` |
| 千问运行时 | qwen 变体（snake/camel 双写、zip≤20MiB 安审） | 官方安审 | 缺原生支持 → 网关/baseURL 桥或降级 | SPEC §1.5.1 |
| 豆包 | doubao 变体（requires.bins/cliHelp 映射 + agents/ interface yaml） | 渠道校验器 | 不适用（平台内闭环） | SPEC §1.5.2 变体表 |

**个人版 MVP 验收口径（DoD）**：在 Claude Code 与 Qoder 两个宿主上，用 skilldock 从零完成「装 meeting-minutes → 触发 → 出纪要 → 卸载」全流程；consent 关闭时 `~/.skilldock/` 外无任何网络外联（可关网复测）；consent 开启时 Langfuse 收到 span 且 span 内无正文（抽查字段）。

---

## 3. 问二：输出给企业客户

### 3.1 私有 skill registry

- **条目模式直接复用 company-assets 资产 YAML**（v2.0 §12：位置指针 / **sha256 钉** / 生命周期态 / 关联边带资产级别 / 运维规定引用）——不发明新格式。载体为企业自有私有 git 仓（审计友好）+ 对象存储（分发）。
- 新建**只读 registry API + 简单报表页**：列包/列版本/下载带 MANIFEST/评测报告下载/生命周期态查询。企业内准入 = PR 入库 + CI 跑渠道校验器（复用 v2.0 §13「五类元数据准入」与 §14「一切变更走 PR」纪律）。
- 起步形态可以只是 Git 仓 + 脚本（无服务），registry API 是 M 级增强——先卖流程与仓，再卖服务。

### 3.2 审计与计量（usage_events 观念）

- 沿用 **usage_events append-only + 业务字段**口径（v2.0 §4.4：append-only；`customer_id/project_id/settlement_class`；`window_id/expires_at/meter_type`；`source_id`；影子成本），企业裁剪为**单表起步**：谁（agent/人身份）/ 哪个 skill+版本 / 事件类（install/run/fail/rollback/consent_change）/ 时间窗 / 计量值 / 来源。
- 采集端新建：skilldock 本地 NDJSON 缓冲 → 批量上报企业后端（Postgres）；上报与企业观测共享 consent gate（企业内部合规以制度+入职协议表达，技术上仍默认最小字段）。
- 审计三件：装包审计（谁在何时装了哪个 sha256 的包）、版本变更审计（current 切换历史）、consent 变更审计——全部落同一 append-only 表，只增不改。
- 对账观念（v2.0 §7 上游计量对账）：若企业按 token 计量结算，预留 `source_id` 对上游账单日/周对账，>2% 偏差告警（阈值沿 v2.0 §7 口径，同时是 key 泄露探测信号）。
- tenant 观念先行：单表即带 `tenant_id` 列（v2.0 §4.2 tenant_id 贯通【建成·未复核】、tenant 表+RLS 未落地〔缺口〕——企业版 v1 单租户部署可绕过 RLS，但列名与语义从第一天对齐，避免日后迁移）。

### 3.3 租约与权限中介的裁剪版

保留 glue 已修复的核心语义，裁掉重基础设施：

| 保留 | 裁掉 | 落地形态 |
|---|---|---|
| 租约对象四元组：资源+操作+期限+撤销；**凭证是租约的兑现物**（v2.0 §2 术语）；级联撤销（W-01 修复：终态父不阻断后代撤销，回归测试在位，v2.0 §3.2） | Higress consumer key 绑定（默认不要求企业上 Higress）、OPA 全量策略引擎、三层身份+五交集（identity/challenge） | 「技能使用租约」：agent 身份 × skill/工具域（映射 SKILL front-matter `permissions` 枚举 shell/network/fs-write/browser/user-handoff，SPEC §1.2）× TTL × 撤销；短时 token 铸造沿 platform_tokens 模式（TTL≤1h、禁缓存禁代签，v2.0 §4.5） |
| 缩权数据驱动/扩权人工（v2.0 §4.5 方向） | — | 收紧可自动（事件触发），扩权走 §3.5 人工清单 |

状态声明：leases/platform_tokens 在 CloudCrane 均为【建成·未复核】（v2.0 §4.2），输出给企业前必须完成对所用子集的针对性复核（见 §6 R5）。

### 3.4 定制 holdout 评测服务

- 每客户一套**对实现方不可见**的 holdout 集：三道隔离裁剪版（v2.0 §4.6：独立仓 + 专用凭证仅评测进程持于 tmpfs + 运行只在评测机）——企业 v1 可裁为「客户托管仓 + 一次性注入评测机的短时凭证」。
- 裁决分层照搬：verdict 纯机器（golden.json checks 机判，SPEC §3.1 同构），归因标签仅 advisory；失败反馈 = 归因标签 + 公开 spec 引用，不泄题。
- 轮换免读密流水线照搬（模型从公开分类法起草 → 程序化查重 → 人抽查 → 原子换批；v2.0 §4.6）；use_count/暴露巡检 runner 侧已实测落地（v2.0 §4.6 缺口登记），run 级 GuardrailRun 记录为〔缺口〕——企业版以评测报告本身作 run 记录，不强依赖 glue 接线。
- 交付物：月度评测报告（分数趋势/回归项/与基线差/与个人版 C0–C2 报告同渲染管线）。这是**最高毛利件**：它把 skillfactory 的评测护城河（总体方案 §3.3）直接变成企业服务。首批资产两轮盲评的数字漂移教训（§0.2）直接进入该服务的交付纪律：**每期报告钉死 golden 版本 + 当轮原始记录归档**，数字只增不改。

### 3.5 升级阶梯的企业映射

L0 执行→L1 同事→L2 协调者→L3 值班工程师(提权租约)→L4 守门者(全景只读+跨框批准)→L5 人类；**升级的是权限/工具/上下文而非模型**；守门者人类就绪包四件套（事实固定/范畴清晰/权限内无解证明/可逆性评估）；人类专属四类硬清单（金钱/法律 ToS/不可逆/theory.Approval）不在表内打回 L3；组织学习（同类升级 3 次=权限扩展提案）与风暴防护（级内限次/回退≤1/签名去重）——全部语义直采 v2.0 §4.7。

企业落点（新建为适配层）：
1. L0–L5 映射企业 RACI：执行 agent→业务 owner；每级配「升级即工单」模板（工单正文=就绪包四件套字段，**缺字段工单不成立=fail-closed**）。
2. 审批落点=企业 IM 审批 webhook（钉钉/飞书/企微）作为 L4/L5 闸口；批准记录回写 §3.2 审计表。
3. 硬清单四类在企业侧固化为「永不自动化」配置项；组织学习信号输出为月度「权限扩展提案」清单供 owner 裁决。

---

## 4. 问三：skill 与 MCP 资产的注入与管理

### 4.1 版本与回滚（三态生命周期）

- 版本 = SPEC §1.2 semver，行为变化必须 bump + CHANGELOG；skilldock 只装 registry 中钉定 semver 的包。
- 生命周期：`install`（校验+钉 sha256）→ `current`；`upgrade` 先写 `fallback` 快照，升级后回归失败（跑 `eval/runner.py`，exit≠0）**自动切回 fallback**（CloudCrane 原则 7 可逆优先）；`disable` → `hidden`（宿主查找不可见，文件保留）；`rollback` = current↔fallback 切换，秒级、无需网络。
- 「打开后后台切版本」的句柄级并发一致性 v0 不解决（FUSE 版的 P2 目标，survey:138）；v0 以「升级前检测正在运行的宿主会话并提示」缓解。

### 4.2 sha256 双钉

- 包内：MANIFEST.json 逐文件 sha256 + 大小 + 总数（SPEC §2.5，Qoder catalog 模式）。
- registry：资产 YAML 对发布 zip 整体 sha256 钉（company-assets 模式，v2.0 §12）。
- 安装时逐文件校验，**不匹配拒装并报差异文件**（fail-closed）；渠道下载后先验 zip 钉再解包验 MANIFEST。分发一律附来源与哈希清单供买方自证安全（ClawHub 恶意 skill 事件后「可审计的干净 skill」本身是卖点；SPEC §2.5 第 4 条）。

### 4.3 渠道矩阵

| 变体 | 目标 | 生成要点 |
|---|---|---|
| standard | agentskills.io/Qoder/WorkBuddy/claude.ai/Skills API/TRAE | version/permissions 收进 metadata；按需 compatibility |
| claude-code | Claude Code/插件市场 | `<!-- cc-only -->` 标注段生成增强字段，无标注不生成 |
| doubao | 豆包 | requires.bins/cliHelp 映射 + agents/ interface yaml |
| qwen | 千问 | snake/camel 双写；zip≤20MiB |

（SPEC §1.5.2 全文为执行依据。）渠道新增按「三要素是否兼容」一票判定；渠道校验器入 CI，每次发布全变体跑一遍。

### 4.4 评测报告随包分发

- 发布包必含 `eval/results/benchmark.json` + 五门验收单 + 由其渲染的 REPORT.md（双臂均分±标准差/逐对胜负/token 与耗时比率/golden 版本/已知局限）；**缺报告 = 不可分发**（fail-closed；当前四资产缺口见 §0.3 P0-1）。
- 报告随包走三处：包内 `eval/results/`（买方自验）、registry 报表页（企业采购评审）、个人版权益页（C1/C2 权益兑现物）。
- 盲评门不过的资产（ppt-method-router/paper-to-skill 现状）**同样不可分发**；迭代修订版的 baseline 臂 = 旧版快照（SPEC §3.3 规则 2），修复后对同一版 golden 重评；报告标注盲评轮次（首批教训：轮间数字会漂移，§0.2，落盘纪律是唯一解）。

### 4.5 失效与停更策略

- 生命周期态枚举（沿 company-assets 生命周期态概念，v2.0 §12）：`active → frozen → deprecated → hidden → retired`。
- 资产失效走**失效证明**（eval 只增不删；v2.0 §5.2 纪律），禁止静默下架；`deprecated` 态在 description/metadata 打 `deprecated-by` 指针并给出替代 skill。
- EOL 节奏：公告（30 天）→ `hidden`（新装不可见，存量可用）→ `retired`（registry 移除，归档保留 sha256 供溯源）。安全事件（如脚本漏洞）：**立即 hidden + 全渠道通告 + 订阅用户推送**，不等待公告期。
- 平台侧停更风险（渠道倒闭/审核下架）：canonical 源始终在自有 GitHub 仓 + registry，渠道只是货架（总体方案 §4.6 纪律 3 的资产侧落实）。

### 4.6 MCP 资产通道

- 分工沿 SPEC §0.2 第 2 条：skill 管程序性知识、MCP 管连接器；不重复造连接器。
- skilldock 对 MCP 提供三件：① `mcpServers` 配置片段生成（按宿主格式）；② **版本钉**（npx/pip 包 `@exact` 版本 + server 实现仓 commit sha 钉入配置，防 supply chain 漂移）；③ 启动前校验（包存在性 + 声明的工具清单核对）。MCP server 风险高于 skill（任意代码），**consent/权限提示强制**：凡声明 network/fs-write 的 server，注入时向用户展示权限清单确认。
- fork 自维护清单（Office-Word-MCP-Server 已归档、excel-mcp-server 单人维护——总体方案 §4.4 进入条件 ③）作为 MCP 通道上架前置。

---

## 5. 问四：与 CloudCrane 的对接路径（逐项）

量级口径：**S ≤3 人日；M ≤2 人周；L 2–6 人周**（粗估，非排期承诺；一人全职折算）。「现状」列照录 v2.0 口径。

### 5.1 直接复用（语义/模式原样拿走）

| CloudCrane 组件 | 现状 | 输出用途 | 量级 |
|---|---|---|---|
| guardrail `aggregate` 三态聚合（fail-closed 空集→UNKNOWN，v2.0 §3.1） | 建成·未复核 | 企业装包前校验门、评测门聚合 | S |
| evidence 三态语义（v2.0 §3.4 负边界资产在位） | 在位 | 评测报告与验收单的证据语义 | S |
| escalation L0–L5 + 就绪包四件套 + 签名去重（v2.0 §4.7） | 建成·未复核（W-06） | 企业升级阶梯（§3.5） | S（语义）+M（适配） |
| usage_events 字段口径（v2.0 §4.4） | 建成·未复核；tenant 表+RLS 未落地〔缺口〕 | 企业计量表 schema（§3.2） | S（schema） |
| holdout_runner 裁决分层/轮换免读密/use_count 巡检（v2.0 §4.6） | 建成·未复核；run 级记录〔缺口〕 | 定制 holdout 服务（§3.4） | S（方法）+M（服务化） |
| company-assets 资产 YAML（sha256 钉/生命周期态/关联边，v2.0 §12） | CNB 单主仓；GitCode 镜像/周 bundle〔缺口〕 | 企业 registry 条目模式（§3.1） | S |
| 假设登记处/tripwire 机制（v2.0 §12） | 设计条款 | 本文 §6 三大假设的管理形式 | S |
| Langfuse self-host 部署经验（srv-1 langfuse-web+worker，v2.0 §4.1） | 建成 | 企业观测后端模板；个人版备选通道（§2.1） | S |
| Skill 起步包/五类元数据准入/配置决策树（v2.0 §13） | 设计条款 | 企业 skill 准入流程模板 | S |

### 5.2 裁剪复用（拿语义、换载体）

| CloudCrane 组件 | 裁剪方式 | 量级 |
|---|---|---|
| leases（W-01 级联修复后，v2.0 §3.2） | 去掉 Higress/OPA 依赖，落为「技能使用租约」表+短时 token（§3.3） | M |
| platform_tokens（v2.0 §4.5） | 保留短时铸造语义（TTL≤1h/禁缓存禁代签），去多 GitHub App 场景 | M |
| signals（signal_inbox 七类，v2.0 §4.2） | 裁为单类：客户 badcase/升级信号收件箱 | S |
| billing（v2.0 §4.2） | 不输出结算骨架；企业对账单=报表查询（轻报表并入 §3.2） | S |
| 两层观测（v2.0 §4.4） | 只输出 System→Langfuse 通道；Behavior 层（ATIF/内核级采集）不输出——与 §6 R1 命名切割同源 | S（口径） |
| SkillFS 三态（ANOLISA 参考，survey:138） | 目录级三态实现，不做 FUSE（§2.1）；FUSE+句柄级版本固定列 P2 | M（v0） |
| Symphony 按需展示（v2.0 §13） | 简化为 description 触发 + 文档地图表（SPEC §1.3/§1.4 已承载），不做独立发现服务 | S |
| OpenBao 凭证模式（v2.0 §4.1） | 企业已有密钥设施时的对接适配器；个人版不输出 | M（可选） |

### 5.3 不输出（内部件，保持边界）

decision(s)（outcome 回填〔缺口 G-1〕）、admission/ablation/promotion、fleet/e2b_compat/console-tui、routes/rules、selection/statebuilder/meta_governance、spec-gate 六维（技能域门禁已由 SKILL-SPEC 五门承担）、line.Selection、OPA/Higress（企业可选接，另立项目）、Temporal/意图层/拉动引擎、jiuwenswarm/provider 池/沙箱三 backend。**输出面与内部面之间沿用 v2.0 §1.2 依赖单向纪律：输出组件只引内部对象 ID，不反向依赖。**

### 5.4 新建（CloudCrane 没有的）

| 新建件 | 内容 | 量级 |
|---|---|---|
| skilldock CLI | 目录管理/三态/格式校验/sha256 复核/consent ledger/回滚（§2.1/§4.1） | M |
| skilldock-lens | 宿主 hook 适配 + OTel GenAI span + 端侧脱敏 + consent gate（§2.1） | M–L |
| 观测云端通道 | Langfuse 云可达性已实测（V8）；余下多租户接入 + 本地积压补报 | M |
| 权益后端 | 兑换码/订阅/权益目录/token 签发与吊销（§2.1） | M |
| registry API+报表页 | 只读查询/报告下载/生命周期态（§3.1） | M |
| 体检报告渲染器 | benchmark.json → REPORT.md（总体方案 §3.4 已列） | S |
| MCP 通道 | 配置片段/版本钉/权限确认（§4.6） | S–M |

---

## 6. 问五：风险

### R1 命名切割（最高优先）

**事实**：GitHub 可检索到的 AgentSight 是 eunomia-bpf 的 eBPF 项目（MIT、710★、arXiv:2508.02736 + ACM 论文），在 TLS 库边界截获明文（`research/oss-research-report.md:269/280`，本会话实读）；我方自有观测项目与其**撞名且路线相悖**（任务下发约束）。调研另记录阿里系 ANOLISA/AgentLoop 的 AgentSight 同为 eBPF uprobe 加密前抓明文路线（survey 报告 :137；且其已被产品化为 LoongCollector 采集接入，survey:275「内核级采集不建议自研」）。

**切割动作（全部 P0）**：
1. 对外产品一律不带 sight/AgentSight 词根——本文工作名 skilldock / skilldock-lens；**定名前必须完成 GitHub/npm/PyPI/商标四重查重**（每项留存检索截图入假设台账）。
2. 自有 agentsight 内部代号退役：开源仓改名或归档，README 顶部声明「与 eunomia-bpf/AgentSight 无关，不做 TLS 边界截获，仅 consent-first 应用层上报」。
3. 对外话术、课程教材、本文所有分发物料统一用新名+路线声明。
4. 不引用对方论文/仓库作技术背书。
5. 每季按 SPEC §6.2 节奏复查搜索结果（撞名搜索是 tripwire：新同名项目出现→登记并评估）。

### R2 隐私与合规

- **硬条款（产品行为，非话术）**：默认不采集；同意范围白名单枚举且不含正文；一键撤销且撤销即删本地+停报云端；端侧脱敏默认开；上报令牌可吊销。技术形态=薄 Collector processor（未同意→丢弃，`oss-research-report.md:279`）。
- PIPL 口径：处理前告知（同意页明示字段清单与留存期）+ 最小必要（白名单即边界）+ 删除权（撤销即删）；未成年人不开放 C1 以上权益。
- 企业版数据主权：Langfuse/registry/计量全部支持 self-host 部署于客户环境（原则 8 存储自建为主，v2.0 §0）；我方只在评测机处理客户 holdout，凭据 tmpfs、评测后即焚（§3.4）。
- 残余风险如实声明：云端观测通道经第三方（Langfuse 云/云厂商）。**可达性已实测**（V8：windev-01 出口 200），但终端用户侧网络表现与数据出境路径未实测——验证前不向 C1 用户承诺 SLA，权益条款写明「观测中断按本地记录折算」。

### R3 平台依赖

- 平台政策随时可变（WorkBuddy/Qoder/TRAE 均无分成证据的「圈量期」判断与跟踪信号，总体方案 §4.1/§4.6）：不赌分成、不签独家、三要素最大公约数+可剥离变体（SPEC §1.5.2 规则 4）；渠道校验器入 CI，规格季审（SPEC §6.2）。
- 宿主 hook 能力差异：观测/注入功能分级降级（观测不可用≠注入器不可用，§2.3）；每宿主一份「支持矩阵」随包发布，不夸大承诺。
- Langfuse 云/单一后端依赖：本地 NDJSON 积压 + 可切换 self-host（§2.1 双通道）；权益兑现不完全依赖观测在线。

### R4 供应链与安全

skill 含可执行代码：发布五步自检 + MANIFEST + 体检报告（SPEC §2.5）；skilldock 安装校验 fail-closed（§4.2）；scripts 禁收凭据/禁越声明域外传（SPEC §2.5 第 3 条）；MCP 通道版本钉+权限确认（§4.6）。

### R5 内部件状态风险（对 CloudCrane 的诚实依赖声明）

本方案引用的 glue 对象（guardrail/leases/usage/escalation/holdout_runner 等）在 v2.0 口径下均为**【建成·未复核】**，且存在已登记缺口（跨圈失效传播未实现 v2.0 §3.3；tenant 表+RLS 未落地；holdout run 级 GuardrailRun 记录未接线）。**对外输出承诺前，必须对实际用到的子集完成针对性复核**（对应 CloudCrane W-02 收口或单独复核工单）；复核未过则输出面降级为「语义重实现」——本文各节均已写成不依赖 glue 运行时的形式，重实现成本即 §5.1/§5.2 所列 S/M 量级，不会导致方案失效。

---

## 7. 路线图（与总体方案 D0–90 对齐）

| 阶段 | 治理面动作 | 出口判据 |
|---|---|---|
| P0（立即） | §0.3 返工单六项；agentsight 命名切割五动作（R1）；ppt-method-router 与 paper-to-skill 盲评迭代重评（§0.3-5） | benchmark.json 落盘×4（含本轮数字+轮次标注）；新名查重留痕；两项盲评达 Δ≥1.0 且胜率≥60% 或明确拆分/降级裁决 |
| D0–30 | skilldock CLI v0（目录三态+校验+sha256+回滚）；consent ledger；Claude Code/Qoder 双宿主 DoD（§2.4）；build.py 两变体 | MVP 验收口径全过；C0 上线首批过验收资产（当前仅 meeting-minutes） |
| D31–60 | skilldock-lens（Claude Code 首发宿主）；观测通道上线（云通道已验证可达，按 V8+终端侧复测结果定云/自建）；权益后端 MVP（兑换码）；badcase 信号收件箱 | C1 权益闭环首个真实用户走通；consent 关闭零外联复测通过 |
| D61–90 | 企业版试点 1 家：registry 仓模式+计量单表+租约裁剪版+holdout 评测服务首单；升级阶梯工单模板交付 | 首份客户 holdout 月报交付（golden 钉版+原始记录归档）；企业试点复盘（Go/No-Go 进总体方案阶段 2/3 评审） |

---

## 附录 A：本轮实测记录（可复跑）

```text
工作目录：D:\workspace\zcode研究\skillfactory\assets
V0 cat {meeting-minutes,ppt-method-router,paper-to-skill}/tests/ab_summary.json
   → delta/winRate 与本轮任务下发逐项一致（4.333/1、0/0.333、−0.5/0）
V1 python <asset>/eval/runner.py <asset>/package/out <asset>/oracle/out   # ×4 资产，均 exit=0
   meeting-minutes: 20 checks 全过（4 case，含 case4 全零边界；溯源/计数/表格/节标题全 PASS）
   monthly-report-ppt: 16 checks 全过（3 产物单元：pptx≥4 页/图表内嵌/18 项重算一致/脏数据规则/页差=0）
   ppt-method-router: method 一致率 20/20=100% ≥ 80%
   paper-to-skill: 五要素齐/6 步可判定/13 项统计偏差最大 0.0% ≤30%
V2 diff <(cd monthly-report-ppt/oracle/out && find . -type f -exec sha256sum {} \;|sort) \
        <(cd monthly-report-ppt/package/out && …)   # 15/15 哈希全部不同
V3/V4 find assets -name benchmark.json / MANIFEST.json（排除 .mimosa）→ 零命中
V5 逐包 awk 抽 front-matter → monthly-report-ppt/ppt-method-router 仅 name+description；
   meeting-minutes/paper-to-skill 六字段齐
V6 ls -la paper-to-skill/NUL → 456 字节在位
V7 逐资产根 ls CHANGELOG.md → 仅 meeting-minutes 在位
V8 curl https://cloud.langfuse.com/api/public/health → 200（1.28s）；根路径 200
V9 sed -n 逐一抽验 research 与 survey 报告行号 → 全部命中
V10 grep -n "1.67" plan/总体方案.md → v1.0 仍载上一轮数字（已被本轮取代，§0.2 披露）
```

未复跑项（如实声明）：双臂盲评（Δ/胜率为本轮任务下发数字，与盘内 `tests/ab_summary.json` 逐项一致，本会话未重跑双臂）；Langfuse 云的终端用户侧网络表现与数据出境路径；eunomia-bpf/AgentSight 仓库本轮未直接访问（数据转引自 `research/oss-research-report.md:269/280`，该两行为本会话实际读取）。

## 附录 B：引用索引

- CloudCrane：`D:/workspace/阿里agent能力全调研/建设方案-v2.0.md`（§0 原则、§1.1 四圈、§1.2 依赖单向、§3.1/3.2 缺陷修复、§3.3 跨圈传播缺口、§4.2 glue 表、§4.4 观测计量、§4.5 权限中介、§4.6 holdout、§4.7 升级体系、§5.2 元门禁、§12 登记处、§13 团队与 SkillFS、§15 路线图）；`建设方案-v2.1.md`（基准标注：降为变更说明与存档）
- 标准：`skillfactory/standard/SKILL-SPEC-v0.1.md`（§1 格式/兼容矩阵/变体、§2 红线、§3 评价、§4 五门——盲评门判定式在 :271、效率门 :272、§6 修订）
- 资产：`skillfactory/assets/{meeting-minutes,monthly-report-ppt,ppt-method-router,paper-to-skill}/`（本会话实查 + runner 实跑 + ab_summary.json 对账；meeting-minutes CHANGELOG specfix 1.1 在位）
- 生态：`D:/workspace/zcode研究/research/oss-research-report.md`（:32 Langfuse；:269/:280 AgentSight 撞名；:277 Claude Code OTel 与 eBPF 路线相悖；:279 薄 Collector consent；:282 生态空位；:374 观测闭环接法）
- 阿里系参考：`D:/workspace/阿里agent能力全调研/阿里Agent基础设施全景与自研内核选型报告.md`（:137 AgentSight eBPF uprobe+端侧脱敏字段集；:138 SkillFS 三态+句柄级版本固定；:275 内核级采集不建议自研）；`build/cnb-company-knowledge/reports/06-龙蜥AgenticOS.md:48`（SkillFS FUSE 三态）
- 同仓文档：`skillfactory/plan/总体方案.md`（治理随行包、阶段 2/3、D0–90；其 v1.0 所载首批资产数字为上一轮快照，出入见 §0.2 披露）

*（治理面输出方案 v0.3 完；命名均为工作名，定名前按 R1 查重流程执行。）*
