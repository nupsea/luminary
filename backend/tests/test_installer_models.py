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


def test_install_sh_pulls_the_performance_pair(sh):
    """`performance` is the only band with room for a text model that cannot read
    figures, so it is the only one that pulls two. Everywhere else one model does
    both -- which is what the backend resolves to, so pulling anything else
    downloads a model that never loads."""
    assert 'LARGE_TEXT_MODEL="qwen2.5:14b-instruct"' in sh
    assert 'CHAT_MODEL="$LARGE_TEXT_MODEL"' in sh
    assert 'VISION_MODEL="$PUBLIC_GENERALIST"' in sh, (
        "the reader on `performance` is the generalist: the large text model is "
        "not multimodal, so something else has to read figures"
    )
    assert "ollama pull qwen2.5vl:7b" not in sh, (
        "a banner telling the user to pull a second model is the advice that "
        "breaks a single-model host"
    )


def test_install_ps1_pulls_the_performance_pair(ps1):
    assert '$LargeTextModel = "qwen2.5:14b-instruct"' in ps1
    assert "$chatModel = $LargeTextModel" in ps1
    assert "$visionModel = $PublicGeneralist" in ps1


def test_the_large_text_model_is_the_registry_top_rank(sh):
    """The installer must pull what the backend will resolve to on that band."""
    from app.model_registry import TEXT_PREFERENCE

    declared = f"ollama/{_assign(sh, r'^LARGE_TEXT_MODEL=\"([^\"]+)\"')}"
    assert declared == TEXT_PREFERENCE[0]


def test_the_performance_pair_fits_the_band_it_targets(sh):
    """`performance` starts above 24GB, so 32GB is the binding case."""
    from app.model_registry import GENERALIST_PREFERENCE, fits_together

    text = REGISTRY[f"ollama/{_assign(sh, r'^LARGE_TEXT_MODEL=\"([^\"]+)\"')}"]
    reader = REGISTRY[GENERALIST_PREFERENCE[0]]
    assert fits_together((text, reader), 32), (
        f"{text.resident_gb + reader.resident_gb:.2f}GB does not fit a 32GB host "
        f"under the half-the-machine budget"
    )


def test_the_bands_agree_across_platforms(sh, ps1):
    """Three bands, two scripts, one boundary set."""
    assert '[ "$_gb" -lt 16 ]; then echo "public"' in sh
    assert '[ "$_gb" -le 24 ]; then echo "standard"' in sh
    assert 'echo "performance"' in sh
    assert '$MemGB -gt 24' in ps1
    assert '$MemGB -ge 16' in ps1


def test_the_chat_model_is_chosen_after_the_profile_is_known(ps1):
    """PowerShell compares an undefined variable as 0, so a profile test evaluated
    before the profile exists takes the wrong branch silently. The band block has
    to be hoisted above the model pull that reads it."""
    defined = ps1.index('$LumProfile = "performance"')
    used = ps1.index('if ($LumProfile -eq "performance")')
    assert defined < used, "the profile block must be hoisted above the model pull"
