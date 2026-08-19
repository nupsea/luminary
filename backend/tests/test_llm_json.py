"""Tests for tolerant LLM JSON parsing."""

from app.services.llm_json import (
    parse_llm_json_array,
    parse_llm_json_object,
    salvage_llm_json_object,
)


def test_valid_array_passes_through():
    assert parse_llm_json_array('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_empty_array():
    assert parse_llm_json_array("[]") == []


def test_fenced_array():
    raw = '```json\n[{"term": "attention"}]\n```'
    assert parse_llm_json_array(raw) == [{"term": "attention"}]


def test_prose_wrapped_array():
    raw = 'Here are the references:\n[{"term": "attention"}]\nHope this helps!'
    assert parse_llm_json_array(raw) == [{"term": "attention"}]


def test_no_array_returns_empty():
    assert parse_llm_json_array("I could not find any references.") == []
    assert parse_llm_json_array("") == []


def test_non_list_json_returns_empty():
    assert parse_llm_json_array('{"term": "attention"}') == []


def test_invalid_latex_escape_repaired():
    """The observed production failure: LaTeX-style backslashes inside string
    values are not legal JSON escapes and must not discard the whole array."""
    raw = (
        '[{"term": "Scaled Dot-Product Attention", '
        '"excerpt": "softmax(QK^T/\\sqrt{d_k})V with \\alpha weights"}]'
    )
    parsed = parse_llm_json_array(raw)
    assert len(parsed) == 1
    assert "sqrt{d_k}" in parsed[0]["excerpt"]


def test_valid_escapes_preserved():
    raw = '[{"excerpt": "line\\nbreak and a \\"quote\\" and \\\\ backslash"}]'
    parsed = parse_llm_json_array(raw)
    assert parsed[0]["excerpt"] == 'line\nbreak and a "quote" and \\ backslash'


def test_truncated_array_salvages_complete_elements():
    raw = '[{"term": "attention", "url": "https://example.org"}, {"term": "transfo'
    parsed = parse_llm_json_array(raw)
    assert parsed == [{"term": "attention", "url": "https://example.org"}]


def test_truncated_with_bad_escape_salvages():
    raw = '[{"term": "ok"}, {"excerpt": "\\lambda values"}, {"term": "cut off he'
    parsed = parse_llm_json_array(raw)
    assert parsed[0] == {"term": "ok"}
    assert parsed[1]["excerpt"] == "\\lambda values"
    assert len(parsed) == 2


def test_unicode_escape_untouched():
    raw = '[{"excerpt": "snowman \\u2603"}]'
    assert parse_llm_json_array(raw)[0]["excerpt"] == "snowman ☃"


def test_object_valid():
    raw = '{"image_type": "diagram", "description": "an encoder stack"}'
    assert parse_llm_json_object(raw) == {
        "image_type": "diagram",
        "description": "an encoder stack",
    }


def test_object_fenced_with_prose():
    raw = 'Sure!\n```json\n{"image_type": "chart"}\n```'
    assert parse_llm_json_object(raw) == {"image_type": "chart"}


def test_object_bad_escape_repaired():
    raw = '{"description": "plots \\sigma over time"}'
    parsed = parse_llm_json_object(raw)
    assert parsed is not None
    assert "sigma" in parsed["description"]


def test_object_unrecoverable_returns_none():
    assert parse_llm_json_object("no braces here") is None
    assert parse_llm_json_object('{"truncated": "mid str') is None
    assert parse_llm_json_object("[1, 2]") is None


def test_salvage_keeps_pairs_completed_before_truncation():
    """A vision model that loops on a dense diagram runs out of tokens mid-object."""
    raw = '```json\n{"image_type": "architecture_diagram", "labels": ["Softmax", "Linear"], "des'
    assert salvage_llm_json_object(raw) == {
        "image_type": "architecture_diagram",
        "labels": ["Softmax", "Linear"],
    }


def test_salvage_drops_the_partial_trailing_value():
    raw = '{"image_type": "flowchart", "description": "a partial senten'
    assert salvage_llm_json_object(raw) == {"image_type": "flowchart"}


def test_salvage_returns_none_when_nothing_completed():
    assert salvage_llm_json_object('{"image_ty') is None
    assert salvage_llm_json_object("no braces here") is None
    assert salvage_llm_json_object("{}") is None


def test_salvage_repairs_illegal_escapes():
    raw = '{"description": "plots \\sigma over time", "labels": ["x'
    salvaged = salvage_llm_json_object(raw)
    assert salvaged is not None
    assert "sigma" in salvaged["description"]


# What the counters mean. These exist because `first_pass_rate` read 0.0000 on a
# 3B model and on a 14B one, and the reason was this module's attempt order
# rather than anything either model did.


def _moved(fn, raw):
    from app.services import llm_output_stats as stats

    before = dict(stats.snapshot()["counts"])
    result = fn(raw)
    after = stats.snapshot()["counts"]
    return result, {k: after[k] - before.get(k, 0) for k in after if after[k] - before.get(k, 0)}


def test_a_compliant_object_is_not_an_array_surrounded_by_prose():
    """`{"flashcards": [...]}` is the shape the flashcard prompt demands. Slicing
    to the inner array made the wrapper look like prose, so every compliant
    generation was recorded as repaired."""
    from app.services.flashcard_parsers import _parse_llm_response

    raw = '{"flashcards": [{"question": "Q", "answer": "A"}]}'
    cards, moved = _moved(lambda r: _parse_llm_response(r, "doc", expect="object"), raw)

    assert len(cards) == 1
    assert moved.get("parses_first_pass") == 1
    assert "repair_surrounded_by_prose" not in moved
    assert "shape_deviations" not in moved


def test_the_other_shape_parses_cleanly_and_is_counted_as_a_deviation():
    """A bare array where an object was specified needed no repair -- but it is
    not what the prompt asked for, and that difference is the model's."""
    from app.services.flashcard_parsers import _parse_llm_response

    raw = '[{"question": "Q", "answer": "A"}]'
    cards, moved = _moved(lambda r: _parse_llm_response(r, "doc", expect="object"), raw)

    assert len(cards) == 1
    assert moved.get("parses_first_pass") == 1
    assert moved.get("shape_deviations") == 1


def test_real_prose_around_the_json_is_still_counted_as_a_repair():
    from app.services.flashcard_parsers import _parse_llm_response

    raw = 'Here are your cards:\n[{"question": "Q", "answer": "A"}]\nHope that helps!'
    cards, moved = _moved(lambda r: _parse_llm_response(r, "doc", expect="array"), raw)

    assert len(cards) == 1
    assert moved.get("repair_surrounded_by_prose") == 1
    assert "parses_first_pass" not in moved


def test_one_completion_is_counted_once_whatever_shape_it_arrived_in():
    """Two attempts at one completion must not become two parses: the denominator
    of every rate on this path is `parses`."""
    from app.services.flashcard_parsers import _parse_llm_response

    _, moved = _moved(
        lambda r: _parse_llm_response(r, "doc", expect="array"),
        '{"flashcards": [{"question": "Q", "answer": "A"}]}',
    )

    assert moved.get("parses") == 1
