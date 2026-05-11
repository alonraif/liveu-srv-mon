#!/usr/bin/env python3
import json
import ipaddress
import logging
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("liveu-host-helperd")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

SOCKET_PATH = Path("/run/liveu-helper/liveu-helper.sock")
SOCKET_DIR = SOCKET_PATH.parent
SOCKET_GID = int(os.environ.get("LIVEU_HELPER_SOCKET_GID", "10001"))
ALLOWED_UID = int(os.environ.get("LIVEU_HELPER_ALLOWED_UID", "10001"))
ALLOWED_GID = int(os.environ.get("LIVEU_HELPER_ALLOWED_GID", str(SOCKET_GID)))
SHARED_TOKEN = os.environ.get("LIVEU_HELPER_SHARED_TOKEN", "").strip()
ALLOWED_ACTIONS = {
    "restart-liveu": ["/usr/bin/systemctl", "restart", "--no-block", "liveu"],
    "reboot": ["/sbin/reboot"],
    "liveu-config-show": ["/bin/bash", "-lc", "liveu-config --show"],
    "liveu-status": ["/usr/bin/systemctl", "show", "--property", "ActiveState", "--value", "liveu"],
}

_VIRTUAL_IFACE_PREFIXES = ("lo", "docker", "br-", "veth", "virbr", "tun", "tap")


def _list_local_physical_ips() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["/usr/sbin/ip", "-o", "-4", "addr", "show", "up", "scope", "global"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"failed to list interfaces: {exc}"

    if result.returncode != 0:
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        return False, output or f"ip command failed with exit code {result.returncode}"

    options: list[dict[str, str]] = []
    seen_ips: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        iface = parts[1]
        if "@" in iface:
            iface = iface.split("@", 1)[0]
        if iface.startswith(_VIRTUAL_IFACE_PREFIXES):
            continue
        if not (Path("/sys/class/net") / iface / "device").exists():
            continue
        cidr = parts[3]
        ip = cidr.split("/", 1)[0].strip()
        try:
            ip = str(ipaddress.IPv4Address(ip))
        except ValueError:
            continue
        if ip in seen_ips:
            continue
        seen_ips.add(ip)
        options.append({"interface": iface, "ip": ip, "label": f"{iface} ({ip})"})

    return True, json.dumps(options)


def _set_whatismyip(ip_value: str) -> tuple[bool, str]:
    try:
        ip_normalized = str(ipaddress.IPv4Address(ip_value.strip()))
    except ValueError:
        return False, "invalid ipv4 address"

    target = Path("/etc/liveu/whatismyip.py")
    temp = target.with_suffix(".py.tmp")
    content = f"STATIC_IP_LIST = ['{ip_normalized}']\n"
    try:
        temp.write_text(content, encoding="utf-8")
        os.chmod(temp, 0o644)
        os.replace(temp, target)
    except OSError as exc:
        return False, f"failed to write whatismyip.py: {exc}"
    return True, f"configured advertised IP to {ip_normalized}"


def _clear_whatismyip() -> tuple[bool, str]:
    target = Path("/etc/liveu/whatismyip.py")
    try:
        if target.exists():
            target.unlink()
    except OSError as exc:
        return False, f"failed to remove whatismyip.py: {exc}"
    return True, "advertised IP set to public"


def _handle_action(action: str, payload: dict) -> tuple[bool, str]:
    if action == "list-local-ips":
        return _list_local_physical_ips()
    if action == "set-whatismyip":
        ip_value = str(payload.get("advertised_ip") or "")
        return _set_whatismyip(ip_value)
    if action == "clear-whatismyip":
        return _clear_whatismyip()

    command = ALLOWED_ACTIONS.get(action)
    if not command:
        return False, "unsupported action"

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30 if action in {"restart-liveu", "reboot"} else 15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"command execution error: {exc}"

    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        logger.warning("Action '%s' failed rc=%s output=%s", action, result.returncode, output[:1000])
        return False, output or f"command failed with exit code {result.returncode}"
    logger.info("Action '%s' succeeded", action)
    return True, output or "OK"


def _serve() -> int:
    SOCKET_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SOCKET_DIR, 0o755)
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
        srv.bind(str(SOCKET_PATH))
        os.chown(SOCKET_PATH, 0, SOCKET_GID)
        os.chmod(SOCKET_PATH, 0o660)
        srv.listen(16)
        while True:
            conn, _ = srv.accept()
            with conn:
                # Restrict callers to the container app user by UID.
                raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                _pid, uid, gid = struct.unpack("3i", raw)
                if uid != ALLOWED_UID or gid != ALLOWED_GID:
                    logger.warning("Rejected helper request from uid=%s gid=%s", uid, gid)
                    response = {"ok": False, "error": "forbidden peer credentials"}
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                    continue
                try:
                    raw = conn.recv(4096)
                except OSError:
                    continue
                if not raw:
                    continue
                try:
                    payload = json.loads(raw.decode("utf-8", "replace").strip())
                except json.JSONDecodeError:
                    response = {"ok": False, "error": "invalid json"}
                else:
                    action = str(payload.get("action") or "")
                    if SHARED_TOKEN:
                        token = str(payload.get("token") or "")
                        if token != SHARED_TOKEN:
                            logger.warning("Rejected helper request with invalid shared token")
                            response = {"ok": False, "error": "invalid shared token"}
                            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                            continue
                    ok, output = _handle_action(action, payload)
                    response = {"ok": ok}
                    if ok:
                        response["output"] = output
                    else:
                        response["error"] = output
                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))


def main() -> int:
    try:
        return _serve()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"liveu-host-helperd fatal error: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
