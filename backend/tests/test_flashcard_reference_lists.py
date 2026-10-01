"""A whole-document card read leaves out bibliography chunks (#191)."""

import pytest

from app.models import ChunkModel, DocumentModel, SectionModel
from app.services.flashcard import _fetch_chunks, _is_reference_chunk

ENTRIES = (
    "[11] Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Deep residual learning.\n"
    "In Proceedings of the IEEE Conference on Computer Vision, pages 770–778, 2016.\n"
    "[12] Sepp Hochreiter and Jürgen Schmidhuber. Long short-term memory. 9(8):1735–1780, 1997.\n"
)
PROSE = "The encoder is composed of a stack of six identical layers, each with two sub-layers."


def test_a_dense_run_of_entries_is_a_reference_list_under_any_heading():
    assert _is_reference_chunk(ENTRIES, "Conclusion")


def test_a_references_heading_decides_even_a_chunk_with_no_marks():
    assert _is_reference_chunk("Daniel J, and Group, RAD-AID Conference Writing.", "References")


def test_prose_citing_a_couple_of_sources_is_kept():
    text = (
        PROSE + " Residual connections [11] follow He et al., 2016. Each is normalized [1] after."
    )
    assert not _is_reference_chunk(text, "Encoder and Decoder Stacks")


async def _document(factory, chunks: list[tuple[str, str | None]]) -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id="d1",
                title="Attention",
                format="pdf",
                content_type="paper",
                word_count=100,
                page_count=1,
                file_path="/tmp/a.pdf",
                stage="complete",
            )
        )
        for i, (text, heading) in enumerate(chunks):
            section_id = None
            if heading:
                section_id = f"s{i}"
                session.add(
                    SectionModel(
                        id=section_id,
                        document_id="d1",
                        heading=heading,
                        level=1,
                        section_order=i,
                    )
                )
            session.add(
                ChunkModel(
                    id=f"c{i}",
                    document_id="d1",
                    section_id=section_id,
                    text=text,
                    token_count=20,
                    page_number=1,
                    chunk_index=i,
                )
            )
        await session.commit()


@pytest.mark.parametrize("heading", [None, "References"])
async def test_a_full_read_skips_the_bibliography(test_db, heading):
    _engine, factory, _tmp = test_db
    await _document(factory, [(PROSE, None), (ENTRIES, heading)])
    async with factory() as session:
        chunks = await _fetch_chunks("d1", "full", None, session)
    assert [c.id for c in chunks] == ["c0"]


async def test_a_document_that_is_only_a_bibliography_is_read_as_is(test_db):
    _engine, factory, _tmp = test_db
    await _document(factory, [(ENTRIES, None)])
    async with factory() as session:
        chunks = await _fetch_chunks("d1", "full", None, session)
    assert [c.id for c in chunks] == ["c0"]


async def test_a_chosen_references_section_is_read_as_is(test_db):
    _engine, factory, _tmp = test_db
    await _document(factory, [(PROSE, "Encoder"), (ENTRIES, "References")])
    async with factory() as session:
        chunks = await _fetch_chunks("d1", "section", "References", session)
    assert [c.id for c in chunks] == ["c1"]
