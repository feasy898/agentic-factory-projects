# 资产包总表（manifest）

> 本表按**逻辑模块**组织（十大模块 = 任务口径）；物理位置逐行标注。
> 每模块一行：模块ID / 名称 / 形态 / 职责 / 冻结契约 / 依赖 / eval 命令与通过线 + **六门 eval 指针** / 顺序位 / 状态 / spec。
> 详细契约汇总见 [CONTRACTS.md](CONTRACTS.md)；整仓再生手册见 [REGENERATE.md](REGENERATE.md)；逐模块 spec 在 [specs/](specs/)；六门结构专页见 [specs/gates.md](specs/gates.md)。
> 所有 eval 命令在仓库根执行；**2026-09-29 本机逐项实测全绿**（m0_infra 20/20、m2_recognizers 6/6、
> m2_semantic 11/11、m3_masking 9/9〔T8.4 增改形还原项后，2026-09-30 复核〕、m4_routing 43/43、m5_outguard 13/13、m6_filesvc 12/12、
> m6_ocr 6/6、m7_audit 16/16、m8_generator 4/4、m9_webui 14/14、t0_gateway 13/13、t0_stream 11/11、
> t0_labels 8/8、m10_e2e `7 PASS / 0 FAIL / 0 DEFERRED`；例外：m8_baselines / m8_quality 为规划态，见 BENCH 行）。

## 状态图例

| 状态 | 含义 |
|---|---|
| `frozen` | 已实现且验收全绿；契约冻结（字段只增不改名），改动视为破坏契约 |
| `partial` | 主体 frozen，个别子入口为规划态（如实标注，无占位实现） |
| `planned` | 未开工；有明确开工前置 |

## 核心模块（十大模块）

| 模块ID | 名称 | 形态 | 职责（一句话） | 冻结契约 | 依赖 | eval 命令 → 通过线 | 六门 eval 指针 | 顺序位 | 状态 | spec |
|---|---|---|---|---|---|---|---|---|---|---|
| `GATEWAY` | 网关主链（M1） | Python + FastAPI + httpx（`gateway/`） | OpenAI 兼容 /v1/chat/completions：detect→mask→route→转发→还原→outguard→audit 主链，流式 SSE 三段管线 | 出站全量叶节点规则（tools/历史 tool_calls/非 text 多模态段全查，任一 BLOCK_FLAG 整单拦）；错误信封 code 词表；端点全表 | RECOG, MASKING, ROUTING, OUTGUARD, AUDIT | `python -m evals.t0_gateway` → exit 0；`python -m evals.t0_stream` → `T0 GATEWAY STREAM: 11/11` | 每门回归 m10_e2e（G0④→B5⑤）；t0_stream 自 G0③ 固化 | 1 | frozen | [gateway-main-chain](specs/gateway-main-chain.md) |
| `RECOG` | 三层识别·规则层（M2） | Python（`recognizers/`，rule 实装 + ner 适配器位） | 正则+校验位+词表+白名单全类别检测；影子扫描；span 占用防重叠 | EntityClass 19 值+中文标签；SUBTYPES 9 值；token 分类序（熵串>证件>卡号>电话）；校验位 GB11643/GB32174/Luhn | — | `python -m evals.m2_recognizers` → `M2 RECOGNIZERS: 6/6`（结构化 100%/模式 99%/白名单误报 ≤1%/2000 字 <100ms） | G-B1④ 首验 → G-B2②-4 起逐批回归 | 2 | frozen | [recognizers-rule](specs/recognizers-rule.md) |
| `MASKING` | 可逆脱敏+会话存储（M3） | Python（`masking/`） | 会话稳定占位符（HMAC-SHA256）、归一化等价、流式还原状态机、工具参数 hold-to-finish、LRU+SQLite+TTL 双层存储 | §5.3.1 占位符算法一字不差；DIGEST_WIDTHS(8,10,12)；归一化表（§5.3.2）；还原形状正则 + T8.4 容错改形还原（canonical_placeholder，窗 48 字符）；流式 ≤48 字符缓冲语义 | RECOG | `python -m evals.m3_masking` → `M3 MASKING: 9/9`（稳定性 1000 值/fuzz 500 条/改形 11 形态/10 万值零碰撞/还原 <20ms） | G-B2③-3 首验 → 整门链回归；m7_audit C 节钉存储 | 3 | frozen | [masking-placeholder](specs/masking-placeholder.md) · [masking-normalize](specs/masking-normalize.md) |
| `ROUTING` | 策略路由（M4） | Python 纯函数（`routing/`） | findings+config → RouteDecision；优先级 BLOCK>GOVCLOUD>INTERNET | R1–R6 决策矩阵；白名单豁免脱敏不豁免拦截；reasons 有序决定性；Block 恒 null 上游 | RECOG | `python -m evals.m4_routing` → `M4 ROUTING: 43/43 checks passed`（38 矩阵格+5 横切） | G-B2③-1 首验 → 整门链回归 | 4 | frozen | [routing-matrix](specs/routing-matrix.md) |
| `OUTGUARD` | 输出侧（M5） | Python（`outguard/`） | AI 生成标识（流/非流+annotations+响应头）、BLOCK 按 reason code 拒答、关键词代答、输出复检钩子 | §5.6 注入方式；文案库 YAML+内置默认双份一致；幂等标识 | ROUTING | `python -m evals.m5_outguard` → `M5 OUTGUARD: 13/13` | G-B2③-2 首验 → 整门链回归 | 5 | frozen | [outguard](specs/outguard.md) |
| `FILECHAN` | 文件通道+OCR（M6） | Python（`filechannel/`；引擎名只进 config，importlib 动态加载） | docx/xlsx/pdf/扫描件解析→体检报告（页码/单元格/坐标定位）→彻底删除式导出+零残留硬闸 | FileReport/FileFinding 形状；location 字符串格式；bbox render 坐标系；风险分级 HIGH/MID/LOW/NONE；导出 re-ingest 零残留铁律 | RECOG | `python -m evals.m6_filesvc` → `12/12`；`python -m evals.m6_ocr` → `6/6`（身份证召回 ≥0.90） | G-B3③ filesvc 首验 → G-B4③⑤ ocr 首验+filesvc 栅格兜底回归 | 6 | frozen | [filechannel-locations](specs/filechannel-locations.md) |
| `SEMANTIC` | 语义层·注入检测（M2 D4） | Python 词表引擎（`recognizers/semantic/`） | STRONG/EXFIL/WEAK 三档词表 + 否定前缀守卫 + WEAK 位置佐证 + env 驱动 judge 升档位（无 key 降级） | 三档结构与行格式 `<class>\|<regex>`；moderate() 形状 P0 冻结；judge 故障降级不抛错 | RECOG | `python -m evals.m2_semantic` → `M2 SEMANTIC: 11/11`（拦截 ≥0.90/误拦 ≤0.05） | G-B4④ 首验 → 整门链回归；U7 由 G-B4⑥ 固化 | 7 | frozen | [semantic-wordlist](specs/semantic-wordlist.md) |
| `AUDIT` | 审计+看板（M7+管理面+看板页） | Python + SQLite WAL + Jinja2（`audit/` + `gateway/admin_api.py` + `webui/`） | 只存脱敏内容的审计库、零明文双闸、部门聚合/CSV/分页查询 API、演示看板页 | AuditEvent 形状（无 raw 字段）；audit_events 表；assert_no_raw_pii + 全库 bytes 扫描双闸；AuditPage/MetricsSummary 查询模型 | GATEWAY | `python -m evals.m7_audit` → `16/16`；`python -m evals.m9_webui` → `14/14`（含看板页 T5.2 口径） | G-B1⑤ / G-B2②-5（T1.3 口径）→ G-B5③④ 全量口径 | 8 | frozen | [audit-schema](specs/audit-schema.md) |
| `BENCH` | 生成器与测评（M8） | Python（`benchmark/generator/`） | seed 固定字节级可复现的合成语料/评测集/夹具 + manifest sha256 凭据 + 阈值单一来源 | manifest 无时间戳无绝对路径；双跑全等；夹具 seed 异或盐 | RECOG, MASKING | `python -m evals.m8_generator` → `M8 GENERATOR: 4/4`（双跑复现+规模+独立校验位复核+夹具） | G-B1③ 首验 → G-B2②-3 起回归 | 9 | frozen（m8_baselines / m8_quality 规划态，未入六门——见 [benchmark-generator](specs/benchmark-generator.md) §4） | [benchmark-generator](specs/benchmark-generator.md) |
| `GATES` | 六道门（ops 验收体系） | 标准库 Python 门脚本 ×6（`ops/gate_d0.py` + `gate_b1..b5.py`） | 系统python任意cwd可跑的收工门：name_lint+逐批 eval+既有门整链回归；唯一裁定口径 | 门项清单/附加断言（DEFERRED=0、U7 在位）/超时预算 900/1200/1800/3600s | 全部 | `python ops/gate_b5.py`（最新门；内嵌 b4→b3→b2 整链）→ 全项 `[PASS]`，exit 0 | 自身即门（2026-09-29 gate_b5 实跑 6/6 记录见 git log `827cdbf`） | 10 | frozen | [gates](specs/gates.md) |

## 基础设施与支撑面（非十大模块主表，但六门必经）

| ID | 名称 | 形态 | 职责 | eval → 通过线 | 六门指针 | 状态 | spec |
|---|---|---|---|---|---|---|---|
| `INFRA` | 基础设施（M0：venv/配置加载/结构化日志/契约模型负例） | Python（`common/` + `config/` + `pyproject/constraints.txt`） | 安装自检 + yaml+env 覆盖配置加载 + 9 个契约模型 extra-forbid 负例 | `python -m evals.m0_infra` → `M0 INFRA: 20/20` | 每门 ②（G0②→B5②） | frozen | [CONTRACTS](CONTRACTS.md) C7 |
| `NAMELINT` | 公开仓名称守卫 | `ops/name_lint.py` + `ops/forbidden_names.txt` | 上游项目名/许可证字样零命中把关（md/py/txt 等默认档 + strict 档 yaml/json） | `python -m ops.name_lint` → 零命中 exit 0 | 每门 ① | frozen | [gates](specs/gates.md) §2 |
| `E2E` | 端到端冒烟（M10 主体） | `ops/e2e_smoke.py`（真端口 9000/8901/8902 + 真实 config） | U1–U7 七用例 + bytes 级零明文 + 三部门演示数据 seed_demo | `python -m evals.m10_e2e` → `e2e_smoke: 7 PASS / 0 FAIL / 0 DEFERRED`（2026-09-29 实测 ≈337s） | 每门必回归（G0④→B5⑤） | frozen | [gateway-main-chain](specs/gateway-main-chain.md) §7 · [gates](specs/gates.md) |
| `LABELS` | 标签体系文档自验收 | `docs/contracts/labels.md` + `evals/t0_labels.py` | 文档与 taxonomy 常量（19 值+9 子类型）逐一即期对账 | `python -m evals.t0_labels` → `T0 LABELS: 8/8` | G-B1⑥ 首验起 | frozen | [recognizers-rule](specs/recognizers-rule.md) §2 |
| `WEBUI` | 演示前端（M9 其余页） | Jinja2 + 原生 JS（`webui/templates/` 五页） | 首页/体检页/演示控制页/双屏聊天页/看板页 | `python -m evals.m9_webui` → `14/14` | G-B3④（骨架口径）→ G-B5④（全量口径） | frozen | [audit-schema](specs/audit-schema.md) §6 |

## 重生成依赖图（顺序位即拓扑序）

```
INFRA(0) → RECOG(2) ──┬──► MASKING(3) ──► ROUTING(4) ──► OUTGUARD(5) ──► GATEWAY(1) ──► AUDIT(8)
                      ├──► SEMANTIC(7) ──────────────────────────┘                   ▲
                      └──► FILECHAN(6) ──────────────────────────────────────────────┘
BENCH(9，夹具供 FILECHAN/E2E；可早于 2 并行) ──► GATES(10，最后收口)
```

顺序位口径：1=主链组装位（依赖最多、最后合拢），2-9=被依赖优先（数字小者先建），
10=验收收口。GATEWAY 编 1 表"主链"，不是"最先建"。

- 铁律 A（先跑通再裁剪）：GATEWAY 主链先通（mock 上游 :8901/:8902 即可，无 key 全链路验收），
  之后一切在能跑的版本上加；
- 每个 eval 的阈值常量一律取自 `evals/thresholds.py`（一处可调，用例内禁散落魔法数字）。
