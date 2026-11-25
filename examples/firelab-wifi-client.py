#!/usr/bin/env python3
"""Read the WiFi helper's one-shot JSON socket and write it atomically.

Usage:
    firelab-wifi-client.py TARGET TEMP

The helper APK (com.firelab.wifi) opens 127.0.0.1:18082 for a single
connection after it receives the COLLECT broadcast. This client retries for a
few seconds so it can be started just before the broadcast.
"""

import json
import os
import socket
import sys
import time

HOST = "127.0.0.1"
PORT = 18082
CONNECT_TIMEOUT = 0.3
READ_TIMEOUT = 5.0
TOTAL_WAIT = 10.0


def read_payload() -> str:
    deadline = time.time() + TOTAL_WAIT
    last_error = None

    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=CONNECT_TIMEOUT) as sock:
                sock.settimeout(READ_TIMEOUT)
                chunks = []
                while True:
                    data = sock.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
                return b"".join(chunks).decode("utf-8", "replace").strip()
        except OSError as exc:
            last_error = exc
            time.sleep(0.2)

    raise TimeoutError(f"helper socket not reachable: {last_error}")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: firelab-wifi-client.py TARGET TEMP", file=sys.stderr)
        return 2

    target, temp = sys.argv[1], sys.argv[2]

    try:
        text = read_payload()
        payload = json.loads(text)
    except Exception as exc:
        print(f"wifi client: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict) or not payload.get("ok", False):
        print("wifi client: helper returned an error payload", file=sys.stderr)
        return 1

    directory = os.path.dirname(temp) or "."
    os.makedirs(directory, exist_ok=True)

    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())

    os.replace(temp, target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
