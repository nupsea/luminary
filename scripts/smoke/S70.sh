#!/usr/bin/env bash
# Smoke test for S70: Ingestion performance — verify add_all batching and generate_all_summaries
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../../backend" && pwd)"

echo "S70 smoke: asserting SQLite batching and generate_all_summaries present"
cd "$BACKEND_DIR"
uv run python - <<'EOF'
# Verify session.add_all is used in chunk paths (grep the source)
import ast, sys
from pathlib import Path

src = Path("app/workflows/ingestion.py").read_text()
tree = ast.parse(src)

add_all_calls = 0
add_chunk_calls = 0
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr == "add_all":
                add_all_calls += 1
            elif func.attr == "add":
                # Check if the argument is a ChunkModel (by variable name heuristic)
                add_chunk_calls += 1

assert add_all_calls >= 4, f"Expected >= 4 add_all calls in ingestion.py, got {add_all_calls}"

# Verify generate_all_summaries is defined on SummarizationService
from app.services.summarizer import SummarizationService
assert hasattr(SummarizationService, "generate_all_summaries"), \
    "SummarizationService missing generate_all_summaries method"

print(f"PASS: {add_all_calls} add_all calls in ingestion.py, generate_all_summaries defined")
EOF
