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

echo "[1/8] Installing base prerequisites..."
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release iptables iptables-persistent

echo "[2/8] Installing Docker Engine and Compose plugin..."
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

echo "[3/8] Verifying Docker installation..."
docker --version
docker compose version

echo "[4/8] Opening TCP 8443 in iptables..."
if iptables -C INPUT -p tcp --dport 8443 -j ACCEPT 2>/dev/null; then
  echo "iptables rule for 8443 already exists."
else
  iptables -I INPUT -p tcp --dport 8443 -j ACCEPT
  echo "Added iptables INPUT rule for tcp/8443"
fi

if command -v netfilter-persistent >/dev/null 2>&1; then
  netfilter-persistent save
  echo "Persisted iptables rules via netfilter-persistent."
else
  iptables-save > /etc/iptables/rules.v4
  echo "Persisted iptables rules to /etc/iptables/rules.v4"
fi

echo "[5/8] Ensuring runtime env file exists..."
cd "${REPO_ROOT}"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "[6/8] Validating expected host mounts..."
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
check_mount_path /run/systemd
check_mount_path /run/dbus/system_bus_socket
check_mount_path /etc/os-release

echo "[7/8] Building and starting LiveU Server Monitor..."
docker compose down --remove-orphans || true
docker compose up -d --build

echo "[8/8] Waiting for health endpoint..."
for i in {1..30}; do
  if curl -kfsS https://127.0.0.1:8443/healthz >/dev/null 2>&1; then
    echo "Health check passed: https://127.0.0.1:8443/healthz"
    docker compose ps
    echo "Install complete. Open: https://<SERVER_IP>:8443"
    exit 0
  fi
  sleep 2
done

echo "Health check did not pass in time. Recent logs:"
docker compose logs --tail=120 liveu-server-monitor || true
exit 1
