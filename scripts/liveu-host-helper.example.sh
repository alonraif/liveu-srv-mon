#!/usr/bin/env bash
# Example HOST helper script if you prefer binding host commands through one allowlisted executable.
# Install on host as /usr/local/sbin/liveu-host-helper and allow only this script in sudoers.
set -euo pipefail

action="${1:-}"
case "$action" in
  restart-liveu)
    exec /usr/bin/systemctl restart liveu
    ;;
  reboot)
    exec /sbin/reboot
    ;;
  *)
    echo "unsupported action" >&2
    exit 2
    ;;
esac
