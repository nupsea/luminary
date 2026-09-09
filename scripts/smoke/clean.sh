#!/usr/bin/env bash
# Remove the library rows the smoke suite creates.
#
# Eight runs' worth had accumulated in a real library before this existed: 27
# documents and 30 notes, because every fixture-creating script ingests and
# nothing deletes.
#
# **It only ever removes rows created after a timestamp.** Matching on the marker
# alone would be a trap: S123's fixture is titled "A Brief History of Time", which
# is also a book somebody may genuinely own, and S122's is a real YouTube video.
# A window makes "this run made it" the deciding fact and the title merely the
# filter. With no window it refuses rather than guessing.
#
# Deletion goes through the API, never SQLite: a row removed behind the app's back
# leaves its LanceDB vectors and Kuzu nodes orphaned, and the vectors keep
# answering searches.
#
#   scripts/smoke/clean.sh --since 2026-09-06T00:00:00Z
#   scripts/smoke/clean.sh --dry-run          # uses .last-run, written by all.sh
set -euo pipefail

BASE="${BASE:-http://localhost:7820}"
HERE="$(cd "$(dirname "$0")" && pwd)"
LAST_RUN_FILE="$HERE/.last-run"
SINCE="${SINCE:-}"
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --since) SINCE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$SINCE" ] && [ -f "$LAST_RUN_FILE" ]; then
  SINCE="$(cat "$LAST_RUN_FILE")"
fi

if [ -z "$SINCE" ]; then
  echo "FAIL: no window to clean within." >&2
  echo "  Pass --since <ISO8601-UTC>, or run the suite once so all.sh records one." >&2
  echo "  Refusing to match on fixture titles alone: 'A Brief History of Time' is" >&2
  echo "  a real book, and deleting a library row on a name collision is worse" >&2
  echo "  than leaving a test artifact behind." >&2
  exit 2
fi

HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE/health" || true)
if [ "$HTTP" != "200" ]; then
  echo "FAIL: no backend on $BASE (health returned $HTTP)" >&2
  exit 1
fi

echo "=== smoke-clean: removing fixtures created at or after $SINCE ==="
[ "$DRY_RUN" -eq 1 ] && echo "(dry run — nothing will be deleted)"

BASE="$BASE" SINCE="$SINCE" DRY_RUN="$DRY_RUN" python3 - <<'PY'
import json, os, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE = os.environ["BASE"].rstrip("/")
DRY_RUN = os.environ["DRY_RUN"] == "1"

# Each marker names the script that creates it, so an obsolete entry is traceable
# to the script that stopped needing it. Documents match on an exact title or a
# prefix; notes on the exact body the script posts.
DOC_TITLES = {
    "Rick Astley - Never Gonna Give You Up": "S122 (ingest-url, dQw4w9WgXcQ)",
    "A Brief History of Time": "S123/S241 (ingest-kindle, synthetic My_Clippings.txt)",
    "smoke_s62": "S62",
    "s86_smoke_fixture": "S86",
    "s182_smoke": "S182",
}
NOTE_BODIES = {
    "S106 smoke note": "S106",
    "S172 smoke test note: backpropagation gradient descent neural network.": "S172",
    "Smoke test note for collection health": "S173",
    "Test note for S201 smoke": "S201",
}


def parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


since = parse(os.environ["SINCE"])


def get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as r:
        return json.load(r)


def delete(path: str) -> int:
    if DRY_RUN:
        return 204
    req = urllib.request.Request(f"{BASE}{path}", method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def all_documents():
    # page_size caps at 100, so a library larger than that needs every page or the
    # cleaner silently misses the fixtures sitting past the first one.
    page, out = 1, []
    while True:
        data = get(f"/documents?page={page}&page_size=100&sort=newest")
        items = data.get("items", [])
        out.extend(items)
        if len(out) >= data.get("total", len(out)) or not items:
            return out
        page += 1


doomed_docs, doomed_notes = [], []
for doc in all_documents():
    for marker, owner in DOC_TITLES.items():
        if doc["title"].startswith(marker) and parse(doc["created_at"]) >= since:
            doomed_docs.append((doc["id"], doc["title"], owner))
            break

for note in get("/notes"):
    body = (note.get("content") or "").strip()
    owner = NOTE_BODIES.get(body)
    if owner and parse(note["created_at"]) >= since:
        doomed_notes.append((note["id"], body, owner))

for ident, label, owner in doomed_notes:
    code = delete(f"/notes/{ident}")
    print(f"  note     [{owner:5}] {code} {label[:56]!r}")
for ident, label, owner in doomed_docs:
    code = delete(f"/documents/{ident}")
    print(f"  document [{owner.split()[0]:5}] {code} {label[:56]!r}")

print(f"\nsmoke-clean: {len(doomed_notes)} note(s), {len(doomed_docs)} document(s)"
      f"{' would be' if DRY_RUN else ''} removed")
PY

echo "=== smoke-clean: done ==="
