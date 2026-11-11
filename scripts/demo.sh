#!/usr/bin/env bash
# Start the MVP demo stack: Docker PostgreSQL 16, Alembic migrations, seed, API.
#
# Run from the repository root (or anywhere; the script cd's to the repo root):
#
#   bash scripts/demo.sh
#
# PostgreSQL 16 runs in Docker on host port 15432 because native PostgreSQL 12
# owns 5432. The explicit OPSCONDUCTOR_DATABASE_URL override below is required:
# the application default still points at 5432. Redis is not started and is not
# required by the MVP.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CONDA_ENV="${OPSCONDUCTOR_CONDA_ENV:-opsconductor}"
PORT="${OPSCONDUCTOR_PORT:-8000}"

# The Docker database lives on 15432; the app default (5432) is the native
# PostgreSQL 12 instance and must not be used for the demo.
export OPSCONDUCTOR_DATABASE_URL="${OPSCONDUCTOR_DATABASE_URL:-postgresql+psycopg://ops:ops@localhost:15432/opsconductor}"
# The demo runs deterministically without model credentials.
export OPSCONDUCTOR_STUB_LLM="${OPSCONDUCTOR_STUB_LLM:-true}"
export OPSCONDUCTOR_APP_ENV="${OPSCONDUCTOR_APP_ENV:-development}"

run_python() {
  if command -v conda >/dev/null 2>&1; then
    conda run --no-capture-output -n "$CONDA_ENV" "$@"
  else
    "$@"
  fi
}

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required (Docker Desktop with Compose v2)." >&2
  exit 1
fi

echo "==> Starting PostgreSQL 16 (host port 15432; Redis is not required)"
docker compose up -d postgres

echo "==> Waiting for PostgreSQL"
ready=0
for _ in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U ops -d opsconductor >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "PostgreSQL did not become ready; inspect 'docker compose logs postgres'." >&2
  exit 1
fi

echo "==> Applying Alembic migrations (idempotent)"
run_python alembic upgrade head

echo "==> Seeding demo data (idempotent)"
run_python python -m opsconductor.domain.seed

echo "==> Starting API on http://127.0.0.1:${PORT}"
echo "    Console: http://127.0.0.1:${PORT}/console/tasks?api_key=dev-operator-a"
echo "    API docs: http://127.0.0.1:${PORT}/docs"
echo "    Press Ctrl+C to stop the API; PostgreSQL keeps running."
# --reload is required on Windows: it makes uvicorn use the selector event
# loop, which psycopg's async connections require. Without it uvicorn selects
# ProactorEventLoop and every database request fails.
run_python uvicorn opsconductor.api.main:app --host 127.0.0.1 --port "$PORT" --reload
