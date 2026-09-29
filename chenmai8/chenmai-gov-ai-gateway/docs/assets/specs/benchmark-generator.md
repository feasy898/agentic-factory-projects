# M8 生成器与测评 spec（确定性语料 + 评测集 + 夹具 + 阈值单一来源）

> 状态：frozen（T1.1 口径）。对照 `benchmark/generator/{build,cases,fixtures,materials,numbers,
> personas,perturb,templates,geo}.py`、`config/synthetic_corpus.yaml`、`evals/thresholds.py`
> 逐行核验于 2026-09-29。

## 1. 确定性契约（build.py，冻结）

- `build_all(seed, outdir)` 一键产出**三件套**：检测评测集 `rule_cases.jsonl`（含 `cases/`
  同字节镜像目录）、seeded 夹具 `fixtures/`（docx/xlsx/pdf 各 5 份 + 演示材料）、
  `generation_manifest.json`；
- **manifest 即「seed 固定 → 字节级可复现」的凭据**：记录 seed、规模分布与全部产物 sha256；
  manifest 自身不含时间戳/绝对路径，只含相对路径；`evals.m8_generator` 以两次独立构建的
  manifest 全等做复现断言，并与 `data/` 规范产物 sha256 对账；
- 夹具 seed = `seed ^ FIXTURE_SEED_SALT`（fixtures.py）；
- 第三方随机语料库模块名只写 `config/synthetic_corpus.yaml`（personas / pdf_writer 两组
  module/factory 坐标），源码经 importlib 动态加载、不得硬编码库名（公开仓库卫生）；
- 区划与号码自研槽位：海南/澄迈区划地址与身份证前缀表（geo.py：澄迈 469023）、
  身份证/信用代码带正确校验位、银行卡过 Luhn（numbers.py）。

## 2. 产出物形态

- `rule_cases.jsonl`：每行一例，`detect / whitelist / reject` 三级计分齐备——正例（含扰动
  变体：全角、插空格、换行、形近字、部分打码 5 类）、白名单负例、难负例（校验位失败等）、
  密级样例、敏感属性正例（9 子类型全覆盖）、PERSON/ADDRESS（NER 层计分）；
- 文档级注入埋点材料（materials.py）——语义层与 e2e U7 的夹具来源；
- 政务文书模板 ≥10 类（12345 工单/信访转办单/低保公示/会议纪要…模板代码内嵌+槽位，
  templates.py）。

## 3. 阈值单一来源（evals/thresholds.py，一处可调）

全部 eval 阈值常量集中此文件，用例内禁止散落魔法数字。要点（2026-09-29 全量对照）：

| 组 | 常量（值） |
|---|---|
| M1 网关 | GATEWAY_OVERHEAD_P95_MS(150)、GATEWAY_BODY_MAX_BYTES(10MB) |
| M2 规则 | RECALL_STRUCTURAL(1.00)、RECALL_PATTERN(0.99)、WHITELIST_FPR_MAX(0.01)、RULE_LATENCY_MS_2000CH(100) |
| M2 语义 | INJECTION_RECALL_MIN(0.90)、NORMAL_TEXT_FP_MAX(0.05)、SEMANTIC_*（规模/延迟，见 semantic-wordlist spec §4） |
| M2 评测集 | RULE_CASES_MIN(300)、RULE_CASES_PER_CLASS_MIN(20)、WHITELIST_NEGATIVES_MIN(40)、CLASSIFICATION_SAMPLES_MIN(20) |
| M3 脱敏 | MASK_STABILITY_VALUES(1000)、MASK_STREAM_FUZZ_CASES(500)、MASK_CHUNK_MIN/MAX_BYTES(1/7)、MASK_COLLISION_PROBE_VALUES(100000)、MASK_RESTORE_MS_50PH_2000CH(20) |
| M4 路由 | ROUTING_MATRIX_CASES_MIN(25) |
| M5 | OUTGUARD_CASES_MIN(12) |
| M6 文件 | FILE_SIZE_MAX_BYTES(50MB)、FILE_FIXTURES_PER_KIND(5)、FILE_EXPORT_RESIDUAL_ALLOWED(0)、FILE_GRADED_SEEDED_MIN(80)、OCR_ID_CARD_RECALL_MIN(0.90)、OCR_SEEDED_SCANS(3)、OCR_IDS_PER_SCAN(4) |
| M7 审计 | AUDIT_E2E_REQUESTS(20)、AUDIT_RAW_PII_HITS_ALLOWED(0)、AUDIT_WRITER_EVENTS(30)、AUDIT_APPEND_BATCH_MS(200)、AUDIT_PAGE_LIMIT_DEFAULT/MAX(100/1000) 等 |
| M8 | CORPUS_DOCS_MIN(5000)、CORPUS_TEMPLATE_CLASSES_MIN(30)、QUALITY_PAIRS_MIN(50)、QUALITY_RATIO_MIN(0.95)、GENERATOR_*（T1.1 口径：模板类 ≥10、扰动 ≥5 类、澄迈身份证 ≥20、难负例 ≥20 等） |

## 4. 基线与质量评测（规划口径，D6/D7）

- `evals.m8_baselines`：三基线（纯正则去校验位 / 最小中文模式识别框架 / 上游 LLM 零样本）
  × full_cases.jsonl 对比表落盘 `data/bench/report.json`——PPT 指标的唯一数据源（不许手填）；
- `evals.m8_quality`：≥50 问答对，脱敏前后双答质量比值 ≥ 0.95。
- **如实登记**：这两入口为规划态，2026-09-29 本资产包核验时未在六道门任何一项中出现、
  未见实现入册（六门覆盖清单见 gates spec §2）；启用时按 CONTRACTS 变更流程补指针。

## 5. eval 指针

| eval | 通过线 | 六道门指针 |
|---|---|---|
| `evals.m8_generator` | 双跑 manifest 字节级一致 + 在盘产物 sha256 全等；规模/分布断言（见 §2/§3）；独立校验位复核（与生成器交叉验证）；夹具重抽取全命中 + xlsx_01 隐藏列在位；`M8 GENERATOR: N/N`，exit 0 | gate_b1 ③ 首验；gate_b2 ②-3 回归 |
