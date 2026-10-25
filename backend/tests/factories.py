"""Rows with every required column filled, so a test names only the fields it is about.

A schema change to these tables lands here, not in every file that builds a row. The model's
own scalar defaults are set up front, so a row reads the same before a flush as after it.
"""

from __future__ import annotations

import uuid

from app.models import ChunkModel, DocumentModel, FlashcardModel, NoteModel, SectionModel


def _row(model, values: dict):
    defaults = {
        c.key: c.default.arg
        for c in model.__table__.columns
        if c.default is not None and c.default.is_scalar
    }
    return model(**{**defaults, **values})


def _id(fields: dict) -> str:
    return fields.pop("id", None) or str(uuid.uuid4())


def make_document(**fields) -> DocumentModel:
    """A finished document; pass `stage` for one still ingesting."""
    doc_id = _id(fields)
    return _row(
        DocumentModel,
        {
            "id": doc_id,
            "title": "Test Doc",
            "format": "txt",
            "form": "prose",
            "file_path": f"/tmp/{doc_id}.txt",
            "stage": "complete",
            "tags": [],
            **fields,
        },
    )


def make_chunk(**fields) -> ChunkModel:
    return _row(ChunkModel, {"id": _id(fields), "text": "t", "chunk_index": 0, **fields})


def make_section(**fields) -> SectionModel:
    return _row(
        SectionModel,
        {"id": _id(fields), "heading": "Section", "level": 1, "section_order": 0, **fields},
    )


def make_card(**fields) -> FlashcardModel:
    return _row(
        FlashcardModel,
        {"id": _id(fields), "question": "q", "answer": "a", "source_excerpt": "", **fields},
    )


def make_note(**fields) -> NoteModel:
    return _row(NoteModel, {"id": _id(fields), "content": "note", "tags": [], **fields})
