#!/usr/bin/env python3
"""Parallel ranged prefetcher: HF repo -> local dir (typically /dev/shm tmpfs).

Rationale: anolis public egress is ~0.6MB/s (CVM bandwidth package) so sshfs from
anolis stalls; hf-mirror from this machine gives ~8MB/s single stream and scales
with parallel range requests. Revisions are pinned to the exact commits used on
anolis so the weights are identical to the smoke-validated deployment.

Usage:
  python prefetch_model.py <repo_id> <revision> <dest_dir> [--workers 8] \
      [--endpoint https://hf-mirror.com] [--expect-sizes json_file]

Writes <dest_dir>/.PREFETCH_OK when all files match the remote manifest sizes.
"""
import argparse
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# Force IPv4: some CDN redirect targets resolve to black-holed IPv6 here and
# urllib's sequential connect hangs (curl survives via happy-eyeballs, urllib not).
_orig_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_v4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _getaddrinfo_v4

CHUNK = 128 * 1024 * 1024  # 128MB per range request


UA = "Mozilla/5.0 (X11; Linux x86_64) prefetch-model/1.0"


def http(url, headers=None, timeout=60):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("仅允许 https 端点（防 SSRF/明文劫持），收到：%s" % parsed.scheme)
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    return urllib.request.urlopen(req, timeout=timeout)


def safe_rel(dest, rel):
    """把远端清单返回的相对路径并入 dest，拒绝绝对路径/盘符/.. 穿越与空段。"""
    if not rel or rel.strip() == "":
        raise ValueError("空路径")
    pure = rel.replace("\\", "/")
    if os.path.isabs(pure) or ":" in pure.split("/")[0] or ".." in pure.split("/"):
        raise ValueError("远端清单路径不合规（拒绝穿越）：%r" % rel)
    joined = os.path.join(dest, *pure.split("/"))
    real_dest = os.path.realpath(dest)
    real_joined = os.path.realpath(joined)
    if os.path.commonpath([real_dest, real_joined]) != real_dest:
        raise ValueError("路径越出目标目录：%r" % rel)
    return joined


def list_files(repo, revision, endpoint, source="hf"):
    if source == "modelscope":
        url = "%s/api/v1/models/%s/repo/files?Recursive=true&Revision=%s" % (
            endpoint, repo, revision)
        with http(url) as r:
            tree = json.load(r)
        out = []
        for it in tree["Data"]["Files"]:
            if it.get("Type") != "blob":
                continue
            p = it["Path"]
            if p == ".gitattributes":
                continue
            out.append((p, int(it.get("Size", 0))))
    else:
        url = "%s/api/models/%s/tree/%s?recursive=true" % (endpoint, repo, revision)
        with http(url) as r:
            tree = json.load(r)
        out = []
        for it in tree:
            if it.get("type") != "file":
                continue
            p = it["path"]
            if p.startswith(".cache/") or p == ".gitattributes":
                continue
            out.append((p, int(it.get("size", 0))))
    if not out:
        raise RuntimeError("empty tree for %s@%s" % (repo, revision))
    return out


def file_url(repo, revision, endpoint, source, path):
    if source == "modelscope":
        return "%s/api/v1/models/%s/repo?Revision=%s&FilePath=%s" % (
            endpoint, repo, revision, urllib.parse.quote(path))
    return "%s/%s/resolve/%s/%s" % (endpoint, repo, revision, path)


def fetch_chunk(url, dest, start, end, tries=4):
    for a in range(tries):
        try:
            with http(url, {"Range": "bytes=%d-%d" % (start, end)}, timeout=300) as r:
                if r.status not in (200, 206):
                    raise RuntimeError("http %s" % r.status)
                with open(dest, "r+b") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left > 0:
                        buf = r.read(min(1 << 20, left))
                        if not buf:
                            raise RuntimeError("short read")
                        f.write(buf)
                        left -= len(buf)
            return end - start + 1
        except Exception as e:
            if a == tries - 1:
                raise
            time.sleep(3 * (a + 1))


def fetch_small(url, dest, tries=4):
    for a in range(tries):
        try:
            with http(url, timeout=120) as r:
                data = r.read()
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return len(data)
        except Exception:
            if a == tries - 1:
                raise
            time.sleep(3 * (a + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("revision")
    ap.add_argument("dest")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--endpoint", default="https://hf-mirror.com")
    ap.add_argument("--source", choices=["hf", "modelscope"], default="hf")
    ap.add_argument("--expect-sizes", help="JSON {path:size} sanity check (e.g. from anolis)")
    a = ap.parse_args()
    if a.source == "modelscope" and a.endpoint == "https://hf-mirror.com":
        a.endpoint = "https://modelscope.cn"

    os.makedirs(a.dest, exist_ok=True)
    files = list_files(a.repo, a.revision, a.endpoint, a.source)
    if a.expect_sizes:
        want = json.load(open(a.expect_sizes))
        mismatch = {p: (s, want.get(p)) for p, s in files if p in want and want.get(p) not in (None, s)}
        if mismatch:
            print("[prefetch] WARNING size mismatch vs reference: %s" % mismatch, flush=True)

    total = sum(s for _, s in files)
    print("[prefetch] %s@%s -> %s : %d files, %.2f GB" %
          (a.repo, a.revision[:10], a.dest, len(files), total / 1e9), flush=True)
    jobs = []   # (url, path, kind, start, end)
    for p, s in files:
        dest = safe_rel(a.dest, p)
        os.makedirs(os.path.dirname(dest) or a.dest, exist_ok=True)
        if os.path.exists(dest) and os.path.getsize(dest) == s:
            if s <= 8 * 1024 * 1024 or os.path.exists(dest + ".ok"):
                continue          # small files are written atomically; big ones need .ok
        for stale in (dest, dest + ".ok", dest + ".part"):
            if os.path.exists(stale):
                os.remove(stale)
        url = file_url(a.repo, a.revision, a.endpoint, a.source, p)
        if s <= 8 * 1024 * 1024:
            jobs.append((url, dest, "small", 0, s - 1))
        else:
            with open(dest, "wb") as f:      # preallocate (sparse)
                f.truncate(s)
            for st in range(0, s, CHUNK):
                jobs.append((file_url(a.repo, a.revision, a.endpoint, a.source, p),
                             dest, "chunk", st, min(st + CHUNK, s) - 1))

    t0 = time.time()
    done_bytes = 0
    errs = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_chunk if k == "chunk" else fetch_small, u, d, s, e)
                if k == "chunk" else ex.submit(fetch_small, u, d): (u, d, k)
                for u, d, k, s, e in jobs}
        for fu in as_completed(futs):
            u, d, k = futs[fu]
            try:
                done_bytes += fu.result()
            except Exception as ex2:
                errs.append("%s: %s" % (os.path.basename(d), ex2))
    dt = time.time() - t0
    if errs:
        print("[prefetch] FAILED (%d errors): %s" % (len(errs), errs[:5]), flush=True)
        sys.exit(1)
    # verify sizes
    bad = [p for p, s in files
           if not os.path.exists(safe_rel(a.dest, p))
           or os.path.getsize(safe_rel(a.dest, p)) != s]
    if bad:
        print("[prefetch] FAILED size verify: %s" % bad, flush=True)
        sys.exit(1)
    for p, s in files:                    # per-file completion markers (big files only)
        if s > 8 * 1024 * 1024:
            open(safe_rel(a.dest, p) + ".ok", "w").close()
    print("[prefetch] OK %.2f GB in %.0fs (%.1f MB/s avg)" %
          (total / 1e9, dt, done_bytes / max(dt, 0.1) / 1e6), flush=True)
    with open(os.path.join(a.dest, ".PREFETCH_OK"), "w") as f:
        f.write("%s@%s at %s\n" % (a.repo, a.revision, time.strftime("%F %T")))


if __name__ == "__main__":
    main()
