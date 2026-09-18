"""Tests for forward-sweeping passage selection, transition skipping, and deduplication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel
from app.services.flashcard import FlashcardService
from app.services.flashcard_generators import (
    _is_lexical_duplicate,
    _passage_not_yet_used,
)


def _chunk(
    index: int,
    text: str = "A substantial text about distributed systems architecture and consensus.",
) -> ChunkModel:
    return ChunkModel(
        id=f"chunk-{index}",
        document_id="doc-1",
        section_id=None,
        text=text,
        token_count=len(text.split()),
        page_number=1,
        chunk_index=index,
    )


class TestPassageSelectionForwardSweep:
    def test_sweeps_forward_from_latest_used_chunk(self):
        """When used chunks are in the middle (e.g. index 10-12), the next passage
        must sweep forward into index 13+, NOT jump backwards to chunk 0."""
        every = [
            _chunk(
                i,
                f"Substantive content block {i} discussing principles of reliable protocols.",
            )
            for i in range(20)
        ]
        preferred = [every[10], every[11]]
        used = {"chunk-10", "chunk-11"}

        result = _passage_not_yet_used(every, preferred, used)
        result_indices = [c.chunk_index for c in result]

        # Must start at 12 or greater (forward), never 0-9
        assert result_indices[0] >= 12, f"Expected sweep forward past 11, got {result_indices[0]}"
        assert not any(idx < 12 for idx in result_indices)

    def test_skips_transition_chunks_when_sweeping(self):
        """Transition headers like 'In the next chapter' or short titles must not be
        selected as the sole passage for flashcard generation."""
        intro = _chunk(0, "Table of Contents")  # short, < 80 chars
        trans = _chunk(
            1,
            "In the next section we will explore how consensus mechanisms function.",
        )  # transition pattern
        real1 = _chunk(
            2,
            "Paxos guarantees consensus by requiring a quorum of acceptors to agree on values.",
        )
        real2 = _chunk(
            3,
            "Raft simplifies the state machine approach by using a designated leader with logs.",
        )
        every = [intro, trans, real1, real2]

        preferred = [real1]
        used = {"chunk-2"}

        result = _passage_not_yet_used(every, preferred, used)
        assert any(c.id == "chunk-3" for c in result)

    def test_wraps_around_when_at_end_of_document(self):
        """When the latest used chunk is at the end, it wraps around to earlier unused content."""
        every = [
            _chunk(
                i,
                f"Substantive content paragraph {i} explaining core indexing algorithms.",
            )
            for i in range(5)
        ]
        preferred = [every[4]]
        used = {"chunk-4"}

        result = _passage_not_yet_used(every, preferred, used)
        assert any(c.id in {"chunk-0", "chunk-1", "chunk-2", "chunk-3"} for c in result)


class TestLexicalAndExcerptDeduplication:
    def test_catches_paraphrased_questions_with_same_content_words(self):
        """Card 1 vs Card 3 symptom: questions asking the same thing in different words."""
        c1 = {
            "question": (
                "Why might relying on a mutual restraint assumption lead to geopolitical danger?"
            ),
            "answer": "Because defection grants an adversary an insurmountable advantage.",
            "source_excerpt": (
                "Relying on mutual restraint assumes both hold back, which leads to danger."
            ),
        }
        c2 = {
            "question": (
                "What happens if countries rely on mutual restraint but one defects to danger?"
            ),
            "answer": "Defection creates severe security danger for the abiding nation.",
            "source_excerpt": "If one secretly continues, the abiding nation faces danger.",
        }
        assert _is_lexical_duplicate(c2, [c1]) is True

    def test_catches_overlapping_source_excerpts(self):
        """Cards quoting the same sentence or substring must be rejected as duplicates."""
        c1 = {
            "question": "What is the primary role of an acceptor in Paxos?",
            "answer": "To accept or reject proposed values based on round numbers.",
            "source_excerpt": (
                "Acceptors store state durably and respond to prepare and accept requests."
            ),
        }
        c2 = {
            "question": "How do acceptors handle proposals in the Paxos protocol?",
            "answer": "They respond to prepare requests and promise not to accept older proposals.",
            "source_excerpt": "Acceptors store state durably and respond to prepare",
        }
        assert _is_lexical_duplicate(c2, [c1]) is True

    def test_allows_distinct_questions_from_different_aspects(self):
        c1 = {
            "question": "What two properties define linearizability in distributed databases?",
            "answer": "Recency guarantee and total order of operations.",
            "source_excerpt": (
                "Linearizability requires that reads observe the most recent write."
            ),
        }
        c2 = {
            "question": "How does multi-version concurrency control reduce read contention?",
            "answer": "By allowing readers to access snapshot versions without locks.",
            "source_excerpt": ("MVCC allows concurrent reads by providing transaction snapshots."),
        }
        assert _is_lexical_duplicate(c2, [c1]) is False


@pytest.fixture()
async def factory(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'passage_test.db'}")
    await create_all_tables(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_falls_back_to_next_passage_when_first_yields_nothing(factory):
    """When the initial passage yields 0 gate-passing cards, generate() must advance
    to the next unused passage rather than returning an empty array to the user."""
    async with factory() as session:
        doc = DocumentModel(
            id="doc-1",
            title="AI Pacing",
            format="pdf",
            content_type="article",
            stage="complete",
            file_path="/tmp/doc.pdf",
        )
        session.add(doc)
        c0 = ChunkModel(
            id="c0",
            document_id="doc-1",
            text="Title header",
            token_count=2,
            page_number=1,
            chunk_index=0,
        )
        c1 = ChunkModel(
            id="c1",
            document_id="doc-1",
            text="Therefore, the key idea of first passage is level 1 pacing requires audits.",
            token_count=16,
            page_number=1,
            chunk_index=1,
        )
        c2 = ChunkModel(
            id="c2",
            document_id="doc-1",
            text="Second passage explaining enforcement and inspection of frontier clusters.",
            token_count=15,
            page_number=1,
            chunk_index=2,
        )
        session.add_all([c0, c1, c2])
        await session.commit()

        call_count = 0

        async def mock_generate(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if "first passage" in prompt.lower():
                # Hallucinated quote that fails verbatim check
                return (
                    '{"flashcards": [{"question": "What is pacing?", '
                    '"answer": "A safety model.", '
                    '"source_excerpt": "nonexistent quote not in text"}]}'
                )
            return (
                '{"flashcards": [{"question": "What does level 2 pacing require?", '
                '"answer": "Inspection of frontier clusters.", '
                '"source_excerpt": "inspection of frontier clusters."}]}'
            )

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=mock_generate)

        with (
            patch(
                "app.services.flashcard_generators._get_llm_service",
                return_value=mock_llm,
            ),
            patch(
                "app.services.flashcard._fetch_existing_embeddings",
                new=AsyncMock(return_value=([], None)),
            ),
            patch(
                "app.services.embedder.get_embedding_service",
                return_value=None,
            ),
        ):
            cards = await FlashcardService().generate(
                document_id="doc-1",
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

        assert len(cards) == 1
        assert "Inspection" in cards[0].answer
        assert call_count >= 2
