"""Speech to text installs the versions CI tested, and a drifted install is offered again."""

import importlib.metadata
import tomllib
from pathlib import Path

from app.services import components

_LOCK = tomllib.loads((Path(__file__).parents[1] / "uv.lock").read_text())
_PACKAGES = {p["name"]: p for p in _LOCK["package"]}
_ROOT = next(p for p in _LOCK["package"] if p.get("source", {}).get("virtual") == ".")


def _closure(names: list[str]) -> set[str]:
    seen: set[str] = set()
    todo = list(names)
    while todo:
        name = todo.pop()
        if name in seen or name not in _PACKAGES:
            continue
        seen.add(name)
        todo += [d["name"] for d in _PACKAGES[name].get("dependencies", [])]
    return seen


def _pins() -> dict[str, str]:
    comp = components.get_component("transcription")
    assert comp is not None
    return dict(r.split("==") for r in comp.packages)


def test_every_pin_is_the_locked_version():
    for name, version in _pins().items():
        assert _PACKAGES[name]["version"] == version, f"{name} pin differs from uv.lock"


def test_every_package_the_bundle_lacks_is_pinned():
    groups = _ROOT["dev-dependencies"]
    bundled = _closure(
        [d["name"] for d in _ROOT["dependencies"]] + [d["name"] for d in groups["full"]]
    )
    needed = _closure([d["name"] for d in groups["media"]]) - bundled
    assert needed == set(_pins()), f"pin exactly the unbundled media packages: {sorted(needed)}"


def test_a_drifted_version_reads_as_not_installed(monkeypatch):
    comp = components.get_component("transcription")
    real = importlib.metadata.version
    monkeypatch.setattr(
        components.importlib.metadata,
        "version",
        lambda name: "99.0.0" if name == "av" else real(name),
    )
    assert components._pins_met(comp) is False


def test_the_locked_versions_read_as_installed():
    assert components._pins_met(components.get_component("transcription")) is True


def test_a_reinstall_drops_the_old_versions_metadata(tmp_path):
    for stale in ("av-17.0.0.dist-info", "faster_whisper-1.2.1.dist-info", "numpy-2.0.0.dist-info"):
        (tmp_path / stale).mkdir()
    components._drop_stale_metadata(tmp_path, _comp_packages())
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["faster_whisper-1.2.1.dist-info", "numpy-2.0.0.dist-info"]


def _comp_packages() -> tuple[str, ...]:
    comp = components.get_component("transcription")
    assert comp is not None
    return comp.packages
