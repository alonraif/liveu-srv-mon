import json
import ipaddress
import re
import subprocess
import time
from pathlib import Path

from ..config import get_settings


class AdminActionError(Exception):
    pass


_IPV4_PATTERN = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')


def _extract_ipv4_candidates(raw: str) -> list[str]:
    values: list[str] = []
    for match in _IPV4_PATTERN.finditer(raw):
        candidate = match.group(0)
        try:
            normalized = str(ipaddress.IPv4Address(candidate))
        except ValueError:
            continue
        if normalized not in values:
            values.append(normalized)
    return values


def _get_host_local_ipv4_options() -> list[dict]:
    try:
        raw = _run_action('list-local-ips', timeout_seconds=10)
    except AdminActionError:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    options: list[dict] = []
    seen_ips: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        iface = str(row.get('interface') or '').strip()
        ip_raw = str(row.get('ip') or '').strip()
        label = str(row.get('label') or '').strip()
        if not iface or not ip_raw:
            continue
        try:
            ip_value = str(ipaddress.IPv4Address(ip_raw))
        except ValueError:
            continue
        if ip_value in seen_ips:
            continue
        seen_ips.add(ip_value)
        options.append(
            {
                'interface': iface,
                'ip': ip_value,
                'label': label or f'{iface} ({ip_value})',
            }
        )
    return options


def _parse_configured_advertised_ip(path: Path) -> str | None:
    try:
        raw = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return None
    candidates = _extract_ipv4_candidates(raw)
    return candidates[0] if candidates else None


def get_advertised_ip_status() -> dict:
    settings = get_settings()
    path = settings.host_liveu_dir / 'whatismyip.py'
    local_ip_options = _get_host_local_ipv4_options()
    configured_ip = _parse_configured_advertised_ip(path) if path.exists() else None
    selected_mode = 'public'
    selected_ip: str | None = None
    if configured_ip:
        local_ips = {entry.get('ip') for entry in local_ip_options if isinstance(entry, dict)}
        selected_mode = 'local' if configured_ip in local_ips else 'custom'
        selected_ip = configured_ip
    return {
        'file_exists': path.exists(),
        'configured_ip': configured_ip,
        'local_ip_options': local_ip_options,
        'selected_mode': selected_mode,
        'selected_ip': selected_ip,
    }


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
        if last in {'active', 'inactive', 'failed'}:
            return last
        time.sleep(1)
    return last


def _run_action(action: str, timeout_seconds: int = 20, args: list[str] | None = None) -> str:
    settings = get_settings()
    if action not in {'restart-liveu', 'reboot', 'liveu-status', 'list-local-ips', 'set-whatismyip', 'clear-whatismyip'}:
        raise AdminActionError('Unsupported action')

    try:
        command = [settings.admin_command_runner, action]
        if args:
            command.extend(args)
        result = subprocess.run(
            command,
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
    output = _run_action('restart-liveu', timeout_seconds=20)
    if output == 'OK':
        return 'Restart command accepted'
    return output


def reboot_server() -> str:
    return _run_action('reboot')


def get_liveu_status_via_runner() -> str:
    try:
        output = _run_action('liveu-status', timeout_seconds=10).strip().lower()
    except AdminActionError:
        return 'unknown'
    if output in {'active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading'}:
        return output
    parsed = _parse_systemctl_active_state(output)
    if parsed:
        return parsed
    return 'unknown'


def update_advertised_ip(mode: str, ip: str | None) -> tuple[str, str]:
    status = get_advertised_ip_status()
    allowed_ips = {entry.get('ip') for entry in status['local_ip_options'] if isinstance(entry, dict)}
    normalized_ip: str | None = None
    if mode == 'local':
        if not ip:
            raise AdminActionError('Local IP is required when mode is local')
        try:
            normalized_ip = str(ipaddress.IPv4Address(ip.strip()))
        except ValueError as exc:
            raise AdminActionError('Invalid local IPv4 address') from exc
        if normalized_ip not in allowed_ips:
            raise AdminActionError('Selected local IP is not allowed on this host')
        _run_action('set-whatismyip', timeout_seconds=15, args=[normalized_ip])
    elif mode == 'custom':
        if not ip:
            raise AdminActionError('Custom IP is required when mode is custom')
        try:
            normalized_ip = str(ipaddress.IPv4Address(ip.strip()))
        except ValueError as exc:
            raise AdminActionError('Invalid custom IPv4 address') from exc
        _run_action('set-whatismyip', timeout_seconds=15, args=[normalized_ip])
    elif mode == 'public':
        _run_action('clear-whatismyip', timeout_seconds=15)
    else:
        raise AdminActionError('Unsupported advertised IP mode')

    restart_output = restart_liveu_service()
    if mode == 'public':
        return 'public', restart_output
    return normalized_ip or '', restart_output


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
