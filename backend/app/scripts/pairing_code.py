"""Mint a pairing code on a server with no screen (#511).

Codes live in the running server's memory and only its own loopback may ask for one, so this
asks it over 127.0.0.1. In the container::

    docker exec <container> python -m app.scripts.pairing_code
"""

from __future__ import annotations

import json
import sys
import urllib.request

from app.config import get_settings


def main() -> int:
    prefix = "/api" if get_settings().LUMINARY_MODE == "public" else ""
    url = f"http://127.0.0.1:7820{prefix}/devices/pairing-code"
    with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=10) as resp:
        body = json.load(resp)
    print(f"Pairing code {body['code']}, valid until {body['expires_at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
