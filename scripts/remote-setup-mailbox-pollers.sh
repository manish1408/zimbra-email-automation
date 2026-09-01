#!/usr/bin/env bash
# Run setup-mailbox-pollers.sh on the production server via SSH.
#
# Usage:
#   ./scripts/remote-setup-mailbox-pollers.sh
#   ./scripts/remote-setup-mailbox-pollers.sh --disable-legacy
#   ./scripts/remote-setup-mailbox-pollers.sh --status

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

remote() {
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

remote "APP_DIR=${APP_DIR} ${APP_DIR}/scripts/setup-mailbox-pollers.sh $*"
