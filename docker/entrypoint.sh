#!/usr/bin/env bash
set -euo pipefail

CERT_DIR="/app/data/certs"
CERT_FILE="${CERT_DIR}/server.crt"
KEY_FILE="${CERT_DIR}/server.key"

mkdir -p "$CERT_DIR"

if [[ ! -f "$CERT_FILE" || ! -f "$KEY_FILE" ]]; then
  echo "[entrypoint] Generating self-signed TLS certificate..."
  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/CN=LiveU-Server-Monitor" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
fi

if [[ -n "${RESET_ADMIN_PASSWORD:-}" ]]; then
  echo "[entrypoint] RESET_ADMIN_PASSWORD is set. Startup will apply a forced admin password reset."
  echo "[entrypoint] Remove RESET_ADMIN_PASSWORD from .env after first successful startup."
fi

exec "$@"
