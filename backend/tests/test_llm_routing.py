"""The routing report says where each unit of work runs, and can be wrong out loud.

`GET /settings/llm/routing` is the evidence behind the claim that a library stays
on the machine. A table that could only ever print "local" would satisfy that
claim with its own text, so the property under test is not that the rows read
local -- it is that `on_device` is **derived** from the resolved model id and moves
when the id moves. `test_a_hosted_component_flips_the_table` is that check; without
it the other three assert nothing.

See `.claude/rules/common/product-integrity.md`.
"""

import pytest

from app.services import llm_routing
from app.services import settings_service as ss

# Work that has no remote implementation at all, so no mode may move it. The
# learner record is here with a null model: nothing to route is not the same
# answer as routed locally, and the report keeps them apart.
STRUCTURALLY_LOCAL = {
    "indexing",
    "retrieval",
    "transcription",
    "extraction",
    "learner_record",
}


def _row(report, work_id):
    for w in report.work:
        if w.id == work_id:
            return w
    raise AssertionError(f"no {work_id!r} row in the routing report")


@pytest.fixture
def private_routing():
    original = dict(ss._cache)
    ss._cache.update({"llm_mode": "private"})
    yield
    ss._cache.clear()
    ss._cache.update(original)


@pytest.fixture
def hybrid_routing():
    """Hybrid with a stub key: without one the interactive branch cannot resolve."""
    original = dict(ss._cache)
    ss._cache.update(
        {
            "llm_mode": "hybrid",
            "cloud_provider": "openai",
            "cloud_model": "gpt-5-mini",
            "openai_api_key": "sk-test-not-a-real-key",
        }
    )
    yield
    ss._cache.clear()
    ss._cache.update(original)


@pytest.fixture
def cloud_routing_without_a_key():
    original = dict(ss._cache)
    ss._cache.update(
        {
            "llm_mode": "cloud",
            "cloud_provider": "anthropic",
            "cloud_model": "claude-sonnet-5",
            "anthropic_api_key": "",
        }
    )
    yield
    ss._cache.clear()
    ss._cache.update(original)


def test_private_mode_keeps_every_unit_of_work_on_device(private_routing):
    report = llm_routing.routing_report()

    assert report.mode == "private"
    assert report.provider is None
    assert report.leaves_device == []


def test_hybrid_moves_only_the_interactive_rows(hybrid_routing):
    report = llm_routing.routing_report()

    assert report.mode == "hybrid"
    assert report.provider == "openai"
    # The whole privacy claim in one assertion: what leaves is the question and
    # the material the user asked to have written, and nothing else.
    assert set(report.leaves_device) == {"answering", "study_material"}
    assert _row(report, "enrichment").on_device, (
        "background work must stay local in hybrid mode, or ingesting a library "
        "sends every document to a provider"
    )


@pytest.mark.parametrize("work_id", sorted(STRUCTURALLY_LOCAL))
def test_structural_rows_stay_local_in_every_mode(hybrid_routing, work_id):
    row = _row(llm_routing.routing_report(), work_id)

    assert row.on_device
    assert not row.routable, (
        f"{work_id} is reported as routable; if it really became routable the "
        "report is right and this test is what needs updating"
    )


def test_a_hosted_component_flips_the_table(monkeypatch, private_routing):
    """The check can fail, which is what makes the other assertions mean anything.

    A hosted embedder is the case I-9 forbids, so it will not arrive by accident
    -- but if it ever did, this table must say so rather than keep printing the
    answer it printed yesterday.
    """
    before = _row(llm_routing.routing_report(), "indexing")
    assert before.on_device

    monkeypatch.setattr(llm_routing, "EMBEDDING_MODEL", "openai/text-embedding-3-small")
    after = _row(llm_routing.routing_report(), "indexing")

    assert not after.on_device
    assert llm_routing.routing_report().leaves_device == ["indexing"]


def test_a_huggingface_id_is_not_mistaken_for_a_provider(private_routing):
    """`BAAI/bge-small-en-v1.5` has a prefix and is still local.

    Reading "contains a slash" as "remote" would report the embedder, the
    reranker and the entity extractor as cloud services in every mode.
    """
    assert llm_routing.is_on_device("BAAI/bge-small-en-v1.5")
    assert llm_routing.is_on_device("cross-encoder/ms-marco-MiniLM-L-12-v2")
    assert llm_routing.is_on_device("urchade/gliner_multi_pii-v1")
    assert llm_routing.is_on_device("ollama/qwen3.5:4b")
    assert not llm_routing.is_on_device("openai/gpt-5-mini")
    assert not llm_routing.is_on_device("anthropic/claude-sonnet-5")


def test_cloud_without_a_key_reports_the_local_model_it_will_really_use(
    cloud_routing_without_a_key,
):
    """The mode says cloud and the machine answers. That is worth seeing."""
    row = _row(llm_routing.routing_report(), "answering")

    assert row.on_device
    assert row.fallback_reason, (
        "a fallback with no reason is indistinguishable from a working cloud "
        "route that happens to name a local model"
    )


def test_the_local_probe_is_null_when_nothing_measured_it(private_routing, monkeypatch):
    """A missing measurement is null, never a number.

    First run quotes this to say what a local answer costs on *this* machine. A
    default would put an invented figure in front of a stranger deciding whether
    to keep the product, which is the shortcut `product-integrity.md` exists for.
    """
    from app.services import model_keepwarm

    monkeypatch.setattr(model_keepwarm, "measured_probe_seconds", lambda: None)
    assert llm_routing.routing_report().local_probe_seconds is None

    monkeypatch.setattr(model_keepwarm, "measured_probe_seconds", lambda: 21.3)
    assert llm_routing.routing_report().local_probe_seconds == 21.3


def test_a_preview_reports_the_unsaved_mode_and_saves_nothing(hybrid_routing):
    """Picking Cloud before saving shows Cloud's routes; the saved Hybrid is untouched."""
    saved = llm_routing.routing_report()
    with ss.previewing_routing("cloud", None, None):
        preview = llm_routing.routing_report()

    assert preview.mode == "cloud"
    assert _row(preview, "enrichment").model == "openai/gpt-5-mini"
    assert not _row(preview, "enrichment").on_device
    assert ss._cache["llm_mode"] == "hybrid"
    assert llm_routing.routing_report().leaves_device == saved.leaves_device


def test_a_previewed_provider_without_its_key_shows_the_local_fallback(hybrid_routing):
    """A provider switch takes its default model, and a missing key is reported, not hidden."""
    with ss.previewing_routing(None, "anthropic", None):
        row = _row(llm_routing.routing_report(), "answering")

    assert row.on_device
    assert row.fallback_reason and "anthropic" in row.fallback_reason


async def test_the_routing_endpoint_previews_query_params(hybrid_routing):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        preview = await client.get(
            "/settings/llm/routing", params={"mode": "cloud", "model": "gpt-6-luna"}
        )
        saved = await client.get("/settings/llm/routing")
        bad = await client.get("/settings/llm/routing", params={"mode": "orbit"})

    rows = {w["id"]: w for w in preview.json()["work"]}
    assert rows["enrichment"]["model"] == "openai/gpt-6-luna"
    assert "enrichment" not in saved.json()["leaves_device"]
    assert bad.status_code == 422
