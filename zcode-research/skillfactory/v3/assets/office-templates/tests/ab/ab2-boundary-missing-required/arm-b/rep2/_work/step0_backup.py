# -*- coding: utf-8 -*-
"""step0: 运行前快照 — 把 oracle/out 与 package/out 中请示函/会议通知 case2 的既有产物备份到 _work/backup。"""
import shutil, hashlib, os, sys

ROOT = r"D:\workspace\zcode研究\skillfactory\v3\assets\office-templates"
WORK = os.path.join(ROOT, r"tests\ab\ab2-boundary-missing-required\arm-b\rep2\_work")
BK = os.path.join(WORK, "backup")

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

items = [
    (r"oracle\out\请示函\case2", r"oracle_out\请示函_case2"),
    (r"oracle\out\会议通知\case2", r"oracle_out\会议通知_case2"),
    (r"package\out\请示函\case2", r"package_out\请示函_case2"),
    (r"package\out\会议通知\case2", r"package_out\会议通知_case2"),
]
manifest = []
for src_rel, dst_rel in items:
    src = os.path.join(ROOT, src_rel)
    dst = os.path.join(BK, dst_rel)
    if not os.path.isdir(src):
        print(f"[MISS] {src_rel} 不存在，跳过")
        continue
    shutil.copytree(src, dst)
    for fn in sorted(os.listdir(dst)):
        fp = os.path.join(dst, fn)
        manifest.append((dst_rel, fn, sha256(fp)))
        print(f"[BAK] {dst_rel}\\{fn} sha256={sha256(fp)[:16]}")

with open(os.path.join(WORK, "backup_manifest.txt"), "w", encoding="utf-8") as f:
    for rel, fn, h in manifest:
        f.write(f"{rel}\\{fn}\t{h}\n")
print(f"[DONE] 共备份 {len(manifest)} 个文件 → {BK}")
