"""Structural guards on the golden datasets, checkable without a backend.

A golden can be broken in ways that produce a confident float rather than an
error, so these run offline against the source corpus and fail before a number
is ever quoted.

Sources under DATA are partly untracked, so each check skips the datasets whose
source file is absent rather than failing on a machine that has a smaller corpus.

The two waiver maps are ratchets in the shape `layer_linter.KNOWN_VIOLATIONS`
uses: a count may shrink, never grow, and shrinking it is the point.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# The repo root makes `evals.lib` importable as a package; `evals/` itself makes
# the flat imports inside run_eval work.
for _path in (REPO_ROOT, REPO_ROOT / "evals"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evals.lib import provenance  # noqa: E402
from evals.lib.retrieval_metrics import _extract_hint_norms, _norm  # noqa: E402

from app.services.universal_parser import read_document_text  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "evals" / "golden"

# Hints matching more than one passage, per dataset. A hit against an ambiguous
# hint credits retrieval for returning ANY copy, so the metric stops measuring
# whether the authored passage was found.
#
# `paper` was regenerated 2026-08-12 from the furniture-collapsed corpus: 18 -> 2,
# and 17 chrome-sourced questions -> 0. The 2 remaining are one phrase the book
# itself prints twice, shared by two questions.
_KNOWN_AMBIGUOUS_HINTS = {
    "paper": 2,
    "odyssey": 2,
}

# Document kinds under DATA with no golden dataset. Emptied 2026-08-12: `legal`,
# `plays`, `study` and `daily_thoughts` were generated, `study` covering the only
# PDFs in the corpus and so the only measurement of the PDF parse path.
_KINDS_WITHOUT_A_GOLDEN: set[str] = set()

# Rows per dataset, and the smallest margin a threshold sits at. A dataset of n
# rows moves HR@5 in steps of 1/n, so one question flipping is 1/n of the metric.
# Below this a "gate" reports noise with a decimal point, so these datasets are
# measured and recorded but must not be the thing a decision rests on.
_MIN_ROWS_TO_GATE = 20

# Datasets under that floor, with what they actually hold. Shrink by adding rows,
# never by lowering the floor.
_TOO_SMALL_TO_GATE = {
    "code": 5,        # generator accepted 5 of 12 attempted
    "thoughts": 4,    # source is 2,944 chars -- one content chunk exists to sample
    "conversation": 18,
}


def _retrieval_goldens() -> list[tuple[str, list[dict]]]:
    out = []
    for path in sorted(GOLDEN_DIR.glob("*.jsonl")):
        if path.name.endswith(".flagged.jsonl"):
            continue
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if rows and "context_hint" in rows[0]:
            out.append((path.stem, rows))
    return out


def _source_text(source_file: str) -> str | None:
    """The corpus as ingestion produces it, then normalised the way hints are.

    Must go through `read_document_text`, not `read_bytes`: a PDF read as bytes
    is `%PDF-1.5 /FlateDecode`, so every hint in the `study` dataset reads as
    unresolved and the guard fires on its own blind spot rather than on the data.
    """
    path = REPO_ROOT / source_file
    if not path.exists():
        return None
    # `_norm` now does the unescaping and nbsp folding this used to do itself;
    # one function so the offline check and the runtime metric cannot disagree.
    return _norm(read_document_text(path))


def _hint_occurrences(rows: list[dict]) -> list[tuple[dict, int]]:
    """(row, occurrence count) for every row whose source file is present."""
    corpora: dict[str, str | None] = {}
    out = []
    for row in rows:
        source_file = row.get("source_file")
        if not source_file:
            continue
        if source_file not in corpora:
            corpora[source_file] = _source_text(source_file)
        corpus = corpora[source_file]
        hints = _extract_hint_norms(row)
        if corpus is None or not hints:
            continue
        out.append((row, max(corpus.count(h) for h in hints)))
    return out


_GOLDENS = _retrieval_goldens()
_IDS = [name for name, _ in _GOLDENS]


@pytest.mark.parametrize("dataset,rows", _GOLDENS, ids=_IDS)
def test_every_hint_resolves_in_its_source(dataset, rows):
    """A hint absent from the corpus makes its question permanently unhittable.

    The metric floor then measures the golden rather than retrieval, and no
    change to the funnel can ever move those rows.
    """
    unresolved = [row["question"] for row, count in _hint_occurrences(rows) if count == 0]

    assert unresolved == [], f"{dataset}: hints found in no chunk of the source"


@pytest.mark.parametrize("dataset,rows", _GOLDENS, ids=_IDS)
def test_every_hint_identifies_exactly_one_passage(dataset, rows):
    """A hit must mean "retrieval found *that* passage", not "found a copy of it"."""
    ambiguous = [row["question"] for row, count in _hint_occurrences(rows) if count > 1]
    allowed = _KNOWN_AMBIGUOUS_HINTS.get(dataset, 0)

    assert len(ambiguous) <= allowed, (
        f"{dataset}: {len(ambiguous)} ambiguous hints, allowance is {allowed}. "
        f"First: {ambiguous[:3]}"
    )
    if allowed and len(ambiguous) < allowed:
        pytest.fail(
            f"{dataset}: only {len(ambiguous)} ambiguous hints remain against an allowance "
            f"of {allowed}. Lower _KNOWN_AMBIGUOUS_HINTS -- the ratchet only shrinks."
        )


def test_every_document_kind_under_data_has_a_golden():
    """A kind with no golden is a parse and retrieval path nothing measures."""
    data_dir = REPO_ROOT / "DATA"
    if not data_dir.exists():
        pytest.skip("Local DATA corpus not present")

    kinds = {p.name for p in data_dir.iterdir() if not p.name.startswith(".")}
    covered = {
        Path(row["source_file"]).parts[1]
        for _, rows in _retrieval_goldens()
        for row in rows
        if row.get("source_file")
    }

    uncovered = kinds - covered - _KINDS_WITHOUT_A_GOLDEN
    assert uncovered == set(), f"document kinds under DATA with no golden dataset: {uncovered}"

    stale = _KINDS_WITHOUT_A_GOLDEN & covered
    assert stale == set(), f"now covered, remove from _KINDS_WITHOUT_A_GOLDEN: {stale}"


def test_a_dataset_small_enough_to_swing_on_one_question_is_declared():
    """One question must not move a dataset past its threshold margin.

    `code` accepted 5 of a 12-row target and `thoughts` has 4 rows, so a single
    question is 20 and 25 points of HR@5 respectively. Both are recorded here
    rather than quietly used as gates. The fix is more rows, never a lower floor.
    """
    for dataset, rows in _GOLDENS:
        declared = _TOO_SMALL_TO_GATE.get(dataset)
        if declared is not None:
            assert len(rows) == declared, (
                f"{dataset} now has {len(rows)} rows, not {declared}. If it reached "
                f"{_MIN_ROWS_TO_GATE}, remove it from _TOO_SMALL_TO_GATE."
            )
            continue
        assert len(rows) >= _MIN_ROWS_TO_GATE, (
            f"{dataset} has {len(rows)} rows, under the {_MIN_ROWS_TO_GATE} needed for a "
            "gate. Add rows, or declare it in _TOO_SMALL_TO_GATE."
        )


# Where a hint came from (E8)


def _meta_for(name: str) -> dict | None:
    path = GOLDEN_DIR / f"{name}.meta.json"
    return json.loads(path.read_text()) if path.exists() else None


@pytest.mark.parametrize("name,rows", _retrieval_goldens())
def test_every_golden_records_where_its_hints_came_from(name, rows):
    """`realign_hints.py` can replace a hint with one the retriever surfaced,
    which lets the retriever define its own target. Nothing recorded which had
    happened, and the two are indistinguishable in the file afterwards."""
    meta = _meta_for(name)
    assert meta is not None, f"{name} has no meta.json, so nothing records its provenance"
    assert provenance.violations(rows, meta) == [], f"{name}: {provenance.violations(rows, meta)}"


def test_a_realigned_row_must_say_why_it_was_safe():
    """The guard itself, on a synthetic dataset -- the real ones carry none yet,
    and a test that passes because the case is absent guards nothing."""
    meta = {"row_provenance": provenance.GENERATED}
    rows = [{"provenance": provenance.REALIGNED}]

    assert provenance.violations(rows, meta) != []
    assert provenance.violations(
        [{"provenance": provenance.REALIGNED, "provenance_reason": "hint was not verbatim"}], meta
    ) == []
