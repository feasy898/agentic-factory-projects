"""recognizers 最小模型位（重生成：仅 EntityClass，供 masking/evals 依赖）。

依据 docs/assets/specs/recognizers-rule.md §2（冻结）：19 个常量，
``label`` = 占位符用中文标签。本文件为重生成实现的**依赖 shim**，
只含 evals.m3_masking 所需的枚举本体；detect/Finding 等不在本次范围。
"""
from __future__ import annotations

from enum import Enum

_LABELS: dict[str, str] = {
    "PERSON": "人名",
    "ADDRESS": "住址",
    "ID_CARD": "身份证",
    "PHONE_MOBILE": "手机号",
    "PHONE_LANDLINE": "座机",
    "BANK_CARD": "银行卡",
    "USCC": "信用代码",
    "PLATE": "车牌",
    "EMAIL": "邮箱",
    "IP": "地址",
    "SECRET_KEY": "密钥",
    "DATE_BIRTH": "出生日期",
    "SENSITIVE_ATTR": "敏感属性",
    "WORK_SECRET": "工作秘密",
    "CLASSIFICATION_MARK": "密级标识",
    "INJECTION": "注入指令",
    "ORG_INTERNAL": "内部机构",
    "DOC_NUMBER": "文号",
    "OTHER": "其他",
}


class EntityClass(str, Enum):
    """实体类别（recognizers-rule spec §2，值即代码常量，label 为占位符中文标签）。"""

    PERSON = "PERSON"
    ADDRESS = "ADDRESS"
    ID_CARD = "ID_CARD"
    PHONE_MOBILE = "PHONE_MOBILE"
    PHONE_LANDLINE = "PHONE_LANDLINE"
    BANK_CARD = "BANK_CARD"
    USCC = "USCC"
    PLATE = "PLATE"
    EMAIL = "EMAIL"
    IP = "IP"
    SECRET_KEY = "SECRET_KEY"
    DATE_BIRTH = "DATE_BIRTH"
    SENSITIVE_ATTR = "SENSITIVE_ATTR"
    WORK_SECRET = "WORK_SECRET"
    CLASSIFICATION_MARK = "CLASSIFICATION_MARK"
    INJECTION = "INJECTION"
    ORG_INTERNAL = "ORG_INTERNAL"
    DOC_NUMBER = "DOC_NUMBER"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return _LABELS[self.value]
