"""pfcore.invariants — 确定性随机源、规范生成器与 I1–I5（+merge）跨字段检查。

从零重建（对照 spec-contract §2.2–§2.4 的冻结语义；实现细节的裁定见 SPEC.md §8）。
本模块只依赖标准库；错误一律产出 {path, message, code}（json-path 风格路径 + 稳定错误码）。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 冻结常量（spec-contract §2.1/§2.2/§2.4）
# ---------------------------------------------------------------------------

REQUIRED_STRING_KEYS = ("cta", "tutorial", "win", "lose", "score")
TEMPLATES = ("match3", "merge", "pullpin", "sort")
CHANNELS = ("applovin", "meta", "mintegral", "unity", "google", "tiktok")
MAX_DURATION_SEC = 30
PULLPIN_REROLL_MAX = 16

# 各模板 params 默认值（与 schema $defs 的 default 一致；typed_params 用 {**DEFAULTS, **params}）
TEMPLATE_PARAM_DEFAULTS: dict[str, dict[str, Any]] = {
    "match3": {
        "cols": 6,
        "rows": 6,
        "moves": 15,
        "colors": 5,
        "goalType": "clear-jelly",
        "goalCount": 30,
        "spriteKeys": ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"],
    },
    "merge": {
        "spriteKeys": [],
        "spawnColors": 4,
        "goalScore": 300,
    },
    "pullpin": {
        "levels": 3,
        "pinsPerLevel": 4,
        "hazard": "hazard",
        "rescuee": "character",
        "orderSolution": [],
    },
    "sort": {
        "colors": 3,
        "rods": 4,
        "layersPerRod": 3,
        "solution": [],
    },
}


def typed_params(template: str, params: dict[str, Any] | None) -> dict[str, Any]:
    """按 template 一次性合并默认值（spec-contract §3：{**DEFAULTS, **params}）。"""
    return {**TEMPLATE_PARAM_DEFAULTS.get(template, {}), **(params or {})}


# ---------------------------------------------------------------------------
# 确定性随机源：32 位 LCG（spec-contract §2.3，冻结）
# ---------------------------------------------------------------------------


class Lcg:
    """state = (1664525 * state + 1013904223) mod 2^32；取值 next() % n（先推进后取值）。"""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFF

    def next(self) -> int:
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return self.state

    def below(self, n: int) -> int:
        return self.next() % n


# ---------------------------------------------------------------------------
# 规范生成器（spec-contract §2.2）
# ---------------------------------------------------------------------------


def match3_board(seed: int, rows: int, cols: int, colors: int) -> list[list[int]]:
    """行优先逐格 below(colors)。色值 -1 不产生（本生成器无补位/无果冻）。"""
    rng = Lcg(seed)
    return [[rng.below(colors) for _ in range(cols)] for _ in range(rows)]


def _has_match_at(board: list[list[int]], r: int, c: int, rows: int, cols: int) -> bool:
    color = board[r][c]
    if color < 0:
        return False
    run = 1
    cc = c - 1
    while cc >= 0 and board[r][cc] == color:
        run += 1
        cc -= 1
    cc = c + 1
    while cc < cols and board[r][cc] == color:
        run += 1
        cc += 1
    if run >= 3:
        return True
    run = 1
    rr = r - 1
    while rr >= 0 and board[rr][c] == color:
        run += 1
        rr -= 1
    rr = r + 1
    while rr < rows and board[rr][c] == color:
        run += 1
        rr += 1
    return run >= 3


def match3_find_move(board: list[list[int]]) -> tuple[int, int, int, int] | None:
    """扫相邻交换（方向 (0,1)/(1,0)），存在任一成三交换即返回 (r,c,r2,c2)，否则 None。"""
    rows = len(board)
    cols = len(board[0]) if rows else 0
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = r + dr, c + dc
                if r2 >= rows or c2 >= cols:
                    continue
                board[r][c], board[r2][c2] = board[r2][c2], board[r][c]
                ok = _has_match_at(board, r, c, rows, cols) or _has_match_at(
                    board, r2, c2, rows, cols
                )
                board[r][c], board[r2][c2] = board[r2][c2], board[r][c]
                if ok:
                    return (r, c, r2, c2)
    return None


def pullpin_level_roles(seed: int, levels: int, pins_per_level: int) -> list[tuple[int, int]]:
    """每关恰 1 救援针 + 1 机关针（其余中性）；单 LCG 流跨关卡连抽（SPEC.md §8.3）。

    rescuee = below(pins)；hazard 重抽至多 PULLPIN_REROLL_MAX 次非 rescuee 值，
    全撞则 (rescuee + 1) % pins。返回 [(rescuee, hazard), ...]。
    """
    rng = Lcg(seed)
    roles: list[tuple[int, int]] = []
    for _ in range(levels):
        rescuee = rng.below(pins_per_level)
        hazard: int | None = None
        for _ in range(PULLPIN_REROLL_MAX):
            candidate = rng.below(pins_per_level)
            if candidate != rescuee:
                hazard = candidate
                break
        if hazard is None:
            hazard = (rescuee + 1) % pins_per_level
        roles.append((rescuee, hazard))
    return roles


def sort_solved_board(colors: int, rods: int, layers_per_rod: int) -> list[list[int]]:
    """已解盘面 = 前 min(colors, rods) 柱各一色满柱 + 空柱；-1 表示空位。"""
    board: list[list[int]] = [[] for _ in range(rods)]
    for i in range(min(colors, rods)):
        board[i] = [i] * layers_per_rod
    return board


def sort_legal_moves(board: list[list[int]], layers_per_rod: int) -> list[tuple[int, int]]:
    """(a, b)：a 非空、b 未满、（b 空或 b 顶同色）。"""
    moves: list[tuple[int, int]] = []
    for a, rod_a in enumerate(board):
        if not rod_a:
            continue
        top = rod_a[-1]
        for b, rod_b in enumerate(board):
            if a == b or len(rod_b) >= layers_per_rod:
                continue
            if not rod_b or rod_b[-1] == top:
                moves.append((a, b))
    return moves


def sort_apply_move(board: list[list[int]], move: tuple[int, int]) -> None:
    src, dst = move
    board[dst].append(board[src].pop())


def sort_inverse_legal(
    board_before: list[list[int]], move: tuple[int, int], layers_per_rod: int
) -> bool:
    """逆步合法：应用 mv 后，逆步 (dst, src) 仍是合法步
    （搬回后目标柱顶同色或空、且不超容量——spec-contract §2.2）。"""
    return _inverse_legal(board_before, move, layers_per_rod)


def _inverse_legal(board_before: list[list[int]], move: tuple[int, int], layers: int) -> bool:
    src, dst = move
    after = [rod[:] for rod in board_before]
    sort_apply_move(after, (src, dst))
    return (dst, src) in sort_legal_moves(after, layers)


def sort_scramble(
    seed: int, colors: int, rods: int, layers_per_rod: int
) -> tuple[list[list[int]], list[tuple[int, int]]]:
    """恰走 rods*layersPerRod 步；候选步仅限逆步合法；mv = cands[below(len(cands))]。

    返回（扰动盘面, 扰动步序列）。校验器用它重放 spec.params.solution。
    """
    rng = Lcg(seed)
    board = sort_solved_board(colors, rods, layers_per_rod)
    moves: list[tuple[int, int]] = []
    for _ in range(rods * layers_per_rod):
        cands = [mv for mv in sort_legal_moves(board, layers_per_rod) if _inverse_legal(board, mv, layers_per_rod)]
        if not cands:  # 理论上不发生（有非满空位即可逆）；防御性跳出
            break
        mv = cands[rng.below(len(cands))]
        sort_apply_move(board, mv)
        moves.append(mv)
    return board, moves


# ---------------------------------------------------------------------------
# 不变式检查：全部返回 issue 列表 [{path, message, code}]
# ---------------------------------------------------------------------------

I1_PULLPIN_ORDER = "I1-pullpin-order"
I1_PULLPIN_UNSOLVABLE = "I1-pullpin-unsolvable"
I2_SORT_COLORS = "I2-sort-colors"
I2_SORT_SCRAMBLE = "I2-sort-scramble"
I2_SORT_REVERSIBLE = "I2-sort-reversible"
I3_SPRITES_COVER_COLORS = "I3-sprites-cover-colors"
I3_MATCH3_FEASIBLE_MOVE = "I3-match3-feasible-move"
I4_DURATION_MAX = "I4-duration-max"
I4_DURATION_TARGET = "I4-duration-target"
I5_I18N_COVERAGE = "I5-i18n-coverage"
I5_I18N_DEFAULT = "I5-i18n-default"
I5_I18N_RTL = "I5-i18n-rtl"
I_MERGE_SPRITES = "I-merge-sprites"
I_MERGE_SPAWN = "I-merge-spawn"
I_MERGE_GOAL = "I-merge-goal"


def _issue(path: str, message: str, code: str) -> dict[str, str]:
    return {"path": path, "message": message, "code": code}


def _int_or_none(value: Any) -> int | None:
    # bool 是 int 子类，显式排除；浮点仅在无小数部分时接受（schema 已限 integer，此处防御）
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value)


def check_i1_pullpin(spec: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    params = spec.get("game", {}).get("params") or {}
    meta = spec.get("meta") or {}
    seed = _int_or_none(meta.get("seed"))
    levels = _int_or_none(params.get("levels"))
    pins = _int_or_none(params.get("pinsPerLevel"))
    orders = params.get("orderSolution")
    if seed is None or levels is None or pins is None or not isinstance(orders, list):
        return issues  # 形状缺失由 schema 阶段负责；此处不重复报
    if levels <= 0 or pins <= 0:
        return issues
    roles = pullpin_level_roles(seed, levels, pins)
    if len(orders) != levels:
        issues.append(
            _issue(
                "$.game.params.orderSolution",
                f"orderSolution has {len(orders)} level(s), template params declare levels={levels}",
                I1_PULLPIN_UNSOLVABLE,
            )
        )
        return issues
    for level, order in enumerate(orders):
        if not isinstance(order, list):
            continue  # schema 阶段负责形状
        rescuee, hazard = roles[level]
        outcome: str | None = None
        for pin in order:
            pin_idx = _int_or_none(pin)
            if pin_idx is None or pin_idx < 0 or pin_idx >= pins:
                continue  # 越界针按中性处理（永不命中 rescuee）
            if pin_idx == hazard:
                outcome = "order"
                break
            if pin_idx == rescuee:
                outcome = "win"
                break
        if outcome == "order":
            issues.append(
                _issue(
                    f"$.game.params.orderSolution[{level}]",
                    f"level {level}: pull order {order} hits the hazard pin #{hazard} before "
                    f"the rescuee pin #{rescuee} (board from seed {seed})",
                    I1_PULLPIN_ORDER,
                )
            )
        elif outcome is None:
            issues.append(
                _issue(
                    f"$.game.params.orderSolution[{level}]",
                    f"level {level}: pull order {order} never frees the rescuee pin #{rescuee} "
                    f"(hazard pin #{hazard}, board from seed {seed})",
                    I1_PULLPIN_UNSOLVABLE,
                )
            )
    return issues


def check_i2_sort(spec: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    params = spec.get("game", {}).get("params") or {}
    meta = spec.get("meta") or {}
    seed = _int_or_none(meta.get("seed"))
    colors = _int_or_none(params.get("colors"))
    rods = _int_or_none(params.get("rods"))
    layers = _int_or_none(params.get("layersPerRod"))
    solution = params.get("solution")
    if seed is None or colors is None or rods is None or layers is None:
        return issues
    if colors < 2:
        issues.append(_issue("$.game.params.colors", f"sort needs >= 2 colors, got {colors}", I2_SORT_COLORS))
        return issues
    if colors >= rods:
        # 无空柱（已解盘面占满全部柱）→ 扰动/还原无从谈起
        issues.append(
            _issue(
                "$.game.params.colors",
                f"sort needs colors < rods so at least one rod stays empty, got colors={colors}, rods={rods}",
                I2_SORT_COLORS,
            )
        )
        return issues
    if rods < 3 or layers < 2:
        issues.append(
            _issue("$.game.params", f"sort needs rods>=3 and layersPerRod>=2, got rods={rods}, layers={layers}", I2_SORT_SCRAMBLE)
        )
        return issues
    if not isinstance(solution, list) or not solution:
        issues.append(
            _issue("$.game.params.solution", "sort spec must carry a non-empty solution move list", I2_SORT_SCRAMBLE)
        )
        return issues
    board, _scramble_moves = sort_scramble(seed, colors, rods, layers)
    for step, move in enumerate(solution):
        if not isinstance(move, list) or len(move) != 2:
            issues.append(
                _issue(
                    f"$.game.params.solution[{step}]",
                    f"solution step {step} is not an [src, dst] pair: {move!r}",
                    I2_SORT_REVERSIBLE,
                )
            )
            return issues
        src_ok = _int_or_none(move[0])
        dst_ok = _int_or_none(move[1])
        if src_ok is None or dst_ok is None:
            issues.append(
                _issue(
                    f"$.game.params.solution[{step}]",
                    f"solution step {step} has non-integer rod index: {move!r}",
                    I2_SORT_REVERSIBLE,
                )
            )
            return issues
        mv = (src_ok, dst_ok)
        if mv not in sort_legal_moves(board, layers):
            issues.append(
                _issue(
                    f"$.game.params.solution[{step}]",
                    f"solution step {step} {list(mv)} is not a legal move on the regenerated board",
                    I2_SORT_REVERSIBLE,
                )
            )
            return issues
        if not _inverse_legal(board, mv, layers):
            issues.append(
                _issue(
                    f"$.game.params.solution[{step}]",
                    f"solution step {step} {list(mv)} is not inverse-legal (replay would deadlock)",
                    I2_SORT_REVERSIBLE,
                )
            )
            return issues
        sort_apply_move(board, mv)
    solved = sort_solved_board(colors, rods, layers)
    if board != solved:
        issues.append(
            _issue(
                "$.game.params.solution",
                "solution replay does not reach the generator's solved board",
                I2_SORT_REVERSIBLE,
            )
        )
    return issues


def check_i3_match3(spec: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    params = spec.get("game", {}).get("params") or {}
    meta = spec.get("meta") or {}
    seed = _int_or_none(meta.get("seed"))
    rows = _int_or_none(params.get("rows"))
    cols = _int_or_none(params.get("cols"))
    colors = _int_or_none(params.get("colors"))
    sprite_keys = params.get("spriteKeys")
    if seed is None or rows is None or cols is None or colors is None:
        return issues
    if isinstance(sprite_keys, list):
        if colors > len(sprite_keys):
            issues.append(
                _issue(
                    "$.game.params.spriteKeys",
                    f"colors={colors} exceeds spriteKeys coverage ({len(sprite_keys)} keys)",
                    I3_SPRITES_COVER_COLORS,
                )
            )
    board = match3_board(seed, rows, cols, colors)
    if match3_find_move(board) is None:
        issues.append(
            _issue(
                "$.game.params",
                f"no feasible swap exists on the canonical board from seed {seed} "
                f"({rows}x{cols}, {colors} colors)",
                I3_MATCH3_FEASIBLE_MOVE,
            )
        )
    return issues


def check_i4_duration(spec: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    game = spec.get("game") or {}
    budget = game.get("durationBudgetSec")
    if not isinstance(budget, dict):
        return issues
    target = budget.get("target")
    maximum = budget.get("max")
    if isinstance(maximum, (int, float)) and not isinstance(maximum, bool):
        if maximum > MAX_DURATION_SEC:
            issues.append(
                _issue(
                    "$.game.durationBudgetSec.max",
                    f"durationBudgetSec.max={maximum} exceeds the {MAX_DURATION_SEC}s cap",
                    I4_DURATION_MAX,
                )
            )
    if (
        isinstance(target, (int, float))
        and not isinstance(target, bool)
        and isinstance(maximum, (int, float))
        and not isinstance(maximum, bool)
        and target > maximum
    ):
        issues.append(
            _issue(
                "$.game.durationBudgetSec.target",
                f"durationBudgetSec.target={target} exceeds max={maximum}",
                I4_DURATION_TARGET,
            )
        )
    return issues


def check_i5_i18n(spec: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    i18n = spec.get("i18n") or {}
    locales = i18n.get("locales")
    strings = i18n.get("strings")
    default_locale = i18n.get("defaultLocale")
    rtl = i18n.get("rtl", [])
    if not isinstance(locales, list) or not isinstance(strings, dict):
        return issues

    def _blank(value: Any) -> bool:
        return not isinstance(value, str) or not value.strip()

    for locale in locales:
        entry = strings.get(locale)
        if not isinstance(entry, dict):
            issues.append(
                _issue(
                    f"$.i18n.strings.{locale}",
                    f"locale '{locale}' is declared in i18n.locales but has no strings entry",
                    I5_I18N_COVERAGE,
                )
            )
            continue
        missing = [key for key in REQUIRED_STRING_KEYS if _blank(entry.get(key))]
        if missing:
            issues.append(
                _issue(
                    f"$.i18n.strings.{locale}",
                    f"locale '{locale}' strings missing/blank keys: {', '.join(missing)}",
                    I5_I18N_COVERAGE,
                )
            )
    if isinstance(default_locale, str) and default_locale not in locales:
        issues.append(
            _issue(
                "$.i18n.defaultLocale",
                f"defaultLocale '{default_locale}' is not in i18n.locales {locales}",
                I5_I18N_DEFAULT,
            )
        )
    if isinstance(rtl, list):
        outside = [tag for tag in rtl if tag not in locales]
        if outside:
            issues.append(
                _issue(
                    "$.i18n.rtl",
                    f"rtl locales {outside} are not declared in i18n.locales {locales}",
                    I5_I18N_RTL,
                )
            )
    return issues


def check_merge(spec: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    params = spec.get("game", {}).get("params") or {}
    sprite_keys = params.get("spriteKeys")
    spawn_colors = _int_or_none(params.get("spawnColors"))
    goal_score = _int_or_none(params.get("goalScore"))
    if spawn_colors is not None and spawn_colors < 2:
        issues.append(
            _issue("$.game.params.spawnColors", f"merge needs >= 2 spawn colors, got {spawn_colors}", I_MERGE_SPAWN)
        )
    if isinstance(sprite_keys, list) and spawn_colors is not None and spawn_colors > len(sprite_keys):
        issues.append(
            _issue(
                "$.game.params.spriteKeys",
                f"spawnColors={spawn_colors} exceeds spriteKeys coverage ({len(sprite_keys)} keys)",
                I_MERGE_SPRITES,
            )
        )
    if goal_score is not None and goal_score < 1:
        issues.append(_issue("$.game.params.goalScore", f"merge goalScore must be >= 1, got {goal_score}", I_MERGE_GOAL))
    return issues


TEMPLATE_CHECKS = {
    "match3": (check_i3_match3, check_i4_duration),
    "pullpin": (check_i1_pullpin, check_i4_duration),
    "sort": (check_i2_sort, check_i4_duration),
    "merge": (check_merge, check_i4_duration),
}


def check_invariants(spec: dict[str, Any]) -> list[dict[str, str]]:
    """对已通过 schema 阶段的 spec 跑模板不变式 + I5（i18n 与模板无关，恒跑）。"""
    template = (spec.get("game") or {}).get("template")
    checks = list(TEMPLATE_CHECKS.get(template, ())) if isinstance(template, str) else []
    issues: list[dict[str, str]] = []
    for check in checks:
        issues.extend(check(spec))
    issues.extend(check_i5_i18n(spec))
    return issues
