"""drama2 / m1_ingest 重生成 gate（工作流调用）。

门项：冻结测试 tests/test_m1.py（7 用例，spec §4 eval：7 passed 零 skipped）全绿 = 门过。
- ffmpeg/ffprobe 位于 D:/tools/bin：gate 注入 PATH 后再起 pytest 子进程（spec §4 skipif 触发条件=
  PATH 解析不到 ffmpeg/ffprobe，注入后 7 个 skipif 不得触发）。
- 夹具纪律：tests/test_m1.py sha256 运行前后各检一次（冻结测试一字不改）。
- skipped 即 FAIL：pytest 退出码之后校验输出无 skipped 行，防「有跳过、无失败」假绿。

用法：python gate.py
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEST_REL = "tests/test_m1.py"
FROZEN_TEST_SHA256 = "00e54b184e4e8ddcf2cd8ab5f45089cb879668446c239d6fd08334cb6577b205"
FFMPEG_DIRS = [r"D:/tools/bin"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    test_path = ROOT / TEST_REL
    before = _sha256(test_path)
    if before != FROZEN_TEST_SHA256:
        print(f"[FROZEN] FAIL —— {TEST_REL} 被改动：{before}")
        return 1
    print(f"[FROZEN] PASS —— {TEST_REL} sha256 未变（{FROZEN_TEST_SHA256[:12]}…）")

    env = {**os.environ, "PYTHONUTF8": "1"}
    injected = [d for d in FFMPEG_DIRS if Path(d).is_dir()]
    env["PATH"] = os.pathsep.join([*injected, env.get("PATH", "")])
    found_ff = shutil.which("ffmpeg", path=env["PATH"])
    found_fp = shutil.which("ffprobe", path=env["PATH"])
    print(f"[GATE] PATH 注入 {injected}；which(ffmpeg)={found_ff}；which(ffprobe)={found_fp}")
    if found_ff is None or found_fp is None:
        print("[GATE] FAIL —— 注入后仍解析不到 ffmpeg/ffprobe（7 个 skipif 会全触发）")
        return 1

    cmd = [sys.executable, "-m", "pytest", TEST_REL, "-ra"]
    print("[GATE]", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    tail = (proc.stdout or "") + (proc.stderr or "")
    print(tail[-2500:])

    after = _sha256(test_path)
    if after != FROZEN_TEST_SHA256:
        print(f"[FROZEN-AFTER] FAIL —— gate 结束后测试被改动：{after}")
        return 1
    print("[FROZEN-AFTER] PASS")

    if proc.returncode != 0:
        print(f"[GATE] FAIL —— pytest 退出码 {proc.returncode}")
        return proc.returncode
    # skipped 即 FAIL：exit 0 但出现 skipped 概要仍是假绿，显式拦截
    for line in tail.splitlines():
        s = line.strip()
        if s.startswith("SKIPPED") or " skipped" in s or s.endswith("skipped"):
            print(f"[GATE] FAIL —— 检出 skipped 行：{s}")
            return 1
    print("[GATE] PASS —— 7 passed 零 skipped")
    return 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
