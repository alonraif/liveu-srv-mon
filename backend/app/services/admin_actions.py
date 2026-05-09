import json
import subprocess
import time

from ..config import get_settings


class AdminActionError(Exception):
    pass


def _parse_systemctl_active_state(raw: str) -> str | None:
    lines = raw.strip().splitlines()
    if not lines:
        return None
    state = lines[0].strip().lower()
    if state in {'active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading'}:
        return state
    return None


def get_liveu_service_status_from_host() -> str:
    commands = [
        ['sudo', '-n', '/usr/bin/env', 'SYSTEMCTL_FORCE_BUS=1', '/usr/bin/systemctl', 'is-active', 'liveu'],
        ['sudo', '-n', '/usr/bin/systemctl', 'is-active', 'liveu'],
        ['systemctl', 'is-active', 'liveu'],
        ['systemctl', 'show', '--property', 'ActiveState', '--value', 'liveu'],
    ]
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            continue

        if result.returncode == 0:
            return 'active'
        if result.returncode == 3:
            return 'inactive'

        parsed = _parse_systemctl_active_state(result.stdout)
        if parsed:
            return parsed
        parsed = _parse_systemctl_active_state(result.stderr)
        if parsed:
            return parsed

    return 'unknown'


def _wait_for_liveu_status(max_wait_seconds: int = 20) -> str:
    deadline = time.monotonic() + max_wait_seconds
    last = 'unknown'
    while time.monotonic() < deadline:
        last = get_liveu_service_status_from_host()
        if last in {'active', 'inactive', 'failed', 'unknown'}:
            return last
        time.sleep(1)
    return last


def _run_action(action: str, timeout_seconds: int = 20) -> str:
    settings = get_settings()
    if action not in {'restart-liveu', 'reboot'}:
        raise AdminActionError('Unsupported action')

    try:
        result = subprocess.run(
            [settings.admin_command_runner, action],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdminActionError(f'Action runner timed out after {timeout_seconds} seconds') from exc
    except OSError as exc:
        raise AdminActionError(f'Action runner missing: {exc}') from exc
    except subprocess.SubprocessError as exc:
        raise AdminActionError(f'Action runner failed: {exc}') from exc

    output = (result.stdout or '') + (result.stderr or '')
    output = output.strip()
    if result.returncode != 0:
        raise AdminActionError(output or f'Command failed with exit code {result.returncode}')
    return output or 'OK'


def restart_liveu_service() -> str:
    try:
        output = _run_action('restart-liveu', timeout_seconds=60)
    except AdminActionError as exc:
        message = str(exc).lower()
        if 'timed out' not in message:
            raise
        status = _wait_for_liveu_status(max_wait_seconds=20)
        if status == 'active':
            return f'Restart timed out, but host reports liveu status: {status}'
        raise AdminActionError(f'Restart timed out and host reports liveu status: {status}') from exc

    status = _wait_for_liveu_status(max_wait_seconds=20)
    if output == 'OK':
        return f'Host reports liveu status: {status}'
    return f'{output}; host reports liveu status: {status}'


def reboot_server() -> str:
    return _run_action('reboot')


def run_speedtest() -> dict:
    try:
        result = subprocess.run(
            ['speedtest-cli', '--json'],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except OSError as exc:
        raise AdminActionError(f'Speedtest command failed to start: {exc}') from exc
    except subprocess.SubprocessError as exc:
        raise AdminActionError(f'Speedtest command failed: {exc}') from exc

    output = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    if result.returncode != 0:
        raise AdminActionError(stderr or output or f'Speedtest failed with exit code {result.returncode}')
    if not output:
        raise AdminActionError('Speedtest returned empty output')

    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise AdminActionError(f'Speedtest returned invalid JSON: {exc}') from exc

    server = payload.get('server') or {}
    client = payload.get('client') or {}

    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    download_mbps = round(_to_float(payload.get('download')) / 1_000_000, 2)
    upload_mbps = round(_to_float(payload.get('upload')) / 1_000_000, 2)
    ping_ms = round(_to_float(payload.get('ping')), 2)

    return {
        'timestamp': str(payload.get('timestamp') or ''),
        'download_mbps': download_mbps,
        'upload_mbps': upload_mbps,
        'ping_ms': ping_ms,
        'server_name': str(server.get('name') or 'Unknown'),
        'server_sponsor': str(server.get('sponsor') or 'Unknown'),
        'server_country': str(server.get('country') or 'Unknown'),
        'server_host': str(server.get('host') or 'Unknown'),
        'public_ip': str(client.get('ip') or 'Unknown'),
    }
