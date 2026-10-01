#!/usr/bin/env bash
# 可复现验证脚本：重建 fixtures，重跑 mv/os.rename/os.replace 探针 + T1..T7，
# 全部输出逐字写入 transcript.txt。cwd 必须是本文件所在目录（verify/）。
set -u
PY=python

# ---------- 0) 环境与清理 ----------
rm -rf fixtures-log fixtures-mixed fixtures-case probe rename-log.tsv transcript.txt
mkdir -p fixtures-log/subdir fixtures-mixed/subdir2 fixtures-case probe

{
  echo "=== environment ==="
  date '+%Y-%m-%d %H:%M:%S %z'
  uname -s -m
  $PY --version 2>&1
  echo "mv path: $(which mv)"
  echo "cwd: $(pwd)"
} > transcript.txt

# ---------- 1) 探针：mv / os.rename / os.replace ----------
{
  echo
  echo "=== P0: probe mv default behavior (dst already exists) ==="
  printf 'A' > probe/a1.txt; printf 'B' > probe/b1.txt
  mv probe/b1.txt probe/a1.txt
  echo "mv exit=$?; a1.txt=$(cat probe/a1.txt); b1.txt still exists: $([ -e probe/b1.txt ] && echo yes || echo no)"

  echo
  echo "=== P1: probe mv -n (dst already exists) ==="
  printf 'A' > probe/a2.txt; printf 'B' > probe/b2.txt
  mv -n probe/b2.txt probe/a2.txt
  echo "mv -n exit=$?; a2.txt=$(cat probe/a2.txt); b2.txt still exists: $([ -e probe/b2.txt ] && echo yes || echo no)"

  echo
  echo "=== P2: probe python os.rename / os.replace on win32 ==="
  $PY verify_os_rename.py
} >> transcript.txt

# ---------- 2) fixture setup ----------
printf 'AAA' > fixtures-log/alpha.log
printf 'BBB' > fixtures-log/beta.log
printf 'GGG' > fixtures-log/gamma.log
printf 'NOT-MATCHED' > fixtures-log/notes.txt
printf 'R002' > fixtures-log/report_002.log
printf 'INNER' > fixtures-log/subdir/inner.log
printf 'aa' > fixtures-mixed/a.log
printf 'bb' > fixtures-mixed/b.txt
printf 'cc' > fixtures-mixed/c.TXT
printf 'xx' > fixtures-mixed/subdir2/x.log
printf 'U' > fixtures-case/upper.LOG

{
  echo
  echo "=== fixture setup ==="
  find fixtures-log fixtures-mixed fixtures-case -mindepth 1 | LC_ALL=C sort
} >> transcript.txt

# ---------- T1: fixtures-log dry-run ----------
{
  echo
  echo "=== T1: dry-run on fixtures-log (pattern *.log, prefix report_) ==="
  $PY rename_files.py fixtures-log --pattern '*.log' --prefix 'report_'
  echo "exit=$?"
} >> transcript.txt

# ---------- T2: dry-run 后目录未变 ----------
{
  echo
  echo "=== T2: fixtures-log unchanged after dry-run ==="
  find fixtures-log -mindepth 1 | LC_ALL=C sort
  echo "notes.txt still present: $([ -e fixtures-log/notes.txt ] && echo yes || echo no)"
} >> transcript.txt

# ---------- T3: apply ----------
{
  echo
  echo "=== T3: apply on fixtures-log ==="
  $PY rename_files.py fixtures-log --pattern '*.log' --prefix 'report_' --apply
  echo "exit=$?"
} >> transcript.txt

# ---------- T4: apply 后状态与清单对账 ----------
{
  echo
  echo "=== T4: post-apply state ==="
  for f in report_001.log beta.log report_002.log report_003.log report_004.log; do
    if [ -e "fixtures-log/$f" ]; then echo "fixtures-log/$f = $(cat "fixtures-log/$f")"; else echo "fixtures-log/$f = MISSING"; fi
  done
  echo "fixtures-log/notes.txt = $(cat fixtures-log/notes.txt)"
  echo "fixtures-log/subdir/inner.log = $(cat fixtures-log/subdir/inner.log)"
  echo "--- rename-log.tsv (written to cwd, NOT the target dir) ---"
  cat rename-log.tsv
} >> transcript.txt

# ---------- T5: 同参数重跑 apply（扰动观察） ----------
{
  echo
  echo "=== T5: re-apply same command (rerun perturbation) ==="
  $PY rename_files.py fixtures-log --pattern '*.log' --prefix 'report_' --apply
  echo "exit=$?"
} >> transcript.txt

# ---------- T6: fixtures-mixed dry-run（扩展名保留、目录排除） ----------
{
  echo
  echo "=== T6: dry-run on fixtures-mixed (pattern *): extension preserved, dirs excluded ==="
  $PY rename_files.py fixtures-mixed --pattern '*' --prefix 'report_'
  echo "exit=$?"
} >> transcript.txt

# ---------- T7: win32 glob 大小写探测 ----------
{
  echo
  echo "=== T7: probe - case sensitivity of *.log glob on win32 ==="
  $PY -c "import glob; print('glob *.log matches:', glob.glob('fixtures-case/*.log'))"
} >> transcript.txt

echo "transcript written: $(pwd)/transcript.txt"
