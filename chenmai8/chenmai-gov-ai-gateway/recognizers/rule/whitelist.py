"""白名单（labels.md §7，M2 落地）：命中 → ``Finding.whitelisted=true`` → 不参与脱敏与路由。

四类候选（labels.md §7）与本模块落地的对应关系：

1. **热线/应急短号**（12345、110/119/120 等）——``is_hotline(normalized)``：
   结构化号码检测后按归一化值回查，命中则改写 whitelisted（号码形态永不参与脱敏）；
2. **单位座机号段**（单位配置）——``is_unit_landline(normalized)``：
   归一化座机号前缀匹配（如 0898-6763xxxx 总机段）→ whitelisted；
3. **公开文号**（``〔20XX〕N号`` 形态）——识别为 DOC_NUMBER 且默认 whitelisted
   （正则在 :mod:`recognizers.rule.detect`，本模块只管配置语义）；
4. **公开职务姓名**——``public_title_before(text, start)``：NER 层产出 PERSON 候选时，
   姓名前紧邻公开职务称谓（如「副县长」）→ 建议白名单豁免。规则层不产出 PERSON，
   本钩子在 NER 接入前为休眠路径（T1.2 预留接口，单测覆盖）。

配置：``config/whitelist.yaml``（缺文件/缺键回退内置默认）；:func:`get_whitelist`
进程级缓存，:func:`set_whitelist` 供测试显式注入。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from common.config import REPO_ROOT

#: 白名单配置路径
WHITELIST_CONFIG_PATH = REPO_ROOT / "config" / "whitelist.yaml"

#: 热线/应急短号默认（labels.md §7：12345、110/119/120；122/12395 为应急体系扩展）
DEFAULT_HOTLINE_NUMBERS: tuple[str, ...] = ("12345", "110", "119", "120", "122", "12395")

#: 单位座机号段默认（归一化形态：区号+局向；演示取值域为 0898-6763xxxx 总机段）
DEFAULT_UNIT_LANDLINE_PREFIXES: tuple[str, ...] = ("08986763",)

#: 公开职务称谓默认（仅职务称谓、不带姓名的公开活动表述；NER 层 PERSON 豁免钩子用）
DEFAULT_PUBLIC_TITLES: tuple[str, ...] = (
    "县委书记", "县长", "副县长", "县委副书记", "县委常委",
    "镇党委书记", "镇长", "副镇长", "局党组书记",
)

#: 称谓探针窗口：PERSON 候选起点向前看多少字符内出现公开称谓即豁免
PUBLIC_TITLE_WINDOW = 12


class Whitelist:
    """白名单词表（进程内只读视图；配置见 config/whitelist.yaml）。"""

    __slots__ = ("hotline", "unit_prefixes", "public_titles")

    def __init__(
        self,
        hotline: tuple[str, ...] = DEFAULT_HOTLINE_NUMBERS,
        unit_prefixes: tuple[str, ...] = DEFAULT_UNIT_LANDLINE_PREFIXES,
        public_titles: tuple[str, ...] = DEFAULT_PUBLIC_TITLES,
    ) -> None:
        self.hotline = frozenset(hotline)
        self.unit_prefixes = tuple(sorted(unit_prefixes, key=len, reverse=True))
        self.public_titles = tuple(sorted(set(public_titles), key=len, reverse=True))

    def is_hotline(self, normalized: str) -> bool:
        """热线/应急短号判定（按归一化值全等）。"""
        return normalized in self.hotline

    def is_unit_landline(self, normalized: str) -> bool:
        """单位座机号段判定（归一化座机号的前缀匹配；最长前缀优先语义）。"""
        return any(normalized.startswith(p) for p in self.unit_prefixes if p)

    def public_title_before(self, text: str, start: int,
                            window: int = PUBLIC_TITLE_WINDOW) -> str | None:
        """PERSON 白名单钩子：姓名候选起点紧邻的前缀是否为公开职务称谓。

        仅认可谓**紧贴**姓名候选起点（称谓结尾 == 姓名起点，窗口 ``window`` 字符），
        避免把「副县长Today考察张三」这类非修饰距离误豁免。返回命中的称谓
        （None = 无）；NER 层据此把该 PERSON 候选标记 whitelisted。
        """
        context = text[max(0, start - window):start]
        for title in self.public_titles:  # 长称谓优先，避免「县长」吃掉「副县长」
            if context.endswith(title):
                return title
        return None


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_whitelist(path: str | Path | None = None) -> Whitelist:
    """加载白名单配置（缺文件/缺键逐项回退内置默认）。"""
    data = _load_yaml(Path(path) if path else WHITELIST_CONFIG_PATH)
    hotline = data.get("hotline_numbers") or DEFAULT_HOTLINE_NUMBERS
    prefixes = data.get("unit_landline_prefixes") or DEFAULT_UNIT_LANDLINE_PREFIXES
    titles = data.get("public_titles") or DEFAULT_PUBLIC_TITLES
    return Whitelist(
        hotline=tuple(str(x) for x in hotline),
        unit_prefixes=tuple(str(x) for x in prefixes),
        public_titles=tuple(str(x) for x in titles),
    )


_WHITELIST_CACHE: Whitelist | None = None


def get_whitelist() -> Whitelist:
    """进程级缓存的白名单（首次调用加载 config/whitelist.yaml）。"""
    global _WHITELIST_CACHE
    if _WHITELIST_CACHE is None:
        _WHITELIST_CACHE = load_whitelist()
    return _WHITELIST_CACHE


def set_whitelist(wl: Whitelist) -> None:
    """测试/运维显式注入白名单（绕过文件）。"""
    global _WHITELIST_CACHE
    _WHITELIST_CACHE = wl
