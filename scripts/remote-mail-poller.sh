#!/usr/bin/env bash
# Start, stop, or inspect the mail poller on the production SSH server.
#
# Usage (from project root):
#   ./scripts/remote-mail-poller.sh start
#   ./scripts/remote-mail-poller.sh stop
#   ./scripts/remote-mail-poller.sh status
#   ./scripts/remote-mail-poller.sh restart
#   ./scripts/remote-mail-poller.sh logs          # last 50 lines
#   ./scripts/remote-mail-poller.sh logs -f       # follow live
#   ./scripts/remote-mail-poller.sh enable        # start on boot
#   ./scripts/remote-mail-poller.sh disable       # do not start on boot
#
# Config: deploy.env in project root (copy from deploy.env.example)
#         or DEPLOY_HOST / DEPLOY_USER / DEPLOY_PASSWORD env vars.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/deploy.env" ]]; then
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/deploy.env"
fi

DEPLOY_HOST="${DEPLOY_HOST:-176.123.3.2}"
DEPLOY_USER="${DEPLOY_USER:-root}"
MAIL_POLLER_SERVICE="${MAIL_POLLER_SERVICE:-zimbra-mail-poller}"

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \?//'
  exit "${1:-0}"
}

remote() {
  local ssh_opts=(-o StrictHostKeyChecking=no -o ConnectTimeout=15)
  if [[ -n "${DEPLOY_PASSWORD:-}" ]] && command -v sshpass >/dev/null 2>&1; then
    sshpass -p "$DEPLOY_PASSWORD" ssh "${ssh_opts[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "$@"
  elif [[ -n "${DEPLOY_PASSWORD:-}" ]]; then
    echo "DEPLOY_PASSWORD is set but sshpass is not installed." >&2
    echo "Install: brew install hudochenkov/sshpass/sshpass" >&2
    echo "Or set up SSH keys and remove DEPLOY_PASSWORD from deploy.env" >&2
    exit 1
  else
    ssh "${ssh_opts[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" "$@"
  fi
}

cmd="${1:-}"
shift || true

case "$cmd" in
  start)
    echo "Starting ${MAIL_POLLER_SERVICE} on ${DEPLOY_USER}@${DEPLOY_HOST}..."
    remote "systemctl start ${MAIL_POLLER_SERVICE}"
    remote "systemctl is-active ${MAIL_POLLER_SERVICE}"
    echo "Mail poller is running."
    ;;
  stop)
    echo "Stopping ${MAIL_POLLER_SERVICE} on ${DEPLOY_USER}@${DEPLOY_HOST}..."
    remote "systemctl stop ${MAIL_POLLER_SERVICE}"
    echo "Mail poller stopped."
    ;;
  restart)
    echo "Restarting ${MAIL_POLLER_SERVICE} on ${DEPLOY_USER}@${DEPLOY_HOST}..."
    remote "systemctl restart ${MAIL_POLLER_SERVICE}"
    remote "systemctl is-active ${MAIL_POLLER_SERVICE}"
    echo "Mail poller restarted."
    ;;
  status)
    remote "systemctl status ${MAIL_POLLER_SERVICE} --no-pager"
    ;;
  logs)
    if [[ "${1:-}" == "-f" ]]; then
      echo "Following logs (Ctrl+C to exit)..."
      remote "journalctl -u ${MAIL_POLLER_SERVICE} -f"
    else
      remote "journalctl -u ${MAIL_POLLER_SERVICE} -n 50 --no-pager"
    fi
    ;;
  enable)
    remote "systemctl enable ${MAIL_POLLER_SERVICE}"
    echo "Mail poller will start automatically on boot."
    ;;
  disable)
    remote "systemctl disable ${MAIL_POLLER_SERVICE}"
    echo "Mail poller will not start on boot (use 'start' to run manually)."
    ;;
  help|-h|--help|"")
    usage 0
    ;;
  *)
    echo "Unknown command: $cmd" >&2
    usage 1
    ;;
esac
