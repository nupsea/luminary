"""A corpus flashcard golden runs in any library (evals/build_flashcard_golden.py --corpus)."""

import json
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals import build_flashcard_golden as builder  # noqa: E402


def _library(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE documents (id, title, content_type, file_path, stage)")
    con.execute("CREATE TABLE chunks (document_id, chunk_index, text)")
    for doc_id, title in (("d-hamlet", "hamlet"), ("d-other", "my_notes")):
        con.execute(
            "INSERT INTO documents VALUES (?, ?, 'book', ?, 'complete')",
            (doc_id, title, f"/lib/raw/{doc_id}.txt"),
        )
        for i in range(20):
            con.execute("INSERT INTO chunks VALUES (?, ?, ?)", (doc_id, i, f"{title} {i} " * 60))
    con.commit()
    con.close()


def test_corpus_rows_name_the_source_file_not_a_library_id(tmp_path, monkeypatch):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "play.jsonl").write_text(json.dumps({"source_file": "DATA/plays/hamlet.txt"}) + "\n")
    monkeypatch.setattr(builder, "GOLDEN_DIR", golden)
    _library(tmp_path / "lib.db")
    out = tmp_path / "corpus.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "b",
            "--db",
            str(tmp_path / "lib.db"),
            "--corpus",
            "play",
            "--per-kind",
            "3",
            "--out",
            str(out),
        ],
    )

    assert builder.main() == 0
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 3
    # A document the corpus does not name stays out, and no row carries an id from this library.
    assert {r["source_file"] for r in rows} == {"DATA/plays/hamlet.txt"}
    assert not any("source_document_id" in r for r in rows)
    meta = json.loads((tmp_path / "corpus.meta.json").read_text())
    assert meta["row_provenance"] == "sampled"
