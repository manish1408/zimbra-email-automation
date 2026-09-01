#!/usr/bin/env bash
# Install one systemd process per mailbox listed in SYNC_MAILBOXES.
#
# Run on the server (or via SSH from your laptop):
#   ./scripts/setup-mailbox-pollers.sh
#   ./scripts/setup-mailbox-pollers.sh --disable-legacy   # stop monolithic poller
#   ./scripts/setup-mailbox-pollers.sh --status
#
# Requires SYNC_MAILBOXES in .env, e.g.:
#   SYNC_MAILBOXES=gk07@gkhair.com,meghan.mchugh@gkhair.com

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/mailbox-poller-utils.sh"

APP_DIR="${APP_DIR:-/opt/zimbra-email-automation}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
POLLER_CONFIG_DIR="${POLLER_CONFIG_DIR:-$APP_DIR/config/pollers}"
SYSTEMD_UNIT_SRC="${SYSTEMD_UNIT_SRC:-$APP_DIR/deploy/systemd/zimbra-mail-poller@.service}"
SYSTEMD_UNIT_DST="/etc/systemd/system/zimbra-mail-poller@.service"
LEGACY_SERVICE="zimbra-mail-poller"
TEMPLATE_SERVICE="zimbra-mail-poller@"

DISABLE_LEGACY=false
SHOW_STATUS=false

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \?//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --disable-legacy) DISABLE_LEGACY=true; shift ;;
    --status) SHOW_STATUS=true; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

if [[ "$SHOW_STATUS" == true ]]; then
  echo "Legacy service:"
  systemctl is-enabled "$LEGACY_SERVICE" 2>/dev/null || echo "  (not installed)"
  systemctl is-active "$LEGACY_SERVICE" 2>/dev/null || true
  echo
  echo "Per-mailbox pollers:"
  systemctl list-units "${TEMPLATE_SERVICE}*" --all --no-pager --no-legend || true
  exit 0
fi

mapfile -t mailboxes < <(read_sync_mailboxes "$ENV_FILE" | sort -u)
if [[ ${#mailboxes[@]} -eq 0 ]]; then
  echo "SYNC_MAILBOXES is empty in $ENV_FILE" >&2
  echo "Set SYNC_MAILBOXES=user1@example.com,user2@example.com and re-run." >&2
  exit 1
fi

if [[ ! -f "$SYSTEMD_UNIT_SRC" ]]; then
  echo "Missing template unit: $SYSTEMD_UNIT_SRC" >&2
  exit 1
fi

mkdir -p "$POLLER_CONFIG_DIR"
install -m 644 "$SYSTEMD_UNIT_SRC" "$SYSTEMD_UNIT_DST"

declare -A desired_instances=()
for mailbox in "${mailboxes[@]}"; do
  instance="$(mailbox_to_instance "$mailbox")"
  desired_instances["$instance"]=1
  cat > "$POLLER_CONFIG_DIR/${instance}.env" <<EOF
MAILBOX=${mailbox}
EOF
  echo "Configured $mailbox -> ${TEMPLATE_SERVICE}${instance}"
done

# Remove stale poller configs for mailboxes no longer in SYNC_MAILBOXES.
shopt -s nullglob
for env_path in "$POLLER_CONFIG_DIR"/*.env; do
  instance="$(basename "$env_path" .env)"
  if [[ -z "${desired_instances[$instance]+x}" ]]; then
    echo "Removing stale poller config: $instance"
    rm -f "$env_path"
    systemctl disable --now "${TEMPLATE_SERVICE}${instance}" 2>/dev/null || true
  fi
done
shopt -u nullglob

systemctl daemon-reload

for instance in "${!desired_instances[@]}"; do
  unit="${TEMPLATE_SERVICE}${instance}"
  systemctl enable "$unit"
  systemctl restart "$unit"
  echo "Started $unit ($(instance_to_mailbox "$instance"))"
done

if [[ "$DISABLE_LEGACY" == true ]]; then
  systemctl disable --now "$LEGACY_SERVICE" 2>/dev/null || true
  echo "Disabled legacy $LEGACY_SERVICE (monolithic all-mailbox poller)."
else
  echo
  echo "Note: legacy $LEGACY_SERVICE is still enabled."
  echo "Disable it to avoid double-processing:"
  echo "  systemctl disable --now $LEGACY_SERVICE"
  echo "Or re-run with: $0 --disable-legacy"
fi

echo
echo "Done. ${#mailboxes[@]} mailbox poller(s) running."
echo "Logs: journalctl -u '${TEMPLATE_SERVICE}*' -f"
