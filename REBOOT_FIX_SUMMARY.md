# Host Reboot Fix Summary

## Problem
When attempting to reboot the server from the UI, the system failed with:
```
Failed to reboot server: sudo: /sbin/reboot: command not found
```

This occurred because the reboot command was trying to execute `/sbin/reboot` inside the container, where:
1. The command doesn't exist (container doesn't have reboot utilities)
2. Even if it did exist, it would try to reboot the container, not the host

## Solution
Modified the system to use `nsenter` to enter the host's namespace and execute the reboot command on the host itself.

## Changes Made

### 1. scripts/liveu-admin-action
**Changed:**
```bash
reboot)
  exec sudo -n /sbin/reboot
  ;;
```

**To:**
```bash
reboot)
  # Use nsenter to reboot the host from the container
  # PID 1 is always init/systemd on the host
  exec sudo -n nsenter -t 1 -p -m -n -- /sbin/reboot
  ;;
```

**Explanation:**
- `nsenter -t 1 -p -m -n` enters the namespace of PID 1 (host's init/systemd)
- `-p` = PID namespace
- `-m` = Mount namespace  
- `-n` = Network namespace
- Then executes `/sbin/reboot` in the host's context

### 2. Dockerfile
**Added `util-linux` package** (provides `nsenter` command):
```dockerfile
apt-get install -y --no-install-recommends \
    ...
    util-linux \
    ...
```

**Updated sudoers** to allow `nsenter`:
```dockerfile
echo "app ALL=(root) NOPASSWD: ..., /usr/bin/nsenter" > /etc/sudoers.d/liveu-monitor
```

### 3. docker-compose.yml
**Added `pid: host`** to share the host's PID namespace:
```yaml
services:
  liveu-server-monitor:
    pid: host
```

This allows the container to see all host processes, including PID 1 (init/systemd).

## Deployment Instructions

### Option 1: Rebuild and Restart (Recommended)
```bash
# Navigate to project directory
cd /path/to/svr-mon

# Stop current container
docker compose down

# Rebuild and start with new changes
docker compose up -d --build

# Verify container is running
docker compose ps
```

### Option 2: Using Install Script
If you want to do a clean install:
```bash
sudo bash scripts/install-liveu-server-monitor.sh
```

## Testing

After deployment, you can test the reboot functionality:

1. **Via UI:**
   - Navigate to https://<SERVER_IP>:8443
   - Log in as admin
   - Go to the "Admin Actions" tab
   - In the "Reboot Server" section, enter your password and type "REBOOT" in the confirmation field
   - Click the "Reboot Server" button
   - The button will show a spinner and change text to "Rebooting..." then "Waiting for server to reboot..."
   - The page will automatically poll every 5 seconds until the server comes back online
   - Once the server is back, you'll see a success message and the dashboard will refresh

2. **Via API (if available):**
   ```bash
   curl -k -X POST https://localhost:8443/api/admin/reboot \
     -H "Cookie: liveu_session=<your_session_token>" \
     -H "Content-Type: application/json" \
     -d '{"password":"your_password","confirmation":"REBOOT"}'
   ```

## Verification

After the host reboots:
1. The UI will automatically detect when the server is back online (polling every 5 seconds)
2. Once detected, you'll see "Server rebooted successfully and is back online." message
3. The dashboard data will automatically refresh
4. If the server doesn't come back within 5 minutes, a timeout error will be displayed

## How It Works

### Backend (Host Reboot)
1. User clicks "Reboot" in the UI
2. Backend calls `reboot_server()` → `_run_action('reboot')`
3. `_run_action` executes `/usr/local/bin/liveu-admin-action reboot`
4. Script runs: `sudo nsenter -t 1 -p -m -n -- /sbin/reboot`
5. `nsenter` enters host's PID 1 namespace (requires privileged container)
6. `/sbin/reboot` executes in host context
7. Host reboots
8. Container stops (as part of host shutdown)
9. After host boots, Docker daemon starts
10. Container auto-restarts (due to `restart: unless-stopped`)

### Frontend (Polling & UI)
1. User clicks "Reboot Server" button
2. Button shows spinner and changes to "Rebooting..."
3. After API call succeeds, button changes to "Waiting for server to reboot..."
4. Frontend polls `/api/status/current` every 5 seconds
5. When server responds, polling stops and success message is shown
6. Dashboard data is refreshed automatically
7. If no response after 5 minutes (60 polls), timeout error is shown

## How It Works

1. User clicks "Reboot" in the UI
2. Backend calls `reboot_server()` → `_run_action('reboot')`
3. `_run_action` executes `/usr/local/bin/liveu-admin-action reboot`
4. Script runs: `sudo nsenter -t 1 -p -m -n -- /sbin/reboot`
5. `nsenter` enters host's PID 1 namespace
6. `/sbin/reboot` executes in host context
7. Host reboots
8. Container stops (as part of host shutdown)
9. After host boots, Docker daemon starts
10. Container auto-restarts (due to `restart: unless-stopped`)

## Important Notes

- **Security:** The container now has access to the host's PID namespace, which is a privilege escalation. However, this is necessary for the reboot functionality and is consistent with the existing architecture where the container already has significant host access (read-only root filesystem, systemd sockets, etc.)

- **Safety:** The reboot command will reboot the entire host, not just the container. Ensure this is the intended behavior.

- **Alternatives Considered:**
  - Using `systemctl reboot` - Would still reboot the container, not host
  - Using SSH to localhost - Requires SSH setup and keys
  - Using a host-level script - More complex, requires additional volume mounts
  - Using sysrq trigger - Less clean, requires kernel configuration

The `nsenter` approach is the cleanest and most straightforward solution.