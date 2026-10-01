# -*- coding: utf-8 -*-
"""Create the 5 public GitHub repos under feasy898. Idempotent."""
import json
import re
import sys
import urllib.request

REPOS = [
    ("chengmai-feeding-arm", "桌面助餐机械臂：学习型舀取、安全送达嘴边、进食数据记录（澄迈大赛作品仓库）"),
    ("chengmai-playable-ads", "HTML5 试玩广告生产线：模板+配置生成、多渠道打包、自动质检、多语言（澄迈大赛作品仓库）"),
    ("chengmai-bean-eye", "咖啡生豆桌面质检台：双面瑕疵识别计数、粒度色泽计量、标准定级、三语质量护照（澄迈大赛作品仓库）"),
    ("chengmai-gov-ai-gateway", "政务 AI 安全网关：敏感信息三层识别、会话稳定可逆脱敏、敏感度路由、输出标识、审计看板（澄迈大赛作品仓库）"),
    ("chengmai-drama-dub", "短剧出海本地化引擎：音色保留配音、时长对齐、口型同步、字幕重渲染、合规报告（澄迈大赛作品仓库）"),
]


def read_token():
    with open(r"C:\Users\Administrator\.git-credentials", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"https://feasy898:([^@]+)@github\.com", line.strip())
            if m:
                return m.group(1)
    sys.exit("no feasy898 token found")


def api(method, path, token, body=None):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        data=json.dumps(body).encode() if body else None,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "orchestrator",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def main():
    token = read_token()
    for name, desc in REPOS:
        status, body = api("POST", "/user/repos", token,
                           {"name": name, "description": desc, "private": False})
        if status == 201:
            print(f"CREATED {body['full_name']}")
        elif status == 422 and any("already exists" in str(e.get("message", "")).lower()
                                   for e in body.get("errors", [])):
            s2, b2 = api("GET", f"/repos/feasy898/{name}", token)
            print(f"EXISTS  {b2.get('full_name', name)} (private={b2.get('private')})")
        else:
            print(f"ERROR   {name}: {status} {body.get('message')}")


if __name__ == "__main__":
    main()
