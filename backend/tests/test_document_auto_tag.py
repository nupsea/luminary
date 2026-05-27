"""Document auto-tagging (2D.1)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import (
    DocumentModel,
    DocumentTagIndexModel,
    DocumentTagProvenanceModel,
)
from app.services import document_tagger as _doc_tagger_module
from app.services.naming import normalize_tag_slug


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def _make_doc(doc_id: str, title: str = "A book about cells") -> DocumentModel:
    return DocumentModel(
        id=doc_id,
        title=title,
        format="txt",
        content_type="book",
        word_count=100,
        page_count=1,
        file_path="/tmp/x.txt",
        stage="complete",
        tags=[],
    )


class _FakeTagger:
    """Stand-in for DocumentTaggerService that yields a scripted suggestion list."""

    def __init__(self, sequence: list[list[str]]):
        self._sequence = list(sequence)

    async def suggest_tags(self, title: str, summary: str, excerpt: str) -> list[str]:
        if self._sequence:
            return self._sequence.pop(0)
        return []


@pytest.mark.anyio
async def test_retag_endpoint_normalizes_dedupes_and_writes_provenance(test_db, monkeypatch):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    # Two raw suggestions normalize to the same slug; the third is distinct.
    fake = _FakeTagger([["Machine Learning", "machine_learning", "Python"]])
    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/retag")
        assert r.status_code == 200
        assert r.json()["added"] == 2

    async with factory() as s:
        # Index rows present and slugs are normalized.
        idx = {
            row[0]
            for row in (
                await s.execute(
                    select(DocumentTagIndexModel.tag_full).where(
                        DocumentTagIndexModel.document_id == doc_id
                    )
                )
            ).all()
        }
        assert idx == {"machine-learning", "python"}

        # Provenance rows present and marked 'auto'.
        prov = (
            await s.execute(
                select(
                    DocumentTagProvenanceModel.tag_full,
                    DocumentTagProvenanceModel.source,
                ).where(DocumentTagProvenanceModel.document_id == doc_id)
            )
        ).all()
        assert {(t, src) for t, src in prov} == {
            ("machine-learning", "auto"),
            ("python", "auto"),
        }


@pytest.mark.anyio
async def test_retag_is_idempotent(test_db, monkeypatch):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    fake = _FakeTagger([["python"], ["python"]])
    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r1 = await c.post(f"/documents/{doc_id}/retag")
        r2 = await c.post(f"/documents/{doc_id}/retag")
        assert r1.json()["added"] == 1
        assert r2.json()["added"] == 0


@pytest.mark.anyio
async def test_retag_does_not_overwrite_manual_tags(test_db, monkeypatch):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # User sets manual tags first.
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["history"]})

        fake = _FakeTagger([["python"]])
        monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: fake)

        await c.post(f"/documents/{doc_id}/retag")

    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        assert "history" in doc.tags
        assert "python" in doc.tags


@pytest.mark.anyio
async def test_retag_swallows_tagger_failure(test_db, monkeypatch):
    """A tagger that raises must not surface a 500; the endpoint stays 200/added=0."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    class _BoomTagger:
        async def suggest_tags(self, *a, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", _BoomTagger)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/retag")
        assert r.status_code == 200
        assert r.json()["added"] == 0


@pytest.mark.anyio
async def test_entity_reinforcement_off_when_flag_false(test_db, monkeypatch):
    """When AUTO_TAG_USE_ENTITIES is False the entity helper must not be called."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    fake = _FakeTagger([["python"]])
    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: fake)

    calls: list[str] = []

    def _spy(*a, **kw):
        calls.append("hit")
        return ["should-not-leak"]

    monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", _spy)

    from app.config import Settings as _S

    monkeypatch.setattr(
        _doc_tagger_module,
        "get_settings",
        lambda: _S(AUTO_TAG_USE_ENTITIES=False),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/retag")
        assert r.status_code == 200

    assert calls == []
    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        assert doc.tags == ["python"]


@pytest.mark.anyio
async def test_entity_reinforcement_appends_when_enabled(test_db, monkeypatch):
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    fake = _FakeTagger([["python"]])
    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: fake)
    monkeypatch.setattr(
        _doc_tagger_module,
        "_fetch_entity_tags",
        lambda _doc, _min_mentions, **_kw: ["Alan Turing", "python", "Cambridge"],
    )

    # Flip the setting on for this test (mirrors the default but explicit).
    from app.config import Settings as _S

    monkeypatch.setattr(
        _doc_tagger_module,
        "get_settings",
        lambda: _S(AUTO_TAG_USE_ENTITIES=True),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/retag")
        assert r.status_code == 200
        # python (LLM) + alan-turing + cambridge. Entity 'python' dedupes against LLM 'python'.
        assert r.json()["added"] == 3

    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        assert set(doc.tags) == {"python", "alan-turing", "cambridge"}


@pytest.mark.anyio
async def test_entity_path_runs_with_no_llm_suggestions(test_db, monkeypatch):
    """Entity tags land even when the LLM tagger returns []."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: _FakeTagger([[]]))
    monkeypatch.setattr(
        _doc_tagger_module,
        "_fetch_entity_tags",
        lambda _doc, _min, **_kw: ["Turing", "Bletchley Park"],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/documents/{doc_id}/retag")
        assert r.json()["added"] == 2

    async with factory() as s:
        provs = (
            await s.execute(
                select(
                    DocumentTagProvenanceModel.tag_full,
                    DocumentTagProvenanceModel.tagger_version,
                ).where(DocumentTagProvenanceModel.document_id == doc_id)
            )
        ).all()
        # Both tags should carry the entity tagger_version, not the LLM one.
        assert {(t, v) for t, v in provs} == {
            ("turing", "entity-1"),
            ("bletchley-park", "entity-1"),
        }


@pytest.mark.anyio
async def test_provenance_distinguishes_llm_from_entity(test_db, monkeypatch):
    """Mixed run: LLM and entity tags get distinct tagger_version rows."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    monkeypatch.setattr(
        _doc_tagger_module, "get_document_tagger", lambda: _FakeTagger([["python"]])
    )
    monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", lambda _d, _m, **_kw: ["Turing"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/documents/{doc_id}/retag")

    async with factory() as s:
        provs = (
            await s.execute(
                select(
                    DocumentTagProvenanceModel.tag_full,
                    DocumentTagProvenanceModel.tagger_version,
                ).where(DocumentTagProvenanceModel.document_id == doc_id)
            )
        ).all()
        assert {(t, v) for t, v in provs} == {
            ("python", "doc-1"),
            ("turing", "entity-1"),
        }


@pytest.mark.anyio
async def test_retag_all_queues_complete_docs_only(test_db, monkeypatch):
    """POST /documents/retag-all schedules background enrichment per complete doc."""
    _, factory = test_db
    done_a = str(uuid.uuid4())
    done_b = str(uuid.uuid4())
    pending = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(done_a))
        s.add(_make_doc(done_b))
        # An in-flight doc is excluded from the queue.
        p = _make_doc(pending)
        p.stage = "parsing"
        s.add(p)
        await s.commit()

    seen: list[str] = []

    async def _spy(doc_id: str) -> int:
        seen.append(doc_id)
        return 0

    monkeypatch.setattr(
        "app.routers.documents.enrich_document_tags", _spy
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/documents/retag-all")
        assert r.status_code == 200
        assert r.json()["queued"] == 2

    # The background tasks were scheduled with asyncio.create_task; give the
    # event loop a tick so the spy records its calls.
    import asyncio as _asyncio

    await _asyncio.sleep(0.05)

    assert set(seen) == {done_a, done_b}
    assert pending not in seen


@pytest.mark.anyio
async def test_entity_quality_gate_drops_noise(test_db, monkeypatch):
    """Each noise shape from the real corpus -- stoplist, slug shape, NER
    artifacts -- must be rejected; real concept tags survive untouched.
    """
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: _FakeTagger([[]]))
    monkeypatch.setattr(
        _doc_tagger_module,
        "_fetch_entity_tags",
        lambda _d, _m, **_kw: [
            # Real concept tags (survive)
            "Apache Iceberg", "data-lakehouse", "Delta Lake",
            # Stoplist hits (rejected)
            "bob", "alice", "users", "user1", "admin-user", "friend",
            "viewer", "member", "thought", "dream",
            # NER artifacts -- normalizer + min-length reject
            "r-.-name", "ne-.-role", "person's-name",
            # URL/template noise -- normalizer strips, min-length keeps short ones out
            "s3:/...",  # -> 's3', passes min-length 2, but useful enough that we let it through
            # All-digit slug (port number lookalike) -> rejected
            "9083",
        ],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/documents/{doc_id}/retag")

    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        kept = set(doc.tags)

    assert "apache-iceberg" in kept
    assert "data-lakehouse" in kept
    assert "delta-lake" in kept
    # All noise shapes gone:
    for noise in {
        "bob", "alice", "users", "user1", "admin-user", "friend",
        "viewer", "member", "thought", "dream",
        "9083",
    }:
        assert noise not in kept, f"stoplist/digit gate let {noise!r} through"
    # Normalizer rejections (these slugs don't survive normalization to a
    # meaningful form -- they collapse to empty or single-letter scraps):
    for artifact_in, _expected_dropped in [
        ("r-.-name", None), ("ne-.-role", None), ("person's-name", None),
    ]:
        assert normalize_tag_slug(artifact_in) not in kept


@pytest.mark.anyio
async def test_llm_path_is_not_filtered_by_stoplist(test_db, monkeypatch):
    """The LLM is prompt-steered; running its output through TAG_STOPLIST
    would chew up legitimate prompt-shaped topics. Only the entity path filters.
    """
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    # 'user-experience' contains 'user' but is a real topic. The leaf-segment
    # stoplist check would only match bare 'user', so this should survive.
    # Bare 'user' from the LLM IS preserved (LLM path bypasses the gate) --
    # arguable, but the LLM has 5-cap so the cost is bounded.
    monkeypatch.setattr(
        _doc_tagger_module,
        "get_document_tagger",
        lambda: _FakeTagger([["user-experience", "machine-learning"]]),
    )
    monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", lambda _d, _m, **_kw: [])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/documents/{doc_id}/retag")

    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        assert "user-experience" in doc.tags
        assert "machine-learning" in doc.tags


@pytest.mark.anyio
async def test_prune_auto_endpoint_removes_only_failing_entity_tags(test_db, monkeypatch):
    """The prune endpoint removes any auto-tag that fails the quality gate
    (entity-1 or doc-1). Manual tags survive even if they would fail.
    """
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    # Seed: LLM ('python'), entity ('iceberg' real + 'bob' noise + 'friend' noise),
    # plus a manual tag ('users' -- would fail the gate if it were entity-sourced).
    monkeypatch.setattr(
        _doc_tagger_module,
        "get_document_tagger",
        lambda: _FakeTagger([["python"]]),
    )
    monkeypatch.setattr(
        _doc_tagger_module, "_fetch_entity_tags", lambda _d, _m, **_kw: []
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Manual write first so 'users' has manual provenance via db_init backfill,
        # then we'll patch entity rows in directly to set up the test.
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["users"]})
        await c.post(f"/documents/{doc_id}/retag")  # adds 'python' as doc-1

    # Inject entity rows directly so we don't have to mock the threshold logic.
    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        doc.tags = doc.tags + ["iceberg", "bob", "friend"]
        from app.services.notes_service import sync_document_tag_index

        await sync_document_tag_index(doc_id, doc.tags, s)
        from datetime import UTC
        from datetime import datetime as _dt

        from app.models import DocumentTagProvenanceModel as _Prov

        now = _dt.now(UTC)
        for slug in ["iceberg", "bob", "friend"]:
            s.add(_Prov(
                document_id=doc_id, tag_full=slug,
                source="auto", tagger_version="entity-1", created_at=now,
            ))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/documents/tags/prune-auto")
        assert r.status_code == 200
        body = r.json()
        # 'bob' and 'friend' fail the new gate. 'iceberg' stays.
        assert body["pruned"] == 2
        assert body["docs_touched"] == 1

    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        # Manual 'users' survives (manual provenance, not entity-1).
        # LLM 'python' survives (doc-1 provenance, not entity-1).
        # Real entity 'iceberg' survives.
        # Noise 'bob', 'friend' pruned.
        assert "users" in doc.tags
        assert "python" in doc.tags
        assert "iceberg" in doc.tags
        assert "bob" not in doc.tags
        assert "friend" not in doc.tags


@pytest.mark.anyio
async def test_prune_sweeps_failing_llm_tag(test_db, monkeypatch):
    """An LLM-sourced tag that fails the new gate (e.g., 'dream' in the stoplist)
    is also pruned -- the user asked us to keep the bar high across sources.
    """
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    # Bypass the runtime gate so we can seed an LLM row that would now fail.
    monkeypatch.setattr(
        _doc_tagger_module, "is_acceptable_auto_tag", lambda *_a, **_kw: True
    )
    monkeypatch.setattr(
        _doc_tagger_module,
        "get_document_tagger",
        lambda: _FakeTagger([["dream"]]),
    )
    monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", lambda _d, _m, **_kw: [])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/documents/{doc_id}/retag")

    # Restore real gate; prune should now sweep 'dream'.
    monkeypatch.undo()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/documents/tags/prune-auto")
        assert r.json()["pruned"] == 1

    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        assert "dream" not in doc.tags


@pytest.mark.anyio
async def test_tech_book_excludes_person_and_place(test_db, monkeypatch):
    """A tech_book content_type triggers CONCEPT-only entity selection."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        doc = _make_doc(doc_id)
        doc.content_type = "tech_book"
        s.add(doc)
        await s.commit()

    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: _FakeTagger([[]]))
    captured: dict = {}

    def _spy(doc_id, min_mentions, allowed_types=("CONCEPT",), limit=None):
        captured["allowed_types"] = allowed_types
        return []

    monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", _spy)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/documents/{doc_id}/retag")

    assert captured["allowed_types"] == ("CONCEPT",)


@pytest.mark.anyio
async def test_narrative_book_includes_person_and_place(test_db, monkeypatch):
    """A plain book content_type opens the gate to PERSON and PLACE entities."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        doc = _make_doc(doc_id)
        doc.content_type = "book"  # narrative-leaning default
        s.add(doc)
        await s.commit()

    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: _FakeTagger([[]]))
    captured: dict = {}

    def _spy(doc_id, min_mentions, allowed_types=("CONCEPT",), limit=None):
        captured["allowed_types"] = allowed_types
        return []

    monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", _spy)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/documents/{doc_id}/retag")

    assert set(captured["allowed_types"]) == {"PERSON", "PLACE", "CONCEPT"}


@pytest.mark.anyio
async def test_prune_drops_entity_tags_no_longer_in_graph(test_db, monkeypatch):
    """An entity-1 row whose entity wouldn't be returned by the current graph
    query (e.g. PERSON for a tech_book after the rules tightened) is pruned.
    """
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        doc = _make_doc(doc_id)
        doc.content_type = "tech_book"
        doc.tags = ["data-lakehouse", "raghu-ramakrishnan"]
        s.add(doc)
        # Seed both as entity-1 (the legacy state where PERSON was allowed).
        await s.flush()
        from app.services.notes_service import sync_document_tag_index

        await sync_document_tag_index(doc_id, doc.tags, s)
        from datetime import UTC
        from datetime import datetime as _dt

        from app.models import DocumentTagProvenanceModel as _Prov

        now = _dt.now(UTC)
        for slug in ["data-lakehouse", "raghu-ramakrishnan"]:
            s.add(_Prov(
                document_id=doc_id, tag_full=slug,
                source="auto", tagger_version="entity-1", created_at=now,
            ))
        await s.commit()

    # Today's graph rules would only return 'data-lakehouse' (CONCEPT) for a
    # tech_book; 'raghu-ramakrishnan' (PERSON) is now excluded.
    def _fresh_graph(doc_id, min_mentions, allowed_types=("CONCEPT",), limit=None):
        # The prune passes allowed_types based on content_type; honour it.
        if allowed_types == ("CONCEPT",):
            return ["data-lakehouse"]
        return ["data-lakehouse", "Raghu Ramakrishnan"]

    monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", _fresh_graph)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/documents/tags/prune-auto")
        assert r.status_code == 200
        assert r.json()["pruned"] == 1

    async with factory() as s:
        doc = (
            await s.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one()
        assert "data-lakehouse" in doc.tags
        assert "raghu-ramakrishnan" not in doc.tags


@pytest.mark.anyio
async def test_prune_handles_orphaned_index_row(test_db):
    """An index row with no JSON-column or provenance backing (legacy state)
    gets cleaned up without touching anything else.
    """
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        # Directly insert an orphan index row for a stoplisted slug.
        s.add(DocumentTagIndexModel(
            document_id=doc_id, tag_full="bob", tag_root="bob", tag_parent="",
        ))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/documents/tags/prune-auto")
        assert r.json()["pruned"] == 1

    async with factory() as s:
        remaining = (
            await s.execute(
                select(DocumentTagIndexModel.tag_full).where(
                    DocumentTagIndexModel.document_id == doc_id
                )
            )
        ).all()
        assert remaining == []


@pytest.mark.anyio
async def test_prune_auto_is_idempotent(test_db, monkeypatch):
    """A second prune call after rules have stabilised returns pruned=0."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: _FakeTagger([[]]))
    monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", lambda _d, _m, **_kw: ["bob"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # Force-bypass the runtime gate so we can seed a row that the prune
        # will then sweep.
        monkeypatch.setattr(
            _doc_tagger_module, "is_acceptable_auto_tag", lambda *_a, **_kw: True
        )
        await c.post(f"/documents/{doc_id}/retag")
        # Reset to real gate for the prune itself.
        monkeypatch.undo()
        monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: _FakeTagger([[]]))
        monkeypatch.setattr(_doc_tagger_module, "_fetch_entity_tags", lambda _d, _m, **_kw: [])

        r1 = await c.post("/documents/tags/prune-auto")
        r2 = await c.post("/documents/tags/prune-auto")
        assert r1.json()["pruned"] == 1
        assert r2.json()["pruned"] == 0


@pytest.mark.anyio
async def test_removing_doc_tag_clears_provenance(test_db, monkeypatch):
    """PATCH that drops a tag also clears its provenance row."""
    _, factory = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(_make_doc(doc_id))
        await s.commit()

    fake = _FakeTagger([["python", "physics"]])
    monkeypatch.setattr(_doc_tagger_module, "get_document_tagger", lambda: fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await c.post(f"/documents/{doc_id}/retag")
        # User keeps only one of the suggested tags.
        await c.patch(f"/documents/{doc_id}/tags", json={"tags": ["python"]})

    async with factory() as s:
        prov = {
            row[0]
            for row in (
                await s.execute(
                    select(DocumentTagProvenanceModel.tag_full).where(
                        DocumentTagProvenanceModel.document_id == doc_id
                    )
                )
            ).all()
        }
        assert prov == {"python"}
