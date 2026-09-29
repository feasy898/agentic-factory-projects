"""assetkit 的 Node 助手调用：一份 JSON 任务 stdin 进，末行 JSON 结果出。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import AssetkitError

NODE_HELPER = Path(__file__).resolve().parent / "node" / "optimize.mjs"


def run_helper(payload: dict, timeout_sec: float = 300) -> dict:
    """跑 node 助手并解析其末行 JSON；node 缺失或助手崩溃 → AssetkitError。"""
    if shutil.which("node") is None:
        raise AssetkitError("未找到 node（压图/图集需要 Node.js + sharp）", 2)
    proc = subprocess.run(
        ["node", str(NODE_HELPER)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout_sec,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-8:])
        raise AssetkitError(f"node 助手失败（exit {proc.returncode}）：\n{tail or '(无输出)'}")
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        raise AssetkitError("node 助手无输出（异常退出？）")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise AssetkitError(f"node 助手输出不可解析：{lines[-1][:200]!r}（{exc}）") from exc
