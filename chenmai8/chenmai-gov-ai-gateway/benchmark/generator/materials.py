"""三路由 e2e 演示材料（M8 产出物 · §9 U3 / §10 场景 2 同源夹具）。

三份 seeded **真实形态材料**，经 T1.1 生成器（:mod:`benchmark.generator.fixtures`）
的确定性写入器产出为真实 docx/pdf 文件（而非构造 JSON / 纯文本）：

- ordinary → docx（一级标题 + 段落：普通公文，零敏感命中 → INTERNET 负例控制）；
- roster   → docx（标题 + 段落 + 名单表格：低保对象/低保户 SENSITIVE_ATTR +
             ≥3 身份证批量名单双判定 → GOVCLOUD）；
- classified → pdf（文本层逐行：机密★/内部资料·注意保密/不得外传 → BLOCK 403）。

确定性契约（与 fixtures.py 同源纪律）：docx 保存后 ``rezip_deterministic`` 重写
zip（固定条目时间戳 + core.xml 修改时间固定）；pdf 经
``config/synthetic_corpus.yaml`` 配置的库模块动态加载写入（铁律 E，源码零库名；
固定元数据 + no-new-id）。材料值为**冻结常量**（不走随机源），同输入两次构建
→ 字节级一致（e2e 物化步逐轮自证，见 ops/e2e_smoke.materialize_materials）。

值层面冻结说明：seeded 值（人名×4 / 身份证×3 / 手机号×2 + 密级词）与
ops/e2e_smoke、evals/m6_filesvc 各自持有的独立副本同源（三方互不 import，
防止牵引网关链路）；任何一方变更值需同步另两方。

往返形态（:func:`material_plain_text` 口径）：材料正文经 filechannel 文本层
权威解析（``filechannel.parsers.parse_any``）后的逐字预测——

- docx = 非空段落（文档序）+ 非空表格单元格（行主序），以 ``"\\n"`` 连接；
- pdf  = 逻辑行以 ``"\\r\\n"`` 连接（坐标级文本抽取的行分隔形态，无尾随换行）。

e2e 以「抽取文本 == plain_text」做往返完整性断言后才把**文件正文**作为
/chat/completions 的 prompt 发送（U3 断言 = 真实文件内容驱动）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from benchmark.generator.fixtures import (
    _PDF_MAX_COLS,
    Draft,
    _sha256,
    _write_docx,
    _write_pdf,
)


def _valid_id(prefix17: str) -> str:
    """GB11643 校验位补算（与 ops/e2e_smoke._valid_id 同式，独立副本）。"""
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    codes = "10X98765432"
    total = sum(int(ch) * w for ch, w in zip(prefix17, weights, strict=True))
    return prefix17 + codes[total % 11]


# ── 冻结 seeded 值（值层面三方同源：本模块 / ops/e2e_smoke / evals/m6_filesvc）──
_ID_A = "11010519491231002X"
_ID_C = _valid_id("46002320010307123")
_ID_D = _valid_id("11010519491231101")
_PHONE_A = "13800138000"
_PHONE_BLOCKED = "13900139001"          # 仅出现在机密材料（BLOCK，上游必须零感知）
_PERSON = "张三"


@dataclass(frozen=True)
class MaterialSpec:
    """一份三路由材料的构造规格（值冻结 + 真实文件形态 + seeded span）。"""

    filename: str
    kind: str                                    # docx | pdf
    #: 正文段落：docx 首行 = 一级标题、其余为段落；pdf 逐行写入文本层
    lines: tuple[str, ...]
    #: docx 附加表格（含表头，行主序；空串单元格 = 物理无值）
    table_rows: tuple[tuple[str, ...], ...] = ()
    #: seeded span（表面值, EntityClass 值）——构造面声明，不回读被测检测器
    spans: tuple[tuple[str, str], ...] = ()


ORDINARY_MATERIAL = MaterialSpec(
    filename="ordinary_flood_drill_notice.docx",
    kind="docx",
    lines=(
        "关于开展全镇防汛演练的通知",
        "各村（居）委会：",
        "为检验防汛应急预案的可操作性，定于本周四上午九点在镇政府大院开展防汛演练，",
        "请各村网格员提前到场并做好记录，演练结束后将情况汇总报镇党政办。",
        "特此通知。",
        "某镇人民政府办公室",
        "2026年9月24日",                      # 落款日期：DATE_BIRTH 有「出生」上下文门控，零命中
    ),
)

# 低保名单：敏感个人信息（低保对象/低保户 → SENSITIVE_ATTR·ROUTE_FLAG）+
# ≥3 身份证（批量名单）双判定 → GOVCLOUD；期望脱敏面 = 人名×3 + 身份证×3 + 手机号×1。
ROSTER_MATERIAL = MaterialSpec(
    filename="low_income_roster_202610.docx",
    kind="docx",
    lines=(
        "某县民政局低保对象名单（2026年10月·节选）",
        "经入户核查与县级联审，现将本月新增低保户名单公示如下：",
        "对名单有异议的，请在公示期内向县民政局社会救助科反映。",
    ),
    table_rows=(
        ("姓名", "公民身份号码", "联系电话"),
        ("李四", _ID_A, _PHONE_A),
        ("王五", _ID_C, ""),
        ("赵六", _ID_D, ""),
    ),
    spans=(
        ("李四", "PERSON"), ("王五", "PERSON"), ("赵六", "PERSON"),
        (_ID_A, "ID_CARD"), (_ID_C, "ID_CARD"), (_ID_D, "ID_CARD"),
        (_PHONE_A, "PHONE_MOBILE"),
    ),
)

CLASSIFIED_MATERIAL = MaterialSpec(
    filename="classified_cadre_minutes.pdf",
    kind="pdf",
    lines=(
        "机密★某县干部考察纪要（内部资料·注意保密）",
        f"考察对象：{_PERSON}，联系电话{_PHONE_BLOCKED}。",
        "考察组意见：该同志政治素质过硬、工作实绩突出，建议进一步培养使用。",
        "本纪要不得外传，请按规定归档管理。",
    ),
    spans=((_PERSON, "PERSON"), (_PHONE_BLOCKED, "PHONE_MOBILE")),
)

MATERIALS: tuple[MaterialSpec, ...] = (
    ORDINARY_MATERIAL, ROSTER_MATERIAL, CLASSIFIED_MATERIAL,
)

_SPEC_BY_FILENAME = {m.filename: m for m in MATERIALS}


def spec_of(filename: str) -> MaterialSpec:
    """按夹具文件名取材料规格（未知文件名即 KeyError，调用方显式失败）。"""
    return _SPEC_BY_FILENAME[filename]


def material_plain_text(spec: MaterialSpec) -> str:
    """材料正文的抽取面预测（往返形态，见模块 docstring）。

    这是「夹具文件里写的是什么」的构造面真相：e2e 抽取文件正文后先与本函数
    全等比对（往返完整性），再把抽取文本作为 prompt 发送。
    """
    if spec.kind == "docx":
        parts = [*spec.lines]
        parts.extend(cell for row in spec.table_rows for cell in row if cell)
        return "\n".join(parts)
    if spec.kind == "pdf":
        return "\r\n".join(spec.lines)
    raise ValueError(f"unsupported material kind: {spec.kind}")


def _draft_of(spec: MaterialSpec) -> Draft:
    """MaterialSpec → fixtures.Draft（复用 T1.1 确定性写入器）。"""
    return Draft(
        filename=spec.filename, kind=spec.kind, template="material",
        lines=list(spec.lines),
        chunk_rows=[[(line, False)] for line in spec.lines],
        table_rows=[list(row) for row in spec.table_rows],
    )


def build_materials(outdir: Path) -> list[dict]:
    """构建三份材料为真实 docx/pdf 文件（确定性、幂等），返回 manifest 条目。

    构造面自检（写盘前）：段落非空、pdf 行不超文本层打包宽度（超宽会被二次
    换行、破坏 plain_text 往返预测）、每个 seeded span 表面值必须在正文中。
    """
    outdir.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for spec in MATERIALS:
        if not spec.lines or any(not line.strip() for line in spec.lines):
            raise ValueError(f"material lines must be non-empty: {spec.filename}")
        text = material_plain_text(spec)
        if spec.kind == "pdf":
            for line in spec.lines:
                if len(line) > _PDF_MAX_COLS:
                    raise ValueError(
                        f"pdf material line exceeds packing width {_PDF_MAX_COLS}: "
                        f"{spec.filename}:{line[:12]}…")
        elif spec.kind != "docx":
            raise ValueError(f"unsupported material kind: {spec.kind}")
        for surface, _etype in spec.spans:
            if surface not in text:
                raise ValueError(
                    f"declared span missing from material body: {surface!r} "
                    f"in {spec.filename}")
        draft = _draft_of(spec)
        path = outdir / spec.filename
        if spec.kind == "docx":
            _write_docx(draft, path)
        else:
            _write_pdf(draft, path, None)
        entries.append({
            "filename": spec.filename,
            "kind": spec.kind,
            "sha256": _sha256(path.read_bytes()),
            "plain_text_chars": len(text),
            "spans": [{"type": etype, "value": surface}
                      for surface, etype in spec.spans],
        })
    return entries


__all__ = [
    "CLASSIFIED_MATERIAL",
    "MATERIALS",
    "ORDINARY_MATERIAL",
    "ROSTER_MATERIAL",
    "MaterialSpec",
    "build_materials",
    "material_plain_text",
    "spec_of",
]
