#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILDER_DIR="$ROOT_DIR/demo/langgraph-builder"
BUILDER_PORT="${BUILDER_PORT:-3000}"

if [[ ! -d "$BUILDER_DIR" ]]; then
  echo "Cloning LangGraph Builder..."
  git clone --depth 1 https://github.com/langchain-ai/langgraph-builder.git "$BUILDER_DIR"
fi

if [[ ! -d "$BUILDER_DIR/node_modules" ]]; then
  echo "Installing dependencies (first run may take ~1 min)..."
  (cd "$BUILDER_DIR" && yarn install)
fi

echo "Starting LangGraph Builder at http://localhost:${BUILDER_PORT}"
cd "$BUILDER_DIR" && exec yarn dev -p "$BUILDER_PORT"
