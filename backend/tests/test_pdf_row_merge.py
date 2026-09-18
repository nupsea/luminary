"""A stacked fraction's pieces render as three disconnected paragraphs (#132).

PyMuPDF's layout segmenter gives each piece of a fraction (numerator, root
symbol, denominator) its own block even though they sit on one visual row;
the TOC-path then joins blocks with a blank line, so
`Attention(Q, K, V ) = softmax(QKT` / `dk` / `)V (1)` rendered as three
paragraphs instead of one line. `_merge_same_row_blocks` reunites blocks that
share vertical space -- but the real risk found while writing it was a
verso/recto running head, which shares a row the same way a split formula
does. Correctness means the merge fires on the formula's own pieces and NOT
on the running head, so both real cases are tested and both must keep
passing if the thresholds ever move.
"""

from app.services.parser import _merge_same_row_blocks

# Coordinates and gaps are the real ones measured on the Attention paper PDF
# this bug was diagnosed on (see the comments beside `_MIN_ROW_OVERLAP_FRAC`
# and `_MAX_ROW_GAP_EM` in parser.py): the formula's own pieces sit within
# ~4.3pt of each other; the running head's two halves sit ~97pt apart; the
# document's average body font size is ~9.7pt.
BODY_FONT = 9.748023148788803


Bbox = tuple[float, float, float, float]


def _block(text: str, x0: float, y0: float, x1: float, y1: float) -> tuple[str, Bbox]:
    return (text, (x0, y0, x1, y1))


def test_formula_pieces_on_one_row_are_merged_into_one_line() -> None:
    blocks = [
        _block("Attention(Q, K, V ) = softmax(QKT", 133.77, 431.99, 330.5, 443.5),
        _block("dk", 233.0, 432.5, 246.0, 443.0),
        _block(")V (1)", 336.0, 431.99, 400.0, 443.5),
    ]
    merged = _merge_same_row_blocks(blocks, BODY_FONT)
    assert merged == ["Attention(Q, K, V ) = softmax(QKT dk )V (1)"]


def test_running_head_on_the_same_row_is_not_merged() -> None:
    """Two unrelated titles printed side by side in the page margin (#132).

    They satisfy pure vertical overlap exactly the way the formula's pieces
    do -- only the ~97pt horizontal gap between them (vs. the formula's
    ~4.3pt) tells the two cases apart.
    """
    blocks = [
        _block("Scaled Dot-Product Attention", 147.78, 71.28, 266.22, 81.16),
        _block("Multi-Head Attention", 363.59, 71.28, 450.20, 81.16),
    ]
    merged = _merge_same_row_blocks(blocks, BODY_FONT)
    assert merged == ["Scaled Dot-Product Attention", "Multi-Head Attention"]


def test_consecutive_paragraphs_never_overlap_and_stay_separate() -> None:
    """Ordinary prose: a new line starts below where the last one ends."""
    blocks = [
        _block("The first paragraph ends here.", 108.0, 200.0, 300.0, 212.0),
        _block("The second paragraph starts here.", 108.0, 218.0, 300.0, 230.0),
    ]
    merged = _merge_same_row_blocks(blocks, BODY_FONT)
    assert merged == ["The first paragraph ends here.", "The second paragraph starts here."]


def test_empty_input_returns_empty() -> None:
    assert _merge_same_row_blocks([], BODY_FONT) == []


def test_falsy_body_font_size_falls_back_instead_of_zeroing_the_gap_budget() -> None:
    """`body_font_size or 10.0` -- a 0.0 average must not make every gap fail."""
    blocks = [
        _block("softmax(QKT", 100.0, 431.99, 160.0, 443.5),
        _block("dk", 164.0, 432.5, 180.0, 443.0),
    ]
    merged = _merge_same_row_blocks(blocks, 0.0)
    assert merged == ["softmax(QKT dk"]
