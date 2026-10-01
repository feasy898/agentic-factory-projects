#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""p2_higress_call.py — P2 模型可读性验证（windev 侧执行，凭证不出本机进程内存）。

协议：
  * 密钥：ssh newbox 经 OpenBao 读 kv/company/gpu/models/higress-consumer 的 key 字段，
    只进内存变量，零打印零落盘（SYSTEM-GUIDE §7 argv-free 纪律）。
  * 图像：ssh dev-env-with-gpu cat 总览图（P1 产物，1600px 宽 <=12 格）。
  * 调用：POST http://100.100.0.6:8080/v1/chat/completions，model=glm-plan（Higress 暴露别名，
    上游 GLM-5.3-Flash），OpenAI 兼容 image_url(base64)。
  * 预算：本项目模型配额 <=5 次（worker-B），本脚本固定 2 次：
      golden_002（A 类 garble_text 注入 1.531-3.531s，期望检出乱码）
      golden_001（C 类干净对照，期望零误报）
  * 两条 clip 用完全相同的提示词，不泄漏期望答案。
输出：out/p2_results.json + 控制台只打 HTTP 状态/模型回内容/usage（不回显任何凭证）。
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import urllib.request
import urllib.error

GPU = "dev-env-with-gpu"
GPU_DIR = "/opt/gpumachine/projects/video-capability/research/proto/out"
HIGRESS = "http://100.100.0.6:8080/v1/chat/completions"
MODEL = "glm-plan"

PROMPT = (
    "你是严格的视频质检员。下面是一张视频关键帧总览图：格子按时间顺序从左到右、"
    "从上到下排列，每格下方标注 #序号 与该帧的时间戳（秒）。请逐格检查画面与画面上出现的文字，"
    "只输出一个 JSON，不要任何其他文字：\n"
    '{"cells_with_text": ["#编号", ...], "text_readout": "把各格读到的文字原样写出",'
    ' "garble_detected": 0或1, "defect_types": ["乱码文字"等类型或空列表],'
    ' "evidence": "一句话中文：哪些格、什么位置文字出现乱码/破碎/无意义字符",'
    ' "main_issue": "一句话中文，无缺陷则写无"}\n'
    "若某格文字太小看不清，在 text_readout 里对该格如实写（看不清），不要编造。"
)

CLIPS = ["golden_002", "golden_001"]  # 注入缺陷（期望检出）在前，干净对照（期望零误报）在后


def bao_key() -> str:
    """OpenBao 读 Higress consumer key（只进内存）。"""
    cmd = ['ssh', 'newbox',
           'RT=$(cat /etc/bao/root-token); '
           'docker exec -e BAO_ADDR=http://127.0.0.1:8200 -e BAO_TOKEN="$RT" '
           'company-bao-1 bao kv get -format=json kv/company/gpu/models/higress-consumer']
    res = subprocess.run(cmd, capture_output=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError("bao read failed: " + res.stderr.decode("utf-8", "replace")[:200])
    data = json.loads(res.stdout.decode("utf-8"))
    return data["data"]["data"]["key"]  # 字段名白名单：只取 key，不碰其他字段


def fetch_sheet(cid: str) -> bytes:
    cmd = ["ssh", GPU, "cat", f"{GPU_DIR}/{cid}/overview.jpg"]
    res = subprocess.run(cmd, capture_output=True, timeout=120)
    if res.returncode != 0 or not res.stdout.startswith(b"\xff\xd8"):
        raise RuntimeError(f"sheet fetch failed for {cid}: "
                           + res.stderr.decode("utf-8", "replace")[:200])
    return res.stdout


def call_higress(key: str, sheet: bytes) -> dict:
    b64 = base64.b64encode(sheet).decode()
    payload = {
        "model": MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                {"type": "text", "text": PROMPT},
            ],
        }],
        "temperature": 0,
        "max_tokens": 800,
    }
    req = urllib.request.Request(
        HIGRESS, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return {"http": r.status, "body": json.loads(r.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode("utf-8", "replace")[:400]}


def main() -> int:
    key = bao_key()
    print("key fetched: ok (never printed)")
    results = []
    for cid in CLIPS:
        sheet = fetch_sheet(cid)
        print(f"{cid}: sheet {len(sheet)} bytes fetched")
        resp = call_higress(key, sheet)
        entry = {"clip_id": cid, "http": resp["http"]}
        if resp["http"] == 200:
            body = resp["body"]
            content = body["choices"][0]["message"]["content"]
            entry["content"] = content
            entry["usage"] = body.get("usage")
            entry["model"] = body.get("model")
            print(f"{cid}: HTTP {resp['http']} model={body.get('model')}")
            print(f"  content: {content}")
            print(f"  usage: {body.get('usage')}")
        else:
            entry["error"] = resp["body"]
            print(f"{cid}: HTTP {resp['http']} ERROR {resp['body'][:200]}")
        results.append(entry)
    out = {"endpoint_host": "100.100.0.6:8080", "model": MODEL,
           "call_count": len(CLIPS), "results": results}
    with open("out/p2_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    ok = all(r["http"] == 200 for r in results)
    print("P2_CALLS_OK" if ok else "P2_CALLS_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
