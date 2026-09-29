# M10 质量护照 spec（report · 护照字段全表 + M13 交付端点）

> 状态：冻结（27 用例全绿，2026-09-29 实测）。
> 本页对照 `beaneye/report/`（builder/qr/evidence/charts/i18n/errors + templates/）与
> `beaneye/app/` 逐行核验于 2026-09-29。
> 定位：全链路的对外交付物——三语自包含单文件 HTML + 二维码验真，护照由 BatchResult
> **唯一确定**（规范化 sha256），结果一变校验和即脱钩。

---

## 1. 护照产物登记字段全表（契约 `PassportReport`，beaneye/schemas.py）

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `report_id` | str | min_length=1 | **与 `BatchResult.result_id` 绑定**（build_passport 直接取 result_id） |
| `langs` | list[`zh`/`en`/`vi`] | min_length=1；**不得重复**（model_validator） | 实际生成的语言版本 |
| `html_paths` | dict[str,str] | — | lang → 写入文件路径；**值为绝对路径（posix 风格）**（契约偏差注：v1.0 未规定绝对/相对，实现取绝对路径并锁进测试） |
| `qr_payload` | str | min_length=1 | `{verify_base_url}/r/{report_id}|{sha256}`（§2） |
| `sha256` | str | `^[0-9a-f]{64}$` | sha256(canonical_json(BatchResult))，64 位十六进制 |

## 2. 校验和与二维码（qr.py）

- **规范化 JSON**：`BatchResult.to_json()` 解析后按**键排序 + 紧凑分隔符 + ensure_ascii=False**
  重新序列化；sha256 即对该 UTF-8 字节串计算（`canonical_sha256`）。
- **QR 负载**：`{verify_base_url}/r/{report_id}|{sha256}`；`|` 分隔，默认
  `verify_base_url = https://verify.beaneye.example`（演示占位，部署时替换）。
  `parse_qr_payload` 反解：rpartition("|") 取校验和、`/r/` 段取 report_id，两段各自正则校验，
  非法即 `ReportError`（三态非法负载有负向用例）。
- **渲染**：segno，纠错级 **M**，`scale=6, border=2`，dark `#111111` / light `#ffffff`，
  PNG → `data:image/png;base64,...` 内嵌（HTML 自包含，零外链）。解码验读由 eval 用
  zxing-cpp 完成「生成→解码→回读一致」闭环（逐语言）。

## 3. build_passport（BatchResult → PassportReport）

```
build_passport(result, out_dir, *, langs=("zh","en","vi"), verify_base_url=默认,
               crop_root=None, standard_verified=None, generated_at=None, taxonomy=None)
```

- 输出：`{out_dir}/{result_id}.{lang}.html`（UTF-8 单文件；实测单份 94–98KB，通过线 >20KB、
  ≤5s/份）。未知语言即刻报错；`crop_root` 缺省用 cwd（crop_path 相对路径的解析根）。
- **角标三态**（页脚）：`standard_verified=False` → 「标准阈值核对中」；`True` → 已对照；
  `None` → 不显示。未显式指定时按 `GradingDecision.warnings` **非空自动置 False**
  （getattr 安全探测，兼容契约 v1.0 无 warnings 字段的旧数据）。
- 模板：`templates/report_{lang}.html.j2`（子模 set lang 后 extends base）——Jinja2 实测支持；
  `Environment(autoescape=True, undefined=StrictUndefined, trim_blocks/lstrip_blocks)`；
  **模板零逻辑**：所有显示值在 builder 的视图函数预组装。

## 4. 页面区块与字段（五区块；base.html.j2 为 XHTML 良构，可过 minidom）

| 区块 | 内容与来源字段 |
|---|---|
| 元信息 | report_id / sample_id / scan_ids（逗号连接）/ generated_at（ISO8601 本地时区秒级）/ standard_id + standard_sha（来自 grading.standard_yaml_sha） |
| 定级结论（大字） | grade、passed→合格/不合格、primary_count/secondary_count、reasons（模板键按 lang 渲染，未登记键原样）、标准 SHA-256 |
| 缺陷统计 | bean_count、缺陷粒数与缺陷率（defect_counts 中 counts_as_defect 类合计 / bean_count）、逐类行：三语名（taxonomy 唯一数据源）+ 主/次归属 + 粒数 + 占比；行排序=严重度降序 |
| 计量摘要 | 目数分布柱状图 PNG（§5）、逐筛目行（目数/粒数/占比，数值升序）、sieve_pass 三态（是/否/—）、直径 min/max/mean/median（2 位小数）、估重 + weight_model、整盘色（L/a/b lab8）、ΔE 均值 + 分桶行 |
| 证据卡 + 溯因 | §5 证据卡；溯因段（causes 逐条：缺陷三语名 + 环节译名 + likelihood 2 位 + 证据句；advice 列表；citations；backend 标签）；agent_report=None 时整段不渲染 |
| 页脚 | 标准核对角标（§3）、QR 图 + payload、sha256 |

## 5. 证据卡与图表的关键语义

- **立卡口径**：`final_severity_rank > 0` 逐豆一卡（含 peaberry 标注豆）；好豆不立卡。
  与缺陷统计表的口径（`grading.defect_counts`，peaberry 不计缺陷）**分工不同**——
  卡是「证据」，表是「计数」，eval 断言卡集合 == 非好豆集合。
- **主判定面**：`worst_side` 即判定面；`both` 时按契约取 conf 高者。
- **每卡必有图**：crop 存在 → 字节缓冲读回（中文路径安全）内嵌 data URI；缺失/损坏 →
  **确定性占位图**（160×120，豆号 + PLACEHOLDER + 质心坐标 mm；sha256(`bean_id|side`) 派生
  扰动，同输入像素级一致）+ 卡面三语「占位图」标记。
- **直方图字体链**（charts.py）：zh 用 CJK 候选链（SimHei 优先，7 候选）+ DejaVu Sans 兜底；
  **vi/en 用 DejaVu Sans 优先**——SimHei 缺越南语声调字形（ố/ạ/ắ）实测渲染方框，eval 抓获后
  改为按语言选链。`axes.unicode_minus=False`（CJK 字体缺 U+2212，负号变方框）；
  一个 CJK 字体都没有时中文文案回退英文（`chart_labels`）。
- **i18n**：`STRINGS` 三语各 **96 键**（2026-09-29 实测；键集对等有 eval 强校验，新增文案三语
  同步加）；唯一允许占位符 `{n}`；缺陷名不在本表（taxonomy 是唯一数据源）；
  `STAGE_I18N` 负责把契约的中文环节名译 en/vi；`STANDARD_DISPLAY` 三语标准显示名
  （cqi 三语取契约给定示例，其余未核对只显示编号）。

## 6. M13 应用壳：护照与结果的交付端点（beaneye/app/main.py）

| 端点 | 语义 | 失败态 |
|---|---|---|
| `POST /api/v1/scans` | multipart 双图（字段名 top/bottom，≤64MB/图，解码 ≥200×200px）或 JSON `{"synth": {...}}`（n_beans[0,400] 默认36 / width,height[256,4096] 默认1024 / seed[0,2^31−1] 默认20260928 / defect_rate[0,1] 默认0.2）→ `{job_id, poll}` | 400（Content-Type 不符/缺图/超限/未知标准）；synth 引擎缺位→回退内置 MockSource 并在 `degraded_reasons.synth` 注明 |
| `GET /api/v1/jobs/{id}` | 状态机 queued→running→done|failed + stage + error/error_stage | 404 |
| `GET /api/v1/results` / `/{id}` | 列表摘要 / 完整信封（BatchResult 全文 + degraded_stages/reasons + pairing_summary + passport_urls + timings） | 404 |
| `GET /api/v1/results/{id}/passport?lang=zh[&download=1]` | 护照 HTML inline/attachment（文件名 `passport_{lang}_{id前8}.html`） | 404（无该语言/文件缺失）；409（护照未生成，带降级原因） |
| `GET /api/v1/results/{id}/evidence/{bean_id}/{side}` | 逐豆证据裁剪图 PNG | 400（side 非法）/404（无豆/无该面观测/图缺失） |
| `GET /api/v1/standards` | 可用标准列表（display/grades/verified=warnings 为空/warning_count）+ 默认标准（优先 cqi_fine_robusta） | — |
| `GET /demo`（`/` 重定向） | 单页演示 UI，静态资源全内嵌零外链 | — |

- 管线九阶段：`ingest → calibration → segment → classify → pairing → metrology → grading →
  agent → passport`；**校验和一致性约定**：QR 内嵌 sha256(BatchResult)，故 BatchResult 必须在
  护照前定型——`timings_s` 覆盖到 agent 为止，护照耗时单列 `passport_runtime_s`（写回会把
  QR 校验和与结果脱钩）。
- **降级语义**：分割/分类缺位 → 0 检出继续全链路并显式标注（NullSegModel/NullClsModel，
  version=`unavailable:null`）；护照失败 → 作业仍 done、护照入降级清单；标定失败 → 作业
  failed（图上无四角码无法给 mm 坐标，静默继续只会产出假结果）。
- 装配约定：`beaneye.segment`/`beaneye.classify` 暴露 `build_default(**kwargs)` 工厂即被
  自动接线（M4/M5 落地零改动）；协议缺陷注记：`SegModel.predict(img_rgb, scan)` 不携带
  side，装配器**每面各调一次**并经 `normalize_seg_result` 规范化 side/scan_id/mask_id
  （`{side}_{i:04d}`），已上报规划方。
- 进程内作业：ThreadPoolExecutor（`max_workers` 默认 2）；作业/结果存内存（重启清空属预期，
  文件持久在数据根 `$BEANEYE_DATA_ROOT` 或 `<仓库>/out/app`）；起服务 `python -m beaneye.app`
  （默认 127.0.0.1:8600）。

## 7. eval（2026-09-29 实测）

```bash
python -m pytest tests/test_report.py -q   # → 27 passed
python -m pytest tests/test_app.py -q      # → 14 passed（httpx ASGI 端到端）
# 护照覆盖：三语键集对等+空值；sha 确定性/往返/敏感；QR 负载往返+三态非法拒收；三语生成
#   各 94–98KB；QR 从 HTML 内嵌图解码回读 payload/report_id/sha 一致（逐语言）；minidom 良构
#   +lang 属性+五区块；证据卡集合==缺陷豆集合+逐卡字段一致+好豆不立卡+每卡必有图+占位图
#   确定性；零缺陷盘 evidence.none；角标三态；溯因两态+环节名已译；单份 <5s；字体链断言
```
