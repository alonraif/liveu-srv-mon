# LiveU Server Monitor (MVP)

Production-oriented local monitoring MVP for Ubuntu-based LiveU servers.

- Backend: FastAPI (Python)
- Frontend: React + Vite + TypeScript
- Storage: SQLite
- Runtime: Docker + docker-compose
- HTTPS: self-signed certificate generated automatically on first startup

## Features

- HTTPS-only web UI on `8443`
- Local administrator authentication with Argon2 password hashing
- First-login forced password change from hardcoded temporary default password
- Optional startup password reset via `RESET_ADMIN_PASSWORD` in `.env`
- Secure cookies: `HttpOnly`, `Secure`, `SameSite=Strict`
- Automatic logout after 10 minutes of inactivity (configurable)
- Closing browser/tab requires login again when reopened
- CSRF protection on authenticated POST requests
- Login rate limiting
- Audit logging for:
  - login events
  - log gather/download
  - LiveU service restart
  - server reboot
- Metrics collection every 5 seconds with 7-day retention:
  - CPU
  - Memory
  - Temperature (`sensors`, defensive parsing)
  - Disk usage
  - OS and kernel version
- Network view:
  - internal IP
  - public IP (multi-provider fallback)
  - link status
  - SSH port 22 status
- LiveU identity/config detection:
  - `/host/etc/liveu/baseuniqueid`
  - `/host/etc/liveu/server-license.txt`
- MMH/Transceiver parsing:
  - `MMH_INSTANCES` from `instances.py`
  - `PORT` from each existing `instanceN/collector.py`
  - `EXTERNAL_PREVIEW_TCP_PORT` and `LOCAL_HUB_PORT` from `overseer.py`
- Ingest mode:
  - read-only, size-capped file display with syntax highlighting for:
    - `ingest.py`
    - `ingest.hotfolderexposure.py`
    - `ingest.transcoder.py`
- Log bundle creation (`.tar.gz`) and download
  - filename format: `liveu-{server type}-logs-YYYY-MM-DD--HH:MM:SS-{server license}.tar.gz`
  - automatic bundle cleanup after 5 minutes
- Controlled admin actions:
  - restart LiveU service (password re-entry)
  - reboot server (password re-entry + `REBOOT` confirmation)

## Repository Structure

- `backend/` FastAPI app
- `frontend/` React app
- `scripts/liveu-admin-action` fixed command runner (no arbitrary command execution)
- `docker/entrypoint.sh` TLS cert bootstrap and startup checks
- `Dockerfile`
- `docker-compose.yml`
- `.env.example`

## Quick Start

### One-command installer (Ubuntu)

```bash
sudo bash scripts/install-liveu-server-monitor.sh
```

This script:

- installs Docker Engine + Docker Compose plugin
- installs required host packages
- opens `tcp/8443` in iptables and persists the rule
- builds and starts the app
- verifies `https://127.0.0.1:8443/healthz`

After install completes, open:

```text
https://SERVER_IP:8443
```

Your browser will warn about the self-signed cert on first access.

### Manual setup (if Docker is already installed)

1. Copy environment template:

```bash
cp .env.example .env
```

2. Build and start:

```bash
docker compose up -d --build
```

3. Open:

```text
https://SERVER_IP:8443
```

Your browser will warn about the self-signed cert on first access.

## First Login

- Username: `admin`
- Temporary default password (hardcoded): `ChangeMeNow!123`

The first login is forced to change password before dashboard access.

## Admin Password Reset via `.env`

Set in `.env`:

```env
RESET_ADMIN_PASSWORD=YourNewTemporaryPassword
```

On startup, the app resets the `admin` password and forces password change on next login.

After successful reset/login:

- Remove `RESET_ADMIN_PASSWORD` from `.env`
- Restart container

The app logs a warning and audit event when this variable is used.

## HTTPS / Certificate Behavior

- Cert path: `/app/data/certs/server.crt`
- Key path: `/app/data/certs/server.key`
- If either is missing, a new self-signed cert/key pair is generated on startup.

Persistent volume keeps certs across restarts.

## Required Mounts

Configured in `docker-compose.yml`:

- `/:/host-root:ro`
- `/etc/liveu:/host/etc/liveu:ro`
- `/opt/liveu:/opt/liveu:ro`
- `/logs:/host/logs:ro`
- `/proc:/host/proc:ro`
- `/sys:/host/sys:ro`
- `/run/systemd:/run/systemd`
- `/run/dbus/system_bus_socket:/run/dbus/system_bus_socket`
- `/etc/os-release:/host/etc/os-release:ro`
- Named volume `liveu_monitor_data:/app/data`

## Sudoers / Helper Setup

### Current MVP default

The container includes a strict sudoers allowlist for user `app`:

- `sudo -n /usr/bin/systemctl restart liveu`
- `sudo -n /usr/bin/systemctl is-active liveu`
- `sudo -n /usr/bin/env SYSTEMCTL_FORCE_BUS=1 /usr/bin/systemctl restart liveu`
- `sudo -n /usr/bin/env SYSTEMCTL_FORCE_BUS=1 /usr/bin/systemctl is-active liveu`
- `sudo -n /usr/local/bin/liveu-config-read *`
- `sudo -n /opt/liveu/debug/version.sh`
- `sudo -n /sbin/reboot`

The API calls only `scripts/liveu-admin-action` logic copied to `/usr/local/bin/liveu-admin-action`.

No arbitrary commands are accepted by the API.

### Optional host helper model

If you require an explicit host-side helper script flow, use `scripts/liveu-host-helper.example.sh` as a template and bind that path into the container, then update `ADMIN_COMMAND_RUNNER` and sudoers accordingly.

## Security Notes

- No privileged Docker mode is used.
- Only host port `8443` is exposed.
- App uses HTTPS only.
- Session cookie is `HttpOnly + Secure + SameSite=Strict`.
- Idle sessions are invalidated after 10 minutes by default (`SESSION_IDLE_TIMEOUT_SECONDS`).
- Auth cookies are non-persistent and the UI enforces per-tab login, so reopening a closed tab/browser requires login again.
- CSRF token is required for authenticated POST actions.
- Login endpoint uses per-IP+username rate limiting.
- Admin actions enforce additional confirmation requirements.
- LiveU config files are parsed as text/AST literals only; never executed.
- `sensors` command invocation is fixed and non-user-controllable.

## Troubleshooting

1. `https://SERVER_IP:8443` not reachable
- Check `docker compose ps`
- Confirm host firewall allows `8443/tcp`

2. Admin actions fail (`restart-liveu` or `reboot`)
- Verify host supports systemd command path from this container context
- Verify mounted `/run/systemd` and `/run/dbus/system_bus_socket`
- Validate service name is exactly `liveu`

3. LiveU config missing in UI
- Ensure `/etc/liveu` exists on host and is mounted correctly
- Check file permissions for mounted paths

4. Public IP shows unavailable
- External lookup endpoints may be blocked; UI will display unavailable gracefully

5. Password reset keeps triggering
- Remove `RESET_ADMIN_PASSWORD` from `.env`
- Restart container

## Development (Optional)

Frontend:

```bash
cd frontend
npm ci
npm run build
```

Backend:

```bash
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload
```
