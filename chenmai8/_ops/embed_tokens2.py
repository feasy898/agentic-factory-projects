# -*- coding: utf-8 -*-
"""Read the Vault JSON (github-feasy898) from stdin and embed the token into
the 5 repos' local remote URLs. The token never touches a central file."""
import json
import os
import subprocess
import sys

outer = json.load(sys.stdin)
d = (outer.get("data") or {}).get("data") or {}
if not d:
    sys.exit("vault payload empty: " + json.dumps(outer)[:200])
token = next(v for v in d.values() if isinstance(v, str) and v.startswith("ghp_"))

pairs = [
    ("chengmai-gov-ai-gateway", "政务AI脱敏网关"),
    ("chengmai-playable-ads", "可玩的小游戏广告"),
    ("chengmai-bean-eye", "咖啡豆质检"),
    ("chengmai-feeding-arm", "具身助餐机器人"),
    ("chengmai-drama-dub", "短剧多国出海"),
]
for repo, dname in pairs:
    path = os.path.join(r"D:\workspace\澄迈8项目", dname, "repo")
    subprocess.run(
        ["git", "remote", "set-url", "origin",
         "https://feasy898:" + token + "@github.com/feasy898/" + repo + ".git"],
        cwd=path, check=True,
    )
    print("SETURL", repo)
