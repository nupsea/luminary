"""Code parser — extract function and class definitions from source files using tree-sitter.

Supports: Python (.py), JavaScript (.js), TypeScript (.ts/.tsx), Go (.go), Rust (.rs).
Each function/class becomes its own chunk with metadata: file_path, language,
function_name/class_name, start_line, end_line, body_text.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

# Language tag → file extensions
_LANG_EXTENSIONS: dict[str, list[str]] = {
    "python": ["py"],
    "javascript": ["js", "mjs", "cjs"],
    "typescript": ["ts", "tsx"],
    "go": ["go"],
    "rust": ["rs"],
}

_EXT_TO_LANG: dict[str, str] = {
    ext: lang for lang, exts in _LANG_EXTENSIONS.items() for ext in exts
}

# Node types that represent function/method definitions per language
_FUNCTION_NODE_TYPES: dict[str, set[str]] = {
    "python": {"function_definition"},
    "javascript": {"function_declaration", "method_definition", "arrow_function"},
    "typescript": {"function_declaration", "method_definition", "arrow_function"},
    "go": {"function_declaration", "method_declaration"},
    "rust": {"function_item"},
}

_CLASS_NODE_TYPES: dict[str, set[str]] = {
    "python": {"class_definition"},
    "javascript": {"class_declaration"},
    "typescript": {"class_declaration"},
    "go": {"type_declaration"},
    "rust": {"impl_item", "struct_item"},
}


class CodeDefinition(TypedDict):
    name: str
    kind: str  # "function" | "class"
    language: str
    docstring: str
    params: list[str]
    start_line: int
    end_line: int
    body_text: str


def _get_parser(language: str):
    """Lazily build and return a tree-sitter parser for the given language."""
    from tree_sitter import Language, Parser  # noqa: PLC0415

    if language == "python":
        import tree_sitter_python as tsp  # noqa: PLC0415

        lang = Language(tsp.language())
    elif language == "javascript":
        import tree_sitter_javascript as tsjs  # noqa: PLC0415

        lang = Language(tsjs.language())
    elif language == "typescript":
        import tree_sitter_typescript as tsts  # noqa: PLC0415

        lang = Language(tsts.language_typescript())
    elif language == "go":
        import tree_sitter_go as tsgo  # noqa: PLC0415

        lang = Language(tsgo.language())
    elif language == "rust":
        import tree_sitter_rust as tsrs  # noqa: PLC0415

        lang = Language(tsrs.language())
    else:
        raise ValueError(f"Unsupported language: {language}")
    return Parser(lang)


def _extract_name_from_node(node, language: str) -> str:
    """Extract the identifier/name from a function or class node."""
    for child in node.children:
        if child.type in ("identifier", "name"):
            return child.text.decode(errors="replace")
    return "anonymous"


def _extract_docstring_python(node) -> str:
    """Extract a Python docstring from the first statement of a block."""
    for child in node.children:
        if child.type == "block":
            for stmt in child.children:
                if stmt.type == "expression_statement":
                    for sub in stmt.children:
                        if sub.type in ("string", "concatenated_string"):
                            raw = sub.text.decode(errors="replace")
                            return raw.strip('"""').strip("'''").strip()
            break
    return ""


def _extract_params_python(node) -> list[str]:
    """Extract parameter names from a Python function definition."""
    params: list[str] = []
    for child in node.children:
        if child.type == "parameters":
            for p in child.children:
                if p.type == "identifier":
                    params.append(p.text.decode(errors="replace"))
                elif p.type in ("typed_parameter", "default_parameter"):
                    for sub in p.children:
                        if sub.type == "identifier":
                            params.append(sub.text.decode(errors="replace"))
                            break
    return params


def _walk_and_collect(
    node,
    source: bytes,
    language: str,
    results: list[CodeDefinition],
    depth: int = 0,
) -> None:
    """Recursively walk the AST and collect function/class definitions."""
    fn_types = _FUNCTION_NODE_TYPES.get(language, set())
    cls_types = _CLASS_NODE_TYPES.get(language, set())

    if node.type in fn_types:
        name = _extract_name_from_node(node, language)
        docstring = _extract_docstring_python(node) if language == "python" else ""
        params = _extract_params_python(node) if language == "python" else []
        body_text = node.text.decode(errors="replace") if node.text else ""
        results.append(
            CodeDefinition(
                name=name,
                kind="function",
                language=language,
                docstring=docstring,
                params=params,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                body_text=body_text,
            )
        )
        return  # don't recurse into functions (inner functions are separate)

    if node.type in cls_types:
        name = _extract_name_from_node(node, language)
        results.append(
            CodeDefinition(
                name=name,
                kind="class",
                language=language,
                docstring="",
                params=[],
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                body_text=node.text.decode(errors="replace") if node.text else "",
            )
        )
        # recurse into class to find method definitions
        for child in node.children:
            _walk_and_collect(child, source, language, results, depth + 1)
        return

    for child in node.children:
        _walk_and_collect(child, source, language, results, depth + 1)


class CodeParser:
    """Parse source code files and extract function/class definitions."""

    def detect_language(self, file_path: str) -> str | None:
        """Return language string from file extension, or None if unsupported."""
        ext = Path(file_path).suffix.lstrip(".").lower()
        return _EXT_TO_LANG.get(ext)

    def parse_file(self, source: str, language: str, file_path: str = "") -> list[CodeDefinition]:
        """Parse source code and return list of function/class definitions."""
        try:
            parser = _get_parser(language)
            source_bytes = source.encode(errors="replace")
            tree = parser.parse(source_bytes)
            results: list[CodeDefinition] = []
            _walk_and_collect(tree.root_node, source_bytes, language, results)
            logger.debug(
                "code_parser extracted %d definitions",
                len(results),
                extra={"language": language, "file_path": file_path},
            )
            return results
        except Exception as exc:
            logger.warning("code_parser.parse_file failed", exc_info=exc)
            return []

    def is_code_file(self, file_path: str) -> bool:
        """Return True if the file extension is a supported code language."""
        return self.detect_language(file_path) is not None

    @staticmethod
    def build_call_edges(
        definitions: list[CodeDefinition],
    ) -> list[tuple[str, str]]:
        """Return (caller_name, callee_name) pairs where callee is called in caller body.

        Uses simple substring matching: if callee_name appears in caller's body_text
        as a call pattern (name followed by '(').
        """
        fn_names = {d["name"] for d in definitions if d["kind"] == "function"}
        edges: list[tuple[str, str]] = []
        for defn in definitions:
            if defn["kind"] != "function":
                continue
            body = defn["body_text"]
            for callee in fn_names:
                if callee == defn["name"]:
                    continue
                # Look for callee_name( pattern in body
                if f"{callee}(" in body:
                    edges.append((defn["name"], callee))
        return edges


_code_parser: CodeParser | None = None


def get_code_parser() -> CodeParser:
    global _code_parser  # noqa: PLW0603
    if _code_parser is None:
        _code_parser = CodeParser()
    return _code_parser
