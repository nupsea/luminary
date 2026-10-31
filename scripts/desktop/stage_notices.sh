#!/usr/bin/env bash
# Stage THIRD-PARTY-LICENSES.txt. Runs after the payload and the runtime are staged,
# and fails when a shipped package has no licence text.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[ -x "$(staged_python)" ] || _die "stage the runtime first (stage_python.sh)"
[ -d "$STAGE/licenses" ] || _die "stage the payload first (stage_payload.sh)"

_step "Staging third-party licence notices"
third_party_notices
