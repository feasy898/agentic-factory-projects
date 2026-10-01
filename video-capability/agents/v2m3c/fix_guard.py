#!/usr/bin/env python3
"""V2-M3C: move Wan budget guard before v2 lane dispatch in orchestrator.py."""
from pathlib import Path

p = Path("src/orchestrator.py")
s = p.read_text(encoding="utf-8")

guard_block = '''            # 产出期守卫: Wan 消耗型车道候选总数 ≤200 (SPECS §5.3; v2 车道口径 D-062)
            placeholders = ",".join("?" * len(WAN_CONSUMING_LANES_SQL))
            used = db._query(
                f"SELECT COUNT(*) AS c FROM candidates WHERE verdict != 'fallback' AND shot_id IN"
                f" (SELECT shot_id FROM tasks WHERE lane IN ({placeholders}))",
                WAN_CONSUMING_LANES_SQL,
            )[0]["c"]
            limit = settings.get("budgets", {}).get("wan_candidates_total", 200)
            if used >= limit:
                raise RuntimeError(f"Wan 候选总数已达守卫上限 {limit}, 停止生成保交付")
'''

new_guard = '''            # 产出期守卫: Wan 消耗型车道候选总数 ≤200 (SPECS §5.3; v2 车道口径 D-062)。
            # 必须先于一切 Wan 消耗型车道分发 — 前手 WIP 把守卫放在 lane 分支之后,
            # pure_gen_short/evidence_transfer 提前 return 绕过守卫
            # (test_budget_guard_counts_new_wan_lanes 捕获, V2-M3C 修复)。
            if lane in WAN_CONSUMING_LANES_SQL:
                placeholders = ",".join("?" * len(WAN_CONSUMING_LANES_SQL))
                used = db._query(
                    f"SELECT COUNT(*) AS c FROM candidates WHERE verdict != 'fallback' AND shot_id IN"
                    f" (SELECT shot_id FROM tasks WHERE lane IN ({placeholders}))",
                    WAN_CONSUMING_LANES_SQL,
                )[0]["c"]
                limit = settings.get("budgets", {}).get("wan_candidates_total", 200)
                if used >= limit:
                    raise RuntimeError(f"Wan 候选总数已达守卫上限 {limit}, 停止生成保交付")
'''

anchor = "            # v2 三车道 (SPECS_V2 §5.2-§5.4): 车道分发优先于调试模型投影 (D-062)\n"
assert anchor in s, "lane dispatch anchor not found"
assert guard_block in s, "old guard block not found"
s = s.replace(anchor, new_guard + anchor, 1)
s = s.replace(guard_block, "", 1)
p.write_text(s, encoding="utf-8")
print("GUARD MOVED OK")
