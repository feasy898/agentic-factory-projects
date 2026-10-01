# -*- coding: utf-8 -*-
"""实测 Windows 上 os.rename / os.replace 对已存在目标文件的行为。

验证目的：证明批量重命名不能依赖 rename 系统调用的默认行为来防止覆盖，
必须在重命名前做显式存在性检查。
运行：python verify_os_rename.py
"""
import os
import sys
import tempfile
from pathlib import Path

work = Path(tempfile.mkdtemp(prefix="rename_probe_")).resolve()
a = work / "a.txt"
b = work / "b.txt"
c = work / "c.txt"
a.write_text("A", encoding="utf-8")
b.write_text("B", encoding="utf-8")
c.write_text("C", encoding="utf-8")

print("platform:", sys.platform)
print("target a.txt exists before:", a.exists())

# 1) os.rename 到已存在的目标
try:
    os.rename(str(b), str(a))
    print("os.rename(b -> existing a): NO ERROR -> OVERWROTE, a.txt =",
          a.read_text(encoding="utf-8"))
except OSError as e:
    print("os.rename(b -> existing a): raised ->", type(e).__name__, "-", e)
    print("  after failed rename: a.txt =", a.read_text(encoding="utf-8"),
          "; b.txt still exists:", b.exists())

# 2) os.replace 到已存在的目标
os.replace(str(c), str(a))
print("os.replace(c -> existing a): NO ERROR -> OVERWROTE, a.txt =",
      a.read_text(encoding="utf-8"), "; c.txt gone:", not c.exists())

# 3) 显式 exists 检查（skill 规定的做法）
if a.exists():
    print("explicit exists-check on existing target: would SKIP, not touching files")
