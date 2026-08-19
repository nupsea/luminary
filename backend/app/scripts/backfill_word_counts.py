"""Recompute `documents.word_count` for rows ingested before it was persisted.

`d14adcd` (2026-07-14) added `word_count=pd.get("word_count") or 0` to
`finalize`; before it the column was never written, so every document ingested
earlier reads 0 while holding a full set of chunks and sections. On this machine
that is 22 of 53 documents, including whole books.

Zero is not cosmetic here. Study slot distribution weights sources by word
count, and a 0-weight source is skipped entirely -- `studyDistribute.test.ts`
carries a regression named for exactly that, "DDIA-with-word_count-0". The
library, reader and document card all print "0 words" as well.

**Recomputed from the source file, through the same reader ingestion uses.**
`read_document_text` dispatches on format, so a PDF is extracted rather than
read as `%PDF-1.5 /FlateDecode`, and the count is `len(text.split())` -- the
expression in `universal_parser`, so a backfilled row equals what a fresh
ingest would write.

Not recomputed from chunks, which is the tempting shortcut and is wrong: chunks
overlap by construction (I-29), so summing across them overcounts by the length
of every seam. A document whose source file is gone keeps its 0 and is reported,
because a number nobody can reproduce is worse than an obvious gap.

Usage::

    uv run python -m app.scripts.backfill_word_counts --dry-run
    uv run python -m app.scripts.backfill_word_counts --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.database import get_session_factory
from app.models import DocumentModel
from app.services.universal_parser import read_document_text

logger = logging.getLogger(__name__)


@dataclass
class Recount:
    document_id: str
    title: str
    word_count: int
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.reason is None


def _word_count(path: Path) -> int:
    """Words as `universal_parser` counts them, from the format-aware reader."""
    return len(read_document_text(path).split())


async def recount_all(*, apply: bool) -> list[Recount]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(DocumentModel).where(
                        DocumentModel.stage == "complete",
                        (DocumentModel.word_count == 0) | (DocumentModel.word_count.is_(None)),
                    )
                )
            )
            .scalars()
            .all()
        )

        results: list[Recount] = []
        for doc in rows:
            path = Path(doc.file_path) if doc.file_path else None
            if path is None or not path.is_file():
                results.append(
                    Recount(doc.id, doc.title or "?", 0, reason="source file is gone")
                )
                continue
            try:
                count = await asyncio.to_thread(_word_count, path)
            except Exception as exc:  # noqa: BLE001 - one unreadable file must not stop the rest
                results.append(
                    Recount(doc.id, doc.title or "?", 0, reason=f"{type(exc).__name__}: {exc}")
                )
                continue
            if count <= 0:
                results.append(
                    Recount(doc.id, doc.title or "?", 0, reason="reader produced no text")
                )
                continue
            results.append(Recount(doc.id, doc.title or "?", count))
            if apply:
                doc.word_count = count

        if apply:
            await session.commit()
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="report without writing")
    group.add_argument("--apply", action="store_true", help="write the recomputed counts")
    args = ap.parse_args()

    results = asyncio.run(recount_all(apply=args.apply))
    if not results:
        print("Nothing to backfill: every complete document already has a word count.")
        return 0

    fixed = [r for r in results if r.ok]
    skipped = [r for r in results if not r.ok]

    verb = "would set" if args.dry_run else "set"
    print(f"\n{len(fixed)} document(s) {verb}:")
    for r in sorted(fixed, key=lambda r: -r.word_count):
        print(f"  {r.title[:44]:<46}{r.word_count:>12,} words")
    if skipped:
        print(f"\n{len(skipped)} left at 0 -- a count nobody can reproduce is worse than a gap:")
        for r in skipped:
            print(f"  {r.title[:44]:<46}{r.reason}")
    if args.dry_run:
        print("\nDry run. Re-run with --apply to write these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
