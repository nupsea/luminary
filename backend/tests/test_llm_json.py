"""Tests for tolerant LLM JSON parsing."""

from app.services.llm_json import parse_llm_json_array, parse_llm_json_object


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
