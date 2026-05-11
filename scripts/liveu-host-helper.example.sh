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
  liveu-config-show)
    exec /bin/bash -lc 'liveu-config --show'
    ;;
  set-whatismyip)
    ip="${2:-}"
    [[ -n "$ip" ]] || { echo "missing ip" >&2; exit 2; }
    printf "STATIC_IP_LIST = ['%s']\n" "$ip" > /etc/liveu/whatismyip.py
    ;;
  clear-whatismyip)
    rm -f /etc/liveu/whatismyip.py
    ;;
  *)
    echo "unsupported action" >&2
    exit 2
    ;;
esac
