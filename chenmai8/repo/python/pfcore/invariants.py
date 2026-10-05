"""PlayableSpec v1 语义不变式与规范生成器（schema 之外的可解性契约）。

定位：``playable-spec.schema.json`` 只能表达结构约束；本模块承担跨字段语义
不变式（§4.1 冻结的五条），并定义"由 seed 确定性生成关卡盘面"的规范生成器
（canonical generator）。packages/spec/src/invariants.mjs 是本模块的 JS 镜像
实现（同一套算法逐行对应），两侧对同一 spec 的判定必须一致——这是 schema v1
冻结的一部分，任何一侧改动都视为破坏契约。

不变式清单：
  I1 pullpin 逐关拔针模拟必须可解；
  I2 sort 初始盘面 = 已解状态经可逆步扰动（栈可逆校验，必有解）；
  I3 match3 seed 生成的初始盘面存在可行步（相邻交换出 >=3 连）；
  I4 game.durationBudgetSec.max <= 30（且 target <= max）；
  I5 i18n.locales 每语言 strings 键全覆盖（cta/tutorial/win/lose/score）。

确定性约定（跨语言一致的关键）：
  - 随机源为 32 位 LCG：state = (1664525 * state + 1013904223) mod 2**32，
    取值用 next() % n；JS 侧用 Math.imul + >>>0 复刻同余结果。
  - pullpin 针角色：每关先抽 rescuee，再重抽（至多 16 次）不等于 rescuee 的
    hazard；16 次全撞则取 (rescuee+1) % pinsPerLevel。
  - sort 扰动步数固定 rods*layersPerRod，候选步只含"逆步合法"的走法。
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- 常量（冻结）

LCG_A = 1664525
LCG_C = 1013904223
MASK32 = 0xFFFFFFFF

#: i18n 每语言必须齐全的字符串键（I5）。
REQUIRED_STRING_KEYS = ("cta", "tutorial", "win", "lose", "score")

#: 与 schema default 注解一致的模板参数默认值（validator 侧用于解析缺省）。
MATCH3_DEFAULTS = {
    "cols": 6, "rows": 6, "moves": 15, "colors": 5,
    "goalType": "clear-jelly", "goalCount": 30,
    "spriteKeys": ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"],
}
MERGE_DEFAULTS = {
    "cols": 5, "rows": 5, "maxTier": 5, "spawnTierMax": 2, "goalTier": 4,
    "spriteKeys": ["tier-1", "tier-2", "tier-3", "tier-4", "tier-5"],
}
PULLPIN_DEFAULTS = {"levels": 3, "pinsPerLevel": 3, "hazard": "lava", "rescuee": "character"}
SORT_DEFAULTS = {"rods": 4, "layersPerRod": 4, "colors": 4, "screwMode": False}

#: sort 扰动中"角色针重抽"的最大尝试次数（与 JS 镜像一致）。
PULLPIN_REROLL_MAX = 16

MAX_DURATION_SEC = 30


# ---------------------------------------------------------------- 确定性随机源

class Lcg:
    """32 位 LCG（numrecipes 经典参数），Python/JS 双侧同余。"""

    __slots__ = ("state",)

    def __init__(self, seed: int) -> None:
        self.state = int(seed) & MASK32

    def next_u32(self) -> int:
        self.state = (LCG_A * self.state + LCG_C) & MASK32
        return self.state

    def below(self, n: int) -> int:
        return self.next_u32() % n


# ---------------------------------------------------------------- 规范生成器

def match3_board(seed: int, rows: int, cols: int, colors: int) -> list[list[int]]:
    """按 seed 生成 match3 初始盘面（行优先，元素为颜色下标）。"""
    rng = Lcg(seed)
    return [[rng.below(colors) for _ in range(cols)] for _ in range(rows)]


def match3_find_move(board: list[list[int]]) -> tuple[int, int, int, int] | None:
    """返回一个可行步 (r1,c1,r2,c2)（相邻交换后出现 >=3 连），无则 None。"""
    rows = len(board)
    cols = len(board[0]) if rows else 0
    if rows == 0 or cols == 0:
        return None

    def has_match(b: list[list[int]]) -> bool:
        for r in range(rows):
            run = 1
            for c in range(1, cols):
                if b[r][c] == b[r][c - 1]:
                    run += 1
                    if run >= 3:
                        return True
                else:
                    run = 1
        for c in range(cols):
            run = 1
            for r in range(1, rows):
                if b[r][c] == b[r - 1][c]:
                    run += 1
                    if run >= 3:
                        return True
                else:
                    run = 1
        return False

    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = r + dr, c + dc
                if r2 >= rows or c2 >= cols or board[r][c] == board[r2][c2]:
                    continue
                board[r][c], board[r2][c2] = board[r2][c2], board[r][c]
                ok = has_match(board)
                board[r][c], board[r2][c2] = board[r2][c2], board[r][c]
                if ok:
                    return (r, c, r2, c2)
    return None


def pullpin_level_roles(seed: int, levels: int, pins_per_level: int) -> list[tuple[int, int]]:
    """按 seed 生成每关 (rescuee_idx, hazard_idx)。

    约定：每关恰有一个救援针（拔掉即角色逃出）与一个机关针（先于救援针拔掉
    则角色遇难），其余为中性针。重抽规则见模块 docstring。
    """
    rng = Lcg(seed)
    roles: list[tuple[int, int]] = []
    for _ in range(levels):
        rescuee = rng.below(pins_per_level)
        hazard = -1
        for _ in range(PULLPIN_REROLL_MAX):
            h = rng.below(pins_per_level)
            if h != rescuee:
                hazard = h
                break
        if hazard < 0:
            hazard = (rescuee + 1) % pins_per_level
        roles.append((rescuee, hazard))
    return roles


def pullpin_simulate(order: list[int], rescuee: int, hazard: int) -> tuple[bool, str]:
    """对一关按 order 逐针模拟：返回 (是否救出, 原因)。"""
    for pin in order:
        if pin == hazard:
            return False, "机关针在救援针之前被拔出"
        if pin == rescuee:
            return True, "角色逃出"
    return False, "救援针未被拔出"


def sort_solved_board(rods: int, layers_per_rod: int, colors: int) -> list[list[int]]:
    """已解状态：前 colors 根柱各为一色满柱，其余为空柱。"""
    filled = min(colors, rods)
    return [[c] * layers_per_rod for c in range(filled)] + [[] for _ in range(rods - filled)]


def sort_legal_moves(board: list[list[int]], layers_per_rod: int) -> list[tuple[int, int, int]]:
    """合法走法（同色顶段整体搬移，(src, dst, k)，k = min(顶段长, 空位)）。"""
    moves: list[tuple[int, int, int]] = []
    for src, rod in enumerate(board):
        if not rod:
            continue
        color = rod[-1]
        run = 1
        while run < len(rod) and rod[-1 - run] == color:
            run += 1
        for dst, drod in enumerate(board):
            if dst == src:
                continue
            space = layers_per_rod - len(drod)
            if space <= 0:
                continue
            if drod and drod[-1] != color:
                continue
            moves.append((src, dst, min(run, space)))
    return moves


def sort_apply_move(board: list[list[int]], src: int, dst: int, k: int) -> None:
    color = board[src][-1]
    for _ in range(k):
        board[src].pop()
        board[dst].append(color)


def sort_inverse_legal(board: list[list[int]], src: int, dst: int, k: int,
                       layers_per_rod: int) -> bool:
    """逆步（把刚搬的 k 个从 dst 搬回 src）是否为合法走法——可逆性判据。"""
    color = board[dst][len(board[dst]) - k]
    s = board[src]
    if len(s) + k > layers_per_rod:
        return False
    return not s or s[-1] == color


def sort_scramble(seed: int, rods: int, layers_per_rod: int,
                  colors: int) -> tuple[list[list[int]], list[tuple[int, int, int]]]:
    """由已解状态经"逆步合法"的走法扰动出初始盘面（可逆 => 必有解）。

    返回 (盘面, 扰动步迹)；validator 逐步重放步迹做栈可逆校验（I2）。
    """
    rng = Lcg(seed)
    board = sort_solved_board(rods, layers_per_rod, colors)
    trace: list[tuple[int, int, int]] = []
    for _ in range(rods * layers_per_rod):
        cands: list[tuple[int, int, int]] = []
        for (s, d, k) in sort_legal_moves(board, layers_per_rod):
            trial = [rod[:] for rod in board]
            sort_apply_move(trial, s, d, k)
            if sort_inverse_legal(trial, s, d, k, layers_per_rod):
                cands.append((s, d, k))
        if not cands:
            break
        mv = cands[rng.below(len(cands))]
        sort_apply_move(board, *mv)
        trace.append(mv)
    return board, trace


# ---------------------------------------------------------------- 不变式检查

@dataclass(frozen=True)
class SpecIssue:
    """一条校验问题：json-path 风格字段路径 + 人读消息 + 稳定错误码。"""

    path: str
    message: str
    code: str

    def render(self) -> str:
        return f"{self.path}: {self.message} [{self.code}]"


def _resolved(params: dict, defaults: dict, key: str):
    return params[key] if key in params else defaults[key]


def check_invariants(spec: dict) -> list[SpecIssue]:
    """schema 通过后执行；返回全部违反项（空列表 = 通过）。"""
    issues: list[SpecIssue] = []
    if not isinstance(spec, dict):
        return [SpecIssue("$", f"顶层必须是 JSON object，得到 {type(spec).__name__}",
                          "schema-type")]
    game = spec.get("game") or {}
    params = game.get("params") or {}
    template = game.get("template")

    # I4 时长预算：max <= 30（schema 亦有 maximum，此处双保险），target <= max。
    dur = game.get("durationBudgetSec") or {}
    if isinstance(dur, dict):
        mx, tg = dur.get("max"), dur.get("target")
        if isinstance(mx, int) and mx > MAX_DURATION_SEC:
            issues.append(SpecIssue("$.game.durationBudgetSec.max",
                                    f"max={mx} 超过 {MAX_DURATION_SEC} 秒预算上限", "I4-duration-max"))
        if isinstance(tg, int) and isinstance(mx, int) and tg > mx:
            issues.append(SpecIssue("$.game.durationBudgetSec.target",
                                    f"target={tg} 不得超过 max={mx}", "I4-duration-target"))

    # 模板级不变式（结构已过 schema，这里放心取字段，但仍做类型防御）。
    if template == "match3" and isinstance(params, dict):
        colors = int(_resolved(params, MATCH3_DEFAULTS, "colors"))
        rows = int(_resolved(params, MATCH3_DEFAULTS, "rows"))
        cols = int(_resolved(params, MATCH3_DEFAULTS, "cols"))
        sprite_keys = list(_resolved(params, MATCH3_DEFAULTS, "spriteKeys"))
        if colors > len(sprite_keys):
            issues.append(SpecIssue("$.game.params.colors",
                                    f"colors={colors} 超过 spriteKeys 数量 {len(sprite_keys)}",
                                    "I3-sprites-cover-colors"))
        board = match3_board(int(spec.get("meta", {}).get("seed", 0)), rows, cols, colors)
        move = match3_find_move(board)
        if move is None:
            issues.append(SpecIssue(
                "$.meta.seed",
                f"seed={spec.get('meta', {}).get('seed')} 生成的 match3 初始盘面无可行步，请换 seed",
                "I3-match3-feasible-move"))
    elif template == "merge" and isinstance(params, dict):
        max_tier = int(_resolved(params, MERGE_DEFAULTS, "maxTier"))
        spawn_max = int(_resolved(params, MERGE_DEFAULTS, "spawnTierMax"))
        goal_tier = int(_resolved(params, MERGE_DEFAULTS, "goalTier"))
        sprite_keys = list(_resolved(params, MERGE_DEFAULTS, "spriteKeys"))
        if max_tier > len(sprite_keys):
            issues.append(SpecIssue("$.game.params.maxTier",
                                    f"maxTier={max_tier} 超过 spriteKeys 数量 {len(sprite_keys)}",
                                    "I-merge-sprites"))
        if not (1 <= spawn_max < max_tier):
            issues.append(SpecIssue("$.game.params.spawnTierMax",
                                    f"spawnTierMax={spawn_max} 须满足 1 <= spawnTierMax < maxTier={max_tier}",
                                    "I-merge-spawn"))
        if goal_tier > max_tier:
            issues.append(SpecIssue("$.game.params.goalTier",
                                    f"goalTier={goal_tier} 不得超过 maxTier={max_tier}",
                                    "I-merge-goal"))
    elif template == "pullpin" and isinstance(params, dict):
        levels = int(_resolved(params, PULLPIN_DEFAULTS, "levels"))
        pins = int(_resolved(params, PULLPIN_DEFAULTS, "pinsPerLevel"))
        order = params.get("orderSolution")
        if not isinstance(order, list):
            issues.append(SpecIssue("$.game.params.orderSolution",
                                    "缺少 orderSolution（每关拔针顺序数组）", "I1-pullpin-order"))
        else:
            if len(order) != levels:
                issues.append(SpecIssue(
                    "$.game.params.orderSolution",
                    f"orderSolution 关数 {len(order)} 与 levels={levels} 不一致",
                    "I1-pullpin-order"))
            roles = pullpin_level_roles(int(spec.get("meta", {}).get("seed", 0)), levels, pins)
            for li, level_order in enumerate(order):
                base = f"$.game.params.orderSolution[{li}]"
                if not isinstance(level_order, list) or not level_order \
                        or not all(isinstance(p, int) for p in level_order):
                    issues.append(SpecIssue(base, "拔针顺序须为非空整数数组", "I1-pullpin-order"))
                    continue
                if len(set(level_order)) != len(level_order):
                    issues.append(SpecIssue(base, "同一针不可重复拔", "I1-pullpin-order"))
                    continue
                if any(p < 0 or p >= pins for p in level_order):
                    issues.append(SpecIssue(base,
                                            f"针下标须在 0..{pins - 1}（pinsPerLevel={pins}）",
                                            "I1-pullpin-order"))
                    continue
                rescuee, hazard = roles[li] if li < len(roles) else (0, 1)
                solved, reason = pullpin_simulate(level_order, rescuee, hazard)
                if not solved:
                    issues.append(SpecIssue(
                        base,
                        f"第 {li} 关不可解：{reason}（rescuee=针{rescuee}, hazard=针{hazard}，"
                        f"布局由 seed 确定性生成）",
                        "I1-pullpin-unsolvable"))
    elif template == "sort" and isinstance(params, dict):
        rods = int(_resolved(params, SORT_DEFAULTS, "rods"))
        layers = int(_resolved(params, SORT_DEFAULTS, "layersPerRod"))
        colors = int(_resolved(params, SORT_DEFAULTS, "colors"))
        if colors > rods:
            issues.append(SpecIssue("$.game.params.colors",
                                    f"colors={colors} 不得超过 rods={rods}（每色需一柱）",
                                    "I2-sort-colors"))
        else:
            # I2 栈可逆校验：重放规范扰动步迹，每一步必须是合法走法且逆步合法。
            board, trace = sort_scramble(int(spec.get("meta", {}).get("seed", 0)),
                                         rods, layers, colors)
            replay = sort_solved_board(rods, layers, colors)
            for i, (s, d, k) in enumerate(trace):
                legal = sort_legal_moves(replay, layers)
                if (s, d, k) not in legal:
                    issues.append(SpecIssue("$.meta.seed",
                                            f"sort 扰动步 {i} ({s}->{d}x{k}) 不是合法走法",
                                            "I2-sort-scramble"))
                    break
                sort_apply_move(replay, s, d, k)
                if not sort_inverse_legal(replay, s, d, k, layers):
                    issues.append(SpecIssue("$.meta.seed",
                                            f"sort 扰动步 {i} ({s}->{d}x{k}) 逆步不合法（破坏可逆性）",
                                            "I2-sort-reversible"))
                    break
            else:
                if replay != board:
                    issues.append(SpecIssue("$.meta.seed",
                                            "sort 盘面重放结果与生成器不一致", "I2-sort-scramble"))

    # I5 i18n：locales 每语言 strings 键全覆盖；rtl ⊆ locales；defaultLocale ∈ locales。
    i18n = spec.get("i18n") or {}
    if isinstance(i18n, dict):
        locales = i18n.get("locales") or []
        strings = i18n.get("strings") or {}
        if isinstance(locales, list) and isinstance(strings, dict):
            for locale in locales:
                entry = strings.get(locale)
                if not isinstance(entry, dict):
                    issues.append(SpecIssue(f"$.i18n.strings.{locale}",
                                            f"语言 {locale!r} 缺少 strings 条目", "I5-i18n-coverage"))
                    continue
                for key in REQUIRED_STRING_KEYS:
                    val = entry.get(key)
                    if not isinstance(val, str) or not val.strip():
                        issues.append(SpecIssue(
                            f"$.i18n.strings.{locale}.{key}",
                            f"语言 {locale!r} 缺少字符串键 {key!r}", "I5-i18n-coverage"))
        default_locale = i18n.get("defaultLocale")
        if isinstance(default_locale, str) and isinstance(locales, list) \
                and default_locale not in locales:
            issues.append(SpecIssue("$.i18n.defaultLocale",
                                    f"defaultLocale={default_locale!r} 不在 locales 中",
                                    "I5-i18n-default"))
        rtl = i18n.get("rtl") or []
        if isinstance(rtl, list) and isinstance(locales, list):
            for i, lang in enumerate(rtl):
                if lang not in locales:
                    issues.append(SpecIssue(f"$.i18n.rtl[{i}]",
                                            f"RTL 语言 {lang!r} 不在 locales 中",
                                            "I5-i18n-rtl"))

    return issues
