# setup_windev — windev-01 本机开发环境记录（T0，2026-09-28）

> 目标：为 pipeline 建立可复现的 Python 3.12 venv + CPU 依赖，并记录两条实测踩坑约束。
> 机器：windev-01（Windows Server 2022 x64，Git Bash；国际网络严重限速，国内镜像快——见
> `D:\agent-knowledge\02-network-and-shell-pitfalls.md`），故 pip 一律走清华源。

## 1. 环境基线（装机时实测）

| 组件 | 版本 | 验证命令 |
|---|---|---|
| Python | 3.12.10（`C:\Program Files\Python312\python.exe`） | `python --version` |
| ffmpeg | 6.1.1 essentials（gyan.dev，含 libass/libfribidi/libharfbuzz） | `ffmpeg -version` |
| venv | `.venv/`（repo 根，已在 .gitignore） | — |

ffmpeg 过滤器确认（M11/M12 依赖）：

```bash
ffmpeg -hide_banner -filters | grep -c "ass\|drawtext"   # 21（ass、drawtext 均在）
```

## 2. 安装命令记录（按序执行）

```bash
cd D:/workspace/澄迈8项目/短剧多国出海/repo

# 1) 建 venv
python -m venv .venv

# 2) 升级 pip（清华源）
.venv/Scripts/python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
#   → pip 25.0.1 → 26.2.1

# 3) torch：Windows 平台 PyPI 轮子即 CPU 构建，无需 pytorch 官方源
.venv/Scripts/python.exe -m pip install torch -i https://pypi.tuna.tsinghua.edu.cn/simple
#   → torch-2.14.0（import 后 torch.__version__ == '2.14.0+cpu'，version.cuda == None）

# 4) paddle：py3.12 有 cp312 win_amd64 轮子，未触发 rapidocr 降级
.venv/Scripts/python.exe -m pip install paddlepaddle -i https://pypi.tuna.tsinghua.edu.cn/simple
#   → paddlepaddle-3.3.1
.venv/Scripts/python.exe -m pip install paddleocr -i https://pypi.tuna.tsinghua.edu.cn/simple
#   → paddleocr-3.7.0 + paddlex-3.7.2（numpy 自动被约束回 2.3.5）

# 5) 其余锁定依赖
.venv/Scripts/python.exe -m pip install fastapi uvicorn httpx pydantic librosa pytest \
    -i https://pypi.tuna.tsinghua.edu.cn/simple
#   → fastapi-0.141.1 uvicorn-0.54.0 librosa-1.0.0（自带 soundfile-0.14.0）pytest-9.1.1
#     httpx 0.28.1 / pydantic 2.13.5 已随 paddle 依赖就位

# 复现安装：pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 3. 实测踩坑（两条硬约束，后续模块必须遵守）

### 3.1 torch 必须先于 paddle 导入（同进程）

- 现象：先 `import paddle` 后 `import torch` →
  `OSError: [WinError 127] 找不到指定的程序。 Error loading "...\torch\lib\shm.dll" or one of its dependencies.`
- 根因：`torch/lib/libiomp5md.dll` 与 `paddle/libs/libiomp5md.dll` 同名（Intel OpenMP 运行时），
  paddle 先加载自己的副本，torch 的 shm.dll 再解析到它时缺新导出符号 → 127。
- 实测：
  - 顺序 `paddle → torch`：**FAIL**（上述报错）
  - 顺序 `torch → paddle → paddleocr`：**OK**（两者均正常工作）
- 约束：pipeline 的公共入口（cli/bootstrap）必须最先 `import torch`；M2(OCR) 与
  M3/M5/M12(torch 系) 同进程运行时严禁调换顺序。

### 3.2 paddleocr 推理必须 `enable_mkldnn=False`

- 现象：默认参数（mkldnn 开）跑 `PaddleOCR.predict()` →
  `NotImplementedError: (Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
  [pir::ArrayAttribute<pir::DoubleAttribute>] (at .../onednn_instruction.cc:118)`
- 实测：加 `enable_mkldnn=False` 后推理正常：
  合成图 "HELLO 12345" → `rec_texts=['HELLO 12345'], rec_scores=[1.0]`。
  （OCR 识别模型由 paddleocr 首次调用时自动下载成功，走国内源。）
- 代价：mkldnn 关闭后为原生 CPU kernel，速度略降；M2 若实测吞吐不足，D2 再评估
  降 paddle 版本或调 PIR 开关，本阶段先按此约束冻结。

## 4. 自验收记录（T0 通过判据，全部真实执行）

```bash
.venv/Scripts/python.exe -c "import torch, paddle, paddleocr, fastapi, uvicorn, httpx, \
    pydantic, numpy, librosa, soundfile; print('SELF-CHECK IMPORTS: ALL OK')"
# → SELF-CHECK IMPORTS: ALL OK
ffmpeg -version
# → ffmpeg version 6.1.1-essentials_build-www.gyan.dev（libass/fribidi/harfbuzz 配置项在列）
```

版本清单（import 实测输出）：

```
torch 2.14.0+cpu (cuda_build: None) | paddle 3.3.1 | paddleocr 3.7.0
fastapi 0.141.1 | uvicorn 0.54.0 | httpx 0.28.1 | pydantic 2.13.5
numpy 2.3.5 | librosa 1.0.0 | soundfile 0.14.0
```

功能级附加验证（超出判据，顺手做实）：
`paddle.utils.run_check()` → "PaddlePaddle works well on 1 CPU"；
torch CPU 矩阵乘正常；paddleocr 真实推理出字（见 3.2）。

## 5. 完整 pip freeze（复现用）

见下方附录；`requirements.txt` 只钉直接依赖。

## 附录：pip freeze 原文（2026-09-28）

<details><summary>展开</summary>

```
aiohappyeyeballs==2.7.1
aiohttp==3.14.3
aiosignal==1.4.0
aistudio_sdk==0.3.9
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
attrs==26.1.0
bce-python-sdk==0.9.79
certifi==2026.7.22
cffi==2.1.1
chardet==7.6.0
charset-normalizer==3.5.1
click==8.5.0
cloudpickle==3.1.2
colorama==0.4.6
colorlog==6.12.0
crc32c==2.9.post0
cryptography==50.0.1
decorator==5.3.1
fastapi==0.141.1
filelock==4.0.5
frozenlist==1.8.0
fsspec==2026.9.0
future==1.0.0
h11==0.16.0
hf-xet==1.6.0
httpcore==1.0.9
httpcore2==2.13.1
httpx==0.28.1
httpx2==2.13.1
huggingface_hub==2.0.0
idna==3.20
imagesize==2.0.1
iniconfig==2.3.0
Jinja2==3.1.6
joblib==1.6.0
lazy-loader==0.6
librosa==1.0.0
llvmlite==0.49.0
MarkupSafe==3.0.3
modelscope==1.40.1
modelscope-hub==0.4.5
mpmath==1.3.0
msgpack==1.2.2
multidict==6.9.1
narwhals==2.26.0
networkx==3.7
numba==0.67.0
numpy==2.3.5
opencv-contrib-python==4.10.0.84
opt-einsum==3.3.0
packaging==26.3
paddleocr==3.7.0
paddlepaddle==3.3.1
paddlex==3.7.2
pandas==3.0.6
pillow==12.3.0
platformdirs==4.12.1
pluggy==1.6.0
pooch==1.9.0
prettytable==3.18.0
propcache==0.5.4
protobuf==7.36.2
psutil==7.2.2
py-cpuinfo==9.0.0
pyclipper==1.4.0
pycparser==3.0
pycryptodome==3.23.0
pydantic==2.13.5
pydantic_core==2.46.5
Pygments==2.21.0
pypdfium2==5.13.0
pytest==9.1.1
python-bidi==0.6.11
python-dateutil==2.9.0.post0
PyYAML==6.0.2
requests==2.34.2
ruamel.yaml==0.19.1
safetensors==0.8.0
scikit-learn==1.9.1
scipy==1.18.1
setuptools==84.0.0
shapely==2.1.2
six==1.17.0
soundfile==0.14.0
soxr==1.1.0
starlette==1.7.0
sympy==1.14.0
threadpoolctl==3.7.0
torch==2.14.0
tqdm==4.70.1
truststore==0.10.4
typing-inspection==0.4.4
typing_extensions==4.16.0
tzdata==2026.4
ujson==6.0.0
urllib3==2.8.0
uvicorn==0.54.0
wcwidth==0.9.1
yarl==1.25.1
```

</details>
