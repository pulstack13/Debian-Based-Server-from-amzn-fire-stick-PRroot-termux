#!/usr/bin/env python3
"""Fetch the ad blocker's localhost status and write it atomically.

Usage:
    firelab-adblock-status.py TARGET TEMP

The blocker APK serves JSON on 127.0.0.1:18083. Termux cannot always read
/sdcard, so the dashboard reads this file through the PRoot /host bind mount
instead of talking to the socket directly.
"""

import json
import os
import socket
import sys
import time

HOST = "127.0.0.1"
PORT = 18083
CONNECT_TIMEOUT = 1.0
READ_TIMEOUT = 2.0


def fetch_status() -> dict:
    with socket.create_connection((HOST, PORT), timeout=CONNECT_TIMEOUT) as sock:
        sock.settimeout(READ_TIMEOUT)
        sock.sendall(
            b"GET /status HTTP/1.0\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Connection: close\r\n\r\n"
        )

        raw = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            raw += chunk
            if len(raw) > 256 * 1024:
                raise ValueError("status response too large")

    body = raw.split(b"\r\n\r\n", 1)[-1]
    payload = json.loads(body.decode("utf-8", "replace"))
    if not isinstance(payload, dict):
        raise ValueError("status response is not an object")
    return payload


def offline_payload() -> dict:
    return {
        "enabled": False,
        "service_running": False,
        "blocklist_ready": False,
        "blocklist_size": 0,
        "queries_session": 0,
        "blocked_session": 0,
        "queries_total": 0,
        "blocked_total": 0,
        "last_blocked": "",
        "upstream": "",
        "uptime_seconds": 0,
        "error": "status socket unreachable",
        "version": "",
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: firelab-adblock-status.py TARGET TEMP", file=sys.stderr)
        return 2

    target, temp = sys.argv[1], sys.argv[2]

    try:
        payload = fetch_status()
        available = True
    except Exception:
        payload = offline_payload()
        available = False

    payload["available"] = available
    payload["collected_at"] = int(time.time() * 1000)
    payload["agent"] = True

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
