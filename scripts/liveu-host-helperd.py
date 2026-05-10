#!/usr/bin/env python3
import json
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
ALLOWED_ACTIONS = {
    "restart-liveu": ["/usr/bin/systemctl", "restart", "liveu"],
    "reboot": ["/sbin/reboot"],
    "liveu-config-show": ["/bin/bash", "-lc", "liveu-config --show"],
}


def _handle_action(action: str) -> tuple[bool, str]:
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
                if uid != ALLOWED_UID:
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
                    ok, output = _handle_action(action)
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
