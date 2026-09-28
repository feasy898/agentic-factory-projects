"""M6 整集上下文翻译 + 时长预算（规划 §4 M6；GPU :9004 主 / API 兜底 / mock 离线）。

职责（本模块只读写 ``06_mt/``，并按 spec ① 校订 ``05_cast/characters.json``）：
  ① 通读全部 C2（``04_dial/utterances.jsonl``）→ 生成/校订角色卡（关系、称谓、
     专有名词、术语表 terms）→ ``06_mt/context.json``（非冻结契约的工作纸，
     schema 见 :func:`build_context`）+ C3 ``characters.json`` 增量合并
     （只新增未见过的 char_id，绝不覆盖既有卡 —— C3「每部剧人工确认一次」）；
  ② 逐句翻译：输入 = 全剧角色卡 + 术语表 + 前/后 ≤2 句 + 本句时长预算
     （预算读 C2 时间戳：``orig=end-start``，窗比取 configs/pipeline.yaml
     ``budget.lo_ratio/hi_ratio``），输出 3–5 个长短候选；
  ③ 音素化估长（占位实现）：音节计数规则 + ``models/syl2dur.json`` 拟合表
     （training-plan §1.3，拟合回归后回填；缺表用 :data:`DEFAULT_SYL_RATE`
     占位常量）→ 每候选 ``est_dur``；
  ④ in-budget 候选排序（policy=``in-budget-first``：预算内优先，再按 q，
     再按 |est-orig|）；无预算内候选时 chosen 仍取排序首位，M8 以
     「无候选落窗」判定进入换译流程。

出口：C4 ``06_mt/translations.jsonl``（契约强校验 + 原子整文件写；
键 = (utt_id, tgt)，重跑同语种按 id 替换、不碰其他语种行）。

CLI：
    python -m pipeline.m6_translate --ep ep01 --lang en [--backend local|api|mock]
退出码：0 成功；1 输入/后端/契约校验错误；2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.mt_backends import (
    MTBackend,
    MTContext,
    MtBackendError,
    MTDraft,
    make_backend,
)
from pipeline.scaffold import ep_dir

__all__ = [
    "DEFAULT_SYL_RATE",
    "count_syllables",
    "estimate_dur_s",
    "budget_for",
    "build_context",
    "translate_episode",
    "main",
]

#: 音节速率占位表（音节/秒）—— 待 models/syl2dur.json 拟合回填
#: （training-plan §1.3：dub 引擎实际合成 ~2000 句回归「音节数+情绪+语速→时长」；
#: 本表为无表时的保守占位，只保证量级正确，非最终口径）。
DEFAULT_SYL_RATE: dict[str, float] = {"zh": 4.2, "en": 4.0, "es": 4.4, "ar": 3.6}

#: 前后文句数（规划 §4 M6 ②：前后 2 句）
CTX_WINDOW = 2

_HAN_CHAR = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_EN_VOWEL_GROUP = re.compile(r"[aeiouy]+")
_ES_VOWEL = re.compile(r"[aeiouáéíóúü]", re.IGNORECASE)
_AR_VOWEL = re.compile(r"[اوية]")
_AR_DIACRITIC = re.compile(r"[\u064b-\u0652\u0670]")


# ---------------------------------------------------------------------------
# ③ 音素化估长（占位实现；拟合表回填后替换核心逻辑，接口不变）
# ---------------------------------------------------------------------------

def count_syllables(text: str, lang: str) -> int:
    """规则音节计数（占位 G2P：pypinyin/词典 G2P/阿语简化法待拟合批替换）。

    - zh/yue/ja：CJK 字数（每字 ≈1 音节；假名同口径）；
    - en：每词元音簇数（[aeiouy]+ 连串，词内至少 1）；
    - es：元音数（西语音节核即元音，规则天然贴合）；
    - ar：去叠符后长元音/软音计数（简化音节法，training-plan §1.3 口径）。
    """
    if not text.strip():
        return 0
    lang = (lang or "en").split("-")[0].lower()
    if lang in {"zh", "yue", "ja"}:
        return len(_HAN_CHAR.findall(text))
    total = 0
    for word in re.findall(r"[\w\u0600-\u06ff]+", text, re.UNICODE):
        if lang == "ar":
            n = len(_AR_VOWEL.findall(_AR_DIACRITIC.sub("", word)))
        elif lang == "es":
            n = len(_ES_VOWEL.findall(word))
        else:  # en 及其他拉丁语种默认走 en 规则
            n = len(_EN_VOWEL_GROUP.findall(word.lower()))
        total += max(1, n) if re.search(r"[a-z\u0600-\u06ff]", word, re.IGNORECASE) else len(word)
    return total


def load_syl_table(path: Optional[Path]) -> dict[str, float]:
    """读 ``models/syl2dur.json`` 拟合表（{"en": {"syl_rate": 4.1}} 或 {"en": 4.1}）。

    文件缺失/格式不符返回 {}（调用方回退 :data:`DEFAULT_SYL_RATE`；不抛异常 ——
    拟合表是增强项，缺失不应阻塞翻译主链路）。
    """
    if not path or not Path(path).is_file():
        return {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    rates: dict[str, float] = {}
    if isinstance(raw, dict):
        for lang, val in raw.items():
            if isinstance(val, dict):
                val = val.get("syl_rate")
            if isinstance(val, (int, float)) and val > 0:
                rates[str(lang).lower()] = float(val)
    return rates


def estimate_dur_s(syl: int, lang: str, rates: Optional[dict[str, float]] = None) -> float:
    """音节数 → 估算秒数：``syl / syl_rate(lang)``，保留 3 位（冻结规则 1）。

    拟合表 rates 优先，缺语种回退 :data:`DEFAULT_SYL_RATE`，仍缺用 4.0 兜底。
    """
    lang = (lang or "en").split("-")[0].lower()
    rate = (rates or {}).get(lang) or DEFAULT_SYL_RATE.get(lang) or 4.0
    return round(max(0, int(syl)) / rate, 3)


# ---------------------------------------------------------------------------
# ② 时长预算（读 C2 时间戳）
# ---------------------------------------------------------------------------

def budget_for(u: C.Utterance, lo_ratio: float, hi_ratio: float) -> C.Budget:
    """C2 句窗 → C4 预算（orig=end-start；lo/hi 按窗比缩放，3 位小数）。"""
    orig = round(u.end - u.start, 3)
    return C.Budget(orig_dur=orig, lo=round(orig * lo_ratio, 3), hi=round(orig * hi_ratio, 3))


# ---------------------------------------------------------------------------
# ① 整集角色卡（生成/校订）
# ---------------------------------------------------------------------------

def char_id_for(u: C.Utterance) -> str:
    """C2 行 → char_id：优先 M5 回填的 ``char_id``；否则按 speaker 派生；
    两者皆缺归 ``char_unknown``（B1 阶段 M5 未跑的合法形态）。"""
    if u.char_id:
        return u.char_id
    if u.speaker:
        return f"char_{u.speaker}" if not u.speaker.startswith("char_") else u.speaker
    return "char_unknown"


def draft_cast_from_utterances(
    utterances: list[C.Utterance], existing: dict[str, C.Character]
) -> tuple[dict[str, C.Character], dict[str, Any]]:
    """从 C2 生成新说话人的**暂定角色卡**（只增不覆盖；C3 权威仍归人工/M5）。

    返回 (合并后 char_id→Character, context.json 的 cast 摘要 dict)。
    暂定卡字段：name=char_id、desc 标注来源与句数、voice_ref 指向
    voicebank 槽位（文件由 M5/人工后续放入）、ref_dur_s=0。
    """
    stats: dict[str, dict[str, Any]] = {}
    for u in utterances:
        cid = char_id_for(u)
        st = stats.setdefault(cid, {"n": 0, "first": "", "sample": []})
        st["n"] += 1
        if not st["first"] and u.text.strip():
            st["first"] = u.text
        if len(st["sample"]) < 2 and u.text.strip() and u.text not in st["sample"]:
            st["sample"].append(u.text)

    merged: dict[str, C.Character] = dict(existing)
    cast_summary: dict[str, Any] = {}
    for cid, st in stats.items():
        old = existing.get(cid)
        if old is None:
            old = C.Character(
                name=cid,
                aliases=[],
                gender="u",
                voice_ref=f"05_cast/voicebank/{cid}_ref.wav",
                ref_dur_s=0.0,
                desc=f"M6 暂定卡（来源=说话人台词 {st['n']} 句；待人工校订/LLM 校订）",
            )
            merged[cid] = old
        cast_summary[cid] = {
            "name": old.name,
            "gender": old.gender,
            "aliases": list(old.aliases),
            "desc": old.desc,
            "terms": dict(old.terms),
            "provisional": cid not in existing,
            "line_count": st["n"],
            "sample_lines": st["sample"],
        }
    return merged, cast_summary


def mine_term_candidates(utterances: list[C.Utterance], *, min_utts: int = 2) -> list[str]:
    """高频汉字专名候选挖掘（仅**列出**供人工/LLM 确认，不自动注入术语表）。

    规则：2–4 字 Han 串跨 ≥min_utts 句出现，且不被更长的候选包含；
    已在既有角色卡 name/aliases/terms 键中的跳过。离线确定性。
    """
    texts = [u.text for u in utterances if u.text.strip()]
    grams: dict[str, set[int]] = {}
    for idx, t in enumerate(texts):
        for m in re.finditer(r"[\u4e00-\u9fff]{2,12}", t):
            s = m.group()
            for n in (2, 3, 4):
                for i in range(len(s) - n + 1):
                    grams.setdefault(s[i:i + n], set()).add(idx)
    cands = [g for g, utts in grams.items() if len(utts) >= min_utts]
    cands.sort(key=lambda g: (-len(grams[g]), -len(g), g))
    kept: list[str] = []
    for g in cands:
        if any(g in k for k in kept):  # 已被更长候选包含的短串不重复列
            continue
        kept.append(g)
    return kept


def build_glossary(
    cast: dict[str, C.Character], seed: dict[str, Any], lang: str
) -> dict[str, str]:
    """术语表：C3 terms[lang]（角色名 + 别名同渲染）∪ 术语种子，源术语→目标语。

    种子格式（``06_mt/terms_seed.json``，可选）：``{"东坡": {"en": "Dongpo", ...}}``。
    冲突时种子覆盖角色卡（人工种子是显式更正）。
    """
    glossary: dict[str, str] = {}
    for ch in cast.values():
        render = ch.terms.get(lang)
        if not render:
            continue
        glossary[ch.name] = render
        for alias in ch.aliases:
            glossary[alias] = render
    for src, render_map in seed.items():
        if isinstance(render_map, dict):
            tgt = render_map.get(lang)
        else:  # 允许直接 {"东坡": "Dongpo"}（仅当前语种）的简写
            tgt = render_map if isinstance(render_map, str) else None
        if tgt:
            glossary[str(src)] = str(tgt)
    return glossary


def build_cast_summary_text(
    cast: dict[str, C.Character], cast_stats: dict[str, Any], lang: str
) -> str:
    """角色卡 → 注入翻译的结构化文本（[背景信息] 段；与训练模板口径一致）。"""
    lines: list[str] = []
    for cid, ch in cast.items():
        render = ch.terms.get(lang, "")
        alias = f"｜别名：{'、'.join(ch.aliases)}" if ch.aliases else ""
        term = f"｜称谓译法({lang})={render}" if render else ""
        lines.append(f"- {cid}｜{ch.name}｜{ch.desc}{alias}{term}")
    return "角色卡：\n" + "\n".join(lines) if lines else ""


def build_context(
    utterances: list[C.Utterance],
    existing: dict[str, C.Character],
    *,
    ep: str,
    lang: str,
    seed: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, C.Character]]:
    """① 通读全部 C2 → context.json 工作纸 + 合并后的角色卡。

    返回 dict（即 06_mt/context.json 的落盘内容，键集即 schema；
    ``relations`` 关系抽取归 local/api 后端的 LLM 通道，mock 离线留空占位）。
    """
    merged, cast_stats = draft_cast_from_utterances(utterances, existing)
    glossary = build_glossary(merged, seed or {}, lang)
    relations: list[dict[str, str]] = []
    cids = [char_id_for(u) for u in utterances]
    # 相邻对话对 → 关系线索占位（离线规则只记共现，语义定名归 LLM 通道）
    for a, b in zip(cids, cids[1:]):
        if a != b and {"a": a, "b": b} not in [
            {"a": r["a"], "b": r["b"]} for r in relations
        ]:
            relations.append({"a": a, "b": b, "relation": "待定（LLM 通道/人工）"})
    return {
        "ep": ep,
        "lang": lang,
        "generated_by": "m6",
        "cast": cast_stats,
        "glossary": glossary,
        "relations": relations,
        "term_candidates": mine_term_candidates(utterances),
        "notes": (
            "context.json 为 M6 工作纸（非冻结契约）：cast=角色卡摘要（provisional=本轮新增）；"
            "glossary=注入逐句翻译的术语表（C3 terms[lang] ∪ terms_seed）；"
            "relations/term_candidates 为占位与候选，须经人工或 LLM 通道确认后才入 C3。"
        ),
        "stats": {
            "n_utt": len(utterances),
            "n_chars": len(merged),
            "n_glossary": len(glossary),
        },
    }, merged


def _write_json_atomic(path: Path, payload: Any) -> None:
    """单文档 JSON 原子写（与 contracts._atomic_write_lines 同口径：tmp + os.replace）。"""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# C4 出口：逐句翻译（(utt_id, tgt) 复合键替换写盘）
# ---------------------------------------------------------------------------

def _upsert_translations(path: Path, rows: list[C.Translation]) -> int:
    """C4 写盘原语：按 (utt_id, tgt) 复合键替换 + 整文件原子重写。

    contracts.upsert_jsonl 是单键（utt_id）口径 —— C4 同句可有多语种行，
    这里沿用同一「读旧→替换同键→整表强校验→原子重写」语义，仅键为复合。
    """
    merged: dict[str, C.Translation] = {}
    if Path(path).is_file():
        for old in C.load_jsonl(path, C.TranslationTable).root:
            merged[f"{old.utt_id}|{old.tgt}"] = old
    for row in rows:
        merged[f"{row.utt_id}|{row.tgt}"] = row
    table = C.TranslationTable.model_validate(list(merged.values()))
    C.dump_jsonl(path, table)
    return len(table.root)


def _order_candidates(
    drafts: list[MTDraft],
    est_durs: list[float],
    budget: C.Budget,
) -> tuple[list[int], str]:
    """④ in-budget 排序：预算内优先 → q 降 → |est−orig| 升。返回排序索引与 policy。"""
    order = sorted(
        range(len(drafts)),
        key=lambda i: (
            0 if budget.lo <= est_durs[i] <= budget.hi else 1,
            -drafts[i].q,
            abs(est_durs[i] - budget.orig_dur),
        ),
    )
    return order, "in-budget-first"


def _translate_one(
    backend: MTBackend,
    u: C.Utterance,
    *,
    utts: list[C.Utterance],
    idx: int,
    prev_translations: list[str],
    lang: str,
    cast_summary_text: str,
    glossary: dict[str, str],
    budget: C.Budget,
    rates: dict[str, float],
    n_candidates: int,
) -> C.Translation:
    """单句：构造上下文 → 后端候选 → 补算 syl/est_dur → 排序 → C4 行。"""
    nxt = [x.text for x in utts[idx + 1: idx + 1 + CTX_WINDOW] if x.text.strip()]
    ctx = MTContext(
        tgt_lang=lang,
        cast_summary=cast_summary_text,
        terms=glossary,
        prev_texts=[t for t in prev_translations[-CTX_WINDOW:]],
        next_texts=nxt,
        budget=(budget.orig_dur, budget.lo, budget.hi),
    )
    drafts = backend.translate(u.text or u.utt_id, ctx, n_candidates=n_candidates)
    if not drafts:
        raise MtBackendError(f"后端 {backend.name} 对 {u.utt_id} 返回 0 候选")
    syl_counts = [count_syllables(d.text, lang) for d in drafts]
    est_durs = [estimate_dur_s(s, lang, rates) for s in syl_counts]
    order, policy = _order_candidates(drafts, est_durs, budget)
    candidates = [
        C.Candidate(
            text=drafts[i].text,
            syl=syl_counts[i],
            est_dur=est_durs[i],
            src=drafts[i].src,
            q=round(drafts[i].q, 3),
        )
        for i in order
    ]
    return C.Translation(
        utt_id=u.utt_id,
        tgt=lang,
        context=[t for t in prev_translations[-CTX_WINDOW:]],
        budget=budget,
        candidates=candidates,
        chosen=0 if candidates else None,
        policy=policy,
    )


def translate_episode(
    ep: str,
    lang: str,
    backend: MTBackend,
    *,
    jobs_dir: str | Path,
    n_candidates: int = 4,
    lo_ratio: float = 0.9,
    hi_ratio: float = 1.1,
    syl_table: Optional[Path] = None,
    seed_path: Optional[Path] = None,
) -> dict[str, Any]:
    """整集翻译主流程（①角色卡 → ②逐句 → ③估长 → ④排序 → C4/C3/context 落盘）。

    返回摘要 dict（句数/预算命中/超预算清单/术语命中/产物路径），供 CLI 与 eval 断言。
    """
    root = ep_dir(ep, jobs_dir)
    utt_path = root / "04_dial" / "utterances.jsonl"
    if not utt_path.is_file():
        raise FileNotFoundError(
            f"C2 不存在: {utt_path}（先跑 M2/M4 产出 04_dial/utterances.jsonl）"
        )
    utterances = C.load_jsonl(utt_path, C.UtteranceTable).root
    if not utterances:
        raise ValueError(f"C2 为空: {utt_path}")

    cast_path = root / "05_cast" / "characters.json"
    existing: dict[str, C.Character] = {}
    if cast_path.is_file():
        existing = dict(C.load_model(cast_path, C.CastBook).root)

    seed: dict[str, Any] = {}
    if seed_path and Path(seed_path).is_file():
        seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))

    # ① 角色卡（context 工作纸 + C3 增量合并）
    ctx_payload, merged_cast = build_context(
        utterances, existing, ep=ep, lang=lang, seed=seed
    )
    mt_dir = root / "06_mt"
    mt_dir.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(mt_dir / "context.json", ctx_payload)
    if merged_cast != existing:
        _write_json_atomic(
            cast_path,
            {cid: ch.model_dump(mode="json") for cid, ch in merged_cast.items()},
        )

    cast_summary_text = build_cast_summary_text(merged_cast, ctx_payload["cast"], lang)
    glossary = ctx_payload["glossary"]
    rates = load_syl_table(syl_table)

    # ②③④ 逐句翻译（前文滚动注入已定稿译文）
    rows: list[C.Translation] = []
    prev_texts: list[str] = []
    for idx, u in enumerate(utterances):
        budget = budget_for(u, lo_ratio, hi_ratio)
        row = _translate_one(
            backend, u,
            utts=utterances, idx=idx, prev_translations=prev_texts, lang=lang,
            cast_summary_text=cast_summary_text, glossary=glossary, budget=budget,
            rates=rates, n_candidates=n_candidates,
        )
        rows.append(row)
        chosen = row.candidates[row.chosen].text if row.chosen is not None else u.text
        prev_texts.append(chosen)

    out_path = mt_dir / "translations.jsonl"
    n_rows = _upsert_translations(out_path, rows)

    # 摘要统计（术语命中按「含源术语的句子，其候选含目标渲染」口径）
    term_hit_ok = term_hit_total = 0
    for u, row in zip(utterances, rows):
        for src_term, tgt_term in glossary.items():
            if src_term and src_term in (u.text or ""):
                term_hit_total += 1
                if any(tgt_term in c.text for c in row.candidates):
                    term_hit_ok += 1
    in_budget = [
        row.utt_id for row in rows
        if any(row.budget.lo <= c.est_dur <= row.budget.hi for c in row.candidates)
    ]
    return {
        "ep": ep,
        "lang": lang,
        "backend": backend.name,
        "n_utt": len(rows),
        "n_rows_written": n_rows,
        "n_candidates": n_candidates,
        "in_budget_utts": in_budget,
        "in_budget_rate": round(len(in_budget) / len(rows), 3) if rows else 0.0,
        "over_budget_utts": [r.utt_id for r in rows if r.utt_id not in in_budget],
        "term_hits": f"{term_hit_ok}/{term_hit_total}",
        "term_hit_rate": round(term_hit_ok / term_hit_total, 3) if term_hit_total else 1.0,
        "glossary": glossary,
        "cast_ids": sorted(merged_cast),
        "context_json": str(mt_dir / "context.json"),
        "characters_json": str(cast_path),
        "translations_jsonl": str(out_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.m6_translate",
        description="M6 整集上下文翻译 + 时长预算（local|api|mock 三后端）",
    )
    ap.add_argument("--ep", required=True, help="集 ID，如 ep01")
    ap.add_argument("--lang", default="en", help="目标语种（en/es/ar）")
    ap.add_argument("--backend", default=None,
                    choices=["local", "api", "mock"],
                    help="翻译后端（默认 env M6_MT_BACKEND，再默认 local）")
    ap.add_argument("--n-candidates", type=int, default=4,
                    help="每句候选数上限（规划口径 3–5，默认 4）")
    ap.add_argument("--jobs-dir", default=None, help="jobs 根目录（默认取 pipeline.yaml）")
    ap.add_argument("--base-url", default=None,
                    help="local 后端服务地址（默认 M6_MT_URL 或 http://127.0.0.1:9004）")
    ap.add_argument("--seed", default=None,
                    help="术语种子 JSON 路径（可选；角色卡 terms 之外的显式更正）")
    args = ap.parse_args(argv)

    cfg = load_pipeline_config()
    jobs_root = Path(args.jobs_dir) if args.jobs_dir else Path(cfg["paths"]["jobs_dir"])
    backend_name = args.backend or os.environ.get("M6_MT_BACKEND", "local")
    seed_path = Path(args.seed) if args.seed else None
    try:
        kw = {"base_url": args.base_url} if (args.base_url and backend_name != "mock") else {}
        backend = make_backend(backend_name, **kw)
        summary = translate_episode(
            args.ep, args.lang, backend, jobs_dir=jobs_root,
            n_candidates=max(1, min(5, args.n_candidates)),
            lo_ratio=float(cfg["budget"]["lo_ratio"]),
            hi_ratio=float(cfg["budget"]["hi_ratio"]),
            syl_table=Path(cfg["paths"]["models_dir"]) / "syl2dur.json",
            seed_path=seed_path,
        )
    except (MtBackendError, FileNotFoundError, ValueError, ValidationError) as exc:
        print(f"FAIL m6_translate: {exc}")
        return 1
    print(
        f"OK m6_translate ep={summary['ep']} lang={summary['lang']} backend={summary['backend']} "
        f"utts={summary['n_utt']} rows={summary['n_rows_written']} "
        f"in_budget={summary['in_budget_rate']} (target {cfg['budget']['hit_target_mvp']}) "
        f"terms={summary['term_hits']}"
    )
    print(f"  超预算句: {summary['over_budget_utts'] or '无'}")
    print(f"  术语表:   {summary['glossary'] or '（空）'}")
    print(f"  产物:     {summary['translations_jsonl']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
