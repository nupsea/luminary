#!/usr/bin/env bash
# Smoke test for S72: Monitoring tab — Arize Phoenix distributed tracing link
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../../backend" && pwd)"

echo "S72 smoke: verifying GET /monitoring/phoenix-url endpoint"
cd "$BACKEND_DIR"
uv run python - <<'EOF'
# Verify PhoenixUrlResponse exists and has expected fields
from app.routers.monitoring import PhoenixUrlResponse

r = PhoenixUrlResponse(url="http://localhost:6006", enabled=False)
assert r.url == "http://localhost:6006"
assert r.enabled is False

r2 = PhoenixUrlResponse(url="http://localhost:6006", enabled=True)
assert r2.enabled is True

# Verify the endpoint is registered
from app.main import app
routes = [r.path for r in app.routes]
assert "/monitoring/phoenix-url" in routes, \
    f"/monitoring/phoenix-url not in routes: {routes}"

# Verify _check_phoenix_reachable_cached exists and is callable
from app.routers.monitoring import _check_phoenix_reachable_cached
import inspect
assert inspect.iscoroutinefunction(_check_phoenix_reachable_cached)

print("PASS: /monitoring/phoenix-url endpoint and PhoenixUrlResponse verified")
EOF
