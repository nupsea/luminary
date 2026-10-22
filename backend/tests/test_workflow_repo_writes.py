"""The repo reads and writes the ingestion and concept workflows moved out of `workflows/`
(0.17.0 batch 1), on a real database."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import ConceptModel, DocumentModel, FlashcardModel
from app.repos.concept_repo import ConceptRepo
from app.repos.document_repo import DocumentRepo
from app.repos.flashcard_repo import FlashcardRepo
from tests.factories import make_card, make_chunk, make_document


@pytest.fixture
async def session(memory_db):
    factory = async_sessionmaker(memory_db.engine, expire_on_commit=False)
    async with factory() as s:
        s.add(make_document(id="d1", title="Book", file_path="/x", stage="parsing"))
        s.add_all(
            make_chunk(
                id=f"c{i}", document_id="d1", token_count=1, chunk_index=i, entities_text=f"e{i}"
            )
            for i in range(2)
        )
        s.add(ConceptModel(id="k1", slug="time-travel", label="Time travel"))
        s.add_all(
            make_card(
                id=cid,
                source_excerpt="s",
                concept_id=concept,
                concept_slug=slug,
                mapping_status="mapped" if concept else "unmapped",
            )
            for cid, concept, slug in (
                ("f1", "k1", "time-travel"),
                ("f2", None, "morlocks"),
                ("f3", None, None),
            )
        )
        await s.commit()
        yield s


async def test_document_fields_title_and_chunk_entities(session):
    docs = DocumentRepo(session)

    await docs.update_fields("d1", stage="error", error_message="ffmpeg not found")
    await docs.set_chunk_entities_text("c0", None)
    await session.commit()

    doc = await session.get(DocumentModel, "d1")
    await session.refresh(doc)
    assert (doc.stage, doc.error_message) == ("error", "ffmpeg not found")
    assert await docs.title("d1") == "Book"
    assert await docs.title("missing") is None
    assert sorted(await docs.chunk_entity_texts(["d1"])) == [("c0", "d1", None), ("c1", "d1", "e1")]


async def test_a_concept_rebuild_unmaps_and_remaps_cards_by_slug(session):
    cards = FlashcardRepo(session)

    await cards.detach_from_concepts()
    await ConceptRepo(session).delete_all()
    await session.commit()
    assert (await session.execute(select(ConceptModel))).first() is None
    assert sorted(c.id for c in await cards.slugged_but_unmapped()) == ["f1", "f2"]

    assert await cards.map_slug_to_concept("time-travel", "k2") == 1
    await session.commit()
    remapped = await session.get(FlashcardModel, "f1")
    await session.refresh(remapped)
    assert (remapped.concept_id, remapped.mapping_status) == ("k2", "mapped")
    assert [c.id for c in await cards.slugged_but_unmapped()] == ["f2"]


async def test_script_reads_and_the_startup_reconcile(session):
    docs = DocumentRepo(session)
    session.add(make_document(id="d2", title="Done", file_path="/z"))
    await session.commit()

    assert sorted(await docs.all_ids()) == ["d1", "d2"]
    assert [d.id for d in await docs.complete_without_word_count()] == ["d2"]
    assert [row[0] for row in await docs.chunk_ner_inputs("d1")] == ["c0", "c1"]

    assert await docs.fail_unfinished("interrupted") == 1
    await session.commit()
    stages = {d.id: (d.stage, d.error_message) for d in await docs.all_documents()}
    assert stages["d2"] == ("complete", None)
    assert stages["d1"][0] == "error"
