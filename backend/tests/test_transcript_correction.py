"""Misheard terms are repaired against a glossary; the model only chooses, never writes."""

import re
import uuid
from unittest.mock import MagicMock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.main import app
from app.models import ChunkModel, DocumentModel, SectionModel
from app.repos.document_repo import index_chunks_fts
from app.services.transcript_correction import (
    MIN_SIMILARITY,
    correct_transcript,
    find_candidates,
    glossary,
    judge,
    parse_choice,
)
from tests.factories import make_chunk, make_document, make_section

# Words the speech model holds whole, as its tokenizer would say.
_COMMON = {
    "you",
    "go",
    "with",
    "the",
    "approach",
    "rate",
    "it",
    "vector",
    "search",
    "senior",
    "data",
    "engineer",
    "at",
    "store",
    "in",
    "and",
    "a",
    "is",
    "of",
}


def _ordinary(word: str) -> bool:
    return word.casefold() in _COMMON


def _segments(*texts: str) -> list[dict]:
    return [{"start": float(i), "end": float(i + 1), "text": t} for i, t in enumerate(texts)]


def test_a_non_word_near_a_term_is_proposed():
    found = find_candidates(_segments("you go with the RAAG approach"), ["RAG"], ordinary=_ordinary)
    assert [(c.heard, c.term) for c in found] == [("RAAG", "RAG")]


def test_ordinary_words_terms_already_written_and_case_alone_are_not_proposed():
    segs = _segments(
        "you rate it",  # "rate" -> "RAG" scores 0.571, and the judge once accepted it
        "vector search at the Senior Data Engineer at",
        "a vector store",
    )
    terms = ["RAG", "Vector", "Senior Data Engineer"]
    assert find_candidates(segs, terms, ordinary=_ordinary) == []


def test_numbers_must_agree():
    """A judge accepted "L2, and" -> "LanceDB" at temperature 0; nobody says "two" for it."""
    segs = _segments("applied at L2, and then", "you hear something, KemiK3, the latest")
    found = find_candidates(segs, ["LanceDB", "Kimi K3"], ordinary=_ordinary)
    assert [(c.heard, c.term) for c in found] == [("KemiK3", "Kimi K3")]


def test_the_similarity_floor_brackets_its_two_cases():
    """ "rack" -> "RAG" was a real mishearing; "Dara engineering is" -> "DataEngBytes" was not."""
    rack = find_candidates(_segments("from your rack"), ["RAG"], ordinary=lambda w: False)
    dara = find_candidates(
        _segments("Dara engineering is"), ["DataEngBytes"], ordinary=lambda w: False
    )
    assert [c.score for c in rack if c.heard == "rack"] == [0.571]
    assert all(c.score < MIN_SIMILARITY for c in dara) and dara == []


def test_glossary_keeps_terms_not_titles_or_initials():
    assert glossary(
        ["Beyond Cosine Similarity: Retrieval Engineering", "AI", "LanceDB"], ["lancedb"]
    ) == ["LanceDB"]


class _FakeLLM:
    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []
        self.models: list[str | None] = []

    async def generate(
        self, prompt: str, background: bool = False, temperature=None, model=None
    ) -> str:
        assert temperature == 0
        self.models.append(model)
        self.prompts.append(prompt)
        return self.answer(prompt)


def _truthful(prompt: str) -> str:
    """Picks whichever sentence carries the glossary term."""
    term = re.search(r'glossary includes "([^"]+)"', prompt).group(1)
    a = re.search(r"^A: (.*)$", prompt, re.M).group(1)
    return "A" if term in a else "B"


async def _judged(answer) -> tuple[bool | None, _FakeLLM]:
    segs = _segments("you go with the RAAG approach")
    cand = find_candidates(segs, ["RAG"], ordinary=_ordinary)[0]
    llm = _FakeLLM(answer)
    with patch("app.services.llm.get_llm_service", return_value=llm):
        return await judge(segs, cand), llm


async def test_a_correction_must_win_in_both_orders():
    accepted, llm = await _judged(_truthful)
    assert accepted is True and len(llm.prompts) == 2


async def test_the_judge_is_the_local_model_in_every_mode():
    """Transcript sentences never leave the machine (engine-and-hosts.md)."""
    from app.services.settings_service import get_local_chat_model

    with patch(
        "app.services.settings_service.get_effective_routing", return_value=("gemini/x", "k")
    ):
        _, llm = await _judged(_truthful)
    assert llm.models == [get_local_chat_model()] * 2


async def test_a_model_that_always_picks_one_position_corrects_nothing():
    assert (await _judged(lambda _p: "A"))[0] is False
    assert (await _judged(lambda _p: "B"))[0] is False


async def test_an_unreadable_reply_is_unjudged_not_a_verdict():
    assert (await _judged(lambda _p: "Sentence A seems right"))[0] is None
    assert parse_choice(" b. ") == "B"


async def _audio_doc(factory, **fields) -> str:
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            make_document(
                **{
                    "id": doc_id,
                    "title": "Talk",
                    "format": "wav",
                    "content_type": "audio",
                    "file_path": "/x.wav",
                    "audio_duration_seconds": 60.0,
                    **fields,
                }
            )
        )
        await session.commit()
    return doc_id


async def test_a_users_fix_is_reapplied_and_the_model_pass_is_recorded(test_db):
    _, factory, _ = test_db
    doc_id = await _audio_doc(
        factory,
        transcript_vocabulary=["RAG"],
        transcript_corrections=[{"heard": "LANs-dv", "term": "LanceDB", "source": "user"}],
    )
    llm = _FakeLLM(_truthful)
    with patch("app.services.llm.get_llm_service", return_value=llm):
        out = await correct_transcript(
            doc_id,
            _segments("stores it in LANs-dv", "you go with the RAAG approach"),
            ordinary=_ordinary,
        )
    assert [s["text"] for s in out] == ["stores it in LanceDB", "you go with the RAG approach"]
    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
    assert doc.transcript_corrections == [
        {"heard": "LANs-dv", "term": "LanceDB", "source": "user", "count": 1},
        {"heard": "RAAG", "term": "RAG", "source": "model", "count": 1},
    ]


async def test_captions_get_the_users_fixes_but_no_model_pass(test_db):
    _, factory, _ = test_db
    doc_id = await _audio_doc(
        factory,
        transcript_vocabulary=["RAG"],
        transcript_corrections=[{"heard": "Lance", "term": "LanceDB", "source": "user"}],
    )
    with patch("app.services.llm.get_llm_service", side_effect=AssertionError("no model")):
        out = await correct_transcript(doc_id, _segments("RAAG on Lance"), ordinary=None)
    assert out[0]["text"] == "RAAG on LanceDB"


async def _seed_transcript(factory, doc_id: str) -> str:
    chunk_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            make_section(
                document_id=doc_id,
                heading="Segment 1 (0s-60s)",
                body="It stores vectors in LANs-dv, then LANs-dv again.",
                preview="It stores vectors in LANs-dv, then LANs-dv again.",
            )
        )
        session.add(
            make_chunk(
                id=chunk_id,
                document_id=doc_id,
                text="It stores vectors in LANs-dv, then LANs-dv again.",
                start_time=0.0,
                end_time=60.0,
            )
        )
        await index_chunks_fts(session, doc_id)
        await session.commit()
    return chunk_id


async def _fix(doc_id: str, **body):
    lancedb = MagicMock()
    embedder = MagicMock()
    embedder.encode.side_effect = lambda texts: [[0.0] * 384 for _ in texts]
    with (
        patch("app.services.embedder.get_embedding_service", return_value=embedder),
        patch("app.services.vector_store.get_lancedb_service", return_value=lancedb),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/documents/{doc_id}/transcript/corrections", json=body)
    return resp, lancedb


async def test_fixing_a_term_rewrites_text_index_and_vectors(test_db):
    _, factory, _ = test_db
    doc_id = await _audio_doc(factory)
    chunk_id = await _seed_transcript(factory, doc_id)

    resp, lancedb = await _fix(doc_id, heard="lans-dv", term="LanceDB")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"occurrences": 2, "chunks": 1, "sections": 1, "vocabulary_added": True}
    async with factory() as session:
        chunk = await session.get(ChunkModel, chunk_id)
        section = await session.scalar(
            select(SectionModel).where(SectionModel.document_id == doc_id)
        )
        doc = await session.get(DocumentModel, doc_id)
        hits = (
            await session.execute(
                text("SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH 'LanceDB'")
            )
        ).all()
    assert chunk.text == "It stores vectors in LanceDB, then LanceDB again."
    assert section.body == section.preview == chunk.text
    assert hits == [(chunk_id,)]
    (updates,), _ = lancedb.replace_chunk_text.call_args
    assert list(updates) == [chunk_id] and updates[chunk_id][0] == chunk.text
    assert doc.transcript_corrections == [
        {"heard": "lans-dv", "term": "LanceDB", "source": "user", "count": 2}
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        vocab = await client.get("/settings/transcript-vocabulary")
        detail = await client.get(f"/documents/{doc_id}")
    assert vocab.json() == {"terms": ["LanceDB"]}
    assert detail.json()["transcript_corrections"][0]["term"] == "LanceDB"


def test_replacing_chunk_text_keeps_every_other_field(tmp_path):
    import lancedb

    from app.services.vector_store import LanceDBService

    svc = LanceDBService()
    svc._db = lancedb.connect(str(tmp_path))
    row = {
        "chunk_id": str(uuid.uuid4()),
        "document_id": str(uuid.uuid4()),
        "content_type": "audio",
        "section_heading": "",
        "page": 0,
        "chunk_index": 7,
        "speaker": "",
        "text": "stores it in LANs-dv",
        "vector": [0.0] * 384,
    }
    svc.upsert_chunks([row])

    assert svc.replace_chunk_text({row["chunk_id"]: ("stores it in LanceDB", [1.0] * 384)}) == 1

    (stored,) = svc._get_table().search().where(f"chunk_id = '{row['chunk_id']}'").to_list()
    assert stored["text"] == "stores it in LanceDB" and list(stored["vector"]) == [1.0] * 384
    assert {k: stored[k] for k in ("document_id", "content_type", "chunk_index")} == {
        k: row[k] for k in ("document_id", "content_type", "chunk_index")
    }


async def test_a_fix_that_matches_nothing_changes_nothing(test_db):
    _, factory, _ = test_db
    doc_id = await _audio_doc(factory)
    await _seed_transcript(factory, doc_id)
    resp, lancedb = await _fix(doc_id, heard="Kemi K3", term="Kimi K3")
    assert resp.json() == {"occurrences": 0, "chunks": 0, "sections": 0, "vocabulary_added": False}
    lancedb.replace_chunk_text.assert_not_called()


async def test_only_a_settled_transcript_can_be_fixed(test_db):
    _, factory, _ = test_db
    importing = await _audio_doc(factory, stage="transcribing")
    book = await _audio_doc(factory, content_type="book", audio_duration_seconds=None)
    assert (await _fix(importing, heard="a", term="b"))[0].status_code == 409
    assert (await _fix(book, heard="a", term="b"))[0].status_code == 422
    assert (await _fix(str(uuid.uuid4()), heard="a", term="b"))[0].status_code == 404


async def test_personal_vocabulary_is_stored_deduplicated(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        put = await client.put(
            "/settings/transcript-vocabulary",
            json={"terms": [" LanceDB ", "lancedb", "Kimi  K3", ""]},
        )
        got = await client.get("/settings/transcript-vocabulary")
    assert put.json() == got.json() == {"terms": ["LanceDB", "Kimi K3"]}
