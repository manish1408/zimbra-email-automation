#!/usr/bin/env bash
# Run on the SSH server to control the mail poller systemd service.
# Installed path on server: /opt/zimbra-email-automation/scripts/mail-poller-service.sh
#
# Usage:
#   ./scripts/mail-poller-service.sh start|stop|restart|status|logs

set -euo pipefail

SERVICE="${MAIL_POLLER_SERVICE:-zimbra-mail-poller}"

usage() {
  echo "Usage: $0 {start|stop|restart|status|logs|logs -f|enable|disable}"
  exit "${1:-0}"
}

cmd="${1:-}"
shift || true

case "$cmd" in
  start)
    systemctl start "$SERVICE"
    systemctl is-active "$SERVICE"
    ;;
  stop)
    systemctl stop "$SERVICE"
    echo "stopped"
    ;;
  restart)
    systemctl restart "$SERVICE"
    systemctl is-active "$SERVICE"
    ;;
  status)
    systemctl status "$SERVICE" --no-pager
    ;;
  logs)
    if [[ "${1:-}" == "-f" ]]; then
      journalctl -u "$SERVICE" -f
    else
      journalctl -u "$SERVICE" -n 50 --no-pager
    fi
    ;;
  enable)  systemctl enable "$SERVICE" ;;
  disable) systemctl disable "$SERVICE" ;;
  *) usage 1 ;;
esac
