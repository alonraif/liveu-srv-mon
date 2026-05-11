import ast
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from ..config import get_settings

logger = logging.getLogger('liveu-monitor')

ROLE_MMH = 'MMH/Transceiver'
ROLE_INGEST = 'Ingest'
ROLE_VR = 'Video Return'
ROLE_UNKNOWN = 'Unknown'


def _run_liveu_config_show() -> str:
    def _extract_text(result: subprocess.CompletedProcess[str]) -> str:
        stdout = result.stdout or ''
        stderr = result.stderr or ''
        merged = f"{stdout}\n{stderr}".strip()
        return merged

    def _looks_like_show_output(text: str) -> bool:
        if not text:
            return False
        markers = ('network:', 'bossID:', 'licenseKey:', 'luc:')
        return any(marker in text for marker in markers)

    settings = get_settings()
    candidates: list[list[str]] = [
        [settings.admin_command_runner, 'liveu-config-show'],
        ['/bin/bash', '-lc', 'liveu-config --show'],
        ['liveu-config', '--show'],
        ['/opt/liveu/liveu-config', '--show'],
        ['/opt/liveu/bin/liveu-config', '--show'],
        ['/usr/local/bin/liveu-config', '--show'],
    ]

    for cmd in candidates:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue

        text = _extract_text(result)
        if _looks_like_show_output(text):
            return text
        logger.warning('liveu-config candidate failed: cmd=%s rc=%s output=%s', cmd, result.returncode, text[:600])

    return ''


def _to_value(raw: str) -> Any:
    value = raw.strip()
    if value in {'None', '--'}:
        return None
    if value.startswith('[') and value.endswith(']'):
        try:
            return ast.literal_eval(value)
        except Exception:
            return value
    if re.fullmatch(r'\d+', value):
        return int(value)
    return value


def _parse_network(lines: list[str], start_idx: int) -> tuple[dict[str, dict[str, Any]], int]:
    network: dict[str, dict[str, Any]] = {}
    idx = start_idx + 1
    current_iface: str | None = None

    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            break
        if not line.startswith(' '):
            break

        iface_match = re.match(r'^\s+([\w.\-]+):\s*$', line)
        if iface_match:
            current_iface = iface_match.group(1)
            network[current_iface] = {}
            idx += 1
            continue

        kv_match = re.match(r'^\s+([^:]+):\s*(.*)$', line)
        if kv_match and current_iface:
            key = kv_match.group(1).strip()
            val = kv_match.group(2).strip()
            network[current_iface][key] = _to_value(val)

        idx += 1

    return network, idx


def _parse_indented_section(lines: list[str], start_idx: int) -> tuple[dict[str, Any], int]:
    data: dict[str, Any] = {}
    idx = start_idx + 1
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            break
        if not line.startswith(' '):
            break
        m = re.match(r'^\s+([^:]+):\s*(.*)$', line)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            data[key] = _to_value(value)
        idx += 1
    return data, idx


def _detect_role(boss_id: str | None, sections: dict[str, dict[str, Any]]) -> str:
    # Video Return is uniquely identified by this section in `liveu-config --show`.
    # Prioritize it over Boss1100_ prefix, which may also appear on VR servers.
    if 'videoreturn port configuration' in sections:
        return ROLE_VR
    if isinstance(boss_id, str):
        if boss_id.startswith('Boss1100_'):
            return ROLE_MMH
        if boss_id.startswith('BossIngest_'):
            return ROLE_INGEST
    return ROLE_UNKNOWN


def _parse_show_output(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    network: dict[str, dict[str, Any]] = {}
    top_level: dict[str, Any] = {}
    sections: dict[str, dict[str, Any]] = {}

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        if not stripped:
            idx += 1
            continue

        if stripped == 'network:':
            network, idx = _parse_network(lines, idx)
            continue

        if stripped.endswith(':') and not line.startswith(' '):
            section_name = stripped[:-1]
            section_data, idx = _parse_indented_section(lines, idx)
            sections[section_name] = section_data
            continue

        if ':' in stripped and not line.startswith(' '):
            k, v = stripped.split(':', 1)
            top_level[k.strip()] = _to_value(v.strip())

        idx += 1

    boss_id = top_level.get('bossID') if isinstance(top_level.get('bossID'), str) else None
    license_key = top_level.get('licenseKey') if isinstance(top_level.get('licenseKey'), str) else None
    role = _detect_role(boss_id, sections)

    role_config: dict[str, Any] = {}
    if role == ROLE_MMH:
        role_config = sections.get('mmh channels configuration', {})
    elif role == ROLE_INGEST:
        role_config = sections.get('ingest port configuration', {})
    elif role == ROLE_VR:
        role_config = sections.get('videoreturn port configuration', {})

    return {
        'identity': {
            'base_unique_id': boss_id,
            'server_license': license_key,
            'server_type': role,
        },
        'server_type': role,
        'network': network,
        'core': {
            'luc': top_level.get('luc'),
            'hubs': top_level.get('hubs'),
            'externalIPs': top_level.get('externalIPs'),
        },
        'sections': sections,
        'role_config': role_config,
    }


def _normalize_show_result(parsed: dict[str, Any]) -> dict[str, Any]:
    identity = parsed.get('identity') or {}
    return {
        'identity': {
            'base_unique_id': identity.get('base_unique_id'),
            'server_license': identity.get('server_license'),
            'server_type': identity.get('server_type') or ROLE_UNKNOWN,
        },
        'server_type': parsed.get('server_type') or ROLE_UNKNOWN,
        'network': parsed.get('network') or {},
        'core': parsed.get('core') or {'luc': None, 'hubs': None, 'externalIPs': None},
        'sections': parsed.get('sections') or {},
        'role_config': parsed.get('role_config') or {},
    }


def _parse_python_constant(path: Path, name: str) -> Any:
    if not path.exists() or not path.is_file():
        return None
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return None
    pat = re.compile(rf'^\s*{re.escape(name)}\s*=\s*(.+?)\s*$', flags=re.MULTILINE)
    match = pat.search(content)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        return ast.literal_eval(raw)
    except Exception:
        return raw.strip('"').strip("'")


def _to_int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_mmh_view(data: dict[str, Any]) -> dict[str, Any]:
    host_liveu = Path('/host/etc/liveu')
    role_config = data.get('role_config') or {}

    mmh_instances = _to_int_or_none(role_config.get('MMH_INSTANCES'))
    if mmh_instances is None:
        mmh_instances = _to_int_or_none(role_config.get('number of channels'))

    external_preview = _to_int_or_none(role_config.get('EXTERNAL_PREVIEW_TCP_PORT'))
    if external_preview is None:
        external_preview = _to_int_or_none(role_config.get('external File Server Tcp Port'))

    local_hub = _to_int_or_none(role_config.get('LOCAL_HUB_PORT'))
    if local_hub is None:
        local_hub = _to_int_or_none(role_config.get('external MMH Unit Control Tcp Port'))

    if mmh_instances is None:
        mmh_instances = _to_int_or_none(_parse_python_constant(host_liveu / 'instances.py', 'MMH_INSTANCES'))
    if external_preview is None:
        external_preview = _to_int_or_none(_parse_python_constant(host_liveu / 'overseer.py', 'EXTERNAL_PREVIEW_TCP_PORT'))
    if local_hub is None:
        local_hub = _to_int_or_none(_parse_python_constant(host_liveu / 'overseer.py', 'LOCAL_HUB_PORT'))

    collectors: list[dict[str, Any]] = []
    for collector_path in sorted(host_liveu.glob('instance*/collector.py')):
        instance_name = collector_path.parent.name
        m = re.fullmatch(r'instance(\d+)', instance_name)
        if not m:
            continue
        instance = int(m.group(1))
        port = _to_int_or_none(_parse_python_constant(collector_path, 'PORT'))
        collectors.append(
            {
                'instance': instance,
                'port': port,
                'status': 'configured' if port is not None else 'unknown',
            }
        )

    # Newer liveu-config --show output often exposes UDP collector ports directly
    # as a list under "udp ports". Use it when file constants are absent.
    udp_ports = role_config.get('udp ports')
    if isinstance(udp_ports, list):
        for idx, raw_port in enumerate(udp_ports, start=1):
            parsed_port = _to_int_or_none(raw_port)
            if parsed_port is None:
                continue
            existing = next((c for c in collectors if c.get('instance') == idx), None)
            if existing:
                if existing.get('port') is None:
                    existing['port'] = parsed_port
                    existing['status'] = 'configured'
            else:
                collectors.append({'instance': idx, 'port': parsed_port, 'status': 'configured'})

    collectors.sort(key=lambda item: int(item.get('instance') or 0))

    if mmh_instances is None and collectors:
        mmh_instances = len(collectors)

    return {
        'mmh_instances': mmh_instances,
        'external_preview_tcp_port': external_preview,
        'local_hub_port': local_hub,
        'collectors': collectors,
    }


def _read_text_if_exists(path: str) -> str | None:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    try:
        value = p.read_text(encoding='utf-8', errors='ignore').strip()
    except OSError:
        return None
    return value or None


def _fallback_from_host_files() -> dict[str, Any]:
    base_unique_id = _read_text_if_exists('/host/etc/liveu/baseuniqueid')
    server_license = _read_text_if_exists('/host/etc/liveu/server-license.txt')
    role = _detect_role(base_unique_id, {})
    return {
        'identity': {
            'base_unique_id': base_unique_id,
            'server_license': server_license,
            'server_type': role,
        },
        'server_type': role,
        'network': {},
        'core': {'luc': None, 'hubs': None, 'externalIPs': None},
        'sections': {},
        'role_config': {},
    }


def get_liveu_config() -> dict[str, Any]:
    output = _run_liveu_config_show()
    if output.strip():
        parsed = _normalize_show_result(_parse_show_output(output))
        if parsed.get('identity', {}).get('base_unique_id'):
            if parsed.get('server_type') == ROLE_MMH:
                parsed['mmh'] = _extract_mmh_view(parsed)
            return parsed
        logger.warning('liveu-config output parsed but missing base_unique_id; falling back to host files')

    fallback = _fallback_from_host_files()
    if fallback.get('identity', {}).get('base_unique_id'):
        if fallback.get('server_type') == ROLE_MMH:
            fallback['mmh'] = _extract_mmh_view(fallback)
        logger.info('Using fallback LiveU config from mounted host files')
        return fallback
    raise RuntimeError('LiveU configuration unavailable: liveu-config --show failed and host fallback files are missing')


def get_liveu_identity() -> dict[str, Any]:
    return get_liveu_config()['identity']
