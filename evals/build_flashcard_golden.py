"""Build the flashcard golden by sampling passages, deterministically.

A flashcard golden row is a source passage and how many cards to ask for. The
eval judges the generated cards against that passage, so the passage IS the
ground truth -- nothing here needs a model to author it, and nothing here can be
overfitted to one. That is why this dataset is sampled rather than generated,
unlike the retrieval goldens, whose questions do need authoring.

Selection rules, all mechanical so a re-run reproduces the file:

  * one document at a time, balanced across content types, because cards from a
    manual and cards from a novel fail differently and a dataset drawn from one
    kind measures one kind;
  * the middle 80% of a document's chunk sequence, which drops front matter,
    licence blocks and indexes without a keyword list that would encode one
    corpus's furniture;
  * chunks between 400 and 1500 characters -- a heading has nothing to ask
    about, and a very long chunk lets a weak model pick the easy sentence;
  * a fixed seed.

Usage::

    uv run --project backend python evals/build_flashcard_golden.py --per-kind 7
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GOLDEN_DIR = REPO_ROOT / "evals" / "golden"

MIN_CHARS = 400
MAX_CHARS = 1500
# Front and back matter live at the ends of a document's chunk sequence.
EDGE_TRIM = 0.10
SEED = 20260815


def _documents(con: sqlite3.Connection) -> list[tuple[str, str, str, str]]:  # noqa: D401
    return con.execute(
        "SELECT id, title, content_type, file_path FROM documents "
        "WHERE stage = 'complete' AND content_type != 'audio' "
        "ORDER BY id"
    ).fetchall()


def _passages(con: sqlite3.Connection, doc_id: str) -> list[str]:
    rows = con.execute(
        "SELECT text FROM chunks WHERE document_id = ? ORDER BY chunk_index", (doc_id,)
    ).fetchall()
    texts = [r[0] for r in rows if r[0]]
    if len(texts) < 10:
        return []
    lo = int(len(texts) * EDGE_TRIM)
    hi = int(len(texts) * (1 - EDGE_TRIM))
    return [t for t in texts[lo:hi] if MIN_CHARS <= len(t) <= MAX_CHARS]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(REPO_ROOT / ".luminary/luminary.db"))
    ap.add_argument("--per-kind", type=int, default=7, help="passages per content type")
    ap.add_argument("--cards-per-passage", type=int, default=3)
    ap.add_argument("--out", default=str(GOLDEN_DIR / "flashcards.jsonl"))
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rng = random.Random(SEED)

    by_kind: dict[str, list[tuple[str, str, str]]] = {}
    for doc_id, title, kind, path in _documents(con):
        for text in _passages(con, doc_id):
            by_kind.setdefault(kind, []).append((title, doc_id, path, text))

    rows: list[dict] = []
    for kind in sorted(by_kind):
        pool = by_kind[kind]
        # Spread across documents within a kind rather than taking whatever the
        # longest document happens to contribute.
        by_doc: dict[str, list[tuple[str, str, str, str]]] = {}
        for item in pool:
            by_doc.setdefault(item[0], []).append(item)
        titles = sorted(by_doc)
        rng.shuffle(titles)
        picked: list[tuple[str, str, str, str]] = []
        round_index = 0
        while len(picked) < args.per_kind and titles:
            progressed = False
            for title in titles:
                candidates = by_doc[title]
                if round_index >= len(candidates):
                    continue
                picked.append(rng.choice(candidates))
                progressed = True
                if len(picked) >= args.per_kind:
                    break
            if not progressed:
                break
            round_index += 1

        for title, doc_id, path, text in picked:
            rows.append(
                {
                    "question": f"Generate flashcards from a {kind} passage ({title})",
                    # The document is named by id, not by path: these passages
                    # come out of the live index, so the row must point at what
                    # is already ingested rather than ask the runner to ingest a
                    # copy from disk.
                    "source_document_id": doc_id,
                    "source_file": path,
                    "chunk_id_or_text": text,
                    "expected_card_count": args.cards_per_passage,
                    "content_type": kind,
                }
            )

    if not rows:
        print("no passages matched the selection rules", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    meta = {
        "name": out.stem,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        # No generator model: the passage is the ground truth, so there is
        # nothing for a model to author and nothing for it to bias.
        "generator_model": None,
        "selection": {
            "seed": SEED,
            "per_kind": args.per_kind,
            "cards_per_passage": args.cards_per_passage,
            "min_chars": MIN_CHARS,
            "max_chars": MAX_CHARS,
            "edge_trim": EDGE_TRIM,
        },
        "rows": len(rows),
        "by_content_type": {
            kind: sum(1 for r in rows if r["content_type"] == kind)
            for kind in sorted({r["content_type"] for r in rows})
        },
    }
    (out.parent / f"{out.stem}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    print(f"{len(rows)} rows -> {out}")
    for kind, n in meta["by_content_type"].items():
        print(f"  {kind:<16} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
