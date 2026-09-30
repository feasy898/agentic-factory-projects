#!/usr/bin/env bash
# eval_b5.sh — B5 批次（M13 审校台 + M14 任务队列）模块 eval 入口。
# 离线为主：零 GPU 依赖；GPU tts(:9002) 未开隧道时 M13 在线用例按 skip-gpu 归因跳过
# （豁免口径同 gate_b4 ①：逐条归因为「服务不可达」才豁免，归因不了即 FAIL）。
# 全量 pytest / 整门不在本脚本口径（gate_b0~b4 为权威门，由 owner 直跑，避免真模型
# CPU 争载）；全仓中性名扫面同归 gate_b0 ④ / gate_b4 ⑥，本脚本只扫本批新增文件。
#
# 三步（逐项打印 [PASS]/[FAIL]，任何 FAIL 退出码 1）：
#   ① 两模块 pytest：tests/test_review_console.py（M13，9 用例=离线 8+在线 1）
#      + tests/test_queue.py（M14，17 用例）一次子进程跑完 —— failed/error 即 FAIL；
#      skipped 逐条归因：原因含「不可达」（服务连不通，隧道未起）才豁免并注明，
#      其余 skipped 即 FAIL（「跳过不算过」纪律沿 gate_b0 修订）；
#   ② 中性名扫描：token 表与 gate_b0 同源（import gate_b0.BANNED_TOKENS，动态加载
#      scripts/，禁止复制表）；仅扫本批新增/改动九件（T19+T20 交付物，含本脚本
#      自身）；文件缺失/后缀越出公开扫描集/任一 token 命中即 FAIL；
#   ③ 契约回归：python -m pipeline.cli validate 逐个校验既有 jsonl 样本（jobs 树下
#      五个 jsonl 契约 kinds 的全部存量样本；样本根取 pipeline.config.jobs_dir 单一
#      来源=configs/pipeline.yaml paths.jobs_dir）——任一样本校验失败、或任一 kind
#      在 jobs 树下连一个样本都没有（回归面出现空洞）即 FAIL。
# 用法: bash scripts/eval_b5.sh        （退出码即验收结果；任意 cwd 可运行）
set -uo pipefail
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

cd "$REPO_ROOT"
if [ -x ".venv/Scripts/python.exe" ]; then PY=.venv/Scripts/python.exe; else PY=.venv/bin/python; fi
export PYTHONUTF8=1

rc_all=0
LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT

echo "== ① 两模块 pytest（M13 审校台 + M14 任务队列）=="
"$PY" -m pytest tests/test_review_console.py tests/test_queue.py -q -ra 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then
  echo "[FAIL] ① pytest 退出码 $rc"
  rc_all=1
else
  # skipped 逐条归因：short summary（-ra）每条 SKIPPED 的原因必须含「不可达」
  bad_skips=$(grep -E "^SKIPPED " "$LOG" | grep -v "不可达" || true)
  n_skip=$(grep -oE "[0-9]+ skipped" "$LOG" | tail -1 | cut -d' ' -f1)
  n_skip=${n_skip:-0}
  if [ -n "$bad_skips" ]; then
    echo "[FAIL] ① pytest 有不可归因（非「服务不可达」）的 skipped："
    echo "$bad_skips" | sed 's/^/       /'
    rc_all=1
  elif [ "$n_skip" -gt 0 ]; then
    echo "[PASS] ① 两模块全绿；${n_skip} 个 skipped 全部归因为服务不可达（skip-gpu 豁免，隧道未开非代码问题）："
    grep -E "^SKIPPED " "$LOG" | sed 's/^/       /'
  else
    echo "[PASS] ① 两模块全绿零跳过"
  fi
fi

echo "== ② 中性名扫描（gate_b0 同源 token 表，仅扫本批新增/改动文件）=="
"$PY" - "$REPO_ROOT" <<'PYEOF'
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
import gate_b0 as b0  # token 表单一来源，禁止复制（gate_b2/b3/b4 同一先例）

# 本批（B5 = T19/M13 + T20/M14）新增/改动文件全集 + 本脚本自身（新公开文件自扫）
NEW_FILES = [
    "pipeline/review_server.py",     # T19/M13 审校台服务
    "tests/test_review_console.py",  # T19/M13 eval
    "configs/models.yaml",           # T19/M13 改动（登记 review-m13）
    "pipeline/queue.py",             # T20/M14 队列引擎
    "pipeline/m7_tts.py",            # T20/M14 配套（M7 模块 CLI）
    "pipeline/cli.py",               # T20/M14 改动（run 落地+enqueue/status/resume）
    "tests/test_queue.py",           # T20/M14 eval
    "tests/test_skeleton.py",        # T20/M14 改动（cli run 占位断言更新）
    "scripts/eval_b5.sh",            # 本脚本
]
bad = []
scanned = 0
for rel in NEW_FILES:
    p = root / rel
    if not p.is_file():
        bad.append(f"{rel}: 文件不存在（清单与仓库脱节，判 FAIL）")
        continue
    if Path(rel).suffix.lower() not in b0.SCAN_SUFFIXES:
        bad.append(f"{rel}: 后缀不在 gate_b0 公开扫描集 {sorted(b0.SCAN_SUFFIXES)}")
        continue
    text = p.read_bytes().decode("utf-8", "replace").lower()
    scanned += 1
    for tok in b0.BANNED_TOKENS:
        if tok in text:
            bad.append(f"{rel}: 命中被禁 token {tok!r}")
if bad:
    print("[FAIL] ② 中性名扫描")
    for ln in bad:
        print(f"       {ln}")
    sys.exit(1)
print(f"[PASS] ② gate_b0 同源 {len(b0.BANNED_TOKENS)} token × 本批 {scanned}/{len(NEW_FILES)} "
      "新增/改动文件，零命中（全仓扫面归 gate_b0④/gate_b4⑥，不在此重复）")
sys.exit(0)
PYEOF
rc=$?
if [ "$rc" -ne 0 ]; then rc_all=1; fi

echo "== ③ 契约回归（pipeline.cli validate 既有 jsonl 样本）=="
"$PY" - "$REPO_ROOT" <<'PYEOF'
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))
from pipeline.config import jobs_dir  # 样本根单一来源（configs/pipeline.yaml）

jroot = jobs_dir()
# 五个 jsonl 契约 kinds → jobs 树内样本定位（lang 变体 synth_plan.<lang>.jsonl 同 glob 覆盖）
PATTERNS = [
    ("diar", "04_dial/diar.jsonl"),
    ("utterances", "04_dial/utterances.jsonl"),
    ("translations", "06_mt/translations.jsonl"),
    ("synth-plan", "07_synth/synth_plan*.jsonl"),
    ("lip-plan", "09_lip/lip_plan*.jsonl"),
]
if not jroot.is_dir():
    print(f"[FAIL] ③ jobs 根不存在: {jroot}（无样本可回归）")
    sys.exit(1)
eps = sorted(d for d in jroot.iterdir() if d.is_dir())
samples: list[tuple[str, Path]] = []
for ep in eps:
    for kind, pat in PATTERNS:
        samples.extend((kind, f) for f in sorted(ep.glob(pat)))
if not samples:
    print(f"[FAIL] ③ {jroot} 下无任何契约 jsonl 样本（无样本可回归）")
    sys.exit(1)
fails: list[str] = []
for kind, f in samples:
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.cli", "validate", kind, str(f)],
        cwd=str(root), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120)
    out = (r.stdout or "").strip() or (r.stderr or "").strip()
    tag = "OK " if r.returncode == 0 else "FAIL"
    print(f"  [{tag}] {f.relative_to(jroot)}（{kind}）: {out.splitlines()[-1] if out else ''}")
    if r.returncode != 0:
        fails.append(f"{f}: exit {r.returncode}")
per_kind = {k: sum(1 for kk, _ in samples if kk == k) for k, _ in PATTERNS}
holes = [k for k, n in per_kind.items() if n == 0]
if holes:
    fails.append(f"契约 kinds 在 jobs 树下零样本（回归面空洞）: {holes}")
if fails:
    print("[FAIL] ③ 契约回归:")
    for ln in fails:
        print(f"       {ln}")
    sys.exit(1)
print(f"[PASS] ③ {len(samples)} 个存量 jsonl 样本全部校验通过"
      f"（{len(eps)} 个集工作区 × 五 kinds 覆盖: {per_kind}）")
sys.exit(0)
PYEOF
rc=$?
if [ "$rc" -ne 0 ]; then rc_all=1; fi

if [ "$rc_all" -eq 0 ]; then
  echo "== eval_b5: PASS =="
else
  echo "== eval_b5: FAIL =="
fi
exit "$rc_all"
