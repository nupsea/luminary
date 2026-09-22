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
    "yt_dlp", "trafilatura", "tree_sitter", "cloudscraper", "pip", "zstandard",
]  # fmt: skip

# `av` carries GPL codecs and ships as the `transcription` component; optimum/onnx are unused.
# NOT sympy: `import transformers` pulls torch.fx, which imports it.
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
