#!/usr/bin/env python
"""V2-M0: update MobileSAM status in audit docs (3rd resume attempt succeeded)."""
import io

def patch(path, pairs):
    s = io.open(path, encoding="utf-8").read()
    for old, new in pairs:
        assert old in s, "pattern not found in %s: %s" % (path, old[:60])
        s = s.replace(old, new)
    io.open(path, "w", encoding="utf-8").write(s)
    print("patched", path)

patch("/root/cradle/reports/V2_M0_AUDIT.md", [
    ("| MobileSAM(备份 40M) | **失败**(两次 github 截断至 3.5MB;ModelScope 无仓) | — | — | 备份不可用,不阻塞(主选 SAM ViT-B 已过;M1 前可重试) |",
     "| MobileSAM(备份) | 40.7M | github raw(两次截断后,第三次后台断点续传成功) | ~40min(约100KB/s) | **文件校验 OK**: torch.load 439 keys;fp16 前向自查留 M1 与主选并行 |"),
    ("2. MobileSAM 备份下载失败(github 大文件通道不稳,ModelScope 无仓)——主选 SAM ViT-B 可用,不阻塞 G7c(D-054);",
     "2. MobileSAM 备份下载两次截断后,由第三次后台断点续传完成(40.7M,torch.load 校验 439 keys 通过,fp16 前向自查留 M1)——主选 SAM ViT-B 不受影响(D-054);"),
])

patch("/root/cradle/DECISIONS.md", [
    ("③SAM ViT-B:transformers SamModel fp16 OK(0.4s,点提示 mask 3.9%);**MobileSAM 备份下载失败**(github 大文件通道两次截断,ModelScope 无仓)——不阻塞,主选已过,M1 前可重试;",
     "③SAM ViT-B:transformers SamModel fp16 OK(0.4s,点提示 mask 3.9%);MobileSAM 备份:github 通道两次截断(3.5MB 假完成)后,第三次后台 `curl -C -` 断点续传完成(40,728,226B,torch.load 校验 439 keys 通过,fp16 前向自查留 M1)——不阻塞;"),
])

patch("/root/cradle/PROGRESS.md", [
    ("pip matplotlib+lap 就绪;MobileSAM 备份下载失败不阻塞",
     "pip matplotlib+lap 就绪;MobileSAM 备份第三次断点续传成功(40.7M,torch.load 439 keys 校验通过)"),
])
print("PATCH_DONE")
