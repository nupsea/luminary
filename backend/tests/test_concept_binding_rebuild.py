"""A concept rebuild preserves the learner's record (docs/concept-model-design.md).

persist_concepts wipes + recreates the concept layer with fresh ids, but cards carry a STABLE
`concept_slug`, so the rebuild re-maps them (by slug, or by re-grounding through their source
chunk) and re-derives mastery -- instead of orphaning every card the way a blanket unmap did.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
import app.services.graph as graph_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ConceptModel, FlashcardModel
from app.workflows.concept_nodes.persist import _sig_slug, persist_concepts

_ENTITIES = ["data modeling", "normalization"]


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_e, orig_f = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    orig_g = graph_module._graph_service
    graph_module._graph_service = None
    yield factory
    db_module._engine, db_module._session_factory = orig_e, orig_f
    graph_module._graph_service = orig_g


def _state():
    cen = [0.1] * 384
    return {
        "dry_run": False,
        "entity_chunks": {"data modeling": ["chX"], "normalization": ["chX"]},
        "lateral_edges": [],
        "hierarchy": {
            "concepts": [
                {"label": "data modeling", "sun": "data modeling", "entities": _ENTITIES,
                 "document_ids": ["bookA"], "salience": 5.0, "centroid": cen},
            ],
        },
    }


def _card(card_id: str, concept_slug: str, chunk_id: str, stability: float) -> FlashcardModel:
    now = datetime.now(UTC)
    return FlashcardModel(
        id=card_id, document_id="bookA", chunk_id=chunk_id,
        question="q", answer="a", source_excerpt="src",
        fsrs_stability=stability, fsrs_state="review", last_review=now,
        concept_id="old-id", concept_slug=concept_slug, mapping_status="mapped",
    )


async def test_card_rebinds_by_slug_and_mastery_rederives(test_db):
    slug = _sig_slug(_ENTITIES)
    async with test_db() as s:
        # a fully-stable card bound by slug; its chunk is NOT in evidence, isolating the slug path
        s.add(_card("card1", slug, "chOther", 21.0))
        await s.commit()

    state = await persist_concepts(_state())

    async with test_db() as s:
        concept = (await s.execute(select(ConceptModel))).scalars().one()
        card = await s.get(FlashcardModel, "card1")

    assert concept.slug == slug
    assert card.concept_id == concept.id and card.mapping_status == "mapped"  # re-bound by slug
    assert concept.mastery > 0  # re-derived from the card's preserved FSRS stability
    diag = state["diagnostics"]["persist_concepts"]
    assert diag["cards_rebound"] == 1 and diag["cards_rebound_via_chunk"] == 0


async def test_orphan_rebinds_via_chunk(test_db):
    async with test_db() as s:
        # slug matches nothing this run, but the card's source chunk (chX) is in the concept's
        # evidence -> re-grounded through the stable chunk layer
        s.add(_card("card2", "c-stale-gone", "chX", 10.0))
        await s.commit()

    state = await persist_concepts(_state())

    async with test_db() as s:
        concept = (await s.execute(select(ConceptModel))).scalars().one()
        card = await s.get(FlashcardModel, "card2")

    assert card.concept_id == concept.id and card.mapping_status == "mapped"
    assert card.concept_slug == concept.slug  # binding corrected for the next rebuild
    diag = state["diagnostics"]["persist_concepts"]
    assert diag["cards_rebound"] == 0 and diag["cards_rebound_via_chunk"] == 1


async def test_truly_gone_concept_leaves_card_unmapped(test_db):
    async with test_db() as s:
        # neither slug nor chunk matches the rebuilt concept -> honest unmap (not a false binding)
        s.add(_card("card3", "c-stale-gone", "chNowhere", 5.0))
        await s.commit()

    await persist_concepts(_state())

    async with test_db() as s:
        card = await s.get(FlashcardModel, "card3")
    assert card.concept_id is None and card.mapping_status == "unmapped"
    assert card.concept_slug == "c-stale-gone"  # slug retained; may re-match a future run
