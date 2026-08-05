"""Resolution of the read-only resources that ship alongside the backend.

Four things are looked up relative to the tree the backend was installed into:
``surface-manifest.json`` (boot-fatal if absent), the built SPA, ``alembic.ini``
plus its versions, and ``pyproject.toml`` for the version string.

In a source checkout that tree is the repo root. In the macOS bundle it is
``Luminary.app/Contents/Resources``, which mirrors the repo layout so the
fallback below still resolves -- ``LUMINARY_APP_ROOT`` exists so the bundle
never has to depend on that coincidence, and so the layout can be verified
before shipping rather than discovered at boot.
"""

import functools
import os
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[2]


@functools.lru_cache(maxsize=1)
def app_root() -> Path:
    override = os.environ.get("LUMINARY_APP_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _SOURCE_ROOT


def is_packaged() -> bool:
    return bool(os.environ.get("LUMINARY_APP_ROOT", "").strip())


def backend_root() -> Path:
    return app_root() / "backend"


def surface_manifest_path() -> Path:
    return app_root() / "surface-manifest.json"


def spa_dist() -> Path:
    return app_root() / "frontend" / "dist"


def alembic_ini() -> Path:
    return backend_root() / "alembic.ini"


def pyproject_path() -> Path:
    return backend_root() / "pyproject.toml"


@functools.lru_cache(maxsize=1)
def app_version() -> str:
    """The shipped version. Lives here, below every layer, because both the API
    and the diagnostics service need it and a service must not import main."""
    try:
        import tomllib  # noqa: PLC0415

        with pyproject_path().open("rb") as fh:
            return tomllib.load(fh)["project"]["version"]
    except Exception:
        return "0.0.0"
