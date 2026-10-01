"""规格评审探针：仅经公开 API 运行参考实现，验证 route.spec.md 中的事实性声明。不读参考实现源码。"""
import os
import sys
from datetime import date

ROOT = r"D:\workspace\学情agent"
sys.path.insert(0, os.path.join(ROOT, "src"))

from xuexing import load_itembank, load_kpgraph, load_strategies  # noqa: E402
from xuexing.diagnosis import diagnose  # noqa: E402
from xuexing.route import RouteError, build_plan  # noqa: E402
from xuexing.types import Response  # noqa: E402

bank = load_itembank(os.path.join(ROOT, "data", "items", "math_grade7_items.json"))
graph = load_kpgraph(os.path.join(ROOT, "data", "knowledge", "math_grade7.json"))
strategies = load_strategies(os.path.join(ROOT, "data", "pedagogy", "strategies.json"))
TODAY = date(2026, 9, 28)


def profile_for(wrong_kp):
    rs = []
    for it in bank.items():
        rs.append(Response(it.id, it.kps[0] != wrong_kp))
    return diagnose(rs, bank, graph, learner_id="u")


print("issubclass(RouteError, ValueError):", issubclass(RouteError, ValueError))
gids = [kp.id for kp in graph.kps()]
print("graph nodes:", len(gids), "| kps() ascending:", gids == sorted(gids))

for wrong in ["kp_rational_add", "kp_power", "kp_eq_solve"]:
    p = profile_for(wrong)
    keys = set(p.mastery.keys())
    print(f"[{wrong}] mastery_keys==graph_ids: {keys == set(gids)}; "
          f"out_of_graph: {sorted(keys - set(gids))}; graph_wo_mastery: {sorted(set(gids) - keys)}")
    weak = sorted(k for k, m in p.mastery.items() if m < 0.65)
    print(f"  weak({len(weak)}): {weak}")
    print(f"  min_weak_m={min((p.mastery[k] for k in weak), default=None):.4f}")

# ---- 例1 全量复核 ----
p1 = profile_for("kp_rational_add")
plan = build_plan(p1, bank, graph, strategies, TODAY)
print("\n[ex1] steps:")
for s in plan.steps:
    print(f"  ({s.kp_id}, {s.strategy_id}, m={p1.mastery[s.kp_id]:.4f}, tm={s.target_mastery!r})")
print("rationale[0]:", repr(plan.steps[0].rationale))
print("[ex1] reviews:", len(plan.reviews))
for r in plan.reviews:
    print(f"  ({r.kp_id}, {r.due}, interval={r.interval_days!r}, ease={r.ease!r})")
print("created_at:", plan.created_at, "| learner_id:", plan.learner_id)
print("determinism plan==plan:", plan == build_plan(p1, bank, graph, strategies, TODAY))

# ---- 例2 ----
p2 = profile_for("kp_power")
plan2 = build_plan(p2, bank, graph, strategies, TODAY)
print("\n[ex2] weak:", sorted(k for k, m in p2.mastery.items() if m < 0.65))
print("[ex2] steps:", [(s.kp_id, s.strategy_id) for s in plan2.steps])
print("[ex2] reviews:", len(plan2.reviews), "ascending:", [r.kp_id for r in plan2.reviews] == sorted(r.kp_id for r in plan2.reviews))
print("[ex2] kp_power in reviews:", any(r.kp_id == "kp_power" for r in plan2.reviews))

# ---- 全对画像 ----
pall = diagnose([Response(it.id, True) for it in bank.items()], bank, graph, learner_id="u")
planall = build_plan(pall, bank, graph, strategies, TODAY)
print("\n[all-mastered] steps:", planall.steps, "| reviews:", len(planall.reviews))

# ---- test_steps 场景（wrong=kp_eq_solve）的 m<0.4 分支是否触发 ----
p3 = profile_for("kp_eq_solve")
plan3 = build_plan(p3, bank, graph, strategies, TODAY)
print("\n[test_steps scenario] steps (kp, m):", [(s.kp_id, round(p3.mastery[s.kp_id], 4)) for s in plan3.steps])
print("[test_steps scenario] any m<0.4:", any(p3.mastery[s.kp_id] < 0.4 for s in plan3.steps))

# ---- 图外 mastery 键的容错（构造性验证规格 §3.1 容错声明）----
from xuexing.types import Profile  # noqa: E402
print("\nProfile fields:", [f for f in getattr(Profile, "__dataclass_fields__", {})] or "not-a-dataclass")
