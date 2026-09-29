"""M8 验收（T14 自验收口径：M6 mock 候选刻意超长 → 逐句落原句窗 ±10%，全离线零 GPU）。

对齐链条（对应任务 T14 四级阶梯 + keep-original）：
  syl2dur 估算占位（消费 C4 ``est_dur``）→ 二分 ``duration_factor`` [0.5,2.0]
  → 仍超长换下一候选译文（消费 M6 mock 的 3–5 候选）→ ``atempo`` [0.9,1.1]
  收口 → nonverbal/缺译文 ``keep_original`` 兜底；出口 C5（每句引擎/参考/
  duration_factor/atempo）。

语料口径（与 test_m6 同源 mock 后端 + 术语注入）：**故意超长译法**——C2
句窗按 mock 候选项估长的固定比例压窗构造（in-budget 1.00 / df 0.62 /
switch 0.52 / atempo 0.43），使五类路径全部真实触发，并用独立复算
（syl 计数回 syl2dur 占位口径）逐句核验「预测落盘时长 ∈ 原句窗 ±10%」。

口径注记（如实区分）：
  - 本文件核心断言 = T14 自验收：逐句对齐 + CLI exit 0（100% 落窗）；
  - 规划 §4 M8 的另两条冻结线（平均语速调整幅度 ≤1.06 / atempo 占比
    ≤30%）中，占比在本语料可复算断言（2/9≈0.222）；平均语速调整幅度在
    「刻意超长」语料上必然显著高于 1.06（0.62/0.52/0.43 压窗即 1.6–2.2
    倍调整），该线针对真实 M6 输出质量语料（mock 命中率基线另见
    test_m6 口径注记），故本文件只断言该指标被如实计算与回传、不设阈值；
  - mock 语料送 M6 前即固定估长比例（系数与 mock 全量变体估长相乘得到
    句窗），对齐的全部输入（C2/C4/C3）均为确定性产物，重跑恒同。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.m6_translate import (
    count_syllables,
    estimate_dur_s,
    translate_episode,
)
from pipeline.m8_align import (
    AlignParams,
    align_episode,
    atempo_close,
    bisect_duration_factor,
    estimate_base_dur,
    main,
    params_from_cfg,
    predict_dur,
)
from pipeline.mt_backends import MTContext, MockMtBackend
from pipeline.scaffold import create_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
EP = "ep01"

#: 演示语料：(文本, 说话人, 目标阶梯)。switch/atempo 阶梯句的候选估长比例
#: 经 mock 实测标定（见 tests 一次性探针输出），窗 = 比例 × 基准候选项估长。
CORPUS: list[tuple[str, str, str]] = [
    ("那你就可以这样对我吗！", "spk0", "in-budget"),          # 候选直接落窗
    ("我以为你至少会信我。", "spk1", "in-budget"),            # 挂情绪参考 wav
    ("程总，预算超了。", "spk1", "in-budget"),
    ("三年了，程氏的项目、老城的基地，哪一样不是我亲手做起来的？", "spk0", "df-bisect"),
    ("总裁，你到底想怎么样？", "spk0", "df-bisect"),          # 别名术语句
    ("你到底想怎么样？把话说清楚。", "spk1", "switch-df"),    # 长子句 → 换译
    ("为什么，为什么要走？", "spk0", "switch-df"),
    ("海南孤岛，也有明月。", "spk1", "atempo-final"),        # 全候选二分失败 → atempo
    ("东坡为什么要走？", "spk1", "atempo-final"),            # 种子术语句
]
NONVERBAL_LINE = ("（哽咽）我以为你至少会信我。", "spk1")  # keep-original（冻结规则 4）

#: 情绪标签句（score 0.8 → emo_alpha = 0.5 + 0.35×0.8 = 0.78）
_EMO_LINE = "那你就可以这样对我吗！"
#: 情绪参考 wav 落点句（04_dial/emo_refs/<utt_id>.wav）
_EMO_REF_LINE = "我以为你至少会信我。"

_CAST = {
    "char_spk0": {
        "name": "程总",
        "aliases": ["总裁"],
        "gender": "m",
        "voice_ref": "05_cast/voicebank/char_spk0_ref.wav",
        "ref_dur_s": 12.0,
        "desc": "男主，世家出身，语气克制但压迫感强",
        "terms": {"en": "Master Cheng", "es": "Sr. Cheng", "ar": "السيد تشنغ"},
    },
}
_SEED = {"东坡": {"en": "Dongpo", "es": "Dongpo", "ar": "دونغبو"}}

#: 阶梯 → (基准候选项, 窗系数)：est0=最长候选估长；min=最短候选估长
WINDOW_RULE: dict[str, tuple[str, float]] = {
    "in-budget": ("est0", 1.00),
    "df-bisect": ("est0", 0.62),
    "switch-df": ("min", 0.52),
    "atempo-final": ("min", 0.43),
}
#: 语料阶梯 → 期望的 align_report status（换译以 switched/cand_idx 区分，
#: 不单列 status —— 阶梯路径名与决策状态名解耦）
TIER_STATUS: dict[str, str] = {
    "in-budget": "in-budget",
    "df-bisect": "df-bisect",
    "switch-df": "df-bisect",
    "atempo-final": "atempo-final",
}
_GAP_S = 0.6


def _glossary() -> dict[str, str]:
    cast = {k: C.Character(**v) for k, v in _CAST.items()}
    from pipeline.m6_translate import build_glossary
    return build_glossary(cast, _SEED, "en")


def _mock_ests(text: str, glossary: dict[str, str]) -> list[float]:
    """对源文本跑 mock 后端取候选估长（syl2dur 占位口径；确定性）。"""
    drafts = MockMtBackend().translate(
        text, MTContext(tgt_lang="en", terms=glossary), n_candidates=5
    )
    return [estimate_dur_s(count_syllables(d.text, "en"), "en") for d in drafts]


def _window_for(tier: str, ests: list[float], tight: float | None) -> float:
    """句窗 = 比例 × 基准候选项估长（tight 非空时全部按 est0×tight 压窗）。

    未登记阶梯（如 nonverbal 的 keep 路径）回落 est0×1.00（原句窗即估长窗）。
    """
    if tight is not None:
        return round(ests[0] * tight, 3)
    base_kind, factor = WINDOW_RULE.get(tier, ("est0", 1.0))
    base = ests[0] if base_kind == "est0" else min(ests)
    return round(base * factor, 3)


def _build_workspace(
    jobs_root: Path,
    *,
    tight: float | None = None,
    with_translation: bool = True,
) -> list[C.Utterance]:
    """建 ep 工作区 + C2 事实表（句窗按 mock 估长压窗构造）+ C4（M6 mock 实跑）。"""
    create_workspace(EP, jobs_root)
    glossary = _glossary()
    utts: list[C.Utterance] = []
    t = 0.0
    for text, speaker, tier in CORPUS:
        w = _window_for(tier, _mock_ests(text, glossary), tight)
        utts.append(
            C.Utterance(
                utt_id=C.make_utt_id(EP, t),
                shot_id="s0000",
                start=round(t, 3),
                end=round(t + w, 3),
                lang="zh",
                speaker=speaker,
                text=text,
                emo=C.EmoTag(label="angry", score=0.8) if text == _EMO_LINE else None,
            )
        )
        t = round(t + w + _GAP_S, 3)
    # nonverbal 句（C5 冻结规则 4 路径）
    w = _window_for("keep", _mock_ests(NONVERBAL_LINE[0], glossary), tight)
    utts.append(
        C.Utterance(
            utt_id=C.make_utt_id(EP, t),
            shot_id="s0000",
            start=round(t, 3),
            end=round(t + w, 3),
            lang="zh",
            speaker=NONVERBAL_LINE[1],
            text=NONVERBAL_LINE[0],
            nonverbal=True,
        )
    )

    dial = jobs_root / EP / "04_dial"
    C.dump_jsonl(dial / "utterances.jsonl", C.UtteranceTable.model_validate(utts))

    # 情绪参考 wav（真实可解码音频；M8 只登记路径，不做时长校验）
    emo_utt = next(u for u in utts if u.text == _EMO_REF_LINE)
    ref_dir = dial / "emo_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    sig = (0.3 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)).astype("float32")
    sf.write(ref_dir / f"{emo_utt.utt_id}.wav", sig, 16000)

    cast_path = jobs_root / EP / "05_cast" / "characters.json"
    cast_path.write_text(
        json.dumps(_CAST, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (jobs_root / EP / "06_mt").mkdir(parents=True, exist_ok=True)
    (jobs_root / EP / "06_mt" / "terms_seed.json").write_text(
        json.dumps(_SEED, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    if with_translation:
        translate_episode(
            EP, "en", MockMtBackend(), jobs_dir=jobs_root,
            seed_path=jobs_root / EP / "06_mt" / "terms_seed.json",
        )
    return utts


@pytest.fixture()
def workspace(tmp_path: Path) -> tuple[Path, list[C.Utterance]]:
    jobs_root = tmp_path / "jobs"
    return jobs_root, _build_workspace(jobs_root)


def _plan_path(jobs_root: Path, lang: str = "en") -> Path:
    return jobs_root / EP / "07_synth" / f"synth_plan.{lang}.jsonl"


def _run_align(jobs_root: Path, lang: str = "en") -> dict:
    return align_episode(EP, lang, jobs_dir=jobs_root)


def _translation_row(jobs_root: Path, utt_id: str, lang: str = "en") -> C.Translation:
    rows = C.load_jsonl(
        jobs_root / EP / "06_mt" / "translations.jsonl", C.TranslationTable
    ).root
    return next(r for r in rows if r.utt_id == utt_id and r.tgt == lang)


# ---------------------------------------------------------------------------
# 纯函数：占位预测 / 二分 / atempo 收口 / 配置
# ---------------------------------------------------------------------------

def test_predict_and_estimate_primitives():
    # 占位预测：base × duration_factor / atempo，3 位小数（冻结规则 1）
    assert predict_dur(6.5, 0.62, 1.0) == 4.03
    assert predict_dur(2.0, 0.5, 1.1) == 0.909
    assert predict_dur(1.0, 1.0, 1.0) == 1.0
    # 估长兜底：est_dur=0 而 syl>0 → 按占位规则补算（syl2dur 拟合延后钩子）
    c = C.Candidate(text="what do you want", syl=8, est_dur=0.0, src="mock", q=0.9)
    assert estimate_base_dur(c, lang="en") == estimate_dur_s(8, "en") == 2.0
    c2 = C.Candidate(text="x", syl=0, est_dur=0.0, src="mock", q=0.9)
    assert estimate_base_dur(c2, lang="en") == 0.0


def test_bisect_duration_factor():
    p = AlignParams()
    # 过长：base=6.5，窗 [3.627, 4.433]（df-bisect 阶梯句口径）→ f≈0.62 落窗
    f = bisect_duration_factor(6.5, 4.03, 3.627, 4.433, p)
    assert f is not None
    assert abs(6.5 * f - 4.03) <= 6.5 * 1.5 / 2 ** p.bisect_rounds + 0.001
    assert 0.5 <= f <= 2.0
    # 过短：base=0.5，窗 [0.9, 1.1] → 二分逼近最慢档 f=2.0（边界目标），落窗
    f_short = bisect_duration_factor(0.5, 1.0, 0.9, 1.1, p)
    assert f_short is not None and 1.99 <= f_short <= 2.0
    assert 0.9 <= 0.5 * f_short <= 1.1
    # 不可行：最快仍超长 / 最慢仍过短 → None（进入换译/atempo）
    assert bisect_duration_factor(10.0, 1.0, 0.9, 1.1, p) is None
    assert bisect_duration_factor(0.3, 1.0, 0.9, 1.1, p) is None
    assert bisect_duration_factor(0.42, 1.0, 0.9, 1.1, p) is None  # 0.42×2=0.84 < lo


def test_atempo_close():
    p = AlignParams()
    # 过长收口（'海南孤岛，也有明月。' 阶梯口径）：d=2.0×0.5=1.0 → atempo=1.1 落窗
    a = atempo_close(2.0, 0.86, 0.774, 0.946, p)
    assert a == 1.1 and 0.774 <= 1.0 / a <= 0.946
    # 过短收口：d=0.42×2.0=0.84 < lo=0.9 → atempo=0.9 落窗
    a_short = atempo_close(0.42, 1.0, 0.9, 1.1, p)
    assert a_short == 0.9 and 0.9 <= 0.84 / a_short <= 1.1
    # 无解：残差远超微调窗 → None（unresolved best-effort 路径）
    assert atempo_close(10.0, 1.0, 0.9, 1.1, p) is None
    # 本可落窗却调用（df 尚未尝试）→ 如实不解，防止误用
    assert atempo_close(2.0, 2.0, 1.9, 2.1, p) is None


def test_params_from_repo_config():
    p = params_from_cfg(load_pipeline_config())
    assert (p.df_lo, p.df_hi) == (0.5, 2.0)          # C5 契约域
    assert (p.atempo_lo, p.atempo_hi) == (0.9, 1.1)  # T14 微调窗
    assert p.bisect_rounds == 10 and p.engine == "dub-tts"


# ---------------------------------------------------------------------------
# 自验收核心：逐句落原句窗 ±10%（五类阶梯路径全覆盖）
# ---------------------------------------------------------------------------

def test_align_episode_every_sentence_in_window(workspace: tuple[Path, list[C.Utterance]]):
    jobs_root, utts = workspace
    summary = _run_align(jobs_root, "en")

    plan = C.load_jsonl(_plan_path(jobs_root), C.SynthPlanTable)
    by_utt = {i.utt_id: i for i in plan.root}
    assert set(by_utt) == {u.utt_id for u in utts}
    report = json.loads(
        (jobs_root / EP / "07_synth" / "align_report.en.json").read_text("utf-8")
    )
    rep_by_utt = {r["utt_id"]: r for r in report["items"]}
    tier_of = {text: tier for text, _, tier in CORPUS}

    # —— 汇总：零未解 + 100% 对齐（T14 自验收主断言）——
    assert summary["n_unresolved"] == 0
    assert summary["alignment_rate"] == 1.0
    assert summary["alignment_rate"] >= 0.70  # 规划 §4 M8 通过线（时长可控翻译未训练前）

    n_in_budget = n_df = n_switch = n_atempo = n_keep = 0
    speeds: list[float] = []
    for u in utts:
        item = by_utt[u.utt_id]
        rep = rep_by_utt[u.utt_id]
        row = _translation_row(jobs_root, u.utt_id)
        lo, hi = row.budget.lo, row.budget.hi

        # ① 独立复算（回到 syl2dur 占位口径，不信 C5 expect_dur 自述）
        if not item.keep_original:
            base = estimate_dur_s(count_syllables(item.text, "en"), "en")
            pred = round(base * item.duration_factor / item.atempo, 3)
            assert abs(pred - item.expect_dur) <= 0.002
            # 采用文本确为 C4 候选之一（消费 M6 候选，非自造）
            assert item.text in {c.text for c in row.candidates}
            speeds.append(max(item.atempo / item.duration_factor,
                              item.duration_factor / item.atempo))
        else:
            assert item.text == u.text  # keep-original 携带原句文本
            assert item.expect_dur == row.budget.orig_dur
        # ② 自验收核心：逐句预测时长 ∈ 原句窗 ±10%
        assert lo <= item.expect_dur <= hi
        # ③ C5 字段口径：引擎/参考/旋钮范围/产物槽位
        assert item.engine == "dub-tts"
        assert 0.5 <= item.duration_factor <= 2.0
        assert 0.9 <= item.atempo <= 1.1
        assert item.out == f"07_synth/wavs/{u.utt_id}.wav"
        assert item.voice_ref in {
            "05_cast/voicebank/char_spk0_ref.wav",   # C3 角色卡音色参考
            "05_cast/voicebank/char_spk1_ref.wav",   # M6 暂定卡槽位（spk1 无 C3 卡）
        }
        # 情绪参考：仅落了 wav 的句子携带；其余如实留空
        if u.text == _EMO_REF_LINE:
            assert item.emo_ref == f"04_dial/emo_refs/{u.utt_id}.wav"
        else:
            assert item.emo_ref is None
        # emo_alpha 映射（score 0.8 → 0.78；无情绪 → 0.7）
        assert item.emo_alpha == (0.78 if u.text == _EMO_LINE else 0.7)

        # ④ 阶梯状态与语料目标一一对应
        if u.text in tier_of:
            tier = tier_of[u.text]
            assert rep["status"] == TIER_STATUS[tier], u.text
            if tier == "in-budget":
                n_in_budget += 1
                assert item.duration_factor == 1.0 and item.atempo == 1.0
                assert rep["cand_idx"] == 0 and rep["switched"] is False
            elif tier == "df-bisect":
                n_df += 1
                assert item.duration_factor < 1.0 and item.atempo == 1.0
                assert rep["cand_idx"] == 0 and rep["switched"] is False
            elif tier == "switch-df":
                n_df += 1
                n_switch += 1
                assert rep["cand_idx"] == 1 and rep["switched"] is True
                assert item.duration_factor < 1.0 and item.atempo == 1.0
            else:  # atempo-final
                n_atempo += 1
                assert item.atempo > 1.0
        else:  # nonverbal
            assert rep["status"] == "keep-original" and item.keep_original is True
            assert item.duration_factor == 1.0 and item.atempo == 1.0
            n_keep += 1

    # ⑤ 汇总指标与逐句复算一致（含如实上报的 atempo 占比 / 平均语速调整幅度）
    # n_df 含换译后二分（status 统一 df-bisect，switched 标志区分是否换译）
    assert (n_in_budget, n_df, n_switch, n_atempo, n_keep) == (3, 4, 2, 2, 1)
    n_synth = len(CORPUS)
    assert summary["n_synth"] == n_synth
    assert summary["n_df"] == 4 and summary["n_switch"] == 4
    # n_switch=4：switch-df 两例 + atempo-final 两例均落到 1 号候选（换译事实）
    assert summary["atempo_ratio"] == round(n_atempo / n_synth, 3) == 0.222
    assert summary["atempo_ratio"] <= 0.30  # 规划 §4 M8 atempo 占比冻结线
    assert summary["mean_speed_adj"] == round(sum(speeds) / len(speeds), 3)
    # 报告汇总与返回摘要同源一致
    assert report["summary"]["alignment_rate"] == 1.0
    assert report["summary"]["n_unresolved"] == 0
    assert report["summary"]["unresolved"] == []
    assert report["policy"]["df_range"] == [0.5, 2.0]
    assert report["policy"]["atempo_window"] == [0.9, 1.1]

    # M8 只读 C4：翻译文件未被改写（行数不变、可强校验）
    rows = C.load_jsonl(
        jobs_root / EP / "06_mt" / "translations.jsonl", C.TranslationTable
    ).root
    assert {r.utt_id for r in rows} == {u.utt_id for u in utts}


# ---------------------------------------------------------------------------
# CLI / 契约校验 / 多语种分文件 / 幂等
# ---------------------------------------------------------------------------

def test_cli_exit0_and_contract_validate(workspace: tuple[Path, list[C.Utterance]]):
    jobs_root, utts = workspace
    env = {**os.environ, "PYTHONUTF8": "1"}
    rc = subprocess.run(
        [sys.executable, "-m", "pipeline.m8_align", "--ep", EP,
         "--lang", "en", "--jobs-dir", str(jobs_root)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert rc.returncode == 0, rc.stdout + rc.stderr
    assert "OK m8_align" in rc.stdout and "aligned=1.000" in rc.stdout
    assert "unresolved=0" in rc.stdout

    rc2 = subprocess.run(
        [sys.executable, "-m", "pipeline.cli", "validate", "synth-plan",
         str(_plan_path(jobs_root))],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert rc2.returncode == 0 and "OK C5" in rc2.stdout, rc2.stdout + rc2.stderr

    # 幂等：同语种重跑按 utt_id 替换，行数不翻倍
    _run_align(jobs_root, "en")
    rows = C.load_jsonl(_plan_path(jobs_root), C.SynthPlanTable).root
    assert len(rows) == len(utts)


def test_multilang_files_and_current_lang_copy(workspace: tuple[Path, list[C.Utterance]]):
    jobs_root, utts = workspace
    _run_align(jobs_root, "en")
    # es 字幕链路：先补跑 M6 es 翻译（C4 复合键），再对齐 es
    translate_episode(
        EP, "es", MockMtBackend(), jobs_dir=jobs_root,
        seed_path=jobs_root / EP / "06_mt" / "terms_seed.json",
    )
    _run_align(jobs_root, "es")  # es 句窗为 en 估长构造：本测试只验文件分治，不断言落窗

    en_rows = C.load_jsonl(_plan_path(jobs_root, "en"), C.SynthPlanTable).root
    es_rows = C.load_jsonl(_plan_path(jobs_root, "es"), C.SynthPlanTable).root
    assert len(en_rows) == len(utts) == len(es_rows)
    # 各语种文件互不覆盖（C5 utt_id 单键，多语种同文件会互踩 → 分文件是硬要求）
    assert {i.utt_id for i in en_rows} == {i.utt_id for i in es_rows}
    assert any("Master Cheng" in i.text for i in en_rows)
    assert any("Sr. Cheng" in i.text for i in es_rows)
    # 无后缀副本 = 最近一次运行的语种（es）
    copy_rows = C.load_jsonl(
        jobs_root / EP / "07_synth" / "synth_plan.jsonl", C.SynthPlanTable
    ).root
    assert [i.text for i in copy_rows] == [i.text for i in es_rows]


# ---------------------------------------------------------------------------
# 兜底与 gate：缺译文 keep-original / unresolved best-effort / CLI 通过线
# ---------------------------------------------------------------------------

def test_no_translation_keeps_original(tmp_path: Path):
    jobs_root = tmp_path / "jobs"
    utts = _build_workspace(jobs_root, with_translation=False)
    summary = _run_align(jobs_root, "en")

    # 缺译文句 keep-original；nonverbal 句走冻结规则 4 的 keep-original（同名不同由）
    assert summary["n_no_translation"] == len(utts) - 1
    assert summary["n_keep_original"] == 1
    assert summary["n_no_translation"] + summary["n_keep_original"] == len(utts)
    assert summary["n_synth"] == 0
    assert summary["atempo_ratio"] == 0.0 and summary["mean_speed_adj"] == 0.0
    assert summary["alignment_rate"] == 1.0  # 原声时长即原句窗（±10% 内）
    plan = C.load_jsonl(_plan_path(jobs_root), C.SynthPlanTable).root
    for u, item in zip(utts, plan):
        assert item.keep_original is True
        assert item.text == u.text
        assert item.duration_factor == 1.0 and item.atempo == 1.0
        assert item.expect_dur == round(u.end - u.start, 3)


def test_nonverbal_keeps_original_with_translation(workspace: tuple[Path, list[C.Utterance]]):
    """冻结规则 4：nonverbal 句即使有 C4 候选也 keep_original（哭腔不合成）。"""
    jobs_root, utts = workspace
    _run_align(jobs_root, "en")
    nv = next(u for u in utts if u.nonverbal)
    row = _translation_row(jobs_root, nv.utt_id)
    assert row.candidates  # M6 确实给了候选 —— 证明是 M8 冻结规则在起作用
    item = next(i for i in C.load_jsonl(_plan_path(jobs_root), C.SynthPlanTable).root
                if i.utt_id == nv.utt_id)
    assert item.keep_original is True and item.text == nv.text
    assert item.expect_dur == row.budget.orig_dur


def test_unresolved_best_effort_and_cli_gate(tmp_path: Path):
    """极端压窗：全候选二分失败且 atempo 不可解 → unresolved best-effort + CLI exit 1。"""
    jobs_root = tmp_path / "jobs"
    utts = _build_workspace(jobs_root, tight=0.12)  # 候选估长 8× 于句窗
    _run_align(jobs_root, "en")

    report = json.loads(
        (jobs_root / EP / "07_synth" / "align_report.en.json").read_text("utf-8")
    )
    assert report["summary"]["n_unresolved"] > 0
    assert report["summary"]["alignment_rate"] < 1.0
    # best-effort：旋钮仍落在 C5 契约域内（不是越界脏值），文本仍是 C4 候选
    plan = C.load_jsonl(_plan_path(jobs_root), C.SynthPlanTable).root
    by_utt = {i.utt_id: i for i in plan}
    for rep in report["items"]:
        if rep["status"] == "unresolved":
            item = by_utt[rep["utt_id"]]
            assert 0.5 <= item.duration_factor <= 2.0
            assert 0.9 <= item.atempo <= 1.1
            assert not item.keep_original
            row = _translation_row(jobs_root, rep["utt_id"])
            assert item.text in {c.text for c in row.candidates}

    rc = main(["--ep", EP, "--lang", "en", "--jobs-dir", str(jobs_root),
               "--min-align-rate", "1.0"])
    assert rc == 1  # 对齐率低于通过线 → exit 1（如实失败，不粉饰）
    rc2 = main(["--ep", EP, "--lang", "en", "--jobs-dir", str(jobs_root),
                "--min-align-rate", "0.0"])
    assert rc2 == 0  # 通过线置零时可放行（未解句在报告中单列）
