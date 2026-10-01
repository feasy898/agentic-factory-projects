"""注入检测模式词表与位置启发（T4.2 语义层第一档：模式词表 + 位置启发）。

三层信号（开发指令 §6 M2：间接注入 = 文档内嵌指令特征，模式词表 + 位置启发）：

- ``STRONG``  强特征：指令覆盖/角色接管/提示词窃取/对用户隐匿——任意位置命中即判；
- ``EXFIL``   外发链：工具调用诱导 + 明确外发目的地（URL/外部渠道）——任意位置命中即判；
- ``WEAK``    弱特征：新任务接管标记、对话模板标记、模式开关、面向模型的嵌入式
  呼叫——须通过位置启发（:func:`corroborated`）佐证才判，压误拦。

反误拦护栏：**否定前缀守卫**（:func:`is_negated`）——命中点前方近邻
（``NEGATION_WINDOW`` 字符内）出现「禁止/严禁/不得/请勿/不要/避免/防止…」等
禁令性措辞时该命中不计：制度文档的「严禁将内部材料上传至外部网盘」「请勿忽略
上述材料要求」是合规表述，不是注入指令。

词表文件 ``config/injection_terms.txt``：行格式 ``<class>|<regex>``（# 注释；
class ∈ STRONG/EXFIL/WEAK），缺失/为空回退本文件内置默认（两者内容保持一致，
同密级词表惯例）。自定义正则非法时跳过该行并记日志，不中断加载。
"""
from __future__ import annotations

import re
from pathlib import Path

from common.config import REPO_ROOT
from common.logs import get_logger

log = get_logger(__name__)

#: 词表默认路径（可配置词表）
INJECTION_TERMS_PATH = REPO_ROOT / "config" / "injection_terms.txt"

#: 信号档位
KIND_STRONG = "STRONG"
KIND_EXFIL = "EXFIL"
KIND_WEAK = "WEAK"
KINDS: tuple[str, ...] = (KIND_STRONG, KIND_EXFIL, KIND_WEAK)

#: 否定前缀守卫：命中点前方该窗口内出现禁令措辞 → 命中不计
NEGATION_WINDOW = 8
_NEGATION_RE = re.compile(
    r"(?:禁止|严禁|不得|切勿|请勿|不要|避免|防止|无需|无须|不可|不能|勿|别)"
)

#: 弱特征位置佐证：命中点位于全文该深度比例之后即视为「文档深处的嵌入式指令」
WEAK_DEPTH_MIN = 0.5

#: 位置佐证：公文收束用语之后（落款后埋注是典型文档埋注位）
_CLOSING_MARKERS: tuple[str, ...] = (
    "特此通知", "特此报告", "特此批复", "特此决定", "特此证明", "特此公告", "此致",
)
_CLOSING_LOOKBACK = 40

#: 位置佐证：行首标记（指令：/备注：/【提示】…开头行内的弱特征视为佐证成立）
_LINE_MARKER_RE = re.compile(r"^[（\[【]?(?:指令|备注|提示|说明|注意|AI|系统|嵌入|附录|附|以下)")

#: 括注块（【】「」『』）内嵌指令佐证：命中点前方同类括号未闭合即视为括注内
_BRACKET_PAIRS: tuple[tuple[str, str], ...] = (("【", "】"), ("「", "」"), ("『", "』"))

#: 内置默认词表（与 config/injection_terms.txt 内容一致）
DEFAULT_PATTERNS: tuple[tuple[str, str], ...] = (
    # ── STRONG：指令覆盖 / 上下文清空 ──────────────────────────────
    (KIND_STRONG, r"(?:忽略|无视|抛开|不予理会|置之不理)(?:掉)?"
                  r"(?:上面|上方|以上|上述|之前|先前|前面|此前|历史)?"
                  r"[^，。；！？\n]{0,4}?(?:的)?"
                  r"(?:所有|全部|一切|先前的?)?(?:指令|指示|要求|规则|约束|设定|提示词?|系统提示)"),
    # ── STRONG：安全/限制解除 ─────────────────────────────────────
    (KIND_STRONG, r"(?:解除|关闭|屏蔽|绕过|突破|无视|忽略)"
                  r"(?:上面|上方|以上|上述|之前|先前|前面|此前)?"
                  r"(?:你的|您的|所有|全部|一切|任何)*"
                  r"(?:安全|内容安全|道德|伦理|法律|平台)?(?:的)?"
                  r"(?:审查|审核|准则|限制|约束|护栏|过滤|防线)"),
    # ── STRONG：时间性角色接管 ────────────────────────────────────
    (KIND_STRONG, r"(?:从现在开始|从现在起|现在开始|现在起|此刻起|从这一刻起|接下来)[，,]?"
                  r"(?:你|请你?要?|你将)?(?:扮演|充当|作为|变成|化身为?|只回应?|只回复|只输出)"),
    (KIND_STRONG, r"(?:你现在是?|现在你是|从现在开始你是|从现在起你是|接下来你是|"
                  r"你将扮演|请你扮演|请扮演)"),
    (KIND_STRONG, r"(?:扮演|充当|化身为?)\s*(?:一个|一名)?"
                  r"(?:没有|不受|毫无|不受任何|没有任何)(?:道德|伦理|规则|法律|限制|约束|审查)"),
    (KIND_STRONG, r"(?:你是|你就是|你当|你来做)\s*(?:一个|一名)?"
                  r"(?:毫无|没有|不受|不受任何|没有任何)(?:道德|伦理|规则|法律|限制|约束|审查)"),
    # ── STRONG：系统提示词窃取 ────────────────────────────────────
    (KIND_STRONG, r"(?:输出|打印|重复|复述|显示|泄露|透露|回显|逐字)"
                  r"(?:一下|一遍|你的|您的|你收到的|您收到的|收到的|全部|完整|所有)?(?:的)?"
                  r"(?:系统提示|系统指令|初始指令|初始设定|人设|设定词|提示词|开场白|预设指令)"),
    # ── STRONG：对用户隐匿（向用户隐瞒指令/要求的存在）────────────
    (KIND_STRONG, r"(?:不要|别|切勿|不准)(?:向|告诉|告知|让|对)"
                  r"(?:用户|对方|任何人|他们|使用者)(?:透露|提及|说明|展示|解释|知道|提起|暴露)"),
    # ── STRONG：英文直球（大小写不敏感）───────────────────────────
    (KIND_STRONG, r"(?i)(?:reveal|print|show|repeat|output|display)\s+(?:me\s+)?"
                  r"(?:your|the)?\s*(?:initial\s+|hidden\s+|full\s+)?(?:system\s+)?"
                  r"(?:prompt|instructions?|rules)"),
    (KIND_STRONG, r"(?i)(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|your\s+)*"
                  r"(?:previous|prior|above|earlier)\s+(?:instructions?|prompts?|rules)"),
    # ── EXFIL：外发目的地为明文 URL ───────────────────────────────
    (KIND_EXFIL, r"(?:发送|上传|提交|转发|外传|传输|泄露)(?:所有|全部|一份|本页|上述|其中)?(?:的)?"
                 r"(?:到|至|给)\s*(?:https?://|ftps?://|www\.|hxxp://)"),
    # ── EXFIL：外发目的地为外部渠道 ───────────────────────────────
    (KIND_EXFIL, r"(?:发送|上传|回传|外传|传输|泄露)(?:到|至)"
                 r"(?:外部|远程|陌生|第三方|境外|私人|个人)(?:的)?"
                 r"(?:服务器|网站|邮箱|网盘|平台|账户|账号|域名|聊天软件)"),
    # ── EXFIL：工具调用诱导 + 外发（调用…工具…把…发送到<外部目的地>）──
    (KIND_EXFIL, r"(?:调用|使用|执行|运行|发起)(?:那?个)?(?:你?的)?"
                 r"(?:文件|邮件|短信|数据库|联网|网络|搜索|HTTP|http)?(?:工具|函数|接口|命令|脚本)"
                 r".{0,20}?(?:把|将).{0,24}?(?:发送|上传|转发|外传|泄露)"
                 r"(?:到|给|至)\s*(?:https?|ftp|www\.|外部|远程|陌生|私人|第三方|境外|我的|攻击者|hxxp)"),
    # ── EXFIL：隐匿动作（背着用户偷偷调用/上传）───────────────────
    (KIND_EXFIL, r"(?:偷偷|悄悄|私下|暗中|瞒着用户|背着用户)(?:地)?"
                 r"(?:调用|执行|运行|发送|上传|外传)"),
    # ── EXFIL：内容走私（在回复中嵌入指定内容）────────────────────
    (KIND_EXFIL, r"(?:在|于)(?:你的|您的|本次)?(?:回答|回复|答复|响应|输出)(?:内容)?(?:中|里)"
                 r"(?:包含|附上|带上|嵌入|加入|写入|夹带|添加)"
                 r"(?:以下|如下|这段|这份|下面|这句)?(?:的)?"
                 r"(?:内容|文本|文字|代码|指令|链接|网址|话术|结论)"),
    # ── WEAK：新任务/新指令接管标记（需位置佐证）──────────────────
    (KIND_WEAK, r"(?:新|真正|实际)(?:的)?(?:系统)?(?:任务|指令|目标|角色设定)"
                r"(?:是|如下|：|:)\s*(?:你|请|从现在|以下|现在)"),
    # ── WEAK：对话模板标记被粘贴进正文（需位置佐证）────────────────
    (KIND_WEAK, r"<\|[a-zA-Z_]{2,20}\|>|\[(?:INST|/INST|SYS|/SYS|SYSTEM)\]"),
    # ── WEAK：模式开关（需位置佐证）──────────────────────────────
    (KIND_WEAK, r"(?:进入|激活|开启|启动)(?:你?的)?(?:越狱|开发者|上帝|无限制|自由|不受限)模式"),
    # ── WEAK：隐匿存在的弱式表述（需位置佐证）──────────────────────
    (KIND_WEAK, r"(?:不要|别|偷偷|悄悄)(?:提及|承认|透露|提起)"
                r"(?:这[份段条]?|上述|本段|上面|这条)?(?:的)?(?:指令|提示词?|规则|设定|要求)的存在"),
    # ── WEAK：面向模型的嵌入式呼叫（AI请注意：…）─────────────────
    (KIND_WEAK, r"(?:AI|人工智能|智能助手|对话助手)(?:请注意|请务必|请执行|请遵守|必读|读我|专用指令|优先指令)"),
    # ── WEAK：写给模型的备忘（给大模型的指令：…）──────────────────
    (KIND_WEAK, r"(?:给|致|写给)(?:AI|人工智能|大模型|语言模型|对话模型)(?:的)?"
                r"(?:指令|提示|备注|说明|批注)"),
    # ── WEAK：伪系统消息声明（以下是新的系统级指令…）───────────────
    (KIND_WEAK, r"(?:以下是?|这是|上面是?)(?:新的|真正的)?(?:系统消息|系统级指令|系统设定|开发者消息)"),
)

_PATTERNS_CACHE: tuple[tuple[str, re.Pattern[str]], ...] | None = None


# ── 词表加载（同一模式：文件缺失/为空回退内置；测试可显式注入）─────────


def load_injection_patterns(
    path: str | Path | None = None,
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """加载注入模式词表：行格式 ``<class>|<regex>``、# 注释；缺失/为空回退内置。

    非法行（档位未知 / 正则编译失败）跳过并记 warning，不中断加载——
    词表是运营可改面，坏一行不能拖垮识别。
    """
    p = Path(path) if path else INJECTION_TERMS_PATH
    patterns: list[tuple[str, re.Pattern[str]]] = []
    if p.exists():
        for lineno, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            kind, _, expr = line.partition("|")
            kind = kind.strip().upper()
            if kind not in KINDS or not expr.strip():
                log.warning("injection_patterns.line_skipped",
                            extra={"path": str(p), "lineno": lineno, "kind": kind})
                continue
            try:
                patterns.append((kind, re.compile(expr.strip())))
            except re.error as exc:
                log.warning("injection_patterns.line_invalid",
                            extra={"path": str(p), "lineno": lineno, "error": str(exc)})
    if not patterns:
        patterns = [(kind, re.compile(expr)) for kind, expr in DEFAULT_PATTERNS]
    return tuple(patterns)


def get_injection_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """进程级缓存的注入模式词表（首次调用加载 config/injection_terms.txt）。"""
    global _PATTERNS_CACHE
    if _PATTERNS_CACHE is None:
        _PATTERNS_CACHE = load_injection_patterns()
    return _PATTERNS_CACHE


def set_injection_patterns(
    patterns: tuple[tuple[str, re.Pattern[str]], ...] | None,
) -> None:
    """测试/运维显式注入词表（绕过文件；传 None/空恢复内置默认）。"""
    global _PATTERNS_CACHE
    _PATTERNS_CACHE = patterns or tuple(
        (kind, re.compile(expr)) for kind, expr in DEFAULT_PATTERNS
    )


# ── 反误拦护栏与位置启发 ───────────────────────────────────────────


def is_negated(text: str, start: int) -> bool:
    """否定前缀守卫：命中点前方近邻出现禁令性措辞 → True（该命中不计）。"""
    window = text[max(0, start - NEGATION_WINDOW):start]
    return bool(_NEGATION_RE.search(window))


def corroborated(text: str, start: int) -> bool:
    """弱特征位置佐证：满足任一即视为「文档深处的嵌入式指令」。

    - 深度：命中点位于全文 ``WEAK_DEPTH_MIN`` 比例之后（正文深处/落款附近）；
    - 括注：命中点位于未闭合的 【】「」『』 括注块内；
    - 收束后：命中点前 ``_CLOSING_LOOKBACK`` 字符内出现公文收束用语（特此通知/此致…）；
    - 行首标记：命中点所在行以 指令/备注/提示/说明/注意/AI/系统/附录… 开头。
    """
    if not text:
        return False
    if start / len(text) >= WEAK_DEPTH_MIN:
        return True
    for opn, cls in _BRACKET_PAIRS:
        if text.count(opn, 0, start) > text.count(cls, 0, start):
            return True
    if any(m in text[max(0, start - _CLOSING_LOOKBACK):start] for m in _CLOSING_MARKERS):
        return True
    line_start = text.rfind("\n", 0, start) + 1
    return bool(_LINE_MARKER_RE.match(text[line_start:start]))
