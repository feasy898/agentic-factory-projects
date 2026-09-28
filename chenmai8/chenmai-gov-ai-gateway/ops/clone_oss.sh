#!/usr/bin/env bash
# 幂等克隆脚本：固定版本的第三方参考件 → third_party/（.gitignore 覆盖，不进公开导出）。
# 用法：bash ops/clone_oss.sh [core|all]   （默认 core）
#   core = 识别框架参考 + 注入攻击种子语料（D1/D4 用）
#   all  = core + 可选模型路由框架参考（P2 用）
# 说明：本文件含第三方真实坐标，属内部工具（导出阶段豁免公开卫生检查，
#       与 third_party/PINNED.txt 同理）；克隆产物不进 git。
# 直连慢时走香港中转克隆再解包（内部知识库 02 篇）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TP="$REPO_ROOT/third_party"
PINNED="$TP/PINNED.txt"
mkdir -p "$TP"
touch "$PINNED"

clone_pin() { # <url> <tag|HEAD> <dst-relative>
  local url="$1" tag="$2" dst="$TP/$3"
  if [ -d "$dst/.git" ]; then
    echo "[skip] $3 already cloned"
  else
    echo "[clone] $3 <- $url @ $tag"
    if [ "$tag" = "HEAD" ]; then
      git clone --depth 1 "$url" "$dst"
    else
      git clone --depth 1 --branch "$tag" "$url" "$dst"
    fi
  fi
  local commit
  commit="$(git -C "$dst" rev-parse HEAD)"
  if ! grep -qF " $commit" "$PINNED"; then
    echo "$3 | tag=$tag | commit=$commit" >> "$PINNED"
  fi
}

GROUP="${1:-core}"

# ── core（D1 识别框架形态参考；D4 注入攻击种子语料）────────────────
clone_pin "https://github.com/microsoft/presidio" "2.2.364" "presidio"
clone_pin "https://github.com/thu-coai/Safety-Prompts" "HEAD" "safety-prompts"

if [ "$GROUP" = "all" ]; then
  # ── 可选（P2：模型路由框架参考，运行时用 pip 版本）────────────────
  clone_pin "https://github.com/BerriAI/litellm" "v1.103.0" "litellm"
fi

# 记录但不克隆：复杂版式 PDF 解析路线（P2 启用前先读其 LICENSE）：
#   https://github.com/opendatalab/MinerU  tag mineru-4.0.8-released

echo "done. pinned versions in third_party/PINNED.txt"
