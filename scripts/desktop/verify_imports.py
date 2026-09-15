"""The dependency set a desktop bundle must import, and what it must never carry.

Run with the staged interpreter, isolated: `<staged python> -I verify_imports.py`.
Every platform's stage verifier calls this one file, so the macOS, Windows and
Linux bundles are held to the same list.
"""

import importlib
import importlib.util
import sys

REQUIRED = [
    "numpy", "scipy", "sklearn", "torch", "onnxruntime", "transformers",
    "sentence_transformers", "gliner", "lancedb", "pyarrow",
    "kuzu", "fitz", "PIL", "litellm", "langgraph", "keyring",
    "fastapi", "uvicorn", "alembic", "sqlalchemy", "aiosqlite",
    "yt_dlp", "trafilatura", "tree_sitter", "cloudscraper", "pip",
]  # fmt: skip

# `av` and its dependants carry libx264/libx265 (GPL-2.0-or-later) inside their
# wheels, and Luminary ships Apache-2.0 -- they are installed after the fact as
# the `transcription` component, never bundled. `optimum`/`onnx` are simply
# unused; they cost ~49MB when they crept in.
# NOT sympy, though it is 72MB and arrives only as a torch dependency: `import
# torch` does not load it, but `import transformers` pulls `torch.fx`, which
# does. Dropping it broke transformers, sentence_transformers and gliner at once.
FORBIDDEN = ["av", "faster_whisper", "ctranslate2", "optimum", "onnx"]


def main() -> int:
    missing = []
    for module in REQUIRED:
        try:
            importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 -- any import failure is the finding
            missing.append(f"missing {module}: {type(exc).__name__}: {exc}")
    leaked = [f"{m} must not ship in the bundle" for m in FORBIDDEN if importlib.util.find_spec(m)]

    present = len(REQUIRED) - len(missing)
    print(f"    {present}/{len(REQUIRED)} required present, {len(FORBIDDEN)} excluded")
    if missing or leaked:
        print("\n".join("    " + line for line in missing + leaked), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
