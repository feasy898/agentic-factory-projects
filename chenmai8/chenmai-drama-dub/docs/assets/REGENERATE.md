# 整仓再生手册（REGENERATE）

> 目标：新 agent 只凭本手册 + 各 spec + CONTRACTS，在双机环境上从零重建全部已实现模块并通过三道验收门。
> 本机命令在**仓库根**执行（另有注明除外）；通过线均为冻结契约，实测记录见各 spec 与 §7 变更史。
> 机器角色：**windev-01（本机）** = 编排 + CPU 链路 + eval 断言；**GPU 机（anolis-gpu-01, 2×V100S-32GB sm_70）**
> = 常驻推理服务（:9001 识别/对齐/情绪、:9002 合成、:9004 翻译）。

---

## 1. 本机（windev-01）环境准备

| 件 | 实测版本 | 说明 |
|---|---|---|
| OS / Shell | Windows Server 2022 + Git Bash | 仓库路径含中文——非 ASCII 路径坑见 §6 |
| Python | 3.12.10 | venv 固定在仓库根 `.venv/` |
| ffmpeg | 6.1.1 essentials（gyan build，**含 libass/fribidi/harfbuzz**——阿语 RTL 渲染硬依赖） | `ffmpeg -version` 核验；`python scripts/check_ffmpeg.py` 可用性检查 |

```bash
# venv + 钉版依赖（requirements.txt 头注就是契约的一部分）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/
```

- 钉版关键项（requirements.txt 是唯一真实发行名登记处，本表用中性名对应）：torch==2.14.0（Windows PyPI
  轮子即 CPU 构建）/ paddle 系 CPU 栈 3.3.1 + 引擎封装 3.7.0 / audiosplit 分离依赖 0.47.0 /
  facemesh 运行时 1.0.1 / scikit-learn==1.9.1 / scipy==1.18.1 / fastapi==0.141.1 / uvicorn==0.54.0 /
  httpx==0.28.1 / pydantic==2.13.5 / pytest==9.1.1。
- ffmpeg 不走 pip（系统级依赖）；requirements.txt 已注明不再写非 pip 行（会令 `pip install -r` 无法重放）。
- **两条进程内硬约束**（违反即崩，详见 [specs/m2-ocr.md](specs/m2-ocr.md) §4）：
  1. 同进程 torch 必须先于 paddle 系导入（libiomp5md.dll 冲突）；
  2. OCR 引擎构造必须 `enable_mkldnn=False`（外部覆盖一律被忽略）。
  两条已锁进可执行代码 `pipeline/ocr_wrap.py`（M2 唯一许可入口），守护测试 tests/test_ocr_wrap.py。

## 2. GPU 机环境与部署（双机部署）

### 2.1 运行环境（anolis-gpu-01，root，部署根 `/data/xdng`）

| 件 | 实测版本 | 说明 |
|---|---|---|
| GPU | 2× V100S-32GB（sm_70） | 有 fp16、**无 bf16**；注意力固定 sdpa；全部推理不依赖重型服务化运行时 |
| 主 venv | `/data/xdng/venv`（python 3.11） | **torch==2.5.1+cu118 + transformers 4.52.x**（TTS/口型/翻译组）——脚本断言版本且二进制含 sm_70 |
| asr venv | `/data/xdng/venv-asr` | **transformers 5.13.0**（识别/对齐原生架构下限）；torch 2.5.1+cu118 以 `.pth` 复用主 venv 不重下 2.3GB 轮子 |

- **两组 transformers 不可共存于同一解释器**（4.52.x 与 5.13）——这是双 venv 的唯一原因
  （configs/models.yaml 部署矩阵头注 + docs/gpu_asr_align_deps.md「为何独立 venv」）。
- `.pth` 复用法：venv 自身 site-packages 优先级更高，新装包正常遮蔽主 venv；
  不用 `--system-site-packages`（暴露的是基础解释器，不含主 venv）。

### 2.2 部署步骤（全部幂等，可重跑）

```bash
ssh root@100.100.0.7
# ① 主 venv（torch cu118 + transformers 4.52.x + fastapi/uvicorn/httpx）
nohup bash gpu/setup_gpu.sh > /data/xdng/setup_gpu.log 2>&1 &
# ② asr 独立 venv（读 /data/xdng/etc/model_ids.env 的模型 ID；该文件留 GPU 机不入公开仓，
#    真名对照登记 docs/gpu_asr_align_deps.md）
nohup bash gpu/setup_asr_venv.sh > /data/xdng/logs/setup_asr_venv.log 2>&1 &
# ③ 权重落位：主路 ModelScope 国内直连（实测 11.8MB/s），HF 镜像兜底；目录 /data/xdng/models/<中性名>/
# ④ 服务启动（各服务 nohup 常驻，PID+日志落盘，幂等 start/stop/restart/status）
bash gpu-services/asr_align/run_gpu.sh start     # :9001，venv-asr
bash gpu-services/tts/run_gpu.sh start           # :9002，主 venv；dub-tts fp32 常驻 cuda:0
bash gpu-services/mt/run_gpu.sh start            # :9004（T12 批部署）
# ⑤ 部署前置核验
bash gpu/setup_tts_service.sh                    # torch sm_70 断言 + python-multipart 补装 + 权重核验
bash gpu/setup_mt_service.sh
```

- 服务只监听 GPU 机 127.0.0.1（该机有公网出口，不对公网暴露端口）；run_gpu.sh 均 `HF_HUB_DISABLE_XET=1`
  （权重全在本地目录，防 from_pretrained 意外联网踩 Xet）。
- 显存预算（models.yaml 部署矩阵）：#0 = asr_align 三模型 + tts dub-tts（~7GB）+ mt（~5GB）同卡共存 32GB；
  **#1 = lip-pro（~18GB，planned）与 alt-tts-b 懒加载（~8GB）互斥——lip-pro 起来前先停 :9002 的备选链懒加载**。

### 2.3 隧道（本机 → GPU 机）

```bash
bash ops/tunnel_gpu.sh start                                   # :9001（默认端口，历史日志/锁名不变）
TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash ops/tunnel_gpu.sh start   # :9002
TUNNEL_LOCAL_PORT=9004 TUNNEL_REMOTE_PORT=9004 bash ops/tunnel_gpu.sh start   # :9004
nohup bash ops/tunnel_gpu.sh keepalive >> tmp/tunnel_keepalive.log 2>&1 &      # 保活循环（每端口一个）
```

坑与定案详见 [specs/gpu-tunnel.md](specs/gpu-tunnel.md)；要点：**tailnet 数据面本机→GPU 方向实测不通，
隧道走 ssh config 公网 Host 条目**；服务零公网暴露。

## 3. 模块重生成顺序（依赖图即拓扑序）

```
0 契约(pipeline/contracts.py)+原语+scaffold → 1 M1 → 2 M2 → 3 M3 → 4 M4(:9001 在线)
→ 5 M5 → 6 M6(mock 全离线，可与 4/5 并行) → 7 M11 → 8 M8 → 9 M9 → 10 M7(:9002 在线) → 11 三道门
```

每步"验收命令 → 通过线"（详见各 spec §eval 与 manifest 表）：

| 步 | 模块 | 验收命令 | 通过线（冻结） |
|---|---|---|---|
| 0 | 契约 | `python -m pipeline.cli validate <kind> <path>`；`pytest tests/test_contracts.py tests/test_b1_contract.py` | exit 0；38 passed |
| 1 | M1 | `pytest tests/test_m1.py` | 7 passed；ffprobe 断言；时长差 ≤0.2s |
| 2 | M2 | `bash scripts/eval_m2.sh` | 12 passed；CER ≤5%；起止误差 ≤0.3s 且 ≥90% 命中 |
| 3 | M3 | `pytest tests/test_m3.py` | 9 passed；时长=输入；RMS 判据；60s 素材 CPU ≤10 分钟 |
| 4 | M4 | `bash ops/tunnel_gpu.sh start && bash scripts/eval_m4.sh` | tests 全绿含 :9001 三模型 loaded 冒烟 |
| 5 | M5 | `pytest tests/test_m5.py` | 13 passed；diar 一致率 ≥0.85；切分召回 ≥0.8；正脸近景 ≥80% |
| 6 | M6 | `bash scripts/eval_m6.sh` | 10 passed（全离线 mock） |
| 7 | M11 | `bash scripts/eval_m11.sh` | 24 用例；擦后中文 OCR=0；标识区哈希一致；ar RTL 断言 |
| 8 | M8 | `bash scripts/eval_m8.sh` | 10 passed；对齐率 ≥0.70；七类路径全触发 |
| 9 | M9 | `bash scripts/eval_m9.sh` | 17 passed；时长差 ≤0.2s；响度 ±1LU；峰值比 ≥8dB |
| 10 | M7 | `TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash ops/tunnel_gpu.sh start && bash scripts/eval_m7.sh` | 11 passed（4 离线+7 在线） |

## 4. 全仓验收（三道门）

```bash
python scripts/gate_b0.py                 # 环境与契约门（系统 Python 任意 cwd，内部定位 .venv）
python scripts/gate_b1.py [--skip-gpu]    # M1–M4（含真模型 CPU 推理，墙钟 ~45 分钟量级）
python scripts/gate_b2.py [--skip-gpu]    # M5/M6/M7（超时预算：单项 1800s / 整门 3600s）
python scripts/gate_b3.py [--skip-gpu]    # M8/M9/M11 + gate_b2 整门回归（同预算；全门墙钟 ~55 分钟量级，
                                          # 外部超时帽需 ≥60min）
```
- 整门记录（2026-09-29）：B3 6/6 PASS 3469s/3600s——177 passed 零跳过（M11 24 / M8 10 / M9 17 / gate_b2 子进程整门回归）。

- 共同纪律：**skipped 即 FAIL**；唯一豁免 = 显式 `--skip-gpu` 且被牵连服务确认不可达的"服务不可达"类跳过，
  且**逐条归因**（tts/9002 归 :9002、asr_align/9001 归 :9001——两条隧道可能只断一条，不能代偿；
  归因不了不豁免）。
- 整门记录：B1 6/6 PASS（92 passed 零跳过）；B2 6/6 PASS 867s（126 passed）；B3 6/6 PASS 3469s（177 passed）——均 2026-09-29。
- 服务可达但模型未就绪属**真实故障**，不提供跳过口径。

## 5. 替换/重生成模块时的回归清单

| 被替换模块 | 必跑回归 | 额外人工检查 |
|---|---|---|
| contracts.py | test_contracts + test_b1_contract + 受影响模块 eval | 只增不改名；CONTRACTS §3 痛点候选未被擅自"顺手实现" |
| M1 | test_m1 + 依赖 01_media 的 M2/M3 eval | probe.json 字段消费方（M3 输入回退、M9 master 时长）不受影响 |
| M2 | eval_m2 + eval_m11（擦除带同源） | 冻结常量（0.2s/0.9/60%）未漂移；ocr_wrap 守护测试仍过 |
| M3 | test_m3 + test_m4（vocals 槽位） + eval_m9（bgm 消费） | 人声槽位 04_dial/vocals.wav 不变 |
| M4 | eval_m4 + eval_m2（投票融合） | 时间零点/切句规则 7/8 未破坏（test_b1_contract 钉住） |
| M5 | test_m5 + C2 回填字段消费方（M6/M8 读 speaker/char_id） | C1 schema 不含正脸字段（frontal_closeups.json 独立落盘） |
| M6 | eval_m6 + eval_m8（C4 消费） | 复合键 (utt_id,tgt) upsert 不串语种 |
| M7 | eval_m7 + eval_m8（C5 消费）/ eval_m9（wav 消费） | 双参考接口与 attempts 口径不变；时长对账 ±0.05s |
| M8 | eval_m8 + eval_m9（C5 句窗摆放） | C5 多语种分文件 + 无后缀副本语义不变 |
| M9 | eval_m9 + eval_m11（成片路径竞争） | 编排顺序：e2e 口径 M11 先于 M9 最终合成（m9 notes §5） |
| M11 | eval_m11 + eval_m9（M11 产物 -c:v copy 接入） | label_zone 排除 + 无损基带不变（标识区哈希判定依赖） |
| models.yaml | gate_b0 ② + 受影响组件 eval | 只增不改名；volta_status 未实测不写 ok |

## 6. 已知坑清单（实测，重生成必读）

1. **中文路径 × C++ 运行时**：facemesh 运行时 C++ 层打不开非 ASCII 模型路径 → `_facemesh_face.py` 复制到
   `%TEMP%` ASCII 路径装载；cv2.imread 同样不支持非 ASCII 路径（→ `np.fromfile + cv2.imdecode`）；
   `cv2.VideoCapture` 不受影响。ffmpeg 滤镜串两级转义 + 非 ASCII 路径坑：M11 压制以 `ass=` 只传相对文件名
   并以 `10_subs` 为 cwd（同 M2 drawtext textfile 手法）。
2. **torch 线程帽**：64 核默认全开线程互踩——m3 threads=16（单窗 65s→11.2s）、voxdia 线程帽 8
   （7.4s 句嵌入 49.6s→0.25s）。新组件默认全核跑慢先查这个。
3. **ffmpeg mp4 自定义元数据**：`-metadata` 对 mp4 只落已知键，任意键被静默丢弃；必须
   `-movflags +use_metadata_tags` 才能落 `XMP:…` 并被 ffprobe 回读（m9 notes §3）。
   loudnorm 内部固定 192k → 链尾必须 `aresample=48000`（否则产物采样率漂移）。
4. **M9 ducking 定案**：确定性句窗包络而非 sidechaincompress（同素材不可复现到 ±1dB，冻结线无从判定）；
   斜坡贴电平区外（窗内斜坡会污染 RMS 实测，T15 修过一版）。
5. **C5/C4 多语种**：C5 每语种一份文件 + 无后缀副本；C4 复合键 (utt_id,tgt)。重跑勿同 id 追加（唯一性自锁）。
6. **首载超时**：tts 客户端默认超时 600s（主力引擎 fp32 首装 35.4s + 备选链懒加载余量）；
   :9001 客户端 300s。gpu_client/m4/m3 服务用例 retries=5、间隔 3s（覆盖公网 reset ~10s 愈合窗）。
7. **Windows 编码**：eval/门禁对子进程统一 `PYTHONUTF8=1`；入口 `reconfigure(encoding="utf-8")`（GBK 控制台乱码）。
8. **权重/模型路径**：权重缓存 `models/` 与素材 `clips/`、工作区 `jobs/` 均不入公开仓（.gitignore）；
   GPU 机模型 ID 经 `/data/xdng/etc/model_ids.env` 注入（真名不进公开仓代码，运行时拼接构造动态加载）。
9. **中性名纪律**：公开文本零上游名（gate_b0 ④：附录A 强校验 + git 追踪文件 grep 零命中；
   docs/ 与 requirements.txt 为依赖安装记录豁免，真名只登记于 docs/*_deps.md）。
   token 表在 gate_b0.py 拼接构造（防自命中）。`c2pa` 裸词允许（标准名/契约字段），
   `lora` 裸词允许（中性名 isomt-lora 自含）。

### 6.1 网络与镜像（限流/403 实测经验）

| 场景 | 实测结论 | 定案 |
|---|---|---|
| 本机 pip：清华源 | T4 起对本机 IP 403（T0 时尚可用） | **一律阿里云镜像** `mirrors.aliyun.com/pypi/simple/`（requirements.txt 头注） |
| GPU 机 pip：清华源 | 对该机 /simple/ 页 403（curl 与 pip 同） | setup_gpu.sh / setup_asr_venv.sh 默认阿里云 |
| GPU 机 pip 自举 | 发行版 venv 自带 pip 23.3.1 的旧 vendored urllib3 对部分镜像响应崩（TypeError >=） | 官方 get-pip.py 先升级 pip 再装 |
| torch cu118 轮子 | pytorch-wheels 镜像慢（实测 ~0.5MB/s） | 主 venv 装一次；venv-asr 用 `.pth` 复用不重下（2.3GB） |
| HF 权重下载 | hf-mirror 不代理 Xet CAS（实测 401）；/resolve 302 到的 HF CDN 本机路由超时频发 | **`HF_HUB_DISABLE_XET=1`** + 权重主路 **ModelScope 国内直连**（同 ID 仓，实测 11.8MB/s），HF 镜像兜底 |
| 服务运行期联网 | from_pretrained 意外联网会踩 Xet | 所有 run_gpu.sh 固定 `HF_HUB_DISABLE_XET=1`（权重全在本地） |
| 遇到限流/429 | 等 60s 重试；不并发叠加请求（同 keepalive 拉起失败不并发叠加的纪律） | 重试由客户端 retries+退避承担（gpu_client/tts_client retries=2、服务用例 5×3s） |

## 7. 本资产包的变更史指针

| commit（2026-09-29 前后） | 内容 |
|---|---|
| T1 冻结批 | contracts.py C1–C8 + cli 骨架 + configs 三件套 |
| B1 批（44ceef2 / 07dfd62 / 726b2e1 等） | 时间零点/utt_id/upsert 冻结规则 7–10；m4/m3 retries 0→5；tunnel keepalive v2 单实例锁；gate_b1 台账 |
| T6/T4/T5/T7 | M2 OCR / M3 分离 / M4 服务 / M5 四链路（模型条目+实测回填 models.yaml） |
| T10/T12 | M6 三后端 + :9004 服务骨架；M7 :9002 服务 + 双参考接口 + 冒烟回填 |
| T13（gate_b2） | 6/6 PASS 867s，126 passed 零跳过记录 |
| T14（81485e6）/ T8（aca8b08）/ T15（99011c1+bec2459） | M8 / M11 / M9（+models.yaml mix-m9、align-m8 登记） |
| T16/B3（b25fc4b） | gate_b3 四道门收口（6/6 PASS 3469s，177 passed 零跳过） |
| （本 commit） | docs/assets/ 四件套（manifest / specs×13 / REGENERATE / CONTRACTS） |
| 回炉二稿（2026-09-30） | 首轮重生成试点缺口回填：m1-ingest spec 二稿（收件固定名 input.mp4 / 产物名随 targets 联动模板 / probe.json 全 schema+loudness 8 字段 / config 键位与 jobs_dir 解析语义 / CLI stdout 逐字形态 / exit 2=argparse SystemExit / `audio=skip` 位置修正：stdout 而非 probe.json）+ contract-io §3 LAYERS/EXPECTED_FILES 全表自含化 |
