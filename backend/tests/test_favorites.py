import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import DocumentModel


@pytest.mark.asyncio
async def test_document_favorites(memory_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create test document directly in DB
        async with memory_db.factory() as session:
            doc = DocumentModel(
                id="doc_fav_test_1",
                title="Test Favorite Doc",
                format="pdf",
                content_type="book",
                file_path="/tmp/test.pdf",
                file_hash="abc123hash",
                word_count=500,
                page_count=2,
                stage="completed",
                tags=["science"],
                is_favorite=False,
            )
            session.add(doc)
            await session.commit()

        # Check facets before favoriting
        res_facets = await client.get("/documents/facets")
        assert res_facets.status_code == 200
        facets_data = res_facets.json()
        assert facets_data.get("favorite_count") == 0

        # Query documents with favorite=true (should be empty)
        res_fav = await client.get("/documents", params={"favorite": "true"})
        assert res_fav.status_code == 200
        assert len(res_fav.json()["items"]) == 0

        # Toggle favorite to True via PATCH
        patch_res = await client.patch("/documents/doc_fav_test_1", json={"is_favorite": True})
        assert patch_res.status_code == 200
        assert patch_res.json()["is_favorite"] is True

        # Query documents with favorite=true (should contain doc)
        res_fav = await client.get("/documents", params={"favorite": "true"})
        assert res_fav.status_code == 200
        items = res_fav.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == "doc_fav_test_1"
        assert items[0]["is_favorite"] is True

        # Check facets favorite_count updated
        res_facets = await client.get("/documents/facets")
        assert res_facets.status_code == 200
        assert res_facets.json()["favorite_count"] == 1

        # Toggle favorite back to False
        patch_res2 = await client.patch("/documents/doc_fav_test_1", json={"is_favorite": False})
        assert patch_res2.status_code == 200
        assert patch_res2.json()["is_favorite"] is False

        # Facets again 0
        res_facets = await client.get("/documents/facets")
        assert res_facets.status_code == 200
        assert res_facets.json()["favorite_count"] == 0


@pytest.mark.asyncio
async def test_note_favorites(memory_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create standard note
        res1 = await client.post("/notes", json={"content": "Standard note", "tags": ["test"]})
        assert res1.status_code == 201
        note1_id = res1.json()["id"]
        assert res1.json()["is_favorite"] is False

        # Create favorited note
        res2 = await client.post(
            "/notes",
            json={"content": "Favorite note", "tags": ["test"], "is_favorite": True},
        )
        assert res2.status_code == 201
        note2_id = res2.json()["id"]
        assert res2.json()["is_favorite"] is True

        # Groups count
        groups_res = await client.get("/notes/groups")
        assert groups_res.status_code == 200
        assert groups_res.json()["favorites_count"] == 1

        # Filter by favorite=true
        fav_notes_res = await client.get("/notes", params={"favorite": "true"})
        assert fav_notes_res.status_code == 200
        fav_notes = fav_notes_res.json()
        assert len(fav_notes) == 1
        assert fav_notes[0]["id"] == note2_id
        assert fav_notes[0]["is_favorite"] is True

        # Toggle note1 to favorite
        patch_res = await client.patch(f"/notes/{note1_id}", json={"is_favorite": True})
        assert patch_res.status_code == 200
        assert patch_res.json()["is_favorite"] is True

        # Check groups count is now 2
        groups_res = await client.get("/notes/groups")
        assert groups_res.status_code == 200
        assert groups_res.json()["favorites_count"] == 2

        # Toggle note2 to not favorite
        patch_res2 = await client.patch(f"/notes/{note2_id}", json={"is_favorite": False})
        assert patch_res2.status_code == 200
        assert patch_res2.json()["is_favorite"] is False

        # Groups count is now 1
        groups_res = await client.get("/notes/groups")
        assert groups_res.status_code == 200
        assert groups_res.json()["favorites_count"] == 1
