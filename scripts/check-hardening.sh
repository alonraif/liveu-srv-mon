#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() {
  echo "[hardening-check] $1" >&2
  exit 1
}

echo "[hardening-check] Checking docker-compose runtime privileges..."
if rg -n "^\s*privileged:\s*true\b" docker-compose.yml >/dev/null; then
  fail "docker-compose.yml must not enable privileged mode."
fi
if rg -n "^\s*pid:\s*host\b" docker-compose.yml >/dev/null; then
  fail "docker-compose.yml must not use host PID namespace."
fi
if rg -n "apparmor=unconfined" docker-compose.yml >/dev/null; then
  fail "docker-compose.yml must not disable apparmor confinement."
fi

echo "[hardening-check] Checking no-new-privileges and cap-drop..."
rg -n "no-new-privileges:true" docker-compose.yml >/dev/null || fail "no-new-privileges:true missing from docker-compose.yml."
rg -n "cap_drop:\s*$" docker-compose.yml >/dev/null || fail "cap_drop block missing from docker-compose.yml."
rg -n "^\s*-\s*ALL\s*$" docker-compose.yml >/dev/null || fail "cap_drop must include ALL."

echo "[hardening-check] Checking for sudo escalation in container image/runtime code..."
if rg -n "NOPASSWD|sudo\s+-n|nsenter" \
  Dockerfile \
  backend \
  docker \
  scripts/liveu-host-helper-client \
  scripts/liveu-host-helperd.py \
  scripts/ensure-liveu-ui-firewall.sh >/dev/null; then
  fail "Detected forbidden sudo/nsenter escalation pattern in runtime code."
fi

echo "[hardening-check] Passed."
