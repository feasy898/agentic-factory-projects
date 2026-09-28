"""M4 客户端 —— ASR + 逐字对齐 + 情绪/事件（GPU :9001 服务的本机封装）。

调用链：``04_dial/vocals.wav``（M3 人声，B1 冻结：M4 只读人声）→ httpx 隧道 →
GPU asr_align 服务 → 契约 C2 出口。本模块落 ``04_dial/`` 原始产物；跨层融合
（OCR 校对、说话人回填、镜头对齐）属 M2/M5，经契约字段完成。

B1 冻结口径落地（docs/b1_contract_notes.md，2026-09-28）：
  - 时间零点：服务响应 words/segments 为**上传音频内相对时间**；落盘前统一
    ``contracts.to_absolute_seconds(t, offset)`` 平移（--offset，默认 0）；
  - 切句：句窗 = 服务 VAD segments（M2 就绪后其 OCR 时间段优先级更高），
    每段一句，**禁止把整段 text 当单句**；无段时兜底 ``[0, 时长]``；
  - ``utt_id = contracts.make_utt_id(ep, 绝对起点)``（稳定公式，替换键）；
  - 写盘：utterances 用 ``contracts.upsert_jsonl``（同 id 原子替换）；
    diar/emo/asr/forced 为读-合并-排序后整文件原子重写；
  - ``diar.jsonl`` = C2-pre ``DiarSegment{start,end,speaker="unknown"}``（M5 回填）。

用法：
    python -m pipeline.m4_asr --ep ep01                       # 默认读 04_dial/vocals.wav
    python -m pipeline.m4_asr --ep ep01 --wav x.wav --offset 12.5
退出码：0 成功；1 输入/服务/契约校验错误；2 用法错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.gpu_client import GpuClient, GpuServiceError
from pipeline.scaffold import ep_dir

#: shot_id 占位（M5 镜头表就绪后回填真实镜头）
PLACEHOLDER_SHOT = "s0000"
#: 字级时间归段判定的窗口容差（秒）
_EPS = 0.001
#: 连 writing（无空格连写）的语种；其余以空格连接
_NO_SPACE_LANGS = {"zh", "yue", "ja"}


class _RawRecord(BaseModel):
    """04_dial 原始记录行（非契约表；extra 放行以保留服务完整响应字段）。"""

    model_config = ConfigDict(extra="allow")
    utt_id: str


class _RawTable(RootModel[list[_RawRecord]]):
    """原始记录容器（供 upsert_jsonl 原子写；无唯一性约束）。"""


def _join_words(words: list[C.Word], lang: str) -> str:
    sep = "" if lang in _NO_SPACE_LANGS else " "
    return sep.join(w.w for w in words).strip()


def _shift(t: float, offset: float) -> float:
    """服务相对时间 → 全片绝对时间（B1 冻结规则 7 原语）。"""
    return C.to_absolute_seconds(t, offset)


def build_utterances(
    *,
    ep: str,
    resp: dict[str, Any],
    lang: str,
    offset: float = 0.0,
) -> tuple[list[C.Utterance], list[C.DiarSegment]]:
    """服务响应 → (契约 C2 行列表, C2-pre diar 段列表)。

    切句按 B1 冻结规则 8：句窗取 VAD segments；字按中点归段并夹取进句窗
    （契约校验器要求 utt.start ≤ word.s ≤ word.e ≤ utt.end 且按时间排序）。
    """
    words = [
        {"w": str(w["w"]), "s": _shift(float(w["s"]), offset), "e": _shift(float(w["e"]), offset)}
        for w in (resp.get("words") or [])
    ]
    dur = _shift(float(resp.get("duration_s") or 0.0), offset)
    segments = resp.get("segments") or []

    if segments:
        windows = [
            (_shift(float(s["start"]), offset), _shift(float(s["end"]), offset))
            for s in segments
        ]
    else:  # 兜底（B1 规则 8 第 3 优先级）：无段时整段作一句窗
        windows = [(0.0 + offset, dur) if dur > 0 else (offset, offset + 0.001)]

    emo = resp.get("emo") or None
    events = resp.get("events") or []
    nonverbal_hint = bool(resp.get("nonverbal_hint"))

    utterances: list[C.Utterance] = []
    diar: list[C.DiarSegment] = []
    for win_start, win_end in windows:
        if win_end <= win_start:
            win_end = win_start + 0.001
        # 字归段：中点落窗内；夹取进窗（契约字级校验要求）
        seg_words: list[C.Word] = []
        for w in words:
            mid = (w["s"] + w["e"]) / 2.0
            if not (win_start - _EPS <= mid <= win_end + _EPS):
                continue
            s = round(max(w["s"], win_start), 3)
            e = round(min(w["e"], win_end), 3)
            if e <= s:
                continue
            seg_words.append(C.Word(w=w["w"], s=s, e=e))
        seg_words.sort(key=lambda w: w.s)  # 契约要求按时间排序（校验器兜底）

        utt_id = C.make_utt_id(ep, win_start)
        utterances.append(
            C.Utterance(
                utt_id=utt_id,
                shot_id=PLACEHOLDER_SHOT,
                start=round(win_start, 3),
                end=round(win_end, 3),
                lang=lang,
                speaker=None,          # M5 说话人聚类回填
                char_id=None,          # M5 角色绑定回填
                text=_join_words(seg_words, lang),
                ocr=None,              # M2 OCR↔ASR 校对后回填
                words=seg_words,
                emo=(C.EmoTag(**emo) if emo else None),  # 服务为整段判别，M2/M5 融合细化
                events=[
                    C.SoundEvent(
                        label=e.get("label") or "unknown",
                        score=e.get("score"),
                        start=e.get("start"),
                        end=e.get("end"),
                    )
                    for e in events
                ],
                overlap=False,         # M5 重叠语音判定回填
                nonverbal=(nonverbal_hint and len(_join_words(seg_words, lang)) <= 2),
                face=None,             # M5 正脸/近景判定回填
            )
        )
        diar.append(
            C.DiarSegment(start=round(win_start, 3), end=round(win_end, 3), speaker="unknown")
        )
    return utterances, diar


def run(
    ep: str,
    wav: Path,
    *,
    lang: str = "zh",
    text: str = "",
    url: Optional[str] = None,
    offset: float = 0.0,
    do_align: bool = True,
    do_emo: bool = True,
) -> dict[str, Any]:
    """执行一次 M4 调用并落 04_dial/ 全部产物（utterances/diar 走契约原语）。返回摘要。"""
    cfg = load_pipeline_config()
    jobs_root = Path(cfg["paths"]["jobs_dir"])
    dial = ep_dir(ep, jobs_root) / "04_dial"
    if not wav.is_file():
        raise FileNotFoundError(
            f"输入音频不存在: {wav}（B1 冻结：M4 只读 04_dial/vocals.wav（M3 产出），"
            "或 --wav 显式指定）"
        )

    resp = GpuClient(url).asr_align(wav, lang=lang, text=text, do_align=do_align, do_emo=do_emo)
    if not (resp.get("text") or "").strip():
        raise GpuServiceError("服务返回空转写")

    utterances, diar = build_utterances(ep=ep, resp=resp, lang=lang, offset=offset)
    if not utterances:
        raise GpuServiceError("切句为空（无 VAD 段且时长为 0）")

    # utterances.jsonl：契约表，按 utt_id 原子替换（冻结写盘原语）
    C.upsert_jsonl(dial / "utterances.jsonl", utterances, container=C.UtteranceTable)

    # diar.jsonl：C2-pre 段级（M5 回填 speaker）；与旧段合并后按时间排序原子重写
    old_diar = []
    if (dial / "diar.jsonl").is_file():
        old_diar = [r.model_dump() for r in C.load_jsonl(dial / "diar.jsonl", C.DiarTable).root]
    merged_diar = sorted(
        [*old_diar, *(d.model_dump() for d in diar)], key=lambda r: r["start"]
    )
    C.dump_jsonl(dial / "diar.jsonl", C.DiarTable.model_validate(merged_diar))

    # 原始产物（asr/forced/emo）：按 utt_id upsert 的非契约原始行，保留服务完整响应
    raw_rows = []
    for u in utterances:
        raw_rows.append(_RawRecord(utt_id=u.utt_id, wav=wav.name, offset=offset, **{
            "text": resp.get("text"), "lang": lang, "lang_detected": resp.get("lang_detected"),
            "duration_s": resp.get("duration_s"), "segments": resp.get("segments"),
            "words": resp.get("words"), "aligner": resp.get("aligner"),
            "timing": resp.get("timing"), "versions": resp.get("versions"),
        }))
    C.upsert_jsonl(dial / "asr.jsonl", raw_rows, container=_RawTable)

    forced_rows = [
        _RawRecord(
            utt_id=u.utt_id,
            aligner=resp.get("aligner"),
            offset=offset,
            words=[{"w": w.w, "s": w.s, "e": w.e} for w in u.words],
        )
        for u in utterances
    ]
    C.upsert_jsonl(dial / "forced.jsonl", forced_rows, container=_RawTable)

    emo_rows = [
        _RawRecord(
            utt_id=u.utt_id,
            offset=offset,
            scope="clip",  # 服务整段判别；句级情绪细化属 M2/M5 融合
            emo=resp.get("emo"),
            events=resp.get("events") or [],
            nonverbal_hint=bool(resp.get("nonverbal_hint")),
        )
        for u in utterances
    ]
    C.upsert_jsonl(dial / "emo.jsonl", emo_rows, container=_RawTable)

    return {
        "ep": ep,
        "n_utt": len(utterances),
        "utt_ids": [u.utt_id for u in utterances],
        "texts": [u.text for u in utterances],
        "n_words_total": sum(len(u.words) for u in utterances),
        "emo": resp.get("emo") or {},
        "n_segments": len(diar),
        "aligner": resp.get("aligner"),
        "timing": resp.get("timing") or {},
        "dial_dir": str(dial),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.m4_asr", description="M4 ASR/对齐/情绪 客户端")
    ap.add_argument("--ep", required=True, help="集 ID，如 ep01")
    ap.add_argument("--wav", default=None, help="输入 wav（B1 冻结默认 04_dial/vocals.wav）")
    ap.add_argument("--lang", default="zh", help="语种（ar 自动走字符比例对齐降级）")
    ap.add_argument("--text", default="", help="校对文本（非空则按它重对齐）")
    ap.add_argument("--url", default=None, help="服务地址（默认 M4_ASR_URL 或 http://127.0.0.1:9001）")
    ap.add_argument("--offset", type=float, default=0.0,
                    help="上传片段在全片时间轴的起点秒（B1 冻结规则 7 的时间零点注入）")
    ap.add_argument("--no-align", action="store_true", help="跳过字级对齐")
    ap.add_argument("--no-emo", action="store_true", help="跳过情绪/事件")
    args = ap.parse_args(argv)

    wav = Path(args.wav) if args.wav else None
    if wav is None:
        cfg = load_pipeline_config()
        wav = ep_dir(args.ep, Path(cfg["paths"]["jobs_dir"])) / "04_dial" / "vocals.wav"
    try:
        summary = run(
            args.ep,
            wav,
            lang=args.lang,
            text=args.text,
            url=args.url,
            offset=args.offset,
            do_align=not args.no_align,
            do_emo=not args.no_emo,
        )
    except (GpuServiceError, FileNotFoundError, ValidationError) as exc:
        print(f"FAIL m4_asr: {exc}")
        return 1
    texts = " | ".join(summary["texts"])
    print(
        f"OK m4_asr ep={summary['ep']} utts={summary['n_utt']} "
        f"words={summary['n_words_total']} emo={summary['emo'].get('label') if summary['emo'] else None} "
        f"segments={summary['n_segments']} aligner={summary['aligner']} timing={summary['timing']}"
    )
    print(f"  utt_ids: {summary['utt_ids']}")
    print(f"  texts:   {texts!r}")
    print(f"  04_dial 产物: {summary['dial_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
