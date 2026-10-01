"""M10 质量护照 eval（W10）。

运行（仓库根）::

    pytest tests/test_report.py -q

覆盖（开发指令 §4 M10 + W10 自验收）：
1. 三语文案键集完全对齐（键齐全、值非空、契约 reason 键在位）；
2. 规范化校验和：确定性、序列化往返不变、内容敏感；
3. QR 验真负载：组装/解析往返、非法输入拒绝；
4. 合成整盘 BatchResult → 三语 HTML 护照：
   - 三份文件生成且各 >20KB，PassportReport 契约自洽；
   - 二维码（segno 渲染）从 HTML 内嵌图经 zxing-cpp 解码回读，
     payload 与 sha256 与输入记录一致；
   - HTML 以 xml.dom.minidom 良构检查（XHTML）；
   - 证据卡数量/内容与输入记录一致（bean_id/缺陷名/置信度/坐标），
     缺图落占位图（含坐标），有裁剪图则真实内嵌——每卡必有图；
   - 标准核对角标三态；溯因段有/无两态；生成 ≤5s/份。
5. 目数直方 PNG（matplotlib）：字体链按语言选择（越南语声调字形不落
   SimHei——实测坑），meta 报告实际字体与文案语言。

全部素材为合成数据（几何/LAB/裁剪图均测试内生成），不依赖任何真实豆图数据集。
"""

from __future__ import annotations

import base64
import re
import time
import xml.dom.minidom
from pathlib import Path

import cv2
import numpy as np
import pytest
import zxingcpp

from beaneye.report import (
    LANGS,
    STRINGS,
    ReportError,
    build_passport,
    build_qr_payload,
    canonical_json,
    canonical_sha256,
    parse_qr_payload,
    sieve_histogram_png,
)
from beaneye.schemas import (
    AgentReport,
    BatchResult,
    BeanMask,
    BeanObservation,
    CauseItem,
    GradingDecision,
    Measurements,
    PairedBean,
    StatsSummary,
)
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
RANK = {k: TAX.severity_rank(k) for k in TAX.keys()}

RESULT_ID = "2f6a9c31-5d24-4b8e-9a70-1e4c8b6d2f11"
STANDARD_SHA = "b" * 64


# ---------------------------------------------------------------------------
# 合成整盘结果（12 粒：5 缺陷 + 7 好豆；裁剪图部分真实部分缺失）
# ---------------------------------------------------------------------------

def _mask(mid: str, side: str, cx: float, cy: float) -> BeanMask:
    pts = [
        [cx - 3.0, cy - 2.0], [cx - 1.0, cy - 3.2], [cx + 3.1, cy - 0.8],
        [cx + 2.2, cy + 3.0], [cx - 2.4, cy + 2.1],
    ]
    return BeanMask(
        mask_id=mid,
        side=side,
        polygon=pts,
        bbox_mm=(cx - 3.2, cy - 3.2, cx + 3.1, cy + 3.0),
        area_mm2=28.0,
        centroid_mm=(cx, cy),
        source="oracle",
        conf=1.0,
    )


def _obs(mid: str, side: str, defect: str, conf: float, cx: float, cy: float, crop: str) -> BeanObservation:
    return BeanObservation(
        obs_id=mid,
        side=side,
        defect=defect,
        defect_conf=conf,
        severity_rank=RANK[defect],
        crop_path=crop,
        mask=_mask(mid, side, cx, cy),
        color_lab=(132.6, 118.0, 148.0) if defect == "normal" else (91.8, 142.0, 140.0),  # lab8 标度
        eq_diameter_mm=6.0,
    )


def _write_crop(path: Path, *, hue_seed: int) -> None:
    """确定性合成裁剪图 PNG（48x64 渐变+椭圆，非任何真实豆图）。"""
    rng = np.random.default_rng(hue_seed)
    img = np.full((64, 48, 3), 235, dtype=np.uint8)
    base = (60 + hue_seed * 13 % 120, 90 + hue_seed * 7 % 80, 120 + hue_seed * 5 % 60)
    cv2.ellipse(img, (24, 32), (16, 24), int(rng.integers(0, 180)), 0, 360, base, -1, lineType=cv2.LINE_AA)
    cv2.ellipse(img, (24, 32), (16, 24), 30, 0, 360, (80, 80, 80), 1, lineType=cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.tobytes())


def synth_result(crop_root: Path, *, with_agent: bool = True, crop_plan: dict[str, set[str]] | None = None) -> BatchResult:
    """构建合成 BatchResult。

    ``crop_plan``: bean_id → 已写盘裁剪图的面集合；缺省
    ``{"b0001": {"top","bottom"}, "b0002": {"bottom"}, "b0004": {"top"}}``，
    其余缺陷豆的裁剪图缺失（走占位图路径）。
    """
    crop_plan = crop_plan or {"b0001": {"top", "bottom"}, "b0002": {"bottom"}, "b0004": {"top"}}
    # (bean 序号, top 规格(defect, conf) 或 None, bottom 规格 或 None)
    layout = [
        (1, ("black", 0.92), ("normal", 0.99)),
        (2, ("broken", 0.70), ("broken", 0.90)),
        (3, None, ("sour", 0.85)),
        (4, ("peaberry", 0.66), None),
        (5, ("mold", 0.88), ("normal", 0.97)),
    ] + [(i, ("normal", 0.99), ("normal", 0.98)) for i in range(6, 13)]

    beans: list[PairedBean] = []
    for idx, top_spec, bottom_spec in layout:
        bean_id = f"b{idx:04d}"
        written = crop_plan.get(bean_id, set())
        sides = []
        for side, spec in (("top", top_spec), ("bottom", bottom_spec)):
            if spec is None:
                continue
            defect, conf = spec
            cx = 10.0 + (idx % 4) * 22.0 + (0.0 if side == "top" else 1.1)
            cy = 20.0 + (idx % 3) * 24.0 + (0.0 if side == "top" else 1.3)
            mid = f"{side}_{bean_id}"
            crop_rel = f"crops/{side}_{bean_id}.png"
            if side in written:
                _write_crop(crop_root / crop_rel, hue_seed=idx)
            sides.append(_obs(mid, side, defect, conf, cx, cy, crop_rel))
        top = next((o for o in sides if o.side == "top"), None)
        bottom = next((o for o in sides if o.side == "bottom"), None)
        cost = 1.5 if (top is not None and bottom is not None) else -1.0
        beans.append(PairedBean.from_sides(bean_id, top, bottom, pairing_cost=cost))

    grading = GradingDecision(
        standard_id="cqi_fine_robusta",
        grade="Fine",
        passed=False,
        primary_count=3,  # black sour mold
        secondary_count=1,  # broken（peaberry counts_as_defect=false 不计次缺陷，W13）
        defect_counts={"black": 1, "broken": 1, "sour": 1, "peaberry": 1, "mold": 1},
        reasons=[
            "grading.reason.primary_over_limit",
            "grading.reason.secondary_within_limit",
        ],
        standard_yaml_sha=STANDARD_SHA,
    )
    measurements = Measurements(
        bean_count=12,
        sieve_hist={"13": 3, "14": 4, "15": 3, "16": 2},
        sieve_pass=True,
        eq_diameter_mm_stats=StatsSummary(min=5.0, max=8.1, mean=6.3, median=6.2),
        color_lab_mean=(133.6, 117.2, 148.6),  # lab8 标度
        delta_e_mean=3.42,
        delta_e_hist={"0-2": 4, "2-4": 5, "4-8": 3},
        est_weight_g=32.1,
        weight_model="area_linear:v1",
    )
    agent = None
    if with_agent:
        agent = AgentReport(
            lang="zh",
            causes=[
                CauseItem(
                    defect="black",
                    stage="干燥",
                    likelihood=0.72,
                    evidence_summary="1 粒黑豆且色差远超参考色，指向干燥温度过高或堆闷。",
                )
            ],
            advice=["降低干燥温度并摊薄铺晒", "采收后 24h 内完成脱果脱胶"],
            citations=["std:cqi_fine_robusta#full_black", "kb:chunk-012"],
            backend="template",
        )
    return BatchResult(
        result_id=RESULT_ID,
        sample_id="sample_w10",
        scan_ids=["scan_w10_0001"],
        beans=beans,
        measurements=measurements,
        grading=grading,
        agent_report=agent,
        timings_s={"segment": 0.9, "classify": 0.2, "pairing": 0.05, "metrology": 0.1},
        pipeline_versions={"segment": "oracle", "classify": "rules_v0", "standard": "cqi_fine_robusta"},
    )


DEFECTIVE_IDS = ["b0001", "b0002", "b0003", "b0004", "b0005"]  # final_defect != normal


@pytest.fixture()
def synth(tmp_path: Path) -> BatchResult:
    return synth_result(tmp_path)


@pytest.fixture()
def passport(tmp_path: Path, synth: BatchResult) -> object:
    return build_passport(synth, tmp_path / "reports", crop_root=tmp_path, standard_verified=False)


def _read(path_str: str) -> str:
    return Path(path_str).read_text(encoding="utf-8")


def _card(html: str, bean_id: str) -> str:
    m = re.search(rf'data-bean-id="{bean_id}".*?</article>', html, re.S)
    assert m is not None, f"证据卡缺失: {bean_id}"
    return m.group(0)


# ---------------------------------------------------------------------------
# 1. 三语文案键集对齐
# ---------------------------------------------------------------------------

def test_i18n_key_parity():
    assert tuple(STRINGS) == LANGS == ("zh", "en", "vi")
    ref = set(STRINGS["zh"])
    assert ref, "zh 键集为空"
    for lang in ("en", "vi"):
        missing = ref - set(STRINGS[lang])
        extra = set(STRINGS[lang]) - ref
        assert not missing, f"{lang} 缺键: {sorted(missing)}"
        assert not extra, f"{lang} 多键: {sorted(extra)}"
    for lang, table in STRINGS.items():
        empty = [k for k, v in table.items() if not str(v).strip()]
        assert not empty, f"{lang} 存在空值键: {empty}"


def test_i18n_contract_reason_keys_present():
    """契约 fixture 使用的判定理由模板键 + 环节名表必须三语在位。"""
    for key in (
        "grading.reason.primary_over_limit",
        "grading.reason.secondary_within_limit",
        "grading.reason.primary_within_limit",
        "grading.reason.secondary_over_limit",
        "grading.reason.sieve_pass",
        "grading.reason.sieve_fail",
    ):
        for lang in LANGS:
            assert key in STRINGS[lang], f"{lang} 缺 {key}"
    for stage in ("采摘", "发酵", "干燥", "仓储", "脱壳"):
        for lang in LANGS:
            assert f"stage.{stage}" in STRINGS[lang]


# ---------------------------------------------------------------------------
# 2. 规范化校验和
# ---------------------------------------------------------------------------

def test_canonical_sha256_deterministic_and_sensitive(synth: BatchResult):
    sha1 = canonical_sha256(synth)
    assert re.fullmatch(r"[0-9a-f]{64}", sha1)
    # 同对象重算一致
    assert canonical_sha256(synth) == sha1
    # 序列化往返后一致（规范化 JSON 与字段序无关）
    clone = BatchResult.from_json(synth.to_json())
    assert canonical_json(clone) == canonical_json(synth)
    assert canonical_sha256(clone) == sha1
    # 内容变化 → 校验和变化
    mutated = synth.model_copy(deep=True)
    mutated.sample_id = "sample_other"
    assert canonical_sha256(mutated) != sha1


# ---------------------------------------------------------------------------
# 3. QR 验真负载
# ---------------------------------------------------------------------------

def test_qr_payload_roundtrip():
    sha = "a" * 64
    payload = build_qr_payload("rpt-001", sha, verify_base_url="https://verify.example.co/")
    assert payload == f"https://verify.example.co/r/rpt-001|{sha}"
    rid, got_sha = parse_qr_payload(payload)
    assert (rid, got_sha) == ("rpt-001", sha)


@pytest.mark.parametrize(
    "bad",
    [
        "https://verify.example.co/r/rpt-001",  # 无分隔符
        "https://verify.example.co/r/|aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # 空 id
        "https://verify.example.co/r/rpt-001|xyz",  # 校验和非法
    ],
)
def test_qr_payload_rejects_malformed(bad: str):
    with pytest.raises(ReportError):
        parse_qr_payload(bad)


def test_build_qr_payload_rejects_bad_sha():
    with pytest.raises(ReportError):
        build_qr_payload("rpt-001", "nothex")


# ---------------------------------------------------------------------------
# 4a. 三语生成 + PassportReport 契约自洽
# ---------------------------------------------------------------------------

def test_trilingual_passports_generated(synth: BatchResult, passport):
    langs = [lg for lg in LANGS]
    assert passport.langs == langs
    assert passport.report_id == synth.result_id
    assert set(passport.html_paths) == set(langs)
    assert passport.sha256 == canonical_sha256(synth)
    assert passport.qr_payload == f"https://verify.beaneye.example/r/{synth.result_id}|{passport.sha256}"
    for lg in langs:
        p = Path(passport.html_paths[lg])
        assert p.is_file(), f"{lg} 文件不存在: {p}"
        assert p.stat().st_size > 20 * 1024, f"{lg} 文件 {p.stat().st_size}B 未超 20KB"
        html = _read(passport.html_paths[lg])
        assert f'lang="{lg}"' in html
    # PassportReport 自身过 M1 契约往返
    clone = type(passport).from_json(passport.to_json())
    assert clone == passport


# ---------------------------------------------------------------------------
# 4b. 二维码解码回读（zxing-cpp，逐语言）
# ---------------------------------------------------------------------------

def _qr_b64_from_html(html: str) -> bytes:
    m = re.search(r'class="qr" src="data:image/png;base64,([A-Za-z0-9+/=]+)"', html)
    assert m is not None, "HTML 中未找到二维码图"
    return base64.b64decode(m.group(1))


@pytest.mark.parametrize("lang", LANGS)
def test_qr_decodes_to_payload_and_checksum(tmp_path: Path, synth: BatchResult, passport, lang: str):
    html = _read(passport.html_paths[lang])
    png = _qr_b64_from_html(html)
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    results = zxingcpp.read_barcodes(img)
    assert results, "二维码解码失败"
    text = results[0].text
    assert text == passport.qr_payload
    rid, sha = parse_qr_payload(text)
    assert rid == synth.result_id
    assert sha == passport.sha256 == canonical_sha256(synth)


# ---------------------------------------------------------------------------
# 4c. HTML 良构（xml.dom.minidom）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lang", LANGS)
def test_html_wellformed_xhtml(passport, lang: str):
    content = _read(passport.html_paths[lang])
    assert "<!ENTITY" not in content, "护照 HTML 不应包含实体定义（输入校验）"
    doc = xml.dom.minidom.parseString(content)
    root = doc.documentElement
    assert root.tagName == "html"
    assert root.getAttribute("lang") == lang
    # 关键区块在位
    ids = {e.getAttribute("id") for e in doc.getElementsByTagName("section")}
    assert {"grading", "defects", "metrology", "evidence", "agent"} <= ids


# ---------------------------------------------------------------------------
# 4d. 证据卡与输入记录一致
# ---------------------------------------------------------------------------

def test_evidence_card_set_matches_input(passport):
    for lang in LANGS:
        html = _read(passport.html_paths[lang])
        found = re.findall(r'data-bean-id="([^"]+)"', html)
        assert found == DEFECTIVE_IDS, f"{lang}: 证据卡集合与缺陷豆不一致: {found}"


@pytest.mark.parametrize("lang", LANGS)
def test_evidence_card_content_matches_input(passport, lang: str):
    html = _read(passport.html_paths[lang])
    # 逐卡核对（bean_id / 三语缺陷名 / 主判定面置信度 / 判定面坐标）
    expected = {
        "b0001": ("black", "top", 0.92),
        "b0002": ("broken", "bottom", 0.90),  # both → conf 高者
        "b0003": ("sour", "bottom", 0.85),
        "b0004": ("peaberry", "top", 0.66),
        "b0005": ("mold", "top", 0.88),
    }
    for bean_id, (defect, side, conf) in expected.items():
        card = _card(html, bean_id)
        assert bean_id in card
        name = getattr(TAX.get(defect), lang)
        assert name in card, f"{bean_id} 缺缺陷名 {name!r}（{lang}）"
        assert f"side.{side}" not in card  # 模板键不得漏翻译直出
        assert f"{conf * 100:.1f}%" in card, f"{bean_id} 缺置信度 {conf}"


def test_evidence_card_coords_and_sides(passport):
    """判定面坐标与逐面素材与输入记录一致；好豆不立卡。

    layout 几何：cx = 10 + (idx % 4) * 22 (+1.1 bottom)，cy = 20 + (idx % 3) * 24 (+1.3 bottom)。
    b0001 top → (32.0, 44.0)；b0002 bottom → (55.1, 69.3)。
    """
    for lang in LANGS:
        html = _read(passport.html_paths[lang])
        card1 = _card(html, "b0001")
        assert "32.00, 44.00 mm" in card1
        card2 = _card(html, "b0002")
        assert "55.10, 69.30 mm" in card2
        # 好豆不出现在任何卡片
        assert 'data-bean-id="b0006"' not in html
        assert 'data-bean-id="b0012"' not in html


def test_evidence_cards_all_have_images_and_placeholders(tmp_path: Path, synth: BatchResult, passport):
    """每张证据卡必有图（缺裁剪图 → 占位图 + 占位标记）；有裁剪图则真实内嵌。"""
    for lang in LANGS:
        ui = STRINGS[lang]
        html = _read(passport.html_paths[lang])
        for bean_id in DEFECTIVE_IDS:
            card = _card(html, bean_id)
            imgs = re.findall(r'src="data:image/png;base64,([A-Za-z0-9+/=]+)"', card)
            assert imgs, f"{lang}/{bean_id} 证据卡无图"
        # b0002: top 缺图（占位标记 1 处）、bottom 真图
        card2 = _card(html, "b0002")
        assert card2.count(ui["evidence.img.placeholder"]) == 1
        # b0004: 裁剪图在盘 → 无占位标记
        card4 = _card(html, "b0004")
        assert ui["evidence.img.placeholder"] not in card4
    # 占位图像素内容确含豆号与坐标（ evidence.placeholder_png 契约）
    from beaneye.report.evidence import placeholder_png

    raw = placeholder_png("b0003", "sour", (54.0, 68.0), side="bottom")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape[0] == 120
    again = placeholder_png("b0003", "sour", (54.0, 68.0), side="bottom")
    assert again == raw  # 确定性


def test_passport_with_zero_defects_has_no_cards(tmp_path: Path):
    base = synth_result(tmp_path, with_agent=False, crop_plan={})

    def to_normal(obs: BeanObservation | None) -> BeanObservation | None:
        if obs is None:
            return None
        return BeanObservation(
            obs_id=obs.obs_id,
            side=obs.side,
            defect="normal",
            defect_conf=0.99,
            severity_rank=0,
            crop_path=obs.crop_path,
            mask=obs.mask,
            color_lab=(132.6, 118.0, 148.0),  # lab8 标度（契约单一标度，W13）
            eq_diameter_mm=obs.eq_diameter_mm,
        )

    beans = []
    for b in base.beans:
        top, bottom = to_normal(b.top), to_normal(b.bottom)
        beans.append(
            PairedBean.from_sides(
                b.bean_id, top, bottom, pairing_cost=1.5 if (top and bottom) else -1.0
            )
        )
    result = BatchResult(
        result_id=base.result_id,
        sample_id=base.sample_id,
        scan_ids=base.scan_ids,
        beans=beans,
        measurements=base.measurements,
        grading=GradingDecision(
            standard_id="cqi_fine_robusta",
            grade="Fine",
            passed=True,
            primary_count=0,
            secondary_count=0,
            defect_counts={"normal": 12},
            reasons=["grading.reason.primary_within_limit"],
            standard_yaml_sha=STANDARD_SHA,
        ),
        agent_report=None,
        timings_s={},
        pipeline_versions={},
    )
    pp = build_passport(result, tmp_path / "rep0", crop_root=tmp_path, langs=("zh",))
    html = _read(pp.html_paths["zh"])
    assert re.findall(r'data-bean-id="([^"]+)"', html) == []
    assert STRINGS["zh"]["evidence.none"] in html


# ---------------------------------------------------------------------------
# 4e. 角标 / 溯因段 / 语言校验
# ---------------------------------------------------------------------------

def test_standard_verified_badge(tmp_path: Path, synth: BatchResult):
    unverified = build_passport(synth, tmp_path / "b0", crop_root=tmp_path, langs=("zh",), standard_verified=False)
    verified = build_passport(synth, tmp_path / "b1", crop_root=tmp_path, langs=("zh",), standard_verified=True)
    silent = build_passport(synth, tmp_path / "b2", crop_root=tmp_path, langs=("zh",), standard_verified=None)
    assert STRINGS["zh"]["footer.standard_unverified"] in _read(unverified.html_paths["zh"])
    assert STRINGS["zh"]["footer.standard_verified"] in _read(verified.html_paths["zh"])
    html_silent = _read(silent.html_paths["zh"])
    assert STRINGS["zh"]["footer.standard_unverified"] not in html_silent
    assert STRINGS["zh"]["footer.standard_verified"] not in html_silent


def test_agent_section_both_states(tmp_path: Path, synth: BatchResult, passport):
    zh = _read(passport.html_paths["zh"])
    assert STRINGS["zh"]["agent.none"] not in zh
    assert "干燥" in zh and "降低干燥温度并摊薄铺晒" in zh
    en = _read(passport.html_paths["en"])
    assert STRINGS["en"]["stage.干燥"] in en  # 环节名已译英文
    # 无溯因报告 → 提示文案
    no_agent = BatchResult(
        result_id=synth.result_id,
        sample_id=synth.sample_id,
        scan_ids=synth.scan_ids,
        beans=synth.beans,
        measurements=synth.measurements,
        grading=synth.grading,
        agent_report=None,
        timings_s=synth.timings_s,
        pipeline_versions=synth.pipeline_versions,
    )
    pp = build_passport(no_agent, tmp_path / "na", crop_root=tmp_path, langs=("zh",))
    assert STRINGS["zh"]["agent.none"] in _read(pp.html_paths["zh"])


def test_unknown_lang_rejected(tmp_path: Path, synth: BatchResult):
    with pytest.raises(ReportError):
        build_passport(synth, tmp_path / "x", langs=("jp",))


# ---------------------------------------------------------------------------
# 4f. 时限（≤5s/份）
# ---------------------------------------------------------------------------

def test_generation_time_under_5s_per_file(tmp_path: Path, synth: BatchResult):
    t0 = time.perf_counter()
    pp = build_passport(synth, tmp_path / "t", crop_root=tmp_path, langs=("zh",))
    elapsed = time.perf_counter() - t0
    assert Path(pp.html_paths["zh"]).is_file()
    assert elapsed < 5.0, f"单份生成 {elapsed:.2f}s 超 5s 时限"


# ---------------------------------------------------------------------------
# 5. 目数直方图
# ---------------------------------------------------------------------------

def test_sieve_histogram_png_font_and_lang(synth: BatchResult):
    from beaneye.report.charts import CJK_FONT_CANDIDATES, resolve_cjk_font

    png, meta = sieve_histogram_png(synth.measurements, lang="zh")
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 5_000
    assert meta["lang_used"] == "zh"
    if resolve_cjk_font() is not None:
        assert meta["font"] in CJK_FONT_CANDIDATES
    # 越南语：文案仍为越南语，但字体链首选必须覆盖越南语声调（DejaVu Sans）
    _, meta_vi = sieve_histogram_png(synth.measurements, lang="vi")
    assert meta_vi["lang_used"] == "vi"
    assert meta_vi["font"] == "DejaVu Sans"
