"""pfcore — PlayableSpec 校验器（Python 权威侧，重生成 pilot）。

公开面（对照 spec-contract §2.5 的 Python 侧职责）：
- validation.validate_spec_file / validate_spec_dict / expand_targets
- invariants：Lcg / match3_board / match3_find_move / pullpin_level_roles /
  sort_* 生成器与常量（REQUIRED_STRING_KEYS、MAX_DURATION_SEC、PULLPIN_REROLL_MAX、*_DEFAULTS）
- spec_model：PlayableSpec 类型化表示层

JS 镜像（packages/spec）不在本 pilot 范围（SPEC.md §1/§8.8）。
"""

from . import invariants, spec_model, validation
from .invariants import (
    CHANNELS,
    MAX_DURATION_SEC,
    PULLPIN_REROLL_MAX,
    REQUIRED_STRING_KEYS,
    TEMPLATES,
    TEMPLATE_PARAM_DEFAULTS,
    Lcg,
    match3_board,
    match3_find_move,
    pullpin_level_roles,
    sort_apply_move,
    sort_inverse_legal,
    sort_legal_moves,
    sort_scramble,
    sort_solved_board,
    typed_params,
)
from .spec_model import PlayableSpec, build_model
from .validation import expand_targets, validate_spec_dict, validate_spec_file

__version__ = "1.0.0"

__all__ = [
    "validation",
    "invariants",
    "spec_model",
    "validate_spec_file",
    "validate_spec_dict",
    "expand_targets",
    "PlayableSpec",
    "build_model",
    "Lcg",
    "match3_board",
    "match3_find_move",
    "pullpin_level_roles",
    "sort_solved_board",
    "sort_legal_moves",
    "sort_apply_move",
    "sort_inverse_legal",
    "sort_scramble",
    "typed_params",
    "REQUIRED_STRING_KEYS",
    "TEMPLATES",
    "CHANNELS",
    "MAX_DURATION_SEC",
    "PULLPIN_REROLL_MAX",
    "TEMPLATE_PARAM_DEFAULTS",
]
