#!/usr/bin/env bash
# Shared helpers for per-mailbox mail poller systemd instances.
#
# Instance names cannot contain @ (systemd treats it as the template separator),
# so gk07@gkhair.com becomes gk07-at-gkhair.com.

set -euo pipefail

mailbox_to_instance() {
  local email="$1"
  echo "$email" | tr '[:upper:]' '[:lower:]' | sed 's/@/-at-/'
}

instance_to_mailbox() {
  local instance="$1"
  echo "$instance" | sed 's/-at-/@/'
}

read_sync_mailboxes() {
  local env_file="${1:-/opt/zimbra-email-automation/.env}"
  if [[ ! -f "$env_file" ]]; then
    echo "Env file not found: $env_file" >&2
    return 1
  fi
  local raw
  raw="$(grep -E '^SYNC_MAILBOXES=' "$env_file" | tail -1 | cut -d= -f2- | tr -d '"'"'"'"' | tr -d ' ')" || true
  if [[ -z "$raw" ]]; then
    return 0
  fi
  local chunk email normalized
  normalized="${raw//$'\n'/,}"
  normalized="${normalized//;/,}"
  IFS=',' read -ra parts <<< "$normalized"
  for chunk in "${parts[@]}"; do
    email="${chunk#"${chunk%%[![:space:]]*}"}"
    email="${email%"${email##*[![:space:]]}"}"
    email="$(echo "$email" | tr '[:upper:]' '[:lower:]')"
    if [[ -n "$email" ]]; then
      printf '%s\n' "$email"
    fi
  done
}
