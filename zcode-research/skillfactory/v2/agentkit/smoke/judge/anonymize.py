import json, random, shutil, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent  # smoke/
judge = root / "judge"
treat = root / "treatment" / "OUT.md"
base = root / "baseline" / "OUT.md"
for p in (treat, base):
    if not p.exists():
        sys.exit(f"缺少产物：{p}")
rng = random.Random()
labels = ["甲", "乙"]
rng.shuffle(labels)  # labels[0] -> treatment
mapping = {labels[0]: "treatment", labels[1]: "baseline"}
shutil.copy(treat, judge / f"{labels[0]}.md")
shutil.copy(base, judge / f"{labels[1]}.md")
(judge / "mapping.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
print("已匿名化：", {k: str((judge / f'{k}.md')) for k in labels})
