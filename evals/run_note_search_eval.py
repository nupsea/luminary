"""Note search eval: does /notes/search find the note, and only the note.

Note search had no eval at all until 2026-08-28, which mattered because it is the
surface that changed most in 0.8.2 -- a liveness join against `notes` and a
cosine floor on the semantic arm, both of which alter what comes back.

**This eval has no committed golden, by design.** The corpus is the user's own
notes; a golden written against one machine's library measures nothing on
another. Queries are derived from whatever notes exist, so the eval runs
anywhere. The cost is that `self_recall_*` is corpus-dependent and its floor is a
collapse detector only -- compare a change against your own previous run on an
unchanged library, never against the floor (see docs/eval-coverage.md).

Metrics, reported separately because they move independently:

  self_recall_1   the note ranks FIRST for a phrase taken from its own body
  self_recall_5   ... or anywhere in the top 5. SATURATES at 1.0000 on a healthy
                  library and is NOT gated: a query built from the note's own
                  words is answerable by the keyword arm alone, so this is a
                  floor with no headroom, quotable only when it drops.
  ghost_rate      results whose note no longer exists in `notes`. The keyword arm
                  joins that table so it cannot produce one; the semantic arm
                  reads LanceDB directly and did, for any note whose vector
                  delete failed. Must be 0.0 on every corpus -- the one metric
                  here that is a real invariant rather than a corpus property.
  vector_share    fraction of result slots contributed by the semantic arm.
                  The collapse detector for NOTE_SEMANTIC_MIN_SIMILARITY: set it
                  too high and the arm goes silent while every other number here
                  stays green, because the keyword arm alone still answers a
                  self-query.
  paraphrase_recall_5  the note is in the top 5 for a query a local model wrote
                  about it sharing no word stem with it (--paraphrase). The case
                  the semantic arm exists for: no keyword can find these, so this
                  is the one recall number the keyword arm cannot hold up.
                  Report-only; compare against your own earlier run.
  noise_rejection fraction of deliberately alien queries returning nothing.
                  Before the floor existed, `limit(k)` had no distance bound, so
                  in a library smaller than k EVERY query returned the k nearest
                  notes however unrelated.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sqlite3
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.lib.environment import capture as capture_environment  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402

# Floors are collapse detectors, not quality bars.
#
# Baselines measured 2026-08-28 by THIS script against a 125-note library
# (40 sampled, seed 42; 119 result slots), bit-reproducible across re-runs:
#   self_recall_1   0.9000      self_recall_5   1.0000
#   ghost_rate      0.0000      vector_share    0.7563
#   noise_rejection 1.0000
# They are corpus-coupled: these hold for THIS library and are not portable.
# Compare a change against your own previous run, never against the floor.
#
# ghost_rate is 0.0 exactly and stays there: a non-zero value means deleted
# content is being served, which is never acceptable on any corpus.
#
# self_recall_1's floor is 0.70 against a measured 0.9250 -- the subtrahend is
# headroom for corpus variation, since a library of short or near-duplicate notes
# legitimately scores lower. Bracketing it: 0.90 would fail on a library only
# slightly noisier than this one, and 0.50 would not notice the keyword arm dying.
#
# vector_share's floor is 0.20 against a measured 0.7563. It exists to catch the
# similarity floor being raised until the semantic arm stops contributing; that
# failure leaves every other metric green.
# Split by direction rather than inferred per key: ghost_rate is a CEILING and
# the rest are FLOORS, and a single dict made the comparison implicit -- the first
# version of this file got the operator wrong for exactly that reason.
FLOORS = {
    "self_recall_1": 0.70,
    "vector_share": 0.20,
    "noise_rejection": 0.75,
}
CEILINGS = {
    "ghost_rate": 0.0,
}

# Deliberately alien to any learning library: domain-specific and mundane. Not
# nonsense strings -- those are trivially far from everything in embedding space,
# which would make the metric pass without the floor doing any work.
NOISE_QUERIES = [
    "quarterly VAT reconciliation for a Belgian subsidiary",
    "how to descale a Gaggia espresso machine",
    "flight LH440 checked baggage allowance",
    "sourdough starter hydration ratio by weight",
    "replacing the timing belt on a 2011 Ford Focus",
]

_STOP = frozenset([
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "for", "with", "that", "this",
    "it", "is", "are", "was", "were", "be", "as", "at", "by", "from", "on", "not", "you",
    "your", "we", "our", "they", "their", "he", "she", "his", "her", "its", "if", "then",
    "than", "so", "what", "which", "who", "when", "where", "how", "can", "will", "would",
    "should", "there", "here", "them", "these", "those", "has", "have", "had"
])


def _distinctive_phrase(content: str, words_wanted: int = 6) -> str | None:
    """A phrase from the middle of the note, stopwords removed.

    From the middle rather than the start because a note's first line is usually
    its title, which is also what the vector arm indexes most strongly -- taking
    the opening would make the query easier than a real one.
    """
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", content) if w.lower() not in _STOP]
    if len(words) < words_wanted:
        return None
    start = len(words) // 3
    return " ".join(words[start : start + words_wanted])


def _stems(text: str) -> set[str]:
    """Content-word stems, cut to five letters: stricter than the FTS tokenizer,
    which matches whole words only, so "vanish" for "vanishes" also counts."""
    return {
        w.lower()[:5]
        for w in re.findall(r"[A-Za-z][A-Za-z'-]+", text)
        if w.lower() not in _STOP and len(w) >= 3
    }


def _shared_words(query: str | None, content: str) -> list[str]:
    """The query's words whose stem the note also has."""
    if not query:
        return []
    note = _stems(content)
    return sorted({w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", query) if _stems(w) & note})


_PARAPHRASE_SYSTEM = (
    "You write the search query a person would type to find one of their own notes "
    "again, months later, having forgotten its wording. Reply with the query only: "
    "3 to 8 words, no quotes. Do not use any word that appears in the note, nor any "
    "form of one; describe what it is about in other words."
)

# At temperature 0 a reply can repeat one word until the context fills, past any
# timeout. 8 words is ~16 tokens; a capped reply is rejected, never searched.
_PARAPHRASE_MAX_TOKENS = 64
_PARAPHRASE_ATTEMPTS = 3


def _paraphrase(content: str, model: str, avoid: list[str] | None = None) -> str | None:
    """A query about the note in other words, or None if the model gave none."""
    base = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    prompt = content[:2000]
    if avoid:
        prompt += "\n\nThese words, and any form of them, are not allowed: " + ", ".join(avoid)
    resp = httpx.post(
        f"{base}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _PARAPHRASE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "seed": 42, "num_predict": _PARAPHRASE_MAX_TOKENS},
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("done_reason") == "length":
        return None  # a reply cut at the cap is a loop, not a query
    text = body["message"]["content"].strip().strip('"').splitlines()
    return text[0].strip() if text and text[0].strip() else None


def _stem_free_paraphrase(content: str, model: str) -> str | None:
    """A paraphrase sharing no stem with the note, or None after the last attempt.

    Each retry bans every word the earlier attempts shared; the stem check decides.
    """
    avoid: set[str] = set()
    for _ in range(_PARAPHRASE_ATTEMPTS):
        query = _paraphrase(content, model, avoid=sorted(avoid) or None)
        shared = _shared_words(query, content)
        # A reply in another script is a failed attempt: the stem check cannot read it.
        if query and query.isascii() and not shared:
            return query
        avoid.update(shared)
    return None


def _search(backend_url: str, query: str, k: int) -> list[dict]:
    resp = httpx.get(
        f"{backend_url}/notes/search", params={"q": query, "k": k}, timeout=120.0
    )
    resp.raise_for_status()
    return resp.json()["results"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the note search eval.")
    parser.add_argument("--backend-url", default="http://localhost:7820")
    parser.add_argument("--db", default=str(REPO_ROOT / ".luminary" / "luminary.db"))
    parser.add_argument("--sample", type=int, default=40)
    parser.add_argument("--assert-thresholds", action="store_true")
    parser.add_argument(
        "--paraphrase",
        metavar="MODEL",
        help="also score recall on queries this Ollama model writes with no shared word stem",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"ERROR: no database at {db_path}.", file=sys.stderr)
        sys.exit(2)

    db = sqlite3.connect(db_path)
    total_notes = db.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    rows = db.execute(
        "SELECT id, content FROM notes WHERE length(content) > 200"
    ).fetchall()
    live_ids = {r[0] for r in db.execute("SELECT id FROM notes")}

    # Requested but not computable is a failure, never a quiet pass: a library
    # this small cannot resolve a rate at all, and reporting one would invent it.
    if len(rows) < 10:
        print(
            f"ERROR: only {len(rows)} notes over 200 chars in {db_path}; this eval "
            "needs at least 10 to produce a rate that means anything. Nothing was "
            "measured -- this is a failure, not a pass.",
            file=sys.stderr,
        )
        sys.exit(2)

    random.Random(42).shuffle(rows)  # noqa: S311 -- sampling, not cryptography
    eligible = rows
    rows = rows[: args.sample]

    hit1 = hit5 = 0
    scored = 0
    slots = 0
    vector_slots = 0
    ghosts = 0
    for note_id, content in rows:
        query = _distinctive_phrase(content)
        if query is None:
            continue
        scored += 1
        results = _search(args.backend_url, query, 5)
        ids = [r["note_id"] for r in results]
        for r in results:
            slots += 1
            if r["source"] in ("vector", "both"):
                vector_slots += 1
            if r["note_id"] not in live_ids:
                ghosts += 1
        if ids and ids[0] == note_id:
            hit1 += 1
        if note_id in ids:
            hit5 += 1

    if scored == 0:
        print("ERROR: no note yielded a usable query; nothing measured.", file=sys.stderr)
        sys.exit(2)

    para_hit1 = para_hit5 = para_scored = para_rejected = 0
    if args.paraphrase:
        # Every eligible note, not the sample: on a long note most queries share a
        # stem, so 40 notes yielded 7 to 12 scorable queries (2026-10-02).
        for note_id, content in eligible:
            query = _stem_free_paraphrase(content, args.paraphrase)
            if query is None:
                para_rejected += 1
                continue
            para_scored += 1
            ids = [r["note_id"] for r in _search(args.backend_url, query, 5)]
            para_hit1 += bool(ids) and ids[0] == note_id
            para_hit5 += note_id in ids
        # Requested but not computable fails (I-32); 10 is the same floor as above.
        if para_scored < 10:
            print(
                f"ERROR: only {para_scored} paraphrases shared no stem with their note "
                f"({para_rejected} rejected); paraphrase recall was not measured.",
                file=sys.stderr,
            )
            sys.exit(2)

    rejected = sum(1 for q in NOISE_QUERIES if not _search(args.backend_url, q, 10))

    metrics = {
        "self_recall_1": hit1 / scored,
        "self_recall_5": hit5 / scored,
        "ghost_rate": ghosts / slots if slots else 0.0,
        "vector_share": vector_slots / slots if slots else 0.0,
        "noise_rejection": rejected / len(NOISE_QUERIES),
        "notes_scored": scored,
        "result_slots": slots,
        "library_notes": total_notes,
    }
    if args.paraphrase:
        metrics |= {
            "paraphrase_recall_1": para_hit1 / para_scored,
            "paraphrase_recall_5": para_hit5 / para_scored,
            "paraphrase_scored": para_scored,
            "paraphrase_rejected": para_rejected,
            "paraphrase_model": args.paraphrase,
        }

    violations: list[str] = []
    for key, floor in FLOORS.items():
        if metrics[key] < floor:
            violations.append(f"{key} {metrics[key]:.4f} < {floor}")
    for key, ceiling in CEILINGS.items():
        if metrics[key] > ceiling:
            violations.append(f"{key} {metrics[key]:.4f} > {ceiling}")
    passed = not violations

    print(f"\n{'=' * 58}")
    print("  Note search evaluation")
    print(f"{'=' * 58}")
    for key in ("self_recall_1", "self_recall_5", "ghost_rate", "vector_share", "noise_rejection"):
        if key in FLOORS:
            mark = f"   (floor {FLOORS[key]})"
        elif key in CEILINGS:
            mark = f"   (ceiling {CEILINGS[key]})"
        else:
            mark = ""
        print(f"  {key:<18} {metrics[key]:.4f}{mark}")
    print(f"  {'self_recall_5':<18} is not gated -- it saturates; read it only when it drops")
    if args.paraphrase:
        for key in ("paraphrase_recall_1", "paraphrase_recall_5"):
            print(f"  {key:<20} {metrics[key]:.4f}   (report-only)")
        print(
            f"  {para_scored} of {len(eligible)} notes scored; {para_rejected} had no "
            f"stem-free paraphrase in {_PARAPHRASE_ATTEMPTS} attempts "
            f"({args.paraphrase})"
        )
    print(f"{'-' * 58}")
    print(f"  scored {scored} notes / {slots} result slots, library has {total_notes} notes")
    print(f"{'=' * 58}\n")

    append_history(
        "notes_live",
        "note-search",
        metrics,
        passed,
        eval_kind="note_search",
        environment=capture_environment(args.backend_url),
    )

    if args.assert_thresholds and violations:
        print("QUALITY GATE FAILED: " + "; ".join(violations), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
