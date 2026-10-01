# M6 文件通道位置语义 spec（FileReport / FileFinding / location / bbox / 风险分级 / 导出）

> 状态：frozen（§5.5 冻结——字段只增不改名）。对照 `filechannel/{models,inspect,parsers,ocr,sanitize,pdf_engine,service,errors}.py`
> 逐行核验于 2026-09-29。

## 1. FileReport / FileFinding（filechannel/models.py，§5.5 形状一字不差）

```json
{
  "file_id": "file_...", "filename": "低保公示.pdf", "sha256": "...",
  "kind": "pdf", "pages": 3,
  "findings": [ {"page": 1, "bbox": [x0,y0,x1,y1], "location": null, "finding": {Finding}} ],
  "risk_level": "HIGH",
  "summary": {"ID_CARD": 12, "PERSON": 30}
}
```

- `FileKind = "pdf" | "docx" | "xlsx" | "scan_pdf"`；`RiskLevel = "HIGH" | "MID" | "LOW" | "NONE"`；
- 全模型 `extra="forbid"`；`finding` 即 §5.1 Finding（fid 全文自增 `f_0001` 起——文件内口径）。

## 2. 位置语义（FileFinding 三字段，models.py:25-39）

| 字段 | 语义 | 适用 kind |
|---|---|---|
| `page` | 1 起始页码（ge=1） | 全部 |
| `bbox` | **render 坐标系** `[x0,y0,x1,y1]`：原点左上、y 轴向下、单位 pt，`x0<x1、y0<y1`；span 的 bbox = 覆盖字符 charbox 并集后翻转（读取库原生为左下原点） | 仅 pdf / scan_pdf |
| `location` | 字符串定位（parsers.py 模块文档口径）：见 §3 | 仅 docx / xlsx；pdf/scan_pdf 恒 None |

scan_pdf 的 bbox 来自 **OCR 重建层**（`OcrTextLayer.union`：行内按字符渲染宽度加权插值，
全角 1.0 / 半角 0.5 权重；跨行 span 逐行取子框再并集，ocr.py:26-30）。

## 3. location 字符串格式（parsers.py 模块文档，冻结）

- docx：`para:5` / `table:2:r1:c3`（嵌套 `…:table:1:r1:c1`）/ `header:1:para:2` /
  `footer:1:table:1:r1:c1`（段落/表序号 1 起始）；
- xlsx：`Sheet1!B3` / `Sheet1!B3#comment`（批注）/ `Sheet1!C2#cached`（公式缓存值补段）；
- pdf / scan_pdf：恒 `None`——定位由 `page` + `bbox` 承担（§5.5 原生形状）。

## 4. 解析面（parsers.py，T3.1 文本层权威实现）

- **docx**：正文段落 + 正文表格（含嵌套、合并单元格去重）+ 各节页眉/页脚
  （`is_linked_to_previous` 继承节跳过防同文重复）；
- **xlsx**：全部工作表（含隐藏表）全部单元格——**隐藏列/隐藏行同权重读取**（隐藏正是
  最易漏检面）；字面值 + 公式文本（data_only=False）+ 公式缓存值（data_only=True，仅与
  字面值不同时补段）+ 单元格批注；
- **pdf 文本层**：读取库模块名经 `config/filechannel.yaml` 配置、importlib 动态加载
  （公开仓库卫生——库名只进 config）；逐页 textpage 全文 + 逐字符 charbox；
- **scan_pdf**：整页零文本 → OCR 路径（ocr.py）：按 `render_dpi=300` 渲染位图 → OCR 引擎
  （纯 CPU——params 显式关闭全部硬件加速执行提供器）→ 重建可检测文本（按页序换行拼接，
  记录行首偏移）+ 命中框。容差如实报告：召回与零残留验收均以"重建文本上的检测命中"为准。

## 5. 体检管线与风险分级（inspect.py:1-30，§5.5 字面口径）

`inspect_bytes`：大小闸（>50MB → FileTooLargeError）→ 解析 → **detect 全套**（规则层 +
NER 适配器；语义 moderate 不产出 Finding、不进 FileReport）→ 装配（pdf 回填 charbox 并集
bbox / scan_pdf 回填 OCR 框 / docx+xlsx 回填 location）→ 分级：

| 级 | 判定 |
|---|---|
| HIGH | 含**非白名单** SENSITIVE_ATTR，或非白名单 ID_CARD+BANK_CARD ≥ 批量线（config thresholds.batch_pii_to_govcloud，与 §5.2 同源） |
| MID | 含其它非白名单结构化 PII（12 码值名单，含 PERSON/ADDRESS） |
| LOW | 有命中但均不属上述（白名单/词面类/文号等） |
| NONE | 零命中 |

密级标识/工作秘密属 BLOCK/ROUTE 语义，不进分级阶梯，但仍作为 finding 呈现在报告与 summary。

## 6. 彻底删除式导出（sanitize.py + pdf_engine.py，验收铁律）

**口径**：对导出物重新走「解析+检测」，seeded PII 命中数必须为 0——实现为导出管线内
**硬闸**（非仅验收断言）：

- docx：删除命中 span 覆盖的 run 文本片段（`docx-run-delete`；run 边界跨越时逐 run 切除，
  非替换非隐藏）；
- xlsx：命中单元格删值（值+批注清空）；命中落在**隐藏列/隐藏行 → 整列/整行删除**
  （删列而非隐藏）；导出前解除全部残余隐藏行列与隐藏工作表（`xlsx-cell-column-delete`）；
- pdf：引擎链（`config/app.yaml pdf_engine_module` 主引擎 + `config/filechannel.yaml`
  内容流手术引擎 + 栅格兜底引擎，**库名只进 config、源码 importlib 动态加载**）——逐引擎
  「涂删 → 导出物 re-ingest → detect 复核」，不净或引擎缺失**自动回退下一引擎**，链尽仍
  不净报 `ExportBlockedError`（宁可阻止不可漏删）；
- scan_pdf：唯一可行形态 = **重打码渲染版**（渲染 → 黑框覆盖命中框 → 整页重栅格化为纯
  图像 PDF，杜绝底层文字；`scan-raster-redaction`）；复核不净外扩重试（+2pt）；
- 验证收敛：`*_verified` 入口就地重跑 `inspect_bytes`，存在**非白名单**残留即继续清理/
  回退，最多 `SANITIZE_MAX_PASSES=3` 轮（删除后相邻文本拼接可能产生新命中）；白名单命中
  照常保留（白名单不参与脱敏也不参与删除）。

导出响应头：`X-Report-Id`（= 导出前体检报告 id，登记表为内存有界 LRU 容量 128）+
`X-Sanitize-Method`（实际生效方式，如实标注）。
错误语义：FileTooLargeError→413 / UnsupportedFileType→400 / DocumentParseError→422 /
ExportBlockedError→422。

## 7. eval 指针

| eval | 通过线 |
|---|---|
| `evals.m6_filesvc` | seeded 夹具 docx/xlsx/pdf 各 5 份 inspect 命中 100% → export → re-ingest 零残留；xlsx 隐藏列导出后无 hidden 无值；`M6 FILESVC(text-layer+export): N/N checks passed`，exit 0 |
| `evals.m6_ocr` | seeded scan_pdf 3 份（每份 4 个身份证）OCR 路径召回 ≥ 0.90（OCR_ID_CARD_RECALL_MIN）；导出重栅格化打码零残留；`M6 OCR(scan-pdf): N/N` |
| `evals.m9_webui` 3-7 项 | 体检页端到端 + 错误形状（400/413/422 信封） |
| 六道门指针 | gate_b3 ③ 首验（filesvc）→ gate_b4 ③⑤（ocr 首验 + filesvc 栅格兜底回归）→ gate_b5 整门链 |
