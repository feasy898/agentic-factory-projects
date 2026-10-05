"""drama-pilot / m1_ingest 重生成 gate（供工作流调用；pytest 透传）。

门项：冻结测试 tests/test_m1.py（7 用例，spec §4 eval：7 passed）全绿 = 门过。
- ffmpeg/ffprobe 位于 D:/tools/bin：gate 注入 PATH 后再起 pytest 子进程
  （spec m1-ingest §4：pytest 子进程需 PATH 可解析 ffmpeg）。
- 透传：命令行附加参数原样追加给 pytest；pytest 退出码原样作为 gate 退出码。
- 夹具纪律：tests/test_m1.py sha256 运行前后各自检一次（测试一字不改）。

用法：python gate.py [pytest 附加参数…]
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


def main(argv: list[str]) -> int:
    test_path = ROOT / TEST_REL
    before = _sha256(test_path)
    if before != FROZEN_TEST_SHA256:
        print(f"[FROZEN] FAIL —— {TEST_REL} 被改动：{before}")
        return 1
    print(f"[FROZEN] PASS —— {TEST_REL} sha256 未变（{FROZEN_TEST_SHA256[:12]}…）")

    env = {**os.environ, "PYTHONUTF8": "1"}
    injected = [d for d in FFMPEG_DIRS if Path(d).is_dir()]
    env["PATH"] = os.pathsep.join([*injected, env.get("PATH", "")])
    found = shutil.which("ffmpeg", path=env["PATH"])
    print(f"[GATE] PATH 注入 {injected}；which(ffmpeg)={found}")
    if found is None:
        print("[GATE] FAIL —— 注入后仍解析不到 ffmpeg")
        return 1

    cmd = [sys.executable, "-m", "pytest", TEST_REL, *argv]
    print("[GATE]", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)

    after = _sha256(test_path)
    if after != FROZEN_TEST_SHA256:
        print(f"[FROZEN-AFTER] FAIL —— gate 结束后测试被改动：{after}")
        return 1
    print("[FROZEN-AFTER] PASS")
    return proc.returncode


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main(sys.argv[1:]))
