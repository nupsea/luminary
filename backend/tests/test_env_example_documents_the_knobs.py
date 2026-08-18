"""`.env.example` is the single place a user changes which models run.

Which model does what is decided in one module, and it reads a small set of
knobs. If one of them is missing from the template, the only way to discover it
is to read the source -- which makes "one place to change it" false.

Defaults are compared too. A template that names a model the code no longer
ships is worse than no template: it is a wrong answer with an authoritative
tone.
"""

import re
from pathlib import Path

import pytest

from app.config import Settings

_ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

# Every knob that names a generation-role model. Kept in step with
# `test_model_registry._ROLE_MODEL_KNOBS`, which enforces that nothing outside
# the registry reads them.
_ROLE_KNOBS = (
    "LITELLM_DEFAULT_MODEL",
    "LITELLM_GENERATION_MODEL",
    "VISION_MODEL",
    "FLASHCARD_FACTUALITY_MODEL",
)


@pytest.fixture(scope="module")
def env_example() -> str:
    return _ENV_EXAMPLE.read_text()


@pytest.mark.parametrize("knob", _ROLE_KNOBS)
def test_every_role_knob_appears_in_the_template(knob: str, env_example: str):
    assert re.search(rf"(?m)^#?\s*{knob}=", env_example), (
        f"{knob} decides which model runs and is not in .env.example, so the "
        f"only way to find it is to read the source"
    )


@pytest.mark.parametrize("knob", _ROLE_KNOBS)
def test_a_documented_default_matches_the_shipped_one(knob: str, env_example: str):
    """A commented-out knob documents an option; an uncommented one states the
    default, and then it has to be the actual default."""
    match = re.search(rf"(?m)^{knob}=(.*)$", env_example)
    if match is None:
        return  # commented out: an example, not a claim about the default
    assert match.group(1).strip() == Settings.model_fields[knob].default, (
        f".env.example says {knob}={match.group(1).strip()!r} but the shipped "
        f"default is {Settings.model_fields[knob].default!r}"
    )


def test_the_precedence_is_written_down(env_example: str):
    """Three layers decide which model runs, and a user who does not know the
    order cannot predict what editing this file will do."""
    assert "Precedence" in env_example
    assert "Settings in the app" in env_example
    assert "registry default" in env_example


def test_third_party_providers_are_documented(env_example: str):
    """A local id needs no key and a hosted one does; that is the difference a
    user hits first."""
    for provider in ("openai/", "anthropic/", "gemini/"):
        assert provider in env_example


def test_an_oversized_model_is_documented_as_a_warning_not_a_refusal(env_example: str):
    assert "warning, never a refusal" in env_example
