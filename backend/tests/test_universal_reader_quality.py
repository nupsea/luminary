"""Integration tests verifying Universal Reader content quality across all document formats:
1. Web articles (rich Markdown, headings, images, content_source="body")
2. YouTube audio text (dialogue/speaker turns, transcripts)
3. EPUBs (fenced code blocks with language, preserved indentation, figure labels, sectioning)
4. PDFs (paginated sections, TOC hierarchy, image bindings)
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel, ImageModel, SectionModel
from app.services.parser import _epub_html_to_markdown, _split_epub_document


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig_engine, orig_factory = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, factory
    yield factory
    db_module._engine, db_module._session_factory = orig_engine, orig_factory
    get_settings.cache_clear()
    await engine.dispose()


def test_epub_markdown_conversion_preserves_rich_elements():
    """Verify EPUB HTML to Markdown preserves code blocks, inline code,
    headings, lists, tables, and figures.
    """
    html_sample = """
    <div class="chapter">
        <h1>Chapter 3: RAG with Vectors</h1>
        <p>In this chapter we implement vector search.</p>
        <pre><code class="language-python">import numpy as np

def cosine_sim(a, b):
    # Calculate similarity
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
</code></pre>
        <p>Here is the architecture diagram:</p>
        <figure>
            <img src="images/rag_pipeline.png" alt="RAG Pipeline Flow" />
            <figcaption>Figure 3-1: The end-to-end RAG indexing and retrieval loop.</figcaption>
        </figure>
        <h3>Configuration Parameters</h3>
        <table>
            <tr><th>Param</th><th>Default</th></tr>
            <tr><td>chunk_size</td><td>512</td></tr>
            <tr><td>top_k</td><td>5</td></tr>
        </table>
        <ul>
            <li>Step 1: Ingest text</li>
            <li>Step 2: Generate embeddings</li>
        </ul>
        <blockquote>Always normalize embeddings before cosine comparison.</blockquote>
    </div>
    """
    md = _epub_html_to_markdown(html_sample)

    # 1. Code fence with language and exact indentation
    assert "```python" in md
    assert "def cosine_sim(a, b):" in md
    assert "    # Calculate similarity" in md
    assert "    return np.dot(a, b)" in md

    # 2. Figure with alt description and caption
    assert "![RAG Pipeline Flow](images/rag_pipeline.png)" in md
    assert "[Figure: RAG Pipeline Flow]" in md
    assert "Figure 3-1: The end-to-end RAG indexing and retrieval loop." in md

    # 3. Headings
    assert "# Chapter 3: RAG with Vectors" in md
    assert "### Configuration Parameters" in md

    # 4. Table markdown format
    assert "| Param | Default |" in md
    assert "| chunk_size | 512 |" in md

    # 5. List items
    assert "- Step 1: Ingest text" in md
    assert "- Step 2: Generate embeddings" in md

    # 6. Blockquote
    assert "> Always normalize embeddings" in md


def test_split_epub_document_ignores_figure_headings():
    """Verify headings inside figures do not split chapters into separate sections."""
    html_content = """
    <h1>Chapter 1. Foundations</h1>
    <p>Opening remarks for the chapter.</p>
    <figure>
        <img src="fig1.png" alt="Vector Space" />
        <h6>Figure 1-1. Vector Space Embedding</h6>
    </figure>
    <p>Continuing explanation after the figure.</p>
    <h1>Chapter 2. Advanced Retrieval</h1>
    <p>Second chapter body.</p>
    """
    sections = _split_epub_document(html_content, "Fallback")
    headings = [h for h, _ in sections]
    assert headings == ["Chapter 1. Foundations", "Chapter 2. Advanced Retrieval"]
    assert "Figure 1-1. Vector Space Embedding" in sections[0][1]


@pytest.mark.asyncio
async def test_web_article_served_lossless_as_body(test_db):
    """Verify web articles serve rich markdown from sections.body with content_source='body'."""
    factory = test_db
    doc_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())
    body_markdown = (
        "# Netflix DataJunction Architecture\n\n"
        "DataJunction is a semantic layer that manages metrics across systems.\n\n"
        "```sql\n"
        "SELECT user_id, COUNT(*) as query_count\n"
        "FROM dj.metrics.active_users\n"
        "GROUP BY user_id\n"
        "```\n\n"
        "Key capabilities:\n"
        "- Centralized metric definitions\n"
        "- Consistency across downstream dashboards\n"
    )

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="DataJunction as Netflix's answer",
                format="md",
                content_type="tech_article",
                word_count=45,
                page_count=0,
                file_path=f"/tmp/{doc_id}.md",
                source_url="https://netflixtechblog.com/datajunction",
                stage="complete",
            )
        )
        session.add(
            SectionModel(
                id=sec_id,
                document_id=doc_id,
                heading="DataJunction Architecture",
                level=1,
                page_start=0,
                page_end=0,
                section_order=0,
                body=body_markdown,
                preview="DataJunction preview...",
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/sections/{doc_id}/content")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    sec = data["items"][0]
    assert sec["content_source"] == "body"
    assert "```sql\nSELECT user_id" in sec["content"]
    assert "- Centralized metric definitions" in sec["content"]


@pytest.mark.asyncio
async def test_youtube_audio_text_dialogue_served_lossless(test_db):
    """Verify YouTube and audio transcripts serve speaker turns and dialogue without degradation."""
    factory = test_db
    doc_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())
    transcript = (
        "Host: Welcome back to the podcast. Today we discuss coding agents.\n\n"
        "Guest: Thanks for having me. Autonomous agents are transforming workflows.\n\n"
        "Host: How do you evaluate the reliability of long-context models?\n\n"
        "Guest: We benchmark across multi-step execution traces."
    )

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Skill Issue: Andrej Karpathy on Code Agents",
                format="wav",
                content_type="audio",
                word_count=50,
                page_count=0,
                file_path=f"/tmp/{doc_id}.wav",
                source_url="https://www.youtube.com/watch?v=kwSVtQ7dziU",
                stage="complete",
            )
        )
        session.add(
            SectionModel(
                id=sec_id,
                document_id=doc_id,
                heading="Transcript",
                level=1,
                page_start=0,
                page_end=0,
                section_order=0,
                body=transcript,
                preview="Host: Welcome back...",
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/sections/{doc_id}/content")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    sec = data["items"][0]
    assert sec["content_source"] == "body"
    assert "Host: Welcome back" in sec["content"]
    assert "Guest: Thanks for having me" in sec["content"]


@pytest.mark.asyncio
async def test_pdf_paginated_with_images_and_sections(test_db):
    """Verify PDF documents expose section page ranges and images return associated section_id."""
    factory = test_db
    doc_id = str(uuid.uuid4())
    sec_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    image_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Chess Architecture Paper",
                format="pdf",
                content_type="paper",
                word_count=100,
                page_count=10,
                file_path=f"/tmp/{doc_id}.pdf",
                stage="complete",
            )
        )
        session.add(
            SectionModel(
                id=sec_id,
                document_id=doc_id,
                heading="Methodology",
                level=1,
                page_start=2,
                page_end=4,
                section_order=0,
                body="We evaluate search tree depths across 10,000 matches.",
                preview="We evaluate...",
            )
        )
        session.add(
            ChunkModel(
                id=chunk_id,
                document_id=doc_id,
                section_id=sec_id,
                text="Chunk text from methodology.",
                chunk_index=0,
            )
        )
        session.add(
            ImageModel(
                id=image_id,
                document_id=doc_id,
                chunk_id=chunk_id,
                page=2,
                path="figures/fig1.png",
                width=400,
                height=300,
                description="Chess search tree diagram",
                content_hash="test123hash",
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sec_resp = await client.get(f"/sections/{doc_id}/content")
        img_resp = await client.get(f"/documents/{doc_id}/images")

    assert sec_resp.status_code == 200
    sec_data = sec_resp.json()
    assert sec_data["items"][0]["page_start"] == 2
    assert sec_data["items"][0]["page_end"] == 4

    assert img_resp.status_code == 200
    img_data = img_resp.json()
    assert len(img_data["items"]) == 1
    img = img_data["items"][0]
    assert img["id"] == image_id
    assert img["section_id"] == sec_id
    assert img["description"] == "Chess search tree diagram"


@pytest.mark.asyncio
async def test_document_asset_endpoint_serves_epub_images(test_db, tmp_path):
    """Verify GET /documents/{id}/asset/{path} extracts and serves embedded EPUB images."""
    import zipfile

    factory = test_db
    doc_id = str(uuid.uuid4())
    fake_epub = tmp_path / f"{doc_id}.epub"

    # Create a minimal valid zip with an embedded image
    with zipfile.ZipFile(fake_epub, "w") as z:
        z.writestr("EPUB/images/rag_arch.png", b"\x89PNG\r\n\x1a\nfake_image_data")

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="RAG Systems Book",
                format="epub",
                content_type="book",
                word_count=500,
                page_count=0,
                file_path=str(fake_epub),
                stage="complete",
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Match by relative subpath
        resp1 = await client.get(f"/documents/{doc_id}/asset/images/rag_arch.png")
        assert resp1.status_code == 200
        assert resp1.content == b"\x89PNG\r\n\x1a\nfake_image_data"
        assert "image/png" in resp1.headers.get("content-type", "")

        # Match by base filename
        resp2 = await client.get(f"/documents/{doc_id}/asset/rag_arch.png")
        assert resp2.status_code == 200
        assert resp2.content == b"\x89PNG\r\n\x1a\nfake_image_data"

        # Missing asset returns 404
        resp3 = await client.get(f"/documents/{doc_id}/asset/nonexistent.png")
        assert resp3.status_code == 404
