import json
from functools import lru_cache
from pathlib import Path

_TIER_ORDER = {"public": 0, "labs": 1, "dev": 2}


@lru_cache(maxsize=1)
def _manifest() -> dict:
    path = Path(__file__).resolve().parents[2] / "surface-manifest.json"
    with path.open() as f:
        data = json.load(f)
    if data.get("version") != 1:
        raise RuntimeError(f"unsupported manifest version: {data.get('version')}")
    return data


def surfaces_for_tier(tier: str) -> list[dict]:
    bundle_rank = _TIER_ORDER[tier]
    return [s for s in _manifest()["surfaces"] if _TIER_ORDER[s["tier"]] <= bundle_rank]


def enabled_routers(tier: str, labs_enabled: set[str]) -> set[str]:
    out: set[str] = set()
    for s in surfaces_for_tier(tier):
        if tier != "dev" and s["tier"] == "labs" and s["id"] not in labs_enabled:
            continue
        for r in (s.get("backend") or {}).get("routers", []):
            out.add(r)
    return out


def labs_surfaces() -> list[dict]:
    return [s for s in _manifest()["surfaces"] if s["tier"] == "labs"]
