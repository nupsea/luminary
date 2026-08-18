"""The memory profile, and the registry fields it makes load-bearing.

`min_ram_gb` and `resident_bytes` sat on every registry entry since P3 and
nothing read them, so a 10GB model was selectable on a 16GB laptop and the first
symptom was a crash during ingestion rather than a refusal at the point of
choosing. These tests hold the three questions that were never asked together:
how big is this machine, how many models will stay resident, and do they fit.
"""

import pytest
from httpx import ASGITransport, AsyncClient

import app.config as config_module
from app import memory_profile
from app.main import app
from app.model_registry import REGISTRY, fits_host, models_for_host, oversized_for_host


@pytest.fixture
def profile_settings(monkeypatch):
    def _apply(**overrides):
        stub = config_module.Settings().model_copy(update=overrides)
        monkeypatch.setattr(memory_profile, "get_settings", lambda: stub)
        return stub

    return _apply


@pytest.fixture
def host_ram(monkeypatch):
    def _apply(gb: int):
        monkeypatch.setattr(memory_profile, "host_ram_gb", lambda: gb)

    return _apply


# Detection and defaulting


def test_a_small_machine_gets_the_low_profile():
    """16GB moved to `standard` on 2026-08-18.

    It had been `low`, which gave a 16GB laptop one serving slot. That machine
    cannot carry two models -- the text model plus the 6.81GB reader is 10.02GB,
    92% of RAM once the backend's 4.7GB ingest peak is counted -- but it can
    comfortably carry more parallelism, which is what the larger profile buys it.
    """
    assert memory_profile.profile_for_ram(8) == "low"
    assert memory_profile.profile_for_ram(12) == "low"
    assert memory_profile.profile_for_ram(16) == "standard"


def test_a_large_machine_gets_standard():
    assert memory_profile.profile_for_ram(24) == "standard"
    assert memory_profile.profile_for_ram(64) == "standard"


def test_performance_is_never_chosen_automatically():
    """It raises parallelism past what a single GPU serves well (I-31), so it
    stays opt-in however large the machine."""
    assert memory_profile.profile_for_ram(512) == "standard"


def test_an_unreadable_ram_figure_is_treated_as_a_small_machine():
    """An unknown box must never be guessed into `standard` -- the installer
    makes the same call, and being wrong downward only costs throughput."""
    assert memory_profile.profile_for_ram(0) == "low"


def test_an_explicit_profile_wins_over_the_detected_one(profile_settings, host_ram):
    profile_settings(LUMINARY_MEMORY_PROFILE="performance")
    host_ram(8)

    assert memory_profile.active_profile() == "performance"
    assert memory_profile.profile_is_explicit() is True


def test_the_installers_legacy_name_still_reads(profile_settings, host_ram):
    """`install.sh` shipped `public` for the small profile before this existed;
    an installed .env must keep working."""
    profile_settings(LUMINARY_MEMORY_PROFILE="public")
    host_ram(64)

    assert memory_profile.active_profile() == "low"


def test_an_unknown_profile_name_falls_back_to_the_detected_one(profile_settings, host_ram):
    profile_settings(LUMINARY_MEMORY_PROFILE="enormous")
    host_ram(8)

    assert memory_profile.active_profile() == "low"
    assert memory_profile.profile_is_explicit() is False


def test_a_profile_larger_than_the_hardware_is_reported(profile_settings, host_ram):
    """Set by hand rather than refused: the failure it causes is a crash under
    load, which is worth warning about and not worth blocking startup for."""
    profile_settings(LUMINARY_MEMORY_PROFILE="performance")
    host_ram(8)

    assert memory_profile.profile_suits_host() is False


def test_residency_limit_follows_the_profile():
    assert memory_profile.max_resident_models("low") == 1
    assert memory_profile.max_resident_models("standard") == 2


# The registry fields, now that something reads them


def test_a_model_larger_than_the_host_does_not_fit():
    big = REGISTRY["ollama/qwen2.5:14b-instruct"]

    assert fits_host(big, 16) is False
    assert fits_host(big, 24) is True


def test_an_unknown_host_size_does_not_block_a_model():
    """The check exists to warn about a machine we measured, never to block one
    we could not."""
    assert fits_host(REGISTRY["ollama/qwen2.5:14b-instruct"], 0) is True


def test_the_host_catalogue_is_smallest_first():
    """On a constrained machine the honest first suggestion is the one leaving
    room for the embedder, the entity model and vision."""
    sizes = [p.resident_bytes for p in models_for_host(64)]

    assert sizes == sorted(sizes)


def test_an_eight_gigabyte_host_is_offered_only_what_it_can_hold():
    ids = {p.id for p in models_for_host(8)}

    assert "ollama/llama3.2" in ids
    assert "ollama/qwen2.5:14b-instruct" not in ids


def test_oversized_names_what_the_model_wanted():
    over = oversized_for_host("ollama/qwen2.5:14b-instruct", 16)

    assert over is not None
    assert over.min_ram_gb == 24


def test_an_unregistered_model_is_unmeasured_not_oversized():
    """Unmeasured and too-large are different answers, and conflating them would
    have every cloud model read as oversized."""
    assert oversized_for_host("ollama/something-nobody-registered", 8) is None


# The report the UI reads


@pytest.mark.asyncio
async def test_the_residency_endpoint_reports_a_configuration_that_does_not_fit(monkeypatch):
    from app.services import model_router

    monkeypatch.setattr(
        model_router,
        "residency_report",
        lambda: {
            "profile": "low",
            "profile_explicit": False,
            "profile_suits_host": True,
            "host_ram_gb": 16,
            "roles": {
                "chat": {"model": "ollama/qwen2.5:14b-instruct", "local": True,
                         "resident_gb": 10.0, "fallback_reason": None},
            },
            "resident_models": ["ollama/qwen2.5:14b-instruct", "ollama/qwen2.5vl:7b"],
            "resident_count": 2,
            "max_resident": 1,
            "within_residency_limit": False,
            "resident_gb": 16.0,
            "unmeasured_models": [],
            "oversized_models": ["ollama/qwen2.5:14b-instruct"],
        },
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/settings/models")

    assert resp.status_code == 200
    body = resp.json()
    assert body["within_residency_limit"] is False
    assert body["oversized_models"] == ["ollama/qwen2.5:14b-instruct"]


@pytest.mark.asyncio
async def test_the_catalogue_lists_models_this_host_cannot_hold_rather_than_hiding_them():
    """Someone deciding what to pull is better served seeing what exists and
    what it would need."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/settings/models/catalogue")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(REGISTRY)
    assert [e["resident_gb"] for e in body] == sorted(e["resident_gb"] for e in body)
    assert all("fits_host" in e for e in body)


@pytest.mark.asyncio
async def test_the_report_counts_distinct_models_not_roles():
    """Four roles resolving to one model cost one runner, not four (I-31)."""
    from app.services.model_router import residency_report

    report = residency_report()

    assert report["resident_count"] == len(set(report["resident_models"]))
    assert len(report["roles"]) == 4


# Footprints are measured, not estimated (scripts/model_footprint.py)


def test_every_footprint_is_a_measured_figure_not_a_round_estimate():
    """The estimates these replaced were low by up to 44% -- llama3.2 was carried
    at a round 2.0GB and weighs 2.88GB. A round number here means someone typed
    it, and these values decide whether a model is offered on a laptop."""
    rounded = [p.id for p in REGISTRY.values() if p.resident_bytes % (1024**3) == 0]

    assert rounded == [], f"these look estimated rather than measured: {rounded}"


def test_the_min_ram_policy_matches_every_entry():
    """`min_ram_gb` is derived, so it must not drift from the rule that derives
    it: twice the resident size, rounded up to a RAM tier."""
    tiers = (8, 16, 24, 32, 48, 64, 96, 128)

    for profile in REGISTRY.values():
        needed = profile.resident_gb * 2
        expected = next(t for t in tiers if t >= needed)
        assert profile.min_ram_gb == expected, (
            f"{profile.id}: {profile.resident_gb}GB resident implies min_ram {expected}GB, "
            f"entry says {profile.min_ram_gb}GB"
        )


def test_no_entry_adopts_its_advertised_context_as_its_budget():
    """I-27: a model advertising 131072 or 262144 is stating a capability. A
    slot costs a full window of KV cache, so the deployed window is a decision."""
    for profile in REGISTRY.values():
        assert profile.usable_context <= 32768, (
            f"{profile.id} carries usable_context={profile.usable_context}, "
            "which reads as an advertised window rather than a deployment choice"
        )


def test_the_small_class_all_fits_an_eight_gigabyte_machine():
    """The product targets 8-16GB. If nothing in the registry fits that, the
    catalogue cannot answer the question a user on a laptop is asking.

    This counted `not p.multimodal` as "text models", which assumed the two
    categories are disjoint. They are not: a multimodal model is a text model
    that also has eyes, and correcting two wrong `multimodal` flags dropped this
    count from 4 to 2 without a single model leaving the registry. Every entry
    does text, so the question is how many the host can hold.
    """
    fitting = models_for_host(8)

    assert len(fitting) >= 4, [p.id for p in fitting]


def test_an_eight_gigabyte_machine_is_offered_something_that_reads_figures():
    """The role with a hard capability requirement is the one that had no model.

    With both small multimodal entries recorded as text-only, the vision role
    resolved to a 6.81GB model needing 16GB, and the low profile had zero
    feasible assignments across its four roles.
    """
    readers = [p for p in models_for_host(8) if p.multimodal]

    assert readers, "an 8GB host cannot run the vision role at all"


def test_a_thinking_model_is_recorded_as_one():
    """think=False is unconditional (I-27), and this is the field that says for
    which models that is load-bearing rather than incidental."""
    thinkers = [p.id for p in REGISTRY.values() if p.thinking_default]

    assert "ollama/qwen3.5:4b" in thinkers
