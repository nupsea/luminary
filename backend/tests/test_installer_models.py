"""The installer must pull the model the backend will resolve to.

These are two independent decisions about the same thing, made in two languages,
and they were already disagreeing. The installer pulled `llama3.2` on every
profile and pulled no vision model at all, while the backend on a single-resident
host resolves every role to a multimodal generalist. The result on an 8GB laptop:
the model answering questions is not the model the backend asks for, and the
vision role points at something that was never downloaded.

Nothing can import a shell script, so this reads the constants out of both
installers and compares them to the registry. It is a text check, which is
weaker than a call -- but the alternative is no check, and the failure it catches
is silent on the machine that can least afford it.
"""

import re
from pathlib import Path

import pytest

from app.model_registry import GENERALIST_PREFERENCE, REGISTRY, profile_for

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_SH = _SCRIPTS / "install.sh"
_PS1 = _SCRIPTS / "install.ps1"


def _assign(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    assert match, f"could not find {pattern!r} -- the installer was restructured"
    return match.group(1).strip().strip('"').strip("'")


@pytest.fixture(scope="module")
def sh() -> str:
    return _SH.read_text()


@pytest.fixture(scope="module")
def ps1() -> str:
    return _PS1.read_text()


def test_the_generalist_is_registered_and_multimodal():
    """The whole point of the single-resident default: one model, every role."""
    profile = profile_for(GENERALIST_PREFERENCE[0])
    assert profile is not None, "the generalist must be in the registry"
    assert profile.multimodal


def test_install_sh_pulls_the_registry_generalist(sh):
    assert _assign(sh, r'^PUBLIC_GENERALIST="([^"]+)"') == GENERALIST_PREFERENCE[0].removeprefix(
        "ollama/"
    )


def test_install_ps1_pulls_the_registry_generalist(ps1):
    assert _assign(ps1, r'^\$PublicGeneralist = "([^"]+)"') == GENERALIST_PREFERENCE[
        0
    ].removeprefix("ollama/")


def test_both_installers_agree_with_each_other(sh, ps1):
    """Two platforms, one decision. They drifted on the chat model before."""
    assert _assign(sh, r'^PUBLIC_GENERALIST="([^"]+)"') == _assign(
        ps1, r'^\$PublicGeneralist = "([^"]+)"'
    )
    assert _assign(sh, r'^DEFAULT_CHAT_MODEL="([^"]+)"') in ps1


def test_the_generalist_fits_the_class_the_public_profile_targets(sh):
    """`public` is chosen for anything under 24GB, so 8GB is the binding case."""
    model = f"ollama/{_assign(sh, r'^PUBLIC_GENERALIST=\"([^\"]+)\"')}"
    profile = REGISTRY[model]
    assert profile.min_ram_gb <= 8, (
        f"{model} asks for {profile.min_ram_gb}GB; the public profile installs on 8GB"
    )


def test_install_sh_pulls_the_reader_rather_than_suggesting_it(sh):
    """The banner used to recommend a 6.81GB model unconditionally.

    On a host keeping one model loaded that advice is actively harmful -- the
    second model evicts the one answering questions. And on a host with room the
    backend resolves vision to it whether or not it is on disk, so leaving it a
    suggestion put the install and the backend in disagreement. It is pulled where
    it fits and not mentioned where it does not.
    """
    assert 'DEDICATED_READER="qwen2.5vl:7b"' in sh
    assert 'VISION_MODEL="$DEDICATED_READER"' in sh, "the reader must be pulled, not suggested"
    assert "ollama pull qwen2.5vl:7b" not in sh, (
        "a closing banner telling the user to pull a second model is the advice "
        "that breaks a single-model host"
    )


def test_install_ps1_pulls_the_reader_rather_than_suggesting_it(ps1):
    assert '$DedicatedReader = "qwen2.5vl:7b"' in ps1
    assert "$visionModel = $DedicatedReader" in ps1
    assert "ollama pull qwen2.5vl:7b" not in ps1


def test_the_resolved_vision_model_is_not_re_read_from_the_environment(ps1):
    """It was, and the re-read discarded the profile decision: `$visionModel` was
    computed from RAM and then overwritten with an unset environment variable, so
    the pull never ran on a machine that had not set it by hand."""
    assert ps1.count("$visionModel = $env:LUMINARY_VISION_MODEL") == 1
    assert ps1.index("$visionModel = $env:LUMINARY_VISION_MODEL") < ps1.index(
        "Pulling vision model"
    )


class TestTheProfileReachesTheBackend:
    """The installer's profile choice must be written where the backend reads it.

    It wrote `OLLAMA_NUM_PARALLEL` and `ENRICHMENT_VISION_CONCURRENCY` but not the
    profile, so the backend sized its own from host RAM. Choose `public` on a 32GB
    machine and the two disagree: the installer pulls one generalist while the
    backend resolves chat and vision to two models that were never downloaded.
    """

    def test_install_sh_persists_it(self, sh):
        assert "_upsert_env LUMINARY_MEMORY_PROFILE" in sh

    def test_install_ps1_persists_it(self, ps1):
        assert 'Set-EnvLine $EnvLines "LUMINARY_MEMORY_PROFILE"' in ps1

    def test_both_translate_public_to_the_canonical_name(self, sh, ps1):
        """`public` collides with LUMINARY_MODE=public, an unrelated axis. `low` is
        the name; the alias is read for .env files that predate it."""
        from app.memory_profile import _LEGACY_ALIASES, PROFILES

        assert _LEGACY_ALIASES.get("public") == "low"
        assert "low" in PROFILES
        assert 'public) _upsert_env LUMINARY_MEMORY_PROFILE "low"' in sh
        assert 'if ($LumProfile -eq "public") { "low" }' in ps1

    def test_every_name_the_installer_can_write_is_one_the_backend_knows(self, sh):
        from app.memory_profile import _LEGACY_ALIASES, PROFILES

        literals = set(re.findall(r'_upsert_env LUMINARY_MEMORY_PROFILE "([^"$]+)"', sh))
        # The `*)` branch passes $PROFILE through, and the prompt offers exactly
        # these three -- `public` is caught by the branch above it.
        written = literals | {"standard", "performance"}
        assert '*)      _upsert_env LUMINARY_MEMORY_PROFILE "$PROFILE"' in sh, (
            "the fallthrough must still write the profile, not skip it"
        )
        unknown = {w for w in written if _LEGACY_ALIASES.get(w, w) not in PROFILES}
        assert not unknown, f"the backend would size from RAM instead for: {unknown}"


def test_the_reader_threshold_is_derived_from_the_registry(sh):
    """`READER_MIN_RAM_GB` must be the RAM at which the backend will actually load
    both models. Below it the installer would download 6GB for a model that never
    runs; above it the backend resolves vision to a model that was never pulled.
    """
    from app.model_registry import (
        _RESIDENT_SET_FRACTION,
        GENERALIST_PREFERENCE,
        VISION_PREFERENCE,
        fits_together,
    )

    declared = int(_assign(sh, r"^READER_MIN_RAM_GB=(\d+)"))
    text = REGISTRY[GENERALIST_PREFERENCE[0]]
    reader = REGISTRY[
        next(v for v in VISION_PREFERENCE if v not in GENERALIST_PREFERENCE)
    ]

    assert fits_together((text, reader), declared), (
        f"the installer pulls the reader at {declared}GB, where the backend would "
        f"refuse to load both: {text.resident_gb + reader.resident_gb:.2f}GB against a "
        f"budget of {declared * _RESIDENT_SET_FRACTION:.2f}GB"
    )
    assert not fits_together((text, reader), declared - 8), (
        f"{declared}GB is higher than it needs to be; the tier below also fits"
    )


def test_the_chat_model_is_chosen_after_the_profile_is_known(ps1):
    """PowerShell compares an undefined variable as 0, so `$MaxLoaded -le 1` is
    True before `$MaxLoaded` exists -- which would silently pick the
    single-model default on every profile, including a 32GB desktop."""
    defined = ps1.index('"performance" { $MaxLoaded = 2')
    used = ps1.index("if ($MaxLoaded -le 1)")
    assert defined < used, "the profile block must be hoisted above the model pull"
