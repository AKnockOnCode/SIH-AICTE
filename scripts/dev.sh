#!/usr/bin/env bash
# One-command local start for AgniDrishti (Linux / macOS).
#
#   scripts/dev.sh            first run: create .venv, install Python packages, build the UI (if Node.js
#                             is installed; otherwise the prebuilt frontend/dist is served), then start
#   scripts/dev.sh --watch    development mode: rebuild the UI on change and reload the API on code change
#
# Safe by default: an existing database is reused. It is seeded only when empty (first start).
# To wipe and regenerate the demo data use:  make reset-db   (asks for confirmation)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
PYTHON="${PYTHON:-python3}"
WATCH=0
[ "${1:-}" = "--watch" ] && WATCH=1
cd "$ROOT"

if [ ! -x .venv/bin/python ]; then
  echo "==> Creating Python virtual environment in .venv"
  "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
  "$PYTHON" -m venv .venv
fi
if ! .venv/bin/python -c "import starlette, pydantic, uvicorn, multipart, sklearn, scipy, networkx, reportlab, openpyxl, xlsxwriter" 2>/dev/null; then
  echo "==> Installing Python packages (backend/requirements.txt)"
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r backend/requirements.txt
fi
[ -f .env ] || { cp .env.example .env; echo "==> Created .env from .env.example"; }

if command -v npm >/dev/null 2>&1; then
  if [ ! -d frontend/node_modules ]; then
    echo "==> Installing UI packages (npm install)"
    (cd frontend && npm install --no-audit --no-fund)
  fi
  if [ "$WATCH" = 1 ]; then
    (cd frontend && node build.mjs) && (cd frontend && node build.mjs --watch) &
    UI_PID=$!
    trap 'kill $UI_PID 2>/dev/null || true' EXIT
  else
    echo "==> Building the UI"
    (cd frontend && npm run build)
  fi
elif [ -f frontend/dist/index.html ]; then
  echo "==> Node.js not found: serving the prebuilt UI in frontend/dist"
else
  echo "!!  Node.js not found and frontend/dist is missing: only the API will be available"
fi

echo
echo "    AgniDrishti  ->  http://localhost:${PORT}"
echo "    API docs     ->  http://localhost:${PORT}/api/docs   (OpenAPI: /api/openapi.json)"
echo "    First start seeds the synthetic dataset and trains the local models (about 10 s). Press Ctrl+C to stop."
echo
(sleep 2 && (which xdg-open >/dev/null 2>&1 && xdg-open "http://localhost:${PORT}" || which open >/dev/null 2>&1 && open "http://localhost:${PORT}") 2>/dev/null) &
cd backend
if [ "$WATCH" = 1 ]; then
  exec ../.venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload --reload-dir app
else
  exec ../.venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
fi
