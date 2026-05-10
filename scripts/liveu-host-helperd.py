#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

SOCKET_PATH = Path("/run/liveu-helper/liveu-helper.sock")
SOCKET_DIR = SOCKET_PATH.parent
ALLOWED_ACTIONS = {
    "restart-liveu": ["/usr/bin/systemctl", "restart", "liveu"],
    "reboot": ["/sbin/reboot"],
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
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"command execution error: {exc}"

    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        return False, output or f"command failed with exit code {result.returncode}"
    return True, output or "OK"


def _serve() -> int:
    SOCKET_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SOCKET_DIR, 0o755)
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
        srv.bind(str(SOCKET_PATH))
        os.chmod(SOCKET_PATH, 0o660)
        srv.listen(16)
        while True:
            conn, _ = srv.accept()
            with conn:
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
