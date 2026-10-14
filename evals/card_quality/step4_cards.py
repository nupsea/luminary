"""Step 4: write one chapter's cards through the product's chapter writer. Local only.

    DATA_DIR=<library> MEM_CAP_GB=12 scripts/capped_run.sh uv run --directory backend python \
        <repo>/evals/card_quality/step4_cards.py --doc <id> --list
    ... --doc <id> --chapter <order> --run N --out labels/step4/cards.jsonl

Reads the library and never writes it; cards are appended to --out with the window they were
written from, which is what the judge and the source check read.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


async def _main(args: argparse.Namespace) -> None:
    from app.database import get_session_factory  # noqa: PLC0415
    from app.repos.document_repo import DocumentRepo  # noqa: PLC0415
    from app.services.chapter_cards import book_for  # noqa: PLC0415
    from app.services.chapters import chapters_for_document  # noqa: PLC0415
    from app.services.embedder import get_embedding_service  # noqa: PLC0415
    from app.services.flashcard import get_llm_service  # noqa: PLC0415
    from app.services.flashcard_chapter import Passage, write_chapter_cards  # noqa: PLC0415

    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        doc = await repo.get_or_404(args.doc)
        chapters = await chapters_for_document(args.doc, doc.title, session)
        if args.list:
            for ch in chapters:
                print(f"{ch.order}\t{ch.chars}\t{ch.title}")
            return
        chapter = next(ch for ch in chapters if ch.order == args.chapter)
        book = await book_for(args.doc, session)
        rows = await repo.chunks_with_headings(chapter.section_ids)
    passages = [Passage(chunk.id, chunk.text, heading) for chunk, heading in rows]
    cards = await write_chapter_cards(
        get_llm_service(),
        None,  # the product's own routing picks the on-device writer
        get_embedding_service().encode,
        book=book,
        passages=passages,
        document_id=args.doc,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a") as out:
        for card in cards:
            row = {
                "card_id": f"s4-{uuid.uuid4().hex[:10]}",
                "run": args.run,
                "doc": doc.title,
                "genre": book.genre,
                "chapter": chapter.title,
                "question": card.question,
                "answer": card.answer,
                "source_excerpt": card.source_excerpt,
                "passage": card.window.text,
            }
            out.write(json.dumps(row) + "\n")
    print(f"{doc.title} / {chapter.title}: {len(cards)} cards, run {args.run}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--doc", required=True)
    parser.add_argument("--list", action="store_true", help="print the document's chapters")
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not args.list and (args.chapter is None or args.out is None):
        parser.error("--chapter and --out are required unless --list")
    # The writer logs each dropped card and why; yield is unreadable without it.
    logging.basicConfig(format="%(message)s")
    logging.getLogger("app.services.flashcard_chapter").setLevel(logging.INFO)
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
