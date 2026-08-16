#!/usr/bin/env bash
# Smoke test for S232: the registry knows what this machine can hold.
#
# The defect this guards: `min_ram_gb` and `resident_bytes` sat on every model
# registry entry and nothing read them, so a 10GB model was selectable on a 16GB
# laptop and the first symptom was a crash during ingestion. Three numbers were
# each knowable and never put together -- host RAM, how many distinct models the
# four roles resolve to, and what those models weigh.
#
# Verifies:
#   1. backend is healthy
#   2. GET /settings/models reports profile, host RAM and the resident footprint
#   3. the resident count is DISTINCT models, not roles (four roles on one model
#      cost one runner, I-31)
#   4. a configuration exceeding the residency limit or the host is reported,
#      not silently served
#   5. GET /settings/models/catalogue is smallest-first and flags what does not fit

set -euo pipefail

BASE="${BASE:-http://localhost:7820}"

fail() {
  echo "FAIL: $1"
  exit 1
}

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/health")
[ "$HTTP" = "200" ] || fail "backend not healthy (got ${HTTP})"

curl -s "${BASE}/settings/models" | python3 -c "
import sys, json
d = json.load(sys.stdin)

for key in ('profile', 'host_ram_gb', 'roles', 'resident_models', 'resident_count',
            'max_resident', 'within_residency_limit', 'resident_gb',
            'oversized_models', 'unmeasured_models'):
    assert key in d, f'/settings/models missing {key}'

assert d['profile'] in ('low', 'standard', 'performance'), d['profile']
assert len(d['roles']) == 4, f\"expected 4 roles, got {sorted(d['roles'])}\"

# Distinct models, never a count of roles.
assert d['resident_count'] == len(set(d['resident_models'])), (
    f\"resident_count {d['resident_count']} != distinct models {d['resident_models']}\"
)
assert d['resident_count'] <= len(d['roles']), 'more resident models than roles'

# The footprint must be at least as large as the biggest single resident model,
# or the sum is not being taken over what is actually loaded.
if d['resident_models'] and not d['unmeasured_models']:
    biggest = max((r['resident_gb'] or 0) for r in d['roles'].values())
    assert d['resident_gb'] >= biggest, (
        f\"footprint {d['resident_gb']}GB is below the largest resident model {biggest}GB\"
    )

print(f\"  profile {d['profile']} on {d['host_ram_gb']}GB host\")
print(f\"  {d['resident_count']}/{d['max_resident']} models resident, {d['resident_gb']}GB\")
if not d['within_residency_limit']:
    print(f\"  OVER RESIDENCY LIMIT: {d['resident_models']}\")
if d['oversized_models']:
    print(f\"  OVERSIZED FOR THIS HOST: {d['oversized_models']}\")
if d['unmeasured_models']:
    print(f\"  unmeasured (no registry entry): {d['unmeasured_models']}\")
if not d['profile_suits_host']:
    print(f\"  profile {d['profile']} is larger than this machine\")
" || fail "GET /settings/models did not report a usable residency picture"

curl -s "${BASE}/settings/models/catalogue" | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert isinstance(d, list) and d, 'catalogue is empty'

sizes = [e['resident_gb'] for e in d]
assert sizes == sorted(sizes), f'catalogue is not smallest-first: {sizes}'
for e in d:
    for key in ('id', 'min_ram_gb', 'licence', 'fits_host', 'accommodations_measured'):
        assert key in e, f'catalogue entry missing {key}'

fits = [e['id'] for e in d if e['fits_host']]
print(f'  catalogue: {len(d)} model(s), {len(fits)} fit this host')
for e in d:
    mark = ' ' if e['fits_host'] else '!'
    measured = 'measured' if e['accommodations_measured'] else 'unmeasured'
    print(f\"  {mark} {e['id']:<32} {e['resident_gb']:>5}GB  needs {e['min_ram_gb']}GB  {measured}\")
" || fail "GET /settings/models/catalogue did not list the registry"

echo "PASS: S232 -- the registry answers what this machine can hold"
