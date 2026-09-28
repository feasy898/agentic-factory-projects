"""短剧多国出海本地化引擎 —— pipeline 包。

T1 起契约冻结：schema 唯一权威定义在 ``pipeline.contracts``（C1–C8）。
注意：本包 __init__ 只导入轻量契约/配置模块，避免在 import 期引入
torch/paddle 等重型依赖（本机存在 torch/paddle 的 DLL 加载顺序约束）。
"""

from pipeline import contracts
from pipeline.contracts import (
    AudioWatermark,
    Budget,
    Candidate,
    CastBook,
    Character,
    ComplianceReport,
    Consent,
    EmoTag,
    ExplicitLabel,
    FaceFact,
    Finding,
    ImplicitLabel,
    LabelStatus,
    Labels,
    LipPlanItem,
    LipPlanTable,
    OcrFact,
    Shot,
    ShotSheet,
    SoundEvent,
    SynthPlanItem,
    SynthPlanTable,
    Translation,
    TranslationTable,
    Utterance,
    UtteranceTable,
    Word,
    lip_eligible,
)

__version__ = "0.1.0"

__all__ = [
    "contracts",
    "AudioWatermark",
    "Budget",
    "Candidate",
    "CastBook",
    "Character",
    "ComplianceReport",
    "Consent",
    "EmoTag",
    "ExplicitLabel",
    "FaceFact",
    "Finding",
    "ImplicitLabel",
    "LabelStatus",
    "Labels",
    "LipPlanItem",
    "LipPlanTable",
    "OcrFact",
    "Shot",
    "ShotSheet",
    "SoundEvent",
    "SynthPlanItem",
    "SynthPlanTable",
    "Translation",
    "TranslationTable",
    "Utterance",
    "UtteranceTable",
    "Word",
    "lip_eligible",
]
