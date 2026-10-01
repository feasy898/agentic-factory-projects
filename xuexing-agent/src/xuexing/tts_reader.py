"""tts_reader —— 语音读题（BACKLOG P3「tts_reader 语音读题」）的确定性内核。

行为契约（specs/drafts/tts_reader.spec.md，本文件为参考实现）：

- 低龄/无障碍读题：题干+选项 -> 确定性朗读文本（choice 追加「选项L：正文」段；
  无题号、无作答提示语，绝不含 solution/answer）-> 注入的 TTS 客户端合成音频
  （mm_client.MMClient.tts 满足 tts.tts(text, voice=…, response_format=…) -> bytes 表面）。
- 音频缓存键 = (题目 id, voice)：命中零次合成调用；未命中恰好一次并回填调用方容器。
- read_paper 按卷面题序（sections 顺序展开、空 sections 回退 paper.item_ids，与
  omr_sheet/paper_layout/mm_ingest 同编号语义）整卷合成，共享同一缓存。
- 模块间零 import：tts 与 item/paper/bank 都是注入鸭子对象，与 mm_client/omr_sheet
  的一致性由契约测试在测试内 import 对方模块跨模块锁定。

全模块纯函数：无 IO、无随机、无时钟、不读环境，同输入同输出（音频字节来自注入的
tts；显式注入的 cache 容器是按设计回填的唯一可变副作用）。
"""
# 注意：不用 `from __future__ import annotations`——它把 dataclass 字段注解字符串化，
# 重生成注入装载（XX_IMPL_DIR，模块名不在 sys.modules）时 dataclasses 的 KW_ONLY
# 探测会 sys.modules.get(cls.__module__).__dict__ 崩溃（mm_ingest 同此约定）。
import hashlib
import re
from collections.abc import MutableMapping
from dataclasses import dataclass

__all__ = [
    "TTSError",
    "READER_VERSION",
    "DEFAULT_VOICE",
    "AUDIO_FORMAT",
    "ITEM_TYPES",
    "ItemAudio",
    "option_labels",
    "build_reading_text",
    "synthesize_item",
    "read_paper",
]


class TTSError(ValueError):
    """tts_reader 模块所有校验失败的异常类型（ValueError 直接子类）。"""


# ---- 冻结常量（specs/drafts/tts_reader.spec.md §3）----

READER_VERSION = "1"

# 与 mm_client.TTS_VOICE / TTS_FORMAT 相等（跨模块锁定，docs/multimodal-api.md 实测矩阵）
DEFAULT_VOICE = "linjiajiejie"
AUDIO_FORMAT = "mp3"

# 合法题型（与 types.Item.item_type 值域一致）
ITEM_TYPES = ("choice", "fill", "solve")

# 显式选项标签：单个 ASCII 字母 + 分隔符（. ． 、 ) ）），后接选项正文
# （与 omr_sheet.parse_option / mm_ingest._OPT_RE 同款正则，跨模块锁定）
_OPT_RE = re.compile(r"([A-Za-z])[.．、)）][ \t]*(.*)\Z", re.S)
_FALLBACK_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MAX_OPTIONS = 26

# 句末标点：拼接时已以此结尾则不再插「。」（：，… 等一律视为非句末）
# 注意必须是 tuple——str.endswith(str) 是单后缀匹配，不是字符集合
_SENTENCE_END = ("。", "！", "？", ".", "!", "?")

# 缓存容器表面：dict-like（tuple 键 (item_id, voice)）；list/str 不是 Mapping
_CACHE_OPS_DOC = "collections.abc.MutableMapping"


def _require_cache(cache):
    if cache is None:
        return {}
    if isinstance(cache, MutableMapping):
        return cache
    raise TTSError(
        "cache must be None or a dict-like MutableMapping "
        f"({_CACHE_OPS_DOC}), got {type(cache).__name__}")


@dataclass
class ItemAudio:
    """一道题的读题音频：朗读文本 + 音频字节 + 是否来自缓存。"""

    item_id: str
    voice: str
    text: str
    audio: bytes
    from_cache: bool

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "voice": self.voice,
            "format": AUDIO_FORMAT,
            "text": self.text,
            "audio_size": len(self.audio),
            "audio_sha256": hashlib.sha256(self.audio).hexdigest(),
            "from_cache": self.from_cache,
        }


# ---------- 表面守卫积木 ----------

def _non_blank_str(value, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TTSError(f"{name} must be a non-blank str")
    return value


def _require_tts(tts):
    fn = getattr(tts, "tts", None)
    if not callable(fn):
        raise TTSError("tts client must provide a callable tts()")
    return fn


def _require_str_attr(obj, attr: str, what: str) -> str:
    value = getattr(obj, attr, None)
    if not isinstance(value, str):
        raise TTSError(f"{what} must be str, got {type(value).__name__}")
    return value


# ---------- 选项标签与正文 ----------

def option_labels(item) -> list:
    """choice 题的选项标签列（与 omr_sheet.parse_option 同闭式，跨模块锁定）。

    options 非 list/tuple、长度 <2 或 >26、含非 str/空白串、标签重复 -> TTSError。
    """
    iid = getattr(item, "id", None)
    raw_options = getattr(item, "options", None)
    if not isinstance(raw_options, (list, tuple)) or len(raw_options) < 2:
        raise TTSError(f"item {iid} choice needs >=2 options")
    if len(raw_options) > _MAX_OPTIONS:
        raise TTSError(
            f"item {iid} has {len(raw_options)} options, max is {_MAX_OPTIONS}")
    labels = []
    for pos, raw in enumerate(raw_options):
        if not isinstance(raw, str) or not raw.strip():
            raise TTSError(f"item {iid} option text must be a non-blank str")
        m = _OPT_RE.match(raw.strip())
        labels.append(m.group(1).upper() if m else _FALLBACK_LABELS[pos])
    if len(set(labels)) != len(labels):
        raise TTSError(f"item {iid} duplicate option labels: {labels}")
    return labels


def _option_body(raw: str, iid) -> str:
    """朗读正文：显式标签后的剩余文本 strip；无显式标签为原文 strip；空白 -> TTSError。"""
    m = _OPT_RE.match(raw.strip())
    body = (m.group(2) if m else raw).strip()
    if not body:
        raise TTSError(f"item {iid} option body is blank after label: {raw!r}")
    return body


# ---------- 朗读文本（只含题干+选项，I2 纯度） ----------

def _join_segments(segments: list) -> str:
    out = ""
    for seg in segments:
        if out and not out.endswith(_SENTENCE_END):
            out += "。"
        out += seg
    if not out.endswith(_SENTENCE_END):
        out += "。"
    return out


def build_reading_text(item) -> str:
    """一道题 -> 确定性朗读文本（题干 + choice 的「选项L：正文」段；I2 纯度）。"""
    iid = _non_blank_str(getattr(item, "id", None), "item.id")
    stem = _non_blank_str(getattr(item, "stem", None), f"item {iid} stem")
    item_type = getattr(item, "item_type", None)
    if item_type not in ITEM_TYPES:
        raise TTSError(f"unknown item_type for {iid}: {item_type!r}")
    segments = [stem.strip()]
    if item_type == "choice":
        raw_options = item.options  # option_labels 已校验 list/tuple + 逐项非空白 str
        for label, raw in zip(option_labels(item), raw_options):
            segments.append(f"选项{label}：{_option_body(raw, iid)}")
    return _join_segments(segments)


# ---------- 卷面表面（题序语义与 omr_sheet/paper_layout/mm_ingest 一致） ----------

def _bank_index(bank) -> dict:
    items_fn = getattr(bank, "items", None)
    if not callable(items_fn):
        raise TTSError("bank must expose items()")
    try:
        seq = items_fn()
        iterator = iter(seq)
    except TypeError:
        raise TTSError("bank.items() must return an iterable") from None
    index = {}
    for it in iterator:
        iid = getattr(it, "id", None)
        if not isinstance(iid, str) or not iid.strip():
            raise TTSError("bank item id must be a non-empty str")
        if iid in index:
            raise TTSError(f"duplicate item id in bank: {iid}")
        index[iid] = it
    return index


def _section_lists(paper) -> list:
    """paper.sections 规整化为 item_ids 列表的列表（空 -> paper.item_ids 单一隐式节）。"""
    raw_sections = getattr(paper, "sections", None)
    if not isinstance(raw_sections, (list, tuple)):
        raise TTSError("paper.sections must be a list")
    sec_list = list(raw_sections)
    if not sec_list:
        fallback_ids = getattr(paper, "item_ids", None)
        if not isinstance(fallback_ids, (list, tuple)):
            raise TTSError("paper.item_ids must be a list when sections is empty")
        sec_list = [{"item_ids": list(fallback_ids)}]
    out = []
    for sec in sec_list:
        if not isinstance(sec, dict):
            raise TTSError("paper.sections entries must be dicts")
        ids = sec.get("item_ids")
        if not isinstance(ids, (list, tuple)):
            raise TTSError(f"section {sec.get('kp_id', '')!r} item_ids must be a list")
        for iid in ids:
            if not isinstance(iid, str) or not iid.strip():
                raise TTSError(f"section item id must be non-empty str, got {iid!r}")
        out.append([str(iid) for iid in ids])
    return out


def _paper_items(paper, bank) -> list:
    """卷面表面校验 + 按卷面题序返回题目列表（校验顺序 V4->V5->V6->空卷门）。"""
    _require_str_attr(paper, "paper_id", "paper.paper_id")
    _require_str_attr(paper, "title", "paper.title")
    index = _bank_index(bank)
    items = []
    for sec_ids in _section_lists(paper):
        for iid in sec_ids:
            item = index.get(iid)
            if item is None:
                raise TTSError(f"unknown item id in paper: {iid}")
            item_type = getattr(item, "item_type", None)
            if item_type not in ITEM_TYPES:
                raise TTSError(f"unknown item_type for {iid}: {item_type!r}")
            items.append(item)
    if not items:
        raise TTSError("empty paper: no questions to read")
    return items


# ---------- 合成 ----------

def _valid_audio(audio) -> bool:
    return isinstance(audio, bytes) and len(audio) > 0


def synthesize_item(item, tts, *, voice=DEFAULT_VOICE, cache=None) -> ItemAudio:
    """单题合成：朗读文本 -> tts 恰好一次（缓存键 (item.id, voice) 命中则零次）。

    守卫顺序 V1 voice -> V2 tts 表面 -> V3 cache 表面 -> V4 item/文本（命中与否都
    校验并重建 text）；非法音频（非 bytes/空）不回填；tts 异常原样传播。
    """
    _non_blank_str(voice, "voice")              # V1
    tts_fn = _require_tts(tts)                  # V2
    store = _require_cache(cache)               # V3
    text = build_reading_text(item)             # V4
    key = (item.id, voice)
    if key in store:                            # 缓存命中：零次出网
        audio = store[key]
        if not _valid_audio(audio):
            raise TTSError(
                f"cached audio for {key!r} must be non-empty bytes, "
                f"got {type(audio).__name__}")
        return ItemAudio(item_id=item.id, voice=voice, text=text,
                         audio=audio, from_cache=True)
    audio = tts_fn(text, voice=voice, response_format=AUDIO_FORMAT)  # 恰好一次出网
    if not _valid_audio(audio):
        raise TTSError(
            f"tts returned non-audio ({type(audio).__name__}); nothing cached")
    store[key] = audio
    return ItemAudio(item_id=item.id, voice=voice, text=text,
                     audio=audio, from_cache=False)


def read_paper(paper, bank, tts, *, voice=DEFAULT_VOICE, cache=None) -> list:
    """整卷读题：卷面题序逐题合成（共享同一 cache），返回按卷面题序的 ItemAudio 列表。

    守卫顺序 V1 voice -> V2 tts -> V3 cache -> V4 paper 表面 -> V5 bank 表面 ->
    V6 逐题 item_type + 空卷门 -> V7 逐题朗读文本全量校验；任一失败零 tts 调用。
    """
    _non_blank_str(voice, "voice")              # V1
    _require_tts(tts)                           # V2
    _require_cache(cache)                       # V3
    items = _paper_items(paper, bank)           # V4-V6
    for it in items:                            # V7 全量校验（纯函数、零出网）
        build_reading_text(it)
    shared = {} if cache is None else cache     # 本调用内共享缓存
    return [synthesize_item(it, tts, voice=voice, cache=shared) for it in items]
