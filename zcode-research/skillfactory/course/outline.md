# 课程大纲（Phase 3）——「agent 资产产线」系列课

> 定位：每节课 = 带学员用一个真实入册资产，走通一次可验收的真实交付。
> 承诺边界（全课程统一）：只承诺「学员当场走通真实交付的过程」，不承诺任何就业、收益、涨粉、效果类结果。
> 资产池（REGISTRY 行号为准）：HW hotwords L162 ｜ DP deploy-pack L163 ｜ SM speaker-mapping L164 ｜ zctl-mcp（2026-10-02 登记节）｜ acceptor-agent（同上）。

## 第 0 讲（引流课，45 分钟）：同一个任务，裸 agent vs 带资产 agent

- 课堂动作：现场跑两组对照——裸跑（凭空写）vs 资产跑（`eval/runner.py` 绿门 + 红门演示）；
- 学员带走：6 条命令的复现手册（walkthrough 第 0 步 + 第 1 课基线）；
- 验收点：学员本机 exit 0/1 与讲师一致（确定性即卖点）；
- 转化钩子：引到第 1 讲（正式课入口）。

## 第 1 讲（2 小时）：会议转写 → 说话人映射，一次可验收的交付（SM，L164）

- 交付物：学员本地产出 `out/student_run1/`（24 文件），评测 4/4 exit 0；
- 知识点：契约冻结（contract §3 cwd/stderr 口径）、红路 fail-closed 为什么是信用底线；
- 课前准备：Python 3.12 + 仓库克隆（handbook §三）；
- 彩排状态：✅ round-1 已通过（record.md）。

## 第 2 讲（2 小时）：一条命令生成三服务部署包（DP，L163）

- 交付物：`out/student_pack1/`（docker-compose.yml + .env.example + DEPLOY.md），validate 7 pass + 评测 4/4；
- 知识点：生成器与校验器分离；密钥占位红线（C4）如何内嵌进资产；
- 彩排状态：✅。

## 第 3 讲（2 小时）：热词表管理器——最小但完整的工具资产（HW，L162）

- 交付物：`out/oracle_student/out/`（manifest + 10 步快照）+ 自己的 funasr 导出文件；
- 知识点：操作序列快照即证据；为什么「重复 add 报错」也是契约的一部分；
- 红线演示：不许在 oracle/ 原地跑 run_all（彩排 D3 的真实教训，最佳教学内容）；
- 彩排状态：✅。

## 第 4 讲（2 小时）：给 CLI 穿上 MCP 外衣（zctl-mcp，扩线首批）

- 交付物：学员本机把 mcp-server.mjs 挂进 ZCode MCP 配置，`tools/list` 现场可见 4 工具；
- 知识点：只读暴露原则、变更类工具为什么一律不进 MCP（confirm 参数守卫为何形同虚设——盲评评委原话就是教学素材）；
- 验收点：`python eval/runner.py` 自评 7/7 exit 0；
- 状态：确定性门 ✅；端到端真机调用欠账（如实告知学员：课上只做离线握手+列举）。

## 第 5 讲（2 小时）：给 agent 立规矩——验收员角色包（acceptor-agent，扩线首批）

- 交付物：学员派一个真子代理按 agent.md 验收前几讲的任一交付物，产出合法 verdict JSON；
- 知识点：verified vs judged、PASS ⇔ 无 blocker、承诺边界条款；
- 验收点：`eval/runner.py` 4/4 + verdict 契约校验；
- 状态：确定性门 ✅；端到端子代理演练随本讲首开。

## 课程资产冻结与升版

- 课堂版本绑定 `classroom-v0.1`（teaching-assets.md）；升版须走「基线 6 门复跑 → 文档同步 → 新 tag」三步（teaching-assets §F）。
