"""契约模型（gov2 盲实现）：M3 冻结测试所需的最小面 = EntityClass 19 值枚举。

来源：docs/assets/CONTRACTS.md C1 节（值=代码常量；label=占位符中文标签）+
recognizers-rule spec §2。M3 只消费 ``EntityClass.value``（摘要 msg 段）与
``EntityClass.label``（占位符标签段）。
"""
from __future__ import annotations

from enum import Enum


class EntityClass(str, Enum):
    """实体类别枚举（值即代码常量；label = 占位符用中文标签）。"""

    label: str

    def __new__(cls, value: str, label: str) -> EntityClass:  # noqa: PYI034 — Enum 惯例
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


#: SENSITIVE_ATTR 的子类型值域（CONTRACTS C1；M3 不消费，契约面带全）
SENSITIVE_ATTR_SUBTYPES: frozenset[str] = frozenset({
    "病症", "残障", "低保特困", "社区矫正", "信访人",
    "金融账户", "行踪轨迹", "犯罪记录", "特定身份",
})
