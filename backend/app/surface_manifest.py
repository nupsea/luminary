import json
from functools import lru_cache
from pathlib import Path

_MODE_ORDER = {"public": 0, "full": 1}


@lru_cache(maxsize=1)
def _manifest() -> dict:
    path = Path(__file__).resolve().parents[2] / "surface-manifest.json"
    with path.open() as f:
        data = json.load(f)
    if data.get("version") != 2:
        raise RuntimeError(f"unsupported manifest version: {data.get('version')}")
    return data


def surfaces_for_mode(mode: str) -> list[dict]:
    rank = _MODE_ORDER[mode]
    return [s for s in _manifest()["surfaces"] if _MODE_ORDER[s["mode"]] <= rank]


def enabled_routers(mode: str) -> set[str]:
    out: set[str] = set()
    for s in surfaces_for_mode(mode):
        for r in (s.get("backend") or {}).get("routers", []):
            out.add(r)
    return out
