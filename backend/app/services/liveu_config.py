import ast
import re
import subprocess
from pathlib import Path
from typing import Any

from ..config import get_settings

MAX_READ_BYTES = 2 * 1024 * 1024


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _read_via_helper(path: Path) -> str | None:
    settings = get_settings()
    try:
        result = subprocess.run(
            ['sudo', '-n', settings.liveu_config_reader, str(path)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _read_text_with_fallback(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return _read_via_helper(path)


def _safe_read(path: Path, max_bytes: int = MAX_READ_BYTES) -> dict[str, Any]:
    if not _safe_exists(path) or not _safe_is_file(path):
        return {'path': str(path), 'exists': False, 'content': None, 'truncated': False}

    content = _read_text_with_fallback(path)
    if content is None:
        return {'path': str(path), 'exists': True, 'content': None, 'truncated': False, 'readable': False}

    truncated = len(content.encode('utf-8', errors='ignore')) > max_bytes
    if truncated:
        content = content.encode('utf-8', errors='ignore')[:max_bytes].decode('utf-8', errors='replace')
        content += '\n\n# [truncated due to max file size limit]'
    size = len(content.encode('utf-8', errors='ignore'))

    return {
        'path': str(path),
        'exists': True,
        'content': content,
        'truncated': truncated,
        'size_bytes': size,
    }


def _parse_python_constant(text: str, name: str) -> Any | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None

    if tree is not None:
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        try:
                            return ast.literal_eval(node.value)
                        except Exception:
                            pass
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        pass

    pattern = re.compile(rf'^{re.escape(name)}\s*=\s*([\"\']?)([^\n#\"\']+)\1', re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    raw = match.group(2).strip()
    if raw.isdigit():
        return int(raw)
    return raw


def _extract_int_constant(path: Path, name: str) -> int | None:
    if not _safe_exists(path):
        return None
    text = _read_text_with_fallback(path)
    if text is None:
        return None
    value = _parse_python_constant(text, name)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _extract_port(path: Path) -> int | None:
    return _extract_int_constant(path, 'PORT')


def _read_host_udp_listening_ports() -> set[int]:
    settings = get_settings()
    ports: set[int] = set()
    for path in (settings.host_proc_dir / '1' / 'net' / 'udp', settings.host_proc_dir / '1' / 'net' / 'udp6'):
        try:
            lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()
        except OSError:
            continue
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            local_addr, state = parts[1], parts[3].upper()
            # UDP sockets shown as UNCONN in netstat/ss typically map to 07 in /proc.
            if state != '07':
                continue
            if ':' not in local_addr:
                continue
            port_hex = local_addr.rsplit(':', 1)[1]
            try:
                ports.add(int(port_hex, 16))
            except ValueError:
                continue
    return ports


def _read_host_udp_allowed_ports() -> set[int]:
    rules_path = Path('/host-root/etc/iptables/rules.v4')
    text = _read_text_with_fallback(rules_path)
    if not text:
        return set()

    allowed: set[int] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('-A INPUT'):
            continue
        if ' -p udp ' not in f' {stripped} ':
            continue
        if ' -j ACCEPT' not in stripped:
            continue
        match = re.search(r'--dport (\d+)\b', stripped)
        if not match:
            continue
        try:
            allowed.add(int(match.group(1)))
        except ValueError:
            continue
    return allowed


def get_liveu_identity() -> dict:
    settings = get_settings()
    base_id_file = settings.host_liveu_dir / 'baseuniqueid'
    license_file = settings.host_liveu_dir / 'server-license.txt'

    base_unique_id = None
    if _safe_exists(base_id_file):
        text = _read_text_with_fallback(base_id_file)
        if text is not None:
            base_unique_id = text.strip() or None

    server_license = None
    if _safe_exists(license_file):
        text = _read_text_with_fallback(license_file)
        if text is not None:
            server_license = text.strip() or None

    server_type = 'Unknown'
    if base_unique_id:
        if base_unique_id.startswith('Boss1100'):
            server_type = 'MMH/Transceiver'
        elif base_unique_id.startswith('BossIngest'):
            server_type = 'Ingest'

    return {
        'base_unique_id': base_unique_id,
        'server_license': server_license,
        'server_type': server_type,
    }


def _get_mmh_config(root: Path) -> dict:
    instances_py = root / 'instances.py'
    mmh_instances = _extract_int_constant(instances_py, 'MMH_INSTANCES') or 0
    listening_udp_ports = _read_host_udp_listening_ports()
    allowed_udp_ports = _read_host_udp_allowed_ports()

    collectors: list[dict[str, Any]] = []
    for idx in range(1, mmh_instances + 1):
        instance_dir = root / f'instance{idx}'
        if not _safe_exists(instance_dir) or not _safe_is_dir(instance_dir):
            continue
        collector_path = instance_dir / 'collector.py'
        port = _extract_port(collector_path)
        collectors.append(
            {
                'instance': idx,
                'collector_path': str(collector_path),
                'port': port,
                'exists': _safe_exists(collector_path),
                'status': (
                    'listening'
                    if isinstance(port, int) and (port in listening_udp_ports or port in allowed_udp_ports)
                    else 'closed'
                ),
            }
        )

    overseer = root / 'overseer.py'
    external_preview_tcp_port = _extract_int_constant(overseer, 'EXTERNAL_PREVIEW_TCP_PORT')
    local_hub_port = _extract_int_constant(overseer, 'LOCAL_HUB_PORT')

    return {
        'mmh_instances': mmh_instances,
        'collectors': collectors,
        'external_preview_tcp_port': external_preview_tcp_port,
        'local_hub_port': local_hub_port,
    }


def _extract_port_candidates(text: str) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = None

    if tree is not None:
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        key = target.id
                        if 'PORT' in key:
                            try:
                                value = ast.literal_eval(node.value)
                            except Exception:
                                continue
                            if isinstance(value, int):
                                ports.append({'name': key, 'value': value})
                            elif isinstance(value, str) and value.isdigit():
                                ports.append({'name': key, 'value': int(value)})
    return ports


def _get_ingest_config(root: Path) -> dict:
    files = [
        root / 'ingest.py',
        root / 'ingest.hotfolderexposure.py',
        root / 'ingest.transcoder.py',
    ]

    read_files = [_safe_read(path) for path in files]
    port_candidates: list[dict[str, Any]] = []
    for item in read_files:
        content = item.get('content')
        if content:
            for port in _extract_port_candidates(content):
                port_candidates.append({'file': item['path'], **port})

    return {'files': read_files, 'port_candidates': port_candidates}


def get_liveu_config() -> dict:
    settings = get_settings()
    identity = get_liveu_identity()
    server_type = identity['server_type']

    result: dict[str, Any] = {'identity': identity, 'server_type': server_type}

    if server_type == 'MMH/Transceiver':
        result['mmh'] = _get_mmh_config(settings.host_liveu_dir)
    elif server_type == 'Ingest':
        result['ingest'] = _get_ingest_config(settings.host_liveu_dir)
    else:
        result['message'] = 'LiveU server type could not be determined from base unique ID.'

    return result
