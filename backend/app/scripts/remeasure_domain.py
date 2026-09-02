"""Measure `domain` and `register` for documents that were never read for them.

Two populations need this:

- Rows written before the domain was measured at all. `classify_node` used to
  set `is_technical = content_type in TECHNICAL_CONTENT_TYPES`, which answered
  for every type and so wrote a hard False for every paper and book. That is
  what stripped the technical entity types from "Attention Is All You Need"
  (70 entities extracted, 0 technical) and `d2l_dive_into_deep_learning`
  (165, 0).
- Rows whose probe returned nothing. The call failed or the model did not
  answer yes/no, and nothing retried. Those carry a null and stay null until
  this runs.

Only fills what it can establish. A probe that fails again leaves the row null,
because an unanswered question is not a finding.

**This does not re-extract entities.** A document whose domain changes needs
`reindex_entities.py` afterwards to actually gain the entity types it was
denied; this script prints the ids to pass it.

    cd backend && uv run python -m app.scripts.remeasure_domain [--apply]

Without --apply it reports what it would change and writes nothing.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import select, update

from app.database import get_session_factory
from app.models import DocumentModel
from app.services.content_classifier import classify_form
from app.types import TECHNICAL_CONTENT_TYPES, DocumentProfile
from app.workflows.ingestion_nodes._shared import (
    detect_register,
    detect_technical_content,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("remeasure_domain")

# Media text lives in chunks, not in the file: the transcript is produced during
# ingestion and the .wav on disk cannot be read back as text.
_MEDIA = ("audio", "video")


async def _read(doc: DocumentModel, session) -> tuple[str, list[dict], int, str]:
    """(text, sections, word_count, extension) -- everything the measurements need.

    Media text lives in chunks: the transcript is produced during ingestion and
    the .wav on disk cannot be read back as text. Everything else is parsed the
    way ingestion parses it, because `classify_form` reads the section headings.
    """
    if doc.content_type in _MEDIA:
        from app.models import ChunkModel  # noqa: PLC0415

        rows = await session.execute(
            select(ChunkModel.text)
            .where(ChunkModel.document_id == doc.id)
            .order_by(ChunkModel.chunk_index)
            .limit(200)
        )
        text = " ".join(r[0] for r in rows.all())
        return text, [], len(text.split()), Path(doc.file_path).suffix.lstrip(".")
    try:
        from app.services.parser import DocumentParser  # noqa: PLC0415

        path = Path(doc.file_path)
        parsed = await asyncio.to_thread(
            DocumentParser().parse, path, path.suffix.lstrip(".")
        )
        sections = [{"heading": s.heading} for s in parsed.sections]
        return parsed.raw_text, sections, parsed.word_count, path.suffix.lstrip(".")
    except Exception as exc:  # noqa: BLE001
        logger.warning("  could not read %s: %s", doc.title, type(exc).__name__)
        return "", [], doc.word_count or 0, ""


async def main(apply: bool) -> int:
    factory = get_session_factory()
    changed: list[tuple[str, str, str | None, str | None]] = []
    undecided: list[str] = []

    async with factory() as session:
        docs = (await session.execute(select(DocumentModel))).scalars().all()

        for doc in docs:
            before = DocumentProfile.from_legacy(doc.content_type, doc.is_technical).domain
            text, sections, word_count, ext = await _read(doc, session)
            has_text = bool(text.strip())

            # Measured from structure, never mapped from content_type: the map
            # reaches `reference` only through `tech_book`, so a non-technical
            # manual could not be one.
            form = (
                classify_form(text, sections, word_count, ext, Path(doc.file_path).name)
                if has_text
                else doc.form
            )

            # A type that names the subject needs no probe; the register never
            # follows from the type, so it is always read.
            if doc.content_type in TECHNICAL_CONTENT_TYPES:
                measured: bool | None = True
            else:
                measured = await detect_technical_content(text) if has_text else None
            register = (
                doc.register or (await detect_register(text) if has_text else None)
            )

            after = DocumentProfile.from_legacy(doc.content_type, measured).domain
            if after == before and register == doc.register and form == doc.form:
                if after is None or register is None:
                    undecided.append(doc.title)
                continue

            changed.append((doc.id, doc.title, before, after))
            logger.info(
                "  %-38s form %s -> %s   domain %s -> %s   register %s -> %s",
                doc.title[:37],
                doc.form or "null",
                form or "null",
                before or "null",
                after or "null",
                doc.register or "null",
                register or "null",
            )
            if apply:
                values: dict[str, object] = {"is_technical": measured, "domain": after}
                if register is not None:
                    values["register"] = register
                if form is not None:
                    values["form"] = form
                await session.execute(
                    update(DocumentModel).where(DocumentModel.id == doc.id).values(**values)
                )
        if apply:
            await session.commit()

    logger.info("")
    verb = "changed" if apply else "would change"
    logger.info("%d document(s) %s", len(changed), verb)
    if undecided:
        logger.info("%d still undecided (the probe did not answer): %s",
                    len(undecided), ", ".join(t[:30] for t in undecided[:5]))
    if changed and apply:
        logger.info("")
        logger.info("Entities are NOT re-extracted by this script. To apply the new")
        logger.info("entity types to the documents above:")
        # Only a document that gained the technical domain has entity types it
        # was previously denied; the others already extracted what they get.
        for doc_id, title, before, after in changed:
            if after != "technical" or before == "technical":
                continue
            logger.info("  # %s", title[:60])
            logger.info(
                "  uv run python -m app.scripts.reindex_entities"
                " --document-id %s --rebuild-graph",
                doc_id,
            )
    elif changed:
        logger.info("Re-run with --apply to write these.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the measurements")
    sys.exit(asyncio.run(main(ap.parse_args().apply)))
