# M2 三层识别 spec（规则层全类别 + NER/语义适配器位）

> 状态：frozen（规则层；ner/semantic 走适配器，无模型时空输出）。对照 `recognizers/{models,pipeline}.py`、
> `recognizers/rule/{detect,whitelist}.py`、`recognizers/ner/adapter.py` 逐行核验于 2026-09-29。
> 语义层（注入检测）独立成页：见 [semantic-wordlist](semantic-wordlist.md)。

## 1. 职责与边界

**做**：正则 + 校验位 + 词表 + 白名单的全类别检测（`detect(text) -> list[Finding]`），
fid 恒空串由调用方按请求编号；NER/语义适配器接口位。

**不做**：占位符与还原（masking 包）、路由（routing 包）、文件定位（filechannel 包）。

## 2. EntityClass 枚举（recognizers/models.py:19-48，冻结——值即代码常量）

19 个常量，`label` = 占位符用中文标签：

| 值 | 标签 | | 值 | 标签 | | 值 | 标签 |
|---|---|---|---|---|---|---|---|
| PERSON | 人名 | | SECRET_KEY | 密钥 | | CLASSIFICATION_MARK | 密级标识 |
| ADDRESS | 住址 | | DATE_BIRTH | 出生日期 | | INJECTION | 注入指令 |
| ID_CARD | 身份证 | | SENSITIVE_ATTR | 敏感属性 | | ORG_INTERNAL | 内部机构 |
| PHONE_MOBILE | 手机号 | | WORK_SECRET | 工作秘密 | | DOC_NUMBER | 文号 |
| PHONE_LANDLINE | 座机 | | | | | OTHER | 其他 |
| BANK_CARD | 银行卡 | | | | | | |
| USCC | 信用代码 | | | | | | |
| PLATE | 车牌 | | | | | | |
| EMAIL | 邮箱 | | | | | | |
| IP | 地址 | | | | | | |

`SENSITIVE_ATTR_SUBTYPES` 9 子类型（models.py:52-55）：病症 / 残障 / 低保特困 / 社区矫正 /
信访人 / 金融账户 / 行踪轨迹 / 犯罪记录 / 特定身份。`Finding.subtype` 仅允许
`type=SENSITIVE_ATTR` 使用，越界值域即校验失败（models.py:87-95）。

## 3. 工程口径（detect.py 模块文档 + 实现，冻结）

- **影子扫描**：先对全文全角→半角（1:1 映射，span 与原文严格对齐），全部正则在影子上匹配；
  raw/词面匹配仍取原文（detect.py:443）；
- **置信度**：校验位通过 = 1.0；仅格式命中（校验位不符）仍输出 = 0.5——宁可多脱敏不可漏脱敏；
  难负例（坏校验位）永不拿到满置信度判定（detect.py:366-370）；
- **单遍扫描 + span 占用表**防重叠，优先序：长熵串 > 证件/卡号/电话 > 日期；词面类不重叠
  数字 span、不受占用表约束（detect.py:28-29）；
- 归一化统一走 `masking.normalize.normalize_value`（见 masking-normalize spec）。

## 4. 检测步骤全序（`detect`，detect.py:433-561，序即契约）

| 步 | 类别 | 判定 | 置信度 |
|---|---|---|---|
| 1 | SECRET_KEY（PEM 块） | `-----BEGIN … KEY----- … -----END … KEY-----` 跨行，最先占位 | 1.0 |
| 2 | 通用 token（熵串/证件/卡号/手机/座机） | `_TOKEN_RE`（≥10 字符，容内部空格/制表/连字符）压缩后 `_classify_token`，见 §5 | 见 §5 |
| 3 | PLATE | 省份简称 + 发牌机关字母（无 I/O）+ 5 位普通 / 6 位新能源，容间隔点 | 1.0 |
| 4 | EMAIL | local@domain.tld，domain 至少一点 | 1.0 |
| 5 | IP | IPv4 逐段 0-255，前后不贴数字/点（杜绝 5 段链与段内截取） | 1.0 |
| 6 | DATE_BIRTH | 数字版式（18/19/20 开头）或中文版式 + **出生上下文门控**：命中 ±8 字符窗口内出现 出生/生于/生日（前方：生于/出生于/生日；后方：出生/生于/生日）才判——公文大量"发布日期"类日期零误报 | 0.9 |
| 7 | DOC_NUMBER | 公开文号 `机关代字〔20XX〕N号` → 默认 `whitelisted=true` | 0.9 |
| 8 | SENSITIVE_ATTR | 词表逐词命中，携带 subtype；**机构名后缀抑制**（命中紧跟 事务局/服务中心 不计） | 1.0 |
| 9 | WORK_SECRET | 词表逐词命中（可选层，ROUTE_FLAG） | 1.0 |
| 10 | CLASSIFICATION_MARK | 词表逐词命中（命中即 BLOCK_FLAG）；`terms` 形参可显式覆盖 | 1.0 |
| 11 | PERSON（规则层 v0 双轨） | 词表精确匹配 1.0 + 常见姓氏启发式 0.5（姓+1~2 汉字+右边界非汉字；停用词表压"到周四/杜绝此类"类误收；词表命中占位后启发式自动去重）——NER 接入前的人名兜底 | 1.0 / 0.5 |

产出按 `(start, end, type.value)` 升序排序。

## 5. token 压缩分类序（`_classify_token`，detect.py:365-399，序即契约）

熵串 > 证件 > 卡号 > 电话：

1. `sk` 前缀且余段 ≥28 位 hex（总长 ≥30）→ SECRET_KEY 1.0；
2. `AKIA` 前缀 + 16-20 位大写字母数字 → SECRET_KEY 1.0；
3. 恰 40 位 hex → SECRET_KEY 1.0；
4. 18 位（前 17 数字 + 尾 0-9Xx）→ **ID_CARD**（GB11643 校验：位权 7,9,10,5,8,4,2,1,6,3,7,9,10,5,8,4,2 +
   校验码表 `10X98765432`，`(加权和+尾) % 11 == 1`），过=1.0 不过=0.5；
5. 18 位且前 17 位**非全数字**且字符域合规（31 进制字符集 `0123456789ABCDEFGHJKLMNPQRTUWXY`，
   无 I/O/S/V/Z）→ USCC（GB32174：全体加权和 ≡ 0 mod 31）；18 位全数字串极少为信用代码，
   已被 4 按身份证解释（同时防坏证件号串联回信用代码满置信度）；
6. 12-19 位数字且 BIN 首位 2-6 → BANK_CARD（Luhn），过=1.0 不过=0.5；
7. 11 位且 1[3-9] 起始 → PHONE_MOBILE 1.0；13 位 86 前缀同形 → PHONE_MOBILE 1.0（span 回扩 `+`）；
8. 11-12 位 0 起始 → PHONE_LANDLINE 1.0。

校验位三函数（`id_card_checksum_ok / uscc_checksum_ok / luhn_ok`）为独立实现，
`evals.m8_generator` 用独立算法交叉复核（防同源同错）。

## 6. 白名单（recognizers/rule/whitelist.py + config/whitelist.yaml）

语义是**豁免脱敏、不参与路由计数**（`Finding.whitelisted=true`）：

- 12345 热线、110/119/120 应急短号（手机/座机命中后回查）；
- 单位座机号段（config/whitelist.yaml 可配）；
- 公开文号 → DOC_NUMBER 默认 whitelisted（§4 步 7）；
- token 扫描内的白名单判定：座机单位号段 or 手机/座机热线（detect.py:420-424）。

唯一安全例外：白名单豁免的是"脱敏"不是"拦截"——`action_hint="BLOCK_FLAG"` 的密级词即便
被误配进白名单也照拦（routing R1 不受白名单影响，routing-matrix spec §2）。

## 7. NER / 语义适配器位（P0 冻结接口）

- `recognizers/ner/adapter.py`：`detect(text) -> list[Finding]`，P0 返回空列表（预留 ONNX
  模型路径，显式声明未加载）；
- `recognizers/semantic/adapter.py`：`moderate(text) -> {verdict, categories}`（P0 形状冻结，
  现为词表第一档实现，见 semantic-wordlist spec）；
- `recognizers/pipeline.detect_full` = 规则层 + 语义层注入检测，网关主链调用入口。

## 8. eval 指针

| eval | 通过线（evals/thresholds.py） | 六道门指针 |
|---|---|---|
| `evals.m2_recognizers` | ID_CARD/USCC/BANK_CARD 召回 = 100%；PHONE/EMAIL/IP/PLATE/SECRET_KEY ≥ 99%；白名单误报 ≤ 1%；2000 字 < 100ms（RECALL_STRUCTURAL/RECALL_PATTERN/WHITELIST_FPR_MAX/RULE_LATENCY_MS_2000CH） | gate_b1 ④ 起；gate_b2 ②-4 回归 |
| `evals.m2_semantic` | 注入拦截 ≥ 0.90、正常公文误拦 ≤ 0.05、规模/延迟下限（INJECTION_RECALL_MIN/NORMAL_TEXT_FP_MAX/SEMANTIC_*） | gate_b4 ④ 起 |
| `evals.t0_labels` | 标签文档与 taxonomy 常量一致（19 值 + 9 子类型逐一对账） | gate_b1 ⑥ 起 |
| `evals.m8_generator` | 评测集规模与质量（规则层评测集来源） | gate_b1 ③ 起 |
