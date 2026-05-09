#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8443}"
CONTAINER_NAME="${CONTAINER_NAME:-liveu-server-monitor}"
INPUT_COMMENT="${INPUT_COMMENT:-LIVEU_UI_INPUT_8443}"
FWD_IN_COMMENT="${FWD_IN_COMMENT:-LIVEU_UI_FWD_IN_8443}"
FWD_OUT_COMMENT="${FWD_OUT_COMMENT:-LIVEU_UI_FWD_OUT_8443}"
PUBLIC_IP_CACHE_FILE="${PUBLIC_IP_CACHE_FILE:-/tmp/liveu-public-ip.txt}"

ensure_rule() {
  local chain="$1"
  shift
  if ! iptables -C "$chain" "$@" 2>/dev/null; then
    iptables -I "$chain" 1 "$@"
  fi
}

delete_rule_spec() {
  local chain="$1"
  local spec="$2"
  # shellcheck disable=SC2086
  eval "iptables -D \"$chain\" $spec" || true
}

cleanup_stale_forward_rules() {
  local current_ip="$1"
  local line rule_spec

  while IFS= read -r line; do
    [[ "$line" == "-A FORWARD"* ]] || continue
    if [[ "$line" == *"--comment"*"$FWD_IN_COMMENT"* ]] && [[ "$line" != *"-d $current_ip"* ]]; then
      rule_spec="${line#-A FORWARD }"
      delete_rule_spec FORWARD "$rule_spec"
    fi
    if [[ "$line" == *"--comment"*"$FWD_OUT_COMMENT"* ]] && [[ "$line" != *"-s $current_ip"* ]]; then
      rule_spec="${line#-A FORWARD }"
      delete_rule_spec FORWARD "$rule_spec"
    fi
  done < <(iptables -S FORWARD)
}

cleanup_legacy_forward_rules() {
  local line rule_spec
  while IFS= read -r line; do
    [[ "$line" == "-A FORWARD"* ]] || continue
    [[ "$line" == *"--comment"*"$FWD_IN_COMMENT"* || "$line" == *"--comment"*"$FWD_OUT_COMMENT"* ]] && continue
    if [[ "$line" == *"--dport $PORT"* && "$line" == *"--ctstate NEW,ESTABLISHED"* ]]; then
      rule_spec="${line#-A FORWARD }"
      delete_rule_spec FORWARD "$rule_spec"
      continue
    fi
    if [[ "$line" == *"--sport $PORT"* && "$line" == *"--ctstate ESTABLISHED"* ]]; then
      rule_spec="${line#-A FORWARD }"
      delete_rule_spec FORWARD "$rule_spec"
    fi
  done < <(iptables -S FORWARD)
}

refresh_public_ip_cache() {
  local fetched
  fetched="$(python3 - <<'PY'
import re
import urllib.request

urls = [
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
    "https://ifconfig.me/ip",
]
pat = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
for url in urls:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            value = resp.read().decode("utf-8", "ignore").strip()
        if pat.fullmatch(value):
            print(value)
            break
    except Exception:
        continue
PY
)"
  if [[ -n "${fetched:-}" ]]; then
    printf '%s\n' "$fetched" > "${PUBLIC_IP_CACHE_FILE}.tmp"
    mv -f "${PUBLIC_IP_CACHE_FILE}.tmp" "$PUBLIC_IP_CACHE_FILE"
    chmod 0644 "$PUBLIC_IP_CACHE_FILE"
  fi
}

# 1) Ensure host accepts inbound TCP/8443.
ensure_rule INPUT -p tcp --dport "$PORT" -m comment --comment "$INPUT_COMMENT" -j ACCEPT

# 2) Ensure forwarding rules for the current UI container IP.
container_ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CONTAINER_NAME" 2>/dev/null || true)"
if [[ -n "$container_ip" ]]; then
  cleanup_legacy_forward_rules
  cleanup_stale_forward_rules "$container_ip"
  ensure_rule FORWARD -p tcp -d "$container_ip" --dport "$PORT" -m conntrack --ctstate NEW,ESTABLISHED -m comment --comment "$FWD_IN_COMMENT" -j ACCEPT
  ensure_rule FORWARD -p tcp -s "$container_ip" --sport "$PORT" -m conntrack --ctstate ESTABLISHED -m comment --comment "$FWD_OUT_COMMENT" -j ACCEPT
fi

# 3) Refresh host-derived public IP cache (best effort).
refresh_public_ip_cache || true
