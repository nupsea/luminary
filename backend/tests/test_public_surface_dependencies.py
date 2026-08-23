"""A `public` surface must be able to run in the image that serves public mode.

Three of them could not. The Docker image installs base dependencies only
(`uv sync --no-default-groups`), while `web_ingest`, `youtube_ingest` and
`audio_transcribe` are all declared `mode: public` and every one of their
libraries sat in a group that install drops. `web_ingest`'s own manifest
description said "requires the full dependency group" -- the contradiction was
written down and still shipped.

The GPL carve-out is real and stays, but it has to be declared here rather than
discovered by a user whose ingest fails.
"""

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = tomllib.loads((REPO / "backend" / "pyproject.toml").read_text())

# The distributions each public ingest surface cannot run without.
PUBLIC_SURFACE_DISTRIBUTIONS = {
    "web_ingest": ("trafilatura", "cloudscraper"),
    "youtube_ingest": ("yt-dlp",),
    "audio_transcribe": ("faster-whisper",),
}

# Public surfaces whose dependencies carry GPL-2.0-or-later components, which
# may not travel inside anything Luminary distributes. These are opt-in at
# build time (WITH_MEDIA=1) instead of shipping by default.
GPL_GATED = {"youtube_ingest", "audio_transcribe"}


_RAW_GROUPS = PYPROJECT["dependency-groups"]


def _names(requirements, *, seen: frozenset[str] = frozenset()) -> set[str]:
    """Distribution names in a requirement list, resolving PEP 735 includes.

    Without the include-group arm this reports `media` as holding only
    faster-whisper, which is what uv installs plus everything the include
    pulls in -- a test that reads groups differently from the resolver would
    pass while the built image lacked the package.
    """
    out: set[str] = set()
    for req in requirements:
        if isinstance(req, str):
            out.add(re.split(r"[<>=!~\[ ]", req, maxsplit=1)[0].strip().lower())
        elif isinstance(req, dict) and "include-group" in req:
            included = req["include-group"]
            assert included not in seen, f"dependency-group cycle at {included!r}"
            out |= _names(_RAW_GROUPS[included], seen=seen | {included})
    return out


BASE = _names(PYPROJECT["project"]["dependencies"])
GROUPS = {name: _names(reqs) for name, reqs in _RAW_GROUPS.items()}


@pytest.mark.parametrize(
    "surface", sorted(set(PUBLIC_SURFACE_DISTRIBUTIONS) - GPL_GATED)
)
def test_an_ungated_public_surface_ships_in_the_public_image(surface):
    """Base dependencies are all the Docker image installs, so anything a
    public surface needs and is allowed to ship has to be there."""
    missing = [d for d in PUBLIC_SURFACE_DISTRIBUTIONS[surface] if d not in BASE]
    assert not missing, (
        f"{surface} is mode=public but {missing} are not base dependencies, "
        f"so the public image cannot serve it"
    )


@pytest.mark.parametrize("surface", sorted(GPL_GATED))
def test_a_gpl_gated_surface_is_reachable_through_the_media_opt_in(surface):
    """The carve-out may withhold these from the image; it may not strand them
    where no documented install reaches them at all."""
    missing = [d for d in PUBLIC_SURFACE_DISTRIBUTIONS[surface] if d not in GROUPS["media"]]
    assert not missing, f"{surface} needs {missing}, which WITH_MEDIA=1 does not install"


def test_the_memory_guard_can_actually_read_memory_where_the_app_ships():
    """psutil sat in `dev`. Absent, host_ram_gb() returns 0, and fits_host reads
    0 as "unmeasurable" and waves every model through -- so the residency check
    was inert in exactly the constrained install it exists for."""
    assert "psutil" in BASE


def test_the_public_image_does_not_carry_full_mode_grammars():
    """code_parsing is mode=full. Shipping five tree-sitter grammars in an image
    with no surface for them is weight with no feature behind it."""
    assert not {d for d in BASE if d.startswith("tree-sitter")}
    assert {d for d in GROUPS["full"] if d.startswith("tree-sitter")}
