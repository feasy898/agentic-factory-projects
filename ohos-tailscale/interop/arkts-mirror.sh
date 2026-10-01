#!/usr/bin/env bash
# ArkTS 检查辅助（WSL 内执行）：
# 1) 把 packages/ 镜像为 .ets 副本（官方 linter 的 lintEtsOnly 只查 .ets）
# 2) 用华为 SDK ets-loader 内置 ArkTSLinter 扫描
set -u
REPO="${1:-/mnt/c/Users/Administrator/.zcode/workspace/default/ohos-tailscale}"
NODE="${2:-$HOME/sdk/node22/bin/node}"
SCAN="$HOME/arkts-scan"

rm -rf "$SCAN"
mkdir -p "$SCAN"
cp -r "$REPO/packages" "$SCAN/packages"

# .ts → .ets（官方 linter 只扫 .ets；导入后缀同步改写）
find "$SCAN/packages" -name '*.ts' | while read -r f; do
  mv "$f" "${f%.ts}.ets"
done
find "$SCAN/packages" -name '*.ets' -exec sed -i "s|\.ts'|.ets'|g" {} +

# 负对照文件（验证 linter 真的在工作）
cat > "$SCAN/packages/common/src/zz-negative-control.ets" <<'EOF'
export enum BadEnum { A = 1 }
export function badAny(v: any): any { return v; }
export function badTuple(): [string, number] { return ['a', 1]; }
export function badStringIndex(s: string): string {
  const t: string = 'abcdef';
  return t.charAt(s.charCodeAt(0) % 6);
}
EOF

cd "$REPO"
SCAN_ROOT="$SCAN/packages" SCAN_EXT=.ets "$NODE" < interop/arkts-check.js 2>&1 | head -50
