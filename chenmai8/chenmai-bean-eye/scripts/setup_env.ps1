<#
.SYNOPSIS
    BeanEye 环境脚手架：建 venv + 装 pinned 依赖 + 环境体检（Windows 原生，无需 WSL/Docker）。

.DESCRIPTION
    步骤：
      1. 校验 Python 为 3.12.x（开发指令 D-4 锚定 3.12.10）
      2. 在仓库根创建 .venv（已存在则复用）
      3. 升级 pip，安装 requirements.txt（全部 == 钉版）
      4. albumentations==2.0.8 以 --no-deps 安装（原因见 requirements.txt 头注释）
      5. 运行 scripts/doctor.py 输出 [OK]/[NG] 体检清单，退出码透传

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_env.ps1 -Python "C:\Program Files\Python312\python.exe"

.NOTES
    本文件含中文注释，必须保存为 UTF-8 **带 BOM**（Windows PowerShell 5.1 无 BOM 时按 GBK
    解析中文导致语法错误）。若用工具改动后丢失 BOM，执行：
    python -c "p=r'scripts\setup_env.ps1'; d=open(p,'rb').read(); open(p,'wb').write((b'\xef\xbb\xbf'+d) if not d.startswith(b'\xef\xbb\xbf') else d)"
#>
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "== BeanEye setup_env ==" -ForegroundColor Cyan
Write-Host "[setup] 仓库根: $Root"

# ---- 1) Python 版本 ----
$ver = (& $Python -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $ver) { throw "无法运行 Python 解释器: $Python" }
Write-Host "[setup] Python 版本: $ver"
if ($ver -notmatch '^3\.12\.') { throw "需要 Python 3.12.x，当前为 $ver（可用 -Python 参数指定解释器）" }

# ---- 2) venv ----
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "[setup] 创建 venv -> $Root\.venv"
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv 创建失败" }
}
else {
    Write-Host "[setup] 复用已有 venv"
}

# ---- 3) pip 升级 + 钉版依赖 ----
Write-Host "[setup] 升级 pip"
& $VenvPy -m pip install --upgrade pip --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip 升级失败" }

Write-Host "[setup] 安装 requirements.txt（钉版）"
& $VenvPy -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败（见上方 pip 输出）" }

# ---- 4) albumentations==2.0.8 及其最小闭包（--no-deps，原因见 requirements.txt 头注释）----
# 默认依赖会拉入 opencv-python-headless（最高 5.x）覆盖钉版 cv2 4.10.0，故按下列
# 固定闭包手工补齐：albumentations -> albucore -> {simsimd, stringzilla}，
# albucore 所需 cv2 由本清单的 opencv-python 提供。版本为 pip 解析结果，已实测可跑增强。
Write-Host "[setup] 安装 albumentations 闭包 (--no-deps)"
& $VenvPy -m pip install --no-deps `
    "albumentations==2.0.8" "albucore==0.0.24" "simsimd==6.5.16" "stringzilla==5.1.2" `
    --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "albumentations 闭包安装失败" }

# ---- 5) 体检 ----
Write-Host "[setup] 运行环境体检 doctor.py"
& $VenvPy (Join-Path $Root "scripts\doctor.py")
exit $LASTEXITCODE
