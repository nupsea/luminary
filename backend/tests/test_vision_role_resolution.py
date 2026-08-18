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
    REGISTRY,
    ROLES,
    VISION_PREFERENCE,
    default_vision_model,
    fits_host,
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

    Quietly retargeting vision on a 32GB laptop -- because the chat model happens
    to also have eyes -- would be this code overruling a deployment decision
    nobody asked it to revisit. The shared model is consulted only when the
    configured reader does not fit.
    """
    from app import memory_profile
    from app.services import model_router, settings_service

    monkeypatch.setattr(memory_profile, "host_ram_gb", lambda: 32)
    monkeypatch.setattr(settings_service, "configured_vision_override", lambda: None)
    monkeypatch.setattr(settings_service, "get_vision_model", lambda: "ollama/qwen2.5vl:7b")
    monkeypatch.setattr(
        model_router,
        "_shared_vision_model",
        lambda: pytest.fail("sharing must not be consulted when the reader fits"),
    )
    assert model_router.resolve("vision").model == "ollama/qwen2.5vl:7b"


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


def test_max_resident_never_promises_more_than_one_on_the_low_profile():
    """If this rises, the single-model requirement above stops being the point."""
    assert MAX_RESIDENT["low"] == 1
