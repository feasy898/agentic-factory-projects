#!/usr/bin/env bash
set -x
python3 - <<'EOF'
p = "/root/cradle/DECISIONS.md"
src = open(p).read()
# Renumber M1-ENV entries (appended at bottom, duplicated 006-010) to D-019..D-023
renames = [
    ("- **D-006** (2026-09-08, M1-ENV):", "- **D-019** (2026-09-08, M1-ENV; 原编号 D-006，因与 M2-CODE 并行撞号重编):"),
    ("- **D-007** (2026-09-08, M1-ENV):", "- **D-020** (2026-09-08, M1-ENV; 原编号 D-007，因与 M2-CODE 并行撞号重编):"),
    ("- **D-008** (2026-09-08, M1-ENV):", "- **D-021** (2026-09-08, M1-ENV; 原编号 D-008，因与 M2-CODE 并行撞号重编):"),
    ("- **D-009** (2026-09-08, M1-ENV):", "- **D-022** (2026-09-08, M1-ENV; 原编号 D-009，因与 M2-CODE 并行撞号重编):"),
    ("- **D-010** (2026-09-08, M1-ENV):", "- **D-023** (2026-09-08, M1-ENV; 原编号 D-010，因与 M2-CODE 并行撞号重编):"),
]
for old, new in renames:
    assert old in src, f"missing {old}"
    src = src.replace(old, new, 1)
open(p, "w").write(src)

pp = "/root/cradle/PROGRESS.md"
s = open(pp).read()
for old, new in [("决策见 **D-006**", "决策见 **D-019**"), ("源策略见 D-008", "源策略见 D-021"), ("patchify 补丁, D-009", "patchify 补丁, D-022")]:
    assert old in s, f"progress ref missing {old}"
    s = s.replace(old, new, 1)
open(pp, "w").write(s)
print("RENUMBER OK")
EOF
cd ~/cradle && for i in 1 2 3; do git add -A && git commit -m "M1-ENV: renumber env decisions D-019..D-023 (collision with M2-CODE D-006..D-018)" && break || { sleep 30; }; done; git log --oneline | head -3
echo "STEP09_DONE rc=$?"
