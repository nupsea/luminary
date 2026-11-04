"""Install a connector from its folder, until the app can do it from Settings (#436, #437).

Builds the connector's own environment with `uv sync`, asks it to `describe` itself, and
prints what it claims and what its source's terms say. The machine root is `DATA_DIR`'s, so
run it with the environment the app runs with.

Usage::

    cd backend && uv run python -m app.scripts.install_connector /path/to/connector
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.services.connectors import install_from_folder


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    installed = asyncio.run(install_from_folder(Path(argv[0])))
    desc = installed.description
    print(f"Installed {installed.name} {desc.get('version')} ({desc.get('licence')})")
    print(f"Claims: {', '.join(desc.get('url_prefixes') or []) or 'no links'}")
    terms = desc.get("terms") or {}
    print(f"Its source's terms ({terms.get('url')}): {terms.get('statement')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
