"""Corpus-vocab spell correction: corrects out-of-vocab domain terms only."""

from app.services import query_spellcorrect as sc


def _with_vocab(monkeypatch, vocab: dict[str, int]):
    monkeypatch.setattr(sc, "_vocab", vocab)
    monkeypatch.setattr(sc, "_built_at", 1e18)  # never expires during the test


def test_corrects_typoed_proper_noun(monkeypatch):
    _with_vocab(monkeypatch, {"ithaca": 40, "king": 200, "who": 500, "the": 900})
    # the smoking-gun case: "Itaca" -> "Ithaca", capitalization preserved
    assert sc.correct_query("who is the king of Itaca?") == "who is the king of Ithaca?"


def test_leaves_in_vocab_and_short_and_unknown_tokens(monkeypatch):
    _with_vocab(monkeypatch, {"ithaca": 40, "penelope": 10})
    # in-vocab unchanged; <4 chars untouched; no e-d-1 candidate -> unchanged
    assert sc.correct_query("Penelope and the cat zzzzq") == "Penelope and the cat zzzzq"


def test_frequency_breaks_ties(monkeypatch):
    # "wold" is e-d-1 from both "world" and "would"; pick the more frequent
    _with_vocab(monkeypatch, {"world": 100, "would": 5})
    assert sc.correct_query("hello wold") == "hello world"


def test_empty_vocab_is_noop(monkeypatch):
    _with_vocab(monkeypatch, {})
    assert sc.correct_query("Itaca") == "Itaca"


def test_edits1_contains_insertion():
    # "itaca" -> "ithaca" is an insertion of 'h'
    assert "ithaca" in sc._edits1("itaca")
