#!/usr/bin/env bash
# Sync app to production, deploy frontend dist, restart services, verify health.
#
# Usage (from project root):
#   ./scripts/redeploy.sh              # full redeploy (backend + frontend)
#   ./scripts/redeploy.sh backend      # Python only
#   ./scripts/redeploy.sh frontend     # Angular dist only
#
# Config: deploy.env (copy from deploy.env.example)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/deploy.env" ]]; then
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/deploy.env"
fi

DEPLOY_HOST="${DEPLOY_HOST:-176.123.3.2}"
DEPLOY_USER="${DEPLOY_USER:-root}"
APP_DIR="${APP_DIR:-/opt/zimbra-email-automation}"
MODE="${1:-all}"

ssh_cmd() {
  local ssh_opts=(-o StrictHostKeyChecking=no -o ConnectTimeout=15)
  if [[ -n "${DEPLOY_PASSWORD:-}" ]] && command -v sshpass >/dev/null 2>&1; then
    sshpass -p "$DEPLOY_PASSWORD" ssh "${ssh_opts[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "$@"
  elif [[ -n "${DEPLOY_PASSWORD:-}" ]]; then
    echo "DEPLOY_PASSWORD is set but sshpass is not installed." >&2
    exit 1
  else
    ssh "${ssh_opts[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "$@"
  fi
}

rsync_cmd() {
  local ssh_opts="-o StrictHostKeyChecking=no -o ConnectTimeout=15"
  if [[ -n "${DEPLOY_PASSWORD:-}" ]] && command -v sshpass >/dev/null 2>&1; then
    sshpass -p "$DEPLOY_PASSWORD" rsync -e "ssh ${ssh_opts}" "$@"
  else
    rsync -e "ssh ${ssh_opts}" "$@"
  fi
}

scp_cmd() {
  local scp_opts=(-o StrictHostKeyChecking=no -o ConnectTimeout=15)
  if [[ -n "${DEPLOY_PASSWORD:-}" ]] && command -v sshpass >/dev/null 2>&1; then
    sshpass -p "$DEPLOY_PASSWORD" scp "${scp_opts[@]}" "$@"
  else
    scp "${scp_opts[@]}" "$@"
  fi
}

sync_backend() {
  echo "Syncing backend to ${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}..."
  rsync_cmd -avz --delete \
    --exclude '.venv' --exclude 'venv' --exclude 'node_modules' --exclude '.git' \
    --exclude 'data' --exclude 'logs' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'frontend/dist' --exclude '.DS_Store' --exclude 'deploy.env' \
    "$PROJECT_ROOT/" "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/"
  scp_cmd "$PROJECT_ROOT/.env" "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/.env"
}

sync_frontend() {
  echo "Syncing frontend dist..."
  rsync_cmd -avz \
    "$PROJECT_ROOT/frontend/dist/" \
    "${DEPLOY_USER}@${DEPLOY_HOST}:${APP_DIR}/frontend/dist/"
}

build_frontend() {
  echo "Building frontend..."
  (cd "$PROJECT_ROOT/frontend" && npm run build)
}

restart_services() {
  echo "Restarting services..."
  if [[ "$MODE" == "frontend" ]]; then
    ssh_cmd "systemctl reload nginx"
  else
    ssh_cmd "systemctl restart zimbra-api zimbra-mail-poller nginx"
  fi
}

verify() {
  echo "Health check:"
  curl -s "http://${DEPLOY_HOST}/api/v1/system/health"
  echo
  curl -o /dev/null -s -w "Frontend: HTTP %{http_code}\n" "http://${DEPLOY_HOST}/"
}

case "$MODE" in
  all)
    build_frontend
    sync_backend
    sync_frontend
    restart_services
    verify
    ;;
  backend)
    sync_backend
    ssh_cmd "systemctl restart zimbra-api zimbra-mail-poller"
    verify
    ;;
  frontend)
    build_frontend
    sync_frontend
    restart_services
    verify
    ;;
  *)
    echo "Usage: $0 [all|backend|frontend]" >&2
    exit 1
    ;;
esac

echo "Deploy complete."
