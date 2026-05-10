import ast
import re
import subprocess
from typing import Any


ROLE_MMH = 'MMH/Transceiver'
ROLE_INGEST = 'Ingest'
ROLE_VR = 'VideoReturn'
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

    candidates: list[list[str]] = [
        ['/bin/bash', '-lc', 'liveu-config --show'],
        ['liveu-config', '--show'],
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
    if isinstance(boss_id, str):
        if boss_id.startswith('Boss1100_'):
            return ROLE_MMH
        if boss_id.startswith('BossIngest_'):
            return ROLE_INGEST
    if 'videoreturn port configuration' in sections:
        return ROLE_VR
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


def get_liveu_config() -> dict[str, Any]:
    output = _run_liveu_config_show()
    if not output.strip():
        raise RuntimeError('liveu-config --show failed on host namespace')
    parsed = _normalize_show_result(_parse_show_output(output))
    if not parsed.get('identity', {}).get('base_unique_id'):
        raise RuntimeError('liveu-config --show did not return a valid base unique id')
    return parsed


def get_liveu_identity() -> dict[str, Any]:
    return get_liveu_config()['identity']
