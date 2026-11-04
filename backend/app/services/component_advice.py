"""What a user is told when an ingest needs components this install lacks: one sentence naming
each, the remedy that reaches this host, and which ones the app can install itself."""

from __future__ import annotations

from app.exceptions import DependencyUnavailable
from app.services.components import ffmpeg_install_command, get_component, running_in_container


class ComponentsMissing(DependencyUnavailable):
    """`detail` is `components_missing_detail`'s body, which the upload dialog reads."""


def components_missing_detail(required: list[str], what: str) -> dict:
    return {
        "message": media_missing_message(required, what),
        # Everything missing, whether or not the app can install it: `components`
        # alone can be empty, and then the payload named nothing while the ingest refused.
        "missing": list(required),
        # Only what the app can fetch: a button that fails on click is worse than none.
        "components": installable(required)[0],
    }


def component_labels(component_ids: list[str]) -> str:
    """Human names for components, so an error names the thing the user installs."""
    names = []
    for cid in component_ids:
        comp = get_component(cid)
        names.append(comp.label if comp else cid)
    if len(names) <= 1:
        return names[0] if names else "an extra component"
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _all_withheld_for_licence(component_ids: list[str]) -> bool:
    """Whether every named component is genuinely held back by its licence.

    The catalogue marks those "(not distributed with Luminary)". A component
    with no entry, or a permissive one, is missing for some other reason and
    must not be described as a licensing decision.
    """
    comps = [get_component(cid) for cid in component_ids]
    return bool(comps) and all(
        c is not None and "not distributed with Luminary" in (c.licence or "") for c in comps
    )


def media_missing_message(required: list[str], what: str = "YouTube") -> str:
    """One sentence naming everything missing, and what to do about each kind."""
    fetchable, manual = installable(required)
    # Only claim a licence reason where one exists. yt-dlp is Unlicense, and
    # saying it was "not bundled for licensing reasons" stated a constraint
    # that is not real and pointed the user at nothing they could act on.
    if _all_withheld_for_licence(required):
        lead = (
            f"{what} needs {component_labels(required)}, "
            f"{'which are' if len(required) > 1 else 'which is'} not bundled for "
            f"licensing reasons."
        )
    else:
        lead = f"{what} needs {component_labels(required)}."
    parts = [lead]
    if fetchable:
        parts.append(f"Install {component_labels(fetchable)} below.")
    if manual:
        # Named precisely, because the old advice ("brew install ffmpeg") was
        # advice the user had often already followed: the binary existed and the
        # bundle's PATH could not see it. It is found automatically now, so the
        # remaining case is genuinely not having it.
        names = component_labels(manual)
        if running_in_container():
            # Host advice cannot reach a container: the user installs ffmpeg on
            # their Mac, the Linux container still cannot see it, and the wall
            # is identical. The image is the thing that has to change.
            parts.append(
                f"{names} is not in this Docker image. Rebuild it with "
                f"`WITH_MEDIA=1 docker compose --profile ai up --build`; "
                f"installing on the host does not reach the container."
            )
        else:
            # One command for the platform running this, not a list to pick
            # from. Windows was in neither of the two the message used to name,
            # so a Windows user was shown brew and apt and left to guess.
            parts.append(
                f"{names} is found automatically once installed on this machine "
                f"(for example `{ffmpeg_install_command()}`)."
            )
    return " ".join(parts)


def installable(component_ids: list[str]) -> tuple[list[str], list[str]]:
    """Split into what the app can fetch and what the user must supply.

    `kind == "tool"` has no automated source on purpose: the licence travels
    with the build, so it is not Luminary's to choose. Offering an install
    button for one is worse than offering nothing -- it fails on click with a
    message the error should have carried in the first place.
    """
    fetchable, manual = [], []
    for cid in component_ids:
        comp = get_component(cid)
        # An id with no catalogue entry is not fetchable -- there is nothing to
        # fetch it from. It used to default the other way, so a missing
        # component the app has no installer for still rendered an "Install"
        # button, which is the failure this docstring warns about.
        fetchable_here = comp is not None and comp.kind != "tool"
        (fetchable if fetchable_here else manual).append(cid)
    return fetchable, manual
