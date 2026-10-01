# -*- coding: utf-8 -*-
"""Embed the feasy898 token into the 5 repos' local remote URLs (survives
~/.git-credentials being wiped). Reads token from the just-restored file."""
import os
import subprocess

cred = open(r"C:\Users\Administrator\.git-credentials").read().strip()
token = cred.split(":")[2].split("@")[0]
assert token.startswith("ghp_"), "unexpected token format"

pairs = [
    ("chengmai-gov-ai-gateway", "政务AI脱敏网关"),
    ("chengmai-playable-ads", "可玩的小游戏广告"),
    ("chengmai-bean-eye", "咖啡豆质检"),
    ("chengmai-feeding-arm", "具身助餐机器人"),
    ("chengmai-drama-dub", "短剧多国出海"),
]
for repo, d in pairs:
    path = os.path.join(r"D:\workspace\澄迈8项目", d, "repo")
    subprocess.run(
        ["git", "remote", "set-url", "origin",
         "https://feasy898:" + token + "@github.com/feasy898/" + repo + ".git"],
        cwd=path, check=True,
    )
    print("SETURL", repo)
