#!/usr/bin/env bash
set -euo pipefail

# LiveU Server Monitor installer/bootstrap for Ubuntu
# - Installs Docker Engine + Compose plugin
# - Opens TCP 8443 in iptables (and persists rules)
# - Builds/starts the app with docker compose
# - Verifies local HTTPS health endpoint

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root (sudo)."
  echo "Example: sudo bash scripts/install-liveu-server-monitor.sh"
  exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer currently supports Ubuntu systems with apt-get."
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  echo "Missing /etc/os-release; cannot verify Ubuntu release."
  exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
  echo "Unsupported OS: ${ID:-unknown}. This installer currently supports Ubuntu only."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "[1/9] Installing base prerequisites..."
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release iptables iptables-persistent

echo "[2/9] Installing Docker Engine and Compose plugin..."
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
fi
chmod a+r /etc/apt/keyrings/docker.gpg

CODENAME="${VERSION_CODENAME:-}"

if [[ -z "${CODENAME}" ]]; then
  echo "Could not determine Ubuntu codename from /etc/os-release"
  exit 1
fi

cat > /etc/apt/sources.list.d/docker.list <<EOL
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable
EOL

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

echo "[3/9] Verifying Docker installation..."
docker --version
docker compose version

echo "[3b/9] Enabling Docker CLI access without sudo..."
docker_user="${SUDO_USER:-}"
if [[ -z "${docker_user}" ]]; then
  docker_user="$(logname 2>/dev/null || true)"
fi
if [[ -z "${docker_user}" || "${docker_user}" == "root" ]]; then
  echo "  [warn] Could not determine a non-root user to add to docker group."
  echo "  [info] Run this after install as needed: sudo usermod -aG docker <username>"
else
  if id -nG "${docker_user}" | tr ' ' '\n' | grep -qx docker; then
    echo "  [ok] User '${docker_user}' is already in docker group."
  else
    usermod -aG docker "${docker_user}"
    echo "  [ok] Added '${docker_user}' to docker group."
    echo "  [info] '${docker_user}' must log out/in (or run 'newgrp docker') before non-sudo docker commands work."
  fi
fi

echo "[4/9] Restricting TCP 8443 to local ETH subnets..."
# Remove legacy broad rule if present.
while iptables -D INPUT -p tcp --dport 8443 -j ACCEPT 2>/dev/null; do :; done
# Remove previously managed subnet rules.
while IFS= read -r line; do
  [[ "$line" == "-A INPUT"* ]] || continue
  [[ "$line" == *"LIVEU_UI_INPUT_SUBNET_8443"* ]] || continue
  rule_spec="${line#-A INPUT }"
  # shellcheck disable=SC2086
  iptables -D INPUT $rule_spec || true
done < <(iptables -S INPUT)

mapfile -t eth_subnets < <(ip -o -4 addr show up | awk '$2 ~ /^eth[0-9]+$/ {print $4}' | sort -u)
if [[ "${#eth_subnets[@]}" -eq 0 ]]; then
  echo "No active eth* IPv4 subnets found; refusing to expose tcp/8443."
  exit 1
fi
for subnet in "${eth_subnets[@]}"; do
  iptables -I INPUT 1 -p tcp -s "$subnet" --dport 8443 -m comment --comment LIVEU_UI_INPUT_SUBNET_8443 -j ACCEPT
  echo "Added restricted INPUT rule for tcp/8443 from ${subnet}"
done

if command -v netfilter-persistent >/dev/null 2>&1; then
  netfilter-persistent save
  echo "Persisted iptables rules via netfilter-persistent."
else
  iptables-save > /etc/iptables/rules.v4
  echo "Persisted iptables rules to /etc/iptables/rules.v4"
fi

echo "[5/9] Installing host helper service..."
install -m 0755 "${REPO_ROOT}/scripts/liveu-host-helperd.py" /usr/local/sbin/liveu-host-helperd.py
install -m 0644 "${REPO_ROOT}/scripts/liveu-host-helper.service" /etc/systemd/system/liveu-host-helper.service
install -d -m 0755 /run/liveu-helper
systemctl daemon-reload
systemctl enable --now liveu-host-helper.service
if [[ ! -S /run/liveu-helper/liveu-helper.sock ]]; then
  echo "Host helper socket missing: /run/liveu-helper/liveu-helper.sock"
  systemctl status --no-pager liveu-host-helper.service || true
  exit 1
fi

echo "[6/9] Ensuring runtime env file exists..."
cd "${REPO_ROOT}"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

generated_initial_admin=0
generated_initial_monitor=0

if ! grep -q '^INITIAL_ADMIN_PASSWORD=' .env; then
  echo 'INITIAL_ADMIN_PASSWORD=' >> .env
fi
if ! grep -q '^INITIAL_MONITOR_PASSWORD=' .env; then
  echo 'INITIAL_MONITOR_PASSWORD=' >> .env
fi
current_initial="$(grep '^INITIAL_ADMIN_PASSWORD=' .env | tail -n1 | cut -d= -f2-)"
current_monitor_initial="$(grep '^INITIAL_MONITOR_PASSWORD=' .env | tail -n1 | cut -d= -f2-)"
if [[ -z "${current_initial}" ]]; then
  generated_password="$(openssl rand -base64 24 | tr -d '\n' | tr '/+' 'AB')"
  sed -i "s|^INITIAL_ADMIN_PASSWORD=.*$|INITIAL_ADMIN_PASSWORD=${generated_password}|" .env
  generated_initial_admin=1
  echo "Generated INITIAL_ADMIN_PASSWORD in .env for first startup."
  echo "Temporary initial administrator password: ${generated_password}"
  echo "Change it immediately after first login."
fi
if [[ -z "${current_monitor_initial}" ]]; then
  generated_monitor_password="$(openssl rand -base64 24 | tr -d '\n' | tr '/+' 'CD')"
  sed -i "s|^INITIAL_MONITOR_PASSWORD=.*$|INITIAL_MONITOR_PASSWORD=${generated_monitor_password}|" .env
  generated_initial_monitor=1
  echo "Generated INITIAL_MONITOR_PASSWORD in .env for first startup."
  echo "Temporary initial monitor password: ${generated_monitor_password}"
  echo "Change it immediately after first login."
fi

if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  chown "${SUDO_USER}:${SUDO_USER}" .env || true
fi
chmod 0640 .env

echo "[7/9] Validating expected host mounts..."
check_mount_path() {
  local p="$1"
  if [[ -e "$p" ]]; then
    echo "  [ok] $p"
  else
    echo "  [warn] Missing path: $p"
  fi
}
check_mount_path /etc/liveu
check_mount_path /opt/liveu
check_mount_path /logs
check_mount_path /proc
check_mount_path /sys
check_mount_path /run/liveu-helper
check_mount_path /etc/os-release

echo "[8/9] Building and starting LiveU Server Monitor..."
docker compose down --remove-orphans || true
docker compose up -d --build

echo "[9/9] Waiting for health endpoint..."
for i in {1..30}; do
  if curl -kfsS https://127.0.0.1:8443/healthz >/dev/null 2>&1; then
    echo "Health check passed: https://127.0.0.1:8443/healthz"

    if [[ "${generated_initial_admin}" -eq 1 || "${generated_initial_monitor}" -eq 1 ]]; then
      echo "Scrubbing one-time INITIAL_* bootstrap passwords from .env..."
      sed -i "s|^INITIAL_ADMIN_PASSWORD=.*$|INITIAL_ADMIN_PASSWORD=|" .env
      sed -i "s|^INITIAL_MONITOR_PASSWORD=.*$|INITIAL_MONITOR_PASSWORD=|" .env
      echo "Restarting container to drop bootstrap passwords from runtime environment..."
      docker compose up -d --force-recreate
      if ! curl -kfsS https://127.0.0.1:8443/healthz >/dev/null 2>&1; then
        echo "Post-scrub health check failed."
        docker compose logs --tail=120 liveu-server-monitor || true
        exit 1
      fi
      echo "Bootstrap passwords removed from .env and runtime environment."
    fi

    docker compose ps
    echo "Install complete. Open: https://<SERVER_IP>:8443"
    exit 0
  fi
  sleep 2
done

echo "Health check did not pass in time. Recent logs:"
docker compose logs --tail=120 liveu-server-monitor || true
exit 1
