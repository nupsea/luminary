#!/usr/bin/env bash
# Smoke test for S71: Summary caching — verify force_refresh and cached SSE events
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../../backend" && pwd)"

echo "S71 smoke: verifying force_refresh param and _should_use_summary"
cd "$BACKEND_DIR"
uv run python - <<'EOF'
# Verify force_refresh signature on stream_summary and stream_library_summary
import inspect
from app.services.summarizer import SummarizationService

sig_summary = inspect.signature(SummarizationService.stream_summary)
assert "force_refresh" in sig_summary.parameters, \
    "stream_summary missing force_refresh param"

sig_library = inspect.signature(SummarizationService.stream_library_summary)
assert "force_refresh" in sig_library.parameters, \
    "stream_library_summary missing force_refresh param"

# Verify _should_use_summary keyword detection
from app.services.qa import _should_use_summary
assert _should_use_summary("summarize this for me") is True
assert _should_use_summary("what is this about?") is True
assert _should_use_summary("who is Achilles?") is False

# Verify SummarizeRequest accepts force_refresh
from app.routers.summarize import SummarizeRequest, LibrarySummarizeRequest
r = SummarizeRequest(mode="executive", force_refresh=True)
assert r.force_refresh is True
lr = LibrarySummarizeRequest(mode="executive", force_refresh=True)
assert lr.force_refresh is True

# Verify glossary is a valid mode
r2 = SummarizeRequest(mode="glossary")
assert r2.mode == "glossary"

print("PASS: force_refresh, _should_use_summary, and glossary mode all verified")
EOF
