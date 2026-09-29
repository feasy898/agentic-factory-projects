# GPU 隧道与保活 spec（ops/tunnel_gpu.sh + GpuClient 约定）

> 状态：frozen。对照 `ops/tunnel_gpu.sh`（112 行全文）、`pipeline/gpu_client.py`、`pipeline/tts_client.py`、
> gate_b1/b2 docstring 环境注记核验于 2026-09-29。

## 1. 为什么需要隧道（拓扑事实）

- GPU 侧三个 FastAPI 服务（:9001 asr_align / :9002 tts / :9004 mt）**只监听 GPU 机 127.0.0.1**
  （该机有公网出口，不对公网暴露端口——安全定案，service.py 各自 docstring）。
- **tailnet 数据面本机→GPU 机方向实测不通** → 隧道走 ssh config 里的**公网 Host 条目**
  （默认 `TUNNEL_GPU_HOST=dev-env-with-gpu`；ssh -L 到 GPU 机回环）。
- 因此本机客户端默认地址就是本机端口：`http://127.0.0.1:9001` / `:9002` / `:9004`
  （gpu_client.SERVICE_ENV / tts_client.SERVICE_ENV）。

## 2. 命令面（幂等，可重跑）

```
bash ops/tunnel_gpu.sh            # start：先清理同端口旧隧道再拉起；健康检查 20×1s
bash ops/tunnel_gpu.sh status     # /health 探测，UP 打印服务 health JSON
bash ops/tunnel_gpu.sh stop       # Windows netstat -ano 抓 LISTENING PID → taskkill //F
bash ops/tunnel_gpu.sh restart
bash ops/tunnel_gpu.sh keepalive  # 保活循环（nohup 后台常驻）
```

- 环境变量：`TUNNEL_GPU_HOST` / `TUNNEL_LOCAL_PORT` / `TUNNEL_REMOTE_PORT`（默认全 9001）。
- ssh 参数：`-N -L 127.0.0.1:<local>:127.0.0.1:<remote>` + `BatchMode` / `ConnectTimeout=15` /
  `ExitOnForwardFailure=yes` / **`ServerAliveInterval=30 -o ServerAliveCountMax=4`**（公网 NAT 保活）/
  `ControlMaster=no -o ControlPath=none`（Windows 控制套接字不可靠，禁用复用）。
- 日志：`tmp/tunnel_gpu.log`（tmp/ 不入库）。
- **多服务端口区分（T10 增补，只增不改行为）**：非 9001 端口 → 日志 `tmp/tunnel_gpu.<port>.log`、
  keepalive 锁 `~/.tunnel_keepalive.<port>.lock`；**9001 的文件名与历史逐字一致**
  （`tmp/tunnel_gpu.log` / `~/.tunnel_keepalive.lock`）——存量单实例锁不受影响，防双实例竞争。

## 3. keepalive（v2，B1 收口）

- **背景**：公网 ssh 链路周期性 reset，reset→重建有 **~10s 愈合窗**，期间经隧道的服务用例瞬时
  GpuServiceError/假红。
- 机制：每 `KA_INTERVAL_S`（默认 5s）探测一次 `/health`（curl -sf -m 3）；不通 → 幂等 `do_start`；
  **拉起失败不并发叠加**（`health || sleep 2` 交下一轮重试）——把愈合窗收敛为秒级自愈。
- **单实例锁** `~/.tunnel_keepalive.lock`（v2）：写 pid、`kill -0` 检活——防多实例竞争导致的
  `bind: Address already in use` 连锁失败（历史坑：多实例互相拉起）。
- 用法：`nohup bash ops/tunnel_gpu.sh keepalive >> tmp/tunnel_keepalive.log 2>&1 &`（每端口一个，
  锁按端口区分）。

## 4. 客户端侧配套（消除瞬时假红）

| 层 | 定案 | 出处 |
|---|---|---|
| 服务用例 retries | m4/m3 服务依赖用例 `GpuClient retries 0→5`（间隔 3s）——覆盖 ~10s 愈合窗 | commit 07dfd62（B1 复核 round2） |
| 默认客户端 retries | gpu_client / tts_client 默认 2 次 ×2s | gpu_client.py:41-43 / tts_client.py:93-95 |
| 门禁豁免 | `--skip-gpu` 只豁免"服务不可达"类跳过且**逐条归因**（tts/9002 归 :9002、asr_align/9001 归 :9001；两条隧道可能只断一条，不能以另一条不可达代偿；归因不了不豁免） | gate_b2 docstring |
| 真实故障 | 服务可达但模型未就绪（如 dub-tts 未装载）不提供跳过口径 | gate_b1/b2 docstring |

## 5. eval / 自检

```bash
bash ops/tunnel_gpu.sh status     # exit 0 且打印 /health JSON = UP
curl -sf -m 3 http://127.0.0.1:9001/health   # 直探（等价 health()）
```

eval 脚本内建隧道前置：`eval_m4.sh`（9001 默认）、`eval_m7.sh`（`TUNNEL_LOCAL_PORT=9002
TUNNEL_REMOTE_PORT=9002` 显式传递）。

## 6. 坑清单（实测）

1. tailnet 直连不通 → 必须公网 Host 条目（本文件 §1）。
2. 公网链路周期 reset ~10s 愈合窗 → keepalive + 客户端 retries 双层消解；**retries=0 会假红**。
3. Windows 无 ssh ControlMaster → `ControlPath=none` 固定。
4. 端口清理：Windows 下用 `netstat -ano -p tcp` 抓 LISTENING PID + `taskkill //F`（Git Bash 双斜杠转义）。
5. keepalive 多实例竞争 → 单实例锁 v2（§3）。
6. keepalive 锁文件名兼容：9001 历史锁名不变（存量循环无缝升级）。
