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

# The pipeline was split into nodes: the chunk writes moved out of
# workflows/ingestion.py into workflows/ingestion_nodes/, so counting one file
# found zero and reported a regression in batching that had not happened. What
# matters is that chunks are inserted in batches somewhere in the pipeline, so
# the whole package is what gets counted.
node_files = sorted(Path("app/workflows/ingestion_nodes").glob("*.py"))
assert node_files, "no ingestion nodes found -- has the package moved again?"

add_all_calls = 0
for path in [Path("app/workflows/ingestion.py"), *node_files]:
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_all":
                add_all_calls += 1

assert add_all_calls >= 4, (
    f"Expected >= 4 add_all calls across the ingestion pipeline, got {add_all_calls}: "
    "a per-row session.add() per chunk is what this guards against"
)

# Verify generate_all_summaries is defined on SummarizationService
from app.services.summarizer import SummarizationService
assert hasattr(SummarizationService, "generate_all_summaries"), \
    "SummarizationService missing generate_all_summaries method"

print(f"PASS: {add_all_calls} add_all calls across the ingestion pipeline, generate_all_summaries defined")
EOF
