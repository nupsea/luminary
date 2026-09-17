"""O'Reilly Learning integration endpoints.

Enables cookie validation, book preview, and automated ingestion of O'Reilly
books into Luminary's local-first knowledge graph.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.oreilly_service import (
    OreillyClient,
    delete_oreilly_cookies,
    get_oreilly_cookies,
    parse_cookies_input,
    parse_oreilly_book_id,
    save_oreilly_cookies,
)
from app.workflows.oreilly_ingestion import start_oreilly_ingestion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oreilly", tags=["oreilly"])


class OreillyCookieRequest(BaseModel):
    cookies: Any = Field(
        ...,
        description="Cookie input: raw JSON, parsed JSON array/object, or Cookie header",
    )


class OreillyPreviewRequest(BaseModel):
    url: str = Field(..., description="O'Reilly book URL, view URL, or ISBN/identifier")


class OreillyIngestRequest(BaseModel):
    url: str = Field(..., description="O'Reilly book URL, view URL, or ISBN/identifier")
    selected_chapters: list[int] | None = Field(
        None, description="Optional chapter indices to ingest (for chapter-by-chapter study)"
    )


@router.get("/status")
async def get_oreilly_status() -> dict[str, Any]:
    """Check whether O'Reilly subscription cookies are configured and active."""
    cookies = get_oreilly_cookies()
    if not cookies:
        return {"configured": False, "valid": False, "user": None}

    client = OreillyClient(cookies)
    is_valid, user_or_err = await asyncio.to_thread(client.validate_session)
    return {
        "configured": True,
        "valid": is_valid,
        "user": user_or_err if is_valid else None,
        "error": user_or_err if not is_valid else None,
    }


@router.post("/cookies")
async def set_oreilly_cookies(body: OreillyCookieRequest) -> dict[str, Any]:
    """Validate and save O'Reilly subscription cookies."""
    cookies = parse_cookies_input(body.cookies)
    if not cookies:
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not find valid cookies in the provided text. "
                "Make sure you pasted cookie JSON or a Cookie header string."
            ),
        )

    client = OreillyClient(cookies)
    is_valid, user_or_err = await asyncio.to_thread(client.validate_session)
    if not is_valid:
        raise HTTPException(
            status_code=401,
            detail=(
                f"Could not authenticate with O'Reilly using those cookies: {user_or_err}. "
                "Make sure you are logged in to learning.oreilly.com."
            ),
        )

    save_oreilly_cookies(cookies)
    return {
        "status": "ok",
        "valid": True,
        "user": user_or_err,
        "cookie_count": len(cookies),
    }


@router.delete("/cookies")
async def remove_oreilly_cookies() -> dict[str, str]:
    """Remove stored O'Reilly cookies."""
    delete_oreilly_cookies()
    return {"status": "ok"}


@router.post("/preview")
async def preview_oreilly_book(body: OreillyPreviewRequest) -> dict[str, Any]:
    """Preview metadata and chapter list for an O'Reilly book without ingesting."""
    book_id = parse_oreilly_book_id(body.url)
    if not book_id:
        raise HTTPException(
            status_code=400,
            detail="Could not extract an O'Reilly book identifier or ISBN from the provided URL.",
        )

    client = OreillyClient()
    if not client.is_configured():
        raise HTTPException(
            status_code=401,
            detail=(
                "O'Reilly subscription cookies not configured. "
                "Please connect your O'Reilly account first."
            ),
        )

    try:
        meta = await asyncio.to_thread(client.fetch_book_metadata, book_id)
        chapters = await asyncio.to_thread(client.fetch_chapter_list, book_id)
    except Exception as exc:
        logger.exception("Failed to preview O'Reilly book %s", book_id)
        raise HTTPException(status_code=500, detail=f"Failed to fetch book preview: {exc}") from exc

    return {
        "book_id": book_id,
        "title": meta.get("title"),
        "authors": meta.get("authors"),
        "description": meta.get("description"),
        "cover_url": meta.get("cover_url"),
        "chapter_count": len(chapters),
        "chapters": [
            {
                "index": i,
                "title": ch.get("title"),
                "minutes_required": ch.get("minutes_required"),
            }
            for i, ch in enumerate(chapters)
        ],
    }


@router.post("/ingest")
async def ingest_oreilly_book(
    body: OreillyIngestRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Download an O'Reilly book as an EPUB and ingest with local LLM processing."""
    return await start_oreilly_ingestion(
        url=body.url,
        settings=settings,
        selected_chapters=body.selected_chapters,
    )
