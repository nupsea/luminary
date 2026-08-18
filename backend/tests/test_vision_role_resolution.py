"""Every profile must have a model that can fill every role.

The low profile had **zero** feasible assignments. `max_resident_models` is 1 on
an 8GB host, and the vision role resolved to a 6.81GB entry declaring
`min_ram_gb=16` -- so the one role that needs a specific capability had no model
that machine could hold, and nothing said so. The first symptom would have been
a crash during ingestion, which is exactly the failure P7 exists to convert into
a refusal at the point of choosing.

Two registry entries were also simply wrong: `qwen3.5:4b` and `gemma3:4b` both
read images and both were recorded `multimodal=False`. A capability written by
hand drifts from the model, so the flags are now measured.
"""

import itertools

import pytest

from app.memory_profile import MAX_RESIDENT, max_resident_models
from app.model_registry import (
    GENERALIST_PREFERENCE,
    REGISTRY,
    ROLES,
    VISION_PREFERENCE,
    default_chat_model,
    default_vision_model,
    fits_host,
    generalist_candidates,
    profile_for,
    vision_candidates,
)


def _feasible(ram_gb: int, profile: str) -> list[dict]:
    """Assignments of a model to every role that this host can actually hold."""
    limit = max_resident_models(profile)
    budget = ram_gb * 1024**3 * 0.5  # models take at most half the machine
    out = []
    for combo in itertools.product(REGISTRY.values(), repeat=len(ROLES)):
        assign = dict(zip(ROLES, combo, strict=True))
        if not assign["vision"].multimodal:
            continue
        if any(not fits_host(m, ram_gb) for m in assign.values()):
            continue
        distinct = {m.id for m in assign.values()}
        if len(distinct) > limit:
            continue
        if sum(REGISTRY[i].resident_bytes for i in distinct) > budget:
            continue
        out.append(assign)
    return out


@pytest.mark.parametrize(
    ("ram_gb", "profile"), [(8, "low"), (16, "standard"), (32, "performance")]
)
def test_every_profile_can_fill_every_role(ram_gb, profile):
    assert _feasible(ram_gb, profile), (
        f"the {profile} profile has no assignment covering all four roles on a "
        f"{ram_gb}GB host: a machine in this class cannot run the product"
    )


def test_the_low_profile_is_satisfiable_by_a_single_model():
    """`max_resident_models` is 1 there, so a second model is not a cost -- it is
    the reason nothing fits."""
    single = [a for a in _feasible(8, "low") if len({m.id for m in a.values()}) == 1]
    assert single, "the low profile needs one model that can do all four roles"


class TestVisionCandidates:
    def test_only_multimodal_models_are_offered(self):
        assert all(p.multimodal for p in vision_candidates(8))

    def test_a_model_the_host_cannot_hold_is_not_offered(self):
        ids = [p.id for p in vision_candidates(8)]
        assert "ollama/qwen2.5vl:7b" not in ids, (
            "6.81GB and min_ram_gb=16: offering it to an 8GB host is the bug"
        )

    def test_measured_quality_outranks_size(self):
        """The ranking is what each model did on real figures, not what it weighs.

        `gemma3:4b` reads images and, measured, called a decision tree a Boolean
        circuit and an Intel manual page ARM. It must not be picked first merely
        for being multimodal and small.
        """
        assert vision_candidates(8)[0].id == VISION_PREFERENCE[0]

    def test_an_unranked_multimodal_model_sorts_last(self):
        """Nobody has looked at it, which is not a reason to hand it a figure."""
        ranked = [p.id for p in vision_candidates(32)]
        unranked = [i for i in ranked if i not in VISION_PREFERENCE]
        if unranked:
            assert ranked.index(unranked[0]) > ranked.index(VISION_PREFERENCE[0])


class TestDefaultAndOverride:
    def test_the_default_is_host_aware(self, monkeypatch):
        import app.model_registry as reg

        monkeypatch.setattr(
            reg, "fits_host", lambda p, ram=None: p.resident_bytes < 4 * 1024**3
        )
        chosen = default_vision_model()
        assert profile_for(chosen).resident_bytes < 4 * 1024**3

    def test_an_explicit_choice_is_honoured_even_when_oversized(self, monkeypatch):
        """Settings is the user's decision; `residency_report` flags it as
        oversized rather than this quietly overruling them."""
        from app.services import model_router, settings_service

        monkeypatch.setattr(
            settings_service, "configured_vision_override", lambda: "ollama/qwen2.5vl:7b"
        )
        choice = model_router.resolve("vision")
        assert choice.model == "ollama/qwen2.5vl:7b"
        assert choice.explicit


def test_a_host_with_room_keeps_its_dedicated_reader(monkeypatch):
    """Sharing is a remedy for a host that cannot hold two models, not a preference.

    Quietly retargeting vision on a large machine -- because the chat model
    happens to also have eyes -- would be this code overruling a deployment
    decision nobody asked it to revisit.

    "Room" is both models fitting *together*, not just the residency count. 32GB
    was not enough for this assertion once that check existed: half of 32GB is
    16GB and the pair is 10.02GB, which fits -- but the earlier version of this
    test asserted sharing was never consulted at all, and it is consulted to
    answer the question.
    """
    from app import memory_profile
    from app.services import model_router, settings_service

    monkeypatch.setattr(memory_profile, "host_ram_gb", lambda: 32)
    monkeypatch.setattr(settings_service, "configured_vision_override", lambda: None)
    monkeypatch.setattr(settings_service, "get_vision_model", lambda: "ollama/qwen2.5vl:7b")
    monkeypatch.setattr(settings_service, "get_local_chat_model", lambda: "ollama/qwen3.5:4b")
    monkeypatch.setattr(
        settings_service,
        "get_effective_routing",
        lambda background=False: ("ollama/qwen3.5:4b", None),
    )
    assert model_router.resolve("vision").model == "ollama/qwen2.5vl:7b"


def test_a_host_too_small_for_both_falls_back_to_one(monkeypatch):
    """16GB is the case this exists for: the pair is 10.02GB, 63% of RAM before
    the backend's 4.7GB ingest peak, which is when both models are in use."""
    from app import memory_profile
    from app.services import model_router, settings_service

    monkeypatch.setattr(memory_profile, "host_ram_gb", lambda: 16)
    monkeypatch.setattr(settings_service, "configured_vision_override", lambda: None)
    monkeypatch.setattr(settings_service, "get_vision_model", lambda: "ollama/qwen2.5vl:7b")
    monkeypatch.setattr(settings_service, "get_local_chat_model", lambda: "ollama/qwen3.5:4b")
    monkeypatch.setattr(
        settings_service,
        "get_effective_routing",
        lambda background=False: ("ollama/qwen3.5:4b", None),
    )
    assert model_router.resolve("vision").model == "ollama/qwen3.5:4b"


def test_an_8gb_host_resolves_every_role_to_one_model(monkeypatch):
    """The whole fix, end to end and without patching the helper under test.

    On a real 8GB laptop: the configured 6.81GB reader does not fit, so vision
    falls back to the model already answering chat, and all four roles land on
    one resident model. Before this, vision resolved to a model that machine
    could not hold and nothing said so.
    """
    from app import memory_profile
    from app.model_registry import ROLES
    from app.services import model_router, settings_service

    monkeypatch.setattr(memory_profile, "host_ram_gb", lambda: 8)
    monkeypatch.setattr(settings_service, "configured_vision_override", lambda: None)
    monkeypatch.setattr(
        settings_service, "get_local_chat_model", lambda: "ollama/qwen3.5:4b"
    )
    monkeypatch.setattr(
        settings_service,
        "get_effective_routing",
        lambda background=False: ("ollama/qwen3.5:4b", None),
    )

    resolved = {role: model_router.resolve(role).model for role in ROLES}
    assert len(set(resolved.values())) == 1, (
        f"an 8GB host can hold one model, and these roles need {len(set(resolved.values()))}: "
        f"{resolved}"
    )

    chosen = profile_for(next(iter(set(resolved.values()))))
    assert chosen is not None and chosen.multimodal, "the one model must be able to read a figure"
    assert fits_host(chosen, 8), "and the machine must be able to hold it"


class TestOneModelServesEveryRole:
    """Fixing the vision role alone was not enough, and the gap was invisible.

    With vision host-aware but chat still defaulting to a text-only model, an 8GB
    host resolved chat to `llama3.2` and vision to `qwen3.5:4b` -- two models on a
    profile allowed one. The failure had moved rather than gone.
    """

    def test_a_fresh_install_on_8gb_resolves_every_role_to_one_model(self, monkeypatch):
        from app import memory_profile
        from app.services import model_router

        monkeypatch.setattr(memory_profile, "host_ram_gb", lambda: 8)

        resolved = {role: model_router.resolve(role).model for role in ROLES}
        distinct = set(resolved.values())
        assert len(distinct) == 1, (
            f"an 8GB host may keep one model resident, and these roles need "
            f"{len(distinct)}: {resolved}"
        )

        chosen = profile_for(next(iter(distinct)))
        assert chosen is not None
        assert chosen.multimodal, "the one model has to be able to read a figure"
        assert fits_host(chosen, 8), "and the machine has to be able to hold it"

    def test_the_generalist_and_vision_rankings_agree(self):
        """Two independent measurements -- P6's text metrics and the figure probe --
        put the same model first, which is why there is no trade-off to weigh."""
        assert GENERALIST_PREFERENCE[0] == VISION_PREFERENCE[0]

    def test_a_generalist_must_be_able_to_do_both_jobs(self):
        assert all(p.multimodal for p in generalist_candidates(8))

    def test_an_explicit_oversized_chat_choice_is_not_silently_downgraded(
        self, monkeypatch
    ):
        """Same rule as vision: the default is narrowed by the host, a choice is not."""
        from app.services import model_router, settings_service

        monkeypatch.setattr(
            settings_service,
            "get_effective_routing",
            lambda background=False: ("ollama/qwen2.5:14b-instruct", None),
        )
        assert model_router.resolve("chat").model == "ollama/qwen2.5:14b-instruct"

    def test_a_host_with_room_upgrades_the_text_model(self, monkeypatch):
        """The shipped default is sized for the machine that cannot hold two.

        Above 24GB the extra memory is there to be used: the strongest measured
        text model plus a reader fits, and leaving the small default in place
        would spend the band on nothing.
        """
        from app import memory_profile
        from app.model_registry import TEXT_PREFERENCE

        monkeypatch.setattr(memory_profile, "host_ram_gb", lambda: 32)
        monkeypatch.setattr(
            "app.model_registry.get_settings",
            lambda: type("S", (), {"LITELLM_DEFAULT_MODEL": "ollama/qwen3.5:4b"})(),
        )
        assert default_chat_model() == TEXT_PREFERENCE[0]

    def test_a_host_without_room_keeps_the_small_default(self, monkeypatch):
        from app import memory_profile

        monkeypatch.setattr(memory_profile, "host_ram_gb", lambda: 16)
        monkeypatch.setattr(
            "app.model_registry.get_settings",
            lambda: type("S", (), {"LITELLM_DEFAULT_MODEL": "ollama/qwen3.5:4b"})(),
        )
        assert default_chat_model() == "ollama/qwen3.5:4b"


def test_max_resident_never_promises_more_than_one_on_the_low_profile():
    """If this rises, the single-model requirement above stops being the point."""
    assert MAX_RESIDENT["low"] == 1


# --- narrowing must be visible, not just correct -----------------------------


def test_a_configured_model_the_host_cannot_use_is_reported(monkeypatch):
    """Overruling the user silently is the failure this reports.

    `oversized_models` is built from the models actually in play, so a model
    narrowed *away* is absent from it: configuring a 14B on a single-resident
    profile produced a clean report describing a 4B nobody chose.
    """
    monkeypatch.setenv("LUMINARY_MEMORY_PROFILE", "low")
    monkeypatch.setenv("LITELLM_DEFAULT_MODEL", "ollama/qwen2.5:14b-instruct")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        from app.services.model_router import residency_report

        narrowed = residency_report()["narrowed_defaults"]
        assert "chat" in narrowed, "the user was overruled and told nothing"
        assert narrowed["chat"]["configured"] == "ollama/qwen2.5:14b-instruct"
        assert narrowed["chat"]["resolved"] != "ollama/qwen2.5:14b-instruct"
        assert narrowed["chat"]["reason"], "a warning with no reason is not actionable"
    finally:
        get_settings.cache_clear()


def test_a_configured_model_the_host_can_use_is_not_reported(monkeypatch):
    """The other direction, so the field is a signal rather than a constant."""
    monkeypatch.setenv("LUMINARY_MEMORY_PROFILE", "performance")
    monkeypatch.setenv("LITELLM_DEFAULT_MODEL", "ollama/qwen2.5:14b-instruct")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        from app.services.model_router import residency_report

        report = residency_report()
        assert report["narrowed_defaults"] == {}
        assert report["roles"]["chat"]["model"] == "ollama/qwen2.5:14b-instruct"
    finally:
        get_settings.cache_clear()


def test_the_oversized_warning_actually_produces_a_warning():
    """It never had. `oversized_models` is a list of model ids and this indexed
    them as dicts, so the check raised TypeError; the boot caller catches every
    exception, so the advisory silently did nothing for as long as it existed.

    Asserting the text, not just the count: a warning that names no model and no
    number tells a user nothing they can act on.
    """
    from app.services import model_router

    original = model_router.residency_report
    model_router.residency_report = lambda: {
        "oversized_models": ["ollama/qwen2.5vl:7b"],
        "host_ram_gb": 8,
        "within_residency_limit": True,
        "unmeasured_models": [],
        "profile": "low",
        "resident_count": 1,
        "max_resident": 1,
        "narrowed_defaults": {},
    }
    try:
        warnings = model_router.warn_if_configuration_exceeds_host()
    finally:
        model_router.residency_report = original

    assert len(warnings) == 1, warnings
    assert "qwen2.5vl:7b" in warnings[0]
    assert "8GB" in warnings[0], "the warning must name the machine it is about"
    assert "16GB" in warnings[0], "and what the model actually needs"


def test_a_narrowed_default_is_warned_about_at_boot():
    """The user picked a model and got another one; silence is the defect."""
    from app.services import model_router

    original = model_router.residency_report
    model_router.residency_report = lambda: {
        "oversized_models": [],
        "host_ram_gb": 8,
        "within_residency_limit": True,
        "unmeasured_models": [],
        "profile": "low",
        "resident_count": 1,
        "max_resident": 1,
        "narrowed_defaults": {
            "chat": {
                "configured": "ollama/qwen2.5:14b-instruct",
                "resolved": "ollama/qwen3.5:4b",
                "reason": "cannot read figures",
            }
        },
    }
    try:
        warnings = model_router.warn_if_configuration_exceeds_host()
    finally:
        model_router.residency_report = original

    assert len(warnings) == 1
    assert "qwen2.5:14b-instruct" in warnings[0] and "qwen3.5:4b" in warnings[0]
