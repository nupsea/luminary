"""Tests for forward-sweeping passage selection, transition skipping, and deduplication."""

import pytest

from app.models import ChunkModel
from app.services.flashcard_generators import (
    _is_lexical_duplicate,
    _passage_not_yet_used,
)


def _chunk(index: int, text: str = "A substantial text about distributed systems architecture and consensus.") -> ChunkModel:
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
        every = [_chunk(i, f"This is substantive content block number {i} discussing principles of reliable protocols.") for i in range(20)]
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
        trans = _chunk(1, "In the next section we will explore how consensus mechanisms function.")  # transition pattern
        real1 = _chunk(2, "Paxos guarantees consensus by requiring a quorum of acceptors to agree on proposed values across rounds.")
        real2 = _chunk(3, "Raft simplifies the state machine approach by using a designated leader with log replication heartbeats.")
        every = [intro, trans, real1, real2]

        preferred = [real1]
        used = {"chunk-2"}

        # Sweeping forward from chunk 2 lands at chunk 3, wrapping around to chunk 0/1.
        # But chunk 0 (<80 chars) and chunk 1 (transition) should be avoided when real chunks are available.
        result = _passage_not_yet_used(every, preferred, used)
        assert any(c.id == "chunk-3" for c in result)

    def test_wraps_around_when_at_end_of_document(self):
        """When the latest used chunk is at the end of the document, it wraps around to earlier unused content."""
        every = [_chunk(i, f"Substantive content paragraph {i} explaining core database indexing algorithms.") for i in range(5)]
        preferred = [every[4]]
        used = {"chunk-4"}

        result = _passage_not_yet_used(every, preferred, used)
        assert any(c.id in {"chunk-0", "chunk-1", "chunk-2", "chunk-3"} for c in result)


class TestLexicalAndExcerptDeduplication:
    def test_catches_paraphrased_questions_with_same_content_words(self):
        """Card 1 vs Card 3 symptom: 'Why might relying on a mutual restraint assumption between countries lead to geopolitical danger?'
        vs 'What are the consequences if countries agree to limit their own AI capabilities but one country defies that restraint?'"""
        c1 = {
            "question": "Why might relying on a mutual restraint assumption lead to severe geopolitical danger?",
            "answer": "Because defection grants an adversary an insurmountable strategic advantage.",
            "source_excerpt": "Relying on mutual restraint assumes both parties hold back, which leads to geopolitical danger if one secretly continues.",
        }
        c2 = {
            "question": "What happens if countries rely on mutual restraint but one defects leading to geopolitical danger?",
            "answer": "Defection creates severe security danger for the abiding nation.",
            "source_excerpt": "If one country secretly continues, the abiding nation faces severe danger.",
        }
        assert _is_lexical_duplicate(c2, [c1]) is True

    def test_catches_overlapping_source_excerpts(self):
        """Cards quoting the exact same sentence or substring of a sentence must be rejected as duplicates."""
        c1 = {
            "question": "What is the primary role of an acceptor in Paxos?",
            "answer": "To accept or reject proposed values based on round numbers.",
            "source_excerpt": "Acceptors store state durably and respond to prepare and accept requests from proposers.",
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
            "source_excerpt": "Linearizability requires that read operations observe the most recent write in a global real-time order.",
        }
        c2 = {
            "question": "How does multi-version concurrency control reduce read contention?",
            "answer": "By allowing readers to access snapshot versions without acquiring write locks.",
            "source_excerpt": "MVCC allows concurrent reads by providing transaction snapshots rather than exclusive locks.",
        }
        assert _is_lexical_duplicate(c2, [c1]) is False


@pytest.fixture()
async def factory(tmp_path):
    from app.database import make_engine
    from app.db_init import create_all_tables
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'passage_test.db'}")
    await create_all_tables(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_falls_back_to_next_passage_when_first_yields_nothing(factory):
    """When the initial passage yields 0 gate-passing cards, generate() must advance
    to the next unused passage rather than returning an empty array to the user."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.models import DocumentModel
    from app.services.flashcard import FlashcardService

    async with factory() as session:
        doc = DocumentModel(id="doc-1", title="AI Pacing", format="pdf", content_type="article", stage="complete", file_path="/tmp/doc.pdf")
        session.add(doc)
        c0 = ChunkModel(id="c0", document_id="doc-1", text="Title header", token_count=2, page_number=1, chunk_index=0)
        c1 = ChunkModel(
            id="c1",
            document_id="doc-1",
            text="Therefore, the key idea of first passage is that level 1 pacing requires safety audits.",
            token_count=16,
            page_number=1,
            chunk_index=1,
        )
        c2 = ChunkModel(
            id="c2",
            document_id="doc-1",
            text="Second passage explaining enforcement mechanisms and bilateral inspection of frontier clusters.",
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
            if "First passage" in prompt:
                # Hallucinated quote that fails verbatim check
                return '{"flashcards": [{"question": "What is pacing?", "answer": "A safety model.", "source_excerpt": "nonexistent quote not in text"}]}'
            return '{"flashcards": [{"question": "What does level 2 pacing require?", "answer": "Bilateral inspection of frontier clusters.", "source_excerpt": "bilateral inspection of frontier clusters."}]}'

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=mock_generate)

        with patch("app.services.flashcard_generators._get_llm_service", return_value=mock_llm), \
             patch("app.services.flashcard._fetch_existing_embeddings", new=AsyncMock(return_value=([], None))), \
             patch("app.services.embedder.get_embedding_service", return_value=None):
            cards = await FlashcardService().generate(
                document_id="doc-1",
                scope="full",
                section_heading=None,
                count=1,
                session=session,
            )

        assert len(cards) == 1
        assert "Bilateral inspection" in cards[0].answer
        assert call_count >= 2
