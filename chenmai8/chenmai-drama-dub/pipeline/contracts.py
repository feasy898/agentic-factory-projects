"""冻结契约 C1–C8 —— 本项目唯一权威 schema（pipeline/contracts.py）。

状态：**T1 冻结（2026-09-28）**。此后任何字段级改动 = 改规划，须主会话裁决；
模块不得单方面新增/删除/放宽字段（``extra="forbid"`` 兜底拒收未登记字段）。

冻结规则（源自规划 §3）：
1. 所有时间字段单位为秒，float 统一保留 3 位小数（写入前四舍五入）；
2. ``utt_id`` 全局唯一（C2/C4/C5/C6 容器强校验），``shot_id`` 集内唯一（C1）；
3. C2 ``text`` 以硬字幕 OCR ↔ 语音识别校对结果为准（M2 产出口径）；
4. C5：``nonverbal`` 句（哭/尖叫）``keep_original=true``，不合成（M7 生产规则）；
5. C6 分流：正脸 + 近景 + 非重叠才入口型；台词最长前 10% 镜头用 lip-pro，
   其余合格镜头用 lip-fast（见 :func:`lip_eligible`）；
6. C7 依据 GB 45438-2025（显式 + 隐式标识 + 内容凭证 + 音频水印）；
7. M4 时间零点（B1 冻结 2026-09-28）：``:9001`` /v1/asr_align 响应中的
   ``words[*].s/e`` 与 ``segments[*].start/end`` 均为**上传音频内相对时间**
   （0 = 上传片段起点）；全片绝对时间 = 片段内时间 + offset
   （offset = 上传片段在 01_media/audio_16k.wav 中的起点秒，由客户端注入，
   见 :func:`to_absolute_seconds`；服务端不做平移）；
8. 切句规则（B1 冻结）：C2 句窗（Utterance.start/end）来源优先级 =
   ① M2 OCR 字幕时间段（03_ocr/ocr_merged.jsonl 有字幕区间时按其切句）
   ② 服务返回 VAD segments（能量预分段）③ 兜底 [0, 音频时长]。
   **禁止**把服务整段 ``text`` 当单句落 C2：服务返回整段一个 string，
   text/words/segments 三者无共同键，唯一共同基准是上传音频 0 秒；
9. ``utt_id`` 稳定生成公式（B1 冻结）：``<ep>-u<起始毫秒,8 位零填充>``
   （:func:`make_utt_id`）；写盘一律「按 utt_id 替换后整文件重写」
   （:func:`upsert_jsonl`），禁止同 id 追加（追加会触发唯一性自锁）；
10. 说话人段级契约 ``diar.jsonl``（B1 冻结）：:class:`DiarSegment`
   （start/end/speaker），M4/VAD 只负责切分，``speaker`` 由 M5 聚类回填；
   **M5 执行不在 B1 批次**（B1 出口 ``Utterance.speaker`` 保持 None），
   归入 B2 批次（见 docs/b1_contract_notes.md §5）。
"""

from __future__ import annotations

import json
import os
from datetime import date as _Date
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Iterable,
    Literal,
    Optional,
    Sequence,
    TypeVar,
    Union,
)

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    field_validator,
    model_validator,
)

__all__ = [
    # C1
    "Shot",
    "ShotSheet",
    # C2
    "OcrFact",
    "Word",
    "EmoTag",
    "SoundEvent",
    "FaceFact",
    "Utterance",
    "UtteranceTable",
    # C2-pre（B1 冻结：说话人段级预分段）
    "DiarSegment",
    "DiarTable",
    # C3
    "Consent",
    "Character",
    "CastBook",
    # C4
    "Budget",
    "Candidate",
    "Translation",
    "TranslationTable",
    # C5
    "SynthPlanItem",
    "SynthPlanTable",
    # C6
    "LipPlanItem",
    "LipPlanTable",
    # C7
    "ExplicitLabel",
    "ImplicitLabel",
    "AudioWatermark",
    "Labels",
    # C8
    "Finding",
    "LabelStatus",
    "ComplianceReport",
    # 分流规则
    "lip_eligible",
    # B1 冻结：时间零点 / utt_id 公式 / 替换写盘原语
    "to_absolute_seconds",
    "make_utt_id",
    "upsert_jsonl",
    # IO
    "dump_jsonl",
    "load_jsonl",
    "load_model",
    "CONTRACT_KINDS",
]


# ---------------------------------------------------------------------------
# 基础类型
# ---------------------------------------------------------------------------

def _sec3(value: Any) -> float:
    """时间秒值 → float 保留 3 位小数（冻结规则 1）。"""
    return round(float(value), 3)


#: 秒（允许任意符号，统一 3 位小数）
Sec = Annotated[float, BeforeValidator(_sec3)]
#: 非负秒
NonNegSec = Annotated[float, BeforeValidator(_sec3), Field(ge=0)]


class _Frozen(BaseModel):
    """契约模型基类：拒收未登记字段，防止模块私下扩 schema。"""

    model_config = ConfigDict(extra="forbid")


def _require_unique(keys: Sequence[str], what: str) -> None:
    seen: set[str] = set()
    dups: list[str] = []
    for k in keys:
        if k in seen and k not in dups:
            dups.append(k)
        seen.add(k)
    if dups:
        raise ValueError(f"{what} 重复: {dups}")


# ---------------------------------------------------------------------------
# 契约 C1 —— shots.json（镜头表）
# ---------------------------------------------------------------------------

class Shot(_Frozen):
    """单个镜头。"""

    shot_id: str = Field(min_length=1)
    start: NonNegSec
    end: NonNegSec
    cut: Literal["hard", "soft"] = "hard"
    faces: int = Field(default=0, ge=0)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: float, info: Any) -> float:
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError(f"shot end 须大于 start: end={v} <= start={start}")
        return v


class ShotSheet(_Frozen):
    """契约 C1 ``shots.json`` —— 镜头切分结果（M5 产出口径）。"""

    ep: str = Field(min_length=1)
    fps: int = Field(gt=0)
    dur: NonNegSec
    shots: list[Shot] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_shot_ids(self) -> "ShotSheet":
        _require_unique([s.shot_id for s in self.shots], "shot_id")
        return self


# ---------------------------------------------------------------------------
# 契约 C2 —— utterances.jsonl（核心契约：OCR/ASR/说话人/情绪融合事实表）
# ---------------------------------------------------------------------------

class OcrFact(_Frozen):
    """硬字幕 OCR 事实（M2 产出口径：conf>=0.9 以 OCR 为准，否则 ASR）。"""

    text: str
    conf: float = Field(ge=0.0, le=1.0)
    agree: bool = False


class Word(_Frozen):
    """字级时间戳（M4 对齐产出口径）。"""

    w: str
    s: NonNegSec
    e: NonNegSec

    @field_validator("e")
    @classmethod
    def _e_after_s(cls, v: float, info: Any) -> float:
        s = info.data.get("s")
        if s is not None and v < s:
            raise ValueError(f"word 结束时间须不早于开始时间: e={v} < s={s}")
        return v


class EmoTag(_Frozen):
    """情绪标签（7 类）+ 强度分。"""

    label: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)


class SoundEvent(_Frozen):
    """非语言声音事件（哭/笑/掌声/叹气等）。"""

    label: str = Field(min_length=1)
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    start: Optional[NonNegSec] = None
    end: Optional[NonNegSec] = None


class FaceFact(_Frozen):
    """正脸/近景判定与人脸框（M5 产出口径）。"""

    frontal: bool
    closeup: bool
    bbox: Annotated[list[int], Field(min_length=4, max_length=4)]


class Utterance(_Frozen):
    """契约 C2 单句事实表 —— 全管线的核心交换格式。

    冻结规则：``utt_id`` 全局唯一；``text`` 以 OCR↔ASR 校对结果为准。
    """

    utt_id: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    start: NonNegSec
    end: NonNegSec
    lang: str = Field(min_length=2)
    speaker: Optional[str] = None
    char_id: Optional[str] = None
    text: str = ""
    ocr: Optional[OcrFact] = None
    words: list[Word] = Field(default_factory=list)
    emo: Optional[EmoTag] = None
    events: list[SoundEvent] = Field(default_factory=list)
    overlap: bool = False
    nonverbal: bool = False
    face: Optional[FaceFact] = None

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: float, info: Any) -> float:
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError(f"utterance end 须大于 start: end={v} <= start={start}")
        return v

    @model_validator(mode="after")
    def _words_within_and_sorted(self) -> "Utterance":
        """字级时间校验（B1 冻结，2026-09-28）：
        每个字须满足 ``utt.start ≤ word.s ≤ word.e ≤ utt.end``，且按时间排序
        （``word.s`` 非降；同起点并列允许）。空 words 跳过。"""
        prev_s = -1.0
        for i, w in enumerate(self.words):
            if not (self.start <= w.s <= w.e <= self.end):
                raise ValueError(
                    f"words[{i}] 越出句窗: utt=[{self.start}, {self.end}] "
                    f"word=[{w.s}, {w.e}] ({w.w!r})"
                )
            if w.s < prev_s:
                raise ValueError(f"words[{i}] 未按时间排序: s={w.s} < 前一字 s={prev_s}")
            prev_s = w.s
        return self


class UtteranceTable(RootModel[list[Utterance]]):
    """契约 C2 容器：``utterances.jsonl`` 全集（``utt_id`` 全局唯一）。"""

    @model_validator(mode="after")
    def _unique_utt_ids(self) -> "UtteranceTable":
        _require_unique([u.utt_id for u in self.root], "utt_id")
        return self


# ---------------------------------------------------------------------------
# 契约 C2-pre —— diar.jsonl（说话人段级预分段；B1 冻结 2026-09-28）
# ---------------------------------------------------------------------------

class DiarSegment(_Frozen):
    """说话人段级 schema（``04_dial/diar.jsonl`` 单行）。

    冻结口径：M4/VAD（或 M2 OCR 时间段）只负责切出 ``start/end``
    （**上传音频内相对时间**，冻结规则 7/8）；``speaker`` 是 M5 聚类回填的
    段级标签（如 ``spk0``；段内未定人时填 ``unknown``，不置空）。
    注意：这是 M4→M5 的**段级**中间契约，句级归属（Utterance.speaker/char_id）
    由 M5 消费本表后回填 C2。
    """

    start: NonNegSec
    end: NonNegSec
    speaker: str = Field(min_length=1)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: float, info: Any) -> float:
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError(f"diar 段 end 须大于 start: end={v} <= start={start}")
        return v


class DiarTable(RootModel[list[DiarSegment]]):
    """契约 C2-pre 容器：``diar.jsonl`` 全集（段按时间排序，允许说话人重复）。"""

    @model_validator(mode="after")
    def _sorted_by_time(self) -> "DiarTable":
        for a, b in zip(self.root, self.root[1:]):
            if b.start < a.start:
                raise ValueError(f"diar 段未按时间排序: {a.start} -> {b.start}")
        return self


# ---------------------------------------------------------------------------
# 契约 C3 —— characters.json（角色表 + 音色库 + 授权）
# ---------------------------------------------------------------------------

class Consent(_Frozen):
    """声音/肖像授权记录（每部剧人工确认一次，各集复用）。"""

    subject: str = Field(min_length=1)
    form: str = Field(min_length=1)
    scope: str = "比赛演示"
    # 注：字段名 date 为契约冻结名；类型用别名 _Date，避免与字段名同名遮蔽
    date: Optional[_Date] = None


class Character(_Frozen):
    """角色卡：称谓、音色参考、术语表与授权。"""

    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    gender: Literal["m", "f", "u"] = "u"
    voice_ref: str = Field(min_length=1)
    ref_dur_s: NonNegSec
    desc: str = ""
    terms: dict[str, str] = Field(default_factory=dict)
    consent: Optional[Consent] = None


class CastBook(RootModel[dict[str, Character]]):
    """契约 C3 容器：char_id → 角色卡。"""

    @model_validator(mode="after")
    def _nonempty_keys(self) -> "CastBook":
        _require_unique(list(self.root.keys()), "char_id")
        return self


# ---------------------------------------------------------------------------
# 契约 C4 —— translations.jsonl（译文候选 + 时长预算）
# ---------------------------------------------------------------------------

class Budget(_Frozen):
    """本句时长预算（秒）。"""

    orig_dur: NonNegSec
    lo: NonNegSec
    hi: NonNegSec

    @model_validator(mode="after")
    def _lo_le_hi(self) -> "Budget":
        if self.lo > self.hi:
            raise ValueError(f"预算下界须不大于上界: lo={self.lo} > hi={self.hi}")
        return self


class Candidate(_Frozen):
    """单个译文候选。"""

    text: str
    syl: int = Field(ge=0)
    est_dur: NonNegSec
    src: str = Field(min_length=1)
    q: float = Field(ge=0.0, le=1.0)


class Translation(_Frozen):
    """契约 C4 单句翻译记录。"""

    utt_id: str = Field(min_length=1)
    tgt: str = Field(min_length=2)
    context: list[str] = Field(default_factory=list)
    budget: Budget
    candidates: list[Candidate] = Field(default_factory=list)
    chosen: Optional[int] = Field(default=None, ge=0)
    policy: str = "in-budget-first"

    @model_validator(mode="after")
    def _chosen_in_range(self) -> "Translation":
        if self.chosen is not None and self.chosen >= len(self.candidates):
            raise ValueError(
                f"chosen={self.chosen} 越界（candidates 共 {len(self.candidates)} 条）"
            )
        return self


class TranslationTable(RootModel[list[Translation]]):
    """契约 C4 容器：(utt_id, tgt) 唯一。"""

    @model_validator(mode="after")
    def _unique_pairs(self) -> "TranslationTable":
        _require_unique([f"{t.utt_id}|{t.tgt}" for t in self.root], "(utt_id, tgt)")
        return self


# ---------------------------------------------------------------------------
# 契约 C5 —— synth_plan.jsonl（合成计划：音色参考与情绪参考分离）
# ---------------------------------------------------------------------------

class SynthPlanItem(_Frozen):
    """契约 C5 单句合成计划。

    冻结规则：``nonverbal=true`` 的句子（哭/尖叫）``keep_original=true``，
    直接复用原片人声，不送合成引擎（M7 生产规则）。
    """

    utt_id: str = Field(min_length=1)
    engine: str = "dub-tts"
    voice_ref: str = Field(min_length=1)
    emo_ref: Optional[str] = None
    emo_alpha: float = Field(default=0.7, ge=0.0, le=1.0)
    duration_factor: float = Field(default=1.0, ge=0.5, le=2.0)
    text: str
    out: str = Field(min_length=1)
    expect_dur: Optional[NonNegSec] = None
    keep_original: bool = False


class SynthPlanTable(RootModel[list[SynthPlanItem]]):
    """契约 C5 容器：utt_id 唯一。"""

    @model_validator(mode="after")
    def _unique_utt_ids(self) -> "SynthPlanTable":
        _require_unique([i.utt_id for i in self.root], "utt_id")
        return self


# ---------------------------------------------------------------------------
# 契约 C6 —— lip_plan.jsonl（口型分流计划）
# ---------------------------------------------------------------------------

class LipPlanItem(_Frozen):
    """契约 C6 单镜头口型计划。"""

    utt_id: str = Field(min_length=1)
    shot_id: str = Field(min_length=1)
    engine: Literal["lip-fast", "lip-pro"] = "lip-fast"
    priority: Literal["normal", "pro"] = "normal"
    window: Annotated[list[NonNegSec], Field(min_length=2, max_length=2)]
    face_track: int = Field(default=0, ge=0)

    @field_validator("window")
    @classmethod
    def _window_ordered(cls, v: list[float]) -> list[float]:
        if v[0] > v[1]:
            raise ValueError(f"window 起点须不大于终点: {v}")
        return v


class LipPlanTable(RootModel[list[LipPlanItem]]):
    """契约 C6 容器：utt_id 唯一。"""

    @model_validator(mode="after")
    def _unique_utt_ids(self) -> "LipPlanTable":
        _require_unique([i.utt_id for i in self.root], "utt_id")
        return self


def lip_eligible(u: Utterance) -> bool:
    """C6 冻结分流规则：正脸 + 近景 + 非重叠 才入口型；否则原画。

    重点镜头（台词最长前 10%）升级 lip-pro 的排序逻辑属 M10 生产策略，
    不在本契约内（契约只冻结"是否合格"）。
    """
    return bool(u.face and u.face.frontal and u.face.closeup and not u.overlap)


# ---------------------------------------------------------------------------
# B1 冻结原语 —— 时间零点 / utt_id 公式（2026-09-28）
# ---------------------------------------------------------------------------

def to_absolute_seconds(t: float, offset: float) -> float:
    """:9001 服务响应时间 → 全片绝对时间（冻结规则 7）。

    ``绝对 = 片段内相对 + offset``，其中 offset 为上传片段在
    ``01_media/audio_16k.wav`` 中的起点秒。与契约同口径保留 3 位小数。
    """
    return round(float(t) + float(offset), 3)


def make_utt_id(ep: str, start_s: float) -> str:
    """``utt_id`` 稳定生成公式（冻结规则 9）：``<ep>-u<起始毫秒,8 位零填充>``。

    同一集内同一时间起点重跑得到同一 id —— 该 id 即 :func:`upsert_jsonl`
    的替换键，支撑同句重跑与断点续跑。负起点拒绝（音频时间轴无负值）。
    """
    if not ep:
        raise ValueError("ep 不得为空")
    ms = int(round(float(start_s) * 1000))
    if ms < 0:
        raise ValueError(f"起始毫秒须非负: {ms}")
    return f"{ep}-u{ms:08d}"


# ---------------------------------------------------------------------------
# 契约 C7 —— labels.json（GB 45438-2025 标识 + 内容凭证 + 音频水印）
# ---------------------------------------------------------------------------

class ExplicitLabel(_Frozen):
    """显式标识（片头文字提示）。"""

    text: str = "本内容由AI生成"
    video: str
    audio_announce: bool = False


class ImplicitLabel(_Frozen):
    """隐式标识（元数据字段）。"""

    metadata_field: str = "XMP:aiGeneratedContent"
    value: str


class AudioWatermark(_Frozen):
    """音频水印（16-bit 负荷）。"""

    engine: str = "audmark"
    payload: str
    bits: Literal[16] = 16


class Labels(_Frozen):
    """契约 C7 ``labels.json``。"""

    service_provider: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    standard: Literal["GB45438-2025"] = "GB45438-2025"
    explicit: ExplicitLabel
    implicit: ImplicitLabel
    c2pa: str
    audio_wm: AudioWatermark


# ---------------------------------------------------------------------------
# 契约 C8 —— compliance.<lang>.json（市场合规报告）
# ---------------------------------------------------------------------------

class Finding(_Frozen):
    """单条合规发现。"""

    utt_id: Optional[str] = None
    rule: str = Field(min_length=1)
    sev: Literal["high", "medium", "low"] = "medium"
    t: Annotated[list[NonNegSec], Field(min_length=2, max_length=2)]
    suggest: str = ""
    auto: str = "flag"

    @field_validator("t")
    @classmethod
    def _t_ordered(cls, v: list[float]) -> list[float]:
        if v[0] > v[1]:
            raise ValueError(f"时间区间起点的须不大于终点: {v}")
        return v


class LabelStatus(_Frozen):
    """四项标识落实状态。"""

    explicit: Literal["ok", "pending", "failed"] = "pending"
    implicit: Literal["ok", "pending", "failed"] = "pending"
    c2pa: Literal["ok", "pending", "failed"] = "pending"
    audio_wm: Literal["ok", "pending", "failed"] = "pending"


class ComplianceReport(_Frozen):
    """契约 C8 ``compliance.<lang>.json``。"""

    market: str = Field(min_length=1)
    ep: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)
    label_status: LabelStatus = Field(default_factory=LabelStatus)
    human_review: list[str] = Field(default_factory=list)
    generator: str = "rule-yaml+LLM"


# ---------------------------------------------------------------------------
# 序列化 IO（JSON 单文档 / JSONL 表）
# ---------------------------------------------------------------------------

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_model(path: str | Path, cls: type[ModelT]) -> ModelT:
    """读取单个 JSON 契约文档（C1/C3/C7/C8）。"""
    return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


def dump_jsonl(path: str | Path, items: Union[Iterable[BaseModel], RootModel]) -> int:
    """写 JSONL；``items`` 可为模型迭代器或 RootModel 容器。返回行数。

    原子写：先写同目录临时文件再 ``os.replace``，避免半截文件被当作产物读入。
    同 id 追加场景请改用 :func:`upsert_jsonl`（追加会触发唯一性自锁）。
    """
    if isinstance(items, RootModel):
        items = items.root  # type: ignore[attr-defined]
    rows = list(items)
    for row in rows:
        if not isinstance(row, BaseModel):
            raise TypeError(f"dump_jsonl 只接受 pydantic 模型，得到 {type(row)!r}")
    _atomic_write_lines(path, [row.model_dump_json() for row in rows])
    return len(rows)


def _atomic_write_lines(path: str | Path, lines: list[str]) -> None:
    """同目录临时文件 + os.replace 的原子整文件写。

    路径安全（写盘统一出口，CWE-22 防护）：先 ``resolve()`` 规范化
    （消解 ``..`` 段与相对引用），再显式复核无 ``..`` 段与 NUL 字节，
    随后全部写盘操作只用规范化路径；上层另有 ``scaffold.ep_dir``
    集 ID 白名单兜底（``--ep`` 是工作区路径的来源组件）。
    原子性：临时文件整体写完后 ``os.replace`` 原子替换 —— 读取方要么看到
    旧整文件要么看到新整文件，不会读到半截（断电丢最后一窗为已知取舍）。
    """
    path = Path(path)
    if "\x00" in str(path):
        raise ValueError(f"非法产物路径（含 NUL 字节）: {path!r}")
    path = path.resolve()  # 规范化：.. 与相对引用在此消解
    if ".." in path.parts:
        raise ValueError(f"非法产物路径（规范化后仍含 .. 段）: {path!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(ln + "\n" for ln in lines), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def upsert_jsonl(
    path: str | Path,
    items: Iterable[BaseModel],
    *,
    container: type[RootModel],
    key_field: str = "utt_id",
) -> int:
    """按 id 替换后整文件重写（冻结规则 9 的写盘原语；解决追加自锁）。

    语义：读旧文件（存在时）→ 以 ``key_field`` 值为键，``items`` 覆盖同键旧行、
    其余保留（替换行保持原位置，新行追加尾部）→ 整表经 ``container`` 强校验
    （唯一性/时间窗等全部规则重新生效）→ 原子重写。返回写出行数。

    ``items`` 为契约模型实例；同键多条以最后一条为准。
    """
    path = Path(path)
    merged: dict[Any, BaseModel] = {}
    if path.is_file():
        for row in load_jsonl(path, container).root:
            merged[getattr(row, key_field)] = row
    for it in items:
        if not isinstance(it, BaseModel):
            raise TypeError(f"upsert_jsonl 只接受 pydantic 模型，得到 {type(it)!r}")
        merged[getattr(it, key_field)] = it
    table = container.model_validate(list(merged.values()))
    _atomic_write_lines(path, [row.model_dump_json() for row in table.root])
    return len(table.root)


def load_jsonl(path: str | Path, cls: type) -> Any:
    """读 JSONL。

    ``cls`` 为 RootModel 容器（如 :class:`UtteranceTable`）→ 返回容器实例；
    ``cls`` 为普通模型（如 :class:`Utterance`）→ 返回模型列表。
    """
    rows: list[Any] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if isinstance(cls, type) and issubclass(cls, RootModel):
        return cls.model_validate(rows)
    return [cls.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# 契约登记表（CLI validate 子命令使用）
# ---------------------------------------------------------------------------

CONTRACT_KINDS: dict[str, tuple[str, type, bool]] = {
    # kind: (契约号, 模型类, 是否 JSONL)
    "shots": ("C1", ShotSheet, False),
    "utterances": ("C2", UtteranceTable, True),
    "diar": ("C2-pre", DiarTable, True),  # B1 冻结：说话人段级预分段（M4→M5）
    "characters": ("C3", CastBook, False),
    "translations": ("C4", TranslationTable, True),
    "synth-plan": ("C5", SynthPlanTable, True),
    "lip-plan": ("C6", LipPlanTable, True),
    "labels": ("C7", Labels, False),
    "compliance": ("C8", ComplianceReport, False),
}
