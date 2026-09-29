# 跨模块冻结契约汇总（CONTRACTS）

> 版本：契约基线 v1.0.0（2026-09-29 对照代码逐行核验）。开发指令 §5 五个冻结 schema +
> 派生契约的权威摘要。**铁律 B：D1 评审后冻结——字段只增不改名不删**；全部契约模型
> `extra="forbid"`（m0_infra 含 9 模型负例）。

---

## C1 Finding（recognizers → 一切下游；recognizers/models.py）

```json
{
  "fid": "f_0001",                // 请求内自增（文件通道=文件内自增）；detect() 恒空串由调用方编号
  "type": "ID_CARD",              // EntityClass 19 值，见下表
  "layer": "rule",                // rule | ner | semantic
  "start": 12, "end": 26,         // 原文 char span（Python 切片语义；validator 强制 start<=end）
  "raw": "460022199003071234",    // 原文：仅内存/调试，禁止入审计
  "subtype": null,                // 仅 type=SENSITIVE_ATTR 可用，值域 9 子类型
  "normalized": "460022199003071234",  // §5.3.2 归一化（masking-normalize spec）
  "confidence": 1.0,              // 校验位过=1.0；仅格式命中=0.5；[0,1]
  "whitelisted": false,           // 命中白名单 → 不参与脱敏、不参与路由计数
  "action_hint": "MASK"           // MASK | ROUTE_FLAG | BLOCK_FLAG
}
```

EntityClass 19 值（值=代码常量；label=占位符中文标签）：
PERSON(人名) ADDRESS(住址) ID_CARD(身份证) PHONE_MOBILE(手机号) PHONE_LANDLINE(座机)
BANK_CARD(银行卡) USCC(信用代码) PLATE(车牌) EMAIL(邮箱) IP(地址) SECRET_KEY(密钥)
DATE_BIRTH(出生日期) SENSITIVE_ATTR(敏感属性) WORK_SECRET(工作秘密)
CLASSIFICATION_MARK(密级标识) INJECTION(注入指令) ORG_INTERNAL(内部机构) DOC_NUMBER(文号)
OTHER(其他)。

SENSITIVE_ATTR_SUBTYPES 9 值：病症/残障/低保特困/社区矫正/信访人/金融账户/行踪轨迹/
犯罪记录/特定身份（对齐敏感个人信息国标公开类别摘要；标签文档自验收 evals.t0_labels）。

action_hint 映射（识别层，冻结）：CLASSIFICATION_MARK→BLOCK_FLAG；
SENSITIVE_ATTR/WORK_SECRET→ROUTE_FLAG；其余→MASK。

## C2 RouteDecision（routing → gateway；routing/models.py）

```json
{
  "route": "INTERNET",            // INTERNET | GOVCLOUD | BLOCK
  "reasons": [                    // 有序，第一条为决定性理由；低优先级命中不随行
    {"code": "CLASSIFICATION_MARK", "fid": "f_0007", "detail": "命中 机密★"}
  ],
  "upstream": "govcloud_local",   // config 上游名；BLOCK 时必须为 null（validator 强制）
  "mask_required": true,          // 存在非白名单 MASK 提示命中（按实际 findings）
  "labels": {"ai_generated": true}
}
```

- RouteReason.code 词汇表（9 码，新增码值不构成契约变更）：CLASSIFICATION_MARK /
  INJECTION（→BLOCK）；WORK_SECRET / SENSITIVE_ATTR / BATCH_STRUCTURED_PII（→GOVCLOUD）；
  SINGLE_STRUCTURED_PII / WHITELIST_ONLY / NO_FINDING / WHITELIST_HIT（→INTERNET）；
- 决策矩阵 R1–R6 与 43 格验收语义：见 [routing-matrix](specs/routing-matrix.md)；
- 结构化 PII 原文永不进 reasons（WHITELIST_HIT 留存条只含 fid+类别标签）；
- reasons 三键形状 + §5.2 五键形状 JSON 往返全等（m4_routing wire 检查钉死）。

## C3 MaskingMapping（§5.3.3；masking/models.py MappingEntry + masking_map 表）

```json
{"placeholder": "〔手机号·9a1b2c3d〕", "type": "PHONE_MOBILE",
 "normalized": "13800138000", "first_seen": "2026-09-28T03:00:00Z",
 "session_id": "sess_...", "preserve_semantic": false}
```

- 占位符算法（§5.3.1 一字不差）：HMAC-SHA256(key=MASK_KEY, msg=`session_id\x1f type\x1f
  normalized`)，截 8 位、同 session+type 碰撞升 10/12 位；`〔中文标签·hex〕`；
- 会话存储：内存 LRU（容量 1024）+ SQLite masking_map（主键 (session_id, placeholder)）+ TTL
  默认 24h；**与审计库分文件**（masking_map 必须存归一化原值，审计库有 bytes 级零明文断言）；
- 详细：[masking-placeholder](specs/masking-placeholder.md)、[masking-normalize](specs/masking-normalize.md)。

## C4 AuditEvent（audit/models.py；§5.4 冻结，禁止出现 raw）

```json
{
  "ts": "2026-09-28T03:00:00Z", "request_id": "req_...", "session_id": "sess_...",
  "dept": "民政局",
  "route": "GOVCLOUD", "blocked": false,
  "reasons": ["SENSITIVE_ATTR"],
  "class_counts": {"ID_CARD": 2, "PHONE_MOBILE": 3},
  "prompt_preview": "〔人名·7f3a2b1c〕提交的…",   // ≤500 字符，已脱敏（占位符版本）
  "response_preview": "…",                        // ≤500 字符
  "upstream": "govcloud_local", "latency_ms": 812, "flags": []
}
```

- 库表 audit_events（id 自增；reasons/class_counts 存 JSON 文本；WAL；ts/dept 索引）；
- **零明文双闸**：入库前 `assert_no_raw_pii`（归一化值+表面形式同查 + 截断边界守护，失败即
  500 且不落库）+ 全库文件 bytes 级 `assert_db_no_raw_pii`（含 -wal/-shm；扫描器有负控）；
- BLOCK_FLAG 命中的表面形式（密级词/注入词）在预览中以 `〔密级·已拦截〕`/`〔注入·已拦截〕`
  占位——拦截语义不进审计明文面；
- 管理面查询模型（T5.1 只增）：AuditPage / LatencyStats / DeptMetrics / MetricsSummary；
- 详细：[audit-schema](specs/audit-schema.md)。

## C5 FileReport / FileFinding（filechannel/models.py；§5.5 冻结）

```json
{
  "file_id": "file_...", "filename": "低保公示.pdf", "sha256": "...",
  "kind": "pdf",                   // pdf | docx | xlsx | scan_pdf
  "pages": 3,
  "findings": [ {"page": 1, "bbox": [x0,y0,x1,y1], "location": null, "finding": {C1 Finding}} ],
  "risk_level": "HIGH",            // HIGH | MID | LOW | NONE
  "summary": {"ID_CARD": 12, "PERSON": 30}
}
```

- 位置语义：page 1 起始；bbox 仅 pdf/scan_pdf（render 坐标系：原点左上、y 向下、pt，
  scan_pdf 来自 OCR 重建）；location 仅 docx/xlsx（`para:5`/`table:2:r1:c3`/`Sheet1!B3`…），
  pdf 恒 null；
- 风险分级：HIGH=非白名单 SENSITIVE_ATTR 或批量号码（≥config 批量线）；MID=其它非白名单
  结构化 PII；LOW=其余命中；NONE=零命中；密级/工作秘密不进分级但进 findings/summary；
- **导出验收铁律**：对导出物重新走「解析+检测」，seeded PII 命中数必须为 0（管线内硬闸，
  ExportBlockedError 宁阻不漏）；导出响应头 X-Report-Id + X-Sanitize-Method；
- 详细：[filechannel-locations](specs/filechannel-locations.md)。

## C6 HTTP API（§5.6；端点全表见 [gateway-main-chain](specs/gateway-main-chain.md) §5）

- `/v1/chat/completions` OpenAI 兼容；响应头 `x-anongw-route` / `x-anongw-request-id`；
- AI 标识三面：内容尾注行 + `annotations` 元数据（流式在 finish chunk delta 上，同名同形）
  + 响应头 `x-anongw-ai-label: 1`（[outguard](specs/outguard.md) §1）；
- 错误信封 `{"error":{"code","message","reasons"}}`，BLOCK 恒 403 + `content_blocked`；
- 管理面 `/admin/api/audit|metrics|report.csv` 部门 Key 鉴权（limit 100 默认 / 1000 上限）；
- `/internal/detect|anonymize|restore` 含还原原文——生产只应经 127.0.0.1/受控内网。

## C7 环境与配置契约（common/config.py + config/app.yaml）

- 字段即契约（字段只增不改名）：listen(9000) / mask_key_env / session_ttl_h(24) /
  upstreams[]（name/base_url/api_key_env/models/route）/ ai_label / outguard_texts /
  thresholds.batch_pii_to_govcloud(3) / moderation_model / pdf_engine_module / audit_db /
  session_db；
- **密钥不入配置文件**：只写环境变量名，运行时 resolve_secret()；env 覆盖顶层键：
  `ANONGW_<K大写>`（如 ANONGW_LISTEN）；
- 上游池按 route 取首个命中（INTERNET/GOVCLOUD 各一）；真实上游产品名不预置在公开示例。

## 已识别契约痛点（变更候选——待 owner/PM 批准，批准前不得擅改实现）

| # | 痛点 | 影响 | 变更候选 |
|---|---|---|---|
| 1 | 出站辅助面 `_iter_string_leaves`（gateway/pipeline.py:144-158）只递归 dict 的 **values**，字符串键不进检测面 | PII/密级词藏在 JSON 键位（如 `{"13800138000": …}`）时漏检漏替换 | 叶遍历增扫键；或入站校验拒绝键位含命中（与 body 校验层合并裁决） |
| 2 | m8_baselines / m8_quality 为规划态未实现 | PPT 基线对比/质量比值（≥0.95）暂无自动产出 | 按 benchmark-generator spec §4 落地后补六门指针 |
| 3 | preserve_semantic 字段已入契约但无消费方（语义保留替换为 P1 规划） | 字段形同虚设 | 接线（ID_CARD 保地区码+出生年、日期平移）或标注"预留" |
| 4 | 人名启发式为静态停用词表 curated | 新词误收需手工追加 | NER 层接入后由 NER 主导，启发式降为兜底 |

## 版本与变更流程（冻结）

- **版本锚**：契约基线 = 开发指令 §5（D1 评审冻结）；全部契约模型 `extra="forbid"`；
  阈值唯一来源 `evals/thresholds.py`。
- **谁批准**：C1–C7 与痛点候选的变更由仓库 owner / PM 批准；实现者不得单方面变更。
- **怎么广播**（每次契约变更必须全做）：
  1. 更新本页对应小节 + 受影响 specs/*（含痛点裁决回填）；
  2. 契约模型同步改（字段只增不改名不删），golden/bad 评测集与 thresholds 按需增补；
  3. 受影响 eval 全绿 + 六道门相关门项复跑 + `python -m ops.name_lint --strict` 零命中；
  4. 单独 commit，标题带 `contract-change:` 前缀。
