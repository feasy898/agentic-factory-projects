#!/usr/bin/env python3
"""Unstage G7 frame-extraction caches, ignore them, report final media size."""
import subprocess
from pathlib import Path

REPO = Path("/root/cradle")

def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout

# 1) unstage g7frames caches anywhere
staged = git("diff", "--cached", "--name-only").splitlines()
caches = [f for f in staged if ".g7frames" in f or "/.frames/" in f]
if caches:
    git("reset", "-q", "--", *caches)
print(f"unstaged {len(caches)} cache files")

# 2) gitignore entry
gi = REPO / ".gitignore"
s = gi.read_text(encoding="utf-8")
if "g7frames" not in s:
    s += "\n# G7 frame-extraction caches (regenerable)\n*.g7frames/\n"
    gi.write_text(s, encoding="utf-8")
    print("gitignore updated")

# 3) final staged size
staged = git("diff", "--cached", "--name-only").splitlines()
total = 0
for f in staged:
    p = REPO / f
    if p.is_file():
        total += p.stat().st_size
print(f"final staged: {len(staged)} files, {total/1048576:.1f} MB")
