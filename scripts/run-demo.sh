#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILDER_DIR="$ROOT_DIR/demo/langgraph-builder"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
UVICORN="$ROOT_DIR/.venv/bin/uvicorn"

FASTAPI_PORT="${FASTAPI_PORT:-8000}"
BUILDER_PORT="${BUILDER_PORT:-3000}"

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]]; then
    kill "$UVICORN_PID" 2>/dev/null || true
  fi
  if [[ -n "${BUILDER_PID:-}" ]]; then
    kill "$BUILDER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -x "$UVICORN" ]]; then
  echo "Virtualenv not found. Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "Missing .env file. Copy .env.example and configure Zimbra + OPENAI_API_KEY."
  exit 1
fi

mkdir -p "$ROOT_DIR/data"

if [[ ! -d "$BUILDER_DIR" ]]; then
  echo "Cloning LangGraph Builder into demo/langgraph-builder..."
  git clone --depth 1 https://github.com/langchain-ai/langgraph-builder.git "$BUILDER_DIR"
fi

if [[ ! -d "$BUILDER_DIR/node_modules" ]]; then
  echo "Installing LangGraph Builder dependencies..."
  (cd "$BUILDER_DIR" && yarn install)
fi

echo "Starting FastAPI on http://localhost:${FASTAPI_PORT}"
(cd "$ROOT_DIR" && "$UVICORN" app.main:app --host 0.0.0.0 --port "$FASTAPI_PORT" --reload) &
UVICORN_PID=$!

echo "Starting LangGraph Builder on http://localhost:${BUILDER_PORT}"
(cd "$BUILDER_DIR" && yarn dev -p "$BUILDER_PORT") &
BUILDER_PID=$!

sleep 3

echo ""
echo "Demo ready:"
echo "  LangGraph Builder : http://localhost:${BUILDER_PORT}"
echo "  Live demo UI      : http://localhost:${FASTAPI_PORT}/demo"
echo "  Swagger docs      : http://localhost:${FASTAPI_PORT}/docs"
echo ""
echo "Press Ctrl+C to stop both services."

wait
