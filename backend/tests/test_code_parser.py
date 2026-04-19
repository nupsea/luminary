"""Tests for CodeParser — tree-sitter-based code function/class extraction."""

import pytest

from app.services.code_parser import CodeParser, get_code_parser

# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


def test_detect_language_python():
    p = CodeParser()
    assert p.detect_language("app/main.py") == "python"


def test_detect_language_javascript():
    p = CodeParser()
    assert p.detect_language("src/index.js") == "javascript"


def test_detect_language_typescript():
    p = CodeParser()
    assert p.detect_language("component.tsx") == "typescript"


def test_detect_language_go():
    p = CodeParser()
    assert p.detect_language("main.go") == "go"


def test_detect_language_rust():
    p = CodeParser()
    assert p.detect_language("lib.rs") == "rust"


def test_detect_language_unknown_returns_none():
    p = CodeParser()
    assert p.detect_language("README.md") is None


def test_is_code_file():
    p = CodeParser()
    assert p.is_code_file("app.py") is True
    assert p.is_code_file("styles.css") is False


# ---------------------------------------------------------------------------
# parse_file — Python
# ---------------------------------------------------------------------------

PYTHON_SOURCE = '''
def greet(name: str) -> str:
    """Return a greeting message."""
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    return a + b


class Calculator:
    """Simple calculator class."""

    def multiply(self, x, y):
        return x * y
'''


def test_python_extracts_top_level_functions():
    p = CodeParser()
    defs = p.parse_file(PYTHON_SOURCE, "python", "calc.py")
    fn_names = [d["name"] for d in defs if d["kind"] == "function"]
    assert "greet" in fn_names
    assert "add" in fn_names


def test_python_extracts_class():
    p = CodeParser()
    defs = p.parse_file(PYTHON_SOURCE, "python", "calc.py")
    class_names = [d["name"] for d in defs if d["kind"] == "class"]
    assert "Calculator" in class_names


def test_python_function_metadata():
    p = CodeParser()
    defs = p.parse_file(PYTHON_SOURCE, "python", "calc.py")
    greet = next(d for d in defs if d["name"] == "greet")
    assert greet["kind"] == "function"
    assert greet["language"] == "python"
    assert greet["start_line"] >= 1
    assert greet["end_line"] >= greet["start_line"]
    assert "name" in greet["params"] or "name: str" in greet["body_text"]


def test_python_function_docstring():
    p = CodeParser()
    defs = p.parse_file(PYTHON_SOURCE, "python", "calc.py")
    greet = next(d for d in defs if d["name"] == "greet")
    assert "greeting" in greet["docstring"].lower()


def test_python_function_body_text():
    p = CodeParser()
    defs = p.parse_file(PYTHON_SOURCE, "python", "calc.py")
    add_def = next(d for d in defs if d["name"] == "add")
    assert "return" in add_def["body_text"]


def test_empty_source_returns_empty():
    p = CodeParser()
    defs = p.parse_file("", "python", "empty.py")
    assert defs == []


def test_parse_file_invalid_language_returns_empty():
    p = CodeParser()
    defs = p.parse_file("def f(): pass", "cobol", "f.cbl")
    assert defs == []


# ---------------------------------------------------------------------------
# chunk_code_file metadata — function_name, file_path, start_line
# ---------------------------------------------------------------------------


def test_chunk_text_contains_function_name():
    p = CodeParser()
    defs = p.parse_file(PYTHON_SOURCE, "python", "calc.py")
    assert any(d["name"] == "greet" for d in defs)


def test_chunk_start_line_set():
    p = CodeParser()
    defs = p.parse_file(PYTHON_SOURCE, "python", "calc.py")
    for d in defs:
        assert d["start_line"] > 0


# ---------------------------------------------------------------------------
# Call edge detection
# ---------------------------------------------------------------------------

PYTHON_CALLS = """
def helper():
    return 42

def compute():
    x = helper()
    return x + 1

def main():
    result = compute()
    print(result)
"""


def test_build_call_edges_detects_calls():
    p = CodeParser()
    defs = p.parse_file(PYTHON_CALLS, "python", "app.py")
    edges = CodeParser.build_call_edges(defs)
    # compute() calls helper()
    assert ("compute", "helper") in edges


def test_build_call_edges_detects_main_calls_compute():
    p = CodeParser()
    defs = p.parse_file(PYTHON_CALLS, "python", "app.py")
    edges = CodeParser.build_call_edges(defs)
    assert ("main", "compute") in edges


def test_build_call_edges_no_self_call():
    """A function should not create a self-call edge."""
    p = CodeParser()
    defs = p.parse_file(PYTHON_CALLS, "python", "app.py")
    edges = CodeParser.build_call_edges(defs)
    for caller, callee in edges:
        assert caller != callee


def test_build_call_edges_empty_when_no_calls():
    source = "def standalone():\n    return 1\n"
    p = CodeParser()
    defs = p.parse_file(source, "python", "s.py")
    edges = CodeParser.build_call_edges(defs)
    assert edges == []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_get_code_parser_returns_same_instance():
    from app.services import code_parser as cp_module

    cp_module._code_parser = None
    p1 = get_code_parser()
    p2 = get_code_parser()
    assert p1 is p2
    cp_module._code_parser = None


# ---------------------------------------------------------------------------
# GET /graph/{doc_id}?type=call_graph endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_graph_endpoint_returns_empty_for_unknown_doc():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/graph/nonexistent-doc?type=call_graph")

    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert isinstance(data["nodes"], list)
    assert isinstance(data["edges"], list)
