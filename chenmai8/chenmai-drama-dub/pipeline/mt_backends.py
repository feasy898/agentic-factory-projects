"""M6 翻译后端抽象（mt_backends）—— 三实现共用同一 ``translate()`` 接口。

规划 §4 M6 / §9：本地翻译主后端（mt-core，GPU :9004 服务）为主，
OpenAI 兼容 API 抽象层兜底（key 从环境变量注入，不落盘），离线词典 mock 供测试。

三实现（同一接口 :meth:`MTBackend.translate`，返回 :class:`MTDraft` 列表）：
  - :class:`LocalMtBackend`  ``mt-core``  GPU :9004 服务的 HTTP 客户端
    （服务部署归 T12 批：本批先交付客户端 + gpu-services/mt 部署脚本；
    客户端/服务请求-响应口径见 :meth:`LocalMtBackend.translate` docstring，
    eval 中用本地桩 HTTP 服务验证了 payload 契约）。
  - :class:`ApiMtBackend`    ``mt-api``   OpenAI 兼容 chat.completions；
    env：``MT_API_BASE`` / ``MT_API_KEY`` / ``MT_API_MODEL``（缺失在构造时即报错，
    绝无默认 key；本仓任何文件不落 key 字面量）。
  - :class:`MockMtBackend`   ``mock``     内置离线小词典 + 规则变体（测试用，
    全离线零网络；同输入恒同输出）。

上下文注入口径（与规划 §4 M6 ② 一致）: 全剧角色卡（:attr:`MTContext.cast_summary`）
+ 术语表（:attr:`MTContext.terms`）+ 前文 ≤2 句 / 后文 ≤2 句 + 本句时长预算
（:attr:`MTContext.budget`）。mock 后端将收到的完整上下文存入
:attr:`MockMtBackend.last_context`，供 eval 断言「角色卡注入」。

命名纪律：本文件为公开文本，不出现任何上游项目/模型名（scripts/gate_b0 口径）。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import httpx

__all__ = [
    "MTContext",
    "MTDraft",
    "MTBackend",
    "MtBackendError",
    "MtServiceError",
    "MT_API_ENV",
    "LocalMtBackend",
    "ApiMtBackend",
    "MockMtBackend",
    "make_backend",
]


class MtBackendError(RuntimeError):
    """翻译后端调用失败（配置缺失/网络/HTTP/解析失败的统一异常）。"""


class MtServiceError(MtBackendError):
    """GPU mt 服务（:9004）调用失败（网络/HTTP/业务错误均归一为该异常）。"""


#: API 兜底后端的环境变量名（构造缺失时报错并提示这三个名字）
MT_API_ENV: dict[str, str] = {
    "base": "MT_API_BASE",
    "key": "MT_API_KEY",
    "model": "MT_API_MODEL",
}


# ---------------------------------------------------------------------------
# 上下文与候选草稿
# ---------------------------------------------------------------------------

@dataclass
class MTContext:
    """喂给每个候选翻译的结构化上下文（规划 §4 M6 ②）。

    ``cast_summary`` 为角色卡的纯文本摘要（整集一次生成，逐句复用）；
    ``terms`` 源术语→目标语译法（角色名/专名，来自 C3 terms + 术语种子）；
    ``prev_texts`` / ``next_texts`` 为紧邻前/后句（≤2 句；前文优先取已定稿译文）；
    ``budget`` = (orig_dur, lo, hi) 秒，仅作提示与候选伸缩参考。
    """

    tgt_lang: str
    cast_summary: str = ""
    terms: dict[str, str] = field(default_factory=dict)
    prev_texts: list[str] = field(default_factory=list)
    next_texts: list[str] = field(default_factory=list)
    budget: Optional[tuple[float, float, float]] = None


@dataclass
class MTDraft:
    """后端产出的候选译文草稿（时长估算 syl/est_dur 由 M6 统一补算后落 C4）。"""

    text: str
    q: float
    src: str


class MTBackend(Protocol):
    """翻译后端统一接口（规划 §4 M6：同一接口 ``MTBackend.translate()``）。"""

    name: str

    def translate(
        self, text: str, ctx: MTContext, *, n_candidates: int = 4
    ) -> list[MTDraft]:
        """返回 1..n_candidates 个候选（长短变体），q∈[0,1] 为后端自估质量分。"""
        ...  # pragma: no cover


def make_backend(name: str, **kw: Any) -> MTBackend:
    """按名构造后端：``local`` | ``api`` | ``mock``（未知名字报 :class:`MtBackendError`）。"""
    if name == "local":
        return LocalMtBackend(**kw)
    if name == "api":
        return ApiMtBackend(**kw)
    if name == "mock":
        return MockMtBackend(**kw)
    raise MtBackendError(f"未知翻译后端: {name!r}（可选 local|api|mock）")


# ---------------------------------------------------------------------------
# local —— GPU :9004 mt 服务客户端（服务部署归 T12 批）
# ---------------------------------------------------------------------------

class LocalMtBackend:
    """mt-core（GPU :9004）客户端：本批交付，服务端骨架见 ``gpu-services/mt/service.py``。

    请求-响应口径（T12 服务端按此实现；eval 已用桩服务验证 payload）::

        POST /v1/translate
          {"text": "...", "tgt": "en", "cast": "<角色卡文本>", "terms": {"程氏": "…"},
           "prev": ["上上句", "上句"], "next": ["下句"],
           "budget": {"orig_dur": 1.62, "lo": 1.46, "hi": 1.78}, "n_candidates": 4}
        → 200 {"candidates": [{"text": "...", "q": 0.88}, ...],
               "timing": {"total_s": 1.2}, "versions": {...}}

    地址解析：显式参数 → env ``M6_MT_URL`` → 默认 ``http://127.0.0.1:9004``
    （GPU 服务只监听其 127.0.0.1，本机经 ops/tunnel_gpu.sh 隧道访问，端口 9004）。
    """

    name = "mt-core"

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 600.0,
        retries: int = 2,
        retry_wait_s: float = 2.0,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("M6_MT_URL", "http://127.0.0.1:9004")
        ).rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.retry_wait_s = retry_wait_s

    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        """GET /health —— 模型装载状态（服务不可达抛 :class:`MtServiceError`）。"""
        return self._request("GET", "/health").json()

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.request(method, f"{self.base_url}{path}", **kw)
                if resp.status_code >= 400:
                    raise MtServiceError(
                        f"HTTP {resp.status_code} {path}: {resp.text[:400]}"
                    )
                return resp
            except (httpx.HTTPError, MtServiceError) as exc:
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(self.retry_wait_s)
        raise MtServiceError(
            f"{method} {self.base_url}{path} 失败（重试 {self.retries} 次后）: {last_exc}"
        )

    # ------------------------------------------------------------------
    def translate(
        self, text: str, ctx: MTContext, *, n_candidates: int = 4
    ) -> list[MTDraft]:
        """POST /v1/translate → 候选列表（q 服务端自估；缺失时按序衰减兜底）。"""
        budget = (
            {"orig_dur": round(ctx.budget[0], 3),
             "lo": round(ctx.budget[1], 3),
             "hi": round(ctx.budget[2], 3)}
            if ctx.budget
            else None
        )
        payload = {
            "text": text,
            "tgt": ctx.tgt_lang,
            "cast": ctx.cast_summary,
            "terms": ctx.terms,
            "prev": list(ctx.prev_texts)[:2],
            "next": list(ctx.next_texts)[:2],
            "budget": budget,
            "n_candidates": int(n_candidates),
        }
        data = self._request("POST", "/v1/translate", json=payload).json()
        raw = data.get("candidates") or []
        drafts: list[MTDraft] = []
        for i, c in enumerate(raw):
            t = str(c.get("text") or "").strip()
            if not t:
                continue
            q = c.get("q")
            drafts.append(
                MTDraft(text=t, q=0.8 if q is None else float(q), src=self.name)
            )
        if not drafts:
            raise MtServiceError(f"mt 服务返回空候选: {str(data)[:200]}")
        return drafts[:n_candidates]


# ---------------------------------------------------------------------------
# api —— OpenAI 兼容 chat.completions 兜底（env 驱动，key 不落盘）
# ---------------------------------------------------------------------------

class ApiMtBackend:
    """OpenAI 兼容 API 兜底后端。env：``MT_API_BASE`` / ``MT_API_KEY`` / ``MT_API_MODEL``。

    构造即读取 env；缺任一项抛 :class:`MtBackendError`（提示变量名，不猜默认值）。
    单次请求要求模型返回 JSON 数组的 n 个长短候选；解析失败降级为把回复
    整体当单候选（q=0.8）。本类不做任何重试退避之外的网络魔法。
    """

    name = "mt-api"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        *,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get(MT_API_ENV["base"]) or "").rstrip("/")
        self.api_key = api_key or os.environ.get(MT_API_ENV["key"]) or ""
        self.model = model or os.environ.get(MT_API_ENV["model"]) or ""
        missing = [
            MT_API_ENV[k]
            for k, v in (("base", self.base_url), ("key", self.api_key), ("model", self.model))
            if not v
        ]
        if missing:
            raise MtBackendError(
                f"API 兜底后端缺环境变量: {', '.join(missing)}"
                "（key 由主会话注入 env，不落盘；离线测试请用 --backend mock）"
            )
        self.timeout = timeout

    # ------------------------------------------------------------------
    @staticmethod
    def _system_prompt(ctx: MTContext, n: int) -> str:
        lang_name = {"en": "英语", "es": "西语", "ar": "阿语"}.get(ctx.tgt_lang, ctx.tgt_lang)
        budget = ""
        if ctx.budget:
            budget = f"目标时长预算 {ctx.budget[1]:.2f}–{ctx.budget[2]:.2f} 秒（可念读、口语化）。"
        parts = [
            f"你是短剧配音翻译。把中文台词译成{lang_name}，口语、可念读、无注释。{budget}",
            f"输出 JSON 数组：{n} 个长短不同的候选（从紧凑到完整），按质量从高到低排序，"
            '形如 [{"text":"...","q":0.9}, ...]，只输出 JSON。',
        ]
        if ctx.cast_summary:
            parts.append(f"[背景信息]\n{ctx.cast_summary}")
        if ctx.terms:
            terms = "；".join(f"{s}→{t}" for s, t in ctx.terms.items())
            parts.append(f"[术语表（必须采用）]\n{terms}")
        return "\n".join(parts)

    def _chat(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise MtBackendError(f"mt-api 请求失败: {exc}") from exc
        if resp.status_code >= 400:
            raise MtBackendError(f"mt-api HTTP {resp.status_code}: {resp.text[:300]}")
        try:
            return str(resp.json()["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError) as exc:
            raise MtBackendError(f"mt-api 响应缺 choices: {resp.text[:300]}") from exc

    def translate(
        self, text: str, ctx: MTContext, *, n_candidates: int = 4
    ) -> list[MTDraft]:
        prev = "\n".join(ctx.prev_texts[-2:])
        nxt = "\n".join(ctx.next_texts[:2])
        user = f"[前文]\n{prev}\n[待翻译]\n{text}\n[后文]\n{nxt}"
        raw = self._chat(self._system_prompt(ctx, n_candidates), user)
        drafts: list[MTDraft] = []
        m = re.search(r"\[.*\]", raw, re.DOTALL)  # 容忍 markdown 围栏/前后杂讯
        if m:
            try:
                arr = json.loads(m.group(0))
                for c in arr if isinstance(arr, list) else []:
                    if isinstance(c, dict) and str(c.get("text") or "").strip():
                        q = c.get("q")
                        drafts.append(MTDraft(
                            text=str(c["text"]).strip(),
                            q=0.8 if q is None else max(0.0, min(1.0, float(q))),
                            src=self.name,
                        ))
                    elif isinstance(c, str) and c.strip():
                        drafts.append(MTDraft(text=c.strip(), q=0.8, src=self.name))
            except ValueError:
                drafts = []
        if not drafts:
            stripped = raw.strip()
            if not stripped:
                raise MtBackendError("mt-api 返回空内容")
            drafts = [MTDraft(text=stripped, q=0.8, src=self.name)]
        return drafts[:n_candidates]


# ---------------------------------------------------------------------------
# mock —— 离线小词典 + 规则变体（测试专用；同输入恒同输出，零网络零模型）
# ---------------------------------------------------------------------------

#: 内置离线词典：词元 → 语种 → 译法。仅覆盖演示语料，丢词保原样并在 q 中罚分。
#: 密度口径：en 译法按 ≈0.9 音节/汉字 标定（占位速率表 3.8 syl/s × 演示语料
#: 0.24s/汉字 的交付语速），使「全量变体」多数落进 ±10% 预算窗 —— 这让
#: in-budget 排序/命中率在离线 eval 里可复现（真实命中率口径归 local/api 后端）。
#: 注意：角色名/专名的译法不在此表 —— 一律走 ctx.terms（eval 据此断言术语注入）。
_MOCK_LEXICON: dict[str, dict[str, str]] = {
    "你到底想怎么样": {"en": "what is it that you want", "es": "qué es lo que quiere", "ar": "ما الذي تريده"},
    "怎么样": {"en": "what", "es": "qué", "ar": "ما"},
    "你": {"en": "you", "es": "usted", "ar": "أنت"},
    "我": {"en": "I", "es": "yo", "ar": "أنا"},
    "他": {"en": "he", "es": "él", "ar": "هو"},
    "把话说清楚": {"en": "say it out loud", "es": "dígamelo en voz alta", "ar": "قلها بصوت عال"},
    "三年了": {"en": "three years now", "es": "ya van tres años", "ar": "مرت ثلاث سنوات"},
    "程氏": {"en": "the Cheng family", "es": "la familia Cheng", "ar": "عائلة تشنغ"},
    "项目": {"en": "project", "es": "el proyecto", "ar": "المشروع"},
    "老城": {"en": "old town", "es": "el casco antiguo", "ar": "المدينة القديمة"},
    "基地": {"en": "base", "es": "la base", "ar": "القاعدة"},
    "哪一样": {"en": "which one", "es": "cuál de ellas", "ar": "أيها"},
    "不是": {"en": "was not", "es": "no fue", "ar": "لم يكن"},
    "亲手": {"en": "with my own hands", "es": "con mis propias manos", "ar": "بيدي"},
    "做起来": {"en": "built up", "es": "levanté", "ar": "بنيت"},
    "那你": {"en": "then you", "es": "entonces usted", "ar": "إذن أنت"},
    "就可以": {"en": "can just", "es": "puede simplemente", "ar": "تستطيع فقط"},
    "这样对我": {"en": "treat me like this", "es": "tratarme así", "ar": "تتعامل معي هكذا"},
    "我以为": {"en": "I thought", "es": "pensé que", "ar": "ظننت أن"},
    "你至少": {"en": "you at least", "es": "usted al menos", "ar": "أنت على الأقل"},
    "会": {"en": "would", "es": "iba a", "ar": "سوف"},
    "信我": {"en": "trust me", "es": "confiar en mí", "ar": "تثق بي"},
    "为什么": {"en": "tell me why", "es": "diga por qué", "ar": "قل لي لماذا"},
    "要走": {"en": "must you leave", "es": "debe irse", "ar": "يجب أن تذهب"},
    "海南": {"en": "Hainan", "es": "Hainan", "ar": "هاينان"},
    "孤岛": {"en": "island", "es": "una isla", "ar": "جزيرة"},
    "也": {"en": "still", "es": "todavía", "ar": "لا يزال"},
    "有": {"en": "has", "es": "tiene", "ar": "فيها"},
    "明月": {"en": "the bright moon", "es": "la luna brillante", "ar": "القمر المضيء"},
    "预算": {"en": "budget", "es": "el presupuesto", "ar": "الميزانية"},
    "超了": {"en": "is over", "es": "se ha pasado", "ar": "قد تجاوزتها"},
    "的": {"en": "", "es": "", "ar": ""},  # 结构助词：mock 不译（清空）
    "了": {"en": "", "es": "", "ar": ""},
    "吗": {"en": "", "es": "", "ar": ""},
    "呢": {"en": "", "es": "", "ar": ""},
}

#: mock 切分句子的终止符（保留在原文与译文里，用于计算变体长度差）
_MOCK_CLAUSE_END = "。！？；!?;"
_HAN = re.compile(r"[\u4e00-\u9fff]+")


class MockMtBackend:
    """离线词典后端（eval 全离线通道）。

    流程：词典∪术语 按最长匹配切分原文 → 逐段翻译拼接 → 按句号/问号等
    子句边界生成「全量 → 递减」的长短变体（≤n_candidates，去重）。
    覆盖率不足时 q 罚分（0.9 基线 - 0.4×未覆盖字符占比 - 0.06×变体序）。
    收到的完整上下文存 :attr:`last_context`（eval 断言角色卡注入的探针）。
    """

    name = "mock"

    def __init__(self) -> None:
        self.last_context: Optional[MTContext] = None
        self.last_terms_applied: dict[str, str] = {}

    # ------------------------------------------------------------------
    def _lexicon(self, ctx: MTContext) -> dict[str, str]:
        """词典 + 术语（术语优先：先放词典再 update 术语，最长匹配时术语更长更优先）。"""
        lex = {src: vals.get(ctx.tgt_lang, "") for src, vals in _MOCK_LEXICON.items()}
        lex.update({s: t for s, t in ctx.terms.items() if s})
        return lex

    def _segment(
        self, text: str, lex: dict[str, str]
    ) -> list[tuple[str, str, bool]]:
        """最长匹配贪心切分。返回 (片段, 译法, 是否命中词表) 三元组；

        未命中的 Han 字进缓冲、译法=原样（计入未覆盖罚分）；非 Han 字符
        （拉丁/标点）原样保留。"""
        out: list[tuple[str, str, bool]] = []
        i, n = 0, len(text)
        buf = ""
        while i < n:
            ch = text[i]
            if not _HAN.match(ch):
                buf += ch
                i += 1
                continue
            match = None
            for j in range(min(n, i + 8), i, -1):  # 词表最长 4 字，取 8 上限保险
                seg = text[i:j]
                if seg in lex:
                    match = (seg, lex[seg])
                    break
            if match:
                if buf:
                    out.append((buf, buf, False))  # 非 Han 缓冲原样保留
                    buf = ""
                out.append((match[0], match[1], True))
                i += len(match[0])
            else:
                buf += ch
                i += 1
        if buf:
            out.append((buf, buf, False))
        return out

    def _render(self, pieces: list[tuple[str, str, bool]], lang: str) -> str:
        if lang in {"zh", "yue", "ja"}:
            return "".join(t for _, t, _ in pieces)
        # 拉丁/阿语：译段以空格连接（空译法跳过），随后清标点前空格
        text = " ".join(t for _, t, _ in pieces if t.strip())
        text = re.sub(r"\s+([,.!?;:،؟。！？；：，、…])", r"\1", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()

    # ------------------------------------------------------------------
    def translate(
        self, text: str, ctx: MTContext, *, n_candidates: int = 4
    ) -> list[MTDraft]:
        self.last_context = ctx
        lex = self._lexicon(ctx)
        self.last_terms_applied = dict(ctx.terms)

        pieces = self._segment(text, lex)
        covered = sum(len(s) for s, _, hit in pieces if hit)
        han_total = sum(len(m.group()) for m in _HAN.finditer(text))
        unknown_ratio = 0.0 if han_total == 0 else 1.0 - covered / han_total
        base_q = max(0.5, 0.9 - 0.4 * unknown_ratio)

        # 子句切分（终止符并入前句），逐句翻译后做「全量→递减」变体
        clauses: list[list[tuple[str, str, bool]]] = [[]]
        for piece in pieces:
            clauses[-1].append(piece)
            if piece[0] and piece[0][-1] in _MOCK_CLAUSE_END:
                clauses.append([])
        if not clauses[-1]:
            clauses.pop()
        full = self._render([p for cl in clauses for p in cl], ctx.tgt_lang)
        variants = [full]
        for k in range(len(clauses) - 1, 0, -1):  # 丢尾部 k 个子句 → 更短变体
            variants.append(self._render([p for cl in clauses[:k] for p in cl], ctx.tgt_lang))
        # 单子句兜底：去尾词的压缩变体（≥3 词时才有意义）
        if len(clauses) == 1:
            words = full.split()
            if len(words) >= 3:
                variants.append(" ".join(words[:-1]))
        seen: set[str] = set()
        uniq = [v for v in variants if v and not (v in seen or seen.add(v))]
        return [
            MTDraft(text=v, q=max(0.5, base_q - 0.06 * i), src=self.name)
            for i, v in enumerate(uniq[:max(1, n_candidates)])
        ]
