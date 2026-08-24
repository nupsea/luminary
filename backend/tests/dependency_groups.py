"""Resolve PEP 735 dependency groups the way uv installs them.

Shared because two tests ask what a group contains and a naive
`" ".join(group)` answers differently from the resolver: with
`{include-group = ...}` a group's real contents are its transitive closure, so
a GPL dependency could be one hop away from a group that must not carry it and
a string check would still pass.
"""

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((REPO / "backend" / "pyproject.toml").read_text())
RAW_GROUPS: dict[str, list] = PYPROJECT["dependency-groups"]


def distributions(requirements, *, seen: frozenset[str] = frozenset()) -> set[str]:
    """Distribution names in a requirement list, following include-group."""
    out: set[str] = set()
    for req in requirements:
        if isinstance(req, str):
            out.add(re.split(r"[<>=!~\[ ]", req, maxsplit=1)[0].strip().lower())
        elif isinstance(req, dict) and "include-group" in req:
            included = req["include-group"]
            assert included not in seen, f"dependency-group cycle at {included!r}"
            out |= distributions(RAW_GROUPS[included], seen=seen | {included})
    return out


BASE: set[str] = distributions(PYPROJECT["project"]["dependencies"])
GROUPS: dict[str, set[str]] = {name: distributions(reqs) for name, reqs in RAW_GROUPS.items()}
