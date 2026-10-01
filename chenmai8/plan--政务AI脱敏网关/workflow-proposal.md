# Workflow Proposal —— 构建阶段任务编排（供主会话构建工作流下发）

> 本项目以 **windev-01 本机构建为主**，无 GPU、无 Docker。每个任务交给一个 GLM-5.3-Flash 构建子代理，交付物 = 代码 + `evals.*` 命令 exit 0 的运行输出。
> 依赖图约定：A → B 表示 B 依赖 A 的契约已落地（不要求 A 完美，契约字段先冻结即可）。
> 任务编号 = 建议下发批次。同一批次内任务可并行下发（不同子代理），跨批次串行。

## 0. 下发模板（每个任务照此填）

```
任务 <ID>：<名称>
仓库：D:\workspace\澄迈8项目\政务AI脱敏网关\repo（下称 REPO_ROOT）
范围：只改 <文件/目录清单>；契约以 plan/开发指令.md §5 为准，spec 见 §6 <M模块> 节
完成定义：
  1) cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.<入口>  → exit 0
  2) 不改动冻结契约字段；如需新增字段，只增不改名
  3) 代码/注释/README 不出现 oss-manifest.md §7.3 禁用词（ops/name_lint.py 通过）
```

## 1. 任务清单与依赖

### 批次 0（D0 9/28 当天，串行+小并行，一切之前）

| ID | 任务 | 内容 | 依赖 | eval 入口 | 备注 |
|---|---|---|---|---|---|
| T0.1 | 仓库脚手架 | pyproject/constraints/ops/name_lint+forbidden_names/config 加载器/.env.example/logging | — | evals.m0_infra | 纯本机 |
| T0.2 | 契约模型落地 | 按开发指令 §5 建 6 个 models.py（finding/route/mapping/audit/file/api 错误体），pydantic v2 | T0.1 | evals.m0_infra(扩展) | 只写模型+序列化往返测试 |
| T0.3 | mock upstream | gateway/mock_upstream.py（:8901/:8902 两实例，回显+ring buffer） | T0.2 | — | e2e 前置 |
| T0.4 | 网关骨架+非流式链路 | /v1/chat/completions 非流式：detect(规则v0: 身份证+手机号+密级词)→mask(占位符+还原)→route(三路由v0)→转发→还原→audit v0(内存) | T0.2 T0.3 | — | 今天的主菜 |
| T0.5 | 流式链路 | SSE 透传+remap 状态机(缓冲还原)+AI标识 | T0.4 | — | |
| T0.6 | e2e_smoke | ops/e2e_smoke.py 六用例（开发指令 §9），U1–U5 当天生效 | T0.4 T0.5 | evals.m10_e2e | **exit 0 = D0 收工线** |

**D0 收工硬标准：`python -m evals.m10_e2e` exit 0。** 达成后当天剩余时间并行：T1.1。

### 批次 1（D1 9/29）

| ID | 任务 | 内容 | 依赖 | eval 入口 | 并行 |
|---|---|---|---|---|---|
| T1.1 | 生成器 v1 | benchmark/generator：Faker zh_CN+校验位号码+海南区划+10 类文书模板+扰动器+白名单负例；产出 rule_cases.jsonl(≥300)+seeded 夹具(docx/xlsx/pdf 各5) | T0.2 | evals.m8_generator | ✔（Track B 起点） |
| T1.2 | 规则层全量 | recognizers 全类别正则+校验位+白名单+密级词表+性能优化 | T0.4, T1.1(用例) | evals.m2_recognizers | 等 T1.1 用例 |
| T1.3 | 会话存储+审计落库 | masking/session_store(SQLite+TTL)、audit/writer(队列+WAL)+assert_no_raw_pii | T0.4 | evals.m7_audit(部分) | ✔ |
| T1.4 | 标签体系文档 | docs/contracts/labels.md（对齐 GB/T 45574 摘要，标注不确定项） | — | evals.t0_labels | ✔（可由规划侧做） |

### 批次 2（D2 9/30）

| ID | 任务 | 内容 | 依赖 | eval 入口 | 并行 |
|---|---|---|---|---|---|
| T2.1 | 策略引擎 | routing 纯函数实现 §5.2 矩阵 | T1.2 | evals.m4_routing | ✔ |
| T2.2 | 输出侧 | outguard：AI 标识(流/非流)+拦截文案+代答 yaml | T2.1 | evals.m5_outguard | 串 T2.1 |
| T2.3 | 工具调用还原 | masking 工具参数缓冲还原（流式 hold-to-finish） | T0.5 | evals.m3_masking(补) | ✔ |
| T2.4 | 三路由 e2e 扩展 | e2e U3 用例材料化（三份 seeded 材料） | T2.1 | evals.m10_e2e | 串 T2.1 |

### 批次 3（D3 10/1）

| ID | 任务 | 内容 | 依赖 | eval 入口 | 并行 |
|---|---|---|---|---|---|
| T3.1 | 文件解析+体检 | filechannel：docx/xlsx/pdf-text 解析→FileReport；pypdfium2 坐标抽取 | T1.1(夹具) | evals.m6_filesvc(部分) | ✔ |
| T3.2 | 彻底删除式导出 | pdf_engine 抽象+engine_pymupdf+engine_pikepdf(两实现都写，pikepdf 先过验收防 AGPL 决策阻塞)+xlsx 删列+docx 删值 | T3.1 | evals.m6_filesvc | 串 T3.1 |
| T3.3 | 体检页/导出 API | /v1/files/* 端点+webui 体检页骨架 | T3.1 | evals.m9_webui(部分) | ✔ |

### 批次 4（D4 10/2）

| ID | 任务 | 内容 | 依赖 | eval 入口 | 并行 |
|---|---|---|---|---|---|
| T4.1 | OCR 路径 | pypdfium2 渲染→RapidOCR→重建可检测文本+bbox 映射；scan_pdf 导出=重栅格化打码版 | T3.1 | evals.m6_ocr | ✔ |
| T4.2 | 语义层接入 | semantic/adapter 接 Qwen3Guard-Gen-0.6B（HF/魔搭下载决策点）+prompt 侧审核+注入拦截；回退实现=规则词表（先写，保演示） | T2.1 | evals.m2_semantic | ✔ |
| T4.3 | 注入演示材料 | 演示控制页场景 4 材料+拦截卡 UI | T4.2 | evals.m9_webui(部分) | 串 T4.2 |

### 批次 5（D5 10/3）

| ID | 任务 | 内容 | 依赖 | eval 入口 | 并行 |
|---|---|---|---|---|---|
| T5.1 | 审计查询/聚合/CSV | /admin/api/audit|metrics|report.csv | T1.3 | evals.m7_audit | ✔ |
| T5.2 | 看板页+聊天页完善 | webui 四页成形态：指标卡、柱状图(无框架 SVG 即可)、route 徽标、对比栏 | T5.1 | evals.m9_webui | 串 T5.1 |
| T5.3 | 部门 Key 与多部门演示数据 | dept_keys 3 部门+看板演示数据注入脚本 | T5.1 | evals.m10_e2e | ✔ |

### 批次 6（D6 10/4）

| ID | 任务 | 内容 | 依赖 | eval 入口 | 并行 |
|---|---|---|---|---|---|
| T6.1 | 基线对比 | bench/baselines：纯正则(去校验位)/Presidio 最小中文/LLM 零样本(上游 key 或 mock 判定器) | T1.1 T1.2 | evals.m8_baselines | ✔ |
| T6.2 | 演示脚本化 | ops/demo/scene1–5.md+演示控制页一键场景 | 全部 | evals.m9_webui | ✔ |

### 批次 7（D7 10/5）

| ID | 任务 | 内容 | 依赖 | eval 入口 | 并行 |
|---|---|---|---|---|---|
| T7.1 | 质量评测 | 50+ 问答对脱敏前后 LLM-judge 对比 | 上游 key | evals.m8_quality | ✔ |
| T7.2 | 全量回归+缺陷修复 | 所有 evals 重跑+畸形输入用例(body 10MB/file 50MB/非法 SSE) | 全部 | evals.m10_e2e 等 | 串前七批 |
| T7.3 | P1 取舍决策 | 语义保留替换/其他 P1 项按剩余时间取舍（规划侧决定） | — | — | 人工 |

### 批次 8–9（D8–D9 10/6–10/7）

| ID | 任务 | 内容 | eval 入口 |
|---|---|---|---|
| T8.1 | 录演示视频 | 按 ops/demo 逐场景录 3–5 分钟 | 人工 |
| T8.2 | 公开导出+compose | ops/export_public.py+docker-compose.yml(标注未实测)+公开版 README | evals.m10_export |
| T9.1 | PPT+计划书 | 指标一律引用 data/bench/report.json 自动生成段落 | 人工 |

## 2. 并行泳道总览

```
Track A(网关/脱敏/路由): T0.4→T0.5→T2.1→T2.2→T2.3→T5.x
Track B(识别/测评):      T1.1→T1.2→T4.2→T6.1→T7.1
Track C(文件):                     T3.1→T3.2→T4.1
Track D(审计/前端):      T1.3→T5.1→T5.2→T6.2
收尾:                    T7.2→T8.x→T9.1
```
- 批次内并行任务互不改同一文件（模板已按目录划界）；若必须同文件，以下发顺序为准。
- 构建子代理遇到契约需变更：禁止自行改 §5 字段，回报主会话由规划侧裁决后统一改。

## 3. 集成门（Gate）

| 门 | 时点 | 内容 | 不达标处置 |
|---|---|---|---|
| G0 | D0 18:00 | evals.m10_e2e exit 0 | 当夜必须修到绿，否则 D1 只做修复 |
| G1 | D2 18:00 | 三路由 e2e + 规则层达标 | 砍 T2.3(工具还原)推到 D4 |
| G2 | D5 18:00 | 审计零明文 + 看板可用 | 砍 T4.3 推到 D6 |
| G3 | D7 18:00 | 全 evals 绿 + 质量评测出数 | 砍质量评测降采样至 30 对 |
| G4 | D8 18:00 | 视频成片 | D9 上午补录兜底 |

## 4. 给构建子代理的固定上下文（下发时附带）

1. 必读：plan/开发指令.md（§5 契约 + 本模块 §6 spec/eval）；
2. 环境：Git Bash；python 用 `./.venv/Scripts/python.exe`；统一 `PYTHONUTF8=1`；无 Docker/无 GPU；
3. 上游 key 仅在 T6.1/T7.1 需要（主会话提供 env 注入）；其余任务全部离线可完成；
4. 交付汇报格式：改动文件清单 + eval 命令与退出码 + 已知遗留（≤5 行）。
