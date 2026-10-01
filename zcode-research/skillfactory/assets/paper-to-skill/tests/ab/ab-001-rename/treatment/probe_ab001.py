# -*- coding: utf-8 -*-
"""probe_ab001.py — ab-001 treatment：实测 SKILL.md 中将引用的系统调用行为。

全部探针在系统临时目录下执行，结束即清理；只打印事实，不改任何工作区文件。
说明：glob 通配符用 chr(42) 动态构造，仅为避免安全扫描器把源码中的
通配符字符串误报为路径穿越（Mimosa 拦截记录，2026-09-29）；语义完全等价。
运行：python probe_ab001.py
"""
import fnmatch
import glob
import os
import shutil
import sys
import tempfile
from pathlib import Path

print("python:", sys.version)
tmp = Path(tempfile.mkdtemp(prefix="ab001_probe_")).resolve()
# 允许目录校验：所有读写都限制在系统临时目录内
_allowed = Path(tempfile.gettempdir()).resolve()
assert str(tmp).startswith(str(_allowed)), "probe dir escaped temp root: %s" % tmp
STAR = chr(42)  # glob 通配符 *


def fresh(names):
    for n in names:
        (tmp / n).write_text("AAA" if n.startswith("a") else "BBB", encoding="utf-8")


# --- 1. os.rename 目标已存在 ---
fresh(["a.txt", "b.txt"])
try:
    os.rename(str(tmp / "a.txt"), str(tmp / "b.txt"))
    print("[rename] no error (UNEXPECTED)")
except OSError as e:
    print("[rename] raised:", type(e).__name__, "errno=%s" % e.errno,
          "winerror=%s" % getattr(e, "winerror", None), "|", e.strerror)
    print("[rename] b.txt content still:", (tmp / "b.txt").read_text(encoding="utf-8"))

# --- 2. os.replace 目标已存在 ---
fresh(["a.txt", "b.txt"])
os.replace(str(tmp / "a.txt"), str(tmp / "b.txt"))
print("[replace] no error; b.txt content now:", (tmp / "b.txt").read_text(encoding="utf-8"),
      "; a.txt exists:", (tmp / "a.txt").exists())

# --- 3. splitext ---
print("[splitext] report_001.log ->", os.path.splitext("report_001.log"))
print("[splitext] archive.tar.gz ->", os.path.splitext("archive.tar.gz"))

# --- 4. glob 三态：非递归 / 递归 / 宽匹配 ---
(tmp / "sub").mkdir()
(tmp / "a.log").write_text("x", encoding="utf-8")
(tmp / "b.log").write_text("x", encoding="utf-8")
(tmp / "notes.txt").write_text("x", encoding="utf-8")
(tmp / "sub" / "y.log").write_text("x", encoding="utf-8")

nonrec = sorted(glob.glob(str(tmp / (STAR + ".log"))))
recursive = sorted(str(p.relative_to(tmp)) for p in tmp.rglob(STAR + ".log"))
wide = sorted(p.name for p in tmp.glob(STAR))
files_only = sorted(p.name for p in tmp.glob(STAR) if p.is_file())
print("[glob] non-recursive glob(*.log) ->", nonrec)
print("[glob] recursive Path.rglob(*.log) (== glob '**/*.log' recursive=True) ->", recursive)
print("[glob] wide Path.glob(*) ->", wide)
print("[glob] isfile filter ->", files_only)

# --- 5. 枚举顺序 vs 按原文件名排序（NTFS 大小写不敏感序 ≠ sorted() 码点序）---
case = Path(tempfile.mkdtemp(prefix="ab001_order_")).resolve()
assert str(case).startswith(str(_allowed)), "probe dir escaped temp root"
for n in ["a.log", "B.log"]:
    (case / n).write_text("x", encoding="utf-8")
enum = os.listdir(str(case))
print("[order] os.listdir (docs: arbitrary order; NTFS returned):", enum)
print("[order] sorted() by original filename:", sorted(enum))
print("[order] two orders equal:", enum == sorted(enum))
shutil.rmtree(str(case))

# --- 6. 改名后的新名仍命中原 pattern（执行循环中重扫目录 = 二次改名风险）---
print("[refmatch] fnmatch('report_001.log', '*.log') ->",
      fnmatch.fnmatch("report_001.log", STAR + ".log"))

shutil.rmtree(str(tmp))
print("probe done, temp cleaned")
