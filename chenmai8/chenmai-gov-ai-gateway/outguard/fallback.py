"""拦截代答/拒答文案库（开发指令 §6 M5）：YAML 加载 + reason 模板回退 + 关键词代答。

- **拒答**：BLOCK 时按决定性 reason code 取模板（第一条 reasons 为决定性理由，
  §5.2）——密级→保密提示卡、注入→安全提示、输出复检→复检拦截提示；未配置的
  code 回落 ``block.default``。文案库 ``config/outguard_texts.yaml`` 是运营可改的
  权威副本；路径缺失/条目缺失时回落本模块内置默认（两者内容保持一致）。
- **代答**：MVP 为 关键词→固定口径问答（子串匹配，条目序即优先级，首个命中生效；
  如涉密载体借阅咨询→引导线下保密流程）。命中时把代答文案拼在拒答文案之后，
  随 403 message 同体下发（WebUI 渲染提示卡）。匹配输入是**脱敏后**的 prompt
  （占位符版本，无原文）——代答文案是 YAML 固定文本，原值零出场。
  P2 升级语义匹配（向量检索），``canned_answer`` 返回形状不变。

纯函数 + 无副作用加载：:func:`block_message`/:func:`canned_answer` 不改入参。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from outguard.models import CannedEntry, OutguardTexts
from routing.models import RouteDecision

#: 文案库默认路径（AppConfig.outguard_texts 的缺省值；相对路径按仓库根解析）
DEFAULT_TEXTS_PATH = "config/outguard_texts.yaml"

#: 兜底拒答文案（§5.6 错误语义默认口径；与 YAML block.default 保持一致）
DEFAULT_BLOCK_DEFAULT = "涉密/涉敏内容已拦截，请通过保密渠道办理或删除敏感标识后重试"

#: reason code → 拒答模板内置默认（与 YAML block.by_code 保持一致）
DEFAULT_BLOCK_BY_CODE: dict[str, str] = {
    # 密级标识命中（§5.2 R1）→ 保密提示卡
    "CLASSIFICATION_MARK": "您的提问包含密级标识或内部资料字样，已按保密要求拦截。"
                           "涉密事项请通过本单位保密渠道线下办理。",
    # 注入指令命中（§5.2 R2，规则/语义层）→ 安全提示
    "INJECTION": "检测到疑似提示注入指令，已拦截本次请求。"
                 "请勿在提交材料中嵌入操控模型行为的指令文本。",
    # 输出侧复检钩子命中（outguard.moderation，P1 起有非空判定）
    "OUTPUT_MODERATION": "回答内容未通过输出侧复检，已拦截本次响应。",
}

#: 代答条目内置默认（与 YAML canned 保持一致）：涉密事务咨询 → 引导线下流程
DEFAULT_CANNED: list[CannedEntry] = [
    CannedEntry(
        id="classified_consult",
        keywords=["借阅", "查阅流程", "定密", "解密", "保密委员会"],
        answer="涉密载体与内部资料的借阅、定密、解密事项，请携带工作证件"
               "经本单位保密部门按线下流程办理，本平台不受理涉密咨询。",
    ),
]


def default_texts() -> OutguardTexts:
    """内置默认文案库（YAML 缺失时的等价回落）。"""
    return OutguardTexts(
        block_default=DEFAULT_BLOCK_DEFAULT,
        block_by_code=dict(DEFAULT_BLOCK_BY_CODE),
        canned=[entry.model_copy(deep=True) for entry in DEFAULT_CANNED],
    )


def load_texts(path: str | Path | None = None) -> OutguardTexts:
    """加载文案库。

    - ``path=None`` 或文件不存在 → 内置默认（文案库缺失不致命，运营可后补）；
    - 文件存在 → YAML 解析；顶层非映射/类型非法 → ValueError（配置错误要响）；
      单条目缺键按键回落内置默认（运营只覆盖想改的部分）。
    """
    if path is None:
        return default_texts()
    p = Path(path)
    if not p.exists():
        return default_texts()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"outguard texts must be a mapping: {p}")
    block = data.get("block") or {}
    if not isinstance(block, dict):
        raise ValueError(f"outguard texts 'block' must be a mapping: {p}")
    canned_raw = data.get("canned") or []
    if not isinstance(canned_raw, list):
        raise ValueError(f"outguard texts 'canned' must be a list: {p}")
    by_code_raw = block.get("by_code") or {}
    if not isinstance(by_code_raw, dict):
        raise ValueError(f"outguard texts 'block.by_code' must be a mapping: {p}")
    return OutguardTexts(
        block_default=str(block.get("default") or DEFAULT_BLOCK_DEFAULT),
        block_by_code={str(k): str(v) for k, v in by_code_raw.items()},
        canned=[CannedEntry.model_validate(entry) for entry in canned_raw],
    )


def canned_answer(texts: OutguardTexts, text: str) -> str | None:
    """关键词代答（MVP 子串匹配）：首个命中的条目文案；无命中返回 None。"""
    if not text:
        return None
    for entry in texts.canned:
        if any(keyword and keyword in text for keyword in entry.keywords):
            return entry.answer
    return None


def block_message(texts: OutguardTexts, decision: RouteDecision,
                  prompt_masked: str = "") -> str:
    """BLOCK 拒答文案：决定性 reason code 模板（未配置→default）+ 可选代答拼尾。

    ``decision.reasons`` 为空（非正常形态）时按 default 兜底；代答命中时以
    换行拼接在拒答文案之后（403 message 同体下发）。
    """
    decisive = decision.reasons[0].code if decision.reasons else ""
    message = texts.block_by_code.get(decisive) or texts.block_default
    reply = canned_answer(texts, prompt_masked)
    if reply:
        message = f"{message}\n{reply}"
    return message
