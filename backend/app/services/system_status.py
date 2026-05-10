import ipaddress
import platform
import re
import shutil
import socket
import subprocess
import time
import zipfile
from datetime import datetime
from glob import glob
from pathlib import Path

import httpx
import psutil

from ..config import get_settings

_SERVER_VERSION_TTL_SECONDS = 60
_server_version_cache: tuple[float, str | None] | None = None
_SERVER_VERSION_PATTERN = re.compile(r'\d+\.\d+\.\d+\.[A-Za-z]\d+\.[A-Za-z0-9]+')
_SERVICE_STATUS_TTL_SECONDS = 1
_service_status_cache: tuple[float, str] | None = None
_SERVICE_STATUS_TIMEOUT_SECONDS = 2
_IPV4_PATTERN = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_public_ip_cache: tuple[float, str | None] | None = None
_PUBLIC_IP_CACHE_TTL_SECONDS = 60
_LIVEU_PROCESS_MARKERS = (
    '/opt/liveu/overlord.egg',
    '/opt/liveu/gru.egg',
    '/opt/liveu/monitor.egg',
    '/opt/liveu/signalbus.egg',
)


def _parse_os_release(path: Path) -> str:
    if not path.exists():
        return 'Unknown'
    content = path.read_text(encoding='utf-8', errors='ignore')
    match = re.search(r'^PRETTY_NAME=(.*)$', content, flags=re.MULTILINE)
    if not match:
        return 'Unknown'
    raw = match.group(1).strip().strip('"').strip("'")
    return raw or 'Unknown'


def _safe_temperature_from_sensors() -> float | None:
    try:
        result = subprocess.run(
            ['sensors'],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return None
        temps: list[float] = []
        preferred_cpu_temps: list[float] = []
        for line in result.stdout.splitlines():
            # Ignore threshold values like "(high=... , crit=...)" and only parse
            # the immediate current value at the start of the sensor reading.
            head = line.split('(', 1)[0]
            match = re.search(r'[:]\s*([+-]?\d+(?:\.\d+)?)\s*°C', head)
            if not match:
                continue
            value = float(match.group(1))
            if -50.0 <= value <= 200.0:
                temps.append(value)
                sensor_name = head.strip().lower()
                if (
                    sensor_name.startswith('package id')
                    or sensor_name.startswith('tdie')
                    or sensor_name.startswith('tctl')
                    or sensor_name.startswith('cpu temp')
                ):
                    preferred_cpu_temps.append(value)
        if preferred_cpu_temps:
            return max(preferred_cpu_temps)
        if not temps:
            return None
        return max(temps)
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _fallback_temperature_psutil() -> float | None:
    try:
        temperatures = psutil.sensors_temperatures(fahrenheit=False)
    except Exception:
        return None
    values: list[float] = []
    for entries in temperatures.values():
        for entry in entries:
            current = getattr(entry, 'current', None)
            if current is None:
                continue
            if -50.0 <= float(current) <= 200.0:
                values.append(float(current))
    return max(values) if values else None


def get_temperature_c() -> float | None:
    return _safe_temperature_from_sensors() or _fallback_temperature_psutil()


def get_disk_usage() -> list[dict]:
    disks: list[dict] = []
    seen: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)
        if part.fstype in {'squashfs', 'tmpfs', 'devtmpfs'}:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except PermissionError:
            continue
        disks.append(
            {
                'mountpoint': part.mountpoint,
                'used_percent': round(usage.percent, 2),
                'total_bytes': int(usage.total),
                'used_bytes': int(usage.used),
            }
        )
    disks.sort(key=lambda item: item['mountpoint'])
    return disks


def get_disk_usage_df() -> list[dict]:
    settings = get_settings()
    host_root = settings.host_root_dir

    host_paths = [
        '/run',
        '/',
        '/dev/shm',
        '/run/lock',
        '/boot',
        '/logs',
        '/boot/efi',
        '/storage',
        '/media/sdb1',
        '/run/user/1000',
    ]

    if host_root.exists():
        target_args = [f'{host_root}{path}' for path in host_paths]
        rows = _run_df_h(target_args)
        if rows:
            normalized_rows: list[dict] = []
            host_root_prefix = str(host_root)
            for row in rows:
                mounted = row['mounted_on']
                if mounted.startswith(host_root_prefix):
                    mapped = mounted[len(host_root_prefix):] or '/'
                    row['mounted_on'] = mapped
                normalized_rows.append(row)
            return normalized_rows

    return _run_df_h([])


def _run_df_h(targets: list[str]) -> list[dict]:
    try:
        command = ['df', '-hP']
        if targets:
            command.extend(targets)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return []
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) < 2:
            return []
        rows: list[dict] = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 6:
                continue
            rows.append(
                {
                    'filesystem': parts[0],
                    'size': parts[1],
                    'used': parts[2],
                    'avail': parts[3],
                    'use_percent': parts[4],
                    'mounted_on': parts[5],
                }
            )
        return rows
    except (subprocess.SubprocessError, OSError):
        return []


def get_cpu_memory_temperature() -> dict:
    return {
        'timestamp': datetime.utcnow(),
        'cpu_percent': round(psutil.cpu_percent(interval=None), 2),
        'memory_percent': round(psutil.virtual_memory().percent, 2),
        'temperature_c': get_temperature_c(),
    }


def get_os_kernel() -> tuple[str, str]:
    settings = get_settings()
    os_version = _parse_os_release(settings.host_os_release)
    if os_version == 'Unknown':
        os_version = _parse_os_release(Path('/etc/os-release'))
    return os_version, platform.release()


def _parse_server_version_output(raw_output: str) -> str | None:
    for line in raw_output.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        parts = cleaned.split()
        if len(parts) < 2:
            continue
        candidate = parts[-1]
        if _SERVER_VERSION_PATTERN.fullmatch(candidate):
            return candidate
    return None


def _parse_server_version_from_pyc_bytes(data: bytes) -> str | None:
    # `common/version.pyc` in LiveU eggs stores split literals like
    # "12.1.1" and "C5312.G588bee03a"; reconstruct if needed.
    ascii_chunks = re.findall(rb'[ -~]{4,}', data)
    core: str | None = None
    suffix: str | None = None
    for chunk in ascii_chunks:
        text = chunk.decode('ascii', errors='ignore')
        if core is None:
            core_match = re.search(r'\d+\.\d+\.\d+', text)
            if core_match:
                core = core_match.group(0)
        if suffix is None:
            suffix_match = re.search(r'C\d+\.G[0-9A-Za-z]+', text)
            if suffix_match:
                suffix = suffix_match.group(0)
        if core and suffix:
            candidate = f'{core}.{suffix}'
            if _SERVER_VERSION_PATTERN.fullmatch(candidate):
                return candidate
    return None


def _get_server_version_from_eggs() -> str | None:
    for egg_path in sorted(glob('/opt/liveu/*.egg')):
        try:
            with zipfile.ZipFile(egg_path) as egg:
                if 'common/version.pyc' not in egg.namelist():
                    continue
                data = egg.read('common/version.pyc')
            version = _parse_server_version_from_pyc_bytes(data)
            if version:
                return version
        except (OSError, zipfile.BadZipFile, KeyError):
            continue
    return None


def get_server_version() -> str | None:
    global _server_version_cache

    now = time.monotonic()
    if _server_version_cache and now - _server_version_cache[0] < _SERVER_VERSION_TTL_SECONDS:
        return _server_version_cache[1]

    try:
        result = subprocess.run(
            ['/opt/liveu/debug/version.sh'],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode != 0:
            version = _get_server_version_from_eggs()
            _server_version_cache = (now, version)
            return version
        version = _parse_server_version_output(result.stdout)
        if version is None:
            version = _get_server_version_from_eggs()
        _server_version_cache = (now, version)
        return version
    except (subprocess.SubprocessError, OSError):
        version = _get_server_version_from_eggs()
        _server_version_cache = (now, version)
        return version


def get_liveu_service_status() -> str:
    global _service_status_cache

    now = time.monotonic()
    if _service_status_cache and now - _service_status_cache[0] < _SERVICE_STATUS_TTL_SECONDS:
        return _service_status_cache[1]

    status = _get_liveu_status_from_systemctl()
    if status is None and shutil.which('systemctl') is None:
        status = _get_liveu_status_from_processes()
    if status is None:
        status = 'unknown'
    _service_status_cache = (now, status)
    return status


def _parse_systemctl_active_state(raw: str) -> str | None:
    value = raw.strip().splitlines()
    if not value:
        return None
    state = value[0].strip().lower()
    if state in {'active', 'inactive', 'failed', 'activating', 'deactivating', 'reloading'}:
        return state
    return None


def _get_liveu_status_from_systemctl() -> str | None:
    # Prefer systemd's own unit state to avoid false positives from unrelated
    # processes that happen to contain LiveU command-line markers.
    commands: list[list[str]] = []
    if shutil.which('systemctl'):
        commands.extend(
            [
                ['systemctl', 'is-active', 'liveu'],
                ['systemctl', 'show', '--property', 'ActiveState', '--value', 'liveu'],
            ]
        )

    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=_SERVICE_STATUS_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            continue

        # `systemctl is-active <unit>` reliably maps return codes:
        # 0=active, 3=inactive, 4=not-found/unknown.
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

    return None


def _get_liveu_status_from_processes() -> str:
    settings = get_settings()
    proc_dir = settings.host_proc_dir
    if not proc_dir.exists():
        return 'unknown'

    marker_hits = 0
    try:
        for entry in proc_dir.iterdir():
            if not entry.name.isdigit():
                continue
            cmdline_path = entry / 'cmdline'
            try:
                raw = cmdline_path.read_bytes()
            except (OSError, PermissionError):
                continue
            if not raw:
                continue
            cmdline = raw.replace(b'\x00', b' ').decode('utf-8', errors='ignore').strip()
            if any(marker in cmdline for marker in _LIVEU_PROCESS_MARKERS):
                marker_hits += 1
                if marker_hits >= 1:
                    return 'active'
    except OSError:
        return 'unknown'

    return 'inactive'


def _decode_route_ipv4_le(raw_hex: str) -> str | None:
    value = raw_hex.strip()
    if len(value) != 8:
        return None
    try:
        octets = [str(int(value[i : i + 2], 16)) for i in range(0, 8, 2)]
    except ValueError:
        return None
    return '.'.join(reversed(octets))


def _read_container_default_gateway() -> str | None:
    try:
        lines = Path('/proc/net/route').read_text(encoding='utf-8', errors='ignore').splitlines()
    except OSError:
        return None

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        destination_hex, gateway_hex = parts[1], parts[2]
        if destination_hex != '00000000':
            continue
        return _decode_route_ipv4_le(gateway_hex)
    return None


def _is_tcp_port_open(host: str, port: int, timeout_seconds: float = 0.5) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_seconds)
    try:
        return sock.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def _read_default_interface(route_path: Path) -> str | None:
    try:
        route_lines = route_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    except OSError:
        return None

    for line in route_lines[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        iface, destination_hex = parts[0], parts[1]
        if destination_hex == '00000000' and iface != 'lo':
            return iface
    return None


def _read_host_nic_counters_from_proc(iface: str) -> tuple[int, int] | None:
    settings = get_settings()
    net_dev_path = settings.host_proc_dir / '1' / 'net' / 'dev'
    try:
        lines = net_dev_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    except OSError:
        return None

    prefix = f'{iface}:'
    for raw_line in lines[2:]:
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        payload = line[len(prefix):].strip().split()
        if len(payload) < 16:
            return None
        try:
            rx_bytes = int(payload[0])
            tx_bytes = int(payload[8])
        except ValueError:
            return None
        return rx_bytes, tx_bytes
    return None


def get_relevant_nic_counters() -> dict:
    settings = get_settings()
    route_path = settings.host_proc_dir / '1' / 'net' / 'route'
    default_iface = _read_default_interface(route_path)

    if default_iface:
        counters = _read_host_nic_counters_from_proc(default_iface)
        if counters:
            return {
                'interface': default_iface,
                'rx_bytes_total': counters[0],
                'tx_bytes_total': counters[1],
            }

    pernic = psutil.net_io_counters(pernic=True)
    stats = psutil.net_if_stats()
    for iface, io in pernic.items():
        if iface.startswith('lo'):
            continue
        st = stats.get(iface)
        if st and not st.isup:
            continue
        return {
            'interface': iface,
            'rx_bytes_total': int(io.bytes_recv),
            'tx_bytes_total': int(io.bytes_sent),
        }

    return {'interface': None, 'rx_bytes_total': None, 'tx_bytes_total': None}


def _read_host_internal_ip() -> tuple[str | None, str]:
    settings = get_settings()
    route_path = settings.host_proc_dir / '1' / 'net' / 'route'
    fib_path = settings.host_proc_dir / '1' / 'net' / 'fib_trie'

    default_iface = _read_default_interface(route_path)
    default_network: ipaddress.IPv4Network | None = None
    link_status = 'down'

    try:
        route_lines = route_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    except OSError:
        return None, link_status

    for line in route_lines[1:]:
        parts = line.split()
        if len(parts) < 8:
            continue
        iface, destination_hex, mask_hex = parts[0], parts[1], parts[7]
        if default_iface and iface == default_iface and destination_hex != '00000000':
            destination = _decode_route_ipv4_le(destination_hex)
            mask = _decode_route_ipv4_le(mask_hex)
            if destination and mask:
                try:
                    default_network = ipaddress.IPv4Network(f'{destination}/{mask}', strict=False)
                    break
                except ValueError:
                    continue

    if default_iface:
        operstate_path = settings.host_sys_dir / 'class' / 'net' / default_iface / 'operstate'
        try:
            if operstate_path.read_text(encoding='utf-8', errors='ignore').strip().lower() == 'up':
                link_status = 'up'
        except OSError:
            pass

    try:
        fib_lines = fib_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    except OSError:
        return None, link_status

    local_ips: list[str] = []
    for idx, line in enumerate(fib_lines):
        if '/32 host LOCAL' not in line:
            continue
        for rev_idx in range(idx - 1, max(-1, idx - 5), -1):
            match = _IPV4_PATTERN.search(fib_lines[rev_idx])
            if not match:
                continue
            ip = match.group(0)
            if ip.startswith('127.'):
                break
            if ip not in local_ips:
                local_ips.append(ip)
            break

    if default_network:
        for ip in local_ips:
            try:
                if ipaddress.IPv4Address(ip) in default_network:
                    return ip, link_status
            except ValueError:
                continue

    for ip in local_ips:
        if not ip.startswith('127.'):
            return ip, link_status

    return None, link_status


def _read_host_public_ip_cached() -> str | None:
    settings = get_settings()
    path = settings.host_public_ip_cache_file
    try:
        value = path.read_text(encoding='utf-8', errors='ignore').strip()
    except OSError:
        return None
    if _IPV4_PATTERN.fullmatch(value):
        return value
    return None


def _fetch_public_ip_http() -> str | None:
    for url in ['https://api.ipify.org', 'https://checkip.amazonaws.com', 'https://ifconfig.me/ip']:
        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(url)
            if resp.status_code != 200:
                continue
            value = resp.text.strip()
            if _IPV4_PATTERN.fullmatch(value):
                return value
        except Exception:
            continue
    return None


def _get_public_ip() -> str | None:
    global _public_ip_cache
    settings = get_settings()

    if settings.public_ip_override and _IPV4_PATTERN.fullmatch(settings.public_ip_override.strip()):
        return settings.public_ip_override.strip()

    now = time.monotonic()
    if _public_ip_cache and now - _public_ip_cache[0] < _PUBLIC_IP_CACHE_TTL_SECONDS:
        return _public_ip_cache[1]

    cached = _read_host_public_ip_cached()
    if cached:
        _public_ip_cache = (now, cached)
        return cached

    fetched = _fetch_public_ip_http()
    _public_ip_cache = (now, fetched)
    return fetched


def get_network_info() -> dict:
    internal_ip, link_status = _read_host_internal_ip()

    if not internal_ip:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        for iface, iface_addrs in addrs.items():
            if iface.startswith('lo'):
                continue
            ipv4 = next((a.address for a in iface_addrs if a.family == socket.AF_INET), None)
            st = stats.get(iface)
            if st and st.isup:
                link_status = 'up'
            if ipv4 and not ipv4.startswith('127.'):
                internal_ip = ipv4
                if st and st.isup:
                    link_status = 'up'
                    break

    public_ip = _get_public_ip()

    ssh_status = 'closed'
    ssh_probe_targets: list[str] = []
    if internal_ip and not internal_ip.startswith('127.'):
        ssh_probe_targets.append(internal_ip)
    gateway_ip = _read_container_default_gateway()
    if gateway_ip and gateway_ip not in ssh_probe_targets and not gateway_ip.startswith('127.'):
        ssh_probe_targets.append(gateway_ip)

    for target in ssh_probe_targets:
        if _is_tcp_port_open(target, 22):
            ssh_status = 'open'
            break

    return {
        'internal_ip': internal_ip,
        'public_ip': public_ip,
        'link_status': link_status,
        'ssh_port_22': ssh_status,
    }
