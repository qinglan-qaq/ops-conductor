#!/usr/bin/env bash
# 启动跨境调度 Demo。只依赖 FastAPI 进程；Dispatch 切片使用内存仓储，
# 不需要 PostgreSQL、Redis 或外部平台 API。
# 使用 conda 环境内的 Python；uvicorn 只是该环境内的 ASGI 服务器库，
# 不需要单独创建“uvicorn 环境”。
set -euo pipefail

cd "$(dirname "$0")/.."
# Git Bash 下把 POSIX 路径转成 Windows 路径，并使用 Windows 的 ; 分隔符，
# 否则 Windows Python 无法解析 PYTHONPATH。
if command -v cygpath >/dev/null 2>&1; then
  ROOT="$(cygpath -w "$PWD")"
  PYTHONPATH_SEP=';'
else
  ROOT="$PWD"
  PYTHONPATH_SEP=':'
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+$PYTHONPATH_SEP$PYTHONPATH}"
CONDA_ENV="${OPSCONDUCTOR_CONDA_ENV:-opsconductor}"
PORT="${PORT:-8000}"

PY="${OPSCONDUCTOR_PYTHON:-}"
if [ -z "$PY" ]; then
  # 直接解析 conda 环境路径，避免 `conda run` 在部分 Windows 环境下缓冲或
  # 错误解析 `-c`/模块参数。
  ENV_PATH="$(conda env list 2>/dev/null | awk -v name="$CONDA_ENV" '$1 == name {print $NF; exit}')"
  if [ -n "${ENV_PATH:-}" ] && [ -x "$ENV_PATH/python.exe" ]; then
    PY="$ENV_PATH/python.exe"
  elif [ -n "${ENV_PATH:-}" ] && [ -x "$ENV_PATH/bin/python" ]; then
    PY="$ENV_PATH/bin/python"
  else
    PY="python"
  fi
fi

if [ ! -f frontend/dist/index.html ]; then
  echo "提示：frontend/dist 缺失，/dispatch 将返回 503；先运行 bash scripts/build_frontend.sh。" >&2
fi

if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "找不到可用的 Python 环境 '$CONDA_ENV'。" >&2
  echo "请先 conda activate '$CONDA_ENV'，或设置 OPSCONDUCTOR_PYTHON 指向解释器。" >&2
  exit 1
fi

exec "$PY" -m opsconductor.api.serve --reload --port "$PORT"
