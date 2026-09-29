"""全部 eval 阈值常量（开发指令 §6），一处可调。

各模块 eval 从这里取阈值，禁止在用例里散落魔法数字。
"""
from __future__ import annotations

# ── M1 网关 ────────────────────────────────────────────────────────
GATEWAY_OVERHEAD_P95_MS = 150          # 2000 字 prompt 规则识别+脱敏 网关自身开销 p95（不含上游）
GATEWAY_BODY_MAX_BYTES = 10 * 1024 * 1024   # 请求体上限

# ── M2 规则层 ──────────────────────────────────────────────────────
RECALL_STRUCTURAL = 1.00               # ID_CARD / USCC / BANK_CARD 必须满分
RECALL_PATTERN = 0.99                  # PHONE / EMAIL / IP / PLATE / SECRET_KEY
WHITELIST_FPR_MAX = 0.01               # 白名单误报率上限（whitelisted 正确标记不算误报）
RULE_LATENCY_MS_2000CH = 100           # 2000 字规则层单遍（10 次均值）

# ── M2 语义层（D4）────────────────────────────────────────────────
INJECTION_RECALL_MIN = 0.90            # 注入样例拦截率
NORMAL_TEXT_FP_MAX = 0.05              # 正常公文误拦率

# ── M2 语义层（T4.2：m2_semantic 用例规模/延迟，只增）─────────────
SEMANTIC_INJECTION_SAMPLES_MIN = 30    # 注入样例总数下限（直接/间接/藏于工具描述合计）
SEMANTIC_DIRECT_SAMPLES_MIN = 10       # 直接注入类样例下限
SEMANTIC_INDIRECT_SAMPLES_MIN = 10     # 间接（文档内嵌）类样例下限
SEMANTIC_TOOLDESC_SAMPLES_MIN = 8      # 藏于工具描述类样例下限
SEMANTIC_NORMAL_SAMPLES_MIN = 40       # 正常公文误报控制样例下限
SEMANTIC_LATENCY_MS_2000CH = 50        # 语义层 2000 字单遍 10 次均值上限

# ── M2 测评集规模（M8 生成器产出）─────────────────────────────────
RULE_CASES_MIN = 300                   # rule_cases.jsonl 最少条数
RULE_CASES_PER_CLASS_MIN = 20          # 每类别正例（含扰动）下限
WHITELIST_NEGATIVES_MIN = 40           # 白名单负例下限
CLASSIFICATION_SAMPLES_MIN = 20        # 密级样例下限

# ── M3 脱敏 ────────────────────────────────────────────────────────
MASK_STABILITY_VALUES = 1000           # 稳定性用值数
MASK_STREAM_FUZZ_CASES = 500           # 流式切块还原用例数
MASK_CHUNK_MIN_BYTES = 1               # SSE 随机切块下限
MASK_CHUNK_MAX_BYTES = 7               # SSE 随机切块上限
MASK_COLLISION_PROBE_VALUES = 100_000  # 8 位 hex 碰撞抽样插入数
MASK_RESTORE_MS_50PH_2000CH = 20       # 2000 字含 50 占位符还原耗时上限

# ── M4 路由 ────────────────────────────────────────────────────────
ROUTING_MATRIX_CASES_MIN = 25          # 决策矩阵逐格用例下限

# ── M5 outguard ────────────────────────────────────────────────────
OUTGUARD_CASES_MIN = 12                # 标识（流/非流）/文案/代答/钩子用例下限

# ── M6 文件通道 ────────────────────────────────────────────────────
FILE_SIZE_MAX_BYTES = 50 * 1024 * 1024
FILE_FIXTURES_PER_KIND = 5             # docx/xlsx/pdf seeded 夹具各 5 份
FILE_EXPORT_RESIDUAL_ALLOWED = 0       # 导出物重解析 seeded PII 命中数上限
FILE_GRADED_SEEDED_MIN = 80            # T3.1 文本层：15 份夹具可评级 seeded 命中总数下限
OCR_ID_CARD_RECALL_MIN = 0.90          # 扫描件身份证召回（D4）
OCR_SEEDED_SCANS = 3
OCR_IDS_PER_SCAN = 4                   # 每份扫描件 seeded 身份证数（T4.1）

# ── M7 审计 ────────────────────────────────────────────────────────
AUDIT_E2E_REQUESTS = 20                # 混合请求数（行数断言；T5.1 全量口径用）
AUDIT_RAW_PII_HITS_ALLOWED = 0         # 库文件 bytes 级扫描命中上限
AUDIT_WRITER_EVENTS = 30               # T1.3 落库完整性写入事件数
AUDIT_APPEND_BATCH_MS = 200            # T1.3 入队 30 次（硬闸+put）总耗时上限（请求路径不阻塞）
AUDIT_SESSION_STABILITY_VALUES = 100   # T1.3 会话稳定抽查值数（全量 1000 在 m3）
SESSION_TTL_PROBE_MS = 150             # T1.3 会话过期探针 TTL
AUDIT_FLUSH_TIMEOUT_S = 10.0           # T1.3 写队列排干等待上限

# ── M7 审计（T5.1：/admin/api/* 查询面，只增）──────────────────────
AUDIT_PAGE_LIMIT_DEFAULT = 100         # /admin/api/audit 缺省页大小
AUDIT_PAGE_LIMIT_MAX = 1000            # /admin/api/audit 单页上限（越界 400）
AUDIT_ADMIN_EVENTS = 20                # T5.1 管理面验收混合请求数（§6 M7：20 个混合请求）

# ── M8 生成器/基线/质量 ────────────────────────────────────────────
CORPUS_DOCS_MIN = 5000
CORPUS_TEMPLATE_CLASSES_MIN = 30
QUALITY_PAIRS_MIN = 50
QUALITY_RATIO_MIN = 0.95               # 脱敏前后回答质量比值下限

# ── M8 生成器（T1.1：rule_cases 评测集 + seeded 夹具）──────────────
GENERATOR_TEMPLATE_CLASSES_MIN = 10    # 政务文书模板类下限（任务口径）
GENERATOR_PERTURB_KINDS_MIN = 5        # 扰动器种类下限（任务口径 5 类）
GENERATOR_ID_CHENGMAI_MIN = 20         # 澄迈区划(469023)身份证正例下限
GENERATOR_REJECT_NEGATIVES_MIN = 20    # 难负例（校验位失败等）下限
GENERATOR_SENSITIVE_ATTR_MIN = 20      # 敏感属性正例下限（9 子类型须全覆盖）
GENERATOR_DATE_BIRTH_MIN = 20          # 出生日期正例下限
GENERATOR_PERSON_MIN = 20              # 人名（NER 层计分）样例下限
GENERATOR_ADDRESS_MIN = 20             # 住址（NER 层计分）样例下限
GENERATOR_LANDLINE_MIN = 20            # 座机正例下限
