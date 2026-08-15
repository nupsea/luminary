"""Ingestion fidelity eval: how much of each source document survives into chunks.

The suite measured retrieval and generation but nothing upstream of them, so a
document could be mangled at parse time while every downstream number still looked
healthy. Retrieval scores what was indexed; it cannot report what never arrived.

Deterministic and LLM-free: reads each manifest document the way ingestion reads it
and compares against the chunks stored for it.

  retention    fraction of the source's distinct content tokens present in some
               chunk. Text that is missing here is unreachable by any query, so
               this is the ceiling on every retrieval metric.
  duplication  chunk tokens / source tokens. Chunking overlaps deliberately, so
               ~1.0-1.2 is expected; far above that means furniture was repeated
               into the index, far below means content was dropped.

Usage:
    uv run --project backend python evals/run_ingest_eval.py [--assert-thresholds]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.universal_parser import read_document_text  # noqa: E402
from evals.generate_golden import strip_gutenberg_boilerplate  # noqa: E402
from evals.lib.manifest import GOLDEN_DIR  # noqa: E402
from evals.lib.environment import capture as capture_environment  # noqa: E402
from evals.lib.scoring_history import append_history  # noqa: E402

# Measured 2026-08-14 over the 12 manifest documents, boilerplate stripped:
# retention 95.7%-100% (lowest hamlet.txt), duplication 0.96-1.14. These floors sit
# below every observed value and detect a parse path collapsing, not a slow drift.
# Gutenberg licence text is stripped from BOTH sides before comparing -- ingestion
# drops it by design, and counting it as loss flags every public-domain book.
THRESHOLDS = {"min_retention": 0.90, "max_duplication": 1.60}

# Audio reaches chunks through transcription, so the file on disk holds no text
# to compare against. Measured by a different method or not at all -- never by
# pretending 0% retention is a result.
_AUDIO_FORMATS = frozenset({"wav", "mp3", "m4a", "mp4"})


def tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()


def measure(source: str, chunk_texts: list[str]) -> tuple[float, float]:
    """Return (retention, duplication) for one document."""
    src_tok = tokens(source)
    if not src_tok:
        return 0.0, 0.0
    chunk_tok: list[str] = []
    for t in chunk_texts:
        chunk_tok.extend(tokens(t))
    chunk_set = set(chunk_tok)
    # Distinct tokens over 3 chars: insensitive to the overlap chunking introduces,
    # and to how often a common word repeats.
    src_set = {t for t in src_tok if len(t) > 3}
    retention = len(src_set & chunk_set) / len(src_set) if src_set else 0.0
    return retention, len(chunk_tok) / len(src_tok)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO_ROOT / ".luminary/luminary.db"))
    parser.add_argument("--assert-thresholds", action="store_true", dest="assert_thresholds")
    # This tool reads the DB directly and needs no backend. The URL is only for
    # provenance; when nothing answers, the row records why rather than nothing.
    parser.add_argument("--backend-url", default="http://localhost:7820")
    parser.add_argument(
        "--all-documents",
        action="store_true",
        dest="all_documents",
        help=(
            "Measure every complete document in the library, grouped by format, "
            "instead of the 12 manifest documents. The manifest covers txt, md "
            "and one PDF; a library also holds epub, docx, scraped articles and "
            "audio, and each reaches chunks through a different parse path."
        ),
    )
    args = parser.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    if args.all_documents:
        rows = con.execute(
            "SELECT file_path, id, format, title FROM documents "
            "WHERE stage = 'complete' AND file_path IS NOT NULL"
        ).fetchall()
        sources = {r[0]: r[1] for r in rows}
        formats = {r[0]: (r[2] or "?") for r in rows}
    else:
        manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text())
        sources = manifest
        formats = {src: Path(src).suffix.lstrip(".") or "?" for src in manifest}

    print(f"{'document':<34} {'src tok':>8} {'chunks':>7} {'retention':>10} {'dup':>6}")
    print("-" * 72)

    violations: list[str] = []
    retentions: list[float] = []
    dups: list[float] = []
    missing: list[str] = []

    by_format: dict[str, list[tuple[float, float]]] = {}
    unmeasurable: list[str] = []

    for src, doc_id in sorted(sources.items()):
        path = Path(src) if Path(src).is_absolute() else REPO_ROOT / src
        name = Path(src).name[:33]
        fmt = formats.get(src, "?")
        if fmt in _AUDIO_FORMATS:
            # The source is audio; its text exists only as the transcript that
            # ingestion produced. Comparing chunks against it would compare the
            # output to itself, so this method cannot measure the kind at all.
            unmeasurable.append(f"{name} ({fmt})")
            continue
        if not path.exists():
            missing.append(src)
            print(f"{name:<34} source file not found")
            continue
        source = strip_gutenberg_boilerplate(read_document_text(path))
        chunk_texts = [
            r[0]
            for r in con.execute("SELECT text FROM chunks WHERE document_id = ?", (doc_id,))
            if r[0]
        ]
        if not chunk_texts:
            # Never a pass: a document with no chunks is invisible to every query.
            violations.append(f"{name}: no chunks stored")
            print(f"{name:<34} {len(tokens(source)):>8} {0:>7}   NO CHUNKS")
            continue

        retention, dup = measure(source, chunk_texts)
        retentions.append(retention)
        dups.append(dup)
        by_format.setdefault(fmt, []).append((retention, dup))
        flag = ""
        if retention < THRESHOLDS["min_retention"]:
            violations.append(f"{name}: retention {retention:.1%} < {THRESHOLDS['min_retention']:.0%}")
            flag = "  <-- LOSS"
        if dup > THRESHOLDS["max_duplication"]:
            violations.append(f"{name}: duplication {dup:.2f} > {THRESHOLDS['max_duplication']}")
            flag = "  <-- DUPLICATED"
        print(
            f"{name:<34} {len(tokens(source)):>8} {len(chunk_texts):>7} "
            f"{retention:>9.1%} {dup:>6.2f}{flag}"
        )

    print("-" * 72)
    if by_format:
        print(f"\n{'format':<10} {'docs':>5} {'min retention':>14} {'mean':>8} {'max dup':>8}")
        for fmt in sorted(by_format):
            vals = by_format[fmt]
            rets = [r for r, _ in vals]
            print(
                f"{fmt:<10} {len(vals):>5} {min(rets):>13.1%} "
                f"{sum(rets) / len(rets):>7.1%} {max(d for _, d in vals):>8.2f}"
            )
    if unmeasurable:
        # Stated, never silently dropped: a kind nothing measures is a coverage
        # gap, and an unreported skip is indistinguishable from a pass.
        print(f"\nnot measurable by source comparison ({len(unmeasurable)}): "
              f"{', '.join(unmeasurable[:6])}")
    if missing:
        # Requested-but-uncomputed is a failure, never a silent skip (I-32).
        violations.append(f"{len(missing)} manifest source file(s) missing: {missing[:3]}")

    metrics = {
        "documents": len(retentions),
        "formats": {
            fmt: {
                "documents": len(v),
                "min_retention": min(r for r, _ in v),
                "mean_retention": sum(r for r, _ in v) / len(v),
                "max_duplication": max(d for _, d in v),
            }
            for fmt, v in by_format.items()
        },
        "unmeasurable_documents": len(unmeasurable),
        "min_retention": min(retentions) if retentions else None,
        "mean_retention": sum(retentions) / len(retentions) if retentions else None,
        "max_duplication": max(dups) if dups else None,
    }
    passed = not violations
    for key, val in metrics.items():
        print(f"  {key:<16} {val if not isinstance(val, float) else f'{val:.4f}'}")
    append_history(
        "corpus",
        "no-llm",
        metrics,
        passed,
        eval_kind="ingest",
        environment=capture_environment(args.backend_url),
    )

    if violations:
        print("\nINGESTION GATE FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        if args.assert_thresholds:
            sys.exit(1)


if __name__ == "__main__":
    main()
