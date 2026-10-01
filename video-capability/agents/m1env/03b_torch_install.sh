#!/usr/bin/env bash
# M1-ENV step 03b: install torch stack with explicit wheel paths (find-links unreliable on pip 26)
set -x
V=~/cradle/.venv/bin
W=~/downloads/wheels
$V/pip install --no-cache-dir \
  $W/torch-2.4.1+cu121-cp312-cp312-linux_x86_64.whl \
  $W/torchvision-0.19.1+cu121-cp312-cp312-linux_x86_64.whl \
  $W/triton-3.0.0-1-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl \
  $W/nvidia_cuda_nvrtc_cu12-12.1.105-py3-none-manylinux1_x86_64.whl \
  $W/nvidia_cuda_runtime_cu12-12.1.105-py3-none-manylinux1_x86_64.whl \
  $W/nvidia_cuda_cupti_cu12-12.1.105-py3-none-manylinux1_x86_64.whl \
  $W/nvidia_cudnn_cu12-9.1.0.70-py3-none-manylinux2014_x86_64.whl \
  $W/nvidia_cublas_cu12-12.1.3.1-py3-none-manylinux1_x86_64.whl \
  $W/nvidia_cufft_cu12-11.0.2.54-py3-none-manylinux1_x86_64.whl \
  $W/nvidia_curand_cu12-10.3.2.106-py3-none-manylinux1_x86_64.whl \
  $W/nvidia_cusolver_cu12-11.4.5.107-py3-none-manylinux1_x86_64.whl \
  $W/nvidia_cusparse_cu12-12.1.0.106-py3-none-manylinux1_x86_64.whl \
  $W/nvidia_nccl_cu12-2.20.5-py3-none-manylinux2014_x86_64.whl \
  $W/nvidia_nvjitlink_cu12-12.9.86-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl \
  $W/nvidia_nvtx_cu12-12.1.105-py3-none-manylinux1_x86_64.whl \
  -i https://mirrors.aliyun.com/pypi/simple/
$V/python -c "import torch, torchvision; print('torch', torch.__version__, 'tv', torchvision.__version__, 'cuda_avail', torch.cuda.is_available(), 'cap', torch.cuda.get_device_capability())"
echo "STEP03B_DONE rc=$?"
