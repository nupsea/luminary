#!/usr/bin/env bash
# Smoke test for S74: LLM provider mode — Private/Cloud settings with encrypted API keys
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/../../backend" && pwd)"

echo "S74 smoke: verifying settings_service, routing, and router endpoints"
cd "$BACKEND_DIR"
uv run python - <<'EOF'
# Verify encrypt/decrypt round-trip
from app.services.settings_service import encrypt_setting, decrypt_setting

secret = "sk-test-1234567890"
encrypted = encrypt_setting(secret)
assert encrypted != secret, "encrypt_setting returned plaintext"
assert decrypt_setting(encrypted) == secret, "decrypt round-trip failed"

# Verify _cache defaults
import app.services.settings_service as svc
assert svc._cache["llm_mode"] == "private", f"default mode is not private: {svc._cache['llm_mode']}"
assert svc._cache["openai_api_key"] == "", "default key is not empty"

# Verify get_effective_routing private mode returns ollama/ prefix
svc._cache["llm_mode"] = "private"
model, key = svc.get_effective_routing()
assert model.startswith("ollama/"), f"private mode should return ollama/ prefix, got: {model}"
assert key is None, "private mode should return None api_key"

# Verify get_effective_routing raises ValueError for cloud + no key
import pytest
svc._cache["llm_mode"] = "cloud"
svc._cache["cloud_provider"] = "openai"
svc._cache["openai_api_key"] = ""
try:
    svc.get_effective_routing()
    assert False, "Expected ValueError not raised"
except ValueError as e:
    assert "key not configured" in str(e), f"Unexpected error: {e}"

# Verify route returns key when encrypted key present
svc._cache["openai_api_key"] = encrypt_setting("sk-real-key")
model2, key2 = svc.get_effective_routing()
assert model2.startswith("openai/"), f"cloud openai should have openai/ prefix, got: {model2}"
assert key2 == "sk-real-key", "decrypted key mismatch"

# Restore defaults
svc._cache.update(svc._DEFAULTS)

# Verify GET /settings/llm is registered
from app.main import app
routes = {r.path for r in app.routes}  # type: ignore[attr-defined]
assert "/settings/llm" in routes, f"/settings/llm not registered. Routes: {routes}"

# Verify PATCH /settings/llm is registered
methods = {}
for r in app.routes:  # type: ignore[attr-defined]
    if hasattr(r, "path") and r.path == "/settings/llm":
        methods.update({m: True for m in getattr(r, "methods", [])})
assert "PATCH" in methods, "PATCH /settings/llm not found"

print("PASS: S74 settings_service encryption, routing, and endpoints all verified")
EOF
