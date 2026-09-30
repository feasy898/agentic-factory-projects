#!/usr/bin/env python3
# par_download.py — modelscope 多连接并行下载器（CDN 单连接限速 ~3MB/s，按连接数扩速）
# 安全: 仅允许 https + www.modelscope.cn（解析 IP 非私网/环回/链路本地）；路径规范化解法限制在 ROOT 内
# 用法: par_download.py <model_id> <local_root>
# 断点续传: 每文件 sidecar json 记录已完成 chunk；已存在且字节数正确的文件跳过
import argparse, ipaddress, json, os, re, socket, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ALLOWED_HOST = "www.modelscope.cn"
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
CHUNK = 16 << 20
WORKERS = int(os.environ.get("PAR_WORKERS", "4"))


def check_host(host):
    if host != ALLOWED_HOST:
        raise SystemExit(f"host not allowed: {host}")
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise SystemExit(f"resolved private/reserved IP blocked: {ip}")
    return host


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("model_id")
    p.add_argument("root")
    a = p.parse_args()
    if not MODEL_ID_RE.match(a.model_id):
        raise SystemExit(f"model_id rejected: {a.model_id}")
    root = os.path.realpath(a.root)
    if not os.path.isdir(root):
        os.makedirs(root, exist_ok=True)
    check_host(urllib.parse.urlsplit(f"https://{ALLOWED_HOST}").hostname)
    return a.model_id, root


def safe_join(root, rel):
    if rel.startswith("/") or ".." in rel.split("/") or "\x00" in rel:
        raise SystemExit(f"path rejected: {rel}")
    dst = os.path.realpath(os.path.join(root, rel))
    if os.path.commonpath([root, dst]) != root:
        raise SystemExit(f"path escapes root: {rel}")
    return dst


def get_json(url, retries=5):
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print("RETRY_JSON", i, repr(e)[:120]); time.sleep(3)
    raise RuntimeError("api fail " + url)


def dl_chunk(url, start, end, dst):
    for i in range(6):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=120) as r:
                final_url = r.geturl()
                if urllib.parse.urlsplit(final_url).scheme != "https":
                    raise IOError("redirect to non-https blocked")
                data = r.read()
            if len(data) != end - start + 1:
                raise IOError(f"short read {len(data)} != {end-start+1}")
            with open(dst, "r+b") as f:
                f.seek(start); f.write(data)
            return start // CHUNK
        except Exception as e:
            print("RETRY_CHUNK", start >> 20, "MB", repr(e)[:120]); time.sleep(2)
    raise RuntimeError("chunk fail " + dst)


def main():
    model_id, root = parse_args()
    api = f"https://{ALLOWED_HOST}/api/v1/models/{model_id}"
    files = get_json(api + "/repo/files?Recursive=true&PageSize=200")["Data"]["Files"]
    keep = ("model_index.json", "scheduler/", "text_encoder/", "tokenizer/", "transformer/", "vae/")
    todo = [f for f in files if f["Path"].startswith(keep) and f.get("Size", 0) > 0]
    print("PLAN", len(todo), "files", round(sum(f["Size"] for f in todo) / 1e9, 1), "GB", flush=True)

    jobs = []
    for f in todo:
        rel, size = f["Path"], f["Size"]
        dst = safe_join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        inc = dst + ".incomplete"
        if os.path.exists(dst) and os.path.getsize(dst) == size:
            print("SKIP_DONE", rel); continue
        if os.path.exists(inc) and os.path.getsize(inc) == size:
            os.replace(inc, dst); print("PROMOTED_INCOMPLETE", rel); continue
        for p in (dst, inc):
            if os.path.exists(p) and os.path.getsize(p) != size:
                print("TRUNCATE_WRONG_SIZE", p, os.path.getsize(p), "!=", size)
                os.remove(p)
        if not os.path.exists(dst):
            with open(dst, "wb") as fh:
                fh.truncate(size)
        n = (size + CHUNK - 1) // CHUNK
        side = dst + ".parts.json"
        done = set(json.load(open(side))) if os.path.exists(side) else set()
        jobs.append((rel, dst, size, n, done, side))

    pending = sum(n - len(d) for _, _, _, n, d, _ in jobs)
    print("PENDING_CHUNKS", pending, f"~{pending*CHUNK/1e9:.1f} GB", flush=True)
    t0 = time.time(); got = 0
    for rel, dst, size, n, done, side in jobs:
        if len(done) >= n:
            continue
        url = f"{api}/repo?FilePath=" + urllib.parse.quote(rel) + "&Revision=master"
        fin = 0
        with ThreadPoolExecutor(WORKERS) as ex:
            futs = {ex.submit(dl_chunk, url, ci * CHUNK, min(size, (ci + 1) * CHUNK) - 1, dst): ci
                    for ci in range(n) if ci not in done}
            for fu in as_completed(futs):
                ci = fu.result()
                done.add(ci); got += CHUNK; fin += 1
                if fin % 8 == 0:
                    json.dump(sorted(done), open(side, "w"))
                    rate = got / (time.time() - t0) / 1e6
                    print(f"PROG {rel} {fin}/{n} {rate:.1f} MB/s", flush=True)
        json.dump(sorted(done), open(side, "w"))
        if len(done) >= n:
            if os.path.exists(side): os.remove(side)
            print("FILE_DONE", rel, flush=True)
    dt = time.time() - t0
    if dt > 0:
        print(f"ALL_DONE {got/1e9:.2f}GB in {dt:.0f}s = {got/dt/1e6:.1f} MB/s")

    ok = True
    for f in todo:
        dst = safe_join(root, f["Path"])
        if not os.path.exists(dst) or os.path.getsize(dst) != f["Size"]:
            print("VERIFY_FAIL", f["Path"]); ok = False
    print("VERIFY_OK" if ok else "VERIFY_FAILED")


if __name__ == "__main__":
    main()
