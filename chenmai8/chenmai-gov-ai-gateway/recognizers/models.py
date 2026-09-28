"""契约模型：识别结果 Finding（开发指令 §5.1，冻结——字段只增不改名）。

recognizers → 一切下游（masking / routing / audit / filechannel）只认本文件形状。
约定：
- ``raw`` 仅内存/调试使用，**禁止写入审计库**（audit.AuditEvent 不含该字段，
  audit 入库前的零明文断言在 audit 包实现）；
- ``type`` 取值即 :class:`EntityClass`，中文标签 ``label`` 供占位符算法使用（§5.3.1）；
- ``subtype`` 为 §5.1.1 指定的增补字段：仅 SENSITIVE_ATTR 使用，值域为
  :data:`SENSITIVE_ATTR_SUBTYPES`。
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EntityClass(str, Enum):
    """实体类别枚举（值即代码常量；``label`` = 占位符用中文标签）。"""

    label: str

    def __new__(cls, value: str, label: str) -> EntityClass:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.label = label
        return obj

    PERSON = ("PERSON", "人名")
    ADDRESS = ("ADDRESS", "住址")
    ID_CARD = ("ID_CARD", "身份证")
    PHONE_MOBILE = ("PHONE_MOBILE", "手机号")
    PHONE_LANDLINE = ("PHONE_LANDLINE", "座机")
    BANK_CARD = ("BANK_CARD", "银行卡")
    USCC = ("USCC", "信用代码")
    PLATE = ("PLATE", "车牌")
    EMAIL = ("EMAIL", "邮箱")
    IP = ("IP", "地址")
    SECRET_KEY = ("SECRET_KEY", "密钥")
    DATE_BIRTH = ("DATE_BIRTH", "出生日期")
    SENSITIVE_ATTR = ("SENSITIVE_ATTR", "敏感属性")
    WORK_SECRET = ("WORK_SECRET", "工作秘密")
    CLASSIFICATION_MARK = ("CLASSIFICATION_MARK", "密级标识")
    INJECTION = ("INJECTION", "注入指令")
    ORG_INTERNAL = ("ORG_INTERNAL", "内部机构")
    DOC_NUMBER = ("DOC_NUMBER", "文号")
    OTHER = ("OTHER", "其他")


#: SENSITIVE_ATTR 的子类型值域（§5.1.1；对齐敏感个人信息公开类别摘要，D1 文档任务复核）
SENSITIVE_ATTR_SUBTYPES: frozenset[str] = frozenset({
    "病症", "残障", "低保特困", "社区矫正", "信访人",
    "金融账户", "行踪轨迹", "犯罪记录", "特定身份",
})

#: 识别层（MVP 仅 rule 实装；ner/semantic 走适配器，无模型时空输出）
FindingLayer = Literal["rule", "ner", "semantic"]

#: 处置提示：MASK=脱敏替换；ROUTE_FLAG=仅作路由依据；BLOCK_FLAG=命中即拦截依据
ActionHint = Literal["MASK", "ROUTE_FLAG", "BLOCK_FLAG"]


class Finding(BaseModel):
    """单条识别结果（§5.1 JSON 形状一字不差；start/end 为 Python 切片语义）。"""

    model_config = ConfigDict(extra="forbid")

    fid: str                                  # 请求内自增，如 f_0001
    type: EntityClass
    layer: FindingLayer = "rule"
    start: int = Field(default=0, ge=0)
    end: int = Field(default=0, ge=0)
    raw: str = ""                             # 原文：仅内存/调试，禁止入审计
    normalized: str = ""                      # 归一化值（§5.3.2 规则在 masking）
    subtype: str | None = None                # 增补字段（§5.1.1）：仅 SENSITIVE_ATTR
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)  # 规则命中校验位=1.0
    whitelisted: bool = False                 # 命中白名单则不参与脱敏
    action_hint: ActionHint = "MASK"

    @model_validator(mode="after")
    def _span_ordered(self) -> Finding:
        if self.start > self.end:
            raise ValueError(f"invalid char span: start={self.start} > end={self.end}")
        return self

    @model_validator(mode="after")
    def _subtype_scope(self) -> Finding:
        if self.subtype is None:
            return self
        if self.type is not EntityClass.SENSITIVE_ATTR:
            raise ValueError("subtype 仅允许用于 type=SENSITIVE_ATTR")
        if self.subtype not in SENSITIVE_ATTR_SUBTYPES:
            raise ValueError(f"unknown SENSITIVE_ATTR subtype: {self.subtype!r}")
        return self
