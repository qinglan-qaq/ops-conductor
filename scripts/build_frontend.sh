#!/usr/bin/env bash
# 构建 Vue 调度台到 frontend/dist，供 FastAPI 直接托管。
# 使用 package-lock.json 时优先 npm ci，保证依赖可复现。
set -euo pipefail

cd "$(dirname "$0")/../frontend"

if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi

npm run build
echo "built frontend/dist"
