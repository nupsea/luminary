"""Code-aware chunking service for tech_book and tech_article content types.

All functions in this module are pure (no I/O, no DB access) and can be
unit-tested without any fixtures.  Orchestration (DB writes, uuid generation)
lives in the ingestion workflow (_chunk_tech_book in ingestion.py).
"""

import ast
import logging
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# Guard against pathological fenced blocks: skip any block whose body exceeds
# this limit (treat as malformed document with unclosed fence).
_MAX_CODE_BLOCK_LEN = 20_000

# Minimum consecutive indented lines to constitute an indented code block
_MIN_INDENTED_LINES = 3

_LANGUAGE_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "rb": "ruby",
    "rs": "rust",
    "sh": "bash",
    "bash": "bash",
    "shell": "bash",
}


def _detect_language(fence_info: str) -> str | None:
    """Normalise the fence info string to a canonical language tag.

    The fence info is the text after the opening triple-backtick, e.g. 'python',
    'js', ''.  Returns a canonical lowercase tag or None for empty/unknown.
    """
    tag = fence_info.strip().lower().split()[0] if fence_info.strip() else ""
    if not tag:
        return None
    return _LANGUAGE_ALIASES.get(tag, tag)


def _parse_ast_signature(source: str, language: str | None) -> str | None:
    """Extract the first top-level function or class signature from Python source.

    Returns a string like "def name(a, b)" or "class Name" for the first
    top-level definition found.  Returns None if the language is not Python,
    if parsing fails (SyntaxError or any other exception), or if no definition
    is found.  Never raises.
    """
    if language != "python":
        return None
    try:
        tree = ast.parse(source)
    except Exception:
        return None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                args = ast.unparse(node.args)
            except Exception:
                args = "..."
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            return f"{prefix} {node.name}({args})"
        if isinstance(node, ast.ClassDef):
            return f"class {node.name}"
    return None


def extract_code_blocks(section_text: str) -> list[dict]:
    """Locate all code blocks in section_text and return their spans.

    Detects:
    1. Fenced blocks: triple-backtick delimited (``` lang \\n body ```).
    2. Indented blocks: >= _MIN_INDENTED_LINES consecutive lines with 4+ leading
       spaces (classic Markdown/RST indented code style).

    Returns a list of dicts sorted by start_pos:
        {
            "type": "fenced" | "indented",
            "language": str | None,
            "content": str,   # the code body only (without fence markers)
            "start_pos": int, # position in section_text where the block starts
            "end_pos": int,   # position just after the block ends
        }

    Blocks whose body exceeds _MAX_CODE_BLOCK_LEN are skipped (malformed guard).
    """
    blocks: list[dict] = []

    # --- Fenced blocks ---
    fenced_re = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
    for m in fenced_re.finditer(section_text):
        fence_info = m.group(1)
        body = m.group(2)
        if len(body) > _MAX_CODE_BLOCK_LEN:
            logger.debug("Skipping oversized fenced block at pos %d", m.start())
            continue
        blocks.append(
            {
                "type": "fenced",
                "language": _detect_language(fence_info),
                "content": body,
                "start_pos": m.start(),
                "end_pos": m.end(),
            }
        )

    # --- Indented blocks ---
    lines = section_text.split("\n")
    pos = 0
    run_start_line: int | None = None
    run_start_pos: int = 0
    run_lines: list[str] = []

    def _flush_run(end_pos: int) -> None:
        if run_start_line is not None and len(run_lines) >= _MIN_INDENTED_LINES:
            content = "\n".join(line[4:] for line in run_lines)  # strip 4 leading spaces
            if len(content) <= _MAX_CODE_BLOCK_LEN:
                # Only add if not already covered by a fenced block at this position
                already_covered = any(
                    b["start_pos"] <= run_start_pos < b["end_pos"] for b in blocks
                )
                if not already_covered:
                    blocks.append(
                        {
                            "type": "indented",
                            "language": None,
                            "content": content,
                            "start_pos": run_start_pos,
                            "end_pos": end_pos,
                        }
                    )

    for i, line in enumerate(lines):
        line_end = pos + len(line) + 1  # +1 for \n
        if line.startswith("    ") and line.strip():
            if run_start_line is None:
                run_start_line = i
                run_start_pos = pos
                run_lines = []
            run_lines.append(line)
        else:
            if run_start_line is not None:
                _flush_run(pos)
            run_start_line = None
            run_lines = []
        pos = line_end

    if run_start_line is not None:
        _flush_run(pos)

    # Sort by position (fenced and indented may interleave)
    blocks.sort(key=lambda b: b["start_pos"])
    return blocks


def chunk_mixed_content(
    section_text: str,
    section_id: str | None,
    doc_id: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict]:
    """Split section_text into chunks preserving code blocks as atomic units.

    Code blocks are never sub-split, even if they exceed chunk_size.
    Prose segments between code blocks are split with RecursiveCharacterTextSplitter.

    Returns a list of chunk dicts:
        {
            "text": str,
            "has_code": bool,
            "code_language": str | None,
            "code_signature": str | None,
            "is_code_block": bool,
        }
    """
    code_blocks = extract_code_blocks(section_text)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    result: list[dict] = []
    cursor = 0

    for block in code_blocks:
        # Prose before this code block
        prose_segment = section_text[cursor : block["start_pos"]]
        if prose_segment.strip():
            for prose_chunk in splitter.split_text(prose_segment):
                if prose_chunk.strip():
                    result.append(
                        {
                            "text": prose_chunk,
                            "has_code": False,
                            "code_language": None,
                            "code_signature": None,
                            "is_code_block": False,
                        }
                    )

        # Atomic code block — never sub-split
        code_text = block["content"].strip()
        if code_text:
            lang = block.get("language")
            sig = _parse_ast_signature(code_text, lang)
            result.append(
                {
                    "text": code_text,
                    "has_code": True,
                    "code_language": lang,
                    "code_signature": sig,
                    "is_code_block": True,
                }
            )

        cursor = block["end_pos"]

    # Prose after the last code block
    trailing_prose = section_text[cursor:]
    if trailing_prose.strip():
        for prose_chunk in splitter.split_text(trailing_prose):
            if prose_chunk.strip():
                result.append(
                    {
                        "text": prose_chunk,
                        "has_code": False,
                        "code_language": None,
                        "code_signature": None,
                        "is_code_block": False,
                    }
                )

    # If no code blocks were found and no prose was produced, fall back to splitting the whole text
    if not result and section_text.strip():
        for prose_chunk in splitter.split_text(section_text):
            if prose_chunk.strip():
                result.append(
                    {
                        "text": prose_chunk,
                        "has_code": False,
                        "code_language": None,
                        "code_signature": None,
                        "is_code_block": False,
                    }
                )

    return result
