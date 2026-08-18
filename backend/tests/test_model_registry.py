"""Model choice resolves in one place, and nothing else reads it from config.

Five call sites resolved a model before this, two of them straight out of
`config`. Those two were flashcard generation, which meant a model chosen in
Settings applied to chat and silently did not apply to the cards -- a defect no
test could see, because both paths type-check and both return a model.
"""

import re
from pathlib import Path

import pytest

from app.model_registry import (
    REGISTRY,
    ROLES,
    configured_generation_override,
    default_chat_model,
    profile_for,
)
from app.services import model_router

_APP = Path(__file__).resolve().parent.parent / "app"

# The one module allowed to read a model name out of config. Everything else
# asks the router, so a Settings change reaches every call site or none.
_MAY_READ_CONFIG = {"model_registry.py"}

# Every knob that names a *generation-role* model. RERANK_MODEL, NER_MODEL and
# WHISPER_MODEL_SIZE are deliberately outside this: they are not roles a user
# picks per request, they are not routed, and nothing in Settings offers them.
# FLASHCARD_FACTUALITY_MODEL was outside it by omission and is not any more --
# it names a model that grades product output, which is exactly what this guard
# is for.
_ROLE_MODEL_KNOBS = r"LITELLM_\w+|VISION_MODEL|FLASHCARD_FACTUALITY_MODEL"

_CONFIG_MODEL_READ = re.compile(
    rf"settings\s*\.\s*(?:{_ROLE_MODEL_KNOBS})|"
    rf"get_settings\(\)\s*\.\s*(?:{_ROLE_MODEL_KNOBS})"
)


def _offenders() -> list[str]:
    hits = []
    for path in _APP.rglob("*.py"):
        if path.name in _MAY_READ_CONFIG:
            continue
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if _CONFIG_MODEL_READ.search(line):
                hits.append(f"{path.relative_to(_APP)}:{i}")
    return hits


def test_only_the_registry_reads_a_model_name_from_config():
    """The guard for the defect above. `settings_service` is not exempt: it
    resolves what the user chose, which is a different question from what
    `config` defaults to."""
    offenders = _offenders()
    assert offenders == [], (
        "these read a model name from config instead of asking model_router: "
        + ", ".join(offenders)
    )


@pytest.mark.parametrize("role", ROLES)
def test_every_role_resolves_to_something(role):
    choice = model_router.resolve(role)
    assert choice.model, role
    assert choice.role == role


def test_generation_follows_settings_when_no_override_is_configured(monkeypatch):
    """The bug in one assertion: with no explicit override, generation is
    whatever chat is, so choosing a model in Settings reaches the cards."""
    monkeypatch.setattr(model_router, "configured_generation_override", lambda: None)

    assert model_router.resolve("generation").model == model_router.resolve("chat").model


def test_an_explicit_override_still_wins_for_generation(monkeypatch):
    monkeypatch.setattr(
        model_router, "configured_generation_override", lambda: "ollama/something-else"
    )

    assert model_router.resolve("generation").model == "ollama/something-else"
    assert model_router.resolve("chat").model != "ollama/something-else"


def test_a_missing_cloud_key_falls_back_locally_with_a_reason(monkeypatch):
    """Refusing here would take ingestion down for a configuration problem the
    user can see in Settings. The fallback is reported, not swallowed."""
    def _raise(*, background: bool = False):
        raise ValueError("cloud routing is active but the API key is missing")

    monkeypatch.setattr(model_router.settings_service, "get_effective_routing", _raise)
    monkeypatch.setattr(
        model_router.settings_service, "get_local_chat_model", lambda: "ollama/local"
    )

    choice = model_router.resolve("chat")
    assert choice.model == "ollama/local"
    assert "API key" in (choice.fallback_reason or "")


def test_resident_models_is_the_set_a_memory_profile_constrains():
    """Two roles resolving to different ids cost two runners (I-31). Phase 7's
    residency test asserts against this set."""
    resident = model_router.resident_models()
    assert resident
    assert resident <= {model_router.resolve(r).model for r in ROLES}


def test_a_profile_carries_both_footprint_and_capability():
    profile = REGISTRY[default_chat_model()] if default_chat_model() in REGISTRY else next(
        iter(REGISTRY.values())
    )
    assert profile.resident_gb > 0
    assert profile.min_ram_gb > 0
    assert profile.usable_context > 0
    assert isinstance(profile.supports_json_schema, bool)


def test_an_unregistered_model_resolves_to_no_profile():
    """A user may point Settings at any model Ollama holds. That is allowed, and
    it means the run has no measured footprint -- which callers must be able to
    see rather than assume."""
    assert profile_for("ollama/some-model-nobody-registered") is None


def test_accommodations_are_empty_until_the_matrix_measures_them():
    """Empty means unmeasured, not 'needs nothing'. Authoring one here would
    invent the finding Phase 6 exists to produce."""
    assert all(p.accommodations_needed == () for p in REGISTRY.values())


def test_the_configured_override_carries_a_provider_prefix():
    override = configured_generation_override()
    assert override is None or "/" in override


# --- a literal name is the other half of the same defect ---------------------

# The guard above catches a module *reading* a model out of config. It does not
# catch one that simply writes the name down, which is the same defect with no
# config involved: `_HYDE_MODEL = "ollama/llama3.2:3b"` loaded a third model that
# no profile budgeted for and that evicted the resident one on a single-slot host
# (I-27), and `components.py` offered `llama3.2` to the setup screen while the
# installer on the same machine pulled the profile's model.
#
# Provenance is exempt and must stay exempt: `introduced_for="ollama/llama3.2"`
# records which model an accommodation was discovered on. It is a historical
# fact, not a selection, and rewriting it when the default moves would destroy
# the only thing it is for.
_PROVENANCE = re.compile(r"introduced_for\s*=|measured_on\s*=|#")

_LITERAL_MODEL = re.compile(
    r"""["']((?:ollama/)?(?:llama|qwen|gemma|phi|granite|mistral|deepseek)[\w.]*(?::[\w.-]+)?)["']"""
)

# `config.py` is where a shipped default belongs -- it is the settings surface
# the user overrides from `.env`, and `model_registry` reads it and narrows it to
# the host. `evals.py` names the models an eval request verifies *against*, which
# is a parameter of the measurement and not a choice about what the product runs.
_MAY_NAME_A_MODEL = {"model_registry.py", "config.py", "evals.py"}


def test_no_module_outside_the_registry_writes_a_model_name_down():
    """One place decides which model runs, and it is not a string in a service."""
    offenders = []
    for path in _APP.rglob("*.py"):
        if path.name in _MAY_NAME_A_MODEL:
            continue
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if _PROVENANCE.search(line):
                continue
            match = _LITERAL_MODEL.search(line)
            if match:
                offenders.append(f"{path.relative_to(_APP)}:{i} names {match.group(1)!r}")

    assert offenders == [], (
        "these decide a model by writing its name down instead of asking the "
        "registry:\n  " + "\n  ".join(offenders)
    )


def test_the_suite_reads_the_shipped_defaults_not_a_developer_env_file():
    """A guard for the fixture that pins them.

    `backend/.env` is untracked and outranks the field defaults in
    pydantic-settings, so without the fixture every model assertion in this
    suite is a statement about whoever ran it. It has already produced a test
    that passed on GitHub -- which has no .env -- and failed locally.
    """
    from app.config import Settings, get_settings

    for knob in ("LITELLM_DEFAULT_MODEL", "VISION_MODEL"):
        declared = Settings.model_fields[knob].default
        actual = getattr(get_settings(), knob)
        assert actual == declared, (
            f"{knob} is {actual!r} but the shipped default is {declared!r} -- "
            "a local .env is leaking into the suite"
        )
