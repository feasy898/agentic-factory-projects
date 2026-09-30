# M1 Volta self-check for PROJECT CRADLE (SPECS section 3 + parent M1 task)
# Outputs a report to reports/milestones/m1_volta_check.txt
import sys, time, json, traceback

import torch
import torch.nn.functional as F

OUT = "/root/cradle/reports/milestones/m1_volta_check.txt"
lines = []

def log(s=""):
    print(s)
    lines.append(str(s))

def main():
    log("=== M1 VOLTA SELF-CHECK ===")
    log(f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"python: {sys.version.split()[0]}  torch: {torch.__version__}")
    log(f"torch.version.cuda: {torch.version.cuda}")
    log(f"cudnn: {torch.backends.cudnn.version()}")

    ok = True
    # 1) CUDA available
    cuda_ok = torch.cuda.is_available()
    log(f"[1] cuda_available: {cuda_ok}")
    ok &= cuda_ok
    if not cuda_ok:
        raise SystemExit(write_fail())

    # 2) device capability == (7,0)
    cap = torch.cuda.get_device_capability(0)
    name = torch.cuda.get_device_name(0)
    log(f"[2] device: {name}  capability: {cap}")
    ok &= (cap == (7, 0))

    # 3) fp16 matmul forward
    try:
        a = torch.randn(256, 256, device="cuda", dtype=torch.float16)
        b = torch.randn(256, 256, device="cuda", dtype=torch.float16)
        c = a @ b
        torch.cuda.synchronize()
        assert torch.isfinite(c.float()).all().item()
        log(f"[3] fp16 matmul forward: OK (c[0,0]={c[0,0].item():.3f})")
    except Exception as e:
        ok = False
        log(f"[3] fp16 matmul forward: FAIL {e}")

    # 4) scaled_dot_product_attention forward (fp16)
    try:
        q = torch.randn(1, 4, 128, 64, device="cuda", dtype=torch.float16)
        k = torch.randn(1, 4, 128, 64, device="cuda", dtype=torch.float16)
        v = torch.randn(1, 4, 128, 64, device="cuda", dtype=torch.float16)
        o = F.scaled_dot_product_attention(q, k, v)
        torch.cuda.synchronize()
        assert torch.isfinite(o.float()).all().item()
        log(f"[4] SDPA fp16 forward: OK (shape={tuple(o.shape)}, mean={o.float().mean().item():.5f})")
    except Exception as e:
        ok = False
        log(f"[4] SDPA fp16 forward: FAIL {e}")

    # 5) 2048^3 fp16 matmul timing
    try:
        n = 2048
        a = torch.randn(n, n, device="cuda", dtype=torch.float16)
        b = torch.randn(n, n, device="cuda", dtype=torch.float16)
        for _ in range(3):  # warmup
            c = a @ b
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        iters = 10
        for _ in range(iters):
            c = a @ b
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) / iters
        flops = 2 * n**3 / dt / 1e12
        log(f"[5] fp16 matmul {n}^3: {dt*1000:.2f} ms/iter ({flops:.2f} TFLOPS fp16)")
        del a, b, c
    except Exception as e:
        ok = False
        log(f"[5] fp16 matmul timing: FAIL {e}")

    mem_peak = torch.cuda.max_memory_allocated() / 1024**2
    log(f"[6] cuda.max_memory_allocated in this check: {mem_peak:.1f} MiB")
    log(f"RESULT: {'PASS' if ok else 'FAIL'}")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nwritten: {OUT}")
    return 0 if ok else 1

def write_fail():
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 1

if __name__ == "__main__":
    try:
        rc = main()
    except Exception:
        traceback.print_exc()
        lines.append(traceback.format_exc())
        lines.append("RESULT: FAIL")
        with open(OUT, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        rc = 1
    sys.exit(rc)
